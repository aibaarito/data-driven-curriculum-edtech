"""Decision-intelligence layer: evidence context, graph, evidence gates, decisions, scenarios, lifecycle.

Unit tests use pure functions; API tests run against the real app and the isolated PostgreSQL test database with
the synthetic demo dataset (and, for the closed loop, the explicitly SIMULATED follow-up file).
"""
from __future__ import annotations

import json
import logging
import random
from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.services import curriculum_graph as cg
from app.services import decisions as dec
from app.services import interventions as iv
from app.services.evidence import assess_textbook_pair, assess_topic
from app.services.importer import validate_dataframe
from app.services.optimizer import OptimizerInput, TopicInput, check_allocation, optimize
from app.services.scenarios import build_scenarios
from app.services.settings_store import AnalysisSettings
from tests.conftest import HEADER, ROOT, make_csv
from tests.test_api import import_demo, upload

S = AnalysisSettings()
FOLLOWUP = ROOT / "app" / "assets" / "data" / "synthetic_followup.csv"


# ============================================================================ unit: graph


def nodes(*specs):
    return {i: cg.Node(i, f"T{i}", f"Тема {i}", subj, grade, i, prio) for i, subj, grade, prio in specs}


def test_find_cycle_detects_and_reports_path_deterministically():
    assert cg.find_cycle([1, 2, 3], [(1, 2), (2, 3)]) is None
    cyc = cg.find_cycle([1, 2, 3], [(2, 3), (3, 1), (1, 2)])
    assert cyc == [1, 2, 3, 1]
    assert cg.find_cycle([1, 2, 3], [(1, 2), (2, 3), (3, 1)]) == cyc  # input order does not matter


def test_validate_edges_rejects_self_duplicate_unknown_cross_subject_and_cycles():
    ns = nodes((1, 1, 7, 2), (2, 1, 7, 2), (3, 2, 7, 2))
    codes = lambda edges: {i["code"] for i in cg.validate_edges(ns, [cg.Edge(a, b) for a, b in edges])}  # noqa: E731
    assert codes([(1, 1)]) == {"SELF_PREREQUISITE"}
    assert codes([(1, 2), (1, 2)]) == {"DUPLICATE_EDGE"}
    assert codes([(1, 99)]) == {"UNKNOWN_TOPIC"}
    assert codes([(1, 3)]) == {"CROSS_SUBJECT"}
    assert codes([(1, 2), (2, 1)]) == {"CYCLE"}
    assert codes([(1, 2)]) == set()
    # rejected edges never count
    assert cg.validate_edges(ns, [cg.Edge(1, 2), cg.Edge(2, 1, review_status="rejected")]) == []


def test_topological_order_is_deterministic_and_handles_disconnected_topics():
    ns = nodes((1, 1, 7, 2), (2, 1, 7, 2), (3, 1, 7, 2), (4, 1, 7, 2))
    edges = [cg.Edge(3, 2), cg.Edge(1, 2)]
    a = cg.topological_order(cg.Graph(ns, edges))
    b = cg.topological_order(cg.Graph(ns, list(reversed(edges))))
    assert a == b == [1, 3, 2, 4]
    with pytest.raises(cg.GraphError):
        cg.topological_order(cg.Graph(ns, [cg.Edge(1, 2), cg.Edge(2, 1)]))


def test_priority_score_is_normalized_and_suppressed_without_evidence():
    at_target = cg.priority_score(80, 3, 5, 5, "supported", 75)
    assert at_target["score"] == 0
    assert cg.priority_score(30, 3, 5, 5, "insufficient", 75)["score"] == 0
    full = cg.priority_score(0, 3, 5, 5, "supported", 75)
    assert full["score"] == 100.0 and all(0 <= v <= 1 for v in full["components"].values())
    weaker = cg.priority_score(60, 2, 0, 5, "supported", 75)["score"]
    stronger_gap = cg.priority_score(40, 2, 0, 5, "supported", 75)["score"]
    assert 0 < weaker < stronger_gap
    assert cg.priority_score(40, 2, 0, 5, "exploratory", 75)["score"] == pytest.approx(stronger_gap * 0.6, abs=0.1)


def topic_row(tid, mastery, n=40, classes=3, status="difficult", interp="low_no_measurable_gain", gain=None):
    return {"topic_id": tid, "code": f"T{tid}", "name": f"Тема {tid}", "grade": 7, "mastery": mastery,
            "student_count": n, "class_count": classes, "assessment_count": 2, "status": status,
            "interpretation_code": interp, "interpretation": "", "gain": gain, "ci_low": None, "ci_high": None,
            "class_mean": mastery, "hours": 10}


