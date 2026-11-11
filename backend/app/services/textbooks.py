"""Statistically cautious textbook comparison (class-level inference).

Study design: a textbook is assigned to whole classes, so students in one class are not independent (shared
teacher, timetable, peers). The number of independent replicates is the number of CLASSES, not students.
Therefore:
* Descriptive figures (student-level means, medians, distributions, Hedges' g) are reported as descriptions only.
* All inferential statements (confidence intervals, p-values, verdicts) are computed with classes as the unit:
  - adjusted difference: OLS on class means, y_c = b0 + b1*textbook_c + b2*baseline_c (+ grade dummies),
    classical standard errors, t distribution with df = G - p (G classes, p parameters);
  - gain difference: Welch test on class-mean gains (post% - pre%), Satterthwaite df;
  - raw difference: Welch test on class means of the outcome.
  Classes enter with equal weight (unweighted class means) because each class is one replicate of a
  textbook; classes with fewer than MIN_CLASS_SIZE students with data are excluded and reported.
* Only outcome items (assessment x topic) taken by students of both textbooks are used.
* When several textbook pairs are compared in one view, intervals use the Bonferroni level 1 - 0.05/m.
* Verdict "observed_difference" requires: >= max(settings, 3) eligible classes per textbook, enough students,
  a baseline, estimable class-level models, and BOTH the adjusted and the gain interval excluding zero with the
  same sign. Results from fewer than 10 classes in total are labelled exploratory. A verdict describes an
  association in non-randomised data, never a causal effect of the textbook.
"""
from __future__ import annotations

from itertools import combinations
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from app.services.analytics import distribution, mean_ci, outcome, r1
from app.services.settings_store import MIN_CLASSES_FOR_INFERENCE, AnalysisSettings

INSUFFICIENT_TEXT = "Недостаточно данных, чтобы определить, какой учебник эффективнее."
MIN_CLASS_SIZE = 5
EXPLORATORY_BELOW_CLASSES = 10
ALPHA = 0.05


def _items(df: pd.DataFrame) -> set[tuple[int, int]]:
    return set(map(tuple, df[["assessment_id", "topic_id"]].drop_duplicates().to_numpy().tolist()))


def _restrict(df: pd.DataFrame, items: set[tuple[int, int]]) -> pd.DataFrame:
    if not items:
        return df.iloc[0:0]
    key = pd.MultiIndex.from_frame(df[["assessment_id", "topic_id"]])
    return df[key.isin(list(items))]


