# Local Qwen3-8B integration — 12 November 2026 (Linux cloud container, CPU only)

Scope: the `ollama` provider (`backend/app/services/ai.py`) with **Qwen3-8B** served by **Ollama 0.40.16** on
`127.0.0.1:11434` (`OLLAMA_NO_CLOUD=1`, log: `Ollama cloud disabled: true`; `OLLAMA_NUM_PARALLEL=1`,
`OLLAMA_MAX_LOADED_MODELS=1`). Model `qwen3:8b`: qwen3, 8.2B parameters, GGUF **Q4_K_M**, 5.2 GB download,
thinking values `[false, true]`. Request: native `/api/chat`, `think: false`, `format` = JSON Schema of `LLMPayload`,
temperature 0.7, top_p 0.8, top_k 20, min_p 0. Host: 4 logical CPUs, no GPU, 16 GB RAM, no swap. This is **not**
the user's Apple M4; latency on Apple silicon with Metal is expected to be much lower but was not measured.

**Automated checks (mocked provider; no Ollama, model or network needed)**

| Check | Result |
|---|---|
| Backend `pytest`, fresh `ddc_verify_test` | **329 passed**, 1 skipped (IPv6 dual-stack test) |
| of which `tests/test_ai_ollama.py` + eval-harness contract | 44 + 4 passed |
| Frontend Vitest (incl. new `mode-view.test.ts`) | **78 passed** |
| `npm run typecheck`, ESLint, `next build` | passed |
| Playwright, isolated stack 8011/3011, template mode as in CI | **19 / 19 passed** |

**Live evaluation** (`scripts/eval_local_llm.py --live`, 22 synthetic contexts, per-call timeout 420 s,
`num_ctx 8192`, `num_predict 2048`; summary in [verification/local-llm-eval.json](../verification/local-llm-eval.json))

| Measure | Result |
|---|---|
| Accepted on the first attempt | **2 / 22** |
| Accepted after the one permitted retry | **4 / 22** |
| Deterministic fallback (both answers rejected) | **16 / 22** |
| Rejections per model call (42 calls) | unknown placeholder 12 · `{{name}}` outside findings 7 · unknown entity 6 · literal topic name 6 · internal code in prose 5 |
| Cold first call / warm calls | 155 s / median 133 s (min 70, max 281) |
| Memory with the model loaded (`num_ctx 8192`) | `llama-server` RSS 8,468 MB (weights 4,730 + 335 MiB, KV cache 1,152 MiB, compute 240 MiB); no swap |
| Crashes / provider errors | none |

Every rejection was a real rule violation (checked from the recorded messages); no validator rule was relaxed.
**Manual review of the 6 accepted answers:** 2 fully sound (`difficult_inconclusive`, `multi_topic_no_mixing`);
4 with at least one misleading statement the validator cannot see — topic mastery called "общее освоение",
invented hour recommendations for topics in good shape, a duplicated unit ("8 ч часов") and a false comparison
("Количество учеников 60 не достигает порога 10"). Values were always bound to the right entity.
The memory sampler in the script missed the `llama-server` process during the run; the figure above was measured
with `ps` immediately afterwards, and the script is fixed. Two earlier prompt versions were evaluated partly
(1/13 and 2/5 accepted); their failures led to the placeholder lists and the worked example now in the prompt.

**Application check** (isolated backend 8011 + production frontend 3011, synthetic demo database
`ddc_browser_test`, `LLM_PROVIDER=ollama`, no `LLM_API_KEY` set, per-call 270 s, total 280 s)

| Scope / test | Result |
|---|---|
| Settings API | `{"enabled": true, "provider": "ollama", "model": "qwen3:8b"}` |
| Математика · 7 класс (prompt 4,479 tokens), 3 tries | 3 × template fallback labelled «Модель не ответила вовремя»: one timeout; twice the first answer (≈260 s) was rejected and no time was left for the retry |
| Математика · 8 класс, 2 tries | try 1 timeout fallback; **try 2 accepted on the first call in 251 s**, labelled «Пояснения написала локальная модель qwen3:8b (Ollama, на этом компьютере)». Checked against the facts: mastery and change values on the right topics, increases described as significant increases, textbook comparison reported as insufficient evidence with no winner. Cosmetic: "п.п.." |
| Loading state | shows the selected group and elapsed time while waiting |
| Ollama unreachable (backend pointed at a closed port) | template fallback, `fallback_kind=unavailable`, page title «Локальная модель недоступна — показаны пояснения по шаблонам» |
| Model not installed (`qwen3:not-installed`) | template fallback after 1 attempt, `model_missing`, message names the model |
| Logs | only the failure kind and timings, no provider text or keys |

