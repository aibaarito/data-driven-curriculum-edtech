"""Decision-intelligence API: evidence context, passports, curriculum graph, decisions, scenarios, interventions.

Every response that carries a conclusion also carries ``context`` (fingerprint, dataset revision, scope, algorithm
version, synthetic flag). Preview endpoints never write; save endpoints recompute on the server, refuse stale
fingerprints and are idempotent.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import models as m
from app.api.deps import DB, FiltersDep
from app.api.routes import _optimizer_input
from app.api.schemas import (
    EdgeReviewBody,
    InterventionCreate,
    InterventionTransition,
    OptimizerRunBody,
    PrerequisiteBody,
    ScenarioSaveBody,
)
from app.services import analytics as an
from app.services import curriculum_graph as cg
from app.services import decisions as dec
from app.services import evidence as evd
from app.services import interventions as iv
from app.services.context import build_context
from app.services.optimizer import InfeasibleError, optimize
from app.services.scenarios import build_scenarios
from app.services.settings_store import get_analysis_settings

router = APIRouter(prefix="/api")
log = logging.getLogger("ddc.decisions")


def _err(status: int, code: str, message: str, details: list[str] | None = None, **extra: Any) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message, "details": details or [], **extra})


# --------------------------------------------------------------------------- shared scope analysis


def scope_analysis(db, subject_id: int, grade: int | None) -> dict[str, Any]:
    if db.get(m.Subject, subject_id) is None:
        raise _err(404, "SUBJECT_NOT_FOUND", "Предмет не найден.")
    s = get_analysis_settings(db)
    f = an.Filters(subject_id=subject_id, grade=grade)
    df = an.load_results(db, f)
    topics = an.topic_analytics(df, s, an.mean_hours_by_topic(db, f))
    g = cg.load_graph(db, subject_id)
    graph = cg.diagnose(g, {t["topic_id"]: t for t in topics}, s, grade)
    scope = {"subject_id": subject_id, "grade": grade, "view": "grade_plan"} if grade is not None else \
        {"subject_id": subject_id, "grade": None, "view": "subject"}
    meta = evd.context_metadata(db, s, scope)
    return {"settings": s, "df": df, "topics": topics, "graph": graph, "meta": meta}


def current_plan_fingerprint(db, subject_id: int, grade: int) -> str:
    return evd.plan_context(db, get_analysis_settings(db), subject_id, grade)["fingerprint"]


def run_summary(r: m.RecommendationRun, current_fp: str | None) -> dict[str, Any]:
    stale = None if r.evidence_fingerprint is None or current_fp is None else r.evidence_fingerprint != current_fp
    return {"run_id": r.id, "status": r.status, "created_at": r.created_at.isoformat(), "grade": r.grade,
            "subject_id": r.subject_id, "total_hours": r.result["total_hours"], "scenario_key": r.scenario_key,
            "changed_topics": sum(1 for x in r.result["rows"] if x["delta"] != 0),
            "decided_at": r.decided_at.isoformat() if r.decided_at else None, "review_note": r.review_note,
            "evidence_fingerprint": r.evidence_fingerprint,
            "evidence_status": "unknown" if stale is None else ("stale" if stale else "current")}


def audit(db, entity_type: str, entity_id: int, action: str, from_status: str | None, to_status: str | None,
          **detail: Any) -> None:
    db.add(m.AuditEvent(entity_type=entity_type, entity_id=entity_id, action=action, from_status=from_status,
                        to_status=to_status, detail=detail))


# --------------------------------------------------------------------------- context & evidence


@router.get("/context")
def analysis_context(db: DB, f: FiltersDep) -> dict[str, Any]:
    s = get_analysis_settings(db)
    return evd.context_metadata(db, s, f.as_dict() | {"view": "analysis"})


@router.get("/evidence/topics/{topic_id}")
def topic_evidence(db: DB, topic_id: int, f: FiltersDep) -> dict[str, Any]:
    topic = db.get(m.Topic, topic_id)
    if topic is None:
        raise _err(404, "TOPIC_NOT_FOUND", "Тема не найдена.")
    if f.subject_id is not None and f.subject_id != topic.subject_id:
        raise _err(422, "SCOPE_MISMATCH", "Тема не относится к выбранному предмету; доказательства из другого среза "
                                          "не смешиваются.")
    if f.grade is not None and f.grade != topic.grade:
        raise _err(422, "SCOPE_MISMATCH", "Тема не относится к выбранной параллели.")
    s = get_analysis_settings(db)
    # The passport is computed for exactly the requested scope (subject and grade of the topic are pinned).
    scoped = an.Filters(topic.subject_id, topic.grade, f.class_id, f.textbook_id, f.date_from, f.date_to)
    df = an.load_results(db, scoped)
    topics = an.topic_analytics(df, s, an.mean_hours_by_topic(db, scoped))
    row = next((t for t in topics if t["topic_id"] == topic_id), None)
    meta = evd.context_metadata(db, s, scoped.as_dict() | {"view": "topic"})
    if row is None:
        row = {"topic_id": topic.id, "code": topic.code, "name": topic.name, "grade": topic.grade, "mastery": None,
               "student_count": 0, "class_count": 0, "assessment_count": 0, "gain": None, "status": "no_outcome_data",
               "interpretation": an.INTERPRETATION_RU["no_outcome_data"], "interpretation_code": "no_outcome_data"}
    graph = cg.diagnose(cg.load_graph(db, topic.subject_id), {t["topic_id"]: t for t in topics}, s, topic.grade)
    node = next((n for n in graph["nodes"] if n["topic_id"] == topic_id), None)
    cands = dec.topic_candidates([row], s, meta["fingerprint"], {n["topic_id"]: n for n in graph["nodes"]})
    return {"context": meta, "passport": evd.topic_passport(row, s, meta, node, cands[0] if cands else None),
            "decision": cands[0] if cands else None}


@router.get("/evidence/textbooks")
def textbook_evidence(db: DB, f: FiltersDep) -> dict[str, Any]:
    ctx = build_context(db, an.Filters(f.subject_id, f.grade, None, None, f.date_from, f.date_to), include_run=False)
    s = get_analysis_settings(db)
    meta = evd.context_metadata(db, s, {"subject_id": f.subject_id, "grade": f.grade, "date_from": f.date_from,
                                        "date_to": f.date_to, "view": "textbooks"})
    return {"context": meta, "passports": [evd.textbook_passport(p, meta) for p in ctx["textbooks"]["pairs"]]}


# --------------------------------------------------------------------------- curriculum graph


@router.get("/curriculum/graph")
def curriculum_graph(db: DB, subject_id: int, grade: int | None = None) -> dict[str, Any]:
    if grade is not None and not 1 <= grade <= 12:
        raise _err(422, "INVALID_SCOPE", "Параллель должна быть от 1 до 12.")
    a = scope_analysis(db, subject_id, grade)
    return {"context": a["meta"], **a["graph"]}


@router.post("/curriculum/prerequisites", status_code=201)
def add_prerequisite(db: DB, body: PrerequisiteBody) -> dict[str, Any]:
    topic, pre = db.get(m.Topic, body.topic_id), db.get(m.Topic, body.prerequisite_id)
    if topic is None or pre is None:
        raise _err(404, "TOPIC_NOT_FOUND", "Тема или пререквизит не найдены.")
    if topic.subject_id != pre.subject_id:
        raise _err(422, "GRAPH_INVALID", "Пререквизит относится к другому предмету.",
                   [f"«{pre.name}» и «{topic.name}» — разные предметы."], issues=[{"code": "CROSS_SUBJECT"}])
    g = cg.load_graph(db, topic.subject_id)
    if any(e.prerequisite_id == pre.id and e.topic_id == topic.id and e.review_status != "rejected" for e in g.edges):
        raise _err(409, "DUPLICATE_EDGE", "Такая связь уже есть.")
    issues = [i for i in cg.check_new_edge(g, pre.id, topic.id) if i["code"] != "GRADE_ORDER"]
    if issues:
        raise _err(422, "GRAPH_INVALID", "Связь нарушает структуру графа пререквизитов.",
                   [i["message"] for i in issues], issues=issues)
    status = "approved" if body.origin == "expert" else "pending"
    edge = m.TopicPrerequisite(topic_id=topic.id, prerequisite_id=pre.id, origin=body.origin, review_status=status)
    db.add(edge)
    db.flush()
    audit(db, "prerequisite", edge.id, "create", None, status, origin=body.origin)
    db.commit()
    return {"id": edge.id, "topic_id": topic.id, "prerequisite_id": pre.id, "origin": edge.origin,
            "review_status": edge.review_status}


@router.post("/curriculum/prerequisites/{edge_id}/review")
def review_prerequisite(db: DB, edge_id: int, body: EdgeReviewBody) -> dict[str, Any]:
    edge = db.get(m.TopicPrerequisite, edge_id)
    if edge is None:
        raise _err(404, "EDGE_NOT_FOUND", "Связь не найдена.")
    if edge.review_status != "pending":
        raise _err(409, "INVALID_TRANSITION", "Проверять можно только связи в статусе «на проверке».")
    if body.decision == "approve":
        topic = db.get(m.Topic, edge.topic_id)
        g = cg.load_graph(db, topic.subject_id)
        g.edges = [e for e in g.edges if e.id != edge.id]
        issues = [i for i in cg.check_new_edge(g, edge.prerequisite_id, edge.topic_id) if i["code"] != "GRADE_ORDER"]
        if issues:
            raise _err(422, "GRAPH_INVALID", "Одобрение создаст некорректный граф.", [i["message"] for i in issues],
                       issues=issues)
    new = "approved" if body.decision == "approve" else "rejected"
    audit(db, "prerequisite", edge.id, "review", edge.review_status, new)
    edge.review_status = new
    db.commit()
    return {"id": edge.id, "review_status": edge.review_status}


@router.delete("/curriculum/prerequisites/{edge_id}")
def delete_prerequisite(db: DB, edge_id: int) -> dict[str, Any]:
    edge = db.get(m.TopicPrerequisite, edge_id)
    if edge is None:
        raise _err(404, "EDGE_NOT_FOUND", "Связь не найдена.")
    audit(db, "prerequisite", edge.id, "delete", edge.review_status, None, topic_id=edge.topic_id,
          prerequisite_id=edge.prerequisite_id)
    db.delete(edge)
    db.commit()
    return {"deleted": edge_id}


# --------------------------------------------------------------------------- scenarios


def _scenarios(db, body: OptimizerRunBody) -> dict[str, Any]:
    a = scope_analysis(db, body.subject_id, body.grade)
    base, s = _optimizer_input(db, body)
    evidence = {t["topic_id"]: evd.assess_topic(t, s)["category"] for t in a["topics"]}
    weak_down = {n["topic_id"]: len(n["weak_downstream"]) for n in a["graph"]["nodes"]}
    scenarios = build_scenarios(base, evidence, weak_down)
    names = {t.topic_id: t.name for t in base.topics}
    table = []
    for t in base.topics:
        row: dict[str, Any] = {"topic_id": t.topic_id, "name": names[t.topic_id], "current_hours": t.current_hours,
                               "min_hours": t.min_hours, "max_hours": t.max_hours, "locked": t.locked,
                               "mastery": t.mastery, "evidence": evidence.get(t.topic_id, "insufficient"),
                               "scenarios": {}}
        for sc in scenarios:
            if sc["ok"]:
                r = next(x for x in sc["result"]["rows"] if x["topic_id"] == t.topic_id)
                row["scenarios"][sc["key"]] = {"proposed": r["proposed_hours"], "delta": r["delta"]}
        table.append(row)
    return {"analysis": a, "base": base, "scenarios": scenarios, "table": table}


@router.post("/optimizer/scenarios/preview")
def scenarios_preview(db: DB, body: OptimizerRunBody) -> dict[str, Any]:
    """Compute three alternative plans. Nothing is written to the database."""
    out = _scenarios(db, body)
    a, base = out["analysis"], out["base"]
    return {"context": a["meta"], "fingerprint": a["meta"]["fingerprint"], "persisted": False,
            "baseline": {"total_hours": round(sum(t.current_hours for t in base.topics), 2),
                         "requested_total": base.total_hours, "target_mastery": base.target_mastery,
                         "max_change_pct": base.max_change_pct},
            "scenarios": out["scenarios"], "comparison": out["table"],
            "graph": {"foundational_gaps": a["graph"]["foundational_gaps"], "chains": a["graph"]["chains"][:3]}}


@router.post("/optimizer/scenarios/save", status_code=201)
def scenarios_save(db: DB, body: ScenarioSaveBody) -> Any:
    existing = db.scalar(select(m.RecommendationRun).where(m.RecommendationRun.idempotency_key == body.idempotency_key))
    if existing is not None:
        if (existing.subject_id, existing.grade, existing.scenario_key) != (body.subject_id, body.grade,
                                                                              body.scenario_key):
            raise _err(409, "IDEMPOTENCY_CONFLICT", "Ключ идемпотентности уже использован для другого сохранения.")
        cur = current_plan_fingerprint(db, body.subject_id, body.grade)
        return {**run_summary(existing, cur), "idempotent_replay": True, "result": existing.result}
    out = _scenarios(db, body)
    a = out["analysis"]
    fp = a["meta"]["fingerprint"]
    if body.fingerprint != fp:
        raise _err(409, "STALE_SCENARIO", "Данные или настройки изменились после предпросмотра. Пересчитайте "
                                          "сценарии перед сохранением.", current_fingerprint=fp)
    sc = next(x for x in out["scenarios"] if x["key"] == body.scenario_key)
    if not sc["ok"]:
        raise _err(422, sc["error"]["code"], sc["error"]["message"], sc["error"]["details"])
    params = body.model_dump(mode="json", exclude={"fingerprint", "idempotency_key"})
    result = sc["result"] | {"scenario": {k: sc[k] for k in ("key", "label", "goal", "parameters")}}
    run = m.RecommendationRun(subject_id=body.subject_id, grade=body.grade, status="proposed",
                              params=params | {"input": out["base"].model_dump()}, result=result,
                              scenario_key=body.scenario_key, evidence_fingerprint=fp,
                              evidence_snapshot=evd.evidence_snapshot(a["meta"], a["topics"], a["settings"]),
                              idempotency_key=body.idempotency_key)
    db.add(run)
    try:
        db.flush()
        audit(db, "recommendation", run.id, "save_scenario", None, "proposed", scenario=body.scenario_key)
        db.commit()
    except IntegrityError:  # concurrent retry with the same key: return the committed one
        db.rollback()
        existing = db.scalar(select(m.RecommendationRun)
                             .where(m.RecommendationRun.idempotency_key == body.idempotency_key))
        if existing is None:
            raise
        return {**run_summary(existing, fp), "idempotent_replay": True, "result": existing.result}
    return {**run_summary(run, fp), "idempotent_replay": False, "result": run.result}


@router.get("/optimizer/runs/{run_id}")
def optimizer_run_detail(db: DB, run_id: int) -> dict[str, Any]:
    run = db.get(m.RecommendationRun, run_id)
    if run is None:
        raise _err(404, "RUN_NOT_FOUND", "Рекомендация не найдена.")
    cur = current_plan_fingerprint(db, run.subject_id, run.grade)
    events = db.scalars(select(m.AuditEvent).where(m.AuditEvent.entity_type == "recommendation",
                                                   m.AuditEvent.entity_id == run.id).order_by(m.AuditEvent.id)).all()
    return {**run_summary(run, cur), "result": run.result, "evidence_snapshot": run.evidence_snapshot,
            "audit": [_event(e) for e in events]}


def _event(e: m.AuditEvent) -> dict[str, Any]:
    return {"action": e.action, "from": e.from_status, "to": e.to_status, "at": e.created_at.isoformat(),
            "detail": e.detail}


# --------------------------------------------------------------------------- decision center


@router.get("/decisions/overview")
def decisions_overview(db: DB, subject_id: int, grade: int) -> dict[str, Any]:
    if not 1 <= grade <= 12:
        raise _err(422, "INVALID_SCOPE", "Параллель должна быть от 1 до 12.")
    a = scope_analysis(db, subject_id, grade)
    s, meta, graph = a["settings"], a["meta"], a["graph"]
    plan_rows: dict[int, dict[str, Any]] = {}
    sensitivity: dict[str, dict[int, float] | None] = {}
    plan_info: dict[str, Any] = {"available": False}
    total = None
    try:
        body = OptimizerRunBody(subject_id=subject_id, grade=grade, total_hours=1)
        base, _ = _optimizer_input(db, body)
        total = round(sum(t.current_hours for t in base.topics) * 2) / 2
        if total > 0:
            base = base.model_copy(update={"total_hours": total})
            res = optimize(base)
            plan_rows = {r["topic_id"]: r for r in res["rows"]}
            plan_info = {"available": True, "total_hours": total, "constraints_ok": all(c["ok"] for c in
                                                                                       res["constraints"])}
            for label, delta in (("minus_2h", -2.0), ("plus_2h", 2.0)):
                try:
                    r2 = optimize(base.model_copy(update={"total_hours": total + delta}))
                    sensitivity[label] = {r["topic_id"]: r["proposed_hours"] for r in r2["rows"]}
                except InfeasibleError as exc:
                    sensitivity[label] = None
                    plan_info.setdefault("sensitivity_notes", []).append(
                        f"При {total + delta:g} ч: {exc} ({exc.code}).")
    except (HTTPException, InfeasibleError, ValueError) as exc:
        plan_info = {"available": False, "reason": getattr(exc, "detail", None) or str(exc)}
    nodes = {n["topic_id"]: n for n in graph["nodes"]}
    candidates = dec.topic_candidates(a["topics"], s, meta["fingerprint"], nodes, plan_rows,
                                      sensitivity if plan_rows else None)
    tb = build_context(db, an.Filters(subject_id=subject_id, grade=grade), include_run=False)["textbooks"]
    candidates += dec.textbook_candidates(tb["pairs"], meta["fingerprint"])
    runs = db.scalars(select(m.RecommendationRun).where(m.RecommendationRun.subject_id == subject_id,
                                                        m.RecommendationRun.grade == grade)
                      .order_by(m.RecommendationRun.created_at.desc(), m.RecommendationRun.id.desc()).limit(20)).all()
    plan_fp = meta["fingerprint"]
    run_list = [run_summary(r, plan_fp) for r in runs]
    ivs = db.scalars(select(m.Intervention).where(m.Intervention.subject_id == subject_id,
                                                  m.Intervention.grade == grade)
                     .order_by(m.Intervention.created_at.desc(), m.Intervention.id.desc())).all()
    return {
        "context": meta,
        "readiness": dec.readiness_summary(a["topics"], s),
        "candidates": candidates,
        "actionable": sum(1 for c in candidates if c["evidence"]["allows_action"]),
        "graph": {"valid": graph["valid"], "issues": graph["issues"], "foundational_gaps": [
            {"topic_id": i, "name": nodes[i]["name"]} for i in graph["foundational_gaps"]],
            "chains": graph["chains"][:3], "ranking": graph["ranking"][:5]},
        "plan": plan_info,
        "pending_approvals": [r for r in run_list if r["status"] == "proposed"],
        "approved": [r for r in run_list if r["status"] == "accepted"],
        "rejected": [r for r in run_list if r["status"] == "rejected"],
        "interventions": [_intervention_dict(x, plan_fp) for x in ivs],
    }


# --------------------------------------------------------------------------- interventions


def _intervention_dict(x: m.Intervention, current_fp: str | None = None) -> dict[str, Any]:
    fp = (x.baseline or {}).get("fingerprint")
    return {"id": x.id, "run_id": x.run_id, "subject_id": x.subject_id, "grade": x.grade, "status": x.status,
            "status_label": iv.STATUS_RU.get(x.status, x.status), "description": x.description,
            "reviewer": x.reviewer, "planned_on": x.planned_on.isoformat() if x.planned_on else None,
            "implemented_on": x.implemented_on.isoformat() if x.implemented_on else None,
            "baseline": x.baseline, "evaluation": x.evaluation, "synthetic": x.synthetic,
            "allowed_transitions": sorted(iv.TRANSITIONS.get(x.status, set())),
            "created_at": x.created_at.isoformat() if x.created_at else None,
            "baseline_status": None if current_fp is None or fp is None else ("current" if fp == current_fp
                                                                               else "superseded")}


@router.post("/interventions", status_code=201)
def create_intervention(db: DB, body: InterventionCreate) -> dict[str, Any]:
    run = db.get(m.RecommendationRun, body.run_id, with_for_update=True)
    if run is None:
        raise _err(404, "RUN_NOT_FOUND", "Рекомендация не найдена.")
    if run.status != "accepted":
        raise _err(409, "INVALID_TRANSITION", "Вмешательство можно запланировать только по принятой рекомендации "
                                              f"(текущий статус: {run.status}).")
    existing = db.scalar(select(m.Intervention).where(m.Intervention.run_id == run.id))
    if existing is not None:
        raise _err(409, "ALREADY_EXISTS", "Для этой рекомендации вмешательство уже создано.",
                   intervention_id=existing.id)
    if run.evidence_snapshot:  # freeze exactly the evidence the run was approved on
        snap = run.evidence_snapshot
        meta = {**snap["context"]}
        topics = snap["topics"]
    else:  # legacy run without a snapshot: freeze the evidence available now and say so
        a = scope_analysis(db, run.subject_id, run.grade)
        meta, topics = a["meta"], a["topics"]
    baseline = iv.frozen_baseline(run.result, topics, meta)
    baseline["source"] = "run_snapshot" if run.evidence_snapshot else "captured_at_planning (legacy run)"
    synthetic = body.synthetic or bool(meta.get("synthetic"))
    x = m.Intervention(run_id=run.id, subject_id=run.subject_id, grade=run.grade, status="planned",
                       description=body.description, reviewer=body.reviewer, planned_on=body.planned_on,
                       baseline=baseline, synthetic=synthetic)
    db.add(x)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise _err(409, "ALREADY_EXISTS", "Для этой рекомендации вмешательство уже создано.") from exc
    audit(db, "intervention", x.id, "create", None, "planned", run_id=run.id)
    db.commit()
    return _intervention_dict(x)


@router.get("/interventions")
def list_interventions(db: DB, subject_id: int | None = None, grade: int | None = None) -> list[dict[str, Any]]:
    q = select(m.Intervention).order_by(m.Intervention.created_at.desc(), m.Intervention.id.desc()).limit(50)
    if subject_id is not None:
        q = q.where(m.Intervention.subject_id == subject_id)
    if grade is not None:
        q = q.where(m.Intervention.grade == grade)
    return [_intervention_dict(x) for x in db.scalars(q)]


@router.get("/interventions/{intervention_id}")
def get_intervention(db: DB, intervention_id: int) -> dict[str, Any]:
    x = db.get(m.Intervention, intervention_id)
    if x is None:
        raise _err(404, "INTERVENTION_NOT_FOUND", "Вмешательство не найдено.")
    events = db.scalars(select(m.AuditEvent).where(m.AuditEvent.entity_type == "intervention",
                                                   m.AuditEvent.entity_id == x.id).order_by(m.AuditEvent.id)).all()
    return _intervention_dict(x, current_plan_fingerprint(db, x.subject_id, x.grade)) | {
        "audit": [_event(e) for e in events]}


@router.post("/interventions/{intervention_id}/transition")
def transition_intervention(db: DB, intervention_id: int, body: InterventionTransition) -> dict[str, Any]:
    x = db.get(m.Intervention, intervention_id, with_for_update=True)
    if x is None:
        raise _err(404, "INTERVENTION_NOT_FOUND", "Вмешательство не найдено.")
    try:
        iv.check_transition(x.status, body.status)
    except iv.TransitionError as exc:
        raise _err(409, exc.code, str(exc)) from exc
    if body.status == "implemented":
        if body.implemented_on is None:
            raise _err(422, "MISSING_DATE", "Укажите фактическую дату внедрения.")
        if body.implemented_on > date.today():
            raise _err(422, "INVALID_DATE", "Дата внедрения не может быть в будущем.")
        x.implemented_on = body.implemented_on
    audit(db, "intervention", x.id, "transition", x.status, body.status)
    x.status = body.status
    x.updated_at = datetime.now(timezone.utc)
    db.commit()
    return _intervention_dict(x)


@router.post("/interventions/{intervention_id}/evaluate")
def evaluate_intervention(db: DB, intervention_id: int) -> dict[str, Any]:
    x = db.get(m.Intervention, intervention_id, with_for_update=True)
    if x is None:
        raise _err(404, "INTERVENTION_NOT_FOUND", "Вмешательство не найдено.")
    if x.status not in ("awaiting_outcome", "evaluated"):
        raise _err(409, "INVALID_TRANSITION", "Оценка доступна после внедрения и перевода в статус «Ожидает данных».")
    df = an.load_results(db, an.Filters(subject_id=x.subject_id, grade=x.grade))
    result = iv.evaluate(df, x.baseline, x.implemented_on)
    result["evaluated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result["synthetic"] = x.synthetic or evd.is_synthetic(db)
    x.evaluation = result
    if result["ready"] and x.status == "awaiting_outcome":
        audit(db, "intervention", x.id, "evaluate", x.status, "evaluated")
        x.status = "evaluated"
    else:
        audit(db, "intervention", x.id, "evaluate_attempt", x.status, x.status, ready=result["ready"])
    db.commit()
    return _intervention_dict(x)
