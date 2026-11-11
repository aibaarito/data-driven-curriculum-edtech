# Data-Driven Curriculum — complete agent handoff

Snapshot date: **11 November 2026**, user timezone **Asia/Almaty**.

## 1. Start here: the user's situation and next objective

The user has a functional local hackathon MVP and is preparing to defend/demonstrate the project. They want confidence that every important function works and want another agent to continue without losing context. They prefer practical action and clear, non-technical explanations.

The immediate next engineering objective is to **write and run meaningful verification tests for the current implementation**, investigate failures, and fix clear defects. A detailed testing prompt was prepared in the chat, but its execution has not been reported. Do not assume the newly requested comprehensive verification has already happened.

The project has already been built. **Do not create a replacement application from scratch.** Preserve the current work, reproduce relevant problems, and improve the existing implementation.

The archive accompanying this document is a snapshot of current source files, including uncommitted modifications and new source files. It excludes private configuration, credentials, database contents, installed dependencies, build caches, logs, and Git history. It includes synthetic demo CSVs, tests, migrations, documentation, and historical demonstration screenshots.

## 2. What the product does

**Name:** Data-Driven Curriculum.

**Category:** EdTech / curriculum analytics / AI-assisted explanations.

**Users:** School methodologists, curriculum specialists, teachers, and administrators.

**Official challenge:** “An intelligent system for evaluating the effectiveness of textbooks and educational curricula.” Four required capabilities:

1. Analyze assessment results by curriculum topic.
2. Identify topics students struggle with.
3. Compare outcomes associated with textbooks.
4. Recommend teaching-hour allocations using evidence and constraints.

Workflow: **Import assessments → validate → analyze topics and progress → compare textbooks → optimize hours → review explanations → export reports.**

The application supports human decisions. It must not present observational associations as causal textbook effects or guarantee that more hours improve achievement.

## 3. Current MVP access and source location

On the original Mac:

- Frontend: **http://127.0.0.1:3010** or **http://localhost:3010**.
- AI explanations: **http://localhost:3010/insights**.
- Settings: **http://localhost:3010/settings**.
- Backend: **http://127.0.0.1:8010**.
- Health: **http://127.0.0.1:8010/api/health**.
- Embedded PostgreSQL port: **55433**.
- Current running database: **`ddc_e2e`**. It contains the synthetic demonstration and is actively used by the MVP. **It is not disposable just because its name includes e2e.**

Original source root:

```text
/Users/ajbartorehanov/Library/Application Support/Claude/scratch-workspaces/5541d615-e577-4904-b083-669462315990/1d12970a-1b71-4de5-ac92-b07492bfe45b/scratch-2026-11-10-3cee95
```

This is a Claude scratch workspace, not the Codex chat's generated directory. Preserve a durable copy before the scratch workspace disappears.

These localhost links work only on the computer running the services. They are **not public deployment links**. Another agent on a different computer must extract the source and set up its own environment.

### Directly checked during handoff preparation

- Frontend-proxied health request returned HTTP 200: application status OK, database reachable, LLM enabled.
- Settings returned HTTP 200: provider `openai_compatible`, model `gemini-3.8-flash`, token access mode.
- Reset is currently enabled but requires the configured administrator token.
- Import limits: 10 MB and 200,000 rows; preview TTL: 60 minutes.
- Metadata returned HTTP 200: synthetic data present, grades 7 and 8, eight classes.
- The active database name was checked without exposing credentials: `ddc_e2e`.

## 4. Git and GitHub situation

- Local branch: **`fix/audit-remediation`**.
- Last commit observed: **`4d260d3` — Harden .gitignore for secrets, caches, databases and build artifacts**.
- Remediation changes remain modified/untracked in the local working tree. They were not committed or pushed during this conversation.
- Intended GitHub repository: **https://github.com/hjwkw452v7-dev/data-driven-curriculum-edtech**.
- The user's screenshot showed that repository as **private and empty**. No subsequent push or deployment has been verified.

Distinguish three separate outcomes: local running application, uploaded source repository, and hosted public application. GitHub repository creation alone accomplished neither source upload nor deployment.

Do not discard the working tree, overwrite the remediation branch, force-push, or publish secrets. The ZIP preserves source contents, not branch history.

## 5. Architecture and important files

Frontend: Next.js 16, React 19, strict TypeScript, Tailwind 4, shadcn/ui, Recharts, React Hook Form and Zod. UI language: Russian; localization remains incomplete.

Backend: FastAPI, Pydantic, SQLAlchemy, Alembic, PostgreSQL, pandas, NumPy, SciPy, ReportLab. Existing requirements and lockfiles specify exact project versions; inspect them rather than assuming remembered APIs.

Testing: Pytest; Vitest and React Testing Library; Playwright.

