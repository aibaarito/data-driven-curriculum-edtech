import random

import numpy as np
import pytest

from app.services.optimizer import (
    POLICY_RELAX_ORDER,
    InfeasibleError,
    OptimizerInput,
    TopicInput,
    check_allocation,
    check_policies,
    optimize,
)


def T(i, cur, lo, hi, mastery=None, prio=2, n=50, locked=False, prereq=(), gain=None, direction=None):
    return TopicInput(topic_id=i, name=f"Тема {i}", current_hours=cur, min_hours=lo, max_hours=hi, priority=prio,
                      mastery=mastery, student_count=n, locked=locked, prerequisites=list(prereq), gain=gain,
                      gain_direction=direction)


def run(topics, total, **kw):
    return optimize(OptimizerInput(total_hours=total, topics=topics, **kw))


def by_id(res):
    return {r["topic_id"]: r for r in res["rows"]}


def hard_ok(res):
    return all(c["ok"] for c in res["constraints"])


def test_total_preserved_and_hard_constraints_reported():
    res = run([T(1, 10, 5, 15, 90), T(2, 10, 5, 15, 40), T(3, 10, 5, 15, 70)], 30)
    assert res["proposed_total"] == 30 and hard_ok(res)
    rows = by_id(res)
    assert rows[2]["delta"] > 0 and rows[1]["delta"] < 0
    assert all(p["status"] == "applied" for p in res["policy_checks"]) and res["relaxed_policies"] == []


def test_below_target_topics_are_never_reduced_by_default():
    res = run([T(1, 10, 5, 15, 95), T(2, 10, 5, 15, 30, prio=3), T(3, 10, 5, 15, 70, prio=1), T(4, 10, 5, 15, 72)], 40)
    for tid in (2, 3, 4):
        assert by_id(res)[tid]["delta"] >= 0


def test_reduced_total_is_infeasible_without_explicit_relaxation():
    topics = [T(1, 10, 5, 15, 40, prio=3), T(2, 10, 5, 15, 60), T(3, 10, 5, 15, 70)]
    with pytest.raises(InfeasibleError) as e:
        run(topics, 24)
    assert e.value.code == "POLICY_INFEASIBLE"
    assert any("allow_policy_relaxation" in d for d in e.value.details)


def test_explicit_relaxation_is_minimal_reported_and_explained():
    topics = [T(1, 10, 5, 15, 40, prio=3), T(2, 10, 5, 15, 60), T(3, 10, 5, 15, 70)]
    res = run(topics, 24, allow_policy_relaxation=True)
    assert res["proposed_total"] == 24 and hard_ok(res)
    assert res["relaxed_policies"] == ["protect_below_target"]  # only the policy that was actually needed
    status = {p["policy"]: p for p in res["policy_checks"]}
    assert status["protect_below_target"]["status"] == "relaxed"
    assert set(status["protect_below_target"]["affected_topics"]) == {r["name"] for r in res["rows"] if r["delta"] < 0}
    for r in res["rows"]:
        if r["delta"] < 0:
            assert "уменьшения общего объёма" in r["explanation"]
            assert "высвободить время" not in r["explanation"]
    assert any("уменьшен" in w for w in res["warnings"])


def test_reduction_from_lower_total_explained_for_donor_topics():
    res = run([T(1, 10, 5, 15, 95), T(2, 10, 5, 15, 90), T(3, 10, 5, 15, 40)], 27)
    for r in res["rows"]:
        if r["delta"] < 0:
            assert "уменьшения общего объёма" in r["explanation"]


def test_locked_topics_unchanged():
    res = run([T(1, 12, 5, 15, 95, locked=True), T(2, 10, 5, 15, 40), T(3, 10, 5, 15, 90)], 32)
    assert by_id(res)[1]["proposed_hours"] == 12 and res["proposed_total"] == 32


def test_prerequisite_of_weak_topic_not_reduced():
    res = run([T(1, 10, 5, 15, 95), T(2, 10, 5, 15, 40, prereq=[1]), T(3, 10, 5, 15, 95)], 30)
    assert by_id(res)[1]["delta"] >= 0 and "пререквизит" in by_id(res)[1]["explanation"]


def test_topics_without_reliable_data_keep_hours():
    res = run([T(1, 10, 5, 15, None), T(2, 10, 5, 15, 40), T(3, 10, 5, 15, 90), T(4, 8, 5, 15, 30, n=2)], 38)
    rows = by_id(res)
    assert rows[1]["delta"] == 0 and rows[4]["delta"] == 0
    assert any("недостаточно данных" in w for w in res["warnings"])


@pytest.mark.parametrize("direction,gain", [("decline", -8.0), ("inconclusive", 0.5), ("increase", 12.0)])
def test_gain_direction_is_sign_aware(direction, gain):
    res = run([T(1, 10, 5, 15, 30, prio=3, gain=gain, direction=direction), T(2, 10, 5, 15, 95)], 20)
    expl = by_id(res)[1]["explanation"]
    if direction == "decline":
        assert by_id(res)[1]["delta"] == 0  # hours are not changed automatically for a declining topic
        assert "СНИЗИЛСЯ" in expl and "осваивается" not in expl and "прирост" not in expl
        assert any("снижение" in w.lower() for w in res["warnings"])
    elif direction == "inconclusive":
        assert "не установлено" in expl and "значим" not in expl
    else:
        assert "статистически значим" in expl and "связь с числом часов не установлена" in expl


