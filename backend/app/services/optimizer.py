"""Transparent curriculum-hours reallocation.

Algorithm (all hours handled in integer units of 0.5 h, so the total is preserved exactly):
1. Validate inputs: bounds, locked topics, total hours (multiple of 0.5) — infeasible inputs raise
   InfeasibleError with an explanation.
2. Need of each topic:  need_i = priority_i × gap_i, gap_i = max(0, target − mastery_i) / 100.
   Prerequisites of below-target topics get need × 1.25 and may not be reduced.
   Topics without outcome data keep their current hours (as far as constraints allow).
3. Desired hours. Below-target topics may only grow: d_i = current_i × (1 + max_change × ñ_i), ñ = need
   scaled to [0, 1]. At/above-target topics may only shrink, by their surplus over the target:
   d_i = current_i × (1 − max_change × (mastery_i − target)/(100 − target)). Topics without reliable data
   keep their hours. No topic changes by more than ±max_change (the band is relaxed only if the total
   cannot otherwise be reached, with a warning).
4. Projection: find λ such that Σ clip(d_i + λ, lo_i, hi_i) = free hours (bisection), then round with
   the largest-remainder method inside the bounds. Lower/upper bounds combine min/max hours, the
   max-change band (relaxed only when needed to reach the total) and locks.
The result contains no predicted score improvements: more hours are not guaranteed to raise mastery.
"""
from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, Field

UNIT = 0.5
PREREQ_BOOST = 1.25


class InfeasibleError(ValueError):
    def __init__(self, message: str, details: list[str] | None = None):
        super().__init__(message)
        self.details = details or []


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
    gain_significant: bool | None = None
    locked: bool = False
    prerequisites: list[int] = Field(default_factory=list)


class OptimizerInput(BaseModel):
    total_hours: float = Field(gt=0)
    target_mastery: float = Field(75, ge=0, le=100)
    max_change_pct: float = Field(30, ge=0, le=100)
    min_students: int = Field(10, ge=1)
    topics: list[TopicInput] = Field(min_length=1)


def _units(x: float) -> float:
    return x / UNIT


def validate_input(inp: OptimizerInput) -> None:
    problems: list[str] = []
    ids = [t.topic_id for t in inp.topics]
    if len(set(ids)) != len(ids):
        problems.append("Темы повторяются.")
    if abs(_units(inp.total_hours) - round(_units(inp.total_hours))) > 1e-9:
        problems.append(f"Общее число часов должно быть кратно {UNIT} ч.")
    for t in inp.topics:
        if t.min_hours > t.max_hours:
            problems.append(f"«{t.name}»: минимум ({t.min_hours} ч) больше максимума ({t.max_hours} ч).")
        if t.locked and not (t.min_hours <= t.current_hours <= t.max_hours):
            problems.append(f"«{t.name}» зафиксирована на {t.current_hours} ч вне допустимого диапазона "
                            f"{t.min_hours}–{t.max_hours} ч.")
        if t.locked and abs(_units(t.current_hours) - round(_units(t.current_hours))) > 1e-9:
            problems.append(f"«{t.name}»: зафиксированные часы должны быть кратны {UNIT} ч.")
    if problems:
        raise InfeasibleError("Ограничения заданы некорректно.", problems)
    locked = sum(t.current_hours for t in inp.topics if t.locked)
    free = [t for t in inp.topics if not t.locked]
    lo = sum(math.ceil(_units(t.min_hours) - 1e-9) for t in free) * UNIT
    hi = sum(math.floor(_units(t.max_hours) + 1e-9) for t in free) * UNIT
    if inp.total_hours < locked + lo - 1e-9:
        raise InfeasibleError("Невозможно выполнить ограничения: общих часов меньше суммы минимумов.", [
            f"Всего часов: {inp.total_hours}; зафиксировано: {locked}; сумма минимумов остальных тем: {lo}. "
            f"Нужно не менее {locked + lo} ч."])
    if inp.total_hours > locked + hi + 1e-9:
        raise InfeasibleError("Невозможно выполнить ограничения: общих часов больше суммы максимумов.", [
            f"Всего часов: {inp.total_hours}; зафиксировано: {locked}; сумма максимумов остальных тем: {hi}. "
            f"Допустимо не более {locked + hi} ч."])