Important backend locations:

- `backend/app/api/routes.py`: API entry points.
- `backend/app/api/schemas.py`: request schemas.
- `backend/app/config.py`: environment settings.
- `backend/app/security.py`: access and streaming body-size middleware.
- `backend/app/services/importer.py`: file parsing and validation.
- `backend/app/services/import_store.py`: import persistence and conflicts.
- `backend/app/services/analytics.py`: topic metrics and gains.
- `backend/app/services/textbooks.py`: textbook inference.
- `backend/app/services/optimizer.py`: allocation and constraints.
- `backend/app/services/context.py`: report/AI scope and optimizer inputs.
- `backend/app/services/ai.py`: facts, provider calls, validation, fallback.
- `backend/app/services/report_pdf.py`: PDF rendering.
- `backend/app/services/previews.py`: preview lifecycle.
- `backend/app/services/integrity.py`: historical integrity checks.
- `backend/scripts/integrity_check.py`: integrity CLI.
- `backend/scripts/simulate_textbook_fpr.py`: statistical simulation.

Important frontend locations:

- `frontend/src/app/api/[...path]/route.ts`: server-side backend proxy; attaches API token.
- `frontend/src/app/*/*-view.tsx`: screen implementations.
- `frontend/src/lib/types.ts`: API contracts.
- `frontend/src/proxy.ts`: frontend access-related behavior.
- `frontend/e2e/journey.spec.ts`: end-to-end journey.
- `frontend/playwright.config.ts`: E2E configuration.
- `frontend/AGENTS.md`: project-specific instructions, including consulting the bundled Next.js docs before frontend changes.

Read `README.md`, `docs/ARCHITECTURE.md`, `docs/ANALYTICS.md`, and `docs/IMPORT_FORMAT.md`. Some historical README statements are outdated; see below.

## 6. Audit findings and reported remediation

An earlier agent audited the backend without changing application code. A subsequent agent reported fixing the findings. The following statuses are **reported by that remediation agent**, not a fresh independent certification of all fixes.

| Original issue | Reported correction |
| --- | --- |
| Only the first subject's textbook assignment survived for a class | Persist an assignment for every `(class, subject)` pair. |
| Too many false textbook differences with few classes | Class-level inference, minimum three eligible classes per textbook, corrected comparisons and exploratory wording. |
| Significant negative gain described as learning | Sign-aware increase/decline/inconclusive/insufficient categories across analytics and explanations. |
| Reduced total silently removed protected hours and still showed green checks | Explicit policy infeasibility; optional declared relaxation; hard constraints remain enforced. |
| Re-import silently accepted inconsistent records | Grade and textbook-subject conflicts rejected; supported setting/hour changes surfaced as warnings. |
| Topic totals and item rows counted the same assessment twice | Reject mixed representations for the same student/assessment/topic within imports and against stored data. |
| AI could move a number from one topic to another | Entity-bound structured facts, placeholders, output validation, retry and deterministic fallback. Semantic guards remain heuristic. |
| Student names echoed in errors and persisted | Redacted errors with row/field/code and an explicit historical-redaction utility. This does not make the entire app anonymous. |
| Report for one class included another grade's hours plan | Restrict plan scope to matching grade and subject; flag stale plans. |

Other reported fixes:

- Blocking import processing moved off the asynchronous event loop.
- Upload limit enforced during streaming, plus an Excel unpacked-size guard.
- Previews expire and staged rows are cleaned up.
- Stable allocation tie-breaking independent of input order.
- Ambiguous numeric strings such as `1,000` rejected instead of silently parsed as 1.0.
- Grade-plan baseline uses a median rounded to half an hour, with class spread displayed; this is a product/methodological choice to verify, not a universal rule.
- Shared-token access; restricted local mode when unset; reset disabled unless explicitly configured and authorized.
- Explicit pooled/student/class weighting and multiple-topic interval correction.
- JSON null versus SQL NULL preview-state bug addressed in model and migration.
- Re-import hour overwrites now warned about.
- Prerequisites from files no longer silently merged into pre-existing topics.

Historical development database `ddc`: the remediation agent reported one stored validation message containing a raw value and two JSON-null preview records. That agent left the development database unmigrated. Do not assume those historical repairs have been applied. The currently running `ddc_e2e` is a separate database.

## 7. Test evidence and its limits

Original reported baseline: **405 backend tests, 20 frontend tests, three E2E tests**. The audit noted 300 backend test cases were repeated seeds of one optimizer test, so the raw count overstated distinct behavioral coverage.

Latest remediation report:

