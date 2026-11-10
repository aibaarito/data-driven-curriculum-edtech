"""Deterministic analytics. All formulas are documented in docs/ANALYTICS.md.

Core formula — topic mastery:
    mastery = Σ obtained points / Σ available points × 100
computed over *outcome* assessments (kind 'post' or 'current'). 'pre' diagnostics measure the
starting level before instruction, so they are used only as a baseline for learning gains.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app import models as m
from app.services.settings_store import AnalysisSettings

OUTCOME_KINDS = ("post", "current")
BINS = list(range(0, 101, 10))
COLUMNS = [
    "student_id", "student_ext", "class_id", "class_name", "grade", "subject_id", "subject_name", "topic_id",
    "topic_code", "topic_name", "topic_order", "assessment_id", "assessment_code", "assessment_date", "kind",
    "comparison_group", "textbook_id", "textbook_code", "textbook_name", "item_id", "score", "max_score",
]


@dataclass
class Filters:
    subject_id: int | None = None
    grade: int | None = None
    class_id: int | None = None
    textbook_id: int | None = None
    date_from: date | None = None
    date_to: date | None = None

    def as_dict(self) -> dict[str, Any]:
        return {k: (v.isoformat() if isinstance(v, date) else v) for k, v in self.__dict__.items()}


def load_results(db: Session, f: Filters) -> pd.DataFrame:
    r, s, c, a, t, sub = m.AssessmentResult, m.Student, m.SchoolClass, m.Assessment, m.Topic, m.Subject
    cs, tb = m.ClassSubject, m.Textbook
    q = (
        select(
            r.student_id, s.external_id, c.id, c.name, c.grade, sub.id, sub.name, t.id, t.code, t.name,
            t.order_index, a.id, a.code, a.assessment_date, a.kind, a.comparison_group, tb.id, tb.code, tb.name,
            r.item_id, r.score, r.max_score,
        )
        .join(s, s.id == r.student_id)
        .join(c, c.id == s.class_id)
        .join(a, a.id == r.assessment_id)
        .join(t, t.id == r.topic_id)
        .join(sub, sub.id == t.subject_id)
        .outerjoin(cs, and_(cs.class_id == c.id, cs.subject_id == t.subject_id))
        .outerjoin(tb, tb.id == cs.textbook_id)
    )
    if f.subject_id is not None:
        q = q.where(t.subject_id == f.subject_id)
    if f.grade is not None:
        q = q.where(c.grade == f.grade)
    if f.class_id is not None:
        q = q.where(c.id == f.class_id)
    if f.textbook_id is not None:
        q = q.where(cs.textbook_id == f.textbook_id)
    if f.date_from is not None:
        q = q.where(a.assessment_date >= f.date_from)
    if f.date_to is not None:
        q = q.where(a.assessment_date <= f.date_to)
    rows = db.execute(q).all()
    df = pd.DataFrame(rows, columns=COLUMNS)
    if not df.empty:
        df["score"] = df["score"].astype(float)
        df["max_score"] = df["max_score"].astype(float)
    return df


# --------------------------------------------------------------------------- primitives


def mastery(score_sum: float, max_sum: float) -> float | None:
    """Σ obtained / Σ available × 100. Returns None when nothing was available (no division by zero)."""
    if max_sum is None or max_sum <= 0:
        return None
    if score_sum < 0 or score_sum > max_sum + 1e-9:
        raise ValueError("Obtained points must be within [0, available points].")
    return score_sum / max_sum * 100.0


def r1(x: float | None, nd: int = 1) -> float | None:
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return None
    return round(float(x), nd)


def mean_ci(values: np.ndarray, conf: float = 0.95) -> tuple[float | None, float | None]:
    n = len(values)
    if n < 2:
        return None, None
    sd = float(np.std(values, ddof=1))
    if sd == 0:
        mu = float(np.mean(values))
        return mu, mu
    se = sd / np.sqrt(n)
    h = float(stats.t.ppf((1 + conf) / 2, n - 1)) * se
    mu = float(np.mean(values))
    return mu - h, mu + h


def distribution(values: np.ndarray) -> list[dict[str, Any]]:
    counts, _ = np.histogram(np.clip(values, 0, 100), bins=BINS)
    return [{"bin": f"{BINS[i]}–{BINS[i + 1]}", "from": BINS[i], "to": BINS[i + 1], "count": int(counts[i])}
            for i in range(len(counts))]


def student_topic_pct(df: pd.DataFrame) -> pd.DataFrame:
    """Per student × topic percentage over all given records (items aggregated by points)."""
    g = df.groupby(["student_id", "topic_id"], as_index=False)[["score", "max_score"]].sum()
    g = g[g["max_score"] > 0]
    g["pct"] = g["score"] / g["max_score"] * 100.0
    return g


def outcome(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["kind"].isin(OUTCOME_KINDS)]


# --------------------------------------------------------------------------- overview


def overview(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {"has_data": False, "students": 0, "assessments": 0, "results": 0, "classes": 0, "topics": 0,
                "textbooks": 0, "average_mastery": None, "outcome_points": 0, "date_from": None, "date_to": None}
    out = outcome(df)
    avg = mastery(out["score"].sum(), out["max_score"].sum()) if not out.empty else None
    return {
        "has_data": True,
        "students": int(df["student_id"].nunique()),
        "assessments": int(df["assessment_id"].nunique()),
        "results": int(len(df)),
        "classes": int(df["class_id"].nunique()),
        "topics": int(df["topic_id"].nunique()),
        "textbooks": int(df["textbook_id"].dropna().nunique()),
        "average_mastery": r1(avg),
        "outcome_points": float(out["max_score"].sum()) if not out.empty else 0,
        "date_from": df["assessment_date"].min().isoformat(),
        "date_to": df["assessment_date"].max().isoformat(),
    }


# --------------------------------------------------------------------------- learning gains


def learning_gains(df: pd.DataFrame) -> dict[int, dict[str, Any]]:
    """Paired pre/post gains per topic within each comparison group.

    Only students who took *both* a 'pre' and a 'post' assessment of the same comparison group on the
    same topic are paired. Unrelated tests (different groups, or topics not on both) are never compared.
    """
    pp = df[df["kind"].isin(("pre", "post")) & df["comparison_group"].notna()]
    if pp.empty:
        return {}
    g = pp.groupby(["comparison_group", "kind", "student_id", "topic_id"], as_index=False)[["score", "max_score"]].sum()
    g = g[g["max_score"] > 0]
    g["pct"] = g["score"] / g["max_score"] * 100
    pre = g[g["kind"] == "pre"][["comparison_group", "student_id", "topic_id", "pct"]].rename(columns={"pct": "pre"})
    post = g[g["kind"] == "post"][["comparison_group", "student_id", "topic_id", "pct"]].rename(columns={"pct": "post"})
    paired = pre.merge(post, on=["comparison_group", "student_id", "topic_id"], how="inner")
    out: dict[int, dict[str, Any]] = {}
    for topic_id, grp in paired.groupby("topic_id"):
        out[int(topic_id)] = gain_stats(grp["pre"].to_numpy(), grp["post"].to_numpy())
        out[int(topic_id)]["groups"] = sorted(grp["comparison_group"].unique().tolist())
    return out


def gain_stats(pre: np.ndarray, post: np.ndarray) -> dict[str, Any]:
    n = len(pre)
    gains = post - pre
    mean_pre, mean_post = float(np.mean(pre)), float(np.mean(post))
    mean_gain = float(np.mean(gains))
    lo, hi = mean_ci(gains)
    p = None
    if n >= 2 and np.std(gains, ddof=1) > 0:
        p = float(stats.ttest_rel(post, pre).pvalue)
    norm = (mean_post - mean_pre) / (100 - mean_pre) if mean_pre < 100 else None  # Hake's class-average gain
    significant = lo is not None and (lo > 0 or hi < 0)
    return {
        "n_paired": n, "pre_mean": r1(mean_pre), "post_mean": r1(mean_post), "mean_gain": r1(mean_gain),
        "ci_low": r1(lo), "ci_high": r1(hi), "p_value": r1(p, 4) if p is not None else None,
        "normalized_gain": r1(norm, 3), "significant": bool(significant),
    }


# --------------------------------------------------------------------------- topics


def classify_topic(mastery_pct: float | None, n_students: int, gain: dict[str, Any] | None,
                   s: AnalysisSettings) -> tuple[str, str]:
    """Return (status, interpretation_code). Never claims causation or 'instructional failure'."""
    if mastery_pct is None:
        return "no_outcome_data", "no_outcome_data"
    if n_students < s.min_students_topic:
        return "insufficient_data", "small_sample"
    if mastery_pct < s.difficult_threshold:
        status = "difficult"
    elif mastery_pct < s.watch_threshold:
        status = "watch"
    else:
        return "ok", "ok"
    if gain is None:
        return status, "low_no_baseline"
    if gain["significant"] and (gain["mean_gain"] or 0) > 0:
        return status, "low_but_improving"
    return status, "low_no_measurable_gain"


INTERPRETATION_RU = {
    "ok": "Освоение на уровне не ниже порога.",
    "no_outcome_data": "Нет итоговых/текущих оцениваний по теме — освоение не рассчитано.",
    "small_sample": "Слишком мало учеников для надёжного вывода.",
    "low_no_baseline": "Низкий результат. Нет входной диагностики, поэтому нельзя отличить слабую исходную "
                       "подготовку от трудностей обучения.",
    "low_but_improving": "Низкий результат, но после обучения зафиксирован статистически значимый прирост: "
                         "тема осваивается, но медленно.",
    "low_no_measurable_gain": "Низкий результат и нет статистически значимого прироста. Это сигнал для "
                              "методического анализа; причина по данным не установлена.",
}


def topic_analytics(df: pd.DataFrame, s: AnalysisSettings, hours: dict[int, float] | None = None) -> list[dict[str, Any]]:
    if df.empty:
        return []
    gains = learning_gains(df)
    out_df = outcome(df)
    topics = df[["topic_id", "topic_code", "topic_name", "topic_order", "subject_name", "grade"]].drop_duplicates(
        "topic_id")
    result = []
    for _, t in topics.sort_values(["grade", "topic_order", "topic_code"]).iterrows():
        tid = int(t["topic_id"])
        sub = out_df[out_df["topic_id"] == tid]
        gain = gains.get(tid)
        if sub.empty:
            mast = None
            st = pd.DataFrame(columns=["pct"])
        else:
            mast = mastery(sub["score"].sum(), sub["max_score"].sum())
            st = student_topic_pct(sub)
        vals = st["pct"].to_numpy(dtype=float)
        n_students = int(len(vals))
        status, interp = classify_topic(mast, n_students, gain, s)
        lo, hi = mean_ci(vals) if n_students else (None, None)
        result.append({
            "topic_id": tid,
            "code": t["topic_code"],
            "name": t["topic_name"],
            "order": int(t["topic_order"]),
            "grade": int(t["grade"]),
            "mastery": r1(mast),
            "mean": r1(float(np.mean(vals))) if n_students else None,
            "median": r1(float(np.median(vals))) if n_students else None,
            "sd": r1(float(np.std(vals, ddof=1))) if n_students > 1 else None,
            "ci_low": r1(lo), "ci_high": r1(hi),
            "student_count": n_students,
            "assessment_count": int(sub["assessment_id"].nunique()) if not sub.empty else 0,
            "result_count": int(len(sub)),
            "distribution": distribution(vals) if n_students else [],
            "gain": gain,
            "status": status,
            "interpretation_code": interp,
            "interpretation": INTERPRETATION_RU[interp],
            "hours": r1(hours.get(tid)) if hours and tid in hours else None,
        })
    return result


def topic_trends(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Mastery per assessment (chronological) for every topic, labelled by assessment kind."""
    if df.empty:
        return []
    g = df.groupby(["assessment_id", "assessment_code", "assessment_date", "kind", "topic_id"], as_index=False)[
        ["score", "max_score"]].sum()
    n = df.groupby(["assessment_id", "topic_id"])["student_id"].nunique().rename("n").reset_index()
    g = g.merge(n, on=["assessment_id", "topic_id"])
    g = g[g["max_score"] > 0].sort_values(["assessment_date", "assessment_code"])
    return [
        {"assessment_id": int(r.assessment_id), "assessment": r.assessment_code, "date": r.assessment_date.isoformat(),
         "kind": r.kind, "topic_id": int(r.topic_id), "mastery": r1(r.score / r.max_score * 100), "students": int(r.n)}
        for r in g.itertuples()
    ]