GAIN = {"n_paired": 40, "direction": "inconclusive", "mean_gain": 0.5, "ci_low": -3, "ci_high": 4, "ci_level": 99,
        "family_size": 3}


def test_diagnose_flags_foundational_gap_without_causal_claim_and_empty_state():
    ns = nodes((1, 1, 7, 3), (2, 1, 7, 2), (3, 1, 7, 2), (4, 1, 7, 2))
    g = cg.Graph(ns, [cg.Edge(1, 2), cg.Edge(2, 3)])
    stats = {1: topic_row(1, 40, gain=GAIN), 2: topic_row(2, 45, gain=GAIN), 3: topic_row(3, 90, status="ok",
                                                                                       interp="ok", gain=GAIN)}
    d = cg.diagnose(g, stats, S, grade=7)
    by = {n["topic_id"]: n for n in d["nodes"]}
    assert d["valid"] and d["foundational_gaps"] == [1]
    assert by[1]["descendants"] == [2, 3] and by[3]["ancestors"] == [1, 2]
    assert by[4]["status"] == "no_outcome_data" and by[4]["priority"]["score"] == 0  # disconnected, no data
    text = " ".join(by[1]["why"])
    assert "предшествует" in text and "причинное влияние" in text and "не установлено" in text
    assert d["chains"][0]["path"] == [1, 2, 3] and d["chains"][0]["weak_count"] == 2
    empty = cg.diagnose(cg.Graph({}, []), {}, S)
    assert empty["nodes"] == [] and empty["valid"] and empty["ranking"] == []


def test_invalid_graph_is_reported_not_traversed():
    ns = nodes((1, 1, 7, 2), (2, 1, 7, 2))
    d = cg.diagnose(cg.Graph(ns, [cg.Edge(1, 2), cg.Edge(2, 1)]), {}, S, 7)
    assert d["valid"] is False and any(i["code"] == "CYCLE" for i in d["issues"]) and d["chains"] == []


# ============================================================================ unit: evidence


def test_evidence_categories_for_topics():
    assert assess_topic(topic_row(1, None, n=0, classes=0), S)["category"] == "insufficient"
    small = assess_topic(topic_row(1, 40, n=5), S)
    assert small["category"] == "insufficient" and small["allows_action"] is False
    no_base = assess_topic(topic_row(1, 40, gain=None), S)
    assert no_base["category"] == "exploratory" and "входной" in no_base["reasons"][0]
    assert assess_topic(topic_row(1, 40, classes=1, gain=GAIN), S)["category"] == "exploratory"
    few_pairs = GAIN | {"n_paired": 3, "direction": "insufficient"}
    assert assess_topic(topic_row(1, 40, gain=few_pairs), S)["category"] == "exploratory"
    low_cov = GAIN | {"n_paired": 15}
    assert assess_topic(topic_row(1, 40, gain=low_cov), S)["category"] == "exploratory"
    ok = assess_topic(topic_row(1, 40, gain=GAIN), S)
    assert ok["category"] == "supported" and ok["allows_action"] and ok["dimensions"]["pairing_coverage"] == 1.0


def test_evidence_categories_for_textbook_pairs():
    base = {"textbook_a": 1, "textbook_b": 2, "common_items": 10, "reasons": [], "verdict": "insufficient_evidence"}
    assert assess_textbook_pair(base | {"common_items": 0})["category"] == "incomparable"
    assert assess_textbook_pair(base | {"reasons": ["Учебники используются в разных параллелях — ..."]})[
        "category"] == "incomparable"
    assert assess_textbook_pair(base)["category"] == "insufficient"
    assert assess_textbook_pair(base | {"verdict": "observed_difference", "evidence_level": "exploratory"})[
        "category"] == "exploratory"
    assert assess_textbook_pair(base | {"verdict": "observed_difference", "evidence_level": "observational"})[
        "category"] == "supported"


# ============================================================================ unit: decisions


def test_decision_rules_never_answer_a_decline_with_more_hours():
    decline = GAIN | {"direction": "decline", "mean_gain": -6, "ci_low": -9, "ci_high": -2}
    c = dec.topic_candidates([topic_row(1, 40, interp="low_declining", gain=decline)], S, "fp")[0]
    assert c["action"]["code"] == "review_methodology"
    assert any(r["code"] == "increase_hours" for r in c["rejected_alternatives"])
    assert c["statement_kinds"]["hypothesis"] == "hypothesis" and "не проверена" in c["hypothesis"]


