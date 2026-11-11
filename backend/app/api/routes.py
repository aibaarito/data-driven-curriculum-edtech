from __future__ import annotations

import io
import logging
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import SQLAlchemyError

from app import models as m
from app.api.deps import DB, FiltersDep
from app.api.schemas import (
    DecisionBody,
    EvaluateBody,
    FiltersBody,
    OptimizerRunBody,
    ReportBody,
    ResetBody,
    TopicUpdate,
)
from app.config import get_settings
from app.services import analytics as an
from app.services.ai import generate_insights
from app.services.context import build_context, filter_labels, topic_inputs_for
from app.services.import_store import ImportConflict, commit_rows, load_existing_state
from app.services.importer import (
    ALL_COLUMNS,
    REQUIRED_COLUMNS,
    FileFormatError,
    ValidationResult,
    read_table,
    rows_from_json,
    rows_to_json,
    validate_dataframe,
)
from app.services.optimizer import (
    InfeasibleError,
    OptimizerInput,
    TopicInput,
    check_allocation,
    check_policies,
    optimize,
)
from app.services.previews import COMMIT_LOCK_KEY, expiry_from_now, purge_expired
from app.security import token_matches
from app.services.integrity import run_integrity_checks
from app.services.report_summary import discussion_points, report_title
from app.services.report_pdf import render_pdf
from app.services.settings_store import (
    AnalysisSettings,
    get_analysis_settings,
    save_analysis_settings,
    settings_notices,
)

router = APIRouter(prefix="/api")
log = logging.getLogger("ddc.api")
DATA_DIR = Path(__file__).resolve().parent.parent / "assets" / "data"


# --------------------------------------------------------------------------- health & meta


@router.get("/health")
def health(db: DB, response: Response) -> dict[str, Any]:
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except SQLAlchemyError:
        db_ok = False
    response.status_code = 200 if db_ok else 503
    response.headers["Cache-Control"] = "no-store"
    return {"status": "ok" if db_ok else "degraded", "database": db_ok, "llm_enabled": get_settings().llm_enabled}


@router.get("/meta")
def meta(db: DB) -> dict[str, Any]:
    subjects = [{"id": s.id, "name": s.name} for s in db.scalars(select(m.Subject).order_by(m.Subject.name))]
    classes = [{"id": c.id, "name": c.name, "grade": c.grade}
               for c in db.scalars(select(m.SchoolClass).order_by(m.SchoolClass.grade, m.SchoolClass.name))]
    textbooks = [{"id": t.id, "code": t.code, "name": t.name, "subject_id": t.subject_id}
                 for t in db.scalars(select(m.Textbook).order_by(m.Textbook.code))]
    dmin, dmax = db.execute(select(func.min(m.Assessment.assessment_date), func.max(m.Assessment.assessment_date))).one()
    synthetic = any(code.upper().startswith("SYNTH") for code in db.scalars(select(m.School.code)))
    return {
        "subjects": subjects, "grades": sorted({c["grade"] for c in classes}), "classes": classes,
        "textbooks": textbooks, "date_from": dmin.isoformat() if dmin else None,
        "date_to": dmax.isoformat() if dmax else None, "synthetic": synthetic,
        "has_data": db.scalar(select(func.count()).select_from(m.AssessmentResult)) > 0,
    }


# --------------------------------------------------------------------------- analytics


def _opportunities(topics: list[dict[str, Any]], s: AnalysisSettings) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    hours = [t["hours"] for t in topics if t.get("hours") is not None]
    med = statistics.median(hours) if hours else None
    for t in topics:
        if t["status"] == "difficult":
            out.append({"type": "difficult_topic", "topic_id": t["topic_id"], "severity": "high",
                        "text": f"«{t['name']}»: освоение {t['mastery']}% — ниже порога {s.difficult_threshold:g}%."})
        elif t["status"] == "watch":
            out.append({"type": "watch_topic", "topic_id": t["topic_id"], "severity": "medium",
                        "text": f"«{t['name']}»: освоение {t['mastery']}% — ниже порога внимания {s.watch_threshold:g}%."})
        if (t.get("gain") or {}).get("direction") == "decline":
            g = t["gain"]
            out.append({"type": "decline", "topic_id": t["topic_id"], "severity": "high",
                        "text": f"«{t['name']}»: результат значимо снизился по сравнению с входной диагностикой "
                                f"({g['mean_gain']} п.п.). Нужен анализ причин; часы сами по себе снижение не устраняют."})
        if med is not None and t.get("hours") is not None and t["mastery"] is not None:
            if t["status"] in ("difficult", "watch") and t["hours"] < med:
                out.append({"type": "hours_review", "topic_id": t["topic_id"], "severity": "medium",
                            "text": f"«{t['name']}» получает {t['hours']} ч — меньше медианы по темам ({med:g} ч) при "
                                    "низком освоении. Распределение часов стоит пересмотреть."})
            elif t["status"] == "ok" and t["mastery"] >= s.target_mastery and t["hours"] > med * 1.25:
                out.append({"type": "hours_review", "topic_id": t["topic_id"], "severity": "low",
                            "text": f"«{t['name']}» получает {t['hours']} ч (медиана {med:g} ч) при освоении "
                                    f"{t['mastery']}% ≥ цели {s.target_mastery:g}% — возможен резерв часов."})
    return out


