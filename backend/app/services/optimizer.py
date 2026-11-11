"""Transparent curriculum-hours reallocation for one grade-level plan (all classes of a grade follow it).

Hours are handled in integer units of 0.5 h (a half lesson period is a legitimate planning unit), so totals
are exact and rounding can never break a bound.

HARD constraints — never relaxed; violating inputs raise InfeasibleError:
  total equals the requested total; min_hours <= hours <= max_hours; locked topics keep their hours;
  multiples of 0.5 h; no negative hours.

POLICIES — on by default; if they make the problem infeasible the result is an InfeasibleError
(code POLICY_INFEASIBLE) unless the caller sets allow_policy_relaxation=True, in which case policies are
relaxed one at a time in POLICY_RELAX_ORDER and every relaxed policy and affected topic is reported:
  max_change            each topic changes by at most ±max_change_pct of its current hours;
  hold_without_evidence topics without reliable mastery data, or with a statistically significant decline,
                        keep their hours (more hours are not assumed to fix a decline);
  protect_prerequisites prerequisites of below-target topics are not reduced;
  protect_below_target  below-target topics are not reduced.

Objective: need_i = priority_i * max(0, target - mastery_i)/100 (x1.25 for prerequisites of weak topics).
Desired hours: below-target topics grow by max_change * need_i/max_need; at/above-target topics shrink by
max_change * surplus_i; the uniform shift λ that hits the total is found by bisection and the result is rounded
by largest remainder with a stable tie-break (larger need first, then lower topic_id) — independent of input
order. Nothing here predicts score improvements: more hours are not evidence of better learning.
"""
from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, Field

UNIT = 0.5
PREREQ_BOOST = 1.25
POLICY_RELAX_ORDER = ["max_change", "hold_without_evidence", "protect_prerequisites", "protect_below_target"]
POLICY_LABELS = {
    "max_change": "Изменение темы за шаг не больше заданного процента",
    "hold_without_evidence": "Темы без надёжных данных или со значимым снижением сохраняют часы",
    "protect_prerequisites": "Пререквизиты тем ниже цели не сокращаются",
    "protect_below_target": "Темы ниже целевого освоения не сокращаются",
}
GainDirection = Literal["increase", "decline", "inconclusive", "insufficient"]


class InfeasibleError(ValueError):
    def __init__(self, message: str, details: list[str] | None = None, code: str = "INFEASIBLE"):
        super().__init__(message)
        self.details = details or []
        self.code = code


class TopicInput(BaseModel):
    topic_id: int
    name: str
    current_hours: float = Field(ge=0)
    min_hours: float = Field(ge=0)
    max_hours: float = Field(ge=0)
    priority: int = Field(2, ge=1, le=3)
    mastery: float | None = Field(None, ge=0, le=100)
    student_count: int = 0
    gain: float | None = None  # mean paired pre→post gain, p.p. (None = no baseline)
    gain_direction: GainDirection | None = None
    gain_significant: bool | None = None  # kept for API compatibility; derived from gain_direction when given
    locked: bool = False
    prerequisites: list[int] = Field(default_factory=list)


class OptimizerInput(BaseModel):
    total_hours: float = Field(gt=0)
    target_mastery: float = Field(75, ge=0, le=100)
    max_change_pct: float = Field(30, ge=0, le=100)
    min_students: int = Field(10, ge=1)
    allow_policy_relaxation: bool = False
    topics: list[TopicInput] = Field(min_length=1)


def _units(x: float) -> float:
    return x / UNIT


def _is_step(x: float) -> bool:
    return abs(_units(x) - round(_units(x))) <= 1e-9


def direction_of(t: TopicInput) -> str | None:
    if t.gain_direction:
        return t.gain_direction
    if t.gain is None or t.gain_significant is None:
        return None
    if not t.gain_significant:
        return "inconclusive"
    return "increase" if t.gain > 0 else "decline"


