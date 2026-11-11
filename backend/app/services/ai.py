"""AI explanations grounded in verified metrics — by construction, not by keyword policing.

Design:
1. Facts are structured: stable entity ids ("topic.T7-05", "textbook.TB-A7", "comparison.0", "plan", "overview",
   "settings") and metric names; a fact key is "<entity>.<metric>". Only aggregates, never student identifiers.
2. The LLM never writes numbers or entity names. It returns findings bound to ONE entity, with prose that may
   reference values only through placeholders: {{metric}} (a metric of that entity), {{name}} (the entity's name)
   or {{overview.metric}} / {{settings.metric}}. Raw digits and literal entity names are rejected, so a value
   cannot be moved to another topic or invented. Titles are rendered deterministically from the entity.
3. Placeholders are rendered deterministically with units, then the rendered text goes through the SAME
   verification as the deterministic explainer: every number must equal a fact of the finding's own entity
   (or overview/settings), with no exemptions for small numbers.
4. Semantic guards on top of the structure: no promises/causal claims; a finding about a topic must not
   contradict its computed status or gain direction; an "insufficient evidence" comparison must not name a
   better textbook. These lists are heuristic and documented as such — the structural rules above are the
   primary protection.
5. Any rejection → one retry with the error, then the deterministic explainer. Provider failures → deterministic.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.config import Settings

log = logging.getLogger(__name__)

NUMBER_RE = re.compile(r"(?<![\w.])[-+−]?\d+(?:[.,]\d+)?")
PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z0-9_.\-]+)\s*\}\}")
PROMISE_RE = re.compile(
    r"(?<!не )\b(гарантир\w*|доказыва\w*|доказал\w*|доказан\w*|превосход\w*|однозначно\s+лучш\w*|"
    r"является\s+причиной|приведёт|приведет|приведут|повысит|повысят|улучшит|улучшат|обеспечит|обеспечат|"
    r"позволит\s+(?:повысить|поднять|улучшить)|guarantee\w*|will\s+improve|prove[sn]?)\b",
    re.IGNORECASE,
)
POSITIVE_STATE_RE = re.compile(r"(не требует внимания|освоен[аы]? хорошо|хорошо освоен|в норме|успешно освоен|"
                               r"высок\w* освоени|проблем нет)", re.IGNORECASE)
PROGRESS_RE = re.compile(r"(прирост|рост|улучшени|осваивается|прогресс)", re.IGNORECASE)
WINNER_RE = re.compile(r"(эффективнее|лучше|превосход|выше)", re.IGNORECASE)
UNITS = {"mastery": "%", "median": "%", "mean": "%", "pre_mean": "%", "post_mean": "%", "average_mastery": "%",
         "baseline_mean": "%", "class_mean": "%", "gain": " п.п.", "gain_ci_low": " п.п.", "gain_ci_high": " п.п.",
         "adjusted_diff": " п.п.", "adjusted_ci_low": " п.п.", "adjusted_ci_high": " п.п.", "raw_diff": " п.п.",
         "baseline_diff": " п.п.", "gain_diff": " п.п.", "gain_mean": " п.п.", "gain_mean_a": " п.п.",
         "gain_mean_b": " п.п.", "current": " ч", "proposed": " ч", "delta": " ч", "total_hours": " ч", "hours": " ч",
         "difficult_threshold": "%", "watch_threshold": "%", "target_mastery": "%", "ci_level": "%",
         "gain_ci_level": "%"}
STATUS_TITLE = {"difficult": "Трудная тема", "watch": "Требует внимания", "ok": "Тема", "insufficient_data": "Тема",
                "no_outcome_data": "Тема"}


class Finding(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    text: str = Field(min_length=10, max_length=2500)
    kind: Literal["observation", "recommendation", "limitation"]
    entity: str = Field("overview", max_length=80)
    metric_keys: list[str] = Field(default_factory=list, max_length=20)


class InsightPayload(BaseModel):
    summary: str = Field(min_length=10, max_length=2000)
    findings: list[Finding] = Field(min_length=1, max_length=14)
    limitations: list[str] = Field(default_factory=list, max_length=10)
    next_steps: list[str] = Field(default_factory=list, max_length=10)


class LLMFinding(BaseModel):
    entity: str = Field(max_length=80)
    kind: Literal["observation", "recommendation", "limitation"]
    text: str = Field(min_length=10, max_length=1500)


class LLMPayload(BaseModel):
    summary: str = Field(min_length=10, max_length=1500)
    findings: list[LLMFinding] = Field(min_length=1, max_length=12)
    limitations: list[str] = Field(default_factory=list, max_length=8)
    next_steps: list[str] = Field(default_factory=list, max_length=8)


class GroundingError(ValueError):
    pass


def numbers_in(text: str) -> list[float]:
    out = []
    for tok in NUMBER_RE.findall(text):
        try:
            out.append(float(tok.replace("−", "-").replace(",", ".")))
        except ValueError:
            continue
    return out


# --------------------------------------------------------------------------- facts


def build_facts(context: dict[str, Any]) -> dict[str, Any]:
    """Flatten verified analytics into '<entity>.<metric>' -> value. Aggregates only; no student identifiers."""
    facts: dict[str, Any] = {}
    ov = context.get("overview") or {}
    topics = context.get("topics") or []
    for k in ("students", "assessments", "classes", "topics", "textbooks", "average_mastery"):
        facts[f"overview.{k}"] = ov.get(k)
    facts["overview.difficult_topics"] = sum(1 for t in topics if t["status"] == "difficult")
    th = context.get("settings") or {}
    for k in ("difficult_threshold", "watch_threshold", "target_mastery", "min_students_topic",
              "min_students_textbook", "min_classes_textbook"):
        facts[f"settings.{k}"] = th.get(k)
    for t in topics:
        p = f"topic.{t['code']}"
        facts[f"{p}.name"] = t["name"]
        for k, src in (("mastery", "mastery"), ("median", "median"), ("students", "student_count"),
                       ("status", "status"), ("hours", "hours"), ("class_mean", "class_mean")):
            facts[f"{p}.{k}"] = t.get(src)
        g = t.get("gain")
        if g:
            facts[f"{p}.gain"] = g["mean_gain"]
            facts[f"{p}.gain_direction"] = g.get("direction")
            facts[f"{p}.gain_ci_low"] = g["ci_low"]
            facts[f"{p}.gain_ci_high"] = g["ci_high"]
            facts[f"{p}.gain_ci_level"] = g.get("ci_level")
            facts[f"{p}.pre_mean"] = g["pre_mean"]
            facts[f"{p}.post_mean"] = g["post_mean"]
            facts[f"{p}.gain_n"] = g["n_paired"]
    tb = context.get("textbooks") or {}
    for s in tb.get("textbooks") or []:
        p = f"textbook.{s['code']}"
        facts[f"{p}.name"] = s["name"]
        for k in ("students", "classes", "mean", "baseline_mean", "gain_mean"):
            facts[f"{p}.{k}"] = s.get(k)
    for i, pr in enumerate(tb.get("pairs") or []):
        p = f"comparison.{i}"
        facts[f"{p}.name"] = f"{pr['name_a']} и {pr['name_b']}"
        facts[f"{p}.name_a"], facts[f"{p}.name_b"] = pr["name_a"], pr["name_b"]
        facts[f"{p}.verdict"] = pr["verdict"]
        facts[f"{p}.evidence_level"] = pr.get("evidence_level")
        facts[f"{p}.ci_level"] = pr.get("ci_level")
        facts[f"{p}.classes_a"], facts[f"{p}.classes_b"] = pr.get("classes_a"), pr.get("classes_b")
        facts[f"{p}.total_classes"] = (pr.get("classes_a") or 0) + (pr.get("classes_b") or 0)
        facts[f"{p}.excluded_small_classes"] = pr.get("excluded_small_classes")
        if pr.get("raw"):
            facts[f"{p}.raw_diff"] = pr["raw"].get("diff")
            facts[f"{p}.students_a"], facts[f"{p}.students_b"] = pr["raw"].get("n_a"), pr["raw"].get("n_b")
        if pr.get("adjusted"):
            for k in ("diff", "ci_low", "ci_high"):
                facts[f"{p}.adjusted_{k}"] = pr["adjusted"][k]
        if pr.get("gain"):
            for k in ("mean_a", "mean_b", "diff", "ci_low", "ci_high"):
                facts[f"{p}.gain_{k}"] = pr["gain"][k]
        facts[f"{p}.baseline_diff"] = pr.get("baseline_diff")
        facts[f"{p}.min_class_size"] = 5
    opt = context.get("optimizer")
    if opt:
        facts["plan.name"] = "план часов"
        facts["plan.total_hours"] = opt["total_hours"]
        facts["plan.status"] = context.get("optimizer_status")
        for r in opt["rows"]:
            p = f"plan.topic_{r['topic_id']}"
            facts[f"{p}.name"] = r["name"]
            for k, src in (("current", "current_hours"), ("proposed", "proposed_hours"), ("delta", "delta")):
                facts[f"{p}.{k}"] = r[src]
    return {k: v for k, v in facts.items() if v is not None}


def entity_names(facts: dict[str, Any]) -> dict[str, str]:
    return {k[: -len(".name")]: v for k, v in facts.items() if k.endswith(".name") and isinstance(v, str)}


def _entity_facts(facts: dict[str, Any], entity: str) -> dict[str, Any]:
    pref = entity + "."
    shared = ("overview.", "settings.")
    return {k: v for k, v in facts.items() if k.startswith(pref) or k.startswith(shared)
            or (entity == "plan" and k.startswith("plan."))}


# --------------------------------------------------------------------------- verification (shared)


def _allowed_numbers(facts_subset: dict[str, Any]) -> set[float]:
    allowed: set[float] = set()
    for v in facts_subset.values():
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            allowed |= {round(float(v), 1), round(abs(float(v)), 1), float(round(v)), float(round(abs(v)))}
        elif isinstance(v, str):
            allowed |= {abs(n) for n in numbers_in(v)} | set(numbers_in(v))
    return allowed


def _check_numbers(text: str, allowed: set[float], where: str) -> None:
    for n in numbers_in(text):
        if not any(abs(n - a) <= 0.051 for a in allowed):
            raise GroundingError(f"{where}: number {n} is not a verified metric of this entity")


def _check_semantics(text: str, entity: str, facts: dict[str, Any], where: str) -> None:
    if PROMISE_RE.search(text):
        raise GroundingError(f"{where}: causal claim or promise of improvement")
    if entity.startswith("topic."):
        status = facts.get(f"{entity}.status")
        direction = facts.get(f"{entity}.gain_direction")
        if status in ("difficult", "watch") and POSITIVE_STATE_RE.search(text):
            raise GroundingError(f"{where}: contradicts the computed status '{status}'")
        if direction in ("decline", "inconclusive", "insufficient") and re.search(
                r"(значим\w* прирост|осваивается|улучшени|прогресс)", text, re.IGNORECASE):
            raise GroundingError(f"{where}: describes progress although gain direction is '{direction}'")
    if entity.startswith("comparison.") and facts.get(f"{entity}.verdict") == "insufficient_evidence":
        if WINNER_RE.search(text) and not re.search(r"недостаточно|нельзя|не установлен", text, re.IGNORECASE):
            raise GroundingError(f"{where}: names a better textbook although evidence is insufficient")


def verify_rendered(p: InsightPayload, facts: dict[str, Any]) -> None:
    """Every number must belong to the finding's own entity (or overview/settings); semantic guards apply."""
    shared = _entity_facts(facts, "overview")
    _check_numbers(p.summary, _allowed_numbers(shared), "summary")
    _check_semantics(p.summary, "overview", facts, "summary")
    for i, f in enumerate(p.findings):
        unknown = sorted(k for k in f.metric_keys if k not in facts)
        if unknown:
            raise GroundingError(f"finding {i}: unknown metric keys {unknown[:5]}")
        subset = _entity_facts(facts, f.entity)
        if f.entity != "overview" and not any(k.startswith(f.entity + ".") for k in facts):
            raise GroundingError(f"finding {i}: unknown entity {f.entity}")
        allowed = _allowed_numbers(subset)
        _check_numbers(f.title + " " + f.text, allowed, f"finding {i}")
        _check_semantics(f.text, f.entity, facts, f"finding {i}")
    for j, t in enumerate(list(p.limitations) + list(p.next_steps)):
        _check_numbers(t, _allowed_numbers(shared), f"list item {j}")
        _check_semantics(t, "overview", facts, f"list item {j}")


