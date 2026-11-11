"""Startup configuration and process ownership checks without touching live services."""
import importlib.util
import os
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("local_services", Path(__file__).parents[1] / "scripts/local_services.py")
local = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(local)


def test_frontend_gets_matching_private_token_and_only_server_api_url(tmp_path, monkeypatch):
    (tmp_path / "backend").mkdir()
    marker = tmp_path / "must-not-be-created"
    (tmp_path / "backend/.env").write_text(
        'API_TOKEN="private-test-token"\nLLM_API_KEY=private-llm-key\nADMIN_TOKEN=private-admin-token\n'
        'DATABASE_URL=private-db-url\nDEMO_BASIC_AUTH_USER=judge\nDEMO_BASIC_AUTH_PASSWORD=private-basic\n'
        f'LLM_MODEL=$(touch {marker})\n')
    monkeypatch.delenv("API_TOKEN", raising=False)
    env = local.runtime_env(tmp_path)
    front = local.frontend_env(env, 8012)
    assert front["API_TOKEN"] == "private-test-token"
    assert front["API_URL"] == "http://127.0.0.1:8012"
    assert front["DEMO_BASIC_AUTH_PASSWORD"] == "private-basic"
    assert not any(k in front for k in ("LLM_API_KEY", "DATABASE_URL", "ADMIN_TOKEN"))
    assert not marker.exists()  # .env was parsed, never evaluated by a shell
    monkeypatch.setenv("API_TOKEN", "process-override")
    assert local.runtime_env(tmp_path)["API_TOKEN"] == "process-override"


def test_stop_never_signals_reused_pid(monkeypatch):
    monkeypatch.setattr(local, "identity", lambda pid: "different-process")
    calls = []
    monkeypatch.setattr(os, "kill", lambda *args: calls.append(args))
    local.stop_owned([{"pid": 123, "identity": "our-former-process"}])
    assert calls == []


def test_stop_signals_only_owned_process(monkeypatch):
    monkeypatch.setattr(local, "identity", lambda pid: "matching-start-time-and-command")
    calls = []
    monkeypatch.setattr(os, "kill", lambda *args: calls.append(args))
    local.stop_owned([{"pid": 123, "identity": "matching-start-time-and-command"}])
    assert calls == [(123, local.signal.SIGTERM)]


def test_process_identity_ignores_mutable_nextjs_process_title(monkeypatch):
    calls = []
    def run(cmd, **kwargs):
        calls.append(cmd)
        return type("Result", (), {"returncode": 0, "stdout": "Wed Nov 11 12:00:00 2026 501\n"})()
    monkeypatch.setattr(local.subprocess, "run", run)
    assert local.identity(123) == "Wed Nov 11 12:00:00 2026 501"
    assert "command=" not in calls[0] and "lstart=" in calls[0] and "uid=" in calls[0]


def test_start_refuses_existing_state_before_any_command(tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    state.write_text("[]")
    monkeypatch.setattr(local, "STATE", state)
    monkeypatch.setattr(local.subprocess, "run", lambda *a, **kw: pytest.fail("must not start a service"))
    with pytest.raises(RuntimeError, match="state exists"):
        local.start(8012, 3012)


@pytest.mark.parametrize("url", [None, "", "invalid-private-secret", "sqlite:///ddc_test",
    "postgresql://user:secret@localhost/ddc_e2e", "postgresql://user:secret@localhost/ddc_e2e?application_name=_test"])
def test_database_guard_rejects_implicit_or_unsafe_targets(url):
    from tests.db_safety import require_test_url
    with pytest.raises(RuntimeError) as exc:
        require_test_url(url)
    assert "secret" not in str(exc.value)


def test_database_guard_checks_database_name_instead_of_url_suffix():
    from tests.db_safety import require_test_url
    url = "postgresql+psycopg://user:secret@localhost/verification_test?application_name=pytest"
    assert require_test_url(url) == url