def overall_trend(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df.empty:
        return []
    g = df.groupby(["assessment_id", "assessment_code", "assessment_date", "kind"], as_index=False).agg(
        score=("score", "sum"), max_score=("max_score", "sum"), students=("student_id", "nunique"),
        topics=("topic_id", "nunique"))
    g = g[g["max_score"] > 0].sort_values(["assessment_date", "assessment_code"])
    return [
        {"assessment": r.assessment_code, "date": r.assessment_date.isoformat(), "kind": r.kind,
         "mastery": r1(r.score / r.max_score * 100), "students": int(r.students), "topics": int(r.topics)}
        for r in g.itertuples()
    ]


def mean_hours_by_topic(db: Session, f: Filters) -> dict[int, float]:
    h, c, t = m.ClassTopicHours, m.SchoolClass, m.Topic
    q = select(h.topic_id, h.hours, h.class_id).join(c, c.id == h.class_id).join(t, t.id == h.topic_id)
    if f.subject_id is not None:
        q = q.where(t.subject_id == f.subject_id)
    if f.grade is not None:
        q = q.where(c.grade == f.grade)
    if f.class_id is not None:
        q = q.where(c.id == f.class_id)
    if f.textbook_id is not None:
        q = q.join(m.ClassSubject, and_(m.ClassSubject.class_id == c.id, m.ClassSubject.subject_id == t.subject_id)
                   ).where(m.ClassSubject.textbook_id == f.textbook_id)
    rows = db.execute(q).all()
    acc: dict[int, list[float]] = {}
    for tid, hours, _ in rows:
        acc.setdefault(tid, []).append(hours)
    return {k: float(np.mean(v)) for k, v in acc.items()}
