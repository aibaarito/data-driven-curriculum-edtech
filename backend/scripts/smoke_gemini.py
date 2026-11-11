"""Opt-in, database-free Gemini check using synthetic aggregate facts only.

No default test/CI dependency on external availability. No credentials or provider prose are printed.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.services import ai  # noqa: E402
from app.services.settings_store import AnalysisSettings  # noqa: E402

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"


def synthetic_context() -> dict:
    return {
        "overview": {"students": 40, "assessments": 2, "classes": 3, "topics": 1, "textbooks": 0,
                     "average_mastery": 42.5},
        "settings": AnalysisSettings().model_dump(),
        "topics": [{"code": "SMOKE", "name": "Дроби", "mastery": 42.5, "median": 40.0,
                    "student_count": 40, "status": "difficult", "hours": 6.0, "gain": None,
                    "interpretation": "Низкий результат; нет входной диагностики."}],
        "textbooks": {"textbooks": [], "pairs": []}, "optimizer": None,
    }


def run_smoke(*, enabled: bool, api_key: str, model: str = "gemini-3.8-flash",
              timeout: float = 20, provider_call=None) -> tuple[dict, int]:
    if not enabled:
        return {"status": "not_run", "reason": "explicit --live flag required", "provider_requests": 0}, 0
    if not api_key.strip():
        return {"status": "blocked", "reason": "private LLM_API_KEY unavailable", "provider_requests": 0}, 2
    if not 0 < timeout <= 30:
        return {"status": "blocked", "reason": "timeout must be in (0, 30] seconds", "provider_requests": 0}, 2
    settings = Settings(_env_file=None, llm_provider="openai_compatible", llm_api_key=api_key,
                        llm_base_url=GEMINI_BASE, llm_model=model, llm_timeout_seconds=timeout)
    calls = 0
    def bounded_call(*args):
        nonlocal calls
        if calls >= 2:
            raise RuntimeError("Provider request budget exhausted")
        calls += 1
        return (provider_call or ai.call_llm)(*args)
    started = time.monotonic()
    result = ai.generate_insights(synthetic_context(), settings, llm=bounded_call)
    success = result["mode"] == "llm" and bool(result["payload"]["findings"])
    report = {"status": "live_success" if success else "deterministic_fallback", "mode": result["mode"],
              "model": result["model"], "provider_requests": calls, "attempts": result["attempts"],
              "validated_findings": len(result["payload"]["findings"]),
              "fallback_reason": result["fallback_reason"], "elapsed_seconds": round(time.monotonic() - started, 2),
              "input": "synthetic aggregate facts; no database accessed"}
    return report, 0 if success else 3


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="explicitly permit up to two Gemini requests")
    parser.add_argument("--env-file", type=Path, help="optional private environment file; never echoed")
    parser.add_argument("--timeout", type=float, default=20, help="per-request timeout, maximum 30 seconds")
    parser.add_argument("--output", type=Path, help="optional sanitized JSON result")
    args = parser.parse_args(argv)
    # Do not even read private files without opt-in.
    config = ({k: v for k, v in dotenv_values(args.env_file).items() if v is not None}
              if args.live and args.env_file else {})
    config.update(os.environ)
    report, code = run_smoke(enabled=args.live, api_key=config.get("LLM_API_KEY", ""),
                             model=config.get("LLM_MODEL", "gemini-3.8-flash"), timeout=args.timeout)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n")
    print(rendered)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