def validate_input(inp: OptimizerInput) -> None:
    """Hard-constraint feasibility only."""
    problems: list[str] = []
    ids = [t.topic_id for t in inp.topics]
    if len(set(ids)) != len(ids):
        problems.append("Темы повторяются.")
    if not _is_step(inp.total_hours):
        problems.append(f"Общее число часов должно быть кратно {UNIT} ч.")
    for t in inp.topics:
        if t.min_hours > t.max_hours:
            problems.append(f"«{t.name}»: минимум ({t.min_hours:g} ч) больше максимума ({t.max_hours:g} ч).")
        if math.ceil(_units(t.min_hours) - 1e-9) > math.floor(_units(t.max_hours) + 1e-9):
            problems.append(f"«{t.name}»: между минимумом и максимумом нет значения, кратного {UNIT} ч.")
        if t.locked and not (t.min_hours <= t.current_hours <= t.max_hours):
            problems.append(f"«{t.name}» зафиксирована на {t.current_hours:g} ч вне допустимого диапазона "
                            f"{t.min_hours:g}–{t.max_hours:g} ч.")
        if t.locked and not _is_step(t.current_hours):
            problems.append(f"«{t.name}»: зафиксированные часы должны быть кратны {UNIT} ч.")
    if problems:
        raise InfeasibleError("Ограничения заданы некорректно.", problems)
    locked = sum(t.current_hours for t in inp.topics if t.locked)
    free = [t for t in inp.topics if not t.locked]
    lo = sum(math.ceil(_units(t.min_hours) - 1e-9) for t in free) * UNIT
    hi = sum(math.floor(_units(t.max_hours) + 1e-9) for t in free) * UNIT
    if inp.total_hours < locked + lo - 1e-9:
        raise InfeasibleError("Невозможно выполнить ограничения: общих часов меньше суммы минимумов.", [
            f"Всего часов: {inp.total_hours:g}; зафиксировано: {locked:g}; сумма минимумов остальных тем: {lo:g}. "
            f"Нужно не менее {locked + lo:g} ч."])
    if inp.total_hours > locked + hi + 1e-9:
        raise InfeasibleError("Невозможно выполнить ограничения: общих часов больше суммы максимумов.", [
            f"Всего часов: {inp.total_hours:g}; зафиксировано: {locked:g}; сумма максимумов остальных тем: {hi:g}. "
            f"Допустимо не более {locked + hi:g} ч."])


def _project(desired: list[float], lo: list[int], hi: list[int], total: int, tie_key: list[tuple]) -> list[int]:
    """Integer vector within [lo, hi] summing to total, closest to `desired` (uniform shift + largest remainder).

    tie_key gives a stable, input-order-independent priority for equal remainders (smaller key wins).
    """
    def s(lam: float) -> float:
        return sum(min(max(d + lam, l), h) for d, l, h in zip(desired, lo, hi))

    a, b = -1e6, 1e6
    for _ in range(200):
        mid = (a + b) / 2
        if s(mid) < total:
            a = mid
        else:
            b = mid
    cont = [min(max(d + b, l), h) for d, l, h in zip(desired, lo, hi)]
    base = [max(l, min(h, math.floor(c + 1e-9))) for c, l, h in zip(cont, lo, hi)]
    rem = total - sum(base)
    frac = [round(c - math.floor(c + 1e-9), 9) for c in cont]
    up = sorted(range(len(cont)), key=lambda i: (-frac[i], tie_key[i]))
    down = sorted(range(len(cont)), key=lambda i: (frac[i], tuple(reversed(tie_key[i]))))
    guard = 0
    while rem != 0 and guard < 100_000:
        moved = False
        for k in (up if rem > 0 else down):
            if rem > 0 and base[k] < hi[k]:
                base[k] += 1
                rem -= 1
                moved = True
                break
            if rem < 0 and base[k] > lo[k]:
                base[k] -= 1
                rem += 1
                moved = True
                break
        if not moved:
            break
        guard += 1
    if rem != 0:
        raise InfeasibleError("Не удалось распределить часы в заданных границах.")
    return base