- **148 backend tests passed**; seeded optimizer property testing replaced many repeated test cases.
- **22 frontend unit tests passed**.
- Type checking and lint passed.
- Production frontend build passed.
- **Three E2E tests passed** on a production build and separate database.
- Migration upgrade/downgrade exercised on a disposable database.
- PDF text extracted and rendered pages inspected.
- Upload concurrency measured: health probes reportedly improved from around 1.1 seconds to tens of milliseconds median under the tested upload.

A final optimizer wording change from “average” to “median” received type/lint checks but was not followed by another production build/E2E run in that report.

The handoff-preparing agent checked current source/status, live health/settings/metadata, and one real Gemini explanation. It **did not independently rerun the complete backend/frontend/E2E suites**.

The user subsequently requested stronger functional testing. A comprehensive prompt was written, but no results from executing that prompt have been supplied. That verification is the next priority.

## 8. Gemini integration: actual current state

The existing backend already supported an OpenAI-compatible provider. During this chat, the user supplied a Gemini key and authorized connection. The agent:

1. Verified Google accepted the key through its model-list endpoint.
2. Saved private configuration in the original project's `backend/.env`, with mode 0600 and Git ignore protection.
3. Preserved the existing runtime database and API/admin token settings.
4. Configured provider `openai_compatible`, base URL `https://generativelanguage.googleapis.com/v1beta/openai/`, model `gemini-3.8-flash`, timeout 60 seconds.
5. Restarted only the backend.
6. Sent one explanation request through the frontend proxy using the current synthetic data.

**Observed live result:** HTTP 200; `mode = llm`; model `gemini-3.8-flash`; one attempt; six findings; no fallback reason; approximately 26.8 seconds. This verifies one live request, not reliability under every condition.

Backend computes the educational metrics. Gemini receives aggregate facts and writes explanations using a constrained JSON/placeholder format. The app renders factual values, validates output, and falls back to deterministic explanations on relevant failures. Do not present these guards as proof that all generated prose is factually or semantically flawless.

**No real keys or tokens are included in this handoff or archive.** A new environment must use separately supplied credentials or deterministic mode.

The key was posted in chat. Rotation was advised and **has not been confirmed**: create a replacement, update private configuration, verify it, then revoke the prior key. Do not ask the user to paste replacement keys into a new chat or commit them.

Reference checked during setup: https://aistudio.google.com/docs/openai and https://aistudio.google.com/docs/api-key . Recheck availability and account access before changing models.

## 9. Synthetic demonstration and defensible claims

Demo CSVs are included in `data/` and backend assets. They represent a synthetic school, not a real deployment or validated educational impact.

Reported demo totals: 15,830 imported rows, 199 students, eight assessments, eight classes, average mastery 67.4%, two difficult topics.

Examples:

- “Формулы сокращённого умножения”: 40.9% mastery; change not established. A nonsignificant result does not prove no effect.
- “Разложение на множители”: 47.5% mastery; positive measured gain, approximately 27 percentage points.
- Grade-7 textbook comparison uses three classes per textbook. Reported class-level raw difference approximately +1.4 percentage points; adjusted difference approximately +5.1; gain difference approximately +8.1. It is exploratory and observational.
- Grade 8 has one class per textbook and insufficient evidence for a comparative verdict.
- Grade-7 hours plan totals 82 hours.

Confidence levels and intervals depend on scope and the multiple-comparison family. The remediation report gave 95% intervals for the grade-7 comparison; an all-grades screenshot uses a different corrected level. **Recompute from the selected API scope instead of copying interval endpoints indiscriminately or forcing old demo numbers.**

The original pre-remediation adjusted result +5.3 and gain difference +8.0 are historical. Current reported methods yield approximately +5.1/+8.1. Documentation and presentation should reflect the current method.

## 10. Known limitations and newly identified handoff gaps

- Suitable for a **local hackathon demonstration**, subject to functional verification; **not ready for real student data**.
- Shared-token access is not user accounts, role separation, per-school isolation, or an audit trail.
- Docker configuration was parsed, but no Docker build/run was reported.
- Source inspection during handoff found Compose passes provider/key/model but does **not** pass `LLM_BASE_URL` or `LLM_TIMEOUT_SECONDS`. Gemini's local configuration therefore should not be assumed to work in Docker. Verify and fix this forwarding before claiming Docker/Gemini support.
- `dev.sh start` starts the frontend without explicitly loading the backend's private API token. The currently running frontend was launched with a matching runtime token. Review token propagation before restarting with that helper; do not weaken access control to hide an integration failure.
- README still claims a live LLM has never been tested; that is outdated after the observed successful Gemini request. The default environment template still targets Anthropic; it does not describe the current private Gemini configuration.
- Current source contains uncommitted work, and the GitHub repository was empty in the user's screenshot.
- No public deployment or publicly reachable judging URL has been verified.
- Few-class inference has low power. Baseline adjustment cannot remove teacher/class confounding or noisy-baseline problems.
- Hours recommendations are constrained proposals, not proven interventions or forecasts.
- Grade-level plans use aggregated class hours; per-class plans are not implemented.
- No IRT/item-difficulty model. Localization is incomplete. Large-dataset performance beyond current measurements remains uncertain.
- A real Gemini request requires network access, quota, model availability, and possibly paid usage. The observed response took about 27 seconds; prepare a deterministic fallback and a clearly labeled recording/screenshots for the defense.
- Hackathon rules about external APIs have not been supplied. Do not assert approval. Describe Gemini transparently as an external explanation provider, not a model trained by this team.

