from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.services import analytics as an
from app.services.settings_store import AnalysisSettings
from app.services.textbooks import INSUFFICIENT_TEXT, compare_textbooks, hedges_g, ols_coef, welch

S = AnalysisSettings()


def rec(student, topic, assessment, kind, score, mx, *, group=None, cls=1, grade=7, tb=1, d=date(2025, 9, 1),
        item="_total", subject=1):
    return {
        "student_id": student, "student_ext": f"S{student}", "class_id": cls, "class_name": f"C{cls}", "grade": grade,
        "subject_id": subject, "subject_name": "Математика", "topic_id": topic, "topic_code": f"T{topic}",
        "topic_name": f"Тема {topic}", "topic_order": topic, "assessment_id": assessment,
        "assessment_code": f"A{assessment}", "assessment_date": d, "kind": kind, "comparison_group": group,
        "textbook_id": tb, "textbook_code": f"TB{tb}" if tb else None, "textbook_name": f"Учебник {tb}" if tb else None,
        "item_id": item, "score": float(score), "max_score": float(mx),
    }


def df(rows):
    return pd.DataFrame(rows, columns=an.COLUMNS)


# ------------------------------------------------------------------ mastery formula


def test_mastery_formula():
    assert an.mastery(30, 40) == 75.0
    assert an.mastery(0, 10) == 0.0


@pytest.mark.parametrize("mx", [0, -5, None])
def test_mastery_zero_or_missing_max_is_none(mx):
    assert an.mastery(0, mx) is None


def test_mastery_rejects_impossible_sums():
    with pytest.raises(ValueError):
        an.mastery(11, 10)
    with pytest.raises(ValueError):
        an.mastery(-1, 10)


def test_topic_mastery_is_points_weighted_not_mean_of_percents():
    rows = [rec(1, 1, 1, "post", 1, 1, item="a"), rec(1, 1, 1, "post", 0, 9, item="b"),
            rec(2, 1, 1, "post", 5, 10)]
    t = an.topic_analytics(df(rows), S)[0]
    # Σ obtained = 6, Σ available = 20 → 30 %
    assert t["mastery"] == 30.0
    # per-student: S1 = 1/10 = 10 %, S2 = 50 % → mean 30, median 30
    assert t["mean"] == 30.0 and t["median"] == 30.0
    assert t["student_count"] == 2 and t["assessment_count"] == 1


def test_pre_tests_excluded_from_mastery():
    rows = [rec(1, 1, 1, "pre", 0, 10), rec(1, 1, 2, "post", 8, 10)]
    t = an.topic_analytics(df(rows), S)[0]
    assert t["mastery"] == 80.0


def test_empty_dataset():
    empty = df([])
    assert an.overview(empty)["has_data"] is False
    assert an.topic_analytics(empty, S) == []
    assert an.learning_gains(empty) == {}
    assert an.overall_trend(empty) == []


def test_distribution_counts_all_students():
    rows = [rec(i, 1, 1, "post", i % 11, 10) for i in range(1, 31)]
    t = an.topic_analytics(df(rows), S)[0]
    assert sum(b["count"] for b in t["distribution"]) == 30


# ------------------------------------------------------------------ learning gains


def test_gains_pair_only_matching_students_and_groups():
    rows = [
        rec(1, 1, 1, "pre", 2, 10, group="G"), rec(1, 1, 2, "post", 8, 10, group="G"),
        rec(2, 1, 1, "pre", 4, 10, group="G"), rec(2, 1, 2, "post", 9, 10, group="G"),
        rec(3, 1, 1, "pre", 0, 10, group="G"),  # no post → not paired
        rec(4, 1, 3, "post", 10, 10, group="OTHER"),  # unrelated test → never compared
    ]
    g = an.learning_gains(df(rows))[1]
    assert g["n_paired"] == 2
    assert g["pre_mean"] == 30.0 and g["post_mean"] == 85.0 and g["mean_gain"] == 55.0
    assert g["normalized_gain"] == pytest.approx((85 - 30) / 70, abs=1e-3)


