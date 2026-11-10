"""Acceptance tests for the four mandatory capabilities of the official hackathon case.

Each test uploads the synthetic dataset through the real API and checks results against values that can be
recomputed independently from the raw CSV (no shared code with the analytics module).
"""
import csv
from collections import defaultdict

import numpy as np
import pandas as pd
import pytest

from app.services.analytics import COLUMNS
from app.services.optimizer import OptimizerInput, TopicInput, optimize
from app.services.textbooks import student_gains
from tests.conftest import DEMO_CSV
from tests.test_api import import_demo


@pytest.fixture()
def demo(client):
    import_demo(client)
    meta = client.get("/api/meta").json()
    return client, meta["subjects"][0]["id"]


def raw_rows():
    with open(DEMO_CSV, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# ---------------------------------------------------------------- 1. analysis by topic


def test_req1_topic_mastery_matches_independent_recomputation(demo):
    client, subject = demo
    obtained, available, students = defaultdict(float), defaultdict(float), defaultdict(set)
    for r in raw_rows():
        if r["grade"] == "7" and r["assessment_type"] in ("post", "current"):
            obtained[r["topic_id"]] += float(r["score"])
            available[r["topic_id"]] += float(r["max_score"])
            students[r["topic_id"]].add(r["student_id"])
    topics = client.get(f"/api/analytics/topics?subject_id={subject}&grade=7").json()["topics"]
    assert len(topics) == 8
    for t in topics:
        expected = round(obtained[t["code"]] / available[t["code"]] * 100, 1)
        assert t["mastery"] == pytest.approx(expected, abs=0.05), t["code"]
        assert t["student_count"] == len(students[t["code"]])
        assert sum(b["count"] for b in t["distribution"]) == t["student_count"]


def test_req1_filters_change_results_consistently(demo):
    client, subject = demo
    all7 = {t["code"]: t for t in client.get(f"/api/analytics/topics?grade=7").json()["topics"]}
    meta = client.get("/api/meta").json()
    cls = next(c for c in meta["classes"] if c["name"] == "7А")
    one = {t["code"]: t for t in client.get(f"/api/analytics/topics?class_id={cls['id']}").json()["topics"]}
    assert one["T7-01"]["student_count"] == 27 < all7["T7-01"]["student_count"]


# ---------------------------------------------------------------- 2. difficult topics


def test_req2_struggling_topics_identified_with_evidence(demo):
    client, subject = demo
    topics = {t["code"]: t for t in client.get(f"/api/analytics/topics?subject_id={subject}&grade=7").json()["topics"]}
    difficult = {c for c, t in topics.items() if t["status"] == "difficult"}
    assert difficult == {"T7-05", "T7-06"}
    # low AND no measurable gain vs low but improving — the platform distinguishes them, no causal claim
    assert topics["T7-05"]["interpretation_code"] == "low_no_measurable_gain"
    assert topics["T7-06"]["interpretation_code"] == "low_but_improving"
    assert "причина по данным не установлена" in topics["T7-05"]["interpretation"]
    ov = client.get(f"/api/analytics/overview?grade=7").json()
    assert [t["code"] for t in ov["difficult_topics"][:2]] == ["T7-05", "T7-06"]


def test_req2_thresholds_drive_classification(demo):
    client, _ = demo
    s = client.get("/api/settings").json()["analysis"]
    client.put("/api/settings", json={**s, "difficult_threshold": 45, "watch_threshold": 65})
    topics = {t["code"]: t for t in client.get("/api/analytics/topics?grade=7").json()["topics"]}
    assert topics["T7-05"]["status"] == "difficult" and topics["T7-06"]["status"] == "watch"


# ---------------------------------------------------------------- 3. textbook effectiveness


def test_req3_textbook_comparison_uses_baseline_gain_and_uncertainty(demo):
    client, _ = demo
    res = client.get("/api/analytics/textbooks?grade=7").json()
    pair = res["pairs"][0]
    # raw averages alone would show "no difference" …
    assert pair["raw"]["ci_low"] < 0 < pair["raw"]["ci_high"]
    # … but group B started lower (baseline) and improved more (gain): both reported with CIs
    assert pair["baseline_diff"] < -3
    assert pair["adjusted"]["ci_low"] > 0 and pair["adjusted"]["clusters"] == 6
    assert pair["gain"]["ci_low"] > 0 and pair["gain"]["method"].startswith("кластеризованные")
    assert pair["verdict"] == "observed_difference"
    assert "не доказательство причинного эффекта" in pair["verdict_text"]
    assert any("Исходный уровень различается" in c for c in pair["confounders"])
    tb = {t["code"]: t for t in res["textbooks"]}
    assert tb["TB-B7"]["gain_mean"] > tb["TB-A7"]["gain_mean"]
    assert res["comparable"] and res["common_items"] > 0


def test_req3_gain_matches_independent_recomputation(demo):
    client, _ = demo
    per = defaultdict(lambda: {"pre": [0.0, 0.0], "post": [0.0, 0.0]})
    tb_of = {}
    for r in raw_rows():
        if r["grade"] == "7" and r["assessment_type"] in ("pre", "post"):
            acc = per[r["student_id"]][r["assessment_type"]]
            acc[0] += float(r["score"])
            acc[1] += float(r["max_score"])
            tb_of[r["student_id"]] = r["textbook_id"]
    gains = defaultdict(list)
    for sid, v in per.items():
        gains[tb_of[sid]].append(v["post"][0] / v["post"][1] * 100 - v["pre"][0] / v["pre"][1] * 100)
    tb = {t["code"]: t for t in client.get("/api/analytics/textbooks?grade=7").json()["textbooks"]}
    for code in ("TB-A7", "TB-B7"):
        assert tb[code]["gain_mean"] == pytest.approx(np.mean(gains[code]), abs=0.05)


def test_req3_insufficient_evidence_is_explicit(demo):
    client, _ = demo
    pair = client.get("/api/analytics/textbooks?grade=8").json()["pairs"][0]
    assert pair["verdict"] == "insufficient_evidence"
    assert pair["verdict_text"] == "Недостаточно данных, чтобы определить, какой учебник эффективнее."
    assert any("Мало классов" in r for r in pair["reasons"])


def test_req3_contradicting_gain_blocks_verdict():
    """Lord's paradox: group 2 starts higher and ends slightly higher (outcome independent of baseline).
    Baseline-adjusted outcome favours group 2, gain favours group 1 → no textbook may be declared better."""
    from app.services.settings_store import AnalysisSettings
    from app.services.textbooks import compare_textbooks
    rows, sid = [], 0
    rng = np.random.default_rng(0)
    for tb, base, post_mean in ((1, 40, 60), (2, 60, 65)):
        for c in range(3):
            for _ in range(25):
                sid += 1
                pre = base + rng.normal(0, 3)
                post = post_mean + rng.normal(0, 3)
                for kind, aid, v in (("pre", 1, pre), ("post", 2, post)):
                    rows.append({**{k: None for k in COLUMNS}, "student_id": sid, "class_id": tb * 10 + c,
                                 "class_name": f"C{tb}{c}", "grade": 7, "subject_id": 1, "topic_id": 1, "topic_code": "T",
                                 "topic_name": "T", "topic_order": 1, "assessment_id": aid, "assessment_code": f"A{aid}",
                                 "kind": kind, "comparison_group": "G", "textbook_id": tb, "textbook_code": f"TB{tb}",
                                 "textbook_name": f"TB{tb}", "item_id": "_total", "score": round(v), "max_score": 100})
    df = pd.DataFrame(rows, columns=COLUMNS)
    g = student_gains(df)
    assert len(g) == 150
    pair = compare_textbooks(df, AnalysisSettings())["pairs"][0]
    assert pair["gain"]["diff"] < 0 and pair["gain"]["ci_high"] < 0
    assert pair["verdict"] == "insufficient_evidence"
    assert any("в разные стороны" in r for r in pair["reasons"]), (pair["adjusted"], pair["reasons"])


# ---------------------------------------------------------------- 4. teaching-hour recommendations


def test_req4_recommendation_is_justified_and_constrained(demo):
    client, subject = demo
    inputs = client.get(f"/api/optimizer/inputs?subject_id={subject}&grade=7").json()
    run = client.post("/api/optimizer/run", json={"subject_id": subject, "grade": 7,
                                                  "total_hours": inputs["total_hours"]}).json()
    rows = {r["name"]: r for r in run["rows"]}
    assert run["proposed_total"] == inputs["total_hours"] == 82
    assert all(c["ok"] for c in run["constraints"])
    for r in run["rows"]:
        assert r["min_hours"] <= r["proposed_hours"] <= r["max_hours"]
        assert f"{r['mastery']}%" in r["explanation"]  # every justification cites the measured mastery
        if r["mastery"] < inputs["target_mastery"]:
            assert r["delta"] >= 0  # underperforming topics never lose hours
    assert rows["Формулы сокращённого умножения"]["delta"] > 0
    assert rows["Линейная функция"]["delta"] < 0  # mastered topic releases time
    assert "не значим" in rows["Формулы сокращённого умножения"]["explanation"]
    assert any("не гарантирует" in w for w in run["warnings"])
    # specialist review: accept, then the plan is stored and reported
    assert client.post(f"/api/optimizer/runs/{run['run_id']}/decision", json={"decision": "accept"}).json()["status"] == "accepted"
    rep = client.post("/api/reports", json={"filters": {"grade": 7}}).json()
    assert rep["content"]["optimizer_status"] == "accepted"


def test_req4_stalled_topic_flagged_in_unit():
    topics = [TopicInput(topic_id=1, name="A", current_hours=10, min_hours=5, max_hours=15, mastery=40, student_count=50,
                         gain=0.5, gain_significant=False),
              TopicInput(topic_id=2, name="B", current_hours=10, min_hours=5, max_hours=15, mastery=90, student_count=50)]
    res = optimize(OptimizerInput(total_hours=20, topics=topics))
    assert any("«A»" in w and "методики" in w for w in res["warnings"])


def test_full_journey_uses_consistent_data(demo):
    """Same numbers flow from analysis → AI explanation → report."""
    client, subject = demo
    topics = {t["code"]: t for t in client.get("/api/analytics/topics?grade=7").json()["topics"]}
    ai = client.post("/api/ai/insights", json={"grade": 7}).json()
    assert ai["facts"]["topic.T7-05.mastery"] == topics["T7-05"]["mastery"]
    assert str(topics["T7-05"]["mastery"]) in " ".join(f["text"] for f in ai["payload"]["findings"])
    rep = client.post("/api/reports", json={"filters": {"grade": 7}}).json()
    rt = {t["code"]: t for t in rep["content"]["topics"]}
    assert rt["T7-05"]["mastery"] == topics["T7-05"]["mastery"]
