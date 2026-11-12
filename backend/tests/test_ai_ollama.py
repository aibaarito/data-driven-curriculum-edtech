"""Local Ollama provider (Qwen3-8B). Every HTTP call is MOCKED: these tests need no Ollama, model or network."""
import json
import logging

import httpx
import pytest

from app.config import Settings
from app.services import ai
from app.services.ai import (
    LLMPayload,
    ProviderError,
    call_ollama,
    generate_insights,
    llm_json_schema,
)
from tests.test_ai import CTX, GOOD_LLM

OLLAMA = Settings(_env_file=None, llm_provider="ollama", llm_model="qwen3:8b",
                  llm_base_url="http://127.0.0.1:11434/v1", llm_api_key="", llm_timeout_seconds=90)
GOOD = json.dumps(GOOD_LLM, ensure_ascii=False)


def ollama_reply(content, done_reason="stop", thinking=None, status=200):
    message = {"role": "assistant", "content": content}
    if thinking is not None:
        message["thinking"] = thinking
    return httpx.Response(status, json={"model": "qwen3:8b", "message": message, "done": True,
                                        "done_reason": done_reason},
                          request=httpx.Request("POST", "http://127.0.0.1:11434/api/chat"))


@pytest.fixture
def fake_post(monkeypatch):
    """Queue responses (or exceptions) returned by httpx.post; record every request."""
    calls, queue = [], []

    def post(url, **kw):
        calls.append({"url": url, **kw})
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(ai.httpx, "post", post)
    return calls, queue


# ------------------------------------------------------------------ configuration and request construction


def test_ollama_needs_no_api_key_and_other_providers_still_do():
    assert OLLAMA.llm_enabled
    assert not Settings(_env_file=None, llm_provider="openai_compatible", llm_api_key="").llm_enabled
    assert Settings(_env_file=None, llm_provider="openai_compatible", llm_api_key="k").llm_enabled
    assert not Settings(_env_file=None, llm_provider="none", llm_api_key="k").llm_enabled


def test_request_targets_local_native_chat_with_model_think_off_schema_and_limits(fake_post):
    calls, queue = fake_post
    queue.append(ollama_reply(GOOD))
    out = generate_insights(CTX, OLLAMA)
    assert out["mode"] == "llm" and out["provider"] == "ollama" and out["model"] == "qwen3:8b"
    req = calls[0]
    assert req["url"] == "http://127.0.0.1:11434/api/chat"  # the /v1 suffix is tolerated, native API used
    body = req["json"]
    assert body["model"] == "qwen3:8b" and body["stream"] is False
    assert body["think"] is False                       # documented Ollama thinking control, not a prompt hint
    assert body["format"] == LLMPayload.model_json_schema()  # schema comes from the validating Pydantic model
    assert body["options"]["num_ctx"] == OLLAMA.llm_context_tokens
    assert body["options"]["num_predict"] == OLLAMA.llm_max_output_tokens
    assert body["options"]["temperature"] == 0.7 and body["options"]["top_p"] == 0.8
    assert body["keep_alive"] == "10m"
    assert "authorization" not in {k.lower() for k in (req.get("headers") or {})}
    assert req["timeout"] <= 90


def test_schema_is_generated_not_handwritten():
    schema = llm_json_schema()
    assert schema == LLMPayload.model_json_schema()
    assert set(schema["required"]) >= {"summary", "findings"}


def test_only_aggregate_facts_are_sent(fake_post):
    calls, queue = fake_post
    queue.append(ollama_reply(GOOD))
    generate_insights(CTX, OLLAMA)
    sent = json.dumps(calls[0]["json"]["messages"], ensure_ascii=False)
    assert "FACTS = " in sent and "student_id" not in sent and "external_id" not in sent


# ------------------------------------------------------------------ accepted and rejected output


def test_valid_russian_response_passes_schema_and_grounding(fake_post):
    calls, queue = fake_post
    queue.append(ollama_reply(GOOD))
    out = generate_insights(CTX, OLLAMA)
    assert out["mode"] == "llm" and out["attempts"] == 1 and out["fallback_kind"] is None
    text = out["payload"]["findings"][0]["text"]
    assert "«Дроби»" in text and "42.5%" in text


