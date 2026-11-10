import json

import httpx
import pytest

from app.config import Settings
from app.services.ai import (
    Finding,
    GroundingError,
    InsightPayload,
    build_facts,
    deterministic_insights,
    generate_insights,
    verify_payload,
)

CTX = {
    "overview": {"students": 40, "assessments": 2, "classes": 2, "topics": 2, "textbooks": 0, "average_mastery": 61.3},
    "settings": {"difficult_threshold": 50, "watch_threshold": 65, "target_mastery": 75, "min_students_topic": 10},
    "topics": [
        {"code": "T1", "name": "Дроби", "mastery": 42.5, "median": 40.0, "student_count": 40, "status": "difficult",
         "interpretation": "Низкий результат.", "hours": 6.0,
         "gain": {"mean_gain": 1.2, "ci_low": -2.0, "ci_high": 4.4, "pre_mean": 41.3, "post_mean": 42.5,
                  "n_paired": 40, "significant": False}},
        {"code": "T2", "name": "Уравнения", "mastery": 80.1, "median": 82.0, "student_count": 40, "status": "ok",
         "interpretation": "ok", "hours": 10.0, "gain": None},
    ],
    "textbooks": {"textbooks": [], "pairs": []},
    "optimizer": None,
}
LLM_ON = Settings(llm_api_key="test-key", llm_provider="anthropic")
GOOD = {
    "summary": "Освоение темы «Дроби» составляет 42.5%, что ниже порога 50.",
    "findings": [{"title": "Дроби", "text": "Освоение 42.5% при медиане 40.0%; прирост 1.2 п.п. статистически не значим.",
                  "kind": "observation", "metric_keys": ["topic.T1.mastery", "topic.T1.gain"]}],
    "limitations": ["Данные наблюдательные."],
    "next_steps": ["Проанализировать задания по теме."],
}


def payload(**over):
    return InsightPayload.model_validate({**GOOD, **over})


def test_facts_contain_no_student_identifiers():
    facts = build_facts(CTX)
    assert facts["topic.T1.mastery"] == 42.5
    assert not any("student_id" in k or "S1" == v for k, v in facts.items())


def test_grounded_payload_passes():
    verify_payload(payload(), build_facts(CTX))


def test_invented_number_rejected():
    with pytest.raises(GroundingError, match="73.4"):
        verify_payload(payload(summary="Освоение выросло до 73.4% за год."), build_facts(CTX))


def test_unknown_metric_key_rejected():
    bad = {**GOOD["findings"][0], "metric_keys": ["topic.T9.mastery"]}
    with pytest.raises(GroundingError, match="Unknown metric"):
        verify_payload(payload(findings=[bad]), build_facts(CTX))


@pytest.mark.parametrize("text", ["Учебник гарантирует рост результатов.", "Это доказывает эффективность.",
                                  "Учебник А превосходит учебник Б."])
def test_causal_language_rejected(text):
    with pytest.raises(GroundingError):
        verify_payload(payload(summary=text), build_facts(CTX))


def test_negated_language_allowed():
    verify_payload(payload(summary="Рост освоения не гарантирован, данные наблюдательные."), build_facts(CTX))


def test_deterministic_explainer_is_grounded():
    p = deterministic_insights(CTX)
    verify_payload(p, build_facts(CTX))
    assert any("Дроби" in f.title for f in p.findings)


def test_no_api_key_uses_deterministic_mode():
    out = generate_insights(CTX, Settings(llm_api_key=""))
    assert out["mode"] == "deterministic" and "Ключ API" in out["fallback_reason"]


def test_valid_llm_output_used():
    out = generate_insights(CTX, LLM_ON, llm=lambda *a: json.dumps(GOOD, ensure_ascii=False))
    assert out["mode"] == "llm" and out["attempts"] == 1


def test_malformed_json_retried_then_succeeds():
    calls = iter(["not json at all", "```json\n" + json.dumps(GOOD, ensure_ascii=False) + "\n```"])
    out = generate_insights(CTX, LLM_ON, llm=lambda *a: next(calls))
    assert out["mode"] == "llm" and out["attempts"] == 2


def test_persistently_bad_output_falls_back():
    bad = {**GOOD, "summary": "Освоение 99.9% — гарантирует успех."}
    out = generate_insights(CTX, LLM_ON, llm=lambda *a: json.dumps(bad, ensure_ascii=False))
    assert out["mode"] == "deterministic" and "отклонён" in out["fallback_reason"]


def test_schema_violation_falls_back():
    out = generate_insights(CTX, LLM_ON, llm=lambda *a: json.dumps({"summary": "x"}))
    assert out["mode"] == "deterministic"


def test_provider_outage_falls_back():
    def boom(*a):
        raise httpx.ConnectTimeout("timeout")
    out = generate_insights(CTX, LLM_ON, llm=boom)
    assert out["mode"] == "deterministic" and "недоступен" in out["fallback_reason"]


def test_finding_schema_validation():
    with pytest.raises(Exception):
        Finding(title="x", text="short", kind="guess", metric_keys=[])


def test_missing_env_vars_use_safe_defaults(monkeypatch):
    for k in ("LLM_API_KEY", "LLM_PROVIDER", "MAX_UPLOAD_MB"):
        monkeypatch.delenv(k, raising=False)
    s = Settings(_env_file=None)
    assert s.llm_enabled is False and s.max_upload_mb == 10