def verify_payload(p: InsightPayload, facts: dict[str, Any]) -> None:  # backwards-compatible name
    verify_rendered(p, facts)


# --------------------------------------------------------------------------- LLM output → rendered payload


def _fmt(key: str, value: Any) -> str:
    unit = UNITS.get(key.rsplit(".", 1)[-1], "")
    if isinstance(value, float):
        return f"{value:g}{unit}"
    return f"{value}{unit}"


def render_llm_payload(raw: LLMPayload, facts: dict[str, Any]) -> InsightPayload:
    names = entity_names(facts)
    literal_names = sorted({n for n in names.values() if len(n) >= 4}, key=len, reverse=True)

    def render(text: str, entity: str, where: str) -> tuple[str, list[str]]:
        stripped = PLACEHOLDER_RE.sub("", text)
        if re.search(r"\d", stripped):
            raise GroundingError(f"{where}: digits outside placeholders are not allowed")
        low = stripped.lower()
        for n in literal_names:
            if n.lower() in low:
                raise GroundingError(f"{where}: entity names must be referenced via {{{{name}}}}")
        used: list[str] = []

        def sub(m: re.Match) -> str:
            ref = m.group(1)
            if ref == "name":
                if entity not in names:
                    raise GroundingError(f"{where}: entity '{entity}' has no name")
                return f"«{names[entity]}»"
            key = ref if ref.startswith(("overview.", "settings.")) else f"{entity}.{ref}"
            if key not in facts:
                raise GroundingError(f"{where}: unknown placeholder '{ref}' for entity '{entity}'")
            used.append(key)
            return _fmt(key, facts[key])

        return PLACEHOLDER_RE.sub(sub, text), used

    summary, _ = render(raw.summary, "overview", "summary")
    findings = []
    for i, f in enumerate(raw.findings):
        if f.entity != "overview" and not any(k.startswith(f.entity + ".") for k in facts):
            raise GroundingError(f"finding {i}: unknown entity {f.entity}")
        text, used = render(f.text, f.entity, f"finding {i}")
        findings.append(Finding(title=_title(f.entity, facts), text=text, kind=f.kind, entity=f.entity,
                                metric_keys=used))
    lims = [render(t, "overview", f"limitation {j}")[0] for j, t in enumerate(raw.limitations)]
    steps = [render(t, "overview", f"next step {j}")[0] for j, t in enumerate(raw.next_steps)]
    return InsightPayload(summary=summary, findings=findings, limitations=lims, next_steps=steps)


