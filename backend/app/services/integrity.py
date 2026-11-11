"""Integrity checks for data imported before the import-integrity fixes, plus explicit, opt-in repairs.

Checks are read-only. Repairs never invent facts:
* missing (class, subject) textbook assignments are created with textbook = NULL ("not specified"), so the
  class is visibly excluded from textbook comparison instead of silently disappearing;
* stored validation messages that echoed raw identifiers are rewritten to the redacted wording;
* expired previews have their staged rows purged.
Mixed topic-total/item-level results and class/topic grade mismatches are only REPORTED: deciding which rows are
correct needs a human.
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.previews import purge_expired

LEGACY_ECHO = re.compile(r"«[^»]*»")
REDACTED_MESSAGES = {
    "INVALID_IDENTIFIER": "Недопустимый идентификатор (значение не показывается).",
    "INVALID_GRADE": "Параллель должна быть целым числом от 1 до 12.",
    "INVALID_DATE": "Неверная дата (ожидается ГГГГ-ММ-ДД или ДД.ММ.ГГГГ).",
    "INVALID_NUMBER": "Значение не распознано как число.",
    "INVALID_TOPIC_SETTING": "Недопустимое значение параметра темы.",
}

Q_MISSING_ASSIGNMENT = """
SELECT DISTINCT s.class_id, t.subject_id FROM assessment_results r
JOIN students s ON s.id = r.student_id JOIN topics t ON t.id = r.topic_id
LEFT JOIN class_subjects cs ON cs.class_id = s.class_id AND cs.subject_id = t.subject_id
WHERE cs.id IS NULL"""
Q_MIXED = """
SELECT student_id, assessment_id, topic_id FROM assessment_results
GROUP BY student_id, assessment_id, topic_id
HAVING bool_or(item_id = '_total') AND bool_or(item_id <> '_total')"""
Q_TB_SUBJECT = """
SELECT cs.id, cs.class_id, cs.subject_id, tb.subject_id AS textbook_subject FROM class_subjects cs
JOIN textbooks tb ON tb.id = cs.textbook_id WHERE tb.subject_id <> cs.subject_id"""
Q_GRADE = """
SELECT DISTINCT c.id AS class_id, c.grade AS class_grade, t.id AS topic_id, t.grade AS topic_grade
FROM assessment_results r JOIN students s ON s.id = r.student_id JOIN classes c ON c.id = s.class_id
JOIN topics t ON t.id = r.topic_id WHERE c.grade <> t.grade"""
Q_LEGACY_VALIDATION = """
SELECT id FROM import_batches WHERE validation::text LIKE '%Недопустимый идентификатор «%'
   OR validation::text LIKE '%(получено «%' OR validation::text LIKE '%Неверная дата «%'
   OR validation::text LIKE '%Балл «%' OR validation::text LIKE '%Недопустимое значение «%'"""
Q_STALE_PREVIEW = """
SELECT id FROM import_batches WHERE status = 'preview' AND staged_rows IS NOT NULL
  AND (expires_at IS NULL OR expires_at < now())"""


def run_integrity_checks(db: Session) -> dict[str, Any]:
    def rows(q: str) -> list[dict[str, Any]]:
        return [dict(r._mapping) for r in db.execute(text(q))]

    checks = {
        "missing_textbook_assignment": rows(Q_MISSING_ASSIGNMENT),
        "mixed_granularity_results": rows(Q_MIXED),
        "textbook_subject_mismatch": rows(Q_TB_SUBJECT),
        "class_topic_grade_mismatch": rows(Q_GRADE),
        "validation_with_echoed_values": rows(Q_LEGACY_VALIDATION),
        "stale_previews_with_staged_rows": rows(Q_STALE_PREVIEW),
    }
    return {
        "ok": not any(checks.values()),
        "counts": {k: len(v) for k, v in checks.items()},
        "samples": {k: v[:20] for k, v in checks.items()},  # internal numeric ids only, no student identifiers
    }


def redact_validation_payload(validation: dict[str, Any]) -> dict[str, Any]:
    out = dict(validation)
    for key in ("errors", "warnings"):
        cleaned = []
        for issue in validation.get(key) or []:
            issue = dict(issue)
            if LEGACY_ECHO.search(issue.get("message") or ""):
                issue["message"] = REDACTED_MESSAGES.get(issue.get("code"), "Значение не показывается.")
            cleaned.append(issue)
        out[key] = cleaned
    out["preview"] = []  # legacy previews may contain raw rows
    return out


def repair(db: Session, *, add_missing_assignments: bool, redact_validation: bool, purge_previews: bool
           ) -> dict[str, int]:
    done = {"assignments_added": 0, "validations_redacted": 0, "previews_purged": 0}
    if add_missing_assignments:
        for r in db.execute(text(Q_MISSING_ASSIGNMENT)):
            db.execute(text("INSERT INTO class_subjects (class_id, subject_id, textbook_id) VALUES (:c, :s, NULL)"),
                       {"c": r.class_id, "s": r.subject_id})
            done["assignments_added"] += 1
    if redact_validation:
        from app import models as m
        for (bid,) in db.execute(text(Q_LEGACY_VALIDATION)).all():
            batch = db.get(m.ImportBatch, bid)
            batch.validation = redact_validation_payload(batch.validation)
            done["validations_redacted"] += 1
    db.commit()
    if purge_previews:
        db.execute(text("UPDATE import_batches SET status = 'expired', staged_rows = NULL "
                        "WHERE status = 'preview' AND (expires_at IS NULL OR expires_at < now())"))
        db.commit()
        done["previews_purged"] = purge_expired(db)
    return done
