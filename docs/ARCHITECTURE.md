# Architecture

```
Browser ──► Next.js 16 (App Router, :3010) ──/api/* rewrite──► FastAPI (:8010) ──► PostgreSQL 17
             React 19, Tailwind 4, shadcn/ui,                   SQLAlchemy 2, Alembic,
             Recharts, RHF + Zod                                 pandas / NumPy / SciPy,
                                                                 ReportLab (PDF), httpx (LLM, optional)
```
* The browser only talks to its own origin; the backend URL and any LLM key live server-side.
* Pages are static shells (prerendered); data is fetched client-side from the API and filters live in the URL.
* One backend process; analytics are pure functions over a pandas DataFrame loaded with one SQL join
  (~0.1 s for ~16k rows), so they are unit-testable without a database.

## Backend layout
| Path | Purpose |
|---|---|
| `app/models.py` | Normalized schema (16 tables) |
| `alembic/versions/` | Migrations — the only way tables are created |
| `app/services/importer.py` | CSV/XLSX parsing and strict validation (no silent fixes) |
| `app/services/import_store.py` | DB conflict snapshot and transactional commit |
| `app/services/analytics.py` | Mastery, distributions, trends, gains, classification |
| `app/services/textbooks.py` | Baseline-adjusted, cluster-robust textbook comparison |
| `app/services/optimizer.py` | Constrained hours reallocation and constraint checks |
| `app/services/ai.py` | Facts builder, LLM call, grounding validation, deterministic explainer |
| `app/services/context.py` | Builds the verified analysis context for a filter set |
| `app/services/report_pdf.py` | PDF rendering (DejaVu Sans for Cyrillic) |
| `app/api/routes.py` | REST endpoints |
| `scripts/generate_synthetic.py` | Deterministic synthetic dataset (seed 20251110) |

## Database
`schools`, `classes` (grade), `class_subjects` (textbook per class+subject), `students` (anonymous external id),
`subjects`, `topics` (grade, order, min/max hours, priority), `topic_prerequisites`, `textbooks`,
`assessments` (date, kind, comparison group), `assessment_results` (item-level; unique student+assessment+topic+item;
CHECK max>0, 0≤score≤max), `class_topic_hours`, `import_batches` (staged preview + validation report),
`recommendation_runs` (params, result, status), `curriculum_allocations` (accepted plan), `generated_reports`, `app_settings`.
All FKs declared with ON DELETE rules; indexes on every FK and on (assessment, topic).

## API (all under `/api`)
| Method | Path | Description |
|---|---|---|
| GET | `/health` | DB connectivity, LLM enabled flag |
| GET | `/meta` | Subjects, grades, classes, textbooks, date range, synthetic flag |
| GET | `/analytics/overview` · `/analytics/topics` · `/analytics/textbooks` | Filters: `subject_id, grade, class_id, textbook_id, date_from, date_to` |
| POST | `/imports/preview` | Multipart upload → validation report + staged batch |
| POST | `/imports/{id}/commit` · `/imports/{id}/discard` | Commit (only if no errors; re-checks conflicts) / discard |
| GET | `/imports` · `/imports/schema` · `/imports/template.csv` · `/imports/demo-dataset.csv` | History, schema, templates |
| PUT | `/topics/{id}` | Update min/max hours and priority |
| GET | `/optimizer/inputs?subject_id&grade` | Current hours, constraints, mastery |
| POST | `/optimizer/run` | Generate and store a recommendation (422 `INFEASIBLE` with details) |
| POST | `/optimizer/evaluate` | Check a manual allocation against all constraints |
| POST | `/optimizer/runs/{id}/decision` | `accept` / `reject` |
| GET | `/optimizer/runs` | History |
| POST | `/ai/insights` | Grounded explanation (LLM or deterministic) |
| POST/GET/DELETE | `/reports`, `/reports/{id}`, `/reports/{id}/pdf` | Create, list, view, export, delete |
| GET/PUT | `/settings` | Analysis thresholds (validated) and LLM status |
| POST | `/admin/reset` | Delete all data; body `{"confirm": "УДАЛИТЬ"}` |

Errors are JSON `{"detail": ...}` in Russian; stack traces are never returned (generic 500 handler, DB-down → 503).

## Security & privacy
Anonymous IDs only (name-like IDs are rejected on import); file type/size/row limits; parameterized ORM queries;
LLM receives aggregates only; API key read from env, never sent to the browser; security headers on both servers;
destructive reset needs a typed confirmation. **No authentication** — single-school MVP (see README limitations).

## Localization
UI strings for the shell, navigation, page headers and states live in `frontend/src/i18n/ru.ts`
(`Dictionary` type); adding `en.ts`/`kk.ts` with the same shape is the path to English/Kazakh. Page bodies still
contain inline Russian text that would need extraction.