def test_no_baseline_means_no_gain():
    rows = [rec(1, 1, 2, "post", 8, 10, group="G")]
    assert an.learning_gains(df(rows)) == {}


def test_pre_post_without_group_not_compared():
    rows = [rec(1, 1, 1, "pre", 2, 10), rec(1, 1, 2, "post", 8, 10)]
    assert an.learning_gains(df(rows)) == {}


def test_gain_ci_and_significance():
    rng = np.random.default_rng(1)
    pre = rng.normal(40, 10, 50)
    post = pre + 10 + rng.normal(0, 5, 50)
    g = an.gain_stats(pre, post)
    assert g["significant"] and g["ci_low"] < g["mean_gain"] < g["ci_high"]
    flat = an.gain_stats(pre, pre + rng.normal(0, 5, 50))
    assert flat["ci_low"] < 0 < flat["ci_high"]


# ------------------------------------------------------------------ classification


def test_classification_distinguishes_low_performance_from_failure():
    big_gain = {"significant": True, "mean_gain": 20}
    no_gain = {"significant": False, "mean_gain": 1}
    decline = {"significant": True, "mean_gain": -9}
    assert an.classify_topic(40, 50, None, S) == ("difficult", "low_no_baseline")
    assert an.classify_topic(40, 50, big_gain, S) == ("difficult", "low_but_improving")
    assert an.classify_topic(40, 50, no_gain, S) == ("difficult", "low_no_measurable_gain")
    assert an.classify_topic(40, 50, decline, S) == ("difficult", "low_declining")
    assert an.classify_topic(90, 50, decline, S) == ("ok", "ok_but_declining")
    assert an.classify_topic(40, 50, {"direction": "insufficient"}, S) == ("difficult", "low_gain_insufficient")
    assert an.classify_topic(60, 50, None, S)[0] == "watch"
    assert an.classify_topic(90, 50, None, S) == ("ok", "ok")
    assert an.classify_topic(10, 3, None, S) == ("insufficient_data", "small_sample")
    assert an.classify_topic(None, 0, None, S)[0] == "no_outcome_data"


def test_significant_decline_is_never_described_as_progress():
    pre = np.array([45.0 + (i % 5) for i in range(40)])
    g = an.gain_stats(pre, pre - 10 + (np.arange(40) % 3), min_pairs=10)
    assert g["direction"] == "decline" and g["ci_high"] < 0
    status, code = an.classify_topic(38, 40, g, S)
    text = an.INTERPRETATION_RU[code]
    assert code == "low_declining" and "СНИЖЕНИЕ" in text
    assert "прирост" not in text.lower() and "осваивается" not in text


def test_inconclusive_is_not_described_as_no_effect():
    text = an.INTERPRETATION_RU["low_no_measurable_gain"]
    assert "не доказывает отсутствие эффекта" in text


def test_bonferroni_family_controls_topic_intervals():
    rng = np.random.default_rng(4)
    rows = []
    for topic in range(1, 9):
        for sid in range(1, 31):
            pre = rng.normal(50, 8)
            rows += [rec(sid, topic, 1, "pre", round(pre), 100, group="G"),
                     rec(sid, topic, 2, "post", round(pre + rng.normal(0, 6)), 100, group="G")]
    gains = an.learning_gains(df(rows), min_pairs=10)
    assert all(g["family_size"] == 8 and g["ci_level"] == pytest.approx(99.38, abs=0.01) for g in gains.values())
    one = an.gain_stats(np.array([1.0, 2, 3, 4]), np.array([2.0, 3, 5, 4]), ci_level=0.95)
    wide = an.gain_stats(np.array([1.0, 2, 3, 4]), np.array([2.0, 3, 5, 4]), ci_level=1 - 0.05 / 8, family_size=8)
    assert wide["ci_high"] - wide["ci_low"] > one["ci_high"] - one["ci_low"]
    assert wide["p_value_adjusted"] == pytest.approx(min(1, one["p_value"] * 8), abs=1e-3)


def test_gain_needs_minimum_pairs():
    g = an.gain_stats(np.array([10.0, 20, 30]), np.array([40.0, 50, 60]), min_pairs=10)
    assert g["direction"] == "insufficient" and g["ci_low"] is None and g["significant"] is False