@router.get("/analytics/overview")
def analytics_overview(db: DB, f: FiltersDep) -> dict[str, Any]:
    ctx = build_context(db, f, include_run=False)
    s = AnalysisSettings(**ctx["settings"])
    topics = ctx["topics"]
    ranked = sorted([t for t in topics if t["mastery"] is not None and t["status"] != "insufficient_data"],
                    key=lambda t: t["mastery"])
    tb = ctx["textbooks"]
    return {
        "overview": ctx["overview"], "settings": ctx["settings"], "synthetic": ctx["synthetic"],
        "topics": [{k: t[k] for k in ("topic_id", "code", "name", "mastery", "student_count", "status", "hours")}
                   for t in topics],
        "difficult_topics": ranked[:5],
        "trend": ctx["trend"],
        "textbooks": [{k: x[k] for k in ("textbook_id", "name", "students", "classes", "mean", "baseline_mean")}
                      for x in tb["textbooks"]],
        "textbook_verdicts": [{k: p[k] for k in ("name_a", "name_b", "verdict", "verdict_text")} for p in tb["pairs"]],
        "opportunities": _opportunities(topics, s),
    }


@router.get("/analytics/topics")
def analytics_topics(db: DB, f: FiltersDep) -> dict[str, Any]:
    s = get_analysis_settings(db)
    df = an.load_results(db, f)
    hours = an.mean_hours_by_topic(db, f)
    return {"topics": an.topic_analytics(df, s, hours), "trends": an.topic_trends(df), "settings": s.model_dump()}


@router.get("/analytics/textbooks")
def analytics_textbooks(db: DB, f: FiltersDep) -> dict[str, Any]:
    ctx = build_context(db, f, include_run=False)
    return ctx["textbooks"] | {"settings": ctx["settings"]}


# --------------------------------------------------------------------------- import


@router.post("/imports/preview")
def import_preview(db: DB, file: UploadFile) -> dict[str, Any]:
    # Sync endpoint: FastAPI runs it in the thread pool, so parsing/validation never blocks the event loop.
    # BodySizeLimitMiddleware has already enforced the byte limit while the upload was being received.
    settings = get_settings()
    limit = settings.max_upload_bytes
    content = file.file.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(413, f"Файл больше {settings.max_upload_mb:g} МБ.")
    filename = (file.filename or "upload").replace("\\", "/").split("/")[-1][:255]
    try:
        df = read_table(content, filename)
    except FileFormatError as exc:
        raise HTTPException(422, str(exc)) from exc
    if len(df) > settings.max_upload_rows:
        raise HTTPException(413, f"Слишком много строк: {len(df)} (максимум {settings.max_upload_rows}).")
    purge_expired(db)
    result = validate_dataframe(df, existing_loader=lambda rows: load_existing_state(db, rows))
    report = result.as_dict()
    batch = m.ImportBatch(filename=filename, status="preview", total_rows=result.total_rows,
                          valid_rows=report["valid_rows"], validation=report,
                          staged_rows=rows_to_json(result.rows) if result.ok else None,
                          expires_at=expiry_from_now(settings.preview_ttl_minutes))
    db.add(batch)
    db.commit()
    return {"batch_id": batch.id, "filename": filename, "expires_at": batch.expires_at.isoformat(), **report}


