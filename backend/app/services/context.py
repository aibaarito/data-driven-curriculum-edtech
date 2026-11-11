"""Builds the full, verified analysis context for a set of filters (shared by API, AI and reports)."""
from __future__ import annotations

import statistics
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app import models as m
from app.services import analytics as an
from app.services.settings_store import get_analysis_settings
from app.services.textbooks import compare_textbooks


def hours_by_class(db: Session, f: an.Filters) -> dict[int, float]:
    h, t, c = m.ClassTopicHours, m.Topic, m.SchoolClass
    q = select(h.class_id, h.hours).join(t, t.id == h.topic_id).join(c, c.id == h.class_id)
    if f.subject_id is not None:
        q = q.where(t.subject_id == f.subject_id)
    if f.grade is not None:
        q = q.where(c.grade == f.grade)
    out: dict[int, float] = {}
    for cid, hours in db.execute(q):
        out[cid] = out.get(cid, 0.0) + hours
    return out


def latest_run(db: Session, subject_id: int, grade: int) -> m.RecommendationRun | None:
    """Latest accepted (else proposed) plan for exactly this subject and grade."""
    q = (select(m.RecommendationRun)
         .where(m.RecommendationRun.subject_id == subject_id, m.RecommendationRun.grade == grade)
         .order_by(m.RecommendationRun.created_at.desc(), m.RecommendationRun.id.desc()))
    accepted = db.scalars(q.where(m.RecommendationRun.status == "accepted")).first()
    return accepted or db.scalars(q.where(m.RecommendationRun.status == "proposed")).first()


def plan_scope(db: Session, f: an.Filters, df) -> tuple[int | None, int | None, str | None]:
    """Resolve (subject_id, grade) a grade-level hours plan may be shown for, or a note why none applies."""
    grade = f.grade
    if f.class_id is not None:
        cls = db.get(m.SchoolClass, f.class_id)
        if cls is not None:
            if grade is not None and grade != cls.grade:
                return None, None, "Выбранный класс не относится к выбранной параллели."
            grade = cls.grade
    subject = f.subject_id
    if not df.empty:
        if grade is None and df["grade"].nunique() == 1:
            grade = int(df["grade"].iloc[0])
        if subject is None and df["subject_id"].nunique() == 1:
            subject = int(df["subject_id"].iloc[0])
    if grade is None or subject is None:
        return None, None, ("План часов составляется для одного предмета и одной параллели. Выберите их в фильтрах, "
                            "чтобы включить рекомендацию.")
    return subject, grade, None


def is_synthetic(db: Session) -> bool:
    return any(code.upper().startswith("SYNTH") for code in db.scalars(select(m.School.code)))


def build_context(db: Session, f: an.Filters, include_run: bool = True) -> dict[str, Any]:
    s = get_analysis_settings(db)
    df = an.load_results(db, f)
    hours = an.mean_hours_by_topic(db, f)
    ctx: dict[str, Any] = {
        "filters": f.as_dict(),
        "settings": s.model_dump(),
        "overview": an.overview(df),
        "topics": an.topic_analytics(df, s, hours),
        "textbooks": compare_textbooks(df, s, hours_by_class(db, f)) if not df.empty else
        {"textbooks": [], "pairs": [], "topic_matrix": [], "common_items": 0, "comparable": False,
         "message": "Нет данных."},
        "trend": an.overall_trend(df),
        "synthetic": is_synthetic(db),
        "optimizer": None,
        "optimizer_status": None,
    }
    if include_run:
        subject, grade, note = plan_scope(db, f, df)
        ctx["optimizer_scope_note"] = note
        if subject is not None:
            run = latest_run(db, subject, grade)
            if run is None:
                ctx["optimizer_scope_note"] = (f"Для параллели {grade} по выбранному предмету рекомендация по часам ещё "
                                               "не сформирована.")
            else:
                ctx["optimizer"] = run.result
                ctx["optimizer_status"] = run.status
                ctx["optimizer_run_id"] = run.id
                notes = [f"План часов для {grade}-й параллели (единый для всех её классов)."]
                if f.class_id or f.textbook_id or f.date_from or f.date_to:
                    notes.append("Фильтры класса, учебника и периода к плану не применяются: он рассчитан по всей "
                                 "параллели.")
                last_import = db.scalar(select(func.max(m.ImportBatch.created_at))
                                        .where(m.ImportBatch.status == "committed"))
                if last_import is not None and run.created_at < last_import:
                    notes.append("Рекомендация сформирована до последнего импорта данных и может быть устаревшей.")
                ctx["optimizer_scope_note"] = " ".join(notes)
    return ctx


def filter_labels(db: Session, f: an.Filters) -> dict[str, str]:
    labels = {"Предмет": "все", "Параллель": "все", "Класс": "все", "Учебник": "все", "Период": "весь"}
    if f.subject_id and (x := db.get(m.Subject, f.subject_id)):
        labels["Предмет"] = x.name
    if f.grade:
        labels["Параллель"] = f"{f.grade}"
    if f.class_id and (c := db.get(m.SchoolClass, f.class_id)):
        labels["Класс"] = c.name
    if f.textbook_id and (t := db.get(m.Textbook, f.textbook_id)):
        labels["Учебник"] = t.name
    if f.date_from or f.date_to:
        labels["Период"] = f"{f.date_from or '…'} — {f.date_to or '…'}"
    return labels


def topic_inputs_for(db: Session, subject_id: int, grade: int) -> list[dict[str, Any]]:
    """Grade-level plan inputs per topic.

    The optimizer works on ONE plan per grade (all classes of the grade follow it). Its baseline is the median of
    the classes' imported hours rounded to 0.5 h — a value a real timetable can contain — instead of a fractional
    mean; the spread across classes is reported so deviating classes stay visible.
    """
    topics = db.scalars(select(m.Topic).where(m.Topic.subject_id == subject_id, m.Topic.grade == grade)
                        .order_by(m.Topic.order_index, m.Topic.code)).all()
    h, c = m.ClassTopicHours, m.SchoolClass
    per_topic: dict[int, list[float]] = {}
    for topic_id, hours in db.execute(select(h.topic_id, h.hours).join(c, c.id == h.class_id)
                                      .where(c.grade == grade, h.topic_id.in_([t.id for t in topics]))):
        per_topic.setdefault(topic_id, []).append(hours)
    prereq: dict[int, list[int]] = {}
    for tp in db.scalars(select(m.TopicPrerequisite).where(m.TopicPrerequisite.topic_id.in_([t.id for t in topics]))):
        prereq.setdefault(tp.topic_id, []).append(tp.prerequisite_id)
    out = []
    for t in topics:
        vals = sorted(per_topic.get(t.id, []))
        median = float(statistics.median(vals)) if vals else 0.0
        out.append({
            "topic_id": t.id, "code": t.code, "name": t.name, "current_hours": round(median * 2) / 2,
            "class_hours_mean": round(sum(vals) / len(vals), 2) if vals else None,
            "class_hours_min": vals[0] if vals else None, "class_hours_max": vals[-1] if vals else None,
            "classes_with_hours": len(vals),
            "min_hours": t.min_hours, "max_hours": t.max_hours, "priority": t.priority,
            "prerequisites": prereq.get(t.id, []), "has_hours_data": bool(vals)})
    return out
