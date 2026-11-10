"""Statistically cautious textbook comparison.

Rules:
* Only outcome items (assessment × topic) taken by students of *every* compared textbook are used, so
  differences in assessment difficulty do not masquerade as textbook differences.
* The headline estimate is baseline-adjusted (ANCOVA: outcome ~ textbook + pre-test [+ grade]) with
  cluster-robust standard errors by class, because students in one class share teacher and schedule.
* A higher average alone never produces a "winner". Without enough students/classes, without a baseline,
  or when the adjusted 95% CI includes zero, the verdict is "insufficient evidence".
"""
from __future__ import annotations

from itertools import combinations
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from app.services.analytics import distribution, mean_ci, outcome, r1
from app.services.settings_store import AnalysisSettings

INSUFFICIENT_TEXT = "Недостаточно данных, чтобы определить, какой учебник эффективнее."


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


def welch(a: np.ndarray, b: np.ndarray) -> dict[str, Any]:
    """Difference of means (b - a) with Welch 95% CI."""
    if len(a) < 2 or len(b) < 2:
        return {"diff": None, "ci_low": None, "ci_high": None, "p_value": None}
    diff = float(np.mean(b) - np.mean(a))
    va, vb = np.var(a, ddof=1) / len(a), np.var(b, ddof=1) / len(b)
    se = np.sqrt(va + vb)
    if se == 0:
        return {"diff": r1(diff), "ci_low": r1(diff), "ci_high": r1(diff), "p_value": 1.0 if diff == 0 else 0.0}
    dof = (va + vb) ** 2 / (va**2 / (len(a) - 1) + vb**2 / (len(b) - 1))
    h = stats.t.ppf(0.975, dof) * se
    p = float(stats.ttest_ind(b, a, equal_var=False).pvalue)
    return {"diff": r1(diff), "ci_low": r1(diff - h), "ci_high": r1(diff + h), "p_value": r1(p, 4)}


def cluster_ols(y: np.ndarray, X: np.ndarray, clusters: np.ndarray, coef: int) -> dict[str, Any] | None:
    """OLS with CR1 cluster-robust SE; returns estimate/CI for column `coef` using t(G-1)."""
    n, k = X.shape
    groups = np.unique(clusters)
    G = len(groups)
    if G < 3 or n <= k or np.linalg.matrix_rank(X) < k:
        return None
    XtX_inv = np.linalg.inv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    e = y - X @ beta
    meat = np.zeros((k, k))
    for g in groups:
        idx = clusters == g
        s = X[idx].T @ e[idx]
        meat += np.outer(s, s)
    c = (G / (G - 1)) * ((n - 1) / (n - k))
    V = c * XtX_inv @ meat @ XtX_inv
    se = float(np.sqrt(max(V[coef, coef], 0)))
    est = float(beta[coef])
    dof = G - 1
    if se == 0:
        return {"diff": r1(est), "ci_low": r1(est), "ci_high": r1(est), "p_value": None, "n": int(n), "clusters": G,
                "df": dof}
    tcrit = stats.t.ppf(0.975, dof)
    p = float(2 * stats.t.sf(abs(est / se), dof))
    return {"diff": r1(est), "se": r1(se, 2), "ci_low": r1(est - tcrit * se), "ci_high": r1(est + tcrit * se),
            "p_value": r1(p, 4), "n": int(n), "clusters": G, "df": dof}


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
        gains = student_gains(sub)["gain"].to_numpy(dtype=float)
        g_lo, g_hi = mean_ci(gains)
        summaries.append({
            "textbook_id": tid, "code": t["textbook_code"], "name": t["textbook_name"],
            "students": int(sub["student_id"].nunique()), "classes": len(classes),
            "class_names": sorted(sub["class_name"].unique().tolist()),
            "grades": sorted(int(g) for g in sub["grade"].unique()),
            "outcome_students": int(len(vals)),
            "mean": r1(float(np.mean(vals))) if len(vals) else None,
            "median": r1(float(np.median(vals))) if len(vals) else None,
            "sd": r1(float(np.std(vals, ddof=1))) if len(vals) > 1 else None,
            "ci_low": r1(lo), "ci_high": r1(hi),
            "distribution": distribution(vals) if len(vals) else [],
            "baseline_mean": r1(float(pre_st["pct"].mean())) if not pre_st.empty else None,
            "baseline_students": int(len(pre_st)),
            "mean_hours_per_class": r1(float(np.mean(class_hours))) if class_hours else None,
            "mean_class_size": r1(sub["student_id"].nunique() / len(classes)) if classes else None,
            "gain_mean": r1(float(np.mean(gains))) if len(gains) else None,
            "gain_ci_low": r1(g_lo), "gain_ci_high": r1(g_hi),
            "gain_students": int(len(gains)),
        })

    # topic matrix on common items
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
    # Only textbooks used in the same grade and subject are comparable at all.
    pairs = [_compare_pair(df, out_df, a, b, item_sets, meta, summaries, s) for a, b in combinations(tb_ids, 2)
             if grades[a] & grades[b] and subjects[a] & subjects[b]]
    return {"textbooks": summaries, "pairs": pairs, "topic_matrix": topic_matrix, "common_items": len(common_all),
            "comparable": comparable,
            "message": None if comparable else "У учебников нет общих итоговых заданий — прямое сравнение невозможно."}


