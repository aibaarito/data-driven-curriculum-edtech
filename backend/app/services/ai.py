"""AI explanations grounded in verified metrics.

The LLM is never a source of numbers. It receives a flat dictionary of verified facts (aggregates only,
no student identifiers) and must return JSON matching InsightPayload. Every number it writes must match
a fact value; every cited metric key must exist; causal/guarantee language is rejected. On any failure
we retry once, then fall back to the deterministic explainer.
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
FORBIDDEN_RE = re.compile(
    r"(?<!не )(?<!не\s)\b(гарантир\w*|доказыва\w*|доказал\w*|доказан\w*|превосход\w*|однозначно\s+лучш\w*|"
    r"является\s+причиной|guarantee\w*|prove[sn]?)\b",
    re.IGNORECASE,
)
ALWAYS_ALLOWED = {float(x) for x in range(0, 11)} | {95.0, 100.0}


class Finding(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    text: str = Field(min_length=10, max_length=1500)
    kind: Literal["observation", "recommendation", "limitation"]
    metric_keys: list[str] = Field(default_factory=list, max_length=12)


class InsightPayload(BaseModel):
    summary: str = Field(min_length=10, max_length=2000)
    findings: list[Finding] = Field(min_length=1, max_length=12)
    limitations: list[str] = Field(default_factory=list, max_length=10)
    next_steps: list[str] = Field(default_factory=list, max_length=10)


class GroundingError(ValueError):
    pass


def _texts(p: InsightPayload) -> list[str]:
    return [p.summary, *[f.title for f in p.findings], *[f.text for f in p.findings], *p.limitations, *p.next_steps]


def numbers_in(text: str) -> list[float]:
    out = []
    for tok in NUMBER_RE.findall(text):
        tok = tok.replace("−", "-").replace(",", ".")
        try:
            out.append(float(tok))
        except ValueError:
            continue
    return out


def verify_payload(p: InsightPayload, facts: dict[str, float | int | str | None]) -> None:
    """Raise GroundingError if the payload cites unknown metrics, invents numbers or claims causation."""
    unknown = sorted({k for f in p.findings for k in f.metric_keys if k not in facts})
    if unknown:
        raise GroundingError(f"Unknown metric keys: {unknown[:5]}")
    allowed = set(ALWAYS_ALLOWED)
    for v in facts.values():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            allowed.add(round(float(v), 1))
            allowed.add(round(abs(float(v)), 1))
            allowed.add(float(round(float(v))))
            allowed.add(float(round(abs(float(v)))))
        elif isinstance(v, str):  # numbers that are part of names, e.g. "Алгебра 11"
            allowed.update(abs(n) for n in numbers_in(v))
            allowed.update(numbers_in(v))
    for text in _texts(p):
        for n in numbers_in(text):
            if not any(abs(n - a) <= 0.051 or abs(abs(n) - a) <= 0.051 for a in allowed):
                raise GroundingError(f"Number {n} is not present in the verified metrics")
        if FORBIDDEN_RE.search(text):
            raise GroundingError("Causal or guarantee language is not allowed")


# --------------------------------------------------------------------------- facts


def build_facts(context: dict[str, Any]) -> dict[str, Any]:
    """Flatten verified analytics into key -> value. Only aggregates; no student identifiers."""
    facts: dict[str, Any] = {}
    ov = context.get("overview") or {}
    for k in ("students", "assessments", "classes", "topics", "textbooks", "average_mastery"):
        facts[f"overview.{k}"] = ov.get(k)
    facts["overview.difficult_topics"] = sum(1 for t in context.get("topics") or [] if t["status"] == "difficult")
    th = context.get("settings") or {}
    for k in ("difficult_threshold", "watch_threshold", "target_mastery", "min_students_topic"):
        facts[f"settings.{k}"] = th.get(k)
    for t in context.get("topics") or []:
        p = f"topic.{t['code']}"
        facts[f"{p}.name"] = t["name"]
        facts[f"{p}.mastery"] = t["mastery"]
        facts[f"{p}.median"] = t["median"]
        facts[f"{p}.students"] = t["student_count"]
        facts[f"{p}.status"] = t["status"]
        facts[f"{p}.hours"] = t.get("hours")
        g = t.get("gain")
        if g:
            facts[f"{p}.gain"] = g["mean_gain"]
            facts[f"{p}.gain_ci_low"] = g["ci_low"]
            facts[f"{p}.gain_ci_high"] = g["ci_high"]
            facts[f"{p}.pre_mean"] = g["pre_mean"]
            facts[f"{p}.post_mean"] = g["post_mean"]
            facts[f"{p}.gain_n"] = g["n_paired"]
    tb = context.get("textbooks") or {}
    for s in tb.get("textbooks") or []:
        p = f"textbook.{s['code']}"
        facts[f"{p}.name"] = s["name"]
        facts[f"{p}.students"] = s["students"]
        facts[f"{p}.classes"] = s["classes"]
        facts[f"{p}.mean"] = s["mean"]
        facts[f"{p}.baseline_mean"] = s["baseline_mean"]
        facts[f"{p}.gain_mean"] = s.get("gain_mean")
    for i, pr in enumerate(tb.get("pairs") or []):
        p = f"comparison.{i}"
        facts[f"{p}.verdict"] = pr["verdict"]
        if pr.get("raw"):
            facts[f"{p}.raw_diff"] = pr["raw"]["diff"]
        if pr.get("adjusted"):
            facts[f"{p}.adjusted_diff"] = pr["adjusted"]["diff"]
            facts[f"{p}.adjusted_ci_low"] = pr["adjusted"]["ci_low"]
            facts[f"{p}.adjusted_ci_high"] = pr["adjusted"]["ci_high"]
        facts[f"{p}.baseline_diff"] = pr.get("baseline_diff")
        if pr.get("gain"):
            for k in ("mean_a", "mean_b", "diff", "ci_low", "ci_high"):
                facts[f"{p}.gain_{k}"] = pr["gain"][k]
    opt = context.get("optimizer")
    if opt:
        facts["plan.total_hours"] = opt["total_hours"]
        for r in opt["rows"]:
            p = f"plan.topic_{r['topic_id']}"
            facts[f"{p}.name"] = r["name"]
            facts[f"{p}.current"] = r["current_hours"]
            facts[f"{p}.proposed"] = r["proposed_hours"]
            facts[f"{p}.delta"] = r["delta"]
    return {k: v for k, v in facts.items() if v is not None}


# --------------------------------------------------------------------------- deterministic explainer


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
        keys = [f"topic.{t['code']}.mastery", f"topic.{t['code']}.students"]
        text = (f"Освоение темы «{t['name']}» — {t['mastery']}% (медиана {t['median']}%, учеников: "
                f"{t['student_count']}). {t['interpretation']}")
        g = t.get("gain")
        if g:
            text += (f" Входная диагностика: {g['pre_mean']}%, итог: {g['post_mean']}%, средний прирост "
                     f"{g['mean_gain']} п.п. (95% ДИ {g['ci_low']}…{g['ci_high']}).")
            keys += [f"topic.{t['code']}.gain"]
        findings.append(Finding(title=f"{'Трудная тема' if t['status'] == 'difficult' else 'Требует внимания'}: "
                                      f"{t['name']}", text=text, kind="observation", metric_keys=keys))
    improving = [t for t in topics if t.get("gain") and t["gain"]["significant"] and t["gain"]["mean_gain"] > 0
                 and t["status"] == "ok"]
    if improving:
        best = max(improving, key=lambda t: t["gain"]["mean_gain"])
        g = best["gain"]
        findings.append(Finding(
            title=f"Заметный прирост: {best['name']}",
            text=(f"По теме «{best['name']}» результат вырос с {g['pre_mean']}% до {g['post_mean']}% "
                  f"(прирост {g['mean_gain']} п.п., 95% ДИ {g['ci_low']}…{g['ci_high']}, пар: {g['n_paired']})."),
            kind="observation", metric_keys=[f"topic.{best['code']}.gain"]))
    tb = context.get("textbooks") or {}
    for i, pr in enumerate(tb.get("pairs") or []):
        text = pr["verdict_text"]
        if pr["verdict"] == "insufficient_evidence" and pr.get("reasons"):
            text += " Причины: " + " ".join(pr["reasons"])
        if pr.get("baseline_diff") is not None:
            text += f" Разница исходного уровня: {pr['baseline_diff']} п.п."
        findings.append(Finding(title=f"Учебники: {pr['name_a']} и {pr['name_b']}", text=text,
                                kind="observation", metric_keys=[f"comparison.{i}.verdict"]))
    opt = context.get("optimizer")
    if opt:
        ups = [r for r in opt["rows"] if r["delta"] > 0]
        downs = [r for r in opt["rows"] if r["delta"] < 0]
        if ups or downs:
            status = {"accepted": "принято методистом", "rejected": "отклонено методистом"}.get(
                context.get("optimizer_status") or "", "предложено, решение не принято")
            text = f"Распределение часов ({status}; сумма сохранена: {opt['total_hours']} ч). "
            if ups:
                text += "Увеличить: " + "; ".join(f"«{r['name']}» {r['current_hours']}→{r['proposed_hours']} ч" for r in ups) + ". "
            if downs:
                text += "Уменьшить: " + "; ".join(f"«{r['name']}» {r['current_hours']}→{r['proposed_hours']} ч" for r in downs) + ". "
            text += "Каждое изменение обосновано разрывом между освоением и целевым уровнем и приоритетом темы."
            findings.append(Finding(title="Рекомендация по часам", text=text, kind="recommendation",
                                    metric_keys=["plan.total_hours"]))
    if not findings:
        findings.append(Finding(title="Существенных проблем не выявлено",
                                text="Все темы с достаточной выборкой освоены не ниже порога внимания.",
                                kind="observation", metric_keys=[]))
    limitations = [
        "Данные наблюдательные: классы распределены по учебникам и часам не случайно, поэтому причинные выводы "
        "невозможны.",
        "Освоение зависит от сложности конкретных заданий; сравнивайте темы с осторожностью.",
    ]
    if any(t["status"] == "insufficient_data" for t in topics):
        limitations.append("По части тем выборка меньше минимальной и они не классифицируются.")
    if not any(t.get("gain") for t in topics):
        limitations.append("Нет пар входной/итоговой диагностики — прирост не рассчитан.")
    next_steps = [
        "Обсудить трудные темы с учителями: какие типы заданий вызывают ошибки (анализ по заданиям).",
        "Проверить предложенное распределение часов на следующем цикле оценивания и сравнить прирост.",
        "Для сравнения учебников собрать входную диагностику и данные минимум трёх классов на каждый учебник.",
    ]
    payload = InsightPayload(summary=summary, findings=findings[:12], limitations=limitations, next_steps=next_steps)
    verify_payload(payload, facts)  # the deterministic explainer obeys the same grounding rules
    return payload


# --------------------------------------------------------------------------- LLM


SYSTEM_PROMPT = """Ты — аналитик-методист. Объясняй результаты анализа учебных данных на русском языке
для методиста школы. Правила:
1. Используй ТОЛЬКО числа из словаря FACTS. Не вычисляй новые числа, не округляй иначе, не выдумывай.
2. В metric_keys указывай ключи FACTS, на которые опирается вывод.
3. Не делай причинных выводов и не обещай улучшений: используй формулировки «наблюдается», «связано»,
   «может указывать». Не называй учебник лучшим, если verdict = insufficient_evidence.
