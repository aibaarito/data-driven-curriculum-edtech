# Decision Intelligence architecture (Data-Driven Curriculum 2.0)

Status: implemented on branch `claude/sharp-noether-oeabba` on top of `main@a0a2edb`. This document describes what
the code does. It is not a roadmap. Items that are not implemented are listed at the end.

## 1. Principles

1. **Deterministic engines are the source of truth.** Analytics, graph diagnostics, evidence gates, decisions and
   scenarios are pure Python over verified data. The LLM (optional) only rephrases verified facts.
2. **Extend, do not replace.** `analytics.py`, `textbooks.py` and `optimizer.optimize()` are unchanged in their
   statistical definitions. New modules call them. The single-plan optimizer API (`/optimizer/run`) is
   backward-compatible: the "balanced" scenario returns the same allocation as `/optimizer/run` with the same inputs.
3. **Four kinds of output are kept apart:** *observation* (computed from data), *statistical interpretation*
   (method + uncertainty), *recommendation* (output of explicit decision rules), *hypothesis* (an effect that has
   not been verified). Every decision candidate and passport labels its statements with one of these kinds.
4. **No silent changes to history.** Saved recommendations, interventions and reports carry a frozen evidence
   snapshot and the fingerprint of the evidence they used. When the data changes, they are flagged `stale`. They are
   not recomputed in place.

## 2. Modular monolith: layers and modules

```
Assessment Input ─► Data Quality Gate ─► Evidence Context ─► Analytics ─► Knowledge-Gap Detection
   importer.py        importer.py          evidence.py        analytics.py   analytics.classify_topic
   import_store.py    (+ cycle check)                         textbooks.py
                                   ─► Curriculum Graph ─► Evidence Assessment ─► Decision Intelligence
                                      curriculum_graph.py   evidence.py            decisions.py
                                   ─► Multi-Scenario Optimization ─► Validation ─► Human Review
                                      scenarios.py → optimizer.optimize()           routes (decision endpoint)
                                   ─► Intervention Tracking ─► Outcome Evaluation ─► (new evidence context)
                                      interventions.py           interventions.evaluate()
Presentation: verified evidence ─► ai.py (grounded explanation) / Evidence Passport / report_pdf.py
```

| Layer | Module(s) | Responsibility |
|---|---|---|
| A. API & security | `main.py`, `security.py`, `api/routes.py`, `api/schemas.py`, `observability.py` | Token/loopback access, body limits, typed contracts, stable error codes, request ID + structured access log |
| B. Integrity & provenance | `importer.py`, `import_store.py`, `evidence.py` (`evidence_revision`, `analysis_fingerprint`) | Validation (now including prerequisite cycles), dataset revision, scope fingerprint, frozen snapshots |
| C. Educational analytics | `analytics.py`, `textbooks.py` (unchanged definitions) | Mastery, gains with Bonferroni intervals, class-level textbook inference |
| D. Curriculum graph | `curriculum_graph.py` | DAG validation, deterministic traversal, downstream dependencies, foundational gaps, priority heuristic, chains |
| E. Decision intelligence | `evidence.py` (`assess_topic`, `assess_textbook_pair`, passports), `decisions.py` | Evidence readiness gates; structured, versioned decision candidates with rejected alternatives |
| F. Scenario optimization | `scenarios.py` + `optimizer.py` | Conservative / balanced / gap-focused plans from real optimizer runs; exact diffs; identical-plan detection |
| G. Human decision & outcomes | `interventions.py`, routes | Lifecycle state machine, frozen baselines, outcome evaluation with explicit causal limits |
| H. Grounded AI & reports | `ai.py`, `report_pdf.py`, `report_summary.py` | Unchanged grounding; reports now carry the evidence fingerprint and stale status |

## 3. Contracts

### 3.1 Evidence context (`evidence.py`)
* `evidence_revision(db, subject_id, grade)`: cheap SQL aggregates over the scope's results (count, max id, point sums),
  assessments, topics (constraints/priority), approved prerequisite edges, class hours and textbook assignments,
  plus analysis settings. Hashed with SHA-256, so the revision contains no student identifiers or raw rows.
* `analysis_fingerprint(scope, revision)`: SHA-256 over canonical JSON of `{scope filters, revision hash,
  ALGORITHM_VERSION}`. It is the identity of an analysis result.
