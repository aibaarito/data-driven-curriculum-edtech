"""Small numerical oracles independent of the application's statistical helpers."""
import numpy as np
import pytest
from scipy import stats

from app.services import analytics as an
from app.services.settings_store import AnalysisSettings
from app.services.textbooks import compare_textbooks
from tests.conftest import make_csv
from tests.test_analytics import df, rec
from tests.test_api import upload


def class_fixture(sizes=(10, 15, 25, 11, 17, 31)):
    baseline = np.array([30., 40., 50., 35., 45., 55.])
    outcome = np.array([53., 58., 63., 77., 80., 87.])
    rows, sid = [], 0
    for cls, size in enumerate(sizes):
        for _ in range(size):
            sid += 1
            for kind, aid, score in (("pre", 1, baseline[cls]), ("post", 2, outcome[cls])):
                rows.append(rec(sid, 1, aid, kind, score, 100, cls=cls + 1, tb=1 + (cls >= 3), group="G"))
    return df(rows), baseline, outcome


def test_full_textbook_adjustment_matches_independent_class_level_qr_reference():
    data, baseline, outcome = class_fixture()
    pair = compare_textbooks(data, AnalysisSettings())["pairs"][0]
    X = np.column_stack((np.ones(6), [0, 0, 0, 1, 1, 1], baseline))
    # QR solve and residual-based covariance; no app ols/class-table helper generates this oracle.
    Q, R = np.linalg.qr(X)
    beta = np.linalg.solve(R, Q.T @ outcome)
    residual = outcome - X @ beta
    dof = 6 - 3
    inverse_R = np.linalg.solve(R, np.eye(3))
    covariance = (residual @ residual / dof) * (inverse_R @ inverse_R.T)
    se = np.sqrt(covariance[1, 1])
    critical = stats.t.ppf(.975, dof)
    actual = pair["adjusted"]
    assert actual["n_classes"] == 6 and actual["df"] == dof
    assert actual["diff"] == pytest.approx(round(beta[1], 1), abs=.001)
    assert actual["se"] == pytest.approx(round(se, 2), abs=.001)
    assert actual["ci_low"] == pytest.approx(round(beta[1] - critical * se, 1), abs=.001)
    assert actual["ci_high"] == pytest.approx(round(beta[1] + critical * se, 1), abs=.001)
    assert actual["p_value"] == pytest.approx(round(2 * stats.t.sf(abs(beta[1] / se), dof), 4), abs=.00001)
    assert pair["baseline_diff"] == round(baseline[3:].mean() - baseline[:3].mean(), 1)
    assert pair["raw"]["diff"] == round(outcome[3:].mean() - outcome[:3].mean(), 1)
    # Independently check the Welch gain interval on six class means.
    a, b = (outcome - baseline)[:3], (outcome - baseline)[3:]
    va, vb = np.var(a, ddof=1) / 3, np.var(b, ddof=1) / 3
    gain_se = np.sqrt(va + vb)
    gain_df = (va + vb) ** 2 / (va ** 2 / 2 + vb ** 2 / 2)
    difference = b.mean() - a.mean()
    halfwidth = stats.t.ppf(.975, gain_df) * gain_se
    assert pair["gain"]["diff"] == round(difference, 1)
    assert pair["gain"]["ci_low"] == round(difference - halfwidth, 1)
    assert pair["gain"]["ci_high"] == round(difference + halfwidth, 1)
    assert pair["verdict"] == "observed_difference" and pair["evidence_level"] == "exploratory"


def test_increasing_one_class_size_does_not_change_inferential_estimates():
    small, *_ = class_fixture()
    large, *_ = class_fixture((100, 15, 25, 11, 17, 31))
    a, b = [compare_textbooks(data, AnalysisSettings())["pairs"][0] for data in (small, large)]
    for method in ("raw", "adjusted", "gain"):
        for metric in ("diff", "se", "ci_low", "ci_high", "p_value"):
            assert a[method][metric] == b[method][metric]
    assert a["raw"]["student_level_diff"] != b["raw"]["student_level_diff"]
    assert a["verdict"] == b["verdict"]