**Defects found and fixed during this check**
1. The Next.js proxy (Node `fetch`) stops waiting for response headers after 300 s; with an 840 s backend budget
   the page showed "server unavailable" instead of the template fallback. The total model budget is now capped at
   280 s (`LLM_TOTAL_TIMEOUT_CAP`), so the backend always answers first.
2. The real all-grades prompt (≈14,400 characters) plus the output could exceed `num_ctx 8192`, and Ollama would
   silently drop part of the prompt. Default `num_ctx` is now 12,288, and a prompt that may not fit (estimated
   conservatively at 2 characters per token; measured ≈2.3) uses templates (`too_large`).

**Conclusion.** The integration works end to end and the fallback is truthful in every failure mode tested. On this
CPU-only host, Qwen3-8B is too slow and too unreliable with the placeholder protocol for an unattended
demonstration: most requests end in template explanations, and accepted text still needs a human check. Not
verified: latency and acceptance on the Apple M4, `OLLAMA_NO_CLOUD` through the macOS app, Qwen3-4B (not
downloaded, as agreed).

---

# Post-merge verification of `main` — 12 November 2026 (Linux cloud container)

Scope: `main` after merging `claude/sharp-noether-oeabba` (Decision Intelligence 2.0 + CI) on top of
`16aba37` (Railway readiness). Everything below was run in this session on a disposable PostgreSQL 16 cluster
(trust auth, loopback, port 55440); no demo database or demo port was touched. LLM key empty (deterministic mode).

| Check | Result |
|---|---|
| Backend `pytest`, fresh `ddc_verify_test` | **283 passed**, 1 skipped (`test_railway_deployment.py`: host lacks dual-stack IPv6) |
| Frontend unit (Vitest) | **70 passed** (9 files) |
| `npm run typecheck`, ESLint (src, e2e, config) | passed |
| `next build` | passed (11 product pages, API proxy, health route) |
| Playwright, isolated stack 8011/3011, `ddc_browser_test`, preinstalled Chromium | **19 / 19 passed** |
| Alembic on empty databases | `d85f0598c8c6 → 6129d2b374e8 → b7c1d2e3f4a5` (linear history) |
| README quick start, fresh `ddc_quickstart`, ports 8010/3010 | migrations applied; `/api/health` ok; synthetic demo CSV previewed (199 students, 0 errors) and committed through the proxy (15 830 rows); UI responded 200 |

Counts grew relative to the branch record below because the merged tree also contains the Railway regression
tests from `main` (`test_railway_deployment.py`, `readiness.test.ts`, extra proxy tests), which the branch
record predates. Not verified: Docker images, live Gemini, macOS `dev.sh`, real data.

---

# Decision Intelligence 2.0 verification — 11 November 2026 (Linux cloud container)

Branch `claude/sharp-noether-oeabba`, built on `main@a0a2edb`. Everything below was run in this session. The
earlier macOS report follows unchanged.

**Isolation.** The demo database `ddc_e2e` and ports 3010/8010/55433 do not exist in this container and were never
targeted. A disposable PostgreSQL **16** cluster was used: trust auth, loopback only, port **55434**, databases
`ddc_verification_test` (pytest) and `ddc_browser_test` (browser stack on 8011/3011). Tokens were generated per
run in a private mode-0600 file outside the repository. LLM key empty: deterministic explainer mode throughout.