@pytest.mark.parametrize("row, action", [
    (topic_row(1, 40, n=4), "collect_more_evidence"),
    (topic_row(1, 40, gain=GAIN), "review_methodology"),
    (topic_row(1, 40, interp="low_no_baseline"), "add_diagnostic_assessment"),
    (topic_row(1, 40, interp="low_but_improving", gain=GAIN | {"direction": "increase", "ci_low": 2}),
     "increase_hours"),
])
def test_decision_rule_table(row, action):
    if row["student_count"] < S.min_students_topic:
        row = row | {"status": "insufficient_data"}
    c = dec.topic_candidates([row], S, "fp")[0]
    assert c["action"]["code"] == action
    assert c["id"] == dec.topic_candidates([row], S, "fp")[0]["id"]  # stable id
    assert c["id"] != dec.topic_candidates([row], S, "other-fp")[0]["id"]  # bound to the evidence version
    assert "predicted" not in json.dumps(c) and "прогноз" not in json.dumps(c, ensure_ascii=False).lower()


def test_ok_topics_without_problems_generate_no_candidates():
    assert dec.topic_candidates([topic_row(1, 90, status="ok", interp="ok", gain=GAIN)], S, "fp") == []


# ============================================================================ unit: scenarios


def T(i, cur, lo, hi, mastery=None, prio=2, n=50, locked=False, prereq=(), direction="inconclusive"):
    return TopicInput(topic_id=i, name=f"Тема {i}", current_hours=cur, min_hours=lo, max_hours=hi, priority=prio,
                      mastery=mastery, student_count=n, locked=locked, prerequisites=list(prereq),
                      gain=0.0 if mastery is not None else None, gain_direction=direction if mastery else None)


def test_balanced_scenario_reproduces_the_single_plan_optimizer_exactly():
    inp = OptimizerInput(total_hours=40, topics=[T(1, 10, 5, 15, 90), T(2, 10, 5, 15, 40, prio=3),
                                                 T(3, 10, 5, 15, 70), T(4, 10, 5, 15, 60, prereq=[2])])
    sc = {s["key"]: s for s in build_scenarios(inp, {i: "supported" for i in range(1, 5)}, {})}
    assert [r["proposed_hours"] for r in sc["balanced"]["result"]["rows"]] == \
           [r["proposed_hours"] for r in optimize(inp)["rows"]]


def test_conservative_scenario_holds_topics_without_supported_evidence():
    inp = OptimizerInput(total_hours=40, topics=[T(1, 10, 5, 15, 90), T(2, 10, 5, 15, 40, prio=3),
                                                 T(3, 10, 5, 15, 50), T(4, 10, 5, 15, 60)])
    sc = {s["key"]: s for s in build_scenarios(inp, {1: "supported", 2: "supported", 3: "exploratory",
                                                     4: "supported"}, {})}
    cons = {r["topic_id"]: r for r in sc["conservative"]["result"]["rows"]}
    assert cons[3]["delta"] == 0 and "сценарий сохраняет часы" in cons[3]["explanation"]
    assert sc["conservative"]["parameters"]["held_for_evidence"] == ["Тема 3"]
    assert sc["conservative"]["parameters"]["max_change_pct"] == 15
    assert sc["gap_focused"]["parameters"]["max_change_pct"] == 45


def test_identical_scenarios_are_reported_transparently():
    inp = OptimizerInput(total_hours=20, topics=[T(1, 10, 10, 10, 40), T(2, 10, 10, 10, 90)])  # fully pinned
    sc = build_scenarios(inp, {1: "supported", 2: "supported"}, {})
    assert all(s["ok"] and len(s["identical_to"]) == 2 and "результат расчёта" in s["identical_note"] for s in sc)


def test_scenario_errors_are_structured_per_scenario():
    inp = OptimizerInput(total_hours=5, topics=[T(1, 10, 5, 15, 40), T(2, 10, 5, 15, 90)])
    sc = build_scenarios(inp, {}, {})
    assert all(not s["ok"] and s["error"]["code"] == "INFEASIBLE" and s["error"]["details"] for s in sc)
    pol = OptimizerInput(total_hours=17, topics=[T(1, 10, 5, 15, 40, prio=3), T(2, 10, 5, 15, 60)])
    assert all(s["error"]["code"] == "POLICY_INFEASIBLE" for s in build_scenarios(pol, {}, {}))


