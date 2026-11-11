# Pre-defense smoke checklist

Use the prepared synthetic demonstration. The verified working copy is at `http://127.0.0.1:3011`; the preserved
original is at 3010. Know which one you are showing. Do not run resets or re-import tests on the original `ddc_e2e`.

1. **Before leaving a network connection:** complete the production build (cold builds fetch Google Fonts), start
   the intended stack and confirm `/api/health` reports database access. Check Settings for the actual AI mode.
2. **Overview:** synthetic-data badge is visible; the complete demo has 199 students and eight assessments. Confirm
   you have cleared unintended filters before citing the 67.4% whole-demo mastery figure.
3. **Topics, grade 7:** show the two difficult topics. Explain the difference between a low-but-improving result and
   a change that is not established; inconclusive does not mean “no effect.”
4. **Textbooks:** grade 7 has six classes and an explicitly exploratory association; grade 8 has insufficient
   class-level evidence. Explain that teachers/classes are not randomized and this is not a causal verdict.
5. **Hours:** inspect the 82-hour plan and its recorded decision. On the separate rehearsal stack, verify an
   infeasible request and explicit policy relaxation if showing these controls. Do not imply guaranteed gains.
6. **Explanations:** the result's badge must match `llm` versus deterministic fallback. Prepare deterministic mode
   and current screenshots as the network-independent fallback. Allow for the handoff's approximately 27-second
   live response; that is one observation, not an SLA.
7. **Report:** open a saved scoped report; download the PDF and check synthetic label, class/grade, plan scope and
   readable Cyrillic. Avoid presenting the confidence interval from a different filter scope.
8. **Presentation claim check:** say what was tested, what remains unverified, and that real-student-data use needs
   additional access, privacy and operational controls. No public deployment or external-API rules approval is assumed.

The actual live-provider smoke test is optional and separate from default verification. Only after explicitly choosing
to permit up to two provider requests, run from `backend/` with a securely stored key in your own private file:

```bash
python scripts/smoke_gemini.py --live --env-file /absolute/path/to/private/gemini.env \
  --timeout 20 --output ../verification/live-smoke.json
```

Do not paste the key in chat, put it literally in a command, or use source control for that file. The script accesses no
database and uses synthetic aggregate facts. Default execution without `--live` makes zero calls, even if a key exists.
Exit 0 with `status=live_success` means validated LLM output; exit 3 means deterministic fallback, and exit 2 means the
key/timeout precondition blocked execution. Read `mode`, `provider_requests`, `attempts` and `fallback_reason`; HTTP 200
alone does not demonstrate a successful Gemini explanation. Requests are capped at two, including retries, with a
per-request timeout of at most 30 seconds. This verification run did not enable a real provider call.
