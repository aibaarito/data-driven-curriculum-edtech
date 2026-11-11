# Data-Driven Curriculum

Платформа аналитики учебных программ для методистов: импорт результатов оцениваний, анализ тем, осторожное
сравнение учебников, прозрачный оптимизатор учебных часов, проверяемые ИИ-пояснения и PDF-отчёты.
Интерфейс — на русском языке.

> Демонстрационные данные **полностью синтетические** (seed 20251110, школа `SYNTH-DEMO`), а интерфейс помечает их
> как синтетические. Это не данные реальной школы.

**Версия 2.0 — Curriculum Decision Intelligence.** Помимо аналитики система отвечает на пять вопросов:
что не осваивается → почему (доказательства, пререквизиты) → что изменить (сценарии плана часов в реальных
ограничениях) → почему этому можно доверять (паспорт доказательств, неопределённость, версия данных) → сработало ли
(отслеживание вмешательств и оценка «до/после» без причинных заявлений). Решения принимают детерминированные
движки; ИИ только объясняет проверенные факты.

* Архитектура Decision Intelligence: [docs/DECISION_INTELLIGENCE_ARCHITECTURE.md](docs/DECISION_INTELLIGENCE_ARCHITECTURE.md)
* Архитектура и API: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
* Формулы и статистические методы: [docs/ANALYTICS.md](docs/ANALYTICS.md)
* Формат импорта, проверки целостности и восстановление старых данных: [docs/IMPORT_FORMAT.md](docs/IMPORT_FORMAT.md)
* Independent verification: [docs/VERIFICATION.md](docs/VERIFICATION.md)
* Exact feature-to-test matrix: [docs/FEATURE_COVERAGE.md](docs/FEATURE_COVERAGE.md)
* Pre-defense checklist and optional live Gemini check: [docs/PRE_DEFENSE_SMOKE.md](docs/PRE_DEFENSE_SMOKE.md)
* Переменные окружения: [.env.example](.env.example)

## Stack
Next.js 16 · React 19 · TypeScript (strict) · Tailwind 4 · shadcn/ui · Recharts · React Hook Form + Zod —
FastAPI · Pydantic 2 · SQLAlchemy 2 · Alembic · PostgreSQL 17 · pandas / NumPy / SciPy · ReportLab —
Pytest · Vitest + React Testing Library · Playwright.

## Run

### Option A — Docker Compose
```bash
cp .env.example .env    # then set POSTGRES_PASSWORD and API_TOKEN (required; no insecure defaults)
docker compose up --build
```
Open http://127.0.0.1:3010 (published on 127.0.0.1 only; the API is not published). Migrations run on backend start.
*Docker was not available in the development environment: the compose file was parsed as YAML, but the images were
**never built or started**.*

### Option B — local, no Docker (macOS arm64; verified on an isolated stack)

**The existing demo uses 3010/8010 and database `ddc_e2e` on 55433. Do not run setup or reset against it.**
Use a new database and different ports for verification; see [docs/VERIFICATION.md](docs/VERIFICATION.md).
Uses an embedded PostgreSQL 17 binary from npm (`@embedded-postgres/darwin-arm64`) on port 55433.
```bash
./dev.sh setup
./dev.sh start
```
Open http://127.0.0.1:3010. Stop this checkout’s recorded services with `./dev.sh stop` (PostgreSQL stays running).
Tested with Python 3.14.5 and Node 24.22.0. `./dev.sh start` refuses occupied service ports, applies migrations,
checks integrity, builds the frontend, and waits for an authenticated proxy request to succeed. It parses
`backend/.env` without shell evaluation and passes the same API token to both servers. Environment variables
override the private file. `BACKEND_PORT`, `FRONTEND_PORT`, `PORT_DB`, `DDC_PGDATA`, and `DDC_PG_BIN` allow an isolated
stack; set `DATABASE_URL` explicitly to match it. `setup` installs test dependencies too. A clean dependency install
was not repeated in the November verification; existing matching dependencies were reused.

