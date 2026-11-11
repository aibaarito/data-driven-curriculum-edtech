# Architecture

```
Browser ──► Next.js 16 (App Router, :3010) ──/api/* proxy──► FastAPI (:8010) ──► PostgreSQL 17
             React 19, Tailwind 4, shadcn/ui,                   SQLAlchemy 2, Alembic,
             Recharts, RHF + Zod                                 pandas / NumPy / SciPy,
                                                                 ReportLab (PDF), httpx (LLM, optional)
```
* The browser only talks to its own origin; `src/app/api/[...path]/route.ts` forwards `/api/*` to FastAPI and adds the
  server-side `API_TOKEN`. The backend URL, API token and any LLM key never reach the browser.
* Access: `AccessControlMiddleware` (token, or loopback-only when no token) and `BodySizeLimitMiddleware` (byte limit
  enforced while the upload streams in); the preview endpoint runs in the thread pool, not on the event loop.
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
| `app/services/evidence.py` | Dataset revision, analysis fingerprint, evidence readiness, Evidence Passports, frozen snapshots |
| `app/services/curriculum_graph.py` | Prerequisite DAG validation, traversal, foundational gaps, priority heuristic, chains |
| `app/services/decisions.py` | Deterministic decision rules → versioned decision candidates |
| `app/services/scenarios.py` | Conservative / balanced / gap-focused plans via `optimizer.optimize` |
| `app/services/interventions.py` | Intervention lifecycle and before/after outcome evaluation |
| `app/observability.py` | X-Request-ID and one sanitized structured access-log line per request |
| `app/api/decision_routes.py` | Decision-intelligence endpoints |
| `app/api/routes.py` | REST endpoints |
| `scripts/generate_synthetic.py` | Deterministic synthetic dataset (seed 20251110) |

## Database
`schools`, `classes` (grade), `class_subjects` (textbook per class+subject), `students` (anonymous external id),
`subjects`, `topics` (grade, order, min/max hours, priority), `topic_prerequisites`, `textbooks`,
`assessments` (date, kind, comparison group), `assessment_results` (item-level; unique student+assessment+topic+item;
CHECK max>0, 0≤score≤max), `class_topic_hours`, `import_batches` (staged preview + validation report),
`recommendation_runs` (params, result, status; since v2 also scenario, evidence fingerprint + frozen snapshot,
idempotency key, review note), `curriculum_allocations` (accepted plan), `generated_reports`, `app_settings`,
`interventions` (lifecycle, frozen baseline, evaluation) and `audit_events` (decisions and transitions).
`topic_prerequisites` carry `origin` (import/expert/suggested) and `review_status` (approved/pending/rejected).
Migration `b7c1d2e3f4a5` is additive and reversible.
All FKs declared with ON DELETE rules; indexes on every FK and on (assessment, topic).

## API (all under `/api`)
| Method | Path | Description |
|---|---|---|
| GET | `/health` | DB connectivity, LLM enabled flag |
| GET | `/meta` | Subjects, grades, classes, textbooks, date range, synthetic flag |
| GET | `/analytics/overview` · `/analytics/topics` · `/analytics/textbooks` | Filters: `subject_id, grade, class_id, textbook_id, date_from, date_to`. Overview trend points carry `grades` and `comparison_group` (separate observations, never one trajectory) |
| POST | `/imports/preview` | Multipart upload → validation report + staged batch |
| POST | `/imports/{id}/commit` · `/imports/{id}/discard` | Commit (only if no errors; re-checks conflicts) / discard |
| GET | `/imports` · `/imports/schema` · `/imports/template.csv` · `/imports/demo-dataset.csv` | History, schema, templates |
| PUT | `/topics/{id}` | Update min/max hours and priority |
| GET | `/optimizer/inputs?subject_id&grade` | Current hours, constraints, mastery |
| POST | `/optimizer/run` | Generate and store a recommendation; `allow_policy_relaxation` opt-in; 422 `INFEASIBLE` (hard) or `POLICY_INFEASIBLE` |
| POST | `/optimizer/evaluate` | Check a manual allocation: hard `constraints` + advisory `policy_checks` |
| POST | `/optimizer/runs/{id}/decision` | `accept` / `reject` |
| GET | `/optimizer/runs` | History |
| POST | `/ai/insights` | Grounded explanation (LLM or deterministic); `fallback_kind` = `not_configured` / `rejected` / `provider_error`, technical cause in `fallback_detail` |
| POST/GET/DELETE | `/reports`, `/reports/{id}`, `/reports/{id}/pdf` | Create, list, view, export, delete. Default title from the stored scope; `discussion` (observation / recommendation / limitation) is derived from the stored snapshot only |
| GET/PUT | `/settings` | Analysis thresholds (validated) and LLM status |
| POST | `/admin/reset` | Delete all data; only with `ENABLE_DATA_RESET=true`, header `X-Admin-Token`, body `{"confirm": "УДАЛИТЬ"}` |
| GET | `/admin/integrity` | Read-only invariant report (legacy data, stale previews) |