| Check | Result |
|---|---|
| Baseline before changes (backend / frontend unit / typecheck / ESLint) | 244 passed / 59 passed / pass / pass |
| Backend after changes (`pytest`, 33 more than the baseline, all in `test_decision_intelligence.py`) | **277 passed** |
| Migration: upgrade from empty schema, downgrade both revisions, upgrade again | passed (`test_migrations_are_reversible_on_disposable_database`) |
| Frontend unit (Vitest) | **63 passed** |
| `npm run typecheck`, ESLint (src, e2e, config) | passed, no findings |
| Production build (`next build`) | passed; 11 product pages + API proxy |
| Playwright, Chromium (preinstalled build via `E2E_CHROMIUM_PATH`), fresh production build | **19 / 19 passed** (16 existing + 3 new decision scenarios) |
| PDF export in browser journey | 4-page PDF produced |
| Access log | one JSON line per request (id, route template, status, ms); fixed-string search of the backend log found 0 student IDs, 0 `Bearer`, 0 API/admin token occurrences |

New negative cases covered by automated tests: cyclic prerequisite (import and API), missing topic, self-edge,
duplicate edge, cross-subject edge, insufficient evidence, incomparable textbook comparison, hard infeasibility and
policy infeasibility per scenario, stale scenario save, idempotent retry and key conflict, stale recommendation
acceptance, invalid lifecycle transitions (create from rejected/proposed run, skipping steps, future dates,
cancelling an evaluated intervention), cross-scope passport request, request-ID sanitisation. Existing tests
already covered invalid datasets, duplicate imports, provider timeout/429/500, a missing database (503) and
stale asynchronous UI responses. All of these still pass.

**Defects found and fixed during this work:**
1. `alembic/env.py` called `fileConfig()` with the default `disable_existing_loggers=True`. Running migrations
   in-process silenced the application's loggers. Now `False`.
2. The importer accepted cyclic prerequisites. Now rejected with `CYCLIC_PREREQUISITE` and the cycle path.

**Not verified here:**
* Docker images (not run).
* Live Gemini calls (none made).
* macOS `dev.sh` startup.
* Real school data.
* Performance beyond the synthetic dataset. The decision overview recomputes analytics plus 3 optimizer runs per
  request, about 0.4–0.6 s locally.

---

# Independent functional verification — 11 November 2026

## Outcome and scope

The existing application was continued in `data-driven-curriculum-mvp/` under the EDTECH 2 workspace. No replacement
application was created. All 146 file hashes in the supplied `SOURCE_MANIFEST.json` matched before edits. That manifest
and `PROJECT_HANDOFF.md` are retained as historical provenance; this report describes the subsequent working copy.
The original scratch workspace, its private configuration and its Git working tree were not edited.

**Hackathon — ready with specified limitations:** the local synthetic-data workflow is functionally ready on the verified macOS setup, with a prepared
production build and a deterministic explanation fallback. This is conditional on the actual judging environment;
Docker, public hosting and sustained Gemini reliability have not been certified. **Real student data:** not ready.

## Isolation and preservation

| Purpose | Database | PostgreSQL port | Backend | Frontend |
|---|---|---:|---:|---:|
| Existing demonstration — preserved | `ddc_e2e` | 55433 | 8010 | 3010 |
| Backend tests — fresh, disposable | `ddc_verification_test` | **55434** | In-process TestClient | — |
| Production-browser verification — fresh | `ddc_browser_test` | **55434** | **8011** | **3011** |

The verification PostgreSQL has its own data directory at `verification/pgdata`, listens on loopback, and uses a
local-only trust-authenticated verification role. It is a disposable local test service, not a production setup.
All schema drops, truncation and API resets targeted only the two new databases. The original database was not
migrated, reset, imported into or repaired. Read-only before/after snapshots of the original frontend's metadata and
analytical overview matched exactly. Its integrity endpoint returned `ok=true`, with all six reported issue counts zero.
This is an application-level comparison, not a byte-for-byte backup or a certification of historical database `ddc`.

Test tokens were generated locally. No original API/admin token or Gemini key was copied. Private test environment
files have mode 0600 and are ignored by Git. The frontend was also restarted with tokens absent from the process
environment: reading this copy's private `backend/.env` alone produced a working authenticated proxy.

## Actual results