def optimize(inp: OptimizerInput) -> dict[str, Any]:
    validate_input(inp)
    topics = inp.topics
    by_id = {t.topic_id: t for t in topics}
    target = inp.target_mastery
    rate = inp.max_change_pct / 100
    reliable = {t.topic_id: (t.mastery is not None and t.student_count >= inp.min_students) for t in topics}
    direction = {t.topic_id: direction_of(t) for t in topics}
    below = {t.topic_id for t in topics if reliable[t.topic_id] and t.mastery < target}
    hold = {t.topic_id for t in topics if not reliable[t.topic_id] or direction[t.topic_id] == "decline"}
    prereq_for: dict[int, list[str]] = {}
    for t in topics:
        if t.topic_id in below:
            for p in t.prerequisites:
                if p in by_id:
                    prereq_for.setdefault(p, []).append(t.name)

    need: dict[int, float] = {}
    for t in topics:
        if t.topic_id in hold:
            need[t.topic_id] = 0.0
            continue
        n = t.priority * max(0.0, target - t.mastery) / 100
        if t.topic_id in prereq_for and t.topic_id in below:
            n *= PREREQ_BOOST
        need[t.topic_id] = n
    max_need = max(need.values()) or 1.0

    free = [t for t in topics if not t.locked]
    total_units = round(_units(inp.total_hours))
    free_total = total_units - sum(round(_units(t.current_hours)) for t in topics if t.locked)
    cur_total = sum(t.current_hours for t in topics)

    desired, hard_lo, hard_hi, tie = [], [], [], []
    for t in free:
        cur = _units(t.current_hours)
        if t.topic_id in hold:
            d = cur
        elif t.topic_id in below:
            d = cur * (1 + rate * need[t.topic_id] / max_need)
        else:
            surplus = min(1.0, max(0.0, (t.mastery - target) / max(1e-9, 100 - target)))
            d = cur * (1 - rate * surplus)
        desired.append(d)
        hard_lo.append(math.ceil(_units(t.min_hours) - 1e-9))
        hard_hi.append(math.floor(_units(t.max_hours) + 1e-9))
        tie.append((-round(need[t.topic_id], 9), t.topic_id))

    def bounds(active: set[str]) -> tuple[list[int], list[int]]:
        lo, hi = list(hard_lo), list(hard_hi)
        for i, t in enumerate(free):
            cur = _units(t.current_hours)
            cur_lo, cur_hi = math.floor(cur + 1e-9), math.ceil(cur - 1e-9)
            if "max_change" in active:
                lo[i] = max(lo[i], math.floor(cur * (1 - rate) + 1e-9))
                hi[i] = min(hi[i], math.ceil(cur * (1 + rate) - 1e-9))
            if "hold_without_evidence" in active and t.topic_id in hold:
                lo[i], hi[i] = max(lo[i], cur_lo), min(hi[i], cur_hi)
            if "protect_prerequisites" in active and t.topic_id in prereq_for:
                lo[i] = max(lo[i], min(hard_hi[i], cur_lo))
            if "protect_below_target" in active and t.topic_id in below:
                lo[i] = max(lo[i], min(hard_hi[i], cur_lo))
            lo[i] = max(lo[i], hard_lo[i])
            hi[i] = min(hi[i], hard_hi[i])
        return lo, hi

    def feasible(lo: list[int], hi: list[int]) -> bool:
        return all(l <= h for l, h in zip(lo, hi)) and sum(lo) <= free_total <= sum(hi)

    active = set(POLICY_RELAX_ORDER)
    relaxed: list[str] = []
    lo, hi = bounds(active)
    if not feasible(lo, hi):
        if not inp.allow_policy_relaxation:
            need_units = sum(lo) * UNIT
            room_units = sum(hi) * UNIT
            detail = (f"Свободных часов (без зафиксированных тем): {free_total * UNIT:g}. По правилам темы можно "
                      f"сократить не ниже {need_units:g} ч и увеличить не выше {room_units:g} ч.")
            raise InfeasibleError(
                "Заданный объём часов нельзя распределить без нарушения правил оптимизатора.",
                [detail] + [f"Правило: {POLICY_LABELS[p]}." for p in POLICY_RELAX_ORDER] +
                ["Измените общий объём часов или разрешите явное ослабление правил (allow_policy_relaxation)."],
                code="POLICY_INFEASIBLE")
        for policy in POLICY_RELAX_ORDER:
            active.discard(policy)
            relaxed.append(policy)
            lo, hi = bounds(active)
            if feasible(lo, hi):
                break
        # minimal relaxation: re-enable every relaxed policy that is not actually needed
        for policy in list(relaxed):
            trial = active | {policy}
            t_lo, t_hi = bounds(trial)
            if feasible(t_lo, t_hi):
                active, lo, hi = trial, t_lo, t_hi
                relaxed.remove(policy)
    units = _project(desired, lo, hi, free_total, tie)

    proposed = {t.topic_id: u * UNIT for t, u in zip(free, units)}
    for t in topics:
        if t.locked:
            proposed[t.topic_id] = t.current_hours

    affected = {p: [] for p in relaxed}
    for t in free:
        new, cur = proposed[t.topic_id], t.current_hours
        if "max_change" in affected and cur > 0 and abs(new - cur) > cur * rate + UNIT / 2 + 1e-9:
            affected["max_change"].append(t.name)
        if "hold_without_evidence" in affected and t.topic_id in hold and new != cur:
            affected["hold_without_evidence"].append(t.name)
        if "protect_prerequisites" in affected and t.topic_id in prereq_for and new < cur - 1e-9:
            affected["protect_prerequisites"].append(t.name)
        if "protect_below_target" in affected and t.topic_id in below and new < cur - 1e-9:
            affected["protect_below_target"].append(t.name)

    total_change = inp.total_hours - cur_total
    rows = []
    for t in topics:
        new = proposed[t.topic_id]
        delta = round(new - t.current_hours, 2)
        rows.append({
            "topic_id": t.topic_id, "name": t.name, "current_hours": t.current_hours, "proposed_hours": new,
            "delta": delta, "min_hours": t.min_hours, "max_hours": t.max_hours, "priority": t.priority,
            "mastery": t.mastery, "student_count": t.student_count, "locked": t.locked,
            "need_score": None if t.topic_id in hold else round(need[t.topic_id], 4),
            "gain": t.gain, "gain_direction": direction[t.topic_id],
            "gain_significant": direction[t.topic_id] in ("increase", "decline") if direction[t.topic_id] else None,
            "explanation": _explain(t, new, delta, target, reliable[t.topic_id], direction[t.topic_id],
                                    prereq_for.get(t.topic_id), inp, total_change,
                                    {p for p, names in affected.items() if t.name in names}),
        })

    warnings: list[str] = []
    if total_change < -1e-9:
        warnings.append(f"Общий объём часов уменьшен с {cur_total:g} до {inp.total_hours:g} ч: сокращения часть "
                        "тем вызваны уменьшением общего объёма, а не только перераспределением.")
    for p in relaxed:
        names = affected[p]
        warnings.append(f"Ослаблено по запросу правило «{POLICY_LABELS[p]}»"
                        + (f": затронуты темы {', '.join(names)}." if names else " (фактически не нарушено)."))
    declining = [t.name for t in topics if direction[t.topic_id] == "decline"]
    if declining:
        warnings.append("Значимое снижение результатов: " + ", ".join(f"«{n}»" for n in declining) + ". Часы этих тем "
                        "не меняются автоматически — сначала нужен анализ причин.")
    stalled = [t.name for t in topics if t.topic_id in below and direction[t.topic_id] == "inconclusive"]
    if stalled:
        warnings.append("Для тем " + ", ".join(f"«{n}»" for n in stalled) + " изменение от входной к итоговой "
                        "диагностике не установлено: дополнительные часы без пересмотра методики могут не дать эффекта.")
    for t in topics:
        if not reliable[t.topic_id]:
            warnings.append(f"«{t.name}»: недостаточно данных об освоении — часы не перераспределялись по потребности.")
    warnings.append("Рекомендация основана на наблюдаемых результатах. Увеличение часов не гарантирует рост "
                    "освоения; эффект следует проверить на следующих оцениваниях.")
    return {
        "total_hours": inp.total_hours,
        "current_total": round(cur_total, 2),
        "proposed_total": round(sum(proposed.values()), 2),
        "rows": rows, "constraints": check_allocation(inp, proposed),
        "policy_checks": [{"policy": p, "name": POLICY_LABELS[p],
                           "status": "relaxed" if p in relaxed else "applied",
                           "affected_topics": affected.get(p, [])} for p in POLICY_RELAX_ORDER],
        "relaxed_policies": relaxed, "band_relaxed": "max_change" in relaxed,
        "warnings": warnings, "plan_scope": "grade",
        "method": "need = priority × max(0, target − mastery); жёсткие ограничения (сумма, мин./макс., фиксации, шаг "
                  "0,5 ч) соблюдаются всегда; правила оптимизатора ослабляются только по явному запросу; "
                  "равные случаи — по потребности, затем по номеру темы.",
    }