@router.post("/imports/{batch_id}/commit")
def import_commit(db: DB, batch_id: int) -> dict[str, Any]:
    # Serialize commits so the conflict re-check and the inserts see a consistent database state.
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": COMMIT_LOCK_KEY})
    batch = db.get(m.ImportBatch, batch_id, with_for_update=True)
    if batch is None:
        raise HTTPException(404, "Импорт не найден.")
    if batch.status == "expired" or (batch.status == "preview" and batch.expires_at is not None
                                     and batch.expires_at < datetime.now(timezone.utc)):
        batch.status, batch.staged_rows = "expired", None
        db.commit()
        raise HTTPException(410, "Срок действия предпросмотра истёк. Загрузите файл заново.")
    if batch.status != "preview":
        raise HTTPException(409, "Этот импорт уже подтверждён или отменён.")
    if not batch.validation.get("ok") or not batch.staged_rows:
        raise HTTPException(422, "Файл содержит ошибки. Исправьте их и загрузите файл заново.")
    rows = rows_from_json(batch.staged_rows)
    # Re-check conflicts: data may have changed since preview.
    state = load_existing_state(db, rows)
    vr = ValidationResult(total_rows=len(rows))
    state.check(rows, vr)
    if vr.errors:
        db.rollback()
        raise HTTPException(409, "С момента проверки данные в базе изменились: обнаружены конфликты. Загрузите файл заново.")
    try:
        inserted = commit_rows(db, rows, batch.id)
        batch.status = "committed"
        batch.inserted_rows = inserted
        batch.staged_rows = None
        db.commit()
    except ImportConflict as exc:
        db.rollback()
        raise HTTPException(409, "Обнаружен конфликт с сохранёнными данными; импорт отменён целиком.") from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(500, "Не удалось сохранить данные; изменения отменены.") from exc
    return {"batch_id": batch.id, "status": "committed", "inserted_rows": inserted,
            "skipped_rows": len(rows) - inserted}


@router.post("/imports/{batch_id}/discard")
def import_discard(db: DB, batch_id: int) -> dict[str, Any]:
    batch = db.get(m.ImportBatch, batch_id)
    if batch is None:
        raise HTTPException(404, "Импорт не найден.")
    if batch.status != "preview":
        raise HTTPException(409, "Этот импорт уже подтверждён или отменён.")
    batch.status = "discarded"
    batch.staged_rows = None
    db.commit()
    return {"batch_id": batch.id, "status": "discarded"}


@router.get("/imports")
def import_history(db: DB) -> list[dict[str, Any]]:
    q = select(m.ImportBatch).order_by(m.ImportBatch.created_at.desc()).limit(20)
    return [{"id": b.id, "filename": b.filename, "status": b.status, "created_at": b.created_at.isoformat(),
             "total_rows": b.total_rows, "inserted_rows": b.inserted_rows,
             "error_count": b.validation.get("error_count", 0)} for b in db.scalars(q)]


@router.get("/imports/schema")
def import_schema() -> dict[str, Any]:
    return {"required": REQUIRED_COLUMNS, "optional": [c for c in ALL_COLUMNS if c not in REQUIRED_COLUMNS]}


@router.get("/imports/template.csv")
def import_template() -> FileResponse:
    return FileResponse(DATA_DIR / "template.csv", media_type="text/csv", filename="ddc_template.csv")


@router.get("/imports/demo-dataset.csv")
def demo_dataset() -> FileResponse:
    return FileResponse(DATA_DIR / "synthetic_assessments.csv", media_type="text/csv",
                        filename="synthetic_assessments_DEMO.csv")


# --------------------------------------------------------------------------- topics & optimizer


@router.put("/topics/{topic_id}")
def update_topic(db: DB, topic_id: int, body: TopicUpdate) -> dict[str, Any]:
    t = db.get(m.Topic, topic_id)
    if t is None:
        raise HTTPException(404, "Тема не найдена.")
    if body.min_hours > body.max_hours:
        raise HTTPException(422, "Минимум часов не может быть больше максимума.")
    t.min_hours, t.max_hours, t.priority = body.min_hours, body.max_hours, body.priority
    db.commit()
    return {"topic_id": t.id, "min_hours": t.min_hours, "max_hours": t.max_hours, "priority": t.priority}


