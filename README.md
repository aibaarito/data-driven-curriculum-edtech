# Data-Driven Curriculum

Платформа аналитики учебных программ для методистов: импорт результатов оцениваний, анализ тем, осторожное
сравнение учебников, прозрачный оптимизатор учебных часов, проверяемые ИИ-пояснения и PDF-отчёты.
Интерфейс — на русском языке.

> Демонстрационные данные **полностью синтетические** (seed 20251110, школа `SYNTH-DEMO`), а интерфейс помечает их
> как синтетические. Это не данные реальной школы.

* Архитектура и API: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
* Формулы и статистические методы: [docs/ANALYTICS.md](docs/ANALYTICS.md)
* Формат импорта, проверки целостности и восстановление старых данных: [docs/IMPORT_FORMAT.md](docs/IMPORT_FORMAT.md)
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

### Option B — local, no Docker (macOS arm64; this is the verified path)
Uses an embedded PostgreSQL 17 binary from npm (`@embedded-postgres/darwin-arm64`) on port 55433.
```bash
./dev.sh setup
./dev.sh start
```
Open http://127.0.0.1:3010. Stop with `./dev.sh stop`. Tested with Python 3.14 and Node 24.
`./dev.sh start` applies migrations (`alembic upgrade head`) and prints the read-only integrity report.

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
Put `LLM_API_KEY` (and optionally `LLM_PROVIDER`, `LLM_MODEL`) in `backend/.env`. Without a key the
**deterministic explainer** is used and the UI says so. The LLM receives only aggregated, verified metrics.

## Tests
```bash
cd backend && . .venv/bin/activate && python -m pytest -q      # unit + integration (wipes database ddc_test only)
cd frontend && npm run typecheck && npx eslint src && npm test  # types, lint, Vitest
python backend/scripts/simulate_textbook_fpr.py --sims 400      # textbook-verdict false-positive/power simulation
```
End-to-end (the journey RESETS ALL DATA, so run it against a dedicated database such as `ddc_e2e`): start the backend
with `DATABASE_URL=…/ddc_e2e API_TOKEN=<t> ENABLE_DATA_RESET=true ADMIN_TOKEN=<a>`, the frontend with
`API_TOKEN=<t> API_URL=http://127.0.0.1:8010 npm start`, then `E2E_ADMIN_TOKEN=<a> npm run e2e`.
Screenshots of the E2E run are written to `frontend/e2e/screenshots/` (including the exported `report.pdf`).

## Demo script for judges (≈5 min)
1. Start clean: **Settings → «Удалить все данные»** (type УДАЛИТЬ and the admin token from `backend/.env`; only
   available when reset is enabled for development). The dashboard shows an empty state.
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
* A live LLM was not exercised end-to-end (no key). The LLM path is tested only with mocked responses (placeholders,
  swapped values, digits, names, promises, status contradictions, malformed JSON, provider errors).
* The hours plan is one plan per grade (median of class hours); per-class plans are not supported.
* Textbook inference with few classes has low power (see docs/ANALYTICS.md): most real differences will be reported as
  "insufficient evidence". Baseline adjustment cannot remove residual confounding (teacher, class composition).
* Assessment difficulty is handled only by comparing textbooks on common items. There is no IRT/item-difficulty model.
* Localization: the shell, navigation, page headers and states come from `src/i18n/ru.ts`, but page bodies still
  contain inline Russian strings.
* Analytics are recomputed per request (~0.1 s for 16k rows). For much larger datasets, add caching or materialized
  aggregates.