def _explain(t: TopicInput, new: float, delta: float, target: float, reliable: bool, direction: str | None,
             prereq_for: list[str] | None, inp: OptimizerInput, total_change: float, relaxed_here: set[str]) -> str:
    if t.locked:
        return f"Часы зафиксированы методистом ({t.current_hours:g} ч)."
    parts: list[str] = []
    if not reliable:
        parts.append("Нет данных об освоении темы" if t.mastery is None else
                     f"Освоение {t.mastery}% рассчитано по {t.student_count} ученикам (< {inp.min_students}) — "
                     "данных недостаточно")
    elif t.mastery < target:
        parts.append(f"Освоение {t.mastery}% ниже цели {target:g}% (разрыв {target - t.mastery:.1f} п.п.), "
                     f"приоритет {t.priority}")
    else:
        parts.append(f"Освоение {t.mastery}% не ниже цели {target:g}%")
    if t.gain is not None and direction:
        gain_text = (f"{t.gain:+.3g}" if t.gain != 0 and round(t.gain, 1) == 0 else f"{t.gain:+.1f}")
        parts.append({
            "increase": f"прирост от входной диагностики {gain_text} п.п. статистически значим (связь с числом "
                        "часов не установлена)",
            "decline": f"результат статистически значимо СНИЗИЛСЯ ({gain_text} п.п.) — часы не меняются "
                       "автоматически, нужен анализ причин",
            "inconclusive": f"изменение от входной диагностики не установлено ({gain_text} п.п., ДИ включает ноль); "
                            "одних часов может быть недостаточно",
            "insufficient": "данных о динамике недостаточно",
        }[direction])
    if prereq_for:
        parts.append("тема — пререквизит для: " + ", ".join(prereq_for) +
                     (" (правило защиты ослаблено)" if "protect_prerequisites" in relaxed_here else
                      " (часы не уменьшаются)"))
    if delta > 0:
        parts.append(f"предлагается +{delta:g} ч" + (" (общий объём часов увеличен)" if total_change > 0 else ""))
    elif delta < 0:
        if "protect_below_target" in relaxed_here or "hold_without_evidence" in relaxed_here:
            parts.append(f"предлагается {delta:g} ч только из-за уменьшения общего объёма; правило защиты темы "
                         "ослаблено по явному запросу")
        elif total_change < 0:
            parts.append(f"предлагается {delta:g} ч в рамках уменьшения общего объёма часов "
                         f"({total_change:+g} ч)")
        else:
            parts.append(f"предлагается {delta:g} ч, чтобы высвободить время для тем с большим разрывом")
    elif not reliable or direction == "decline":
        parts.append("часы сохранены")
    elif t.mastery < target:
        parts.append("часы сохранены: высвобожденного резерва не хватило с учётом приоритетов других тем")
    else:
        parts.append("изменение не требуется")
    if new >= t.max_hours and delta > 0:
        parts.append("достигнут максимум часов")
    if new <= t.min_hours and delta < 0:
        parts.append("достигнут минимум часов")
    return "; ".join(parts) + "."


