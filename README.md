# Data-Driven Curriculum

Платформа аналитики учебных программ для методистов: импорт результатов оцениваний, анализ тем, осторожное
сравнение учебников, прозрачный оптимизатор учебных часов, проверяемые ИИ-пояснения и PDF-отчёты.
Интерфейс — на русском языке.

> Демонстрационные данные **полностью синтетические** (seed 20251110, школа `SYNTH-DEMO`), а интерфейс помечает их
> как синтетические. Это не данные реальной школы.

* Архитектура и API: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
* Формулы и статистические методы: [docs/ANALYTICS.md](docs/ANALYTICS.md)
* Переменные окружения: [.env.example](.env.example)

## Stack
Next.js 16 · React 19 · TypeScript (strict) · Tailwind 4 · shadcn/ui · Recharts · React Hook Form + Zod —
FastAPI · Pydantic 2 · SQLAlchemy 2 · Alembic · PostgreSQL 17 · pandas / NumPy / SciPy · ReportLab —
Pytest · Vitest + React Testing Library · Playwright.

## Run

### Option A — Docker Compose
```bash
cp .env.example .env
docker compose up --build
```
Open http://localhost:3010. Migrations run automatically on backend start, so the stack starts from an empty database.
*Note: the Docker files were written but **not executed** in the development environment (Docker was not installed there).*

### Option B — local, no Docker (macOS arm64; this is the verified path)
Uses an embedded PostgreSQL 17 binary from npm (`@embedded-postgres/darwin-arm64`) on port 55433.
```bash
./dev.sh setup
./dev.sh start
```
Open http://127.0.0.1:3010. Stop with `./dev.sh stop`. Requires Python ≥ 3.12 and Node ≥ 20.

Manual equivalent: start PostgreSQL, then
`cd backend && . .venv/bin/activate && alembic upgrade head && uvicorn app.main:app --port 8010`, and
`cd frontend && npm run build && npm start` (Next.js proxies `/api/*` to `API_URL`, default `http://127.0.0.1:8010`).

### Optional LLM
Put `LLM_API_KEY` (and optionally `LLM_PROVIDER`, `LLM_MODEL`) in `backend/.env`. Without a key the
**deterministic explainer** is used and the UI says so. The LLM receives only aggregated, verified metrics.

## Tests
```bash
cd backend && . .venv/bin/activate && python -m pytest -q      # unit + integration (uses database ddc_test)
cd frontend && npm run typecheck && npx eslint src && npm test  # types, lint, Vitest
cd frontend && npm run build && npm start &                    # then, with the backend running:
cd frontend && npx playwright install chromium && npm run e2e  # end-to-end journey (RESETS ALL APP DATA)
```
Screenshots of the E2E run are written to `frontend/e2e/screenshots/` (including the exported `report.pdf`).

## Demo script for judges (≈5 min)
1. **Settings → «Удалить все данные»** (type УДАЛИТЬ) to start clean. The dashboard shows an empty state.
2. **Импорт данных** → «Демо-набор (синтетический)» downloads the CSV → choose it → **«Проверить файл»**:
   15 830 rows, 199 students, 0 errors → **«Подтвердить импорт»**. Optionally upload a broken file first to show
   row-level errors (score > max, ФИО instead of an ID) and that import stays disabled.
3. **Обзор**: 199 students, 8 assessments, average mastery 67.4%, 2 difficult topics; improvement opportunities.
4. **Анализ тем** (grade 7): «Формулы сокращённого умножения» 40.9%, no measurable gain (pre 40.3 → post 40.9,
   CI −3.5…4.8), which the app flags for methodological review, *not* as instructional failure. «Разложение на
   множители» is low but improving (+27 p.p.). «Линейные уравнения» shows +43.5 p.p.
5. **Сравнение учебников**, grade 7: the raw difference of +1.5 p.p. is not significant, but textbook B classes
   started 5 p.p. lower. The baseline-adjusted estimate is +5.3 p.p. (95% CI 3.8…6.8, clustered by 6 classes),
   and the pre→post gain difference (+8.0 p.p., CI 4.9…11.2) points the same way. Both are reported as an
   association, not a causal effect. Grade 8 shows «Недостаточно данных…» because there is only
   one class per textbook.
6. **Оптимизатор часов**, Математика / 7: the total of 82 h is preserved. Hours move from «Линейная функция»
   (84.8%, above target) to the weak topics, each with a written justification and all 5 constraint checks green.
   «Формулы сокращённого умножения» is flagged: its gain is not significant, so the app recommends a methodological
   review rather than promising that more hours will help.
   Lock a topic, type a manual allocation, press **«Проверить ручной вариант»**, then **«Принять»**. Set the total
   to 10 h to show the infeasibility explanation.
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
* **No authentication or multi-tenant isolation.** The data model has `school_id`, but all users see all data.
  Do not deploy publicly with real student data.
* Docker Compose and the Dockerfiles were not run in the build environment.
* A live LLM was not exercised end-to-end (no key available). The LLM path is covered by unit tests with stubbed
  responses: valid output, malformed JSON with retry, invented numbers, causal wording, and provider outage.
* Teaching-hours "current" values are averaged across the classes of a grade; per-class optimization is not implemented.
* Assessment difficulty is handled only by comparing textbooks on common items. There is no IRT/item-difficulty model.
* With few classes (6 here), cluster-robust intervals rely on t(G−1) and remain approximate.
* Localization: the shell, navigation, page headers and states come from `src/i18n/ru.ts`, but page bodies still
  contain inline Russian strings.
* Analytics are recomputed per request (~0.1 s for 16k rows). For much larger datasets, add caching or materialized
  aggregates.