def test_all_scenarios_satisfy_hard_constraints_on_random_problems():
    rng = random.Random(20261111)
    for _ in range(120):
        k = rng.randint(2, 8)
        topics = []
        for i in range(1, k + 1):
            lo = rng.choice([0, 1, 2, 4])
            hi = lo + rng.choice([2, 4, 8, 12])
            cur = rng.randrange(int(lo * 2), int(hi * 2) + 1) / 2
            topics.append(T(i, cur, lo, hi, rng.choice([None, 30, 50, 65, 80, 95]), prio=rng.randint(1, 3),
                            n=rng.choice([5, 50]), locked=rng.random() < 0.15,
                            direction=rng.choice(["increase", "decline", "inconclusive", "insufficient"])))
        total = sum(t.current_hours for t in topics) + rng.choice([-2, -1, 0, 0, 1, 2])
        if total <= 0:
            continue
        inp = OptimizerInput(total_hours=total, topics=topics, allow_policy_relaxation=rng.random() < 0.5)
        ev = {t.topic_id: rng.choice(["supported", "exploratory", "insufficient"]) for t in topics}
        for s in build_scenarios(inp, ev, {t.topic_id: rng.randint(0, 5) for t in topics}):
            if not s["ok"]:
                assert s["error"]["code"] in ("INFEASIBLE", "POLICY_INFEASIBLE")
                continue
            alloc = {r["topic_id"]: r["proposed_hours"] for r in s["result"]["rows"]}
            assert all(c["ok"] for c in check_allocation(inp, alloc)), (s["key"], s["result"]["constraints"])
            assert abs(sum(alloc.values()) - total) < 1e-9
            for t in topics:
                if t.locked:
                    assert alloc[t.topic_id] == t.current_hours


# ============================================================================ unit: importer + lifecycle


def test_import_rejects_cyclic_prerequisites():
    header = HEADER + ",topic_prerequisites"
    rows = ["s,STU-1,7,7А,Математика,T1,Тема 1,A1,post,2025-09-10,G1,Q1,2,4,TB-A,10,T2",
            "s,STU-1,7,7А,Математика,T2,Тема 2,A1,post,2025-09-10,G1,Q1,2,4,TB-A,10,T3",
            "s,STU-1,7,7А,Математика,T3,Тема 3,A1,post,2025-09-10,G1,Q1,2,4,TB-A,10,T1"]
    from app.services.importer import read_table
    res = validate_dataframe(read_table(make_csv(rows, header), "x.csv"))
    errs = [e for e in res.errors if e.code == "CYCLIC_PREREQUISITE"]
    assert len(errs) == 1 and "T1 → T3 → T2 → T1" in errs[0].message
    assert not res.ok


def test_lifecycle_transitions():
    iv.check_transition("planned", "implemented")
    iv.check_transition("implemented", "awaiting_outcome")
    for a, b in [("planned", "evaluated"), ("cancelled", "implemented"), ("evaluated", "planned"),
                 ("awaiting_outcome", "cancelled"), ("planned", "awaiting_outcome")]:
        with pytest.raises(iv.TransitionError):
            iv.check_transition(a, b)


def test_outcome_evaluation_reports_association_with_missingness():
    rows = []
    for s in range(12):
        rows.append((s, 1, date(2026, 5, 1), "post", 5.0, 10.0))
        if s < 10:  # two students lost to follow-up
            rows.append((s, 1, date(2026, 10, 1), "current", 7.0 if s % 2 else 6.0, 10.0))
    df = pd.DataFrame(rows, columns=["student_id", "topic_id", "assessment_date", "kind", "score", "max_score"])
    baseline = {"fingerprint": "fp", "topics": [{"topic_id": 1, "name": "Тема 1", "mastery": 50.0}]}
    out = iv.evaluate(df, baseline, date(2026, 9, 1))
    t = out["topics"][0]
    assert out["ready"] and out["comparison_group"] is None
    assert t["after"] == 65.0 and t["descriptive_change"] == 15.0 and t["baseline_consistent"]
    assert t["paired_students"] == 10 and t["lost_to_follow_up"] == 2 and t["direction"] == "increase"
    assert "НЕ доказывает" in out["statements"]["causal"]
    none = iv.evaluate(df, baseline, date(2027, 1, 1))
    assert none["ready"] is False and none["topics"][0]["direction"] == "no_outcome_data"


