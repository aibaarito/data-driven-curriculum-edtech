"""AI grounding tests. All LLM calls are MOCKED — these tests do not exercise a live provider."""
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
    verify_rendered,
)


def gain(mean, lo, hi, direction, pre=41.3, post=42.5):
    return {"mean_gain": mean, "ci_low": lo, "ci_high": hi, "pre_mean": pre, "post_mean": post, "n_paired": 40,
            "significant": direction in ("increase", "decline"), "direction": direction, "ci_level": 99.17}


CTX = {
    "overview": {"students": 40, "assessments": 2, "classes": 2, "topics": 3, "textbooks": 2, "average_mastery": 61.3},
    "settings": {"difficult_threshold": 50, "watch_threshold": 65, "target_mastery": 75, "min_students_topic": 10,
                 "min_students_textbook": 30, "min_classes_textbook": 3},
    "topics": [
        {"code": "T1", "name": "Дроби", "mastery": 42.5, "median": 40.0, "student_count": 40, "status": "difficult",
         "interpretation": "Низкий результат.", "hours": 6.0, "gain": gain(1.2, -2.0, 4.4, "inconclusive")},
        {"code": "T2", "name": "Уравнения", "mastery": 80.1, "median": 82.0, "student_count": 40, "status": "ok",
         "interpretation": "ok", "hours": 10.0, "gain": None},
        {"code": "T3", "name": "Проценты", "mastery": 45.0, "median": 44.0, "student_count": 40, "status": "difficult",
         "interpretation": "Низкий результат и снижение.", "hours": 8.0,
         "gain": gain(-6.0, -9.1, -2.9, "decline", pre=51.0, post=45.0)},
    ],
    "textbooks": {"textbooks": [], "pairs": [
        {"name_a": "Учебник А", "name_b": "Учебник Б", "verdict": "insufficient_evidence",
         "verdict_text": "Недостаточно данных, чтобы определить, какой учебник эффективнее.", "reasons": [],
         "raw": {"diff": 1.5, "n_a": 20, "n_b": 21}, "adjusted": None, "gain": None, "baseline_diff": None,
         "classes_a": 1, "classes_b": 1, "ci_level": 95.0, "evidence_level": "insufficient",
         "excluded_small_classes": 0}]},
    "optimizer": None,
}
LLM_ON = Settings(llm_api_key="test-key", llm_provider="anthropic", _env_file=None)
FACTS = build_facts(CTX)
GOOD_LLM = {
    "summary": "Проанализировано {{overview.students}} учеников; трудных тем: {{overview.difficult_topics}}.",
    "findings": [{"entity": "topic.T1", "kind": "observation",
                  "text": "Освоение темы {{name}} — {{mastery}}; изменение {{gain}} не установлено."}],
    "limitations": ["Данные наблюдательные."],
    "next_steps": ["Проанализировать задания по теме."],
}


def finding(entity, text, kind="observation"):
    return Finding(title="Тема", text=text, kind=kind, entity=entity)


def payload(*findings, summary="Проанализировано 40 учеников."):
    return InsightPayload(summary=summary, findings=list(findings))


def llm_returning(*outputs):
    it = iter(outputs)
    return lambda *a: next(it)


# ------------------------------------------------------------------ rendered-text verification


def test_facts_are_entity_keyed_and_contain_no_student_identifiers():
    assert FACTS["topic.T1.mastery"] == 42.5 and FACTS["topic.T3.gain_direction"] == "decline"
    assert all(k.split(".")[0] in {"overview", "settings", "topic", "textbook", "comparison", "plan"} for k in FACTS)


def test_value_of_another_topic_is_rejected():
    """Audit A1: 80.1 is a real fact, but it belongs to «Уравнения», not to «Дроби»."""
    with pytest.raises(GroundingError, match="not a verified metric of this entity"):
        verify_rendered(payload(finding("topic.T1", "Тема «Дроби» освоена на 80.1%.")), FACTS)


def test_small_invented_numbers_are_not_exempt():
    with pytest.raises(GroundingError):
        verify_rendered(payload(finding("topic.T1", "Освоение 42.5%, проблема в 7 классах.")), FACTS)


@pytest.mark.parametrize("text", ["Освоение 42.5%; дополнительные часы повысят результат.",
                                  "Освоение 42.5%, это доказывает эффективность метода.",
                                  "Рост часов приведёт к улучшению освоения 42.5%."])
def test_causal_promises_rejected(text):
    with pytest.raises(GroundingError, match="causal"):
        verify_rendered(payload(finding("topic.T1", text)), FACTS)