The production build currently downloads Inter from Google Fonts; network access is needed on a cold build.
Build before the defense. The stop helper uses recorded process start time/owner, avoiding broad process-name kills.
Processes launched by older helpers must be identified and stopped separately; they are not adopted automatically.

Manual equivalent: start PostgreSQL, then
`cd backend && . .venv/bin/activate && alembic upgrade head && uvicorn app.main:app --host 127.0.0.1 --port 8010`, and
`cd frontend && npm run build && npm start` (the server-side route `src/app/api/[...path]` forwards `/api/*` to `API_URL`).

### Upgrading an existing installation
```bash
cd backend && . .venv/bin/activate
alembic upgrade head                        # adds import-preview expiry; normalises cleared staging to SQL NULL
python scripts/integrity_check.py           # read-only report on data imported before the integrity fixes
python scripts/integrity_check.py --redact-validation --purge-expired-previews   # optional, explicit repairs
```
Migration `6129d2b374e8` is reversible (`alembic downgrade -1` drops the expiry column); its JSON-null → SQL-NULL
normalisation is data-only and intentionally not reverted. A stored "min classes per textbook" below 3 is raised to 3
at load time and shown as a notice in Settings.

## Access
* **Local demo (default):** no `API_TOKEN` → the API serves loopback clients only, the UI is bound to 127.0.0.1.
* **Token mode:** set `API_TOKEN` for both backend and frontend processes; the Next.js server adds it to proxied
  requests, it never reaches the browser. Optional `DEMO_BASIC_AUTH_USER/PASSWORD` protects the whole UI.
* **Delete all data** is disabled unless `ENABLE_DATA_RESET=true` and `ADMIN_TOKEN` (≥ 16 chars) are set; the Settings
  dialog then asks for the admin token. `./dev.sh setup` enables it for local development with a random token stored
  in the git-ignored `backend/.env`.
* There are no user accounts and no per-school isolation: anyone with the API token sees all data.

### Optional LLM
Without a key the **deterministic explainer** is used and the UI labels the mode. For Gemini, edit only the private
server file (`backend/.env` locally; root `.env` for Compose):

```dotenv
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
LLM_MODEL=gemini-3.8-flash
LLM_TIMEOUT_SECONDS=60
# Set LLM_API_KEY privately; never paste a real key into documentation or chat.
```