# ============================================================================ API


@pytest.fixture()
def demo(client):
    import_demo(client)
    sid = client.get("/api/meta").json()["subjects"][0]["id"]
    graph = client.get(f"/api/curriculum/graph?subject_id={sid}&grade=7").json()
    ids = {n["code"]: n["topic_id"] for n in graph["nodes"]}
    return client, sid, ids


def test_api_graph_is_valid_deterministic_and_identifies_foundational_gap(demo):
    client, sid, ids = demo
    a = client.get(f"/api/curriculum/graph?subject_id={sid}&grade=7").json()
    b = client.get(f"/api/curriculum/graph?subject_id={sid}&grade=7").json()
    strip = lambda g: {k: v for k, v in g.items() if k != "context"}  # noqa: E731
    assert strip(a) == strip(b) and a["context"]["fingerprint"] == b["context"]["fingerprint"]
    assert a["valid"] and len(a["nodes"]) == 8
    assert a["ranking"][0]["topic_id"] == ids["T7-05"] and a["ranking"][0]["foundational_gap"]
    assert a["chains"][0]["path"] == [ids[c] for c in ("T7-02", "T7-03", "T7-04", "T7-05", "T7-06")]
    assert a["context"]["synthetic"] is True and a["context"]["algorithm_version"] == "ddc-2.0.0"
    assert client.get("/api/curriculum/graph?subject_id=9999").status_code == 404


def test_api_prerequisite_mutations_are_validated(demo, client):
    _, sid, ids = demo
    post = lambda a, b, origin="expert": client.post("/api/curriculum/prerequisites", json={  # noqa: E731
        "topic_id": b, "prerequisite_id": a, "origin": origin})
    cyc = post(ids["T7-06"], ids["T7-02"])  # T7-02 → … → T7-06 already exists: closing the loop is a cycle
    assert cyc.status_code == 422 and cyc.json()["detail"]["code"] == "GRAPH_INVALID"
    assert any(i["code"] == "CYCLE" for i in cyc.json()["detail"]["issues"])
    assert post(ids["T7-02"], 999999).status_code == 404
    assert post(ids["T7-02"], ids["T7-02"]).status_code == 422
    assert post(ids["T7-04"], ids["T7-05"]).status_code == 409  # duplicate of an imported edge
    before = client.get(f"/api/curriculum/graph?subject_id={sid}&grade=7").json()
    sug = post(ids["T7-01"], ids["T7-07"], origin="suggested")
    assert sug.status_code == 201 and sug.json()["review_status"] == "pending"
    after = client.get(f"/api/curriculum/graph?subject_id={sid}&grade=7").json()
    # a pending edge is listed for review but changes neither diagnostics nor the evidence fingerprint
    assert after["context"]["fingerprint"] == before["context"]["fingerprint"]
    assert next(n for n in after["nodes"] if n["topic_id"] == ids["T7-07"])["prerequisites"] == []
    eid = sug.json()["id"]
    assert client.post(f"/api/curriculum/prerequisites/{eid}/review", json={"decision": "approve"}).status_code == 200
    assert client.post(f"/api/curriculum/prerequisites/{eid}/review", json={"decision": "approve"}).status_code == 409
    approved = client.get(f"/api/curriculum/graph?subject_id={sid}&grade=7").json()
    assert approved["context"]["fingerprint"] != before["context"]["fingerprint"]
    assert client.delete(f"/api/curriculum/prerequisites/{eid}").status_code == 200
    # a second subject: cross-subject edges are refused
    other = make_csv(["s2,STU-9,7,7Б,Физика,PH-1,Механика,PA1,post,2025-09-10,,Q1,2,4,TB-P,10"])
    r = upload(client, other)
    assert r.json()["ok"], r.json()["errors"][:2]
    assert client.post(f"/api/imports/{r.json()['batch_id']}/commit").status_code == 200
    ph = client.get(f"/api/curriculum/graph?subject_id={sid + 1}&grade=7").json()["nodes"][0]["topic_id"]
    cross = post(ids["T7-01"], ph)
    assert cross.status_code == 422 and cross.json()["detail"]["issues"][0]["code"] == "CROSS_SUBJECT"