Git includes the compact sanitized JSON evidence and final backend JUnit XML. Raw logs, environment files,
database storage, browser captures and other runtime artifacts remain local and ignored; artifact paths below
refer to the verification working copy when those files are not published.

| Check | Result | Evidence under `verification/` |
|---|---|---|
| Original backend baseline | 148 passed | `backend-baseline.log`, `backend-baseline.xml` |
| Expanded backend suite | 238 passed | `backend-final.log`, `backend-final.xml` |
| API method/route reachability | 28/28 exercised | `route-coverage.json` |
| Original frontend baseline | 22 passed | `frontend-baseline.log` |
| Expanded frontend unit suite | 38 passed, four files | `frontend-final.log` |
| TypeScript, including clean route type generation | Passed | `typecheck-final.log` |
| ESLint on source, E2E and Playwright config | Passed | `lint-final.log` (empty means no findings) |
| Production Next.js build | Passed; all eight product pages plus API proxy | `build.log`, `startup-private-env.log` |
| Chromium production journey | Eight unique scenarios passed | `e2e.log` |
| Browser stability repetitions | 16/16 passed (the same eight scenarios twice) | `e2e-repeat.log` |
| Migration upgrade from empty schema; downgrade/upgrade latest migration | Passed in backend suite | `test_migrations_are_reversible_on_disposable_database` |
| Startup, owned-process stop, restart and private-file token propagation | Passed; data persisted | `startup-first.log`, `startup-restart.log`, `startup-private-env.log`, `stop.log` |
| PDF | Fresh four-page export rendered and inspected; Cyrillic, scope and text checked; orphan heading fixed | `browser-artifacts/report.pdf`, `pdf-pages/report-*.png` |
| Compose | YAML parsed; six environment/network/dependency assertions passed | `compose-static.json` |
| Docker images/containers | **Not run — Docker unavailable** | No Docker build/run claim |
| Textbook statistical simulation | 18 scenarios × 400 simulations reproduced the documented table | `statistical-simulation.log` |
| Three concurrent synthetic previews | 3 × 15,830 rows, all HTTP 200; no assessment commits | `upload-smoke.json` |

Python 3.14.5, Node 24.22.0; existing Python virtualenv packages were used read-only and frontend dependencies were
copied into this checkout. Their dependency versions matched the supplied pinned requirements and lockfile. A fresh
pip/npm install, Docker dependency resolution, Windows and Linux startup were not independently exercised. Backend
runs emit one Starlette/httpx TestClient deprecation warning. Vitest emits a future Vite config-loader warning;
neither prevented the checks above. Raw counts include parameterized examples; the optimizer's 250 random problems
are deliberately one property test, not 250 independently distinct features.

The concurrency probe collected ten health responses: **14.3 ms median, 539.1 ms maximum**, 1.76 seconds total.
This is a small preview-only smoke measurement on this Mac, not a capacity, p95 latency or performance guarantee.

## Feature and endpoint coverage matrix

The detailed [feature-to-test matrix](FEATURE_COVERAGE.md) supplies expected behavior, exact automated test names,
actual results and remaining gaps. Use [PRE_DEFENSE_SMOKE.md](PRE_DEFENSE_SMOKE.md) for the short rehearsal checklist.

“Passed” means the listed behavior was exercised, not that every possible input, user or deployment is covered.
`route-coverage.json` records route templates, methods and observed statuses without bodies, query values or tokens.

