"""Database side of the import: conflict snapshot and transactional commit."""
from __future__ import annotations

import math
from typing import Any

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app import models as m
from app.services.importer import DEFAULT_SCHOOL, ExistingState


def school_name(code: str) -> str:
    return "Школа по умолчанию (синтетические данные)" if code == DEFAULT_SCHOOL else code


def load_existing_state(db: Session, rows: list[dict[str, Any]]) -> ExistingState:
    subjects = {s.id: s.name for s in db.scalars(select(m.Subject))}
    topic_codes = {r["topic_id"] for r in rows}
    topics = {
        t.code: (t.name, subjects[t.subject_id], t.grade)
        for t in db.scalars(select(m.Topic).where(m.Topic.code.in_(topic_codes)))
    }
    a_codes = {r["assessment_id"] for r in rows}
    assessments = {
        a.code: (a.assessment_date, a.kind, subjects[a.subject_id], a.comparison_group)
        for a in db.scalars(select(m.Assessment).where(m.Assessment.code.in_(a_codes)))
    }
    schools = {s.id: s.code for s in db.scalars(select(m.School))}
    classes = {c.id: (schools[c.school_id], c.name) for c in db.scalars(select(m.SchoolClass))}
    students: dict[tuple, str] = {}
    student_key: dict[int, tuple] = {}
    for s in db.scalars(select(m.Student)):
        key = (schools[s.school_id], s.external_id)
        students[key] = classes[s.class_id][1]
        student_key[s.id] = key
    tbs = {t.id: t.code for t in db.scalars(select(m.Textbook))}
    class_tb = {
        classes[cs.class_id] + (subjects[cs.subject_id],): (tbs.get(cs.textbook_id) if cs.textbook_id else None)
        for cs in db.scalars(select(m.ClassSubject))
    }
    results: dict[tuple, tuple] = {}
    if assessments:
        a_ids = {a.id: a.code for a in db.scalars(select(m.Assessment).where(m.Assessment.code.in_(a_codes)))}
        t_ids = {t.id: t.code for t in db.scalars(select(m.Topic))}
        q = select(m.AssessmentResult.student_id, m.AssessmentResult.assessment_id, m.AssessmentResult.topic_id,
                   m.AssessmentResult.item_id, m.AssessmentResult.score, m.AssessmentResult.max_score).where(
            m.AssessmentResult.assessment_id.in_(a_ids.keys()))
        for sid, aid, tid, item, score, mx in db.execute(q):
            sk = student_key[sid]
            results[(sk[0], sk[1], a_ids[aid], t_ids[tid], item)] = (score, mx)
    return ExistingState(topics, assessments, students, class_tb, results)


def _default_bounds(mean_hours: float | None) -> tuple[float, float]:
    if mean_hours is None or mean_hours <= 0:
        return 0.0, 0.0
    lo = math.floor(mean_hours * 0.5 * 2) / 2
    hi = math.ceil(mean_hours * 1.5 * 2) / 2
    return lo, hi