def _optimizer_input(db, body: OptimizerRunBody) -> tuple[OptimizerInput, AnalysisSettings]:
    s = get_analysis_settings(db)
    base = topic_inputs_for(db, body.subject_id, body.grade)
    if not base:
        raise HTTPException(404, "Для выбранного предмета и параллели нет тем.")
    df = an.load_results(db, an.Filters(subject_id=body.subject_id, grade=body.grade))
    stats = {t["topic_id"]: t for t in an.topic_analytics(df, s)}
    overrides = {o.topic_id: o for o in body.topics}
    unknown = set(overrides) - {t["topic_id"] for t in base}
    if unknown:
        raise HTTPException(422, "Переданы темы, не относящиеся к выбранному предмету и параллели.")
    topics = []
    for t in base:
        o = overrides.get(t["topic_id"])
        st = stats.get(t["topic_id"])
        topics.append(TopicInput(
            topic_id=t["topic_id"], name=t["name"],
            current_hours=o.current_hours if o and o.current_hours is not None else t["current_hours"],
            min_hours=o.min_hours if o and o.min_hours is not None else t["min_hours"],
            max_hours=o.max_hours if o and o.max_hours is not None else t["max_hours"],
            priority=o.priority if o and o.priority is not None else t["priority"],
            mastery=st["mastery"] if st else None, student_count=st["student_count"] if st else 0,
            gain=st["gain"]["mean_gain"] if st and st.get("gain") else None,
            gain_direction=st["gain"]["direction"] if st and st.get("gain") else None,
            locked=bool(o and o.locked), prerequisites=t["prerequisites"]))
    inp = OptimizerInput(total_hours=body.total_hours,
                         target_mastery=body.target_mastery if body.target_mastery is not None else s.target_mastery,
                         max_change_pct=body.max_change_pct if body.max_change_pct is not None else s.max_change_pct,
                         min_students=s.min_students_topic, allow_policy_relaxation=body.allow_policy_relaxation,
                         topics=topics)
    return inp, s


@router.get("/optimizer/inputs")
def optimizer_inputs(db: DB, subject_id: int, grade: int) -> dict[str, Any]:
    s = get_analysis_settings(db)
    base = topic_inputs_for(db, subject_id, grade)
    df = an.load_results(db, an.Filters(subject_id=subject_id, grade=grade))
    stats = {t["topic_id"]: t for t in an.topic_analytics(df, s)}
    for t in base:
        st = stats.get(t["topic_id"])
        t["mastery"] = st["mastery"] if st else None
        t["student_count"] = st["student_count"] if st else 0
        t["status"] = st["status"] if st else "no_outcome_data"
        t["gain"] = st["gain"]["mean_gain"] if st and st.get("gain") else None
        t["gain_significant"] = st["gain"]["significant"] if st and st.get("gain") else None
        t["gain_direction"] = st["gain"]["direction"] if st and st.get("gain") else None
    return {"topics": base, "total_hours": round(sum(t["current_hours"] for t in base) * 2) / 2,
            "target_mastery": s.target_mastery, "max_change_pct": s.max_change_pct,
            "min_students": s.min_students_topic}


def _infeasible(exc: InfeasibleError) -> HTTPException:
    return HTTPException(422, {"message": str(exc), "details": exc.details, "code": exc.code})


@router.post("/optimizer/run")
def optimizer_run(db: DB, body: OptimizerRunBody) -> dict[str, Any]:
    inp, _ = _optimizer_input(db, body)
    try:
        result = optimize(inp)
    except InfeasibleError as exc:
        raise _infeasible(exc) from exc
    run = m.RecommendationRun(subject_id=body.subject_id, grade=body.grade, status="proposed",
                              params=body.model_dump(mode="json") | {"input": inp.model_dump()}, result=result)
    db.add(run)
    db.commit()
    return {"run_id": run.id, "status": run.status, **result}


@router.post("/optimizer/evaluate")
def optimizer_evaluate(db: DB, body: EvaluateBody) -> dict[str, Any]:
    inp, _ = _optimizer_input(db, body)
    ids = {t.topic_id for t in inp.topics}
    if set(body.allocation) - ids:
        raise HTTPException(422, "Распределение содержит неизвестные темы.")
    checks = check_allocation(inp, body.allocation)
    return {"constraints": checks, "ok": all(c["ok"] for c in checks),
            "policy_checks": check_policies(inp, body.allocation),
            "total": round(sum(body.allocation.get(i, 0) for i in ids), 2)}