def test_api_topic_passport_numbers_match_topic_analytics_and_scope_is_enforced(demo):
    client, sid, ids = demo
    topics = {t["topic_id"]: t for t in client.get("/api/analytics/topics?grade=7").json()["topics"]}
    p = client.get(f"/api/evidence/topics/{ids['T7-05']}?grade=7").json()
    t = topics[ids["T7-05"]]
    st = p["passport"]["statistics"]
    assert st["mastery"] == t["mastery"] == 40.9
    assert (st["mean_gain"], st["gain_ci_low"], st["gain_ci_high"]) == (t["gain"]["mean_gain"], t["gain"]["ci_low"],
                                                                         t["gain"]["ci_high"])
    assert p["passport"]["sample"] == {"students": t["student_count"], "classes": t["class_count"],
                                       "paired": t["gain"]["n_paired"]}
    assert p["passport"]["gate"]["category"] == "supported"
    assert p["decision"]["action"]["code"] == "review_methodology"
    assert any("не доказывают" in u for u in p["passport"]["uncertainty"])
    # cross-scope contamination is refused, not silently broadened
    mism = client.get(f"/api/evidence/topics/{ids['T7-05']}?grade=8")
    assert mism.status_code == 422 and mism.json()["detail"]["code"] == "SCOPE_MISMATCH"
    assert client.get("/api/evidence/topics/999999").status_code == 404
    # a class filter changes the evidence context (different scope → different fingerprint)
    cls = client.get("/api/meta").json()["classes"][0]["id"]
    pc = client.get(f"/api/evidence/topics/{ids['T7-05']}?grade=7&class_id={cls}").json()
    assert pc["context"]["fingerprint"] != p["context"]["fingerprint"]
    assert pc["passport"]["gate"]["category"] == "exploratory"  # one class only


def test_api_textbook_passports_gate_winners(demo):
    client, sid, _ = demo
    g7 = client.get(f"/api/evidence/textbooks?subject_id={sid}&grade=7").json()["passports"]
    g8 = client.get(f"/api/evidence/textbooks?subject_id={sid}&grade=8").json()["passports"]
    assert [p["gate"]["category"] for p in g7] == ["exploratory"] and g7[0]["winner_allowed"]
    assert [p["gate"]["category"] for p in g8] == ["insufficient"] and not g8[0]["winner_allowed"]


def test_api_scenario_preview_is_real_and_does_not_persist(demo, migrated_db):
    client, sid, ids = demo
    body = {"subject_id": sid, "grade": 7, "total_hours": 82}
    p = client.post("/api/optimizer/scenarios/preview", json=body).json()
    assert p["persisted"] is False and client.get("/api/optimizer/runs").json() == []
    assert [s["key"] for s in p["scenarios"]] == ["conservative", "balanced", "gap_focused"]
    for s in p["scenarios"]:
        assert s["ok"] and s["result"]["proposed_total"] == 82 and all(c["ok"] for c in s["result"]["constraints"])
    single = client.post("/api/optimizer/run", json=body).json()
    bal = next(s for s in p["scenarios"] if s["key"] == "balanced")
    assert [r["proposed_hours"] for r in bal["result"]["rows"]] == [r["proposed_hours"] for r in single["rows"]]
    cons = next(s for s in p["scenarios"] if s["key"] == "conservative")
    assert cons["diff"]["max_abs_change"] <= bal["diff"]["max_abs_change"]
    t5 = next(r for r in p["comparison"] if r["topic_id"] == ids["T7-05"])
    assert set(t5["scenarios"]) == {"conservative", "balanced", "gap_focused"}
    for total, code in ((10, "INFEASIBLE"), (70, "POLICY_INFEASIBLE")):
        e = client.post("/api/optimizer/scenarios/preview", json=body | {"total_hours": total}).json()
        assert all(not s["ok"] and s["error"]["code"] == code for s in e["scenarios"])
    locked = client.post("/api/optimizer/scenarios/preview", json=body | {"topics": [
        {"topic_id": ids["T7-07"], "locked": True}]}).json()
    for s in locked["scenarios"]:
        r = next(x for x in s["result"]["rows"] if x["topic_id"] == ids["T7-07"])
        assert r["delta"] == 0 and r["locked"]