def test_thinking_field_is_ignored_and_leading_think_block_is_stripped(fake_post):
    calls, queue = fake_post
    queue.append(ollama_reply("<think>\n\n</think>\n\n" + GOOD, thinking="private reasoning with 99.9"))
    out = generate_insights(CTX, OLLAMA)
    assert out["mode"] == "llm"
    assert "private reasoning" not in json.dumps(out, ensure_ascii=False)


def test_stray_reasoning_tags_are_rejected(fake_post):
    calls, queue = fake_post
    queue += [ollama_reply(GOOD + "</think>"), ollama_reply("<think>x</think><think>y</think>" + GOOD)]
    out = generate_insights(CTX, OLLAMA)
    assert out["mode"] == "deterministic" and out["fallback_kind"] == "rejected" and out["attempts"] == 2


@pytest.mark.parametrize("bad_text, why", [
    ("Освоение темы {{name}} — 42,5%.", "digit outside a placeholder"),
    ("Освоение темы {{name}} — {{secret_metric}}.", "unknown placeholder"),
    ("Тема Дроби освоена на {{mastery}}.", "literal entity name"),
])
def test_invented_numbers_unknown_placeholders_and_literal_names_are_rejected(fake_post, bad_text, why):
    calls, queue = fake_post
    bad = {**GOOD_LLM, "findings": [{"entity": "topic.T1", "kind": "observation", "text": bad_text}]}
    queue += [ollama_reply(json.dumps(bad, ensure_ascii=False))] * 2
    out = generate_insights(CTX, OLLAMA)
    assert out["mode"] == "deterministic" and out["fallback_kind"] == "rejected", why


def test_finding_for_an_unknown_entity_is_rejected(fake_post):
    """Placeholders resolve against the finding's own entity, so an entity absent from FACTS has nothing to borrow."""
    calls, queue = fake_post
    bad = {**GOOD_LLM, "findings": [{"entity": "topic.T9", "kind": "observation", "text": "Освоение {{mastery}}."}]}
    queue += [ollama_reply(json.dumps(bad, ensure_ascii=False))] * 2
    out = generate_insights(CTX, OLLAMA)
    assert out["fallback_kind"] == "rejected"


@pytest.mark.parametrize("entity, text", [
    ("topic.T1", "Освоение темы {{name}} — {{mastery}}; это приведёт к улучшению при добавлении часов."),
    ("topic.T3", "По теме {{name}} наблюдается прогресс: изменение {{gain}}."),          # decline described as progress
    ("topic.T1", "По теме {{name}} значимый прирост {{gain}}."),                          # inconclusive as significant
    ("comparison.0", "Учебник {{name_a}} лучше, его результаты выше."),                   # insufficient evidence
])
def test_causal_claims_wrong_direction_and_unsupported_winner_are_rejected(fake_post, entity, text):
    calls, queue = fake_post
    bad = {**GOOD_LLM, "findings": [{"entity": entity, "kind": "observation", "text": text}]}
    queue += [ollama_reply(json.dumps(bad, ensure_ascii=False))] * 2
    out = generate_insights(CTX, OLLAMA)
    assert out["mode"] == "deterministic" and out["fallback_kind"] == "rejected"


def test_invalid_first_answer_then_valid_retry_with_same_facts(fake_post):
    calls, queue = fake_post
    queue += [ollama_reply("{\"summary\": \"x\"}"), ollama_reply(GOOD)]
    out = generate_insights(CTX, OLLAMA)
    assert out["mode"] == "llm" and out["attempts"] == 2 and len(calls) == 2
    first, second = (c["json"]["messages"][1]["content"] for c in calls)
    assert second.startswith(first) and "Предыдущий ответ отклонён проверкой" in second  # facts unchanged