def check_allocation(inp: OptimizerInput, alloc: dict[int, float]) -> list[dict[str, Any]]:
    """Verify an allocation (proposed or user-edited) against every HARD constraint."""
    checks = []
    total = round(sum(alloc.get(t.topic_id, 0) for t in inp.topics), 4)
    checks.append({"name": "Сумма часов равна заданной", "ok": abs(total - inp.total_hours) < 1e-6,
                   "detail": f"{total:g} из {inp.total_hours:g} ч"})
    bad_bounds = [t.name for t in inp.topics if not (t.min_hours - 1e-9 <= alloc.get(t.topic_id, 0) <= t.max_hours + 1e-9)]
    checks.append({"name": "Часы каждой темы в пределах мин./макс.", "ok": not bad_bounds,
                   "detail": "Нарушено: " + ", ".join(bad_bounds) if bad_bounds else "Все темы в пределах"})
    bad_lock = [t.name for t in inp.topics if t.locked and abs(alloc.get(t.topic_id, 0) - t.current_hours) > 1e-9]
    checks.append({"name": "Зафиксированные темы не изменены", "ok": not bad_lock,
                   "detail": "Изменены: " + ", ".join(bad_lock) if bad_lock else
                   f"Зафиксировано тем: {sum(1 for t in inp.topics if t.locked)}"})
    bad_step = [t.name for t in inp.topics if not _is_step(alloc.get(t.topic_id, 0))]
    checks.append({"name": f"Часы кратны {UNIT} ч", "ok": not bad_step,
                   "detail": "Нарушено: " + ", ".join(bad_step) if bad_step else "Да"})
    neg = [t.name for t in inp.topics if alloc.get(t.topic_id, 0) < 0]
    checks.append({"name": "Нет отрицательных значений", "ok": not neg, "detail": ", ".join(neg) or "Да"})
    return checks


def check_policies(inp: OptimizerInput, alloc: dict[int, float]) -> list[dict[str, Any]]:
    """Report which optimizer policies a (manual) allocation respects. Policies are advisory for manual plans."""
    target, rate = inp.target_mastery, inp.max_change_pct / 100
    reliable = {t.topic_id: (t.mastery is not None and t.student_count >= inp.min_students) for t in inp.topics}
    below = {t.topic_id for t in inp.topics if reliable[t.topic_id] and t.mastery < target}
    out = []
    viol = [t.name for t in inp.topics if t.topic_id in below and alloc.get(t.topic_id, 0) < t.current_hours - 1e-9]
    out.append({"policy": "protect_below_target", "name": POLICY_LABELS["protect_below_target"], "ok": not viol,
                "affected_topics": viol})
    viol = [t.name for t in inp.topics if not t.locked and t.current_hours > 0
            and abs(alloc.get(t.topic_id, 0) - t.current_hours) > t.current_hours * rate + UNIT / 2 + 1e-9]
    out.append({"policy": "max_change", "name": POLICY_LABELS["max_change"], "ok": not viol, "affected_topics": viol})
    return out