### Decision intelligence (v2)
| Method | Path | Description |
|---|---|---|
| GET | `/context` | Evidence context (fingerprint, revision, algorithm version) for filters |
| GET | `/evidence/topics/{id}` · `/evidence/textbooks` | Evidence Passports; `422 SCOPE_MISMATCH` for a topic outside the requested subject/grade |
| GET | `/curriculum/graph?subject_id&grade` | Nodes with diagnostics, edges, validation, ranking, chains |
| POST/DELETE | `/curriculum/prerequisites`, `/curriculum/prerequisites/{id}` · POST `…/{id}/review` | Add (expert → approved, suggested → pending), review, delete; `422 GRAPH_INVALID` (cycle, cross-subject, self), `409 DUPLICATE_EDGE` |
| GET | `/decisions/overview?subject_id&grade` | Readiness, decision candidates, graph summary, plans awaiting approval, interventions |
| POST | `/optimizer/scenarios/preview` | Three scenarios; **no writes** |
| POST | `/optimizer/scenarios/save` | Recompute + store as proposed run; `409 STALE_SCENARIO`, `409 IDEMPOTENCY_CONFLICT`, idempotent replay |
| GET | `/optimizer/runs/{id}` | Run with frozen evidence snapshot, `evidence_status` (current/stale/unknown) and audit trail |
| POST | `/optimizer/runs/{id}/decision` | (extended) `note`; accepting a stale run needs `acknowledge_stale` (`409 STALE_RECOMMENDATION`) |
| POST/GET | `/interventions`, `/interventions/{id}` | Create from an accepted run (`409 INVALID_TRANSITION` otherwise); list; detail with audit |
| POST | `/interventions/{id}/transition` · `/interventions/{id}/evaluate` | Lifecycle (`409 INVALID_TRANSITION`); before/after evaluation |
| GET | `/imports/demo-followup.csv` | **Simulated** follow-up assessment for demonstrating evaluation |

Structured errors use `{"detail": {"code", "message", "details"}}`. Reports now store an evidence fingerprint, and
`GET /reports/{id}` adds `evidence_status`.

Errors are JSON `{"detail": ...}` in Russian; stack traces are never returned (generic 500 handler, DB-down → 503).

## Security & privacy
Anonymous IDs only (name-like IDs are rejected on import and validation messages never echo raw values); file
type/size/row limits incl. uncompressed `.xlsx` size; parameterized ORM queries; LLM receives aggregates only; secrets
from env only (compose requires them, no fallbacks); security headers on both servers; destructive reset disabled by
default and token-protected. Single shared token, no user accounts or per-school isolation (see README).

## Localization
UI strings for the shell, navigation, page headers and states live in `frontend/src/i18n/ru.ts`
(`Dictionary` type); adding `en.ts`/`kk.ts` with the same shape is the path to English/Kazakh. Page bodies still
contain inline Russian text that would need extraction.

## Verification and local startup

See [VERIFICATION.md](VERIFICATION.md) for independently run checks and unverified areas.
`backend/scripts/local_services.py` parses the private backend environment, propagates the server token, waits
for proxy readiness, and records only process identity metadata. Stop targets only this checkout’s recorded
processes and leaves PostgreSQL running. Docker forwards the OpenAI-compatible base URL and timeout; Docker
image execution remains unverified.
