"""Deterministic decision intelligence: verified findings → structured, reviewable decision candidates.

The engine never predicts learning improvement and never treats "more hours" as the default remedy. Each
candidate separates four kinds of statements: observation, statistical interpretation, recommendation (the proposed
action, produced by the rule table below) and hypothesis (an effect that has NOT been verified).

Rule table (problem → primary action; see docs/ANALYTICS.md § Decision rules):
    insufficient evidence            → collect_more_evidence      (hours preserved)
    low + significant decline        → review_methodology         (hours preserved; more hours rejected)
    ok + significant decline         → review_methodology
    low + change not established     → review_methodology         (+ increase_hours only inside a reviewed scenario)
    low + no baseline / too few pairs→ add_diagnostic_assessment
    low + significant increase       → increase_hours (reallocate within the budget; slow but measurable learning)
    weak prerequisite of weak topics → review_prerequisites added (foundational gap)
    textbook pair observed difference→ review_textbook (scope level; never "replace")
"""
from __future__ import annotations

from typing import Any

from app.services.evidence import assess_textbook_pair, assess_topic, sha
from app.services.settings_store import AnalysisSettings

ACTIONS = {
    "review_methodology": "Пересмотреть методику преподавания темы",
    "increase_hours": "Увеличить часы (перераспределением в рамках бюджета)",
    "reallocate_hours": "Высвободить часы для других тем",
    "add_diagnostic_assessment": "Провести дополнительную диагностику",
    "review_prerequisites": "Проверить освоение пререквизитов",
    "review_textbook": "Проверить соответствие учебника",
    "collect_more_evidence": "Собрать больше данных",
    "maintain": "Сохранить текущий план",
}
PROBLEMS = {
    "insufficient_evidence": "Недостаточно данных для вывода",
    "low_declining": "Низкое освоение и значимое снижение",
    "ok_but_declining": "Освоение в норме, но значимое снижение",
    "low_no_measurable_gain": "Низкое освоение, изменение не установлено",
    "low_no_baseline": "Низкое освоение, нет входной диагностики",
    "low_gain_insufficient": "Низкое освоение, мало пар для оценки динамики",
    "low_but_improving": "Низкое освоение, но значимый прирост",
    "foundational_gap": "Слабый пререквизит слабых тем",
    "surplus": "Освоение выше цели",
    "textbook_difference": "Наблюдаемое различие между учебниками",
}
SEVERITY = {"low_declining": 3, "ok_but_declining": 2, "low_no_measurable_gain": 2, "low_no_baseline": 2,
            "low_gain_insufficient": 2, "low_but_improving": 1, "insufficient_evidence": 1, "foundational_gap": 2,
            "surplus": 0, "textbook_difference": 1}


def _rule(t: dict[str, Any], ev: dict[str, Any]) -> tuple[str, str, list[str], list[dict[str, str]]]:
    """(problem, primary action, secondary actions, rejected alternatives with reasons)."""
    interp = t.get("interpretation_code")
    if ev["category"] == "insufficient":
        return ("insufficient_evidence", "collect_more_evidence", ["add_diagnostic_assessment"], [
            {"code": "increase_hours", "reason": "Диагноз не подтверждён данными: часы не меняются автоматически."}])
    if interp in ("low_declining", "ok_but_declining"):
        return (interp, "review_methodology", ["add_diagnostic_assessment"], [
            {"code": "increase_hours", "reason": "Причина снижения не установлена; увеличение часов не является "
                                                 "доказанным средством. Часы сохраняются до анализа причин, если "
                                                 "эксперт явно не решит иначе."}])
    if interp == "low_no_measurable_gain":
        return (interp, "review_methodology", ["increase_hours"], [
            {"code": "increase_hours (как основное действие)",
             "reason": "Изменение от входной к итоговой диагностике не установлено: одних дополнительных часов может "
                       "быть недостаточно. Увеличение допускается только в составе проверенного сценария."}])
    if interp in ("low_no_baseline", "low_gain_insufficient"):
        return (interp, "add_diagnostic_assessment", ["increase_hours"], [
            {"code": "review_methodology", "reason": "Без входной диагностики нельзя отличить слабую исходную "
                                                     "подготовку от трудностей обучения."}])
    if interp == "low_but_improving":
        return (interp, "increase_hours", [], [
            {"code": "review_methodology", "reason": "Зафиксирован значимый прирост: тема осваивается, хотя "
                                                     "медленно; пересмотр методики не первоочередной."}])
    return ("surplus", "maintain", [], [])


