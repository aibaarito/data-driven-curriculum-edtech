"""Multi-scenario planning on top of ``optimizer.optimize`` (the only allocation engine).

Every scenario is a real optimizer run with explicit, reported parameters; nothing is hard-coded:

    conservative  max_change = ½·base;  topics whose evidence is not "supported" join the hold policy
    balanced      base settings (identical to POST /optimizer/run for the same inputs)
    gap_focused   max_change = min(100, 1.5·base);  need × (1 + 0.25·min(weak_downstream, 4)/4)

Hard constraints are enforced by ``optimize`` and verified again with ``check_allocation`` for every scenario.
A policy infeasibility in one scenario is returned as that scenario's structured error; others still run.
"""
from __future__ import annotations

from typing import Any

from app.services.optimizer import InfeasibleError, OptimizerInput, check_allocation, optimize

SCENARIO_KEYS = ("conservative", "balanced", "gap_focused")
SCENARIO_META = {
    "conservative": {"label": "Консервативный",
                     "goal": "Минимум изменений: меньший шаг изменения и сохранение часов там, где доказательства "
                             "не достаточны (категория не «supported»)."},
    "balanced": {"label": "Сбалансированный",
                 "goal": "Базовые правила оптимизатора: баланс между разрывом освоения и стабильностью плана."},
    "gap_focused": {"label": "Фокус на пробелах",
                    "goal": "Больше часов темам с наибольшим разрывом и слабыми зависимыми темами — в пределах "
                            "явного, расширенного лимита изменения."},
}
GAP_BAND_FACTOR = 1.5
CONSERVATIVE_BAND_FACTOR = 0.5
WEAK_DOWNSTREAM_CAP = 4
WEAK_DOWNSTREAM_WEIGHT = 0.25


def scenario_inputs(base: OptimizerInput, evidence: dict[int, str], weak_downstream: dict[int, int]
                    ) -> dict[str, tuple[OptimizerInput, dict[str, Any]]]:
    """Derive the three optimizer inputs and the parameters each one used (for transparency)."""
    out: dict[str, tuple[OptimizerInput, dict[str, Any]]] = {}

    cons_topics, held = [], []
    for t in base.topics:
        cat = evidence.get(t.topic_id, "insufficient")
        if cat != "supported" and not t.locked and t.hold_reason is None:
            cons_topics.append(t.model_copy(update={"hold_reason": f"сценарий сохраняет часы — данные «{cat}»"}))
            held.append(t.name)
        else:
            cons_topics.append(t)
    cons_band = round(base.max_change_pct * CONSERVATIVE_BAND_FACTOR, 2)
    out["conservative"] = (base.model_copy(update={"max_change_pct": cons_band, "topics": cons_topics}),
                           {"max_change_pct": cons_band, "held_for_evidence": held, "need_weights": {}})

    out["balanced"] = (base, {"max_change_pct": base.max_change_pct, "held_for_evidence": [], "need_weights": {}})

    gap_band = round(min(100.0, base.max_change_pct * GAP_BAND_FACTOR), 2)
    weights: dict[str, float] = {}
    gap_topics = []
    for t in base.topics:
        k = min(weak_downstream.get(t.topic_id, 0), WEAK_DOWNSTREAM_CAP)
        w = round(1 + WEAK_DOWNSTREAM_WEIGHT * k / WEAK_DOWNSTREAM_CAP, 4)
        if w != 1:
            weights[t.name] = w
        gap_topics.append(t.model_copy(update={"need_weight": w}))
    out["gap_focused"] = (base.model_copy(update={"max_change_pct": gap_band, "topics": gap_topics}),
                          {"max_change_pct": gap_band, "held_for_evidence": [], "need_weights": weights})
    return out


def _diff(base: OptimizerInput, rows: list[dict[str, Any]]) -> dict[str, Any]:
    changed = [r for r in rows if abs(r["delta"]) > 1e-9]
    return {"changed_topics": len(changed), "hours_moved": round(sum(r["delta"] for r in changed if r["delta"] > 0), 2),
            "hours_released": round(-sum(r["delta"] for r in changed if r["delta"] < 0), 2),
            "max_abs_change": round(max((abs(r["delta"]) for r in changed), default=0.0), 2),
            "changes": [{"topic_id": r["topic_id"], "name": r["name"], "current": r["current_hours"],
                         "proposed": r["proposed_hours"], "delta": r["delta"]} for r in changed]}


def build_scenarios(base: OptimizerInput, evidence: dict[int, str], weak_downstream: dict[int, int]
                    ) -> list[dict[str, Any]]:
    inputs = scenario_inputs(base, evidence, weak_downstream)
    out: list[dict[str, Any]] = []
    for key in SCENARIO_KEYS:
        inp, params = inputs[key]
        entry: dict[str, Any] = {"key": key, **SCENARIO_META[key], "parameters": params, "ok": False,
                                 "result": None, "error": None, "identical_to": [], "diff": None}
        try:
            res = optimize(inp)
            # independent re-verification of every hard constraint
            alloc = {r["topic_id"]: r["proposed_hours"] for r in res["rows"]}
            res["constraints"] = check_allocation(inp, alloc)
            if not all(c["ok"] for c in res["constraints"]):  # pragma: no cover - optimize guarantees this
                raise InfeasibleError("Внутренняя проверка ограничений не пройдена.", code="INTERNAL_CONSTRAINT")
            for r in res["rows"]:
                r["evidence"] = evidence.get(r["topic_id"], "insufficient")
            entry |= {"ok": True, "result": res, "diff": _diff(inp, res["rows"]), "allocation": alloc}
        except InfeasibleError as exc:
            entry["error"] = {"code": exc.code, "message": str(exc), "details": exc.details}
        out.append(entry)
    for a in out:
        if not a["ok"]:
            continue
        for b in out:
            if b is not a and b["ok"] and a["allocation"] == b["allocation"]:
                a["identical_to"].append(b["key"])
        if a["identical_to"]:
            a["identical_note"] = _identical_reason(a, [b for b in out if b["key"] in a["identical_to"]])
    for a in out:
        a.pop("allocation", None)
    return out


def _identical_reason(a: dict[str, Any], others: list[dict[str, Any]]) -> str:
    names = ", ".join(f"«{o['label']}»" for o in others)
    return (f"Распределение совпадает со сценарием {names}: при этих данных ограничения (мин./макс., лимит "
            "изменения, защита тем ниже цели и пререквизитов) оставляют одно и то же решение. Это результат расчёта, "
            "а не повтор шаблона.")
