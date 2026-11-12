"""The live evaluation harness is opt-in. All checks here are offline; no model is called."""
import importlib.util
import json
from pathlib import Path

import httpx
import pytest

SPEC = importlib.util.spec_from_file_location("eval_local_llm", Path(__file__).parents[1] / "scripts/eval_local_llm.py")
ev = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ev)


def no_network(*a, **k):
    pytest.fail("the harness must not make network calls here")


def test_without_live_flag_no_call_is_made(monkeypatch, capsys):
    monkeypatch.setattr(httpx, "post", no_network)
    monkeypatch.setattr(httpx, "get", no_network)
    assert ev.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "not_run"


def test_non_loopback_endpoint_is_refused(monkeypatch):
    monkeypatch.setattr(httpx, "post", no_network)
    monkeypatch.setattr(httpx, "get", no_network)
    assert ev.main(["--live", "--base-url", "https://ollama.com"]) == 2


def test_contexts_cover_required_situations_and_are_internally_consistent():
    names = {n for n, _ in ev.CONTEXTS}
    assert len(ev.CONTEXTS) >= 20
    for required in ("difficult_inconclusive", "confirmed_decline", "insufficient_sample",
                     "no_textbook_winner_few_classes", "hours_proposal", "missing_optional_metrics",
                     "multi_topic_no_mixing"):
        assert required in names
    for _, c in ev.CONTEXTS:
        ev.ai.deterministic_insights(c)  # the same grounding rules hold for every synthetic context


def test_rejection_messages_map_to_categories():
    assert ev.classify(ValueError("finding 0: internal code 'difficult' must be expressed")) == "internal_code"
    assert ev.classify(ValueError("Model output was cut off by the output limit")) == "truncated"