def _project(desired: list[float], lo: list[int], hi: list[int], total: int) -> list[int]:
    """Integer vector within [lo, hi] summing to total, closest to `desired` (shift + largest remainder)."""
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
    order = sorted(range(len(cont)), key=lambda i: -(cont[i] - math.floor(cont[i] + 1e-9)))
    i = 0
    guard = 0
    while rem != 0 and guard < 100_000:
        k = order[i % len(order)]
        if rem > 0 and base[k] < hi[k]:
            base[k] += 1
            rem -= 1
        elif rem < 0 and base[k] > lo[k]:
            base[k] -= 1
            rem += 1
        i += 1
        guard += 1
    if rem != 0:
        raise InfeasibleError("Не удалось распределить часы в заданных границах.")
    return base


def optimize(inp: OptimizerInput) -> dict[str, Any]:
    validate_input(inp)
    topics = inp.topics
    by_id = {t.topic_id: t for t in topics}
    target = inp.target_mastery
    reliable = {t.topic_id: (t.mastery is not None and t.student_count >= inp.min_students) for t in topics}

    below_target = {t.topic_id for t in topics if reliable[t.topic_id] and t.mastery < target}
    protected_prereq: dict[int, list[str]] = {}
    for t in topics:
        if t.topic_id in below_target:
            for p in t.prerequisites:
                if p in by_id:
                    protected_prereq.setdefault(p, []).append(t.name)

    need: dict[int, float | None] = {}
    for t in topics:
        if not reliable[t.topic_id]:
            need[t.topic_id] = None
            continue
        gap = max(0.0, target - t.mastery) / 100
        n = t.priority * gap
        if t.topic_id in protected_prereq and t.topic_id in below_target:
            n *= PREREQ_BOOST
        need[t.topic_id] = n

    known = [v for v in need.values() if v is not None]
    max_need = max(known) if known else 0
    scaled = {k: (v / max_need if (v is not None and max_need > 0) else (0.0 if v is not None else None))
              for k, v in need.items()}
    rate = inp.max_change_pct / 100

    free = [t for t in topics if not t.locked]
    locked_units = sum(round(_units(t.current_hours)) for t in topics if t.locked)
    total_units = round(_units(inp.total_hours))
    free_total = total_units - locked_units

    desired, lo_hard, hi_hard, lo_band, hi_band = [], [], [], [], []
    for t in free:
        cur = _units(t.current_hours)
        sc = scaled[t.topic_id]
        lh = math.ceil(_units(t.min_hours) - 1e-9)
        hh = math.floor(_units(t.max_hours) + 1e-9)
        if t.topic_id in protected_prereq:
            lh = max(lh, min(hh, math.floor(cur + 1e-9)))  # do not reduce prerequisites of weak topics
        cur_lo, cur_hi = math.floor(cur + 1e-9), math.ceil(cur - 1e-9)
        if sc is None:  # no reliable data: keep current hours
            d, lb, hb = cur, max(lh, cur_lo), min(hh, cur_hi)
        elif t.topic_id in below_target:  # may only grow, proportionally to need
            d = cur * (1 + rate * sc)
            lb, hb = max(lh, cur_lo), min(hh, math.ceil(cur * (1 + rate) - 1e-9))
        else:  # at/above target: may only shrink, proportionally to surplus over target
            surplus = min(1.0, max(0.0, (t.mastery - target) / max(1e-9, 100 - target)))
            d = cur * (1 - rate * surplus)
            lb, hb = max(lh, math.floor(cur * (1 - rate) + 1e-9)), min(hh, cur_hi)
        if lb > hb:
            lb, hb = lh, hh
        desired.append(d)
        lo_hard.append(lh)
        hi_hard.append(hh)
        lo_band.append(lb)
        hi_band.append(hb)

    warnings: list[str] = []
    if sum(lo_hard) > free_total or sum(hi_hard) < free_total:
        raise InfeasibleError("Невозможно выполнить ограничения с учётом защиты пререквизитов.", [
            "Пререквизиты трудных тем не уменьшаются; ослабьте минимумы других тем или увеличьте общее число часов."])
    if sum(lo_band) <= free_total <= sum(hi_band):
        units = _project(desired, lo_band, hi_band, free_total)
        band_relaxed = False
    else:
        units = _project(desired, lo_hard, hi_hard, free_total)
        band_relaxed = True
        warnings.append(f"Чтобы выйти на заданную сумму часов, ограничение «не более ±{inp.max_change_pct:g}% за шаг» "
                        "пришлось ослабить для некоторых тем.")

    proposed = {t.topic_id: u * UNIT for t, u in zip(free, units)}
    for t in topics:
        if t.locked:
            proposed[t.topic_id] = t.current_hours

    rows = []
    for t in topics:
        new = proposed[t.topic_id]
        delta = round(new - t.current_hours, 2)
        rows.append({
            "topic_id": t.topic_id, "name": t.name, "current_hours": t.current_hours, "proposed_hours": new,
            "delta": delta, "min_hours": t.min_hours, "max_hours": t.max_hours, "priority": t.priority,
            "mastery": t.mastery, "student_count": t.student_count, "locked": t.locked,
            "need_score": None if need[t.topic_id] is None else round(need[t.topic_id], 4),
            "gain": t.gain, "gain_significant": t.gain_significant,
            "explanation": _explain(t, new, delta, target, reliable[t.topic_id], protected_prereq.get(t.topic_id),
                                    inp.min_students),
        })

    checks = check_allocation(inp, proposed)
    stalled = [t.name for t in topics if t.topic_id in below_target and t.gain_significant is False]
    if stalled:
        warnings.append("Для тем " + ", ".join(f"«{n}»" for n in stalled) + " не зафиксирован значимый прирост от входной "
                        "к итоговой диагностике: дополнительные часы без пересмотра методики и материалов могут не дать "
                        "эффекта.")
    for t in topics:
        if not reliable[t.topic_id]:
            warnings.append(f"«{t.name}»: недостаточно данных об освоении — часы не перераспределялись по потребности.")
    warnings.append("Рекомендация основана на наблюдаемых результатах. Увеличение часов не гарантирует рост "
                    "освоения; эффект следует проверить на следующих оцениваниях.")
    return {
        "total_hours": inp.total_hours,
        "current_total": round(sum(t.current_hours for t in topics), 2),
        "proposed_total": round(sum(proposed.values()), 2),
        "rows": rows, "constraints": checks, "warnings": warnings, "band_relaxed": band_relaxed,
        "method": "need = priority × max(0, target − mastery); перераспределение в пределах ±max_change, "
                  "мин./макс. часов, фиксаций и защиты пререквизитов; округление до 0,5 ч.",
    }