def test_gain_interval_and_adjusted_probability_match_hand_calculation():
    pre = np.array([20., 30., 40., 50., 60.])
    post = np.array([25., 37., 44., 60., 62.])
    gains = post - pre
    n, family = 5, 3
    mean = sum(gains) / n
    variance = sum((v - mean) ** 2 for v in gains) / (n - 1)
    se = (variance / n) ** .5
    level = 1 - .05 / family
    critical = stats.t.ppf(1 - .05 / (2 * family), n - 1)
    actual = an.gain_stats(pre, post, ci_level=level, family_size=family)
    assert actual["mean_gain"] == round(mean, 1)
    assert actual["ci_low"] == round(mean - critical * se, 1)
    assert actual["ci_high"] == round(mean + critical * se, 1)
    expected_p = 2 * stats.t.sf(abs(mean / se), n - 1)
    assert actual["p_value_adjusted"] == round(min(1, family * expected_p), 4)
    assert actual["direction"] == ("increase" if mean - critical * se > 0 else "inconclusive")


@pytest.mark.parametrize("delta,direction,p", [(10, "increase", 0), (-10, "decline", 0), (0, "inconclusive", 1)])
def test_zero_variance_gain_follows_documented_degenerate_convention(delta, direction, p):
    pre = np.array([20., 30., 40., 50.])
    actual = an.gain_stats(pre, pre + delta)
    assert actual["mean_gain"] == actual["ci_low"] == actual["ci_high"] == delta
    assert actual["direction"] == direction and actual["p_value"] == p


@pytest.mark.parametrize("delta", [.04, -.04])
def test_reported_significant_gain_interval_does_not_round_to_zero(delta):
    pre = np.array([20., 30., 40., 50.])
    actual = an.gain_stats(pre, pre + delta)
    assert actual["significant"]
    assert actual["mean_gain"] != 0
    assert (actual["ci_low"] > 0) if delta > 0 else (actual["ci_high"] < 0)


@pytest.mark.parametrize("mastery,count,status", [(49.999, 10, "difficult"), (50, 10, "watch"),
    (64.999, 10, "watch"), (65, 10, "ok"), (49, 9, "insufficient_data")])
def test_classification_exact_threshold_and_sample_boundaries(mastery, count, status):
    assert an.classify_topic(mastery, count, None, AnalysisSettings())[0] == status


def test_scoring_scale_weighting_and_exact_distribution_bins():
    # Pooled points and equal-student/equal-class averages deliberately all differ.
    rows = [rec(1, 1, 1, "post", 0, 2, cls=1), rec(2, 1, 1, "post", 20, 20, cls=2),
            rec(3, 1, 1, "post", 10, 10, cls=2)]
    t = an.topic_analytics(df(rows), AnalysisSettings())[0]
    assert t["mastery"] == round(30 / 32 * 100, 1)
    assert t["mean"] == round(200 / 3, 1) and t["median"] == 100 and t["class_mean"] == 50
    bins = an.distribution(np.array([0, 9.9, 10, 19.9, 20, 29.9, 30, 39.9, 40, 49.9,
                                     50, 59.9, 60, 69.9, 70, 79.9, 80, 89.9, 90, 100]))
    assert [b["count"] for b in bins] == [2] * 10


def test_all_six_filters_match_independent_raw_row_selection(client):
    rows = [
        "s,S1,7,7A,Math,M7,Algebra,A7,current,2026-05-01,,Q1,1,2,TB-M7,10",
        "s,S2,7,7B,Math,M7,Algebra,A7,current,2026-05-01,,Q1,3,4,TB-N7,12",
        "s,S3,8,8A,Math,M8,Geometry,A8,current,2026-05-02,,Q1,4,5,TB-M8,10",
        "s,S1,7,7A,Physics,P7,Motion,P7A,current,2026-05-02,,Q1,6,10,TB-P7,8",
    ]
    p = upload(client, make_csv(rows)).json()
    assert p["ok"]
    assert client.post(f"/api/imports/{p['batch_id']}/commit").status_code == 200
    meta = client.get("/api/meta").json()
    math = next(s["id"] for s in meta["subjects"] if s["name"] == "Math")
    cls = next(c["id"] for c in meta["classes"] if c["name"] == "7A")
    book = next(b["id"] for b in meta["textbooks"] if b["code"] == "TB-N7")
    cases = [(f"subject_id={math}", [0, 1, 2]), ("grade=7", [0, 1, 3]),
             (f"class_id={cls}", [0, 3]), (f"textbook_id={book}", [1]),
             ("date_from=2026-05-02", [2, 3]), ("date_to=2026-05-01", [0, 1])]
    for query, selected in cases:
        source = [rows[i].split(",") for i in selected]
        expected = round(sum(float(r[12]) for r in source) / sum(float(r[13]) for r in source) * 100, 1)
        result = client.get("/api/analytics/overview?" + query).json()["overview"]
        assert result["average_mastery"] == expected and result["results"] == len(selected)
        assert result["students"] == len({r[1] for r in source})