def topic_candidates(topics: list[dict[str, Any]], s: AnalysisSettings, fingerprint: str,
                     graph_nodes: dict[int, dict[str, Any]] | None = None,
                     plan_rows: dict[int, dict[str, Any]] | None = None,
                     sensitivity: dict[str, dict[int, float] | None] | None = None) -> list[dict[str, Any]]:
    graph_nodes = graph_nodes or {}
    plan_rows = plan_rows or {}
    names = {t["topic_id"]: t["name"] for t in topics}
    out = []
    for t in topics:
        ev = assess_topic(t, s)
        node = graph_nodes.get(t["topic_id"], {})
        is_problem = (t["status"] in ("difficult", "watch") or t.get("interpretation_code") == "ok_but_declining"
                      or ev["category"] == "insufficient" or node.get("foundational_gap"))
        if not is_problem:
            continue
        problem, action, secondary, rejected = _rule(t, ev)
        if node.get("foundational_gap"):
            secondary = [*secondary, "review_prerequisites"] if "review_prerequisites" not in secondary else secondary
            if problem not in ("low_declining",):
                problem = problem if SEVERITY.get(problem, 0) >= SEVERITY["foundational_gap"] else "foundational_gap"
        weak_prereqs = [p for p in node.get("prerequisites", []) if graph_nodes.get(p, {}).get("status")
                        in ("difficult", "watch")]
        if weak_prereqs and "review_prerequisites" not in secondary:
            secondary = [*secondary, "review_prerequisites"]
        gain = t.get("gain") or {}
        observations = [f"Освоение {t['mastery']}% по {t['student_count']} ученикам из {t['class_count']} классов."
                        if t.get("mastery") is not None else "Освоение не рассчитано: нет итоговых оцениваний."]
        if gain.get("ci_low") is not None:
            observations.append(f"Среднее изменение от входной к итоговой: {gain['mean_gain']:+} п.п. "
                                f"({gain['n_paired']} пар).")
        if node.get("weak_downstream"):
            observations.append("Тема предшествует слабым темам: " + ", ".join(
                f"«{graph_nodes[i]['name']}»" for i in node["weak_downstream"] if i in graph_nodes) + ".")
        if weak_prereqs:
            observations.append("Слабые пререквизиты: " + ", ".join(
                f"«{graph_nodes[i]['name']}»" for i in weak_prereqs) + ".")
        row = plan_rows.get(t["topic_id"])
        impact: dict[str, Any] = {"balanced_delta": row["delta"] if row else None,
                                  "balanced_proposed": row["proposed_hours"] if row else None,
                                  "current_hours": row["current_hours"] if row else t.get("hours"),
                                  "explanation": row["explanation"] if row else None, "sensitivity": None}
        if sensitivity and row:
            sens = {}
            for k, alloc in sensitivity.items():
                sens[k] = None if alloc is None else round(alloc.get(t["topic_id"], row["current_hours"])
                                                           - row["current_hours"], 2)
            impact["sensitivity"] = sens
        pr = node.get("priority") or {"score": 0.0, "components": {}}
        hypothesis = None
        if action in ("increase_hours", "review_methodology", "review_prerequisites"):
            hypothesis = ("Гипотеза (не проверена): выбранное действие может повысить освоение темы. Проверить на "
                          "следующем сопоставимом оценивании; без группы сравнения вывод будет наблюдательным.")
        limitations = ["Данные наблюдательные: причина низкого результата по данным не установлена."]
        if ev["category"] == "exploratory":
            limitations += ev["reasons"]
        if s and t.get("class_mean") is not None and t.get("mastery") is not None and abs(t["class_mean"] - t["mastery"]) >= 3:
            limitations.append("Объединённое и среднее по классам освоение заметно различаются.")
        out.append({
            "id": sha({"fp": fingerprint, "topic": t["code"], "action": action}, 16),
            "kind": "topic", "topic_id": t["topic_id"], "topic_code": t["code"], "topic_name": t["name"],
            "grade": t["grade"], "status": t["status"],
            "problem": {"code": problem, "label": PROBLEMS[problem], "severity": SEVERITY.get(problem, 0)},
            "evidence": ev,
            "action": {"code": action, "label": ACTIONS[action]},
            "secondary_actions": [{"code": a, "label": ACTIONS[a]} for a in secondary],
            "rejected_alternatives": [{"code": r["code"], "label": ACTIONS.get(r["code"], r["code"]),
                                       "reason": r["reason"]} for r in rejected],
            "observations": observations,
            "interpretation": t.get("interpretation"),
            "hypothesis": hypothesis,
            "limitations": limitations,
            "required_review": _review(action, ev),
            "constraint_impact": impact,
            "priority": pr,
            "why_topic": node.get("why") or [t.get("interpretation") or ""],
            "related_topics": {"weak_prerequisites": [{"topic_id": i, "name": names.get(i, graph_nodes.get(i, {})
                                                                                      .get("name"))} for i in weak_prereqs],
                               "weak_dependents": [{"topic_id": i, "name": graph_nodes.get(i, {}).get("name")}
                                                   for i in node.get("weak_downstream", [])]},
            "version": {"fingerprint": fingerprint},
            "statement_kinds": {"observations": "observation", "interpretation": "statistical_interpretation",
                                "action": "recommendation", "hypothesis": "hypothesis"},
        })
    out.sort(key=lambda d: (not d["evidence"]["allows_action"], -d["priority"]["score"], -d["problem"]["severity"],
                            d["topic_code"]))
    return out