def test_weighting_is_explicit_points_student_and_class():
    # class 1: one student 10/10; class 2: three students 0/10 → pooled 25%, student mean 25%, class mean 50%
    rows = [rec(1, 1, 1, "post", 10, 10, cls=1)] + [rec(i, 1, 1, "post", 0, 10, cls=2) for i in (2, 3, 4)]
    t = an.topic_analytics(df(rows), S)[0]
    assert (t["mastery"], t["mean"], t["class_mean"]) == (25.0, 25.0, 50.0)


def test_thresholds_are_configurable():
    strict = AnalysisSettings(difficult_threshold=80, watch_threshold=90)
    assert an.classify_topic(75, 50, None, strict)[0] == "difficult"


def test_settings_reject_inverted_thresholds():
    with pytest.raises(ValueError):
        AnalysisSettings(difficult_threshold=70, watch_threshold=60)


# ------------------------------------------------------------------ textbooks


def _school(effect_b: float, n_per_class: int = 25, classes_per_tb: int = 3, baseline_b: float = 0, seed: int = 0,
            with_pre: bool = True):
    rng = np.random.default_rng(seed)
    rows = []
    sid = 0
    for tb in (1, 2):
        for c in range(classes_per_tb):
            cls = tb * 10 + c
            ce = rng.normal(0, 1)
            for _ in range(n_per_class):
                sid += 1
                ability = rng.normal(0, 12) + (baseline_b if tb == 2 else 0)
                pre = np.clip(40 + ability + ce + rng.normal(0, 5), 0, 100)
                post = np.clip(60 + ability + ce + (effect_b if tb == 2 else 0) + rng.normal(0, 5), 0, 100)
                if with_pre:
                    rows.append(rec(sid, 1, 1, "pre", round(pre), 100, group="G", cls=cls, tb=tb))
                rows.append(rec(sid, 1, 2, "post", round(post), 100, group="G", cls=cls, tb=tb))
    return df(rows)


def test_identical_textbooks_are_insufficient_evidence():
    res = compare_textbooks(_school(effect_b=0, seed=3), S)
    pair = res["pairs"][0]
    assert pair["verdict"] == "insufficient_evidence"
    assert pair["verdict_text"] == INSUFFICIENT_TEXT


def test_real_adjusted_difference_detected_despite_baseline_gap():
    # textbook 2 starts 6 p.p. lower but gains 8 p.p. more: raw means look similar
    res = compare_textbooks(_school(effect_b=8, baseline_b=-6, seed=5), S)
    pair = res["pairs"][0]
    assert pair["verdict"] == "observed_difference"
    assert pair["adjusted"]["ci_low"] > 0
    assert abs(pair["raw"]["diff"]) < pair["adjusted"]["diff"]
    assert "не доказательство" in pair["verdict_text"]
    assert any("Исходный уровень" in c for c in pair["confounders"])


def test_small_samples_never_declare_a_winner():
    res = compare_textbooks(_school(effect_b=30, n_per_class=5, classes_per_tb=1, seed=2), S)
    pair = res["pairs"][0]
    assert pair["verdict"] == "insufficient_evidence"
    assert any("Мало" in r for r in pair["reasons"])


def test_without_baseline_no_verdict_even_with_big_raw_difference():
    res = compare_textbooks(_school(effect_b=20, seed=4, with_pre=False), S)
    pair = res["pairs"][0]
    assert pair["raw"]["diff"] > 10
    assert pair["verdict"] == "insufficient_evidence"
    assert any("входной диагностики" in r for r in pair["reasons"])


def test_missing_textbook_rows_are_excluded():
    rows = [rec(1, 1, 1, "post", 5, 10, tb=None)]
    res = compare_textbooks(df(rows), S)
    assert res["textbooks"] == [] and res["pairs"] == []


