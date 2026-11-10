import numpy as np
import pytest

from app.services.optimizer import InfeasibleError, OptimizerInput, TopicInput, check_allocation, optimize


def T(i, cur, lo, hi, mastery=None, prio=2, n=50, locked=False, prereq=()):
    return TopicInput(topic_id=i, name=f"Тема {i}", current_hours=cur, min_hours=lo, max_hours=hi, priority=prio,
                      mastery=mastery, student_count=n, locked=locked, prerequisites=list(prereq))


def run(topics, total, **kw):
    return optimize(OptimizerInput(total_hours=total, topics=topics, **kw))


def by_id(res):
    return {r["topic_id"]: r for r in res["rows"]}


def test_total_preserved_and_constraints_reported():
    res = run([T(1, 10, 5, 15, 90), T(2, 10, 5, 15, 40), T(3, 10, 5, 15, 70)], 30)
    assert res["proposed_total"] == 30
    assert all(c["ok"] for c in res["constraints"])
    rows = by_id(res)
    assert rows[2]["delta"] > 0  # weakest topic gains
    assert rows[1]["delta"] < 0  # mastered topic gives time
    assert all(r["explanation"] for r in res["rows"])


def test_below_target_topics_are_never_reduced():
    res = run([T(1, 10, 5, 15, 95), T(2, 10, 5, 15, 30, prio=3), T(3, 10, 5, 15, 70, prio=1),
               T(4, 10, 5, 15, 72)], 40)
    rows = by_id(res)
    for tid in (2, 3, 4):
        assert rows[tid]["delta"] >= 0


def test_locked_topics_unchanged():
    res = run([T(1, 12, 5, 15, 95, locked=True), T(2, 10, 5, 15, 40), T(3, 10, 5, 15, 90)], 32)
    assert by_id(res)[1]["proposed_hours"] == 12
    assert res["proposed_total"] == 32


def test_prerequisite_of_weak_topic_not_reduced():
    res = run([T(1, 10, 5, 15, 95), T(2, 10, 5, 15, 40, prereq=[1]), T(3, 10, 5, 15, 95)], 30)
    rows = by_id(res)
    assert rows[1]["delta"] >= 0
    assert "пререквизит" in rows[1]["explanation"]


def test_topics_without_reliable_data_keep_hours():
    res = run([T(1, 10, 5, 15, None), T(2, 10, 5, 15, 40), T(3, 10, 5, 15, 90), T(4, 8, 5, 15, 30, n=2)], 38)
    rows = by_id(res)
    assert rows[1]["delta"] == 0 and rows[4]["delta"] == 0
    assert any("недостаточно данных" in w for w in res["warnings"])


def test_infeasible_total_too_small():
    with pytest.raises(InfeasibleError) as e:
        run([T(1, 10, 8, 15, 50), T(2, 10, 8, 15, 50)], 10)
    assert "меньше суммы минимумов" in str(e.value)


def test_infeasible_total_too_large():
    with pytest.raises(InfeasibleError):
        run([T(1, 10, 8, 12, 50), T(2, 10, 8, 12, 50)], 30)


def test_invalid_bounds_and_lock_outside_bounds():
    with pytest.raises(InfeasibleError):
        run([T(1, 10, 12, 8, 50)], 10)
    with pytest.raises(InfeasibleError):
        run([T(1, 20, 5, 15, 50, locked=True), T(2, 10, 5, 15, 50)], 30)


def test_total_must_be_half_hour_multiple():
    with pytest.raises(InfeasibleError):
        run([T(1, 10, 5, 15, 50)], 10.3)


def test_no_hypothetical_improvement_claims():
    res = run([T(1, 10, 5, 15, 90), T(2, 10, 5, 15, 40)], 20)
    assert any("не гарантирует" in w for w in res["warnings"])
    assert "predicted" not in str(res).lower()


def test_check_allocation_flags_violations():
    inp = OptimizerInput(total_hours=20, topics=[T(1, 10, 5, 15, 90, locked=True), T(2, 10, 5, 15, 40)])
    checks = {c["name"]: c["ok"] for c in check_allocation(inp, {1: 9, 2: 16.3})}
    assert not checks["Сумма часов равна заданной"]
    assert not checks["Часы каждой темы в пределах мин./макс."]
    assert not checks["Зафиксированные темы не изменены"]
    assert not checks["Часы кратны 0.5 ч"]


@pytest.mark.parametrize("seed", range(300))
def test_random_feasible_problems_always_satisfy_constraints(seed):
    rng = np.random.default_rng(seed)
    n = int(rng.integers(2, 10))
    topics = []
    for i in range(n):
        lo = float(rng.integers(0, 8))
        hi = lo + float(rng.integers(0, 10))
        cur = float(np.round(rng.uniform(lo, hi) * 3) / 3)
        locked = bool(rng.random() < 0.2)
        if locked:
            cur = float(np.round(cur * 2) / 2)
        mastery = None if rng.random() < 0.15 else float(np.round(rng.uniform(10, 99), 1))
        topics.append(T(i + 1, cur, lo, hi, mastery, prio=int(rng.integers(1, 4)), locked=locked,
                        n=int(rng.integers(0, 60)), prereq=[j + 1 for j in range(i) if rng.random() < 0.2]))
    locked_sum = sum(t.current_hours for t in topics if t.locked)
    lo_sum = sum(t.min_hours for t in topics if not t.locked) + locked_sum
    hi_sum = sum(t.max_hours for t in topics if not t.locked) + locked_sum
    total = float(np.round(rng.uniform(lo_sum, hi_sum) * 2) / 2)
    if not (lo_sum <= total <= hi_sum):
        pytest.skip("rounding left the feasible interval")
    try:
        res = run(topics, total)
    except InfeasibleError as e:
        # only acceptable when prerequisite protection makes the problem infeasible
        assert "пререквизит" in str(e) + " ".join(e.details), (str(e), e.details)
        return
    assert abs(res["proposed_total"] - total) < 1e-9
    assert all(c["ok"] for c in res["constraints"]), res["constraints"]