def test_api_scenario_save_is_stale_safe_and_idempotent(demo):
    client, sid, _ = demo
    body = {"subject_id": sid, "grade": 7, "total_hours": 82}
    p = client.post("/api/optimizer/scenarios/preview", json=body).json()
    save = body | {"scenario_key": "gap_focused", "fingerprint": p["fingerprint"], "idempotency_key": "save-key-0001"}
    first = client.post("/api/optimizer/scenarios/save", json=save)
    assert first.status_code == 201 and first.json()["idempotent_replay"] is False
    again = client.post("/api/optimizer/scenarios/save", json=save)
    assert again.status_code == 201 and again.json()["idempotent_replay"] is True
    assert again.json()["run_id"] == first.json()["run_id"]
    assert len(client.get("/api/optimizer/runs").json()) == 1
    conflict = client.post("/api/optimizer/scenarios/save", json=save | {"scenario_key": "balanced"})
    assert conflict.status_code == 409 and conflict.json()["detail"]["code"] == "IDEMPOTENCY_CONFLICT"
    stale = client.post("/api/optimizer/scenarios/save", json=save | {"fingerprint": "0" * 32,
                                                                       "idempotency_key": "save-key-0002"})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "STALE_SCENARIO"
    bad = client.post("/api/optimizer/scenarios/save", json=save | {"total_hours": 70,
                                                                     "idempotency_key": "save-key-0003"})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "POLICY_INFEASIBLE"
    detail = client.get(f"/api/optimizer/runs/{first.json()['run_id']}").json()
    assert detail["scenario_key"] == "gap_focused" and detail["evidence_status"] == "current"
    assert detail["evidence_snapshot"]["context"]["fingerprint"] == p["fingerprint"]
    assert "S7A-" not in json.dumps(detail["evidence_snapshot"])  # aggregates only, no student identifiers