def test_textbooks_from_different_grades_not_paired():
    a = [rec(i, 1, 1, "post", 5, 10, tb=1, grade=7) for i in range(1, 5)]
    b = [rec(i, 2, 2, "post", 5, 10, tb=2, grade=8) for i in range(10, 15)]
    res = compare_textbooks(df(a + b), S)
    assert len(res["textbooks"]) == 2 and res["pairs"] == []


def test_welch_matches_scipy_and_handles_degenerate_input():
    from scipy import stats
    a = np.array([1.0, 2, 3, 4, 5])
    b = np.array([11.0, 13, 12, 16, 14])
    w = welch(a, b)
    ref = stats.ttest_ind(b, a, equal_var=False)
    assert w["diff"] == round(b.mean() - a.mean(), 1)
    assert w["p_value"] == pytest.approx(ref.pvalue, abs=1e-4)
    assert w["ci_low"] < w["diff"] < w["ci_high"]
    assert welch(np.array([1.0]), b) is None  # one unit per group: not estimable
    assert welch(np.array([5.0, 5.0]), np.array([7.0, 7.0])) is None  # zero variance: no uncertainty estimate
    assert hedges_g(a, a) == 0.0


def test_ols_coef_matches_closed_form_and_requires_two_df():
    # 6 classes, intercept + group + baseline -> df = 3; compare with numpy lstsq + classical SE
    rng = np.random.default_rng(3)
    g = np.array([0, 0, 0, 1, 1, 1.0])
    base = rng.normal(40, 3, 6)
    y = 20 + 5 * g + 0.8 * base + rng.normal(0, 1, 6)
    X = np.column_stack([np.ones(6), g, base])
    est = ols_coef(y, X, 1)
    beta, res, *_ = np.linalg.lstsq(X, y, rcond=None)
    sigma2 = float(res[0]) / 3
    se = np.sqrt(sigma2 * np.linalg.inv(X.T @ X)[1, 1])
    from scipy import stats
    assert est["df"] == 3
    assert est["diff"] == round(beta[1], 1)
    assert est["ci_high"] == pytest.approx(round(beta[1] + stats.t.ppf(0.975, 3) * se, 1), abs=0.051)
    assert ols_coef(y[:4], X[:4], 1) is None  # df = 1 < 2 -> not estimable


def test_one_class_per_textbook_is_never_a_verdict_even_with_huge_effect():
    res = compare_textbooks(_school(effect_b=40, n_per_class=40, classes_per_tb=1, seed=9), S)
    pair = res["pairs"][0]
    assert pair["verdict"] == "insufficient_evidence" and pair["adjusted"] is None
    assert any("Мало классов" in r for r in pair["reasons"])


def test_inference_unit_is_class_not_student():
    """Doubling students per class must not shrink the class-level interval the way a student-level test would."""
    small = compare_textbooks(_school(effect_b=3, n_per_class=20, classes_per_tb=4, seed=11), S)["pairs"][0]
    big = compare_textbooks(_school(effect_b=3, n_per_class=80, classes_per_tb=4, seed=11), S)["pairs"][0]
    assert small["inference_unit"] == "class" and small["classes_a"] == 4
    width = lambda e: e["ci_high"] - e["ci_low"]  # noqa: E731
    # with student-level SEs the width would halve (sqrt(4)); with classes as units it shrinks far less
    assert width(big["gain"]) > 0.6 * width(small["gain"])


def test_pair_family_widens_intervals_for_three_textbooks():
    rows = []
    sid = 0
    rng = np.random.default_rng(5)
    for tb in (1, 2, 3):
        for c in range(3):
            for _ in range(20):
                sid += 1
                ab = rng.normal(0, 10)
                rows.append(rec(sid, 1, 1, "pre", round(np.clip(40 + ab, 0, 100)), 100, group="G", cls=tb * 10 + c, tb=tb))
                rows.append(rec(sid, 1, 2, "post", round(np.clip(60 + ab + rng.normal(0, 5), 0, 100)), 100, group="G",
                                cls=tb * 10 + c, tb=tb))
    pairs = compare_textbooks(df(rows), S)["pairs"]
    assert len(pairs) == 3 and all(p["ci_level"] == pytest.approx(100 * (1 - 0.05 / 3), abs=0.01) for p in pairs)