@router.post("/optimizer/runs/{run_id}/decision")
def optimizer_decision(db: DB, run_id: int, body: DecisionBody) -> dict[str, Any]:
    run = db.get(m.RecommendationRun, run_id)
    if run is None:
        raise HTTPException(404, "Рекомендация не найдена.")
    if run.status != "proposed":
        raise HTTPException(409, "Решение по этой рекомендации уже принято.")
    run.decided_at = datetime.now(timezone.utc)
    if body.decision == "accept":
        if not all(c["ok"] for c in run.result["constraints"]):
            raise HTTPException(422, "Нельзя принять распределение, нарушающее ограничения.")
        run.status = "accepted"
        for r in run.result["rows"]:
            db.add(m.CurriculumAllocation(run_id=run.id, topic_id=r["topic_id"], hours=r["proposed_hours"]))
    else:
        run.status = "rejected"
    db.commit()
    return {"run_id": run.id, "status": run.status}


@router.get("/optimizer/runs")
def optimizer_runs(db: DB, subject_id: int | None = None, grade: int | None = None) -> list[dict[str, Any]]:
    q = select(m.RecommendationRun).order_by(m.RecommendationRun.created_at.desc(), m.RecommendationRun.id.desc()).limit(20)
    if subject_id:
        q = q.where(m.RecommendationRun.subject_id == subject_id)
    if grade:
        q = q.where(m.RecommendationRun.grade == grade)
    return [{"run_id": r.id, "status": r.status, "created_at": r.created_at.isoformat(), "grade": r.grade,
             "subject_id": r.subject_id, "total_hours": r.result["total_hours"],
             "changed_topics": sum(1 for x in r.result["rows"] if x["delta"] != 0), "result": r.result}
            for r in db.scalars(q)]


# --------------------------------------------------------------------------- AI


@router.post("/ai/insights")
def ai_insights(db: DB, body: FiltersBody) -> dict[str, Any]:
    ctx = build_context(db, body.to_filters())
    if not ctx["overview"]["has_data"]:
        raise HTTPException(404, "Нет данных для выбранных фильтров.")
    out = generate_insights(ctx, get_settings())
    out["optimizer_status"] = ctx["optimizer_status"]
    return out


# --------------------------------------------------------------------------- reports


def _limitations(ctx: dict[str, Any]) -> list[str]:
    lim = []
    if ctx["synthetic"]:
        lim.append("Данные синтетические (сгенерированы для демонстрации) и не описывают реальную школу.")
    lim.append("Данные наблюдательные: выводы описывают связи, а не причинные эффекты.")
    lim.append("Освоение зависит от сложности заданий; сравнение тем между собой ориентировочное.")
    if any(t["status"] == "insufficient_data" for t in ctx["topics"]):
        lim.append("Часть тем имеет выборку меньше минимальной и не классифицируется.")
    if not any(t.get("gain") for t in ctx["topics"]):
        lim.append("Нет пар входной и итоговой диагностики — прирост не рассчитан.")
    for p in ctx["textbooks"]["pairs"]:
        if p["verdict"] == "insufficient_evidence":
            lim.append(f"{p['name_a']} / {p['name_b']}: недостаточно данных для вывода об эффективности учебников.")
    if ctx.get("optimizer"):
        lim.append("Рекомендации по часам не являются прогнозом: рост освоения при увеличении часов не гарантирован.")
    return lim


STATUS_LABEL = {"proposed": "предложена, решение не принято", "accepted": "принята методистом",
                "rejected": "отклонена методистом"}


@router.post("/reports")
def create_report(db: DB, body: ReportBody) -> dict[str, Any]:
    f = body.filters.to_filters()
    ctx = build_context(db, f)
    if not ctx["overview"]["has_data"]:
        raise HTTPException(404, "Нет данных для выбранных фильтров — отчёт не сформирован.")
    insights = generate_insights(ctx, get_settings()) if body.include_ai else None
    content = {
        "filter_labels": filter_labels(db, f), "filters": f.as_dict(), "synthetic": ctx["synthetic"],
        "settings": ctx["settings"], "overview": ctx["overview"], "topics": ctx["topics"],
        "textbooks": ctx["textbooks"], "optimizer": ctx["optimizer"], "optimizer_status": ctx["optimizer_status"],
        "optimizer_status_label": STATUS_LABEL.get(ctx["optimizer_status"] or "", None),
        "optimizer_scope_note": ctx.get("optimizer_scope_note"),
        "insights": insights, "limitations": _limitations(ctx), "trend": ctx["trend"],
    }
    # Informative default title from the actual stored scope; the creation time is kept separately (created_at).
    title = body.title or report_title(content["filter_labels"], content["filters"])
    rep = m.GeneratedReport(title=title, filters=f.as_dict(), content=content)
    db.add(rep)
    db.commit()
    return _report_dict(rep)


