"""Builds the full, verified analysis context for a set of filters (shared by API, AI and reports)."""
from __future__ import annotations

from typing import Any

from sqlalchemy import and_, select
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


def latest_run(db: Session, f: an.Filters) -> m.RecommendationRun | None:
    q = select(m.RecommendationRun).order_by(m.RecommendationRun.created_at.desc(), m.RecommendationRun.id.desc())
    if f.subject_id is not None:
        q = q.where(m.RecommendationRun.subject_id == f.subject_id)
    if f.grade is not None:
        q = q.where(m.RecommendationRun.grade == f.grade)
    accepted = db.scalars(q.where(m.RecommendationRun.status == "accepted")).first()
    return accepted or db.scalars(q.where(m.RecommendationRun.status == "proposed")).first()


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
        run = latest_run(db, f)
        if run is not None:
            ctx["optimizer"] = run.result
            ctx["optimizer_status"] = run.status
            ctx["optimizer_run_id"] = run.id
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
    """Current hours (mean over classes of the grade), constraints and prerequisites of each topic."""
    topics = db.scalars(select(m.Topic).where(m.Topic.subject_id == subject_id, m.Topic.grade == grade)
                        .order_by(m.Topic.order_index, m.Topic.code)).all()
    f = an.Filters(subject_id=subject_id, grade=grade)
    hours = an.mean_hours_by_topic(db, f)
    prereq: dict[int, list[int]] = {}
    for tp in db.scalars(select(m.TopicPrerequisite).where(m.TopicPrerequisite.topic_id.in_([t.id for t in topics]))):
        prereq.setdefault(tp.topic_id, []).append(tp.prerequisite_id)
    _ = and_
    return [
        {"topic_id": t.id, "code": t.code, "name": t.name, "current_hours": round(hours.get(t.id, 0.0), 2),
         "min_hours": t.min_hours, "max_hours": t.max_hours, "priority": t.priority,
         "prerequisites": prereq.get(t.id, []), "has_hours_data": t.id in hours}
        for t in topics
    ]