def _title(entity: str, facts: dict[str, Any]) -> str:
    name = entity_names(facts).get(entity)
    if entity.startswith("topic."):
        return f"{STATUS_TITLE.get(facts.get(entity + '.status'), 'Тема')}: {name}"
    if entity.startswith("comparison."):
        return f"Учебники: {name}"
    if entity.startswith("textbook."):
        return f"Учебник: {name}"
    if entity == "plan" or entity.startswith("plan."):
        return "Рекомендация по часам" if entity == "plan" else f"Часы: {name}"
    return "Общая картина"


# --------------------------------------------------------------------------- deterministic explainer

GAIN_PHRASE = {
    "increase": "статистически значимый прирост",
    "decline": "статистически значимое СНИЖЕНИЕ",
    "inconclusive": "изменение не установлено (интервал включает ноль; это не доказывает отсутствие эффекта)",
    "insufficient": "пар данных недостаточно для оценки динамики",
}


def deterministic_insights(context: dict[str, Any]) -> InsightPayload:
    facts = build_facts(context)
    topics = context.get("topics") or []
    ov = context.get("overview") or {}
    findings: list[Finding] = []
    difficult = [t for t in topics if t["status"] == "difficult"]
    watch = [t for t in topics if t["status"] == "watch"]
    summary = (f"Проанализировано {ov.get('students', 0)} учеников, {ov.get('assessments', 0)} оцениваний и "
               f"{ov.get('topics', 0)} тем. Среднее освоение по итоговым и текущим оцениваниям — "
               f"{ov.get('average_mastery')}%.")
    if difficult:
        summary += f" Трудных тем: {len(difficult)}."
    for t in difficult + watch:
        e = f"topic.{t['code']}"
        keys = [f"{e}.mastery", f"{e}.students"]
        text = (f"Освоение темы «{t['name']}» — {t['mastery']}% (медиана {t['median']}%, учеников: "
                f"{t['student_count']}). {t['interpretation']}")
        g = t.get("gain")
        if g and g.get("direction") != "insufficient":
            text += (f" Входная диагностика: {g['pre_mean']}%, итог: {g['post_mean']}%; изменение {g['mean_gain']} п.п. "
                     f"({g['ci_level']:g}% ДИ {g['ci_low']}…{g['ci_high']}) — {GAIN_PHRASE[g['direction']]}.")
            keys.append(f"{e}.gain")
        findings.append(Finding(title=_title(e, facts), text=text, kind="observation", entity=e, metric_keys=keys))
    declining_ok = [t for t in topics if t["status"] == "ok" and (t.get("gain") or {}).get("direction") == "decline"]
    for t in declining_ok:
        e, g = f"topic.{t['code']}", t["gain"]
        findings.append(Finding(title=_title(e, facts), kind="observation", entity=e, metric_keys=[f"{e}.gain"],
                                text=(f"Освоение темы «{t['name']}» — {t['mastery']}%, но по сравнению с входной "
                                      f"диагностикой результат снизился на {abs(g['mean_gain'])} п.п. "
                                      f"({g['ci_level']:g}% ДИ {g['ci_low']}…{g['ci_high']}). Причина не установлена.")))
    improving = [t for t in topics if (t.get("gain") or {}).get("direction") == "increase" and t["status"] == "ok"]
    if improving:
        best = max(improving, key=lambda t: t["gain"]["mean_gain"])
        e, g = f"topic.{best['code']}", best["gain"]
        findings.append(Finding(
            title=f"Заметный прирост: {best['name']}", entity=e, kind="observation", metric_keys=[f"{e}.gain"],
            text=(f"По теме «{best['name']}» результат вырос с {g['pre_mean']}% до {g['post_mean']}% "
                  f"(прирост {g['mean_gain']} п.п., {g['ci_level']:g}% ДИ {g['ci_low']}…{g['ci_high']}, "
                  f"пар: {g['n_paired']}). Связь с конкретными часами или учебником не установлена.")))
    tb = context.get("textbooks") or {}
    for i, pr in enumerate(tb.get("pairs") or []):
        e = f"comparison.{i}"
        text = pr["verdict_text"]
        if pr["verdict"] == "insufficient_evidence" and pr.get("reasons"):
            text += " Причины: " + " ".join(pr["reasons"])
        if pr.get("baseline_diff") is not None:
            text += f" Разница исходного уровня (средние классов): {pr['baseline_diff']} п.п."
        findings.append(Finding(title=_title(e, facts), text=text, kind="observation", entity=e,
                                metric_keys=[f"{e}.verdict"]))
    opt = context.get("optimizer")
    if opt:
        ups = [r for r in opt["rows"] if r["delta"] > 0]
        downs = [r for r in opt["rows"] if r["delta"] < 0]
        if ups or downs:
            status = {"accepted": "принято методистом", "rejected": "отклонено методистом"}.get(
                context.get("optimizer_status") or "", "предложено, решение не принято")
            text = f"Распределение часов ({status}; итог: {opt['total_hours']} ч). "
            if ups:
                text += "Увеличить: " + "; ".join(f"«{r['name']}» {r['current_hours']}→{r['proposed_hours']} ч" for r in ups) + ". "
            if downs:
                text += "Уменьшить: " + "; ".join(f"«{r['name']}» {r['current_hours']}→{r['proposed_hours']} ч" for r in downs) + ". "
            text += ("Изменения следуют из разрыва между освоением и целевым уровнем и приоритета темы; эффект "
                     "дополнительных часов не гарантирован и должен проверяться на следующих оцениваниях.")
            findings.append(Finding(title="Рекомендация по часам", text=text, kind="recommendation", entity="plan",
                                    metric_keys=["plan.total_hours"]))
    if not findings:
        findings.append(Finding(title="Существенных проблем не выявлено", entity="overview", kind="observation",
                                text="Все темы с достаточной выборкой освоены не ниже порога внимания."))
    limitations = [
        "Данные наблюдательные: классы распределены по учебникам и часам не случайно, поэтому причинные выводы "
        "невозможны.",
        "Освоение зависит от сложности конкретных заданий; сравнивайте темы с осторожностью.",
        "Динамика по темам оценена с поправкой на множественные сравнения (интервалы Бонферрони по темам в выборке).",
    ]
    if any(t["status"] == "insufficient_data" for t in topics):
        limitations.append("По части тем выборка меньше минимальной и они не классифицируются.")
    if not any(t.get("gain") for t in topics):
        limitations.append("Нет пар входной/итоговой диагностики — прирост не рассчитан.")
    next_steps = [
        "Обсудить трудные темы с учителями: какие типы заданий вызывают ошибки (анализ по заданиям).",
        "Проверить принятое распределение часов на следующем цикле оценивания и сравнить динамику.",
        "Для сравнения учебников собрать входную диагностику и данные как можно большего числа классов на учебник.",
    ]
    payload = InsightPayload(summary=summary, findings=findings[:14], limitations=limitations, next_steps=next_steps)
    verify_rendered(payload, facts)  # the deterministic explainer obeys the same grounding rules
    return payload