def test_negated_language_allowed():
    verify_rendered(payload(finding("topic.T1", "Освоение 42.5%. Рост освоения не гарантирован.")), FACTS)


def test_status_contradiction_rejected():
    with pytest.raises(GroundingError, match="status"):
        verify_rendered(payload(finding("topic.T1", "Тема освоена хорошо: 42.5%.")), FACTS)


def test_decline_described_as_progress_rejected():
    with pytest.raises(GroundingError, match="progress"):
        verify_rendered(payload(finding("topic.T3", "Тема осваивается, изменение 6.0 п.п.")), FACTS)


def test_winner_for_insufficient_comparison_rejected():
    with pytest.raises(GroundingError, match="better textbook"):
        verify_rendered(payload(finding("comparison.0", "Учебник Б эффективнее учебника А.")), FACTS)


def test_deterministic_explainer_passes_its_own_checks_and_is_sign_aware():
    p = deterministic_insights(CTX)
    verify_rendered(p, FACTS)
    t3 = next(f for f in p.findings if f.entity == "topic.T3")
    assert "СНИЖЕНИЕ" in t3.text and "прирост" not in t3.text.lower()
    t1 = next(f for f in p.findings if f.entity == "topic.T1")
    assert "не доказывает отсутствие эффекта" in t1.text


# ------------------------------------------------------------------ LLM pipeline (mocked)


def test_no_api_key_uses_deterministic_mode():
    out = generate_insights(CTX, Settings(llm_api_key="", _env_file=None))
    assert out["mode"] == "deterministic" and "Ключ API" in out["fallback_reason"]


def test_placeholder_output_is_rendered_from_facts():
    out = generate_insights(CTX, LLM_ON, llm=llm_returning(json.dumps(GOOD_LLM, ensure_ascii=False)))
    assert out["mode"] == "llm" and out["attempts"] == 1
    f = out["payload"]["findings"][0]
    assert "«Дроби»" in f["text"] and "42.5%" in f["text"] and f["title"] == "Трудная тема: Дроби"
    assert set(f["metric_keys"]) == {"topic.T1.mastery", "topic.T1.gain"}


@pytest.mark.parametrize("bad_text,reason", [
    ("Освоение темы {{name}} — 80.1%.", "digits"),
    ("Освоение темы Дроби — {{mastery}}.", "names"),
    ("Освоение {{name}}: {{mastery}}, медиана {{median_of_other}}.", "placeholder"),
])
def test_llm_structural_violations_fall_back(bad_text, reason):
    bad = {**GOOD_LLM, "findings": [{"entity": "topic.T1", "kind": "observation", "text": bad_text}]}
    out = generate_insights(CTX, LLM_ON, llm=llm_returning(*[json.dumps(bad, ensure_ascii=False)] * 2))
    assert out["mode"] == "deterministic" and "отклонён" in out["fallback_reason"]


def test_unknown_entity_falls_back():
    bad = {**GOOD_LLM, "findings": [{"entity": "topic.T99", "kind": "observation", "text": "Тема {{name}} сложная."}]}
    out = generate_insights(CTX, LLM_ON, llm=llm_returning(*[json.dumps(bad, ensure_ascii=False)] * 2))
    assert out["mode"] == "deterministic"


def test_malformed_json_retried_then_succeeds():
    out = generate_insights(CTX, LLM_ON, llm=llm_returning(
        "not json", "```json\n" + json.dumps(GOOD_LLM, ensure_ascii=False) + "\n```"))
    assert out["mode"] == "llm" and out["attempts"] == 2


def test_schema_violation_falls_back():
    out = generate_insights(CTX, LLM_ON, llm=llm_returning(json.dumps({"summary": "x"}), json.dumps({"summary": "x"})))
    assert out["mode"] == "deterministic"


@pytest.mark.parametrize("exc", [httpx.ConnectTimeout("timeout"), httpx.HTTPStatusError(
    "500", request=httpx.Request("POST", "https://example.invalid"), response=httpx.Response(500)), RuntimeError("x")])
def test_provider_failures_fall_back(exc):
    def boom(*a):
        raise exc
    out = generate_insights(CTX, LLM_ON, llm=boom)
    assert out["mode"] == "deterministic" and "недоступен" in out["fallback_reason"]


def test_missing_env_vars_use_safe_defaults(monkeypatch):
    for k in ("LLM_API_KEY", "LLM_PROVIDER", "MAX_UPLOAD_MB", "API_TOKEN", "ENABLE_DATA_RESET", "ADMIN_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    s = Settings(_env_file=None)
    assert s.llm_enabled is False and s.max_upload_mb == 10
    assert s.api_token == "" and s.reset_enabled is False  # local-only mode, reset off
