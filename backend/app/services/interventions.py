"""Intervention lifecycle and outcome evaluation (closed loop).

Lifecycle (recommendation runs keep their own proposed → accepted/rejected review state):
    planned ─► implemented ─► awaiting_outcome ─► evaluated
    planned ─► cancelled;   implemented ─► cancelled
An intervention can only be created from an ACCEPTED run. Illegal transitions raise TransitionError.

Outcome evaluation compares, for the affected topics of the same subject and grade, outcome assessments dated
BEFORE the implementation date with those ON/AFTER it:
  * descriptive change of pooled mastery against the frozen baseline (from the snapshot taken at creation);
  * paired change for students observed in both periods (t-interval, Bonferroni over affected topics);
  * missingness (students lost/added) and whether the pre-period recomputation still matches the frozen baseline.
There is no comparison group, so the result is an observed association, never "proven impact".
"""
from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from app.services import analytics as an

TRANSITIONS: dict[str, set[str]] = {
    "planned": {"implemented", "cancelled"},
    "implemented": {"awaiting_outcome", "cancelled"},
    "awaiting_outcome": {"evaluated"},
    "evaluated": set(),
    "cancelled": set(),
}
STATUS_RU = {"planned": "Запланировано", "implemented": "Внедрено", "awaiting_outcome": "Ожидает данных",
             "evaluated": "Оценено", "cancelled": "Отменено"}
MIN_PAIRED = 5


class TransitionError(ValueError):
    def __init__(self, message: str, code: str = "INVALID_TRANSITION"):
        super().__init__(message)
        self.code = code


def check_transition(current: str, target: str) -> None:
    if target not in TRANSITIONS.get(current, set()):
        allowed = ", ".join(STATUS_RU[s] for s in sorted(TRANSITIONS.get(current, set()))) or "нет"
        raise TransitionError(f"Переход «{STATUS_RU.get(current, current)}» → «{STATUS_RU.get(target, target)}» "
                              f"недопустим. Допустимо: {allowed}.")


def frozen_baseline(run_result: dict[str, Any], topics: list[dict[str, Any]], meta: dict[str, Any]) -> dict[str, Any]:
    """Aggregate-only snapshot (no student identifiers) of the evidence the approved plan relied on."""
    by_id = {t["topic_id"]: t for t in topics}
    changes = [r for r in run_result["rows"] if abs(r["delta"]) > 1e-9]
    affected = [r["topic_id"] for r in changes] or [r["topic_id"] for r in run_result["rows"]
                                                    if (by_id.get(r["topic_id"]) or {}).get("status")
                                                    in ("difficult", "watch")]
    snap = []
    for tid in affected:
        t = by_id.get(tid) or {}
        g = t.get("gain") or {}
        snap.append({"topic_id": tid, "name": t.get("name") or next(
            (r["name"] for r in run_result["rows"] if r["topic_id"] == tid), str(tid)),
                     "mastery": t.get("mastery"), "student_count": t.get("student_count"),
                     "class_count": t.get("class_count"), "status": t.get("status"),
                     "gain_direction": g.get("direction"), "mean_gain": g.get("mean_gain")})
    return {"fingerprint": meta["fingerprint"], "revision": meta["revision"], "algorithm_version":
            meta["algorithm_version"], "captured_at": meta["generated_at"], "topics": snap,
            "hour_changes": [{"topic_id": r["topic_id"], "name": r["name"], "from": r["current_hours"],
                              "to": r["proposed_hours"], "delta": r["delta"]} for r in changes]}


def _pct_by_student(df: pd.DataFrame) -> pd.DataFrame:
    return an.student_topic_pct(df) if not df.empty else pd.DataFrame(columns=["student_id", "topic_id", "pct"])


def evaluate(df: pd.DataFrame, baseline: dict[str, Any], implemented_on: date) -> dict[str, Any]:
    """Outcome evaluation of an implemented intervention. ``df`` = load_results for the subject and grade."""
    topic_ids = [t["topic_id"] for t in baseline["topics"]]
    out = an.outcome(df)
    out = out[out["topic_id"].isin(topic_ids)] if not out.empty else out
    before = out[out["assessment_date"] < implemented_on] if not out.empty else out
    after = out[out["assessment_date"] >= implemented_on] if not out.empty else out
    k = max(1, len(topic_ids))
    level = 1 - 0.05 / k
    rows = []
    for bt in baseline["topics"]:
        tid = bt["topic_id"]
        b = before[before["topic_id"] == tid] if not before.empty else before
        a = after[after["topic_id"] == tid] if not after.empty else after
        m_before = an.mastery(b["score"].sum(), b["max_score"].sum()) if not b.empty else None
        m_after = an.mastery(a["score"].sum(), a["max_score"].sum()) if not a.empty else None
        pb, pa = _pct_by_student(b), _pct_by_student(a)
        paired = pb.merge(pa, on=["student_id", "topic_id"], suffixes=("_b", "_a"))
        n_b, n_a, n_p = int(pb["student_id"].nunique()), int(pa["student_id"].nunique()), int(len(paired))
        row: dict[str, Any] = {
            "topic_id": tid, "name": bt["name"], "frozen_mastery": bt["mastery"],
            "recomputed_before": an.r1(m_before), "after": an.r1(m_after),
            "descriptive_change": an.r1(m_after - bt["mastery"]) if m_after is not None and bt["mastery"] is not None
            else None,
            "students_before": n_b, "students_after": n_a, "paired_students": n_p,
            "lost_to_follow_up": max(0, n_b - n_p), "new_students": max(0, n_a - n_p),
            "baseline_consistent": (bt["mastery"] is None or m_before is None or abs(an.r1(m_before) - bt["mastery"]) < 0.05),
            "paired": None, "direction": "no_outcome_data" if m_after is None else "insufficient",
        }
        if n_p >= MIN_PAIRED:
            g = an.gain_stats(paired["pct_b"].to_numpy(dtype=float), paired["pct_a"].to_numpy(dtype=float),
                              min_pairs=MIN_PAIRED, ci_level=level, family_size=k)
            row["paired"] = {k2: g[k2] for k2 in ("mean_gain", "ci_low", "ci_high", "ci_level", "p_value_adjusted",
                                                   "n_paired")}
            row["direction"] = g["direction"]
        rows.append(row)
    has_after = any(r["after"] is not None for r in rows)
    statements = {
        "design": "До/после без группы сравнения (одна параллель, нерандомизированное внедрение).",
        "causal": "Результат описывает наблюдаемое изменение после внедрения. Он НЕ доказывает, что изменение "
                  "вызвано вмешательством: на результат влияют сложность заданий, состав учеников, время года и "
                  "другие факторы.",
        "inconclusive": "Если интервал включает ноль, изменение не установлено; это не доказательство отсутствия "
                        "эффекта.",
    }
    return {"ready": has_after, "implemented_on": implemented_on.isoformat(), "ci_level": round(level * 100, 2),
            "family_size": k, "comparison_group": None, "topics": rows, "statements": statements,
            "baseline_fingerprint": baseline.get("fingerprint")}