# --------------------------------------------------------------------------- LLM

SYSTEM_PROMPT = """Ты — аналитик-методист. Поясняй результаты анализа на русском языке для методиста школы.
Строгие правила вывода:
1. Верни только JSON: {"summary": str, "findings": [{"entity": str, "kind": "observation"|"recommendation"|
"limitation", "text": str}], "limitations": [str], "next_steps": [str]}.
2. entity — один идентификатор сущности из FACTS (например "topic.T7-05", "comparison.0", "plan", "overview").
3. НЕ пиши цифры и названия тем/учебников. Значения вставляй только плейсхолдерами: {{метрика}} — метрика этой
   сущности (например {{mastery}}, {{gain}}, {{adjusted_diff}}), {{name}} — её название, {{overview.students}} или
   {{settings.target_mastery}} — общие показатели. В summary, limitations и next_steps допускаются только
   {{overview.*}} и {{settings.*}}.
4. Не обещай улучшений и не делай причинных выводов. Не противоречь статусу темы (status) и направлению
   динамики (gain_direction). Если verdict = insufficient_evidence, не называй учебник лучшим."""

def call_llm(settings: Settings, system: str, user: str) -> str:
    if settings.llm_provider == "anthropic":
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": settings.llm_api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": settings.llm_model, "max_tokens": 3000, "system": system,
                  "messages": [{"role": "user", "content": user}]},
            timeout=settings.llm_timeout_seconds,
        )
        r.raise_for_status()
        data = r.json()
        blocks = data.get("content") if isinstance(data, dict) else None
        if not isinstance(blocks, list) or any(not isinstance(b, dict) for b in blocks):
            raise ValueError("Invalid provider content envelope")
        parts = [b.get("text") for b in blocks if b.get("type") == "text"]
        if not parts or any(not isinstance(p, str) for p in parts):
            raise ValueError("Missing provider text")
        return "".join(parts)
    if settings.llm_provider == "openai_compatible":
        base = settings.llm_base_url.rstrip("/")
        r = httpx.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            json={"model": settings.llm_model, "messages": [{"role": "system", "content": system},
                                                            {"role": "user", "content": user}],
                  "response_format": {"type": "json_object"}},
            timeout=settings.llm_timeout_seconds,
        )
        r.raise_for_status()
        data = r.json()
        choices = data.get("choices") if isinstance(data, dict) else None
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ValueError("Invalid provider choices envelope")
        message = choices[0].get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Missing provider text")
        return content
    raise RuntimeError("LLM provider is not configured")