The endpoint matches [Google’s official OpenAI compatibility documentation](https://aistudio.google.com/docs/openai),
checked 11 November 2026. Check model access for your own account before relying on it. Compose now forwards the
base URL and timeout as well as provider/key/model, but its images have **not** been run here. Locally, the helper
passes the API token to the frontend; for a manual launch set `API_TOKEN` and `API_URL` on the frontend process too.
The model receives aggregate facts; output guards are heuristic and do not certify every sentence.

Evidence: the handoff records one successful live Gemini request (about 27 seconds). This verification used mocks
and deterministic mode, and made no live model calls. The prior key’s rotation is unconfirmed; replace it privately
before using it beyond the original demonstration. Do not copy the original private configuration into source exports.

## Tests

Tests destroy the schema of their target database. `TEST_DATABASE_URL` is now required explicitly and its parsed
PostgreSQL database name must end in `_test`. Create a **fresh** database on a separate verification instance/port.
Never use `ddc_e2e`: despite its name, it is the live demonstration database.

```bash
# From backend/, with dependencies installed:
TEST_DATABASE_URL=postgresql+psycopg://verification@127.0.0.1:55434/ddc_verification_test python -m pytest -q
# From frontend/:
npm run typecheck       # generates Next.js route types before tsc
npx eslint src e2e playwright.config.ts
npm test
npm run build
```

Browser tests require an already running isolated backend/database and production frontend. After checking those
service targets, run from `frontend/`:

```bash
E2E_BASE_URL=http://127.0.0.1:3011 E2E_ALLOW_RESET=isolated-database \
  E2E_ADMIN_TOKEN='<private test admin token>' npm run e2e
```

If the pinned Playwright browser build is not installed (e.g. a sandbox image with its own Chromium), add
`E2E_CHROMIUM_PATH=/path/to/chrome`. Load the actual token from a private file, rather than putting it literally in shell history. The configuration refuses
missing targets, remote hosts, and demo port 3010. The journey **resets all data** on the selected stack. Use
`E2E_ARTIFACT_DIR` to keep new screenshots/PDFs separate from the archive’s historical screenshots.
Full commands, results, limitations, and coverage are in [docs/VERIFICATION.md](docs/VERIFICATION.md).

## Demo script for judges (≈5 min)
1. Use the prepared synthetic demo, or start clean on a **separate rehearsal database**. Reset only that rehearsal
   stack via Settings with its private admin token. Preserve the running demo database `ddc_e2e`.
2. **Импорт данных** → «Демо-набор (синтетический)» downloads the CSV → choose it → **«Проверить файл»**:
   15 830 rows, 199 students, 0 errors → **«Подтвердить импорт»**. Optionally upload a broken file first to show
   row-level errors (score > max, ФИО instead of an ID) and that import stays disabled.
3. **Обзор**: 199 students, 8 assessments, average mastery 67.4%, 2 difficult topics; improvement opportunities.
4. **Анализ тем** (grade 7): «Формулы сокращённого умножения» 40.9%, change not established (pre 40.3 → post 40.9;
   +0.6 p.p., 99.4% CI −5.2…6.5 with a Bonferroni correction over 8 topics) — flagged for methodological review, *not*
   as instructional failure and *not* as "no effect". «Разложение на множители» is low but improving (+27.2 p.p.).
5. **Сравнение учебников**, grade 7: inference uses classes (3 + 3) as units. Raw difference of class means +1.4 p.p.
   (95% CI −4.8…7.6); B classes started 5.1 p.p. lower; baseline-adjusted +5.1 p.p. (95% CI 1.6…8.6, df = 3); gain
   difference +8.1 p.p. (95% CI 4.1…12.1). Both agree, so the app reports an **exploratory** association («Предварительный
   вывод, всего 6 классов»), not a causal effect. Grade 8: «Недостаточно данных…» (one class per textbook).
6. **Оптимизатор часов**, Математика / 7: the grade plan (medians of class hours) totals 82 h and is preserved. Hours
   move from «Линейная функция» (84.8%, above target) to weak topics; hard checks and policy checks are green.
   «Формулы сокращённого умножения»: change not established, so the explanation warns that hours alone may not help.
   Set the total to 70 h: refused by policy (below-target topics would lose hours) until «Разрешить явное ослабление» is
   ticked — then the relaxed rule and affected topics are listed. Set 10 h to show a hard infeasibility.
7. **ИИ-пояснения** → «Сформировать пояснения»: the mode badge, the findings with the metrics they cite,
   limitations and next steps.
8. **Отчёты** → «Сформировать отчёт» → **«Скачать PDF»**. The report's sections are labelled as observations,
   recommendation or limitations.

## Three-minute demo (v2.0, synthetic data)
Prepared state: synthetic dataset imported on a rehearsal stack (never `ddc_e2e` unless it is the intended demo).
Say aloud that the data is synthetic.

| Time | Screen | What to show |
|---|---|---|
| 0:00–0:25 | — | Schools collect assessment data, but turning it into defensible curriculum changes is hard. |
| 0:25–0:55 | **Центр решений**, Математика / 7 | Readiness strip: 8 topics, evidence sufficient. «Формулы сокращённого умножения» 40.9%: change *not established*, so the recommendation is **methodology review, not more hours** (open "why not other actions"). «Разложение на множители» is low but improving, so hours are reallocated. |
| 0:55–1:20 | **Карта программы** | Select «Формулы…» (keyboard works). It is a weak prerequisite of a weak topic, priority 38.6, and the chain «Степень → … → Разложение» is highlighted. The text says it *precedes*, not *causes*. |
| 1:20–2:00 | **Сценарии плана** | Budget 82 h → three real plans; all hard constraints are green; the comparison table shows exact differences. Optionally set 10 h to show per-scenario `INFEASIBLE`. Choose «Фокус на пробелах» for approval. |
| 2:00–2:30 | **Паспорт доказательств** | Observation, 99.4% Bonferroni CI −5.2…6.5, "does not prove absence of effect", why the action is allowed, dataset fingerprint, synthetic flag. |
| 2:30–3:00 | **Центр решений** → Отчёты | Approve → plan intervention → mark implemented (2026-09-01) → awaiting data → "Оценить": *no data yet*. Import «synthetic_followup_SIMULATED.csv» (`/api/imports/demo-followup.csv`) → evaluation with the **non-causal** statement, and the approved plan is now marked *stale* with its frozen evidence intact. Export the PDF report. |

Closing line: *"Data-Driven Curriculum does not simply analyze what students scored. It helps educators understand
what to change, justify their decisions, and evaluate whether those changes worked."* The follow-up file is
**simulated** (+3 p.p. by construction): do not present its result as proof that the intervention works.

**Backup plan.** Record the run above beforehand. `npm run e2e` with `E2E_ARTIFACT_DIR` produces the same screens
as screenshots (`di-01`…`di-06`). Everything works without an LLM key, so a Gemini outage does not affect the demo.

## Official case coverage
| Requirement | Where | Acceptance tests |
|---|---|---|
| 1. Analysis by topic | Анализ тем, Обзор | `test_req1_*` (mastery recomputed independently from the raw CSV) |
| 2. Topics students struggle with | Обзор, Анализ тем | `test_req2_*` |
| 3. Textbook effectiveness (baseline, gain, sample size, comparability, uncertainty) | Сравнение учебников | `test_req3_*` |
| 4. Justified teaching-hour recommendations under constraints, with review | Оптимизатор часов | `test_req4_*` |

All are in `backend/tests/test_core_requirements.py`. The E2E test `frontend/e2e/journey.spec.ts` drives the
whole journey in a browser: upload → analyze → difficulties → textbooks → hours → explanation → report.

## Known limitations
* **Access control is a single shared token plus a local-only default.** No user accounts, roles, audit log or per-school
  isolation. Not suitable for real student data as is.
* Docker images were never built or run here (Docker unavailable).
* The handoff records one successful live Gemini request. The current independent suite used mocked provider
  responses, including invalid envelopes, timeouts, HTTP 401/429/500 and grounding violations. Sustained live
  provider reliability, quota and account access remain unverified.
* The hours plan is one plan per grade (median of class hours); per-class plans are not supported.
* Textbook inference with few classes has low power (see docs/ANALYTICS.md): most real differences will be reported as
  "insufficient evidence". Baseline adjustment cannot remove residual confounding (teacher, class composition).
* Assessment difficulty is handled only by comparing textbooks on common items. There is no IRT/item-difficulty model.
* Localization: the shell, navigation, page headers and states come from `src/i18n/ru.ts`, but page bodies still
  contain inline Russian strings.
* Decision intelligence: the priority score is a documented heuristic, not a trained predictor. Decision rules are
  fixed in code (not user-configurable). Outcome evaluation is before/after **without a comparison group**, so it
  reports associations only. Knowledge tracing was not added: the data has 2–3 occasions per topic, which is too
  few to fit or validate a model. No OR-Tools solver; scenarios use the existing deterministic projection
  optimizer without optimality certification.
* The evidence fingerprint is scope-limited (subject + grade, plus filters). Any import, constraint, approved edge,
  hours or settings change in that scope marks saved runs, reports and interventions as stale. Their stored
  snapshots are never recomputed.
* Analytics are recomputed per request (~0.1 s for 16k rows). For much larger datasets, add caching or materialized
  aggregates.