def test_legacy_significant_flag_with_negative_gain_is_a_decline():
    t = TopicInput(topic_id=1, name="A", current_hours=10, min_hours=5, max_hours=15, mastery=30, student_count=50,
                   gain=-8.0, gain_significant=True)
    res = optimize(OptimizerInput(total_hours=20, topics=[t, T(2, 10, 5, 15, 95)]))
    assert res["rows"][0]["gain_direction"] == "decline" and "осваивается" not in res["rows"][0]["explanation"]


def test_ties_are_independent_of_input_order():
    a = run([T(1, 10, 5, 15, 50), T(2, 10, 5, 15, 50)], 20.5)
    b = run([T(2, 10, 5, 15, 50), T(1, 10, 5, 15, 50)], 20.5)
    assert {r["topic_id"]: r["proposed_hours"] for r in a["rows"]} == {r["topic_id"]: r["proposed_hours"] for r in b["rows"]}


@pytest.mark.parametrize("lo,hi,total,ok", [(4.3, 4.4, 10, False), (4.3, 6.2, 10.5, True), (0, 0.4, 5, False)])
def test_rounding_boundaries(lo, hi, total, ok):
    topics = [T(1, 5, lo, hi, 50), T(2, 5, 0, 20, 50)]
    if not ok:
        with pytest.raises(InfeasibleError):
            run(topics, total)
        return
    res = run(topics, total)
    assert hard_ok(res) and res["proposed_total"] == total
    assert by_id(res)[1]["proposed_hours"] >= 4.5  # ceil(4.3) to the 0.5 grid


def test_infeasible_hard_constraints():
    with pytest.raises(InfeasibleError, match="меньше суммы минимумов"):
        run([T(1, 10, 8, 15, 50), T(2, 10, 8, 15, 50)], 10)
    with pytest.raises(InfeasibleError):
        run([T(1, 10, 8, 12, 50), T(2, 10, 8, 12, 50)], 30)
    with pytest.raises(InfeasibleError):
        run([T(1, 10, 12, 8, 50)], 10)
    with pytest.raises(InfeasibleError):
        run([T(1, 20, 5, 15, 50, locked=True), T(2, 10, 5, 15, 50)], 30)
    with pytest.raises(InfeasibleError):
        run([T(1, 10, 5, 15, 50)], 10.3)


def test_no_hypothetical_improvement_claims():
    res = run([T(1, 10, 5, 15, 90), T(2, 10, 5, 15, 40)], 20)
    assert any("не гарантирует" in w for w in res["warnings"])
    assert all("повысит" not in r["explanation"] for r in res["rows"])


def test_check_allocation_and_policies_flag_violations():
    inp = OptimizerInput(total_hours=20, topics=[T(1, 10, 5, 15, 90, locked=True), T(2, 10, 5, 15, 40)])
    checks = {c["name"]: c["ok"] for c in check_allocation(inp, {1: 9, 2: 16.3})}
    assert [k for k, ok in checks.items() if ok] == ["Нет отрицательных значений"]
    pol = {p["policy"]: p for p in check_policies(inp, {1: 10, 2: 6})}
    assert not pol["protect_below_target"]["ok"] and pol["protect_below_target"]["affected_topics"] == ["Тема 2"]


def test_random_problems_property():
    """One property test over many seeded random problems (not N copies of a test).

    Invariants checked independently of the implementation: hard constraints always hold; without relaxation,
    below-target topics never lose hours; with relaxation every hard-feasible problem gets a valid plan and any
    reduced below-target topic is listed under a relaxed policy; the plan does not depend on topic order.
    """
    rng = np.random.default_rng(20261111)
    policy_infeasible = solved = 0
    for _ in range(250):
        n = int(rng.integers(2, 9))
        topics = []
        for i in range(n):
            lo = float(rng.integers(0, 8))
            hi = lo + float(rng.integers(1, 10))
            cur = float(np.round(rng.uniform(lo, hi) * 2) / 2)
            mastery = None if rng.random() < 0.15 else float(np.round(rng.uniform(10, 99), 1))
            direction = rng.choice([None, "increase", "decline", "inconclusive"])
            topics.append(T(i + 1, cur, lo, hi, mastery, prio=int(rng.integers(1, 4)), locked=bool(rng.random() < 0.15),
                            n=int(rng.integers(0, 60)), prereq=[j + 1 for j in range(i) if rng.random() < 0.2],
                            gain=None if direction is None else 1.0, direction=direction))
        locked = sum(t.current_hours for t in topics if t.locked)
        lo_sum = sum(t.min_hours for t in topics if not t.locked) + locked
        hi_sum = sum(t.max_hours for t in topics if not t.locked) + locked
        total = float(np.ceil(rng.uniform(lo_sum, hi_sum) * 2) / 2)
        if not lo_sum <= total <= hi_sum:
            continue
        try:
            res = run(topics, total)
            below = {t.topic_id for t in topics if t.mastery is not None and t.student_count >= 10 and t.mastery < 75}
            assert all(r["delta"] >= 0 for r in res["rows"] if r["topic_id"] in below)
        except InfeasibleError as e:
            assert e.code == "POLICY_INFEASIBLE", e.details
            policy_infeasible += 1
        res = run(topics, total, allow_policy_relaxation=True)
        assert hard_ok(res) and abs(res["proposed_total"] - total) < 1e-9
        relaxed = set(res["relaxed_policies"])
        assert relaxed <= set(POLICY_RELAX_ORDER)
        shuffled = topics[:]
        random.Random(1).shuffle(shuffled)
        res2 = run(shuffled, total, allow_policy_relaxation=True)
        assert by_id(res2) and {k: v["proposed_hours"] for k, v in by_id(res).items()} == \
            {k: v["proposed_hours"] for k, v in by_id(res2).items()}
        solved += 1
    assert solved > 150 and policy_infeasible > 0  # both branches are exercised