def _extract_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).rstrip("`").strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("No JSON object in model output")
    return json.loads(text[start : end + 1])


def generate_insights(context: dict[str, Any], settings: Settings, llm=call_llm) -> dict[str, Any]:
    facts = build_facts(context)
    fallback_reason: str | None = None
    attempts = 0
    if settings.llm_enabled:
        user = "FACTS = " + json.dumps(facts, ensure_ascii=False)
        while attempts < 2:
            attempts += 1
            try:
                raw = LLMPayload.model_validate(_extract_json(llm(settings, SYSTEM_PROMPT, user)))
                payload = render_llm_payload(raw, facts)
                verify_rendered(payload, facts)
                return {"mode": "llm", "model": settings.llm_model, "payload": payload.model_dump(),
                        "facts": facts, "attempts": attempts, "fallback_reason": None}
            except (ValidationError, GroundingError, ValueError, json.JSONDecodeError) as exc:
                fallback_reason = f"Ответ модели отклонён проверкой: {type(exc).__name__}"
                log.warning("LLM output rejected (attempt %s): %s", attempts, type(exc).__name__)
                user += ("\n\nПредыдущий ответ отклонён проверкой: " + str(exc)[:300] +
                         ". Соблюдай правила: только плейсхолдеры, без цифр и названий.")
            except (httpx.HTTPError, RuntimeError, KeyError) as exc:
                fallback_reason = f"Сервис ИИ недоступен: {type(exc).__name__}"
                log.warning("LLM call failed: %s", type(exc).__name__)
                break
    else:
        fallback_reason = "Ключ API модели не задан — используется детерминированный режим."
    payload = deterministic_insights(context)
    return {"mode": "deterministic", "model": None, "payload": payload.model_dump(), "facts": facts,
            "attempts": attempts, "fallback_reason": fallback_reason}