| Screen / capability | Routes / actions | Verification and result | Residual gap |
|---|---|---|---|
| Overview `/` | GET health, meta, analytics/overview | Empty state; 199 students, eight assessments, 67.4%; opportunities; scoped and empty results; real browser | Larger datasets and accessibility audit not covered |
| Import `/import` | GET imports, schema, template and demo CSV; POST preview, commit, discard | CSV/XLSX, encoding, numeric ambiguity, invalid IDs/scores, duplicates, conflicts, expiry, mixed granularity, all class/subject assignments; byte/row/unpacked-XLSX limits; concurrent conflicting commits; injected failure rolls back all rows | Not a full malicious-file/parser-fuzzing audit; maximum 200,000-row performance unmeasured |
| Topics `/topics` — challenge 1 and 2 | GET analytics/topics | Mastery independently recomputed from source CSV; weak-topic thresholds; pre/post pairing, positive/negative/inconclusive gains, corrected intervals; grade/class/subject/book/date and empty scopes; reload and error retry | Item difficulty/IRT and longitudinal intervention validation absent |
| Textbooks `/textbooks` — challenge 3 | GET analytics/textbooks | Class-level units, minimum samples, common items, baseline/gain checks, contradictory directions suppress verdict; grade 7 exploratory / grade 8 insufficient; independently reproduced simulation | Observational association; confounding and low power remain |
| Optimizer `/optimizer` — challenge 4 | GET inputs and runs; POST run/evaluate/decision; PUT topic constraints | Totals, bounds, locks, half-hour steps, prerequisites, signs, stable tie-breaking, explicit policy infeasibility/relaxation; accept/reject/history; manual invalid values; 250 randomized invariant cases; persistence | One grade plan, no per-class plan; accepted recommendations are not verified interventions |
| Insights `/insights` | POST ai/insights | No-key mode; valid placeholders; wrong entities/numbers/names, causal claims, contradictions, malformed JSON/envelopes; HTTP 401/429/500, timeout; maximum two attempts; honest fallback labels and attempt counts; actual OpenAI-compatible HTTP request contract mocked | No new live Gemini call; semantic guards heuristic; quota/latency/reliability unknown |
| Reports `/reports` | POST/GET reports; GET detail/PDF; DELETE report | Scope restricted to selected grade/class, missing/stale plans, optional AI, immutable snapshots after settings edits, Cyrillic PDF text and four rendered pages, reopen/delete confirmation and 404 lifecycle | Stress with very long titles, huge tables and every paper size not covered |
| Settings `/settings` | GET/PUT settings; POST admin/reset | Threshold validation, three-class floor consistent in UI/API, save/reload, reset cancel, wrong/missing admin token/confirmation, disabled reset, reset retains analysis settings | Shared-token settings are available to every token holder; no roles |
| Integrity | GET admin/integrity, CLI, migrations | Legacy missing assignments/mixed rows/raw validation/JSON-null/expired staging checks; explicit repair tests; live demo read-only report clean | Historical `ddc` was not inspected or repaired |
| Navigation / access / errors | All eight screens; server proxy; optional Basic authentication | Main browser journey no unexpected JS errors; 390px mobile menu/overflow; token required except health; loopback mode; malformed Basic gets 401; proxy token/filter/PDF/header behavior; sanitized 503/500; safety headers | Chromium with mobile emulation only; no complete security, pen-test or accessibility certification |
| Startup / configuration | dev.sh, local_services.py, Compose, env template | Refuse occupied ports, token precedence, no shell evaluation of private env, recorded-process stop/restart, database persistence, Gemini base URL and timeout forwarding | Docker runtime untested; cold font build requires network; shared-token architecture remains |

API route coverage demonstrates each route was reached; it does not establish exhaustive branch coverage.

## Reproduced defects and fixes

The existing baseline tests were green but missed the following defects. The first new backend batch reproduced
**12 failing cases out of 28** (`regressions-before.log`). The new Basic-authentication test failed once
(`frontend-regressions-before.log`). Further browser/PDF checks found the Settings and layout defects below.

1. **Reversed date ranges accepted by POST filters:** report/AI body validation now matches GET date-order validation.
2. **Non-finite manual allocations could cause server errors:** NaN/Infinity strings are rejected with HTTP 422.
3. **Duplicate topic overrides silently used the last value:** duplicates now fail validation before planning.
4. **Malformed successful provider envelopes could escape fallback:** both provider adapters validate their envelope
   and require text; empty/null/list content falls back after bounded attempts.
5. **Fallback always reported zero attempts:** it now reports actual calls (zero without a key; one on HTTP failure;
   at most two on invalid output).
6. **Malformed Basic-authentication base64 threw:** it now returns the normal 401 challenge.
7. **Settings UI allowed fewer than three classes while backend rejected it:** frontend validation now uses three,
   with a field-level message. Added unit cases and production-browser save/reload checks.