def _explain(t: TopicInput, new: float, delta: float, target: float, reliable: bool, prereq_for: list[str] | None,
             min_students: int) -> str:
    parts: list[str] = []
    if t.locked:
        return f"Часы зафиксированы методистом ({t.current_hours} ч)."
    if not reliable:
        if t.mastery is None:
            parts.append("Нет данных об освоении темы")
        else:
            parts.append(f"Освоение {t.mastery}% рассчитано по {t.student_count} ученикам (< {min_students}) — "
                         "данных недостаточно")
        parts.append("часы сохранены" if delta == 0 else f"часы изменены на {delta:+g} ч только для соблюдения общей суммы")
        return "; ".join(parts) + "."
    if t.mastery < target:
        parts.append(f"Освоение {t.mastery}% ниже цели {target:g}% (разрыв {target - t.mastery:.1f} п.п.), "
                     f"приоритет {t.priority}")
    else:
        parts.append(f"Освоение {t.mastery}% не ниже цели {target:g}%")
    if t.mastery < target and t.gain is not None:
        if t.gain_significant:
            parts.append(f"прирост pre→post {t.gain:+.1f} п.п. значим — тема осваивается, но медленно")
        else:
            parts.append(f"прирост pre→post {t.gain:+.1f} п.п. не значим — нужен пересмотр методики, одних часов "
                         "может быть недостаточно")
    if prereq_for:
        parts.append("тема — пререквизит для: " + ", ".join(prereq_for) + " (часы не уменьшаются)")
    if delta > 0:
        parts.append(f"предлагается +{delta:g} ч")
    elif delta < 0:
        parts.append(f"предлагается {delta:g} ч, чтобы высвободить время для тем с большим разрывом")
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
    """Verify an allocation (proposed or user-edited) against every constraint."""
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
    bad_step = [t.name for t in inp.topics if abs(_units(alloc.get(t.topic_id, 0)) - round(_units(alloc.get(t.topic_id, 0)))) > 1e-9]
    checks.append({"name": f"Часы кратны {UNIT} ч", "ok": not bad_step,
                   "detail": "Нарушено: " + ", ".join(bad_step) if bad_step else "Да"})
    neg = [t.name for t in inp.topics if alloc.get(t.topic_id, 0) < 0]
    checks.append({"name": "Нет отрицательных значений", "ok": not neg, "detail": ", ".join(neg) or "Да"})
    return checks