def _review(action: str, ev: dict[str, Any]) -> str:
    if not ev["allows_action"]:
        return "Экспертная проверка данных; автоматических изменений плана нет."
    if action == "review_methodology":
        return "Методист/предметное объединение: анализ причин до изменения часов."
    if ev["category"] == "exploratory":
        return "Методист: подтвердить вывод вручную (данные предварительные)."
    return "Методист: утвердить изменение в составе сценария плана часов."


def textbook_candidates(pairs: list[dict[str, Any]], fingerprint: str) -> list[dict[str, Any]]:
    out = []
    for p in pairs:
        ev = assess_textbook_pair(p)
        if p.get("verdict") != "observed_difference":
            continue
        out.append({
            "id": sha({"fp": fingerprint, "pair": [p["textbook_a"], p["textbook_b"]], "action": "review_textbook"}, 16),
            "kind": "textbook", "pair": [p["textbook_a"], p["textbook_b"]], "topic_name": None,
            "title": f"«{p['name_a']}» / «{p['name_b']}»",
            "problem": {"code": "textbook_difference", "label": PROBLEMS["textbook_difference"], "severity": 1},
            "evidence": ev, "action": {"code": "review_textbook", "label": ACTIONS["review_textbook"]},
            "secondary_actions": [{"code": "collect_more_evidence", "label": ACTIONS["collect_more_evidence"]}],
            "rejected_alternatives": [{"code": "replace_textbook", "label": "Заменить учебник",
                                       "reason": "Связь наблюдательная (классы распределены не случайно); замена "
                                                 "учебника по этим данным не обоснована."}],
            "observations": [p["verdict_text"]], "interpretation": "Наблюдаемая связь, не причинный эффект.",
            "hypothesis": None, "limitations": list(p.get("confounders") or []),
            "required_review": "Предметное объединение: сопоставить с содержанием учебников.",
            "constraint_impact": None, "priority": {"score": 0.0, "components": {}}, "why_topic": [],
            "related_topics": {}, "version": {"fingerprint": fingerprint},
            "statement_kinds": {"observations": "observation", "interpretation": "statistical_interpretation",
                                "action": "recommendation"},
        })
    return out


def readiness_summary(topics: list[dict[str, Any]], s: AnalysisSettings) -> dict[str, int]:
    counts = {"supported": 0, "exploratory": 0, "insufficient": 0, "incomparable": 0, "stale": 0}
    for t in topics:
        counts[assess_topic(t, s)["category"]] += 1
    return counts
