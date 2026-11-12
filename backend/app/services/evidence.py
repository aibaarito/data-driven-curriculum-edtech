"""Evidence context, versioning and evidence-readiness assessment.

* ``evidence_revision`` — a cheap, scope-limited identity of the data a conclusion depends on (SQL aggregates, no
  copies, no student identifiers). Any import, topic-constraint change, prerequisite change, hours change or
  settings change in the scope changes the revision.
* ``analysis_fingerprint`` — identity of an analysis result: scope filters + revision + algorithm version.
* ``assess_topic`` / ``assess_textbook_pair`` — the EvidenceAssessment contract. Categories describe how ready the
  evidence is for a decision; they are NOT probabilities that an intervention works.
* ``topic_passport`` / ``textbook_passport`` — the Evidence Passport: what was observed, on which data, by which
  method, with what uncertainty, and why an action is allowed or blocked.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models as m
from app.services import analytics as an
from app.services.settings_store import AnalysisSettings

# Bumped whenever an analytical definition, decision rule or scenario rule changes, so that results computed by
# a different algorithm are never presented as identical.
ALGORITHM_VERSION = "ddc-2.0.0"

Category = Literal["supported", "exploratory", "insufficient", "incomparable", "stale"]
CATEGORY_RU = {
    "supported": "Доказательства достаточны",
    "exploratory": "Предварительные данные",
    "insufficient": "Недостаточно данных",
    "incomparable": "Несопоставимые данные",
    "stale": "Устаревшие данные",
}
CATEGORY_HINT = {
    "supported": "Достаточная выборка, несколько классов и сопоставленная входная/итоговая диагностика. Это "
                 "готовность данных к решению, а не вероятность успеха вмешательства.",
    "exploratory": "Данных достаточно для описания, но не хватает одного из элементов (входной диагностики, "
                   "нескольких классов или сопоставленных пар). Решение — только с экспертной проверкой.",
    "insufficient": "Данных недостаточно для вывода. Автоматические действия не предлагаются.",
    "incomparable": "Сравнение некорректно: разные задания, параллели или предметы.",
    "stale": "Данные или настройки изменились после сохранения результата.",
}
MIN_CLASSES_SUPPORTED = 2
MIN_PAIRING_COVERAGE = 0.5


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def sha(obj: Any, n: int = 64) -> str:
    return hashlib.sha256(_canonical(obj).encode("utf-8")).hexdigest()[:n]


# --------------------------------------------------------------------------- revision & fingerprint


def evidence_revision(db: Session, s: AnalysisSettings, subject_id: int | None = None,
                      grade: int | None = None) -> dict[str, Any]:
    """Scope-limited revision of the evidence base. Returns hash + human-readable counters (no identifiers)."""
    r, st, c, t, a = m.AssessmentResult, m.Student, m.SchoolClass, m.Topic, m.Assessment
    q = (select(func.count(r.id), func.coalesce(func.max(r.id), 0), func.coalesce(func.sum(r.score), 0.0),
                func.coalesce(func.sum(r.max_score), 0.0), func.count(func.distinct(r.assessment_id)),
                func.count(func.distinct(r.student_id)))
         .join(st, st.id == r.student_id).join(c, c.id == st.class_id).join(t, t.id == r.topic_id))
    tq = select(t.id, t.min_hours, t.max_hours, t.priority, t.order_index).order_by(t.id)
    hq = (select(func.count(m.ClassTopicHours.id), func.coalesce(func.sum(m.ClassTopicHours.hours), 0.0))
          .join(c, c.id == m.ClassTopicHours.class_id).join(t, t.id == m.ClassTopicHours.topic_id))
    eq = (select(m.TopicPrerequisite.topic_id, m.TopicPrerequisite.prerequisite_id)
          .join(t, t.id == m.TopicPrerequisite.topic_id)
          .where(m.TopicPrerequisite.review_status == "approved")
          .order_by(m.TopicPrerequisite.topic_id, m.TopicPrerequisite.prerequisite_id))
    bq = (select(m.ClassSubject.class_id, m.ClassSubject.subject_id, m.ClassSubject.textbook_id)
          .join(c, c.id == m.ClassSubject.class_id).order_by(m.ClassSubject.class_id, m.ClassSubject.subject_id))
    if subject_id is not None:
        q, tq, hq, eq = (x.where(t.subject_id == subject_id) for x in (q, tq, hq, eq))
        bq = bq.where(m.ClassSubject.subject_id == subject_id)
    if grade is not None:
        q, hq, bq = q.where(c.grade == grade), hq.where(c.grade == grade), bq.where(c.grade == grade)
        tq, eq = tq.where(t.grade == grade), eq.where(t.grade == grade)
    n, max_id, score_sum, max_sum, n_assess, n_students = db.execute(q).one()
    hours_n, hours_sum = db.execute(hq).one()
    topics = [list(x) for x in db.execute(tq).all()]
    edges = [list(x) for x in db.execute(eq).all()]
    books = [list(x) for x in db.execute(bq).all()]
    aq = select(a.id, a.assessment_date, a.kind, a.comparison_group).order_by(a.id)
    if subject_id is not None:
        aq = aq.where(a.subject_id == subject_id)
    assess = [list(x) for x in db.execute(aq).all()]
    material = {"results": [n, max_id, round(float(score_sum), 4), round(float(max_sum), 4)],
                "hours": [hours_n, round(float(hours_sum), 4)], "topics": topics, "edges": edges, "textbooks": books,
                "assessments": sorted(assess, key=lambda x: x[0]), "settings": s.model_dump()}
    return {"hash": sha(material, 16), "results": int(n), "students": int(n_students),
            "assessments": int(n_assess), "topics": len(topics), "prerequisites": len(edges),
            "hours_records": int(hours_n)}


def analysis_fingerprint(scope: dict[str, Any], revision_hash: str) -> str:
    return sha({"scope": scope, "revision": revision_hash, "algorithm": ALGORITHM_VERSION}, 32)


def is_synthetic(db: Session) -> bool:
    return any(code.upper().startswith("SYNTH") for code in db.scalars(select(m.School.code)))


def context_metadata(db: Session, s: AnalysisSettings, scope: dict[str, Any]) -> dict[str, Any]:
    """Lightweight immutable metadata identifying an analysis (attached to every decision-layer response)."""
    rev = evidence_revision(db, s, scope.get("subject_id"), scope.get("grade"))
    return {"fingerprint": analysis_fingerprint(scope, rev["hash"]), "revision": rev, "scope": scope,
            "algorithm_version": ALGORITHM_VERSION, "settings": s.model_dump(), "synthetic": is_synthetic(db),
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def plan_context(db: Session, s: AnalysisSettings, subject_id: int, grade: int) -> dict[str, Any]:
    """Context of a grade-level plan (the scope recommendation runs, scenarios and interventions are bound to)."""
    return context_metadata(db, s, {"subject_id": subject_id, "grade": grade, "view": "grade_plan"})


def evidence_snapshot(meta: dict[str, Any], topics: list[dict[str, Any]], s: AnalysisSettings) -> dict[str, Any]:
    """Frozen, aggregate-only evidence for a saved recommendation (no student identifiers)."""
    keys = ("mean_gain", "ci_low", "ci_high", "ci_level", "direction", "n_paired")
    return {"context": {k: meta[k] for k in ("fingerprint", "revision", "scope", "algorithm_version", "synthetic",
                                              "generated_at", "settings")},
            "topics": [{"topic_id": t["topic_id"], "code": t["code"], "name": t["name"], "mastery": t["mastery"],
                        "student_count": t["student_count"], "class_count": t["class_count"], "status": t["status"],
                        "ci_low": t["ci_low"], "ci_high": t["ci_high"],
                        "gain": {k: t["gain"].get(k) for k in keys} if t.get("gain") else None,
                        "evidence": assess_topic(t, s)["category"]} for t in topics]}


def last_committed_import(db: Session) -> datetime | None:
    return db.scalar(select(func.max(m.ImportBatch.created_at)).where(m.ImportBatch.status == "committed"))


# --------------------------------------------------------------------------- evidence assessment


def _assessment(category: Category, reasons: list[str], dimensions: dict[str, Any]) -> dict[str, Any]:
    return {"category": category, "label": CATEGORY_RU[category], "hint": CATEGORY_HINT[category],
            "reasons": reasons, "dimensions": dimensions, "allows_action": category in ("supported", "exploratory")}


def assess_topic(t: dict[str, Any], s: AnalysisSettings) -> dict[str, Any]:
    """Evidence readiness of one topic row produced by ``analytics.topic_analytics``."""
    gain = t.get("gain") or {}
    n = int(t.get("student_count") or 0)
    paired = int(gain.get("n_paired") or 0)
    coverage = round(paired / n, 3) if n else 0.0
    direction = an.gain_direction(gain) if gain else None
    dims = {
        "students": n, "min_students": s.min_students_topic, "classes": int(t.get("class_count") or 0),
        "assessments": int(t.get("assessment_count") or 0), "paired_students": paired,
        "pairing_coverage": coverage, "gain_direction": direction,
        "mastery_ci": [t.get("ci_low"), t.get("ci_high")],
        "gain_ci": [gain.get("ci_low"), gain.get("ci_high")] if gain else None,
        "gain_ci_level": gain.get("ci_level") if gain else None,
        "observational": True,
    }
    if t.get("mastery") is None:
        return _assessment("insufficient", ["Нет итоговых или текущих оцениваний по теме."], dims)
    if n < s.min_students_topic:
        return _assessment("insufficient", [f"Учеников с результатами: {n} (минимум {s.min_students_topic})."], dims)
    reasons: list[str] = []
    if dims["classes"] < MIN_CLASSES_SUPPORTED:
        reasons.append(f"Данные только по {dims['classes']} классу: нельзя отделить особенности класса от темы.")
    if not gain:
        reasons.append("Нет сопоставленной входной диагностики (pre/post одной группы сравнения): нельзя "
                       "отличить слабую исходную подготовку от трудностей обучения.")
    elif direction == "insufficient":
        reasons.append(f"Пар «входная–итоговая» только {paired}: динамику оценить нельзя.")
    elif coverage < MIN_PAIRING_COVERAGE:
        reasons.append(f"Входная диагностика сопоставлена только для {coverage:.0%} учеников.")
    if reasons:
        return _assessment("exploratory", reasons, dims)
    return _assessment("supported", ["Достаточная выборка, несколько классов, сопоставленные пары и "
                                     "интервал с поправкой на множественные сравнения."], dims)


def assess_textbook_pair(p: dict[str, Any]) -> dict[str, Any]:
    dims = {"classes_a": p.get("classes_a"), "classes_b": p.get("classes_b"), "common_items": p.get("common_items"),
            "inference_unit": p.get("inference_unit"), "ci_level": p.get("ci_level"),
            "pairs_in_family": p.get("pairs_in_family"), "observational": True}
    reasons = list(p.get("reasons") or [])
    if not p.get("common_items") or any("разных параллелях" in r for r in reasons):
        return _assessment("incomparable", reasons or ["Нет общих итоговых заданий."], dims)
    if p.get("verdict") == "observed_difference":
        cat: Category = "supported" if p.get("evidence_level") == "observational" else "exploratory"
        return _assessment(cat, ["Оценка с поправкой на исходный уровень и оценка по приросту согласованы."], dims)
    return _assessment("insufficient", reasons or ["Различие не установлено."], dims)


def mark_stale(assessment: dict[str, Any], reason: str) -> dict[str, Any]:
    out = dict(assessment)
    out.update({"category": "stale", "label": CATEGORY_RU["stale"], "hint": CATEGORY_HINT["stale"],
                "reasons": [reason, *assessment.get("reasons", [])], "allows_action": False})
    return out


# --------------------------------------------------------------------------- passports

DIRECTION_RU = {"increase": "статистически значимый прирост", "decline": "статистически значимое снижение",
                "inconclusive": "изменение не установлено (интервал включает ноль)",
                "insufficient": "мало пар для оценки динамики"}


def topic_passport(t: dict[str, Any], s: AnalysisSettings, meta: dict[str, Any],
                   graph_node: dict[str, Any] | None = None, decision: dict[str, Any] | None = None) -> dict[str, Any]:
    ev = assess_topic(t, s)
    gain = t.get("gain") or {}
    observation = [
        f"Освоение {t['mastery']}% (Σ набранных / Σ максимальных баллов по итоговым и текущим оцениваниям)."
        if t.get("mastery") is not None else "Освоение не рассчитано: нет итоговых оцениваний.",
        f"Учеников: {t.get('student_count', 0)}, классов: {t.get('class_count', 0)}, оцениваний: "
        f"{t.get('assessment_count', 0)}.",
    ]
    if t.get("class_mean") is not None and t.get("mastery") is not None and abs(t["class_mean"] - t["mastery"]) >= 3:
        observation.append(f"Среднее по классам ({t['class_mean']}%) заметно отличается от объединённого значения: "
                           "состав классов влияет на итог.")
    statistics = {"mastery": t.get("mastery"), "mean": t.get("mean"), "median": t.get("median"),
                  "class_mean": t.get("class_mean"), "sd": t.get("sd"), "ci_low": t.get("ci_low"),
                  "ci_high": t.get("ci_high")}
    uncertainty = []
    if t.get("ci_low") is not None:
        uncertainty.append(f"95% ДИ среднего по ученикам: {t['ci_low']}…{t['ci_high']}% (без учёта группировки "
                           "по классам — описательно).")
    if gain:
        statistics |= {"pre_mean": gain.get("pre_mean"), "post_mean": gain.get("post_mean"),
                       "mean_gain": gain.get("mean_gain"), "gain_ci_low": gain.get("ci_low"),
                       "gain_ci_high": gain.get("ci_high"), "gain_ci_level": gain.get("ci_level"),
                       "p_value_adjusted": gain.get("p_value_adjusted"), "family_size": gain.get("family_size"),
                       "n_paired": gain.get("n_paired")}
        d = an.gain_direction(gain)
        if gain.get("ci_low") is not None:
            uncertainty.append(f"Прирост {gain['mean_gain']:+} п.п., {gain['ci_level']}% ДИ {gain['ci_low']}…"
                               f"{gain['ci_high']} (поправка Бонферрони на {gain['family_size']} тем): "
                               f"{DIRECTION_RU.get(d, d)}.")
        if d == "inconclusive":
            uncertainty.append("Интервал включает ноль: данные не устанавливают изменения, но и не доказывают его "
                               "отсутствие.")
    strengthen = _strengthen(ev, t)
    passport = {
        "subject_kind": "topic", "subject_id": t["topic_id"], "title": f"«{t['name']}»",
        "observation": observation,
        "interpretation": t.get("interpretation"),
        "statistics": statistics,
        "method": "Освоение — объединённые баллы; прирост — парный t-тест (те же ученики, та же группа сравнения), "
                  "интервал Бонферрони по всем темам с достаточным числом пар; классификация по порогам настроек.",
        "dataset": {"fingerprint": meta["fingerprint"], "revision": meta["revision"], "scope": meta["scope"],
                    "algorithm_version": meta["algorithm_version"], "synthetic": meta["synthetic"]},
        "sample": {"students": t.get("student_count"), "classes": t.get("class_count"),
                   "paired": gain.get("n_paired") if gain else 0},
        "uncertainty": uncertainty,
        "gate": ev,
        "strengthen": strengthen,
        "limitations": ["Данные наблюдательные: связь не означает причинный эффект.",
                        "Освоение зависит от сложности заданий; сравнение тем между собой ориентировочное."],
    }
    if graph_node:
        passport["graph"] = {k: graph_node.get(k) for k in ("prerequisites", "dependents", "downstream_count",
                                                             "weak_downstream", "foundational_gap", "priority")}
    if decision:
        passport["decision"] = {k: decision.get(k) for k in ("id", "action", "problem", "required_review")}
    return passport


def _strengthen(ev: dict[str, Any], t: dict[str, Any]) -> list[str]:
    d = ev["dimensions"]
    out = []
    if d["students"] < d["min_students"]:
        out.append(f"Собрать результаты ещё не менее {d['min_students'] - d['students']} учеников.")
    if d["classes"] < MIN_CLASSES_SUPPORTED:
        out.append("Добавить данные других классов параллели.")
    if not t.get("gain"):
        out.append("Провести входную диагностику (pre) с той же группой сравнения, что и итоговая.")
    elif d["pairing_coverage"] < MIN_PAIRING_COVERAGE:
        out.append("Сопоставить входную и итоговую диагностику для большего числа учеников.")
    out.append("Проверить результаты на следующем оценивании (тот же формат заданий).")
    return out


def textbook_passport(p: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    ev = assess_textbook_pair(p)
    stats: dict[str, Any] = {"common_items": p.get("common_items"), "classes_a": p.get("classes_a"),
                             "classes_b": p.get("classes_b"), "baseline_diff": p.get("baseline_diff"),
                             "ci_level": p.get("ci_level")}
    unc = []
    for key, label in (("raw", "Разница средних классов (без поправки)"),
                       ("adjusted", "С поправкой на исходный уровень (ANCOVA по классам)"),
                       ("gain", "Разница прироста (Welch по классам)")):
        e = p.get(key)
        if e:
            stats[key] = {k: e.get(k) for k in ("diff", "ci_low", "ci_high", "p_value", "df")}
            if e.get("diff") is None or e.get("ci_low") is None:
                unc.append(f"{label}: не оценивается.")
            else:
                unc.append(f"{label}: {e['diff']:+} п.п., {p.get('ci_level')}% ДИ {e['ci_low']}…{e['ci_high']}.")
    return {
        "subject_kind": "textbook_pair", "subject_id": f"{p['textbook_a']}-{p['textbook_b']}",
        "title": f"«{p['name_a']}» и «{p['name_b']}»",
        "observation": [p.get("verdict_text") or ""],
        "interpretation": "Наблюдаемая связь в нерандомизированных данных, а не причинный эффект учебника."
        if p.get("verdict") == "observed_difference" else "Победитель не определяется: условия вывода не выполнены.",
        "statistics": stats,
        "method": "Единица вывода — класс. ANCOVA по средним классов + Welch по приросту классов; вывод только при "
                  "согласии обеих оценок; поправка Бонферрони по парам учебников.",
        "dataset": {"fingerprint": meta["fingerprint"], "revision": meta["revision"], "scope": meta["scope"],
                    "algorithm_version": meta["algorithm_version"], "synthetic": meta["synthetic"]},
        "sample": {"classes": (p.get("classes_a") or 0) + (p.get("classes_b") or 0)},
        "uncertainty": unc,
        "gate": ev,
        "strengthen": ["Добавить классы для каждого учебника (не менее 3, лучше 10+ всего).",
                       "Использовать общие задания итоговой и входной диагностики для всех классов."],
        "limitations": list(p.get("confounders") or []),
        "winner_allowed": ev["category"] in ("supported", "exploratory") and p.get("verdict") == "observed_difference",
    }