def commit_rows(db: Session, rows: list[dict[str, Any]], batch_id: int) -> int:
    """Insert validated rows in one transaction. Caller commits. Returns inserted result count."""
    def get_or_create(model, lookup: dict, defaults: dict | None = None):
        obj = db.scalars(select(model).filter_by(**lookup)).first()
        if obj is None:
            obj = model(**lookup, **(defaults or {}))
            db.add(obj)
            db.flush()
        return obj

    schools: dict[str, m.School] = {}
    subjects: dict[str, m.Subject] = {}
    textbooks: dict[str, m.Textbook] = {}
    classes: dict[tuple, m.SchoolClass] = {}
    topics: dict[str, m.Topic] = {}
    assessments: dict[str, m.Assessment] = {}
    students: dict[tuple, m.Student] = {}

    hours_by_topic: dict[str, list[float]] = {}
    for r in rows:
        if r["teaching_hours"] is not None:
            hours_by_topic.setdefault(r["topic_id"], [])
    class_topic_hours: dict[tuple, float] = {}
    for r in rows:
        if r["teaching_hours"] is not None:
            class_topic_hours[(r["school"], r["class"], r["topic_id"])] = r["teaching_hours"]
    for (_, _, t), h in class_topic_hours.items():
        hours_by_topic[t].append(h)

    for r in rows:
        if r["school"] not in schools:
            schools[r["school"]] = get_or_create(m.School, {"code": r["school"]}, {"name": school_name(r["school"])})
        if r["subject"] not in subjects:
            code = r["subject"].strip().lower()[:64]
            subjects[r["subject"]] = get_or_create(m.Subject, {"code": code}, {"name": r["subject"]})
        subj = subjects[r["subject"]]
        tb_code = r["textbook_id"]
        if tb_code and tb_code not in textbooks:
            textbooks[tb_code] = get_or_create(
                m.Textbook, {"code": tb_code}, {"name": r["textbook_name"] or tb_code, "subject_id": subj.id})
        ck = (r["school"], r["class"])
        if ck not in classes:
            classes[ck] = get_or_create(m.SchoolClass, {"school_id": schools[r["school"]].id, "name": r["class"]},
                                        {"grade": r["grade"]})
            existing_cs = db.scalars(select(m.ClassSubject).filter_by(class_id=classes[ck].id, subject_id=subj.id)).first()
            if existing_cs is None:
                db.add(m.ClassSubject(class_id=classes[ck].id, subject_id=subj.id,
                                      textbook_id=textbooks[tb_code].id if tb_code else None))
        if r["topic_id"] not in topics:
            hrs = hours_by_topic.get(r["topic_id"])
            mean_h = sum(hrs) / len(hrs) if hrs else None
            lo, hi = _default_bounds(mean_h)
            t = db.scalars(select(m.Topic).filter_by(code=r["topic_id"])).first()
            if t is None:
                t = m.Topic(
                    code=r["topic_id"], name=r["topic_name"], subject_id=subj.id, grade=r["grade"],
                    order_index=r["topic_order"] if r["topic_order"] is not None else 0,
                    min_hours=r["topic_min_hours"] if r["topic_min_hours"] is not None else lo,
                    max_hours=r["topic_max_hours"] if r["topic_max_hours"] is not None else max(hi, lo),
                    priority=r["topic_priority"] if r["topic_priority"] is not None else 2,
                )
                db.add(t)
                db.flush()
            topics[r["topic_id"]] = t
        if r["assessment_id"] not in assessments:
            assessments[r["assessment_id"]] = get_or_create(
                m.Assessment, {"code": r["assessment_id"]},
                {"subject_id": subj.id, "assessment_date": r["assessment_date"], "kind": r["assessment_type"],
                 "comparison_group": r["comparison_group"]})
        sk = (r["school"], r["student_id"])
        if sk not in students:
            students[sk] = get_or_create(m.Student, {"school_id": schools[r["school"]].id, "external_id": r["student_id"]},
                                         {"class_id": classes[ck].id})

    # prerequisites
    for r in rows:
        for p in r["topic_prerequisites"]:
            t, pre = topics[r["topic_id"]], topics.get(p)
            if pre is None:
                pre = db.scalars(select(m.Topic).filter_by(code=p)).first()
            if pre is not None:
                exists = db.scalars(select(m.TopicPrerequisite).filter_by(topic_id=t.id, prerequisite_id=pre.id)).first()
                if exists is None:
                    db.add(m.TopicPrerequisite(topic_id=t.id, prerequisite_id=pre.id))
                    db.flush()

    # teaching hours (replace per class/topic as provided by the file; conflicts were rejected in validation)
    for (school, cls, topic_code), h in class_topic_hours.items():
        c = classes[(school, cls)]
        t = topics[topic_code]
        db.execute(delete(m.ClassTopicHours).where(m.ClassTopicHours.class_id == c.id,
                                                   m.ClassTopicHours.topic_id == t.id))
        db.add(m.ClassTopicHours(class_id=c.id, topic_id=t.id, hours=h))

    payload = [
        {
            "student_id": students[(r["school"], r["student_id"])].id,
            "assessment_id": assessments[r["assessment_id"]].id,
            "topic_id": topics[r["topic_id"]].id,
            "item_id": r["item_id"],
            "score": r["score"],
            "max_score": r["max_score"],
            "import_batch_id": batch_id,
        }
        for r in rows
        if not r.get("_skip")
    ]
    for i in range(0, len(payload), 5000):
        db.execute(insert(m.AssessmentResult), payload[i : i + 5000])
    return len(payload)