def _report_dict(r: m.GeneratedReport, full: bool = True) -> dict[str, Any]:
    d = {"id": r.id, "title": r.title, "created_at": r.created_at.isoformat(), "filters": r.filters}
    if full:
        d["content"] = r.content
        # Derived from the stored snapshot only (never from current analytics), so older reports stay consistent.
        d["discussion"] = discussion_points(r.content)
    return d


@router.get("/reports")
def list_reports(db: DB) -> list[dict[str, Any]]:
    q = select(m.GeneratedReport).order_by(m.GeneratedReport.created_at.desc()).limit(50)
    return [_report_dict(r, full=False) | {"labels": r.content.get("filter_labels")} for r in db.scalars(q)]


@router.get("/reports/{report_id}")
def get_report(db: DB, report_id: int) -> dict[str, Any]:
    r = db.get(m.GeneratedReport, report_id)
    if r is None:
        raise HTTPException(404, "Отчёт не найден.")
    return _report_dict(r)


@router.get("/reports/{report_id}/pdf")
def report_pdf(db: DB, report_id: int) -> Response:
    r = db.get(m.GeneratedReport, report_id)
    if r is None:
        raise HTTPException(404, "Отчёт не найден.")
    pdf = render_pdf(_report_dict(r))
    return StreamingResponse(io.BytesIO(pdf), media_type="application/pdf",
                             headers={"Content-Disposition": f'attachment; filename="ddc_report_{r.id}.pdf"'})


@router.delete("/reports/{report_id}")
def delete_report(db: DB, report_id: int) -> dict[str, Any]:
    r = db.get(m.GeneratedReport, report_id)
    if r is None:
        raise HTTPException(404, "Отчёт не найден.")
    db.delete(r)
    db.commit()
    return {"deleted": report_id}


# --------------------------------------------------------------------------- settings & admin


@router.get("/settings")
def get_settings_route(db: DB) -> dict[str, Any]:
    st = get_settings()
    return {"analysis": get_analysis_settings(db).model_dump(), "notices": settings_notices(db),
            "llm": {"enabled": st.llm_enabled, "provider": st.llm_provider if st.llm_enabled else None,
                    "model": st.llm_model if st.llm_enabled else None},
            "limits": {"max_upload_mb": st.max_upload_mb, "max_upload_rows": st.max_upload_rows,
                       "preview_ttl_minutes": st.preview_ttl_minutes},
            "access": {"mode": "token" if st.api_token else "local_only", "reset_enabled": st.reset_enabled}}


@router.put("/settings")
def put_settings(db: DB, body: AnalysisSettings) -> dict[str, Any]:
    return {"analysis": save_analysis_settings(db, body).model_dump()}


@router.post("/admin/reset")
def reset_data(db: DB, body: ResetBody, x_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    settings = get_settings()
    if not settings.reset_enabled:
        raise HTTPException(403, "Удаление всех данных отключено. Включается только в среде разработки/тестирования "
                                 "(ENABLE_DATA_RESET=true и ADMIN_TOKEN).")
    if not token_matches(x_admin_token, settings.admin_token):
        raise HTTPException(403, "Неверный или отсутствующий токен администратора.")
    if body.confirm != "УДАЛИТЬ":
        raise HTTPException(422, "Для удаления всех данных введите слово УДАЛИТЬ.")
    for model in (m.CurriculumAllocation, m.RecommendationRun, m.GeneratedReport, m.AssessmentResult,
                  m.ClassTopicHours, m.TopicPrerequisite, m.Student, m.ClassSubject, m.Assessment, m.Topic,
                  m.Textbook, m.SchoolClass, m.Subject, m.School, m.ImportBatch):
        db.execute(delete(model))
    db.commit()
    log.warning("All application data was reset via /api/admin/reset")
    return {"reset": True}


@router.get("/admin/integrity")
def integrity(db: DB) -> dict[str, Any]:
    """Read-only check of invariants that older imports may violate (see scripts/integrity_check.py)."""
    return run_integrity_checks(db)