## 11. Startup and testing guidance

For a new extracted copy, read the repository README and environment template first. Installed dependencies and the database are deliberately not included.

The reported verified local route is macOS Apple Silicon using embedded PostgreSQL, Python 3.14 and Node 24. `dev.sh setup` installs dependencies and initializes its local database; `dev.sh start` applies migrations and starts services. These scripts bind fixed ports. **Do not run them blindly beside the existing live MVP**, and avoid the broad process-killing stop helper against unrelated services.

On other platforms use an appropriate PostgreSQL setup and manual services, or verify/fix the Docker path. Do not call the archive a universal one-click executable.

No-key deterministic mode is supported. New Gemini setup requires a private server environment file, provider/base URL/model, a separately supplied key, and matching frontend/backend API-token settings if token mode is enabled.

Existing backend test fixture:

- Reads `TEST_DATABASE_URL` and requires the final database name to end in `_test`.
- Overrides `DATABASE_URL`, clears `LLM_API_KEY`, generates test tokens, and enables test reset.
- Drops/recreates the public schema and truncates tables in the target database.

Existing E2E configuration:

- Defaults to frontend port 3010, which is **the user's currently running demo**.
- Journey resets application data.
- Supports `E2E_BASE_URL`, which must point at a separate verification stack.

Create a fresh verification database such as `ddc_verification_test`, select unused ports, and verify all targets before running destructive fixtures. Never assume a database is unused based on its name. Never point the reset journey at the current MVP.

## 12. What the next agent should do

1. Read project instructions and preserve the working tree. Confirm source provenance and services in use.
2. Build a coverage matrix for every real screen, route, and workflow.
3. Run existing tests on a fresh isolated stack, then add meaningful missing regression tests.
4. Cover all original audit defects, empty/error states, filtering, persistence, invalid imports, optimizer invariants, independent analytical expectations, protected reset, report scope, and real PDF content/layout.
5. Mock external providers by default; test valid/invalid JSON, wrong-entity metrics, causal promises, provider failures, bounded retries, mode labels, and fallback. Live smoke tests must be opt-in and bounded.
6. Exercise a complete production-build browser journey using synthetic data and separate ports/database. Check frontend contracts after backend changes.
7. Verify startup/restart token propagation; document current Gemini configuration without secrets; fix the identified Compose environment-forwarding gap if implementing Docker support.
8. Fix clear defects with regression evidence; do not weaken tests or rewrite statistical assumptions simply to obtain green output.
9. Produce actual test counts/results, feature matrix, remaining blockers, and separate demo-readiness versus real-student-data assessments.
10. Prepare a clear defense script and reproducible startup. Source publication/deployment is separate work: do not imply it has already happened.

The user favors completing useful work over merely offering plans. Routine reversible engineering work is appropriate; protect user data and credentials and keep them informed in plain language.

## 13. Presentation direction and suggested demonstration

The earlier brief suggested five slides: product; workflow; analytical differentiation; product demonstration; results and practical value. Design preference: 16:9, modern minimalist typography, black/white with controlled red accents, real screenshots, analytical charts, little text. The existing application UI itself is blue/purple and white; no redesign was requested here.

Focus on implementation: learning gains rather than scores alone, careful textbook comparison, constraints and explicit infeasibility, honest uncertainty, and understandable explanations. Do not invent accuracy, time savings, learning improvements, or superiority over other teams.

Suggested demonstration: overview → synthetic import preview → weak topics and gain direction → exploratory grade-7 comparison and insufficient grade-8 evidence → 82-hour allocation and explicit infeasibility → Gemini explanations with mode label → scoped PDF export. Avoid resetting the user's active demo merely to rehearse; prepare a separate demo database if a clean import is needed.

## 14. Suggested opening instruction for the receiving agent

“Read this handoff and inspect the accompanying existing MVP source. Preserve all current changes and live data. Continue by implementing and running comprehensive functional verification on a separate database and ports. Reproduce and fix clear defects, update outdated setup/AI documentation, and report evidence and remaining limitations. Do not rebuild the app from scratch, expose secrets, reset the running demo, or claim a public deployment exists.”