def test_repeated_invalid_output_falls_back_after_two_attempts(fake_post):
    calls, queue = fake_post
    queue += [ollama_reply("not json"), ollama_reply("still not json")]
    out = generate_insights(CTX, OLLAMA)
    assert out["mode"] == "deterministic" and out["model"] is None and out["attempts"] == 2 == len(calls)
    assert out["fallback_kind"] == "rejected" and "отклонён" in out["fallback_reason"]
    assert out["payload"]["findings"]  # deterministic explanations remain usable


@pytest.mark.parametrize("reply", [
    ollama_reply(""),                                            # empty content
    ollama_reply(GOOD[: len(GOOD) // 2], done_reason="length"),  # cut off by num_predict
    httpx.Response(200, text="<html>proxy</html>", request=httpx.Request("POST", "http://x")),  # not JSON
    httpx.Response(200, json={"done": True}, request=httpx.Request("POST", "http://x")),       # no message
])
def test_empty_truncated_and_malformed_envelopes_are_rejected(fake_post, reply):
    calls, queue = fake_post
    queue += [reply, reply]
    out = generate_insights(CTX, OLLAMA)
    assert out["mode"] == "deterministic" and out["fallback_kind"] == "rejected" and out["attempts"] == 2


# ------------------------------------------------------------------ provider failures


@pytest.mark.parametrize("failure, kind, phrase", [
    (httpx.ConnectError("connection refused"), "unavailable", "недоступен"),
    (httpx.ReadTimeout("slow"), "timeout", "не ответила за отведённое время"),
    (httpx.Response(404, json={"error": "model 'qwen3:8b' not found"},
                    request=httpx.Request("POST", "http://x")), "model_missing", "qwen3:8b не установлена"),
    (httpx.Response(500, json={"error": "llama runner process has terminated: secret detail"},
                    request=httpx.Request("POST", "http://x")), "provider_error", "вернул ошибку"),
])
def test_service_down_model_missing_timeout_and_server_error_fall_back_once(fake_post, caplog, failure, kind, phrase):
    calls, queue = fake_post
    queue.append(failure)
    with caplog.at_level(logging.INFO):
        out = generate_insights(CTX, OLLAMA)
    assert out["mode"] == "deterministic" and out["fallback_kind"] == kind and out["attempts"] == 1 == len(calls)
    assert phrase in out["fallback_reason"]
    assert out["fallback_detail"] == "ProviderError"  # technical detail is a class name, never provider text
    leaked = json.dumps(out, ensure_ascii=False) + caplog.text
    assert "secret detail" not in leaked and "connection refused" not in leaked


def test_primary_messages_have_no_exception_names():
    for kind, msg in ai.FALLBACK_MESSAGES.items():
        assert "Error" not in msg and "Exception" not in msg, kind


def test_call_ollama_classifies_errors_directly(monkeypatch):
    monkeypatch.setattr(ai.httpx, "post", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("x")))
    with pytest.raises(ProviderError) as e:
        call_ollama(OLLAMA, "s", "u")
    assert e.value.kind == "unavailable"


def test_total_deadline_bounds_the_retry(monkeypatch):
    """A slow rejected first attempt must not start a second call past the overall deadline."""
    clock = iter([0.0, 0.0, 200.0, 200.0, 200.0])
    monkeypatch.setattr(ai.time, "monotonic", lambda: next(clock, 200.0))
    calls = []

    def slow_invalid(settings, system, user):
        calls.append(settings.llm_timeout_seconds)
        return "not json"

    out = generate_insights(CTX, OLLAMA.model_copy(update={"llm_total_timeout_seconds": 100}), llm=slow_invalid)
    assert len(calls) == 1 and calls[0] <= 90 and out["mode"] == "deterministic"


def test_concurrent_request_falls_back_instead_of_queuing(fake_post):
    slot = ai._llm_slot(1)
    assert slot.acquire(timeout=0)
    try:
        out = generate_insights(CTX, OLLAMA)
    finally:
        slot.release()
    assert out["mode"] == "deterministic" and out["fallback_kind"] == "busy" and out["attempts"] == 0
    assert fake_post[0] == []  # no model call was made


def test_oversized_facts_are_not_truncated_but_fall_back(fake_post):
    out = generate_insights(CTX, OLLAMA.model_copy(update={"llm_max_input_chars": 100}))
    assert out["fallback_kind"] == "too_large" and out["attempts"] == 0 and fake_post[0] == []


def test_ollama_does_not_need_or_send_any_gemini_key(fake_post, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "fake-gemini-key")
    calls, queue = fake_post
    queue.append(ollama_reply(GOOD))
    s = OLLAMA.model_copy(update={"llm_api_key": "fake-gemini-key"})
    out = generate_insights(CTX, s)
    assert out["mode"] == "llm"
    assert "fake-gemini-key" not in json.dumps(calls, ensure_ascii=False, default=str)


@pytest.mark.parametrize("text", [
    "Тема {{name}} в статусе difficult, освоение {{mastery}}.",
    "Изменение {{gain}} — inconclusive.",
    "Статус темы {{name}}: {{status}}.",        # a code placeholder renders to the raw code
])
def test_internal_codes_in_prose_are_rejected(fake_post, text):
    """Found in the first live Qwen3-8B answer: codes such as 'difficult' leaked into Russian text."""
    calls, queue = fake_post
    bad = {**GOOD_LLM, "findings": [{"entity": "topic.T1", "kind": "observation", "text": text}]}
    queue += [ollama_reply(json.dumps(bad, ensure_ascii=False))] * 2
    out = generate_insights(CTX, OLLAMA)
    assert out["mode"] == "deterministic" and out["fallback_kind"] == "rejected"


def test_internal_code_check_does_not_touch_placeholders_or_russian_words(fake_post):
    calls, queue = fake_post
    ok = {**GOOD_LLM, "findings": [{"entity": "topic.T1", "kind": "observation",
          "text": "Тема {{name}} трудная: освоение {{mastery}}, изменение {{gain}} не установлено."}]}
    queue.append(ollama_reply(json.dumps(ok, ensure_ascii=False)))
    assert generate_insights(CTX, OLLAMA)["mode"] == "llm"


def test_placeholder_qualified_with_own_entity_is_the_same_value(fake_post):
    """Seen live: Qwen3-8B writes {{topic.T1.mastery}}. Inside a topic.T1 finding this is the same fact."""
    calls, queue = fake_post
    ok = {**GOOD_LLM, "findings": [{"entity": "topic.T1", "kind": "observation",
          "text": "Тема {{topic.T1.name}}: освоение {{topic.T1.mastery}}."}]}
    queue.append(ollama_reply(json.dumps(ok, ensure_ascii=False)))
    out = generate_insights(CTX, OLLAMA)
    assert out["mode"] == "llm" and "«Дроби»: освоение 42.5%" in out["payload"]["findings"][0]["text"]


@pytest.mark.parametrize("where, item", [
    ("findings", {"entity": "topic.T1", "kind": "observation", "text": "Освоение {{topic.T2.mastery}}."}),
    ("summary", "Тема {{topic.T1.name}} трудная."),
    ("summary", "Тема {{name}} трудная."),
])
def test_other_entity_qualified_placeholders_and_names_outside_findings_stay_rejected(fake_post, where, item):
    calls, queue = fake_post
    bad = {**GOOD_LLM, **({"findings": [item]} if where == "findings" else {"summary": item})}
    queue += [ollama_reply(json.dumps(bad, ensure_ascii=False))] * 2
    assert generate_insights(CTX, OLLAMA)["fallback_kind"] == "rejected"


def test_placeholder_map_lists_own_metrics_without_internal_codes():
    m = ai.placeholder_map(ai.build_facts(CTX))
    assert "mastery" in m["topic.T1"] and "gain" in m["topic.T1"]
    assert "status" not in m["topic.T1"] and "gain_direction" not in m["topic.T1"]
    assert "verdict" not in m["comparison.0"]
    assert "overview.students" in m["SHARED"]
