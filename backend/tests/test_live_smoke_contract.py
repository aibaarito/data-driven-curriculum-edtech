"""All calls are mocked here; this tests the opt-in harness, not live Gemini."""
import importlib.util
import json
from pathlib import Path

import httpx
import pytest

SPEC = importlib.util.spec_from_file_location("smoke_gemini", Path(__file__).parents[1] / "scripts/smoke_gemini.py")
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


def test_no_optin_makes_no_calls_even_with_key():
    result, code = smoke.run_smoke(enabled=False, api_key="fake-private-key",
                                  provider_call=lambda *a: pytest.fail("network must stay disabled"))
    assert code == 0 and result["status"] == "not_run" and result["provider_requests"] == 0


def test_optin_without_key_is_explicitly_blocked():
    result, code = smoke.run_smoke(enabled=True, api_key="")
    assert code == 2 and result["status"] == "blocked" and result["provider_requests"] == 0


def test_validated_llm_success_is_distinct_from_fallback():
    def valid(settings, system, user):
        assert settings.llm_base_url == smoke.GEMINI_BASE
        assert "student_id" not in user
        return json.dumps({"summary": "Проанализировано {{overview.students}} учеников.",
            "findings": [{"entity": "topic.SMOKE", "kind": "observation",
                          "text": "Освоение темы {{name}} — {{mastery}}."}],
            "limitations": ["Данные синтетические."], "next_steps": ["Проверить задания."]})
    result, code = smoke.run_smoke(enabled=True, api_key="fake-private-key", provider_call=valid)
    assert code == 0 and result["status"] == "live_success" and result["mode"] == "llm"
    assert result["provider_requests"] == result["attempts"] == 1
    assert "fake-private-key" not in json.dumps(result)


def test_invalid_output_can_make_no_more_than_two_requests():
    calls = []
    def invalid(*args):
        calls.append(args)
        return "invalid JSON"
    result, code = smoke.run_smoke(enabled=True, api_key="fake-private-key", provider_call=invalid)
    assert len(calls) == result["provider_requests"] == result["attempts"] == 2
    assert code == 3 and result["status"] == "deterministic_fallback" and result["mode"] == "deterministic"


def test_timeout_stops_after_one_request_and_never_logs_credentials(caplog):
    def timeout(*args):
        raise httpx.ReadTimeout("fake-private-key and private provider detail")
    result, code = smoke.run_smoke(enabled=True, api_key="fake-private-key", provider_call=timeout)
    assert code == 3 and result["provider_requests"] == 1
    assert "fake-private-key" not in json.dumps(result) + caplog.text
    assert "private provider detail" not in json.dumps(result) + caplog.text


def test_without_live_flag_private_env_file_is_not_read(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(smoke, "dotenv_values", lambda *a: pytest.fail("must not read private environment"))
    assert smoke.main(["--env-file", str(tmp_path / "private.env")]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "not_run"


@pytest.mark.parametrize("timeout", [0, -1, 31])
def test_timeout_cannot_be_unbounded(timeout):
    result, code = smoke.run_smoke(enabled=True, api_key="fake-private-key", timeout=timeout)
    assert code == 2 and result["provider_requests"] == 0
