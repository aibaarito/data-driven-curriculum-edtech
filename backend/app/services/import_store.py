"""Database side of the import: conflict snapshot and transactional commit."""
from __future__ import annotations

import math
from typing import Any

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app import models as m
from app.services.importer import DEFAULT_SCHOOL, ExistingState


class ImportConflict(RuntimeError):
    """Raised inside the commit transaction if persisted state contradicts the staged rows."""


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
    tb_objs = list(db.scalars(select(m.Textbook)))
    tbs = {t.id: t.code for t in tb_objs}
    textbooks = {t.code: (subjects[t.subject_id], t.name) for t in tb_objs}
    class_grade = {(schools[c.school_id], c.name): c.grade for c in db.scalars(select(m.SchoolClass))}
    topic_objs = list(db.scalars(select(m.Topic).where(m.Topic.code.in_(topic_codes))))
    code_by_id = {t.id: t.code for t in db.scalars(select(m.Topic))}
    prereqs: dict[int, set[str]] = {}
    if topic_objs:
        for tp in db.scalars(select(m.TopicPrerequisite).where(
                m.TopicPrerequisite.topic_id.in_([t.id for t in topic_objs]))):
            prereqs.setdefault(tp.topic_id, set()).add(code_by_id[tp.prerequisite_id])
    topic_settings = {t.code: {"order": t.order_index, "min": t.min_hours, "max": t.max_hours, "priority": t.priority,
                               "prerequisites": frozenset(prereqs.get(t.id, set()))} for t in topic_objs}
    class_tb = {
        classes[cs.class_id] + (subjects[cs.subject_id],): (tbs.get(cs.textbook_id) if cs.textbook_id else None)
        for cs in db.scalars(select(m.ClassSubject))
    }
    results: dict[tuple, tuple] = {}
    granularity: dict[tuple, set[str]] = {}
    if assessments:
        a_ids = {a.id: a.code for a in db.scalars(select(m.Assessment).where(m.Assessment.code.in_(a_codes)))}
        t_ids = {t.id: t.code for t in db.scalars(select(m.Topic))}
        q = select(m.AssessmentResult.student_id, m.AssessmentResult.assessment_id, m.AssessmentResult.topic_id,
                   m.AssessmentResult.item_id, m.AssessmentResult.score, m.AssessmentResult.max_score).where(
            m.AssessmentResult.assessment_id.in_(a_ids.keys()))
        for sid, aid, tid, item, score, mx in db.execute(q):
            sk = student_key[sid]
            results[(sk[0], sk[1], a_ids[aid], t_ids[tid], item)] = (score, mx)
            granularity.setdefault((sk[0], sk[1], a_ids[aid], t_ids[tid]), set()).add(
                "total" if item == "_total" else "items")
    hours = {(classes[h.class_id][0], classes[h.class_id][1], code_by_id[h.topic_id]): h.hours
             for h in db.scalars(select(m.ClassTopicHours))}
    return ExistingState(topics, assessments, students, class_tb, results, classes=class_grade, textbooks=textbooks,
                         topic_settings=topic_settings, granularity=granularity, hours=hours)


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
    class_subjects: dict[tuple[int, int], m.ClassSubject] = {}
    new_topic_codes: set[str] = set()

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
            if textbooks[tb_code].subject_id != subj.id:
                raise ImportConflict(f"textbook subject conflict: {tb_code}")
        ck = (r["school"], r["class"])
        if ck not in classes:
            classes[ck] = get_or_create(m.SchoolClass, {"school_id": schools[r["school"]].id, "name": r["class"]},
                                        {"grade": r["grade"]})
            if classes[ck].grade != r["grade"]:  # validation rejects this; never write a contradictory record
                raise ImportConflict(f"class grade conflict: {r['class']}")
        cs_key = (classes[ck].id, subj.id)
        if cs_key not in class_subjects:  # one textbook assignment per (class, subject) pair
            cs = db.scalars(select(m.ClassSubject).filter_by(class_id=cs_key[0], subject_id=cs_key[1])).first()
            tb_id = textbooks[tb_code].id if tb_code else None
            if cs is None:
                cs = m.ClassSubject(class_id=cs_key[0], subject_id=cs_key[1], textbook_id=tb_id)
                db.add(cs)
                db.flush()
            elif cs.textbook_id != tb_id:
                raise ImportConflict(f"textbook assignment conflict: {r['class']}")
            class_subjects[cs_key] = cs
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
                new_topic_codes.add(r["topic_id"])
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

    # prerequisites: only for topics created by this import (settings of existing topics are changed explicitly)
    prereq_pairs = {(r["topic_id"], p) for r in rows if r["topic_id"] in new_topic_codes
                    for p in r["topic_prerequisites"]}
    for topic_code, prereq_code in sorted(prereq_pairs):
        t = topics[topic_code]
        pre = topics.get(prereq_code) or db.scalars(select(m.Topic).filter_by(code=prereq_code)).first()
        if pre is not None:
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
