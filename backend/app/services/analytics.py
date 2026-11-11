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


FAMILY_ALPHA = 0.05


def learning_gains(df: pd.DataFrame, min_pairs: int = 2) -> dict[int, dict[str, Any]]:
    """Paired pre/post gains per topic within each comparison group, with multiplicity control.

    Only students who took *both* a 'pre' and a 'post' assessment of the same comparison group on the
    same topic are paired. Unrelated tests (different groups, or topics not on both) are never compared.

    Multiple comparisons: the family is every topic in the current analysis view that has at least
    ``min_pairs`` pairs. Each topic's interval uses the Bonferroni level 1 − 0.05/k, and the direction
    (increase / decline / inconclusive) is read from that interval, so interval, adjusted p-value and
    conclusion always agree. Topics below ``min_pairs`` get direction "insufficient" and no test.
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
    groups = {int(t): grp for t, grp in paired.groupby("topic_id")}
    k = sum(1 for grp in groups.values() if len(grp) >= max(2, min_pairs))
    level = 1 - FAMILY_ALPHA / max(k, 1)
    out: dict[int, dict[str, Any]] = {}
    for topic_id, grp in groups.items():
        out[topic_id] = gain_stats(grp["pre"].to_numpy(), grp["post"].to_numpy(), min_pairs=min_pairs,
                                   ci_level=level, family_size=k)
        out[topic_id]["groups"] = sorted(grp["comparison_group"].unique().tolist())
    return out


def gain_stats(pre: np.ndarray, post: np.ndarray, min_pairs: int = 2, ci_level: float = 0.95,
               family_size: int = 1) -> dict[str, Any]:
    """Paired gain summary. ``direction`` is one of increase | decline | inconclusive | insufficient.

    A decline is never reported as progress; "inconclusive" means the interval includes zero, which is
    not evidence of no effect.
    """
    n = len(pre)
    gains = post - pre
    mean_pre, mean_post = float(np.mean(pre)), float(np.mean(post))
    mean_gain = float(np.mean(gains))
    def reported(value: float) -> float:
        # Preserve the sign when normal display rounding would turn a nonzero estimate/bound into zero.
        rounded = round(float(value), 1)
        return float(f"{value:.6g}") if value != 0 and rounded == 0 else rounded
    norm = (mean_post - mean_pre) / (100 - mean_pre) if mean_pre < 100 else None  # Hake's class-average gain
    base = {"n_paired": n, "pre_mean": r1(mean_pre), "post_mean": r1(mean_post), "mean_gain": reported(mean_gain),
            "normalized_gain": r1(norm, 3), "ci_level": round(ci_level * 100, 2), "family_size": family_size}
    if n < max(2, min_pairs):
        return base | {"ci_low": None, "ci_high": None, "p_value": None, "p_value_adjusted": None,
                       "significant": False, "direction": "insufficient"}
    sd = float(np.std(gains, ddof=1))
    if sd == 0:  # degenerate: every student changed by exactly the same amount
        lo = hi = mean_gain
        p = 0.0 if mean_gain != 0 else 1.0
    else:
        lo, hi = mean_ci(gains, conf=ci_level)
        p = float(stats.ttest_rel(post, pre).pvalue)
    p_adj = min(1.0, p * family_size)
    if lo > 0:
        direction = "increase"
    elif hi < 0:
        direction = "decline"
    else:
        direction = "inconclusive"
    return base | {"ci_low": reported(lo), "ci_high": reported(hi), "p_value": r1(p, 4), "p_value_adjusted": r1(p_adj, 4),
                   "significant": direction in ("increase", "decline"), "direction": direction}


def gain_direction(gain: dict[str, Any] | None) -> str | None:
    """Sign-aware direction; also derives it for legacy gain dicts that only carry 'significant' and 'mean_gain'."""
    if not gain:
        return None
    if gain.get("direction"):
        return gain["direction"]
    if gain.get("n_paired") is not None and gain["n_paired"] < 2:
        return "insufficient"
    if not gain.get("significant"):
        return "inconclusive"
    return "increase" if (gain.get("mean_gain") or 0) > 0 else "decline"


# --------------------------------------------------------------------------- topics


def classify_topic(mastery_pct: float | None, n_students: int, gain: dict[str, Any] | None,
                   s: AnalysisSettings) -> tuple[str, str]:
    """Return (status, interpretation_code). Never claims causation or 'instructional failure'."""
    if mastery_pct is None:
        return "no_outcome_data", "no_outcome_data"
    if n_students < s.min_students_topic:
        return "insufficient_data", "small_sample"
    direction = gain_direction(gain)
    if mastery_pct < s.difficult_threshold:
        status = "difficult"
    elif mastery_pct < s.watch_threshold:
        status = "watch"
    else:
        return ("ok", "ok_but_declining") if direction == "decline" else ("ok", "ok")
    if gain is None:
        return status, "low_no_baseline"
    return status, {"increase": "low_but_improving", "decline": "low_declining",
                    "inconclusive": "low_no_measurable_gain", "insufficient": "low_gain_insufficient"}[direction]


INTERPRETATION_RU = {
    "ok": "Освоение на уровне не ниже порога.",
    "ok_but_declining": "Освоение не ниже порога, но результат статистически значимо снизился по сравнению с "
                        "входной диагностикой. Причина по данным не установлена.",
    "no_outcome_data": "Нет итоговых/текущих оцениваний по теме — освоение не рассчитано.",
    "small_sample": "Слишком мало учеников для надёжного вывода.",
    "low_no_baseline": "Низкий результат. Нет входной диагностики, поэтому нельзя отличить слабую исходную "
                       "подготовку от трудностей обучения.",
    "low_gain_insufficient": "Низкий результат. Пар «входная–итоговая диагностика» слишком мало, чтобы оценить "
                             "динамику.",
    "low_but_improving": "Низкий результат, но после обучения зафиксирован статистически значимый прирост: "
                         "тема осваивается, но медленно.",
    "low_declining": "Низкий результат и статистически значимое СНИЖЕНИЕ по сравнению с входной диагностикой. "
                     "Нужен анализ причин; само по себе увеличение часов не устраняет снижение.",
    "low_no_measurable_gain": "Низкий результат; изменение по сравнению с входной диагностикой не установлено "
                              "(доверительный интервал включает ноль — это не доказывает отсутствие эффекта). "
                              "Сигнал для методического анализа; причина по данным не установлена.",
}

WEIGHTING_NOTE = ("mastery — объединённые баллы (Σ набранных / Σ максимальных; крупные оценивания и классы весят "
                  "больше); mean/median — по ученикам (каждый ученик с равным весом); class_mean — среднее "
                  "средних по классам (каждый класс с равным весом).")


def topic_analytics(df: pd.DataFrame, s: AnalysisSettings, hours: dict[int, float] | None = None) -> list[dict[str, Any]]:
    if df.empty:
        return []
    gains = learning_gains(df, min_pairs=s.min_students_topic)
    out_df = outcome(df)
    topics = df[["topic_id", "topic_code", "topic_name", "topic_order", "subject_name", "grade"]].drop_duplicates(
        "topic_id")
    student_class = df.drop_duplicates("student_id").set_index("student_id")["class_id"]
    result = []
    for _, t in topics.sort_values(["grade", "topic_order", "topic_code"]).iterrows():
        tid = int(t["topic_id"])
        sub = out_df[out_df["topic_id"] == tid]
        gain = gains.get(tid)
        if sub.empty:
            mast = None
            st = pd.DataFrame(columns=["student_id", "pct"])
        else:
            mast = mastery(sub["score"].sum(), sub["max_score"].sum())
            st = student_topic_pct(sub)
        vals = st["pct"].to_numpy(dtype=float)
        n_students = int(len(vals))
        class_mean = None
        if n_students:
            cls = st.assign(class_id=st["student_id"].map(student_class)).groupby("class_id")["pct"].mean()
            class_mean = float(cls.mean())
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
            "class_mean": r1(class_mean),
            "sd": r1(float(np.std(vals, ddof=1))) if n_students > 1 else None,
            "ci_low": r1(lo), "ci_high": r1(hi),
            "student_count": n_students,
            "class_count": int(sub["class_id"].nunique()) if not sub.empty else 0,
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
    # Population metadata: which grades sat each assessment and its pre/post comparison group. Different
    # assessments are separate observations (different pupils and/or content), not one longitudinal series.
    grades = df.groupby("assessment_id")["grade"].agg(lambda s: sorted({int(x) for x in s}))
    groups = df.groupby("assessment_id")["comparison_group"].first()
    return [
        {"assessment": r.assessment_code, "date": r.assessment_date.isoformat(), "kind": r.kind,
         "mastery": r1(r.score / r.max_score * 100), "students": int(r.students), "topics": int(r.topics),
         "grades": grades.get(r.assessment_id, []),
         "comparison_group": groups.get(r.assessment_id) if isinstance(groups.get(r.assessment_id), str) else None}
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