def _compare_pair(df, out_df, a: int, b: int, item_sets, meta, summaries, s: AnalysisSettings) -> dict[str, Any]:
    name = dict(zip(meta["textbook_id"], meta["textbook_name"]))
    summ = {x["textbook_id"]: x for x in summaries}
    common = item_sets[a] & item_sets[b]
    reasons: list[str] = []
    confounders: list[str] = []
    res: dict[str, Any] = {"textbook_a": a, "textbook_b": b, "name_a": name[a], "name_b": name[b],
                           "common_items": len(common), "raw": None, "adjusted": None, "baseline_diff": None,
                           "hours_diff": None, "gain": None}
    if not common:
        reasons.append("Нет общих итоговых заданий (оценивание × тема) для двух учебников.")
        return res | {"verdict": "insufficient_evidence", "verdict_text": INSUFFICIENT_TEXT, "reasons": reasons,
                      "confounders": confounders}

    pair = _restrict(out_df[out_df["textbook_id"].isin([a, b])], common)
    st = _student_pct(pair)
    va = st[st["textbook_id"] == a]["pct"].to_numpy()
    vb = st[st["textbook_id"] == b]["pct"].to_numpy()
    raw = welch(va, vb)
    raw["hedges_g"] = r1(hedges_g(va, vb), 2)
    raw["n_a"], raw["n_b"] = int(len(va)), int(len(vb))
    res["raw"] = raw

    ca = st[st["textbook_id"] == a]["class_id"].nunique()
    cb = st[st["textbook_id"] == b]["class_id"].nunique()
    if min(len(va), len(vb)) < s.min_students_textbook:
        reasons.append(f"Мало учеников: {len(va)} и {len(vb)} (нужно не менее {s.min_students_textbook} в каждой группе).")
    if min(ca, cb) < s.min_classes_textbook:
        reasons.append(f"Мало классов: {ca} и {cb} (нужно не менее {s.min_classes_textbook}); эффект учебника "
                       "неотделим от эффекта учителя и класса.")
    grades_a = set(st[st["textbook_id"] == a]["grade"])
    grades_b = set(st[st["textbook_id"] == b]["grade"])
    if not grades_a & grades_b:
        reasons.append("Учебники используются в разных параллелях — сравнение смешивает учебник и возраст учеников.")

    # baseline: pre-test on the same topics
    common_topics = {t for _, t in common}
    pre = df[(df["kind"] == "pre") & df["textbook_id"].isin([a, b]) & df["topic_id"].isin(common_topics)]
    pre_st = _student_pct(pre)[["student_id", "pct"]].rename(columns={"pct": "pre"})
    if pre_st.empty:
        reasons.append("Нет входной диагностики (pre) по общим темам — нельзя учесть исходный уровень учеников.")
    else:
        pa = pre_st.merge(st[st["textbook_id"] == a][["student_id"]], on="student_id")["pre"]
        pb = pre_st.merge(st[st["textbook_id"] == b][["student_id"]], on="student_id")["pre"]
        if len(pa) and len(pb):
            bd = float(pb.mean() - pa.mean())
            res["baseline_diff"] = r1(bd)
            if abs(bd) >= 3:
                confounders.append(f"Исходный уровень различается: {r1(bd):+} п.п. (входная диагностика). Сравнение "
                                   "средних без поправки было бы некорректным.")
        merged = st.merge(pre_st, on="student_id", how="inner")
        merged = merged[merged["grade"].isin(grades_a & grades_b)]
        if len(merged) and merged["textbook_id"].nunique() == 2:
            cols = [np.ones(len(merged)), (merged["textbook_id"] == b).astype(float).to_numpy(), merged["pre"].to_numpy()]
            for gr in sorted(merged["grade"].unique())[1:]:
                cols.append((merged["grade"] == gr).astype(float).to_numpy())
            X = np.column_stack(cols)
            adj = cluster_ols(merged["pct"].to_numpy(), X, merged["class_id"].to_numpy(), coef=1)
            if adj is None:
                reasons.append("Недостаточно классов для оценки с учётом кластеризации (нужно ≥ 3 класса всего).")
            res["adjusted"] = adj

    # learning improvement: paired pre→post gain on the common topics, clustered by class
    gains = student_gains(df[df["textbook_id"].isin([a, b])], common_topics)
    gains = gains[gains["grade"].isin(grades_a & grades_b)]
    ga = gains[gains["textbook_id"] == a]["gain"].to_numpy(dtype=float)
    gb = gains[gains["textbook_id"] == b]["gain"].to_numpy(dtype=float)
    if len(ga) >= 2 and len(gb) >= 2:
        cols = [np.ones(len(gains)), (gains["textbook_id"] == b).astype(float).to_numpy()]
        for gr in sorted(gains["grade"].unique())[1:]:
            cols.append((gains["grade"] == gr).astype(float).to_numpy())
        est = cluster_ols(gains["gain"].to_numpy(dtype=float), np.column_stack(cols), gains["class_id"].to_numpy(), 1)
        method = "кластеризованные ошибки по классам"
        if est is None:
            est = welch(ga, gb)
            method = "Welch (без учёта классов — приблизительно)"
        res["gain"] = {"mean_a": r1(float(np.mean(ga))), "mean_b": r1(float(np.mean(gb))), "n_a": int(len(ga)),
                       "n_b": int(len(gb)), "diff": est["diff"], "ci_low": est["ci_low"], "ci_high": est["ci_high"],
                       "p_value": est.get("p_value"), "method": method}

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

    adj = res["adjusted"]
    if adj is not None and adj.get("ci_low") is not None and not reasons:
        g = res["gain"]
        gain_contradicts = (g is not None and g["ci_low"] is not None and g["diff"] is not None
                            and (g["ci_low"] > 0 or g["ci_high"] < 0) and (g["diff"] > 0) != (adj["diff"] > 0))
        if gain_contradicts:
            reasons.append("Оценка с поправкой на исходный уровень и оценка по приросту указывают в разные стороны.")
        elif adj["ci_low"] > 0 or adj["ci_high"] < 0:
            better, worse = (name[b], name[a]) if adj["diff"] > 0 else (name[a], name[b])
            text = (f"После поправки на исходный уровень ученики, обучавшиеся по «{better}», в среднем показали "
                    f"результат на {abs(adj['diff'])} п.п. выше, чем по «{worse}» (95% ДИ: {adj['ci_low']}…"
                    f"{adj['ci_high']} п.п. для разницы «{name[b]}» − «{name[a]}»). Это наблюдаемая связь, а не "
                    "доказательство причинного эффекта учебника.")
            if g is not None and g["diff"] is not None:
                text += (f" Средний прирост от входной к итоговой диагностике: {g['mean_a']} п.п. («{name[a]}») и "
                         f"{g['mean_b']} п.п. («{name[b]}»), разница {g['diff']} п.п. (95% ДИ {g['ci_low']}…"
                         f"{g['ci_high']}).")
            return res | {"verdict": "observed_difference", "verdict_text": text, "reasons": [],
                          "confounders": confounders}
        else:
            reasons.append("После поправки на исходный уровень 95% доверительный интервал разницы включает ноль.")
    elif adj is None and not reasons:
        reasons.append("Не удалось оценить разницу с поправкой на исходный уровень.")
    return res | {"verdict": "insufficient_evidence", "verdict_text": INSUFFICIENT_TEXT, "reasons": reasons,
                  "confounders": confounders}