8. **Clean typecheck could not resolve LayoutProps:** the command runs `next typegen` before `tsc`.
9. **Compose omitted Gemini base URL/timeout:** forwarded both, plus existing upload/preview-limit configuration.
10. **dev.sh did not propagate a token from backend/.env and stopped by broad process names:** the new launcher parses
    private config, propagates the token, checks readiness and stops only recorded process identities. A restart test
    exposed Next.js changing its process title; stable start-time/owner metadata fixed ownership tracking.
11. **A PDF heading was stranded at the previous page's bottom:** section headings now stay with following content;
    reproduced by PDF extraction and verified again in all four rendered pages.
12. **Destructive tests defaulted to an existing demo port/database convention:** pytest now requires an explicit
    parsed `_test` database target; E2E requires an explicit loopback URL and reset acknowledgement, and refuses 3010.

Two intermediate browser failures were test expectations, not product defects: Next.js also has a hidden `alert`
route-announcer, and negative manual hours are rejected locally before backend evaluation. Locators/assertions now
check the intended alert and separately exercise client validation and backend constraint evaluation. No statistical
rules were relaxed, errors suppressed, or failing cases removed to obtain green results.

## Additional checks from the detailed QA brief

The final suite adds independent class-level QR/OLS and Welch reference calculations over unequal class sizes;
changing the size of one class leaves inferential estimates unchanged. It independently checks all six filters,
exact threshold/sample boundaries, zero-variance gains, scoring-scale weighting and distribution bins. Further
checks cover every API method's token boundary, path-like filenames, traversal parameters in the frontend proxy,
credential sentinels in errors/logs, unintended data in outbound facts, same-grade/different-subject plan scope,
and class-scoped PDF values against the selected API metrics. UTF-8-BOM/Windows-1251 and NaN/infinite score cases
have explicit regression coverage. Browser Settings now verifies an actual classification change, and an eighth
scenario holds an intercepted response to check the loading state without fixed sleeps.

A further clear defect was reproduced: a significant +0.04/-0.04-point gain and its interval could be rounded to
zero while retaining an increase/decline label (`precision-regression-before.log`, `precision-frontend-before.log`).
The backend now retains small nonzero gain estimates/bounds, the frontend preserves their sign when ordinary
rounding would show zero, and optimizer prose uses the same principle. Statistical calculations, thresholds and
optimization policies were not changed. Final regression, type, lint, build and browser checks passed afterward.

The new toy/reference tests initially exposed three test-setup errors: the chosen toy effect did not satisfy both
verdict intervals, the assumed histogram width was wrong (the product uses ten 10-point bins), and a mocked API
failure inherited the verification file's disabled-provider setting. Those fixtures now match the documented
model, and assert independently calculated results. A PDF assertion was also adjusted for legitimate word wrapping
within the narrow “Освоение” column heading. These were test defects, separate from the reproduced precision bug.

## Opt-in Gemini smoke check

`backend/scripts/smoke_gemini.py` is database-free, uses synthetic aggregate facts, and caps provider requests at
two including retries. Without `--live` it does not read a private environment file and makes zero calls, even if a
key exists. With `--live`, a key supplied securely via environment or `--env-file` is required. Per-request timeout
is at most 30 seconds. The sanitized JSON distinguishes `live_success` (validated LLM output, exit 0),
`deterministic_fallback` (exit 3), and precondition `blocked` (exit 2). It does not treat HTTP 200 as proof of success.

Nine harness tests use mocked calls and are **not live integration evidence**. This run exercised the default
command; `verification/live-smoke-default.json` records `not_run`, zero provider requests. Live execution was not
enabled and no Gemini credential exists in this verification copy. The handoff's one historical live result remains
separate. Secure opt-in instructions are in [PRE_DEFENSE_SMOKE.md](PRE_DEFENSE_SMOKE.md).

## Reproduce safely

Do not run these commands against the original live stack. Create two fresh PostgreSQL databases on your isolated
instance and first check the host, port and names. In this working copy the isolated instance is already on 55434.
Use your own installation paths, roles and private credentials elsewhere.