* `context_metadata(...)`: `{fingerprint, revision, scope, algorithm_version, settings, synthetic, generated_at}`.
  It is attached to graph, decision, scenario and passport responses.

### 3.2 Evidence assessment
`EvidenceAssessment = {category, reasons[], dimensions{...}, allows_action}` with category ∈
`supported | exploratory | insufficient | incomparable | stale`. A category describes how ready the evidence is.
It is **not** a probability that an intervention works.

Topic rules (`assess_topic`, thresholds from settings):
* `insufficient`: no outcome data, or fewer than `min_students_topic` students.
* `supported`: enough students, at least 2 classes, matched pre/post pairs with a tested direction
  (`increase|decline|inconclusive`), and pairing coverage of at least 50% of students.
* `exploratory`: everything else with enough students, for example no baseline, a single class, untested gains or
  low pairing coverage.
* `stale`: only applied to saved artifacts whose fingerprint differs from the current one.

Textbook pairs (`assess_textbook_pair`): no common items or disjoint grades gives `incomparable`. A verdict of
`observed_difference` gives `exploratory` or `supported`, following the existing `evidence_level`. Anything else is
`insufficient`. A winner is never passed on for `incomparable` or `insufficient` pairs.

### 3.3 Evidence Passport
`{subject_kind, title, observation[], statistics{}, method, dataset{fingerprint, revision, scope, synthetic},
sample{students, classes, paired}, uncertainty[], gate{category, allows_action, reasons}, strengthen[], kinds}`.
A passport is generated for topics (`GET /api/evidence/topics/{id}`), textbook pairs (`GET /api/evidence/textbooks`),
decision candidates and scenario rows.

### 3.4 Curriculum graph (`curriculum_graph.py`)
Nodes are topics of one subject, optionally limited to one grade. Prerequisites in other grades of the same subject
appear as `in_scope=false` context nodes. Edges are the **existing** `topic_prerequisites` rows. Migration
`b7c1d2e3f4a5` adds `origin` (`import|expert|suggested`), `review_status` (`approved|pending|rejected`) and
`created_at` to those rows. Only `approved` edges take part in diagnostics and the optimizer.

Validation runs both on import and on edge creation. It rejects self-edges, duplicates, unknown topics,
cross-subject edges and **cycles** (iterative DFS that reports the cycle path). Traversal is deterministic:
Kahn's algorithm with a `(grade, order, code)` tie-break.

**Priority heuristic (documented, not a predictor):**
```
gap        = clip((target − mastery) / target, 0, 1)            (0 when mastery unknown)
curriculum = (priority − 1) / 2                                  ∈ [0, 1]
dependency = downstream_count / max_downstream_in_scope          ∈ [0, 1]
evidence   = {supported 1.0, exploratory 0.6, insufficient 0, incomparable 0, stale 0}
score      = 100 · evidence · gap · (0.6 + 0.2·curriculum + 0.2·dependency)
```
A topic at or above target scores 0. Insufficient evidence scores 0, so no automatic action is taken, while the node
stays visible with its own reason. A **foundational gap** is a below-target topic that has at least one
below-target topic downstream. The text says the prerequisite *precedes* those topics. It never says the
prerequisite *caused* their weakness.

### 3.5 Decision candidate (`decisions.py`)
```
{id (sha256 of fingerprint+topic+action, 16 hex), topic, problem{code,label}, evidence{EvidenceAssessment},
 action{code,label}, secondary_actions[], rejected_alternatives[{code, reason}], observations[] (kind=observation),
 interpretation (kind=statistical_interpretation), hypothesis (kind=hypothesis, never asserted), limitations[],
 required_review, constraint_impact{balanced_delta, sensitivity{minus, plus}}, priority{score, components},
 version{algorithm, fingerprint}}
```
Actions are `review_methodology`, `increase_hours`, `reallocate_hours`, `add_diagnostic_assessment`,
`review_prerequisites`, `review_textbook`, `collect_more_evidence` and `maintain`. The rule table is in
`docs/ANALYTICS.md` § Decision rules. A significant decline is **never** answered with more hours.

### 3.6 Scenarios (`scenarios.py`)
Three plans are produced by calling `optimizer.optimize()` with explicit, reported parameters:

| Scenario | max_change_pct | Hold set (policy `hold_without_evidence`) | Need weight |
|---|---|---|---|
| conservative | ½ × base | base + topics whose evidence is not `supported` | 1 |
| balanced | base (settings) | base (no reliable data, or significant decline) | 1 (= `/optimizer/run`) |
| gap_focused | min(100, 1.5 × base) | base | 1 + 0.25·min(weak_downstream, 4)/4 |

Hard constraints (total, min/max, locks, 0.5 h, ≥ 0) are enforced by `optimize()` in every scenario and checked again
by `check_allocation()`. A policy infeasibility in one scenario is returned as that scenario's structured error and
does not affect the others. Two scenarios with identical allocations are reported as `identical_to`, with the reason.
Preview never writes to the database. Save recomputes on the server, checks that the client's `fingerprint` still
matches (`409 STALE_SCENARIO` otherwise), and is idempotent on `idempotency_key`.

### 3.7 Lifecycle (`interventions.py`)
```
Recommendation run: proposed ─► accepted (approved) | rejected                         (existing table + audit)
Intervention:       planned ─► implemented ─► awaiting_outcome ─► evaluated
                    planned ─► cancelled;  implemented ─► cancelled
```
An intervention can only be created from an **accepted** run (one per run). Illegal transitions return `409
INVALID_TRANSITION`. Every transition is written to `audit_events`. The intervention freezes the run's evidence
snapshot (topic mastery, gains, students, fingerprint) at creation.

**Outcome evaluation:** affected topics are compared before and after `implemented_on` for the same grade and
subject. The output includes descriptive change against the frozen baseline, a paired comparison for students who
appear in both periods (t-interval, Bonferroni over the affected topics) and missingness. It always says that there
is **no comparison group** and that the design gives association, not causal impact. If there is no post-period data,
the status stays `awaiting_outcome`.

## 4. Persistence (migration `b7c1d2e3f4a5`, additive and reversible)
* `topic_prerequisites` + `origin`, `review_status`, `created_at` (defaults keep existing rows `import/approved`).
* `recommendation_runs` + `scenario_key`, `evidence_fingerprint`, `evidence_snapshot` (JSONB), `idempotency_key`
  (unique), `review_note`.
* `interventions`: FK `run_id` → `recommendation_runs` (RESTRICT, unique), FK `subject_id`, status CHECK, dates,
  frozen `baseline` JSONB, `evaluation` JSONB, `synthetic`, timestamps, indexes on `(subject_id, grade)` and status.
* `audit_events`: entity type/id, action, from/to status, sanitized detail, timestamp; indexed by entity.
Existing migrations are untouched.

## 5. Failure model
| Failure | Behavior |
|---|---|
| Cyclic / self / unknown / cross-subject prerequisite | Import error `CYCLIC_PREREQUISITE` etc.; API `422 GRAPH_INVALID` with the cycle path |
| Insufficient evidence | Category `insufficient`, `allows_action=false`, action `collect_more_evidence`; hours held |
| Incompatible textbook comparison | `incomparable`; no winner; descriptive only |
| Hard infeasibility / policy infeasibility | Per-scenario `{code: INFEASIBLE | POLICY_INFEASIBLE, message, details}` |
| Stale scenario save | `409 STALE_SCENARIO` |
| Retry of save | Same `idempotency_key` gives the same run (`200`, `idempotent_replay=true`) |
| Invalid lifecycle transition | `409 INVALID_TRANSITION` |
| LLM timeout/429/5xx/invalid JSON | Existing bounded attempts, then deterministic explainer (unchanged) |
| DB error | Transaction rolled back; sanitized 500/503 (unchanged handlers) |

Observability: `RequestContextMiddleware` assigns an `X-Request-ID` (or accepts a safe client value). It logs one
structured line per request: id, method, route template, status and duration in ms. Bodies, query values, tokens and
student identifiers are never logged.

## 6. Not implemented (explicitly)
* Knowledge tracing: the synthetic dataset has 2–3 assessment occasions per topic and no ordered attempt stream,
  which is not enough to fit or evaluate a KT model. Statistical mastery analysis stays in place.
* OR-Tools CP-SAT backend: not added. The projection optimizer is exact on hard constraints and deterministic, and no
  certified-optimal claim is made.
* Kazakh localization, CASE identifiers (topic `code` is the future mapping key), per-school isolation and user
  accounts.