def _student_pct(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby(["student_id", "class_id", "grade", "textbook_id"], as_index=False)[["score", "max_score"]].sum()
    g = g[g["max_score"] > 0]
    g["pct"] = g["score"] / g["max_score"] * 100
    return g


def student_gains(df: pd.DataFrame, topics: set[int] | None = None) -> pd.DataFrame:
    """Per-student learning gain (post% − pre%) over the given topics, paired within a comparison group.

    A student contributes only topics present in BOTH their pre and post assessments of the same group,
    so the two percentages measure the same content.
    """
    pp = df[df["kind"].isin(("pre", "post")) & df["comparison_group"].notna()]
    if topics is not None:
        pp = pp[pp["topic_id"].isin(topics)]
    cols = ["student_id", "class_id", "grade", "textbook_id", "gain", "pre", "post"]
    if pp.empty:
        return pd.DataFrame(columns=cols)
    g = pp.groupby(["comparison_group", "kind", "student_id", "class_id", "grade", "textbook_id", "topic_id"],
                   as_index=False)[["score", "max_score"]].sum()
    pre = g[g["kind"] == "pre"].drop(columns="kind")
    post = g[g["kind"] == "post"].drop(columns="kind")
    keys = ["comparison_group", "student_id", "class_id", "grade", "textbook_id", "topic_id"]
    paired = pre.merge(post, on=keys, suffixes=("_pre", "_post"))
    if paired.empty:
        return pd.DataFrame(columns=cols)
    agg = paired.groupby(["student_id", "class_id", "grade", "textbook_id"], as_index=False)[
        ["score_pre", "max_score_pre", "score_post", "max_score_post"]].sum()
    agg = agg[(agg["max_score_pre"] > 0) & (agg["max_score_post"] > 0)]
    agg["pre"] = agg["score_pre"] / agg["max_score_pre"] * 100
    agg["post"] = agg["score_post"] / agg["max_score_post"] * 100
    agg["gain"] = agg["post"] - agg["pre"]
    return agg[cols]


def hedges_g(a: np.ndarray, b: np.ndarray) -> float | None:
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return None
    sp = np.sqrt(((na - 1) * np.var(a, ddof=1) + (nb - 1) * np.var(b, ddof=1)) / (na + nb - 2))
    if sp == 0:
        return 0.0 if np.mean(a) == np.mean(b) else None
    d = (np.mean(b) - np.mean(a)) / sp
    return float(d * (1 - 3 / (4 * (na + nb) - 9)))


def welch(a: np.ndarray, b: np.ndarray, level: float = 0.95) -> dict[str, Any] | None:
    """Difference of means (b - a) with a Welch interval at ``level``. None if not estimable."""
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if len(a) < 2 or len(b) < 2:
        return None
    va, vb = np.var(a, ddof=1) / len(a), np.var(b, ddof=1) / len(b)
    se = float(np.sqrt(va + vb))
    if se == 0:
        return None  # no between-unit variation: uncertainty cannot be estimated
    diff = float(np.mean(b) - np.mean(a))
    dof = float((va + vb) ** 2 / (va**2 / (len(a) - 1) + vb**2 / (len(b) - 1)))
    h = float(stats.t.ppf(1 - (1 - level) / 2, dof)) * se
    p = float(2 * stats.t.sf(abs(diff / se), dof))
    return {"diff": r1(diff), "se": r1(se, 2), "ci_low": r1(diff - h), "ci_high": r1(diff + h), "p_value": r1(p, 4),
            "df": r1(dof, 1), "ci_level": round(level * 100, 2)}


def ols_coef(y: np.ndarray, X: np.ndarray, coef: int, level: float = 0.95) -> dict[str, Any] | None:
    """Classical OLS estimate for column ``coef`` with t(n - p) interval. None if df < 2 or not estimable."""
    n, k = X.shape
    dof = n - k
    if dof < 2 or np.linalg.matrix_rank(X) < k:
        return None
    XtX_inv = np.linalg.inv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    resid = y - X @ beta
    sigma2 = float(resid @ resid) / dof
    se = float(np.sqrt(sigma2 * XtX_inv[coef, coef]))
    if se == 0:
        return None
    est = float(beta[coef])
    h = float(stats.t.ppf(1 - (1 - level) / 2, dof)) * se
    p = float(2 * stats.t.sf(abs(est / se), dof))
    return {"diff": r1(est), "se": r1(se, 2), "ci_low": r1(est - h), "ci_high": r1(est + h), "p_value": r1(p, 4),
            "df": dof, "ci_level": round(level * 100, 2)}


def _excludes_zero(e: dict[str, Any] | None) -> bool:
    return e is not None and e["ci_low"] is not None and (e["ci_low"] > 0 or e["ci_high"] < 0)


def compare_textbooks(df: pd.DataFrame, s: AnalysisSettings, hours_by_class: dict[int, float] | None = None
                      ) -> dict[str, Any]:
    hours_by_class = hours_by_class or {}
    df = df[df["textbook_id"].notna()].copy()
    if df.empty:
        return {"textbooks": [], "pairs": [], "topic_matrix": [], "common_items": 0, "comparable": False,
                "message": "Нет данных с указанными учебниками для выбранных фильтров."}
    df["textbook_id"] = df["textbook_id"].astype(int)
    meta = df[["textbook_id", "textbook_code", "textbook_name"]].drop_duplicates("textbook_id").sort_values("textbook_code")
    tb_ids = meta["textbook_id"].tolist()
    out_df = outcome(df)
    item_sets = {t: _items(out_df[out_df["textbook_id"] == t]) for t in tb_ids}
    common_all = set.intersection(*item_sets.values()) if item_sets else set()
    comparable = len(tb_ids) >= 2 and bool(common_all)
    base_df = _restrict(out_df, common_all) if comparable else out_df

    summaries = []
    for _, t in meta.iterrows():
        tid = int(t["textbook_id"])
        sub = df[df["textbook_id"] == tid]
        st = _student_pct(base_df[base_df["textbook_id"] == tid])
        vals = st["pct"].to_numpy()
        lo, hi = mean_ci(vals)
        pre = df[(df["textbook_id"] == tid) & (df["kind"] == "pre")]
        pre_st = _student_pct(pre)
        classes = sorted(sub["class_id"].unique().tolist())
        class_hours = [hours_by_class[c] for c in classes if c in hours_by_class]
        gains = student_gains(sub)
        class_gains = gains.groupby("class_id")["gain"].mean().to_numpy(dtype=float) if not gains.empty else np.array([])
        summaries.append({
            "textbook_id": tid, "code": t["textbook_code"], "name": t["textbook_name"],
            "students": int(sub["student_id"].nunique()), "classes": len(classes),
            "class_names": sorted(sub["class_name"].unique().tolist()),
            "grades": sorted(int(g) for g in sub["grade"].unique()),
            "outcome_students": int(len(vals)),
            # descriptive, student-level (each student weighted equally); the CI ignores clustering
            "mean": r1(float(np.mean(vals))) if len(vals) else None,
            "median": r1(float(np.median(vals))) if len(vals) else None,
            "sd": r1(float(np.std(vals, ddof=1))) if len(vals) > 1 else None,
            "ci_low": r1(lo), "ci_high": r1(hi),
            "distribution": distribution(vals) if len(vals) else [],
            "baseline_mean": r1(float(pre_st["pct"].mean())) if not pre_st.empty else None,
            "baseline_students": int(len(pre_st)),
            "mean_hours_per_class": r1(float(np.mean(class_hours))) if class_hours else None,
            "mean_class_size": r1(sub["student_id"].nunique() / len(classes)) if classes else None,
            "gain_mean": r1(float(gains["gain"].mean())) if not gains.empty else None,
            # class-level summary of gains (each class weighted equally)
            "gain_class_mean": r1(float(np.mean(class_gains))) if len(class_gains) else None,
            "gain_ci_low": None, "gain_ci_high": None,
            "gain_students": int(len(gains)),
            "descriptive_note": "Описательные показатели по ученикам; интервалы не учитывают группировку по классам.",
        })
        if len(class_gains) >= 2:
            g_lo, g_hi = mean_ci(class_gains)
            summaries[-1]["gain_ci_low"], summaries[-1]["gain_ci_high"] = r1(g_lo), r1(g_hi)

    topic_matrix = []
    if comparable:
        for (tid_topic, name, order), grp in base_df.groupby(["topic_id", "topic_name", "topic_order"]):
            row: dict[str, Any] = {"topic_id": int(tid_topic), "name": name, "order": int(order), "values": {}}
            for tb in tb_ids:
                g2 = grp[grp["textbook_id"] == tb]
                if g2["max_score"].sum() > 0:
                    row["values"][str(tb)] = {"mastery": r1(g2["score"].sum() / g2["max_score"].sum() * 100),
                                              "students": int(g2["student_id"].nunique())}
            topic_matrix.append(row)
        topic_matrix.sort(key=lambda r: (r["order"], r["name"]))

    grades = {t: set(df[df["textbook_id"] == t]["grade"].unique().tolist()) for t in tb_ids}
    subjects = {t: set(df[df["textbook_id"] == t]["subject_id"].unique().tolist()) for t in tb_ids}
    pair_ids = [(a, b) for a, b in combinations(tb_ids, 2) if grades[a] & grades[b] and subjects[a] & subjects[b]]
    level = 1 - ALPHA / max(len(pair_ids), 1)
    pairs = [_compare_pair(df, out_df, a, b, item_sets, meta, summaries, s, level, len(pair_ids))
             for a, b in pair_ids]
    return {"textbooks": summaries, "pairs": pairs, "topic_matrix": topic_matrix, "common_items": len(common_all),
            "comparable": comparable, "inference_unit": "class",
            "message": None if comparable else "У учебников нет общих итоговых заданий — прямое сравнение невозможно."}


def _class_table(df: pd.DataFrame, out_df: pd.DataFrame, a: int, b: int, common: set, grades: set) -> pd.DataFrame:
    """One row per class: outcome mean, baseline mean and gain mean over the common items/topics."""
    common_topics = {t for _, t in common}
    st = _student_pct(_restrict(out_df[out_df["textbook_id"].isin([a, b])], common))
    pre = df[(df["kind"] == "pre") & df["textbook_id"].isin([a, b]) & df["topic_id"].isin(common_topics)]
    pre_st = _student_pct(pre)[["student_id", "pct"]].rename(columns={"pct": "pre"})
    gains = student_gains(df[df["textbook_id"].isin([a, b])], common_topics)[["student_id", "gain"]]
    st = st.merge(pre_st, on="student_id", how="left").merge(gains, on="student_id", how="left")
    st = st[st["grade"].isin(grades)]
    return st.groupby(["class_id", "textbook_id", "grade"], as_index=False).agg(
        n=("pct", "size"), y=("pct", "mean"), n_pre=("pre", "count"), baseline=("pre", "mean"),
        n_gain=("gain", "count"), gain=("gain", "mean"))


def _compare_pair(df, out_df, a: int, b: int, item_sets, meta, summaries, s: AnalysisSettings, level: float,
                  n_pairs: int) -> dict[str, Any]:
    name = dict(zip(meta["textbook_id"], meta["textbook_name"]))
    summ = {x["textbook_id"]: x for x in summaries}
    common = item_sets[a] & item_sets[b]
    min_classes = max(s.min_classes_textbook, MIN_CLASSES_FOR_INFERENCE)
    reasons: list[str] = []
    confounders: list[str] = []
    res: dict[str, Any] = {"textbook_a": a, "textbook_b": b, "name_a": name[a], "name_b": name[b],
                           "common_items": len(common), "raw": None, "adjusted": None, "gain": None,
                           "baseline_diff": None, "hours_diff": None, "inference_unit": "class",
                           "ci_level": round(level * 100, 2), "pairs_in_family": n_pairs,
                           "classes_a": 0, "classes_b": 0, "excluded_small_classes": 0,
                           "evidence_level": "insufficient"}

    def finish(verdict: str, text: str) -> dict[str, Any]:
        return res | {"verdict": verdict, "verdict_text": text, "reasons": reasons, "confounders": confounders}

    if not common:
        reasons.append("Нет общих итоговых заданий (оценивание × тема) для двух учебников.")
        return finish("insufficient_evidence", INSUFFICIENT_TEXT)

    st = _student_pct(_restrict(out_df[out_df["textbook_id"].isin([a, b])], common))
    va = st[st["textbook_id"] == a]["pct"].to_numpy()
    vb = st[st["textbook_id"] == b]["pct"].to_numpy()
    grades = set(st[st["textbook_id"] == a]["grade"]) & set(st[st["textbook_id"] == b]["grade"])
    if not grades:
        reasons.append("Учебники используются в разных параллелях — сравнение смешивает учебник и возраст учеников.")
        return finish("insufficient_evidence", INSUFFICIENT_TEXT)

    cls_all = _class_table(df, out_df, a, b, common, grades)
    cls = cls_all[cls_all["n"] >= MIN_CLASS_SIZE]
    res["excluded_small_classes"] = int(len(cls_all) - len(cls))
    ca = cls[cls["textbook_id"] == a]
    cb = cls[cls["textbook_id"] == b]
    res["classes_a"], res["classes_b"] = int(len(ca)), int(len(cb))

    raw = welch(ca["y"].to_numpy(), cb["y"].to_numpy(), level)
    res["raw"] = (raw or {"diff": None, "ci_low": None, "ci_high": None, "p_value": None}) | {
        "method": "Welch по средним классов", "student_level_diff": r1(float(np.mean(vb) - np.mean(va)))
        if len(va) and len(vb) else None, "hedges_g": r1(hedges_g(va, vb), 2), "n_a": int(len(va)),
        "n_b": int(len(vb))}

    if min(len(va), len(vb)) < s.min_students_textbook:
        reasons.append(f"Мало учеников: {len(va)} и {len(vb)} (нужно не менее {s.min_students_textbook} в каждой группе).")
    if min(len(ca), len(cb)) < min_classes:
        reasons.append(f"Мало классов: {len(ca)} и {len(cb)} (нужно не менее {min_classes} на учебник, в каждом "
                       f"не менее {MIN_CLASS_SIZE} учеников с данными). Учебник назначается классу, поэтому "
                       "независимые наблюдения — это классы, а эффект учебника неотделим от учителя и класса.")
    if res["excluded_small_classes"]:
        reasons.append(f"Исключено классов с менее чем {MIN_CLASS_SIZE} учениками с данными: "
                       f"{res['excluded_small_classes']}.")

    with_base = cls[cls["n_pre"] >= MIN_CLASS_SIZE]
    if with_base.empty or with_base["textbook_id"].nunique() < 2:
        reasons.append("Нет входной диагностики (pre) по общим темам — нельзя учесть исходный уровень учеников.")
    else:
        bd = float(with_base[with_base.textbook_id == b]["baseline"].mean() - with_base[with_base.textbook_id == a]["baseline"].mean())
        res["baseline_diff"] = r1(bd)
        if abs(bd) >= 3:
            confounders.append(f"Исходный уровень различается: {r1(bd):+} п.п. (входная диагностика, средние классов). "
                               "Сравнение средних без поправки было бы некорректным.")
        cols = [np.ones(len(with_base)), (with_base["textbook_id"] == b).astype(float).to_numpy(),
                with_base["baseline"].to_numpy(dtype=float)]
        for gr in sorted(with_base["grade"].unique())[1:]:
            cols.append((with_base["grade"] == gr).astype(float).to_numpy())
        adj = ols_coef(with_base["y"].to_numpy(dtype=float), np.column_stack(cols), 1, level)
        if adj is None:
            reasons.append("Модель с поправкой на исходный уровень не оценивается: слишком мало классов для "
                           "числа параметров (нужно не менее 2 степеней свободы) или нет межклассовой вариации.")
        else:
            adj |= {"n_classes": int(len(with_base)), "n": int(with_base["n"].sum()),
                    "method": "ANCOVA по средним классов (OLS, df = классы − параметры)"}
        res["adjusted"] = adj
        confounders.append("Входная диагностика измеряет исходный уровень с погрешностью, поэтому поправка может "
                           "быть неполной (остаточное смешение); оценки по приросту и с поправкой могут расходиться.")

    with_gain = cls[cls["n_gain"] >= MIN_CLASS_SIZE]
    ga = with_gain[with_gain.textbook_id == a]["gain"].to_numpy(dtype=float)
    gb = with_gain[with_gain.textbook_id == b]["gain"].to_numpy(dtype=float)
    gain = welch(ga, gb, level)
    if gain is not None:
        res["gain"] = gain | {"mean_a": r1(float(np.mean(ga))), "mean_b": r1(float(np.mean(gb))),
                              "n_a": int(len(ga)), "n_b": int(len(gb)),
                              "method": "Welch по среднему приросту классов"}

    sa, sb = summ[a]["mean_class_size"], summ[b]["mean_class_size"]
    if sa and sb and abs(sa - sb) / max(sa, sb) >= 0.15:
        confounders.append(f"Различается средний размер класса: {sa} и {sb} учеников.")
    ha, hb = summ[a]["mean_hours_per_class"], summ[b]["mean_hours_per_class"]
    if ha is not None and hb is not None:
        res["hours_diff"] = r1(hb - ha)
        if ha > 0 and abs(hb - ha) / ha >= 0.05:
            confounders.append(f"Разное количество учебных часов на класс: {ha} и {hb} ч.")
    confounders.append("Классы распределены по учебникам не случайно; учитель, состав класса и расписание могут "
                       "влиять на результат.")

    if reasons:
        return finish("insufficient_evidence", INSUFFICIENT_TEXT)
    adj, g = res["adjusted"], res["gain"]
    if g is None:
        reasons.append("Не удалось оценить различие прироста между классами.")
        return finish("insufficient_evidence", INSUFFICIENT_TEXT)
    pct = res["ci_level"]
    if not _excludes_zero(adj):
        reasons.append(f"С поправкой на исходный уровень {pct:g}% доверительный интервал разницы включает ноль.")
    if not _excludes_zero(g):
        reasons.append(f"По приросту (входная → итоговая) {pct:g}% доверительный интервал разницы включает ноль.")
    if not reasons and (adj["diff"] > 0) != (g["diff"] > 0):
        reasons.append("Оценка с поправкой на исходный уровень и оценка по приросту указывают в разные стороны.")
    if reasons:
        return finish("insufficient_evidence", INSUFFICIENT_TEXT)

    total_classes = len(ca) + len(cb)
    res["evidence_level"] = "exploratory" if total_classes < EXPLORATORY_BELOW_CLASSES else "observational"
    better, worse = (name[b], name[a]) if adj["diff"] > 0 else (name[a], name[b])
    prefix = (f"Предварительный вывод (всего {total_classes} классов). " if res["evidence_level"] == "exploratory"
              else "")
    text = (f"{prefix}С поправкой на исходный уровень результаты классов, обучавшихся по «{better}», в среднем на "
            f"{abs(adj['diff'])} п.п. выше, чем по «{worse}» ({pct:g}% ДИ разницы «{name[b]}» − «{name[a]}»: "
            f"{adj['ci_low']}…{adj['ci_high']} п.п.). Средний прирост классов: {g['mean_a']} п.п. («{name[a]}») и "
            f"{g['mean_b']} п.п. («{name[b]}»), разница {g['diff']} п.п. ({pct:g}% ДИ {g['ci_low']}…{g['ci_high']}). "
            "Это наблюдаемая связь в нерандомизированных данных, а не доказательство причинного эффекта учебника.")
    return finish("observed_difference", text)