```bash
# backend/ — destructive, explicitly selected fresh test database only:
TEST_DATABASE_URL=postgresql+psycopg://verification@127.0.0.1:55434/ddc_verification_test \
  python -m pytest -q -p tests.route_evidence --junitxml=../verification/backend-final.xml

# frontend/:
npm run typecheck
npx eslint src e2e playwright.config.ts
npm test
npm run build
```

For an isolated stack, set its private backend environment to `ddc_browser_test`, generate new API/admin tokens,
set `ENABLE_DATA_RESET=true`, and use `LLM_PROVIDER=none`/empty key for deterministic tests. Never reuse the demo's
private tokens. Then, from the source root with embedded PostgreSQL binaries installed:

```bash
PORT_DB=55434 BACKEND_PORT=8011 FRONTEND_PORT=3011 \
  DDC_PGDATA="$PWD/verification/pgdata" ./dev.sh start
```

This command expects that PostgreSQL data directory already exists and `backend/.env` points to the correct database.
`DDC_PG_BIN` can point at separately installed embedded PostgreSQL binaries; `DDC_PYTHON` can select a prepared venv.
It does not initialize/migrate the original demonstration database. For the browser journey, load the **test** admin
token privately into `E2E_ADMIN_TOKEN` and run from `frontend/`:

```bash
E2E_BASE_URL=http://127.0.0.1:3011 E2E_ALLOW_RESET=isolated-database \
  E2E_ARTIFACT_DIR="$PWD/../verification/browser-artifacts" npm run e2e
```

The acknowledgement is a guard, not database discovery: verify that the selected frontend actually proxies to your
isolated backend/database before running. An absent `TEST_DATABASE_URL` or unsafe E2E target intentionally fails.
`./dev.sh stop` stops only services recorded by this checkout and leaves its PostgreSQL instance running.

## Remaining problems and readiness

### Hackathon defense

**Ready for a local demonstration with synthetic data on the verified Mac.** The four challenge capabilities and
complete import-to-PDF flow passed. Rehearse using the existing synthetic demo or the separate verification stack.
The fixes in this copy are not automatically applied to the original running demo. Do not replace its source or
restart/migrate it without an explicit transfer plan. There is no verified GitHub upload or public deployment.

Before relying on a different machine or Docker, build/start and test there. For an offline defense, prepare the
production build beforehand because the current font build fetches Google Fonts. Keep deterministic mode ready;
the handoff's live Gemini response took about 27 seconds, and this run intentionally made no real model requests.
Google's [official compatibility reference](https://aistudio.google.com/docs/openai) was checked on 11 November 2026;
it confirms the configured OpenAI-compatible base URL. Model/account access and key rotation remain separate checks.
Hackathon permission to use external APIs has not been supplied and is not asserted.

Defensible five-minute flow: synthetic data label → import preview → weak topics with gain directions → grade-7
exploratory textbook comparison and grade-8 insufficiency → 82-hour recommendation plus hard/policy infeasibility →
mode-labelled explanation → scoped PDF. Say “observed association” and “constrained proposal”; do not claim a trained
proprietary model, a causal textbook advantage, proven educational improvement or a public judging link.

The 7,200 statistical simulations yielded observed false-positive proportions **0.7–4.0%** in the nine no-effect
scenarios, and detection proportions **5.5–93.0%** for a simulated +6-point effect across the other nine. These are
simulation-specific results, with Monte Carlo uncertainty, not accuracy figures on real school data.

### Real student data

**Not ready.** Shared tokens do not provide individual accounts, roles, per-school isolation, attributable audit trails
or governed access to exports. Identifier validation is not anonymity: IDs, class membership and small aggregates can
still be identifying. This verification did not establish backup/restore procedures, retention/deletion governance,
incident handling, external-provider data handling approval, production transport/storage controls or a security audit.

Educational validity also remains separate from functional correctness: no intervention study, no calibrated
item-difficulty model, small-class uncertainty and teacher/class confounding. Hours recommendations require review and
later assessment; they are not forecasts. Plans are grade-wide. Localization remains partial. Large-dataset sustained
loads and multi-user race cases beyond the tested import conflicts have not been established.

No real student data should be onboarded on the strength of these green synthetic-data tests alone.