def test_api_stale_recommendation_requires_acknowledgement_and_history_is_frozen(demo):
    client, sid, _ = demo
    run = client.post("/api/optimizer/run", json={"subject_id": sid, "grade": 7, "total_hours": 82}).json()
    snapshot_before = client.get(f"/api/optimizer/runs/{run['run_id']}").json()
    settings = client.get("/api/settings").json()["analysis"]
    assert client.put("/api/settings", json={**settings, "target_mastery": 80}).status_code == 200
    detail = client.get(f"/api/optimizer/runs/{run['run_id']}").json()
    assert detail["evidence_status"] == "stale"
    assert detail["result"] == snapshot_before["result"]  # history not recomputed
    assert detail["evidence_snapshot"] == snapshot_before["evidence_snapshot"]
    r = client.post(f"/api/optimizer/runs/{run['run_id']}/decision", json={"decision": "accept"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "STALE_RECOMMENDATION"
    ok = client.post(f"/api/optimizer/runs/{run['run_id']}/decision",
                     json={"decision": "accept", "acknowledge_stale": True, "note": "Принято по снимку"})
    assert ok.status_code == 200 and ok.json()["evidence_status"] == "stale"
    audit = client.get(f"/api/optimizer/runs/{run['run_id']}").json()["audit"]
    assert [a["action"] for a in audit] == ["create", "accept"] and audit[1]["detail"]["stale_acknowledged"]


def test_api_decision_center_overview(demo):
    client, sid, ids = demo
    d = client.get(f"/api/decisions/overview?subject_id={sid}&grade=7").json()
    by = {c.get("topic_id"): c for c in d["candidates"] if c["kind"] == "topic"}
    assert by[ids["T7-05"]]["action"]["code"] == "review_methodology"
    assert by[ids["T7-06"]]["action"]["code"] == "increase_hours"
    assert by[ids["T7-05"]]["constraint_impact"]["sensitivity"] is not None
    assert any(c["kind"] == "textbook" and c["action"]["code"] == "review_textbook" for c in d["candidates"])
    assert d["readiness"]["supported"] == 8 and d["plan"]["available"] and d["plan"]["total_hours"] == 82
    assert d["graph"]["foundational_gaps"][0]["topic_id"] == ids["T7-05"]
    assert client.get(f"/api/decisions/overview?subject_id={sid}&grade=13").status_code == 422


def test_api_closed_loop_lifecycle_and_simulated_outcome(demo, client):
    _, sid, ids = demo
    run = client.post("/api/optimizer/run", json={"subject_id": sid, "grade": 7, "total_hours": 82}).json()
    rejected = client.post("/api/optimizer/run", json={"subject_id": sid, "grade": 7, "total_hours": 82}).json()
    client.post(f"/api/optimizer/runs/{rejected['run_id']}/decision", json={"decision": "reject"})
    r = client.post("/api/interventions", json={"run_id": rejected["run_id"], "description": "Нельзя"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "INVALID_TRANSITION"
    proposed = client.post("/api/interventions", json={"run_id": run["run_id"], "description": "Ещё не принято"})
    assert proposed.status_code == 409
    assert client.post(f"/api/optimizer/runs/{run['run_id']}/decision",
                       json={"decision": "accept"}).status_code == 200
    again = client.post(f"/api/optimizer/runs/{run['run_id']}/decision", json={"decision": "reject"})
    assert again.status_code == 409
    created = client.post("/api/interventions", json={"run_id": run["run_id"], "description": "Новый план часов",
                                                      "planned_on": "2026-08-25"})
    assert created.status_code == 201
    x = created.json()
    assert x["status"] == "planned" and x["synthetic"] is True
    assert {t["topic_id"] for t in x["baseline"]["topics"]} == {c["topic_id"] for c in x["baseline"]["hour_changes"]}
    assert client.post("/api/interventions", json={"run_id": run["run_id"], "description": "дубль"}).status_code == 409
    url = f"/api/interventions/{x['id']}"
    bad = client.post(url + "/transition", json={"status": "awaiting_outcome"})
    assert bad.status_code == 409 and bad.json()["detail"]["code"] == "INVALID_TRANSITION"
    assert client.post(url + "/evaluate").status_code == 409
    assert client.post(url + "/transition", json={"status": "implemented"}).status_code == 422  # date required
    assert client.post(url + "/transition", json={"status": "implemented",
                                                  "implemented_on": "2099-01-01"}).status_code == 422
    assert client.post(url + "/transition", json={"status": "implemented",
                                                  "implemented_on": "2026-09-01"}).status_code == 200
    assert client.post(url + "/transition", json={"status": "awaiting_outcome"}).status_code == 200
    waiting = client.post(url + "/evaluate").json()
    assert waiting["status"] == "awaiting_outcome" and waiting["evaluation"]["ready"] is False
    # explicitly SIMULATED follow-up assessment (scripts/generate_followup.py)
    fu = upload(client, FOLLOWUP.read_bytes(), "synthetic_followup_SIMULATED.csv").json()
    assert fu["ok"], fu["errors"][:3]
    assert client.post(f"/api/imports/{fu['batch_id']}/commit").status_code == 200
    done = client.post(url + "/evaluate").json()
    ev = done["evaluation"]
    assert done["status"] == "evaluated" and ev["ready"] and ev["comparison_group"] is None and ev["synthetic"]
    t5 = next(t for t in ev["topics"] if t["topic_id"] == ids["T7-05"])
    assert t5["frozen_mastery"] == 40.9 and t5["baseline_consistent"] and t5["paired_students"] > 100
    assert t5["paired"]["ci_level"] == ev["ci_level"]
    assert "НЕ доказывает" in ev["statements"]["causal"]
    full = client.get(url).json()
    assert [a["to"] for a in full["audit"]] == ["planned", "implemented", "awaiting_outcome", "awaiting_outcome",
                                                "evaluated"]
    assert full["baseline_status"] == "superseded"  # new data arrived after the plan was frozen
    assert client.post(url + "/transition", json={"status": "cancelled"}).status_code == 409
    listing = client.get(f"/api/interventions?subject_id={sid}&grade=7").json()
    assert [i["id"] for i in listing] == [x["id"]]


def test_api_request_id_and_sanitized_access_log(client, caplog):
    caplog.set_level(logging.INFO, logger="ddc.access")
    r = client.get("/api/analytics/topics?grade=7&class_id=424242", headers={"X-Request-ID": "trace-abcdef12"})
    assert r.headers["x-request-id"] == "trace-abcdef12"
    generated = client.get("/api/meta", headers={"X-Request-ID": "bad id with spaces"})
    assert len(generated.headers["x-request-id"]) == 16
    lines = [json.loads(rec.getMessage()) for rec in caplog.records if rec.name == "ddc.access"]
    assert any(x["request_id"] == "trace-abcdef12" and x["route"] == "/api/analytics/topics" and x["status"] == 200
               for x in lines)
    assert "424242" not in caplog.text


def test_api_report_carries_evidence_fingerprint(demo):
    client, sid, _ = demo
    rep = client.post("/api/reports", json={"filters": {"subject_id": sid, "grade": 7}, "include_ai": False}).json()
    assert len(rep["content"]["evidence"]["fingerprint"]) == 32 and rep["evidence_status"] == "current"
    assert np.isfinite(rep["content"]["overview"]["average_mastery"])