4. Отличай наблюдения (observation), рекомендации (recommendation) и ограничения (limitation).
5. Ответ — только JSON без markdown со структурой:
{"summary": str, "findings": [{"title": str, "text": str, "kind": "observation"|"recommendation"|"limitation",
"metric_keys": [str]}], "limitations": [str], "next_steps": [str]}"""


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
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
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
        return r.json()["choices"][0]["message"]["content"]
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
    if settings.llm_enabled:
        user = "FACTS = " + json.dumps(facts, ensure_ascii=False)
        attempts = 0
        while attempts < 2:
            attempts += 1
            try:
                raw = llm(settings, SYSTEM_PROMPT, user)
                payload = InsightPayload.model_validate(_extract_json(raw))
                verify_payload(payload, facts)
                return {"mode": "llm", "model": settings.llm_model, "payload": payload.model_dump(),
                        "facts": facts, "attempts": attempts, "fallback_reason": None}
            except (ValidationError, GroundingError, ValueError, json.JSONDecodeError) as exc:
                fallback_reason = f"Ответ модели отклонён проверкой: {type(exc).__name__}"
                log.warning("LLM output rejected (attempt %s): %s", attempts, exc)
                user += ("\n\nПредыдущий ответ отклонён проверкой: " + str(exc)[:300] +
                         ". Используй только числа и ключи из FACTS и верни корректный JSON.")
            except (httpx.HTTPError, RuntimeError, KeyError) as exc:
                fallback_reason = f"Сервис ИИ недоступен: {type(exc).__name__}"
                log.warning("LLM call failed: %s", type(exc).__name__)
                break
    else:
        fallback_reason = "Ключ API модели не задан — используется детерминированный режим."
    payload = deterministic_insights(context)
    return {"mode": "deterministic", "model": None, "payload": payload.model_dump(), "facts": facts,
            "attempts": 0, "fallback_reason": fallback_reason}
