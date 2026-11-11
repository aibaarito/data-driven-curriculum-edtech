# Analytical methods

All numbers are computed by deterministic backend code (`backend/app/services/`). Language models never compute or alter
a number. Results describe associations in observational, non-randomised school data — never causal effects.

## Mastery and weighting — `analytics.topic_analytics`
| Field | Definition | Weighting |
|---|---|---|
| `mastery` | Σ obtained / Σ available points × 100 over outcome assessments (`post`, `current`) | pooled points: larger assessments and larger classes weigh more |
| `mean`, `median`, distribution | per-student percentage (student × topic, points within the student) | every student equal |
| `class_mean` | mean of class means of the student percentages | every class equal |

`pre` diagnostics are a baseline only. Classification (`difficult` / `watch` / `ok`) uses the pooled `mastery`
with configurable thresholds and a minimum number of students. This is a documented choice, not a defect: when
pooled and class-weighted values diverge strongly, class composition is driving the pooled number — the UI shows both.

## Learning gains — `analytics.learning_gains`, `gain_stats`
* Pairs: the same student, same topic, `pre` and `post` of the same `comparison_group`. Unrelated tests are never compared.
* At least `min_students_topic` pairs are required; fewer → direction **insufficient** (no test).
* **Multiple comparisons**: the family is every topic in the current analysis view with enough pairs (k). Each interval
  uses the Bonferroni level 1 − 0.05/k; `p_value_adjusted = min(1, k·p)`. The direction is read from that interval, so
  interval, adjusted p-value and conclusion always agree.
* **Direction** (sign-aware): `increase` (interval > 0), `decline` (interval < 0), `inconclusive` (interval contains 0 —
  this is *not* evidence of no effect), `insufficient`. A decline is never described as progress anywhere (analytics,
  optimizer, explanations, AI facts, reports).
* Interpretations: `low_but_improving`, `low_declining`, `low_no_measurable_gain` (= inconclusive), `low_gain_insufficient`,
  `low_no_baseline`, `ok_but_declining`.

## Textbook comparison — `textbooks.compare_textbooks`
**Design.** A textbook is assigned to whole classes; students in a class share teacher, timetable and peers. The number
of independent replicates is the number of classes, so inference uses classes as units (the audit showed that
student-level/cluster-robust inference with 2–3 classes per textbook gave 9–14% false "differences").
1. Only textbooks used in the same grade and subject are paired; only outcome items (assessment × topic) taken by both
   are used (controls for assessment difficulty).
2. Class table: per class, mean outcome %, mean baseline %, mean gain (post − pre). Classes with fewer than 5 students
   with data are excluded and reported. Classes enter unweighted (each class is one replicate; unequal class sizes do not
   let one large class dominate).
3. **Adjusted difference**: OLS on class means `y_c = b0 + b1·textbook_c + b2·baseline_c (+ grade dummies)`, classical
   SE, t with df = G − p. Requires df ≥ 2 (else "not estimable").
4. **Gain difference**: Welch test on class-mean gains (Satterthwaite df), robust to unequal variances between textbooks.
5. **Raw difference**: Welch on class means of the outcome. Student-level means, Hedges' g and the summary table are
   labelled *descriptive*.
6. Several textbook pairs in one view → Bonferroni level 1 − 0.05/m for all their intervals.
7. **Verdict** `observed_difference` only if: ≥ max(setting, 3) eligible classes per textbook (stored settings below 3
   are raised at load time and reported), ≥ `min_students_textbook` students per textbook, a baseline, estimable models,
   and both the adjusted and the gain interval exclude 0 **with the same sign**. Otherwise «Недостаточно данных…» with
   reasons. Fewer than 10 classes in total → labelled *exploratory* («Предварительный вывод»).
8. Confounders always listed: non-random assignment (teacher, class composition, timetable), baseline gap, hours gap,
   class-size gap, and measurement error of the baseline (residual confounding — the adjustment can be incomplete; the
   adjusted and gain estimates may disagree, e.g. Lord's paradox, in which case no verdict is given).

**Simulation** (`backend/scripts/simulate_textbook_fpr.py --sims 400`, seed 20261111; two textbooks, one topic,
class sizes 18–30, ability SD 13, residual SD 7, class effects on level and on gain each N(0, class SD); MC s.e. in
brackets):

| classes / textbook | class SD | P(difference) when true effect = 0 | P(difference) when true effect = 6 p.p. |
|---|---|---|---|
| 3 | 1.5 | 0.018 (0.007) | 0.365 (0.024) |
| 3 | 4 | 0.022 (0.007) | 0.120 (0.016) |
| 3 | 8 | 0.022 (0.007) | 0.055 (0.011) |
| 4 | 1.5 | 0.022 (0.007) | 0.647 (0.024) |
| 4 | 4 | 0.007 (0.004) | 0.198 (0.020) |
| 4 | 8 | 0.025 (0.008) | 0.117 (0.016) |
| 6 | 1.5 | 0.035 (0.009) | 0.930 (0.013) |
| 6 | 4 | 0.013 (0.006) | 0.415 (0.025) |
| 6 | 8 | 0.040 (0.010) | 0.172 (0.019) |

False-positive rates are at or below the nominal 5% (conservative, because both estimates must agree). The price is
low power with few classes: a real 6 p.p. effect is usually reported as "insufficient evidence" unless there are many
classes and small between-class differences. Before the fix the same no-effect scenarios gave 6–14%.

## Hours optimizer — `optimizer.optimize`
One plan per grade (all classes follow it). Baseline = median of the classes' imported hours rounded to 0.5 h (the
spread across classes is shown); 0.5 h is the planning unit, so the integer-unit arithmetic keeps totals exact.
* **Hard constraints** (never relaxed; violations → 422 `INFEASIBLE`): total, min/max, locks, 0.5 h steps, non-negative.
* **Policies** (on by default; if they make the request infeasible → 422 `POLICY_INFEASIBLE` unless the request sets
  `allow_policy_relaxation`, then the *minimal* set of policies is relaxed and reported with affected topics):
  `max_change` (±max_change_pct per step), `hold_without_evidence` (no reliable data or significant decline → keep hours;
  more hours are not assumed to fix a decline), `protect_prerequisites`, `protect_below_target`.
* Objective: need = priority × max(0, target − mastery)/100 (×1.25 for prerequisites of weak topics); below-target
  topics grow by need, above-target topics shrink by surplus; uniform shift by bisection; largest-remainder rounding with
  a stable tie-break (larger need, then lower topic id) — independent of input order.
* Explanations cite mastery, gain direction and the real reason for each change (redistribution vs. a reduced total vs.
  a relaxed policy). No predicted improvement is ever produced.

## AI explanations — `ai.py`
Facts are keyed by stable entity ids (`topic.T7-05.mastery`, `comparison.0.gain_diff`, `plan.total_hours`, …). An LLM may
only return findings bound to one entity, with prose that references values through placeholders (`{{mastery}}`,
`{{name}}`, `{{overview.students}}`); raw digits and literal entity names are rejected, placeholders are rendered
deterministically with units. Every rendered finding — LLM or deterministic — must contain only numbers of its own entity
(no small-number exemptions). Heuristic guards additionally reject promises/causal claims, statements contradicting a
topic's status or gain direction, and naming a "better" textbook when evidence is insufficient. One retry, then the
deterministic explainer. The handoff records one successful live Gemini request; the independent November verification used mocks only.
HTTP failures fall back after one attempt; invalid output/envelopes have at most two attempts. `attempts` reports the
actual number of calls, including on fallback. Semantic guards remain heuristic. The 400-simulation-per-scenario
table above was independently reproduced on 11 November 2026; it validates those simulated conditions, not all
possible school data or causal educational effectiveness.

## Decision intelligence (v2.0, `ALGORITHM_VERSION = ddc-2.0.0`)
Full contracts: [DECISION_INTELLIGENCE_ARCHITECTURE.md](DECISION_INTELLIGENCE_ARCHITECTURE.md).

### Output kinds
Every decision-layer statement belongs to exactly one kind:

| Kind | Example | Source |
|---|---|---|
| Observation | "Mastery 40.9% for 156 students in 6 classes" | computed from data |
| Statistical interpretation | "Change not established (99.4% CI −5.2…6.5)" | stated method + uncertainty |
| Recommendation | "Review the teaching methodology" | decision rule table below |
| Hypothesis | "The action *may* raise mastery — not verified" | never asserted as a result |

### Evidence readiness (`evidence.assess_topic`)
| Category | Topic rule |
|---|---|
| `insufficient` | no outcome data, or < `min_students_topic` students. Actions are blocked and hours are held |
| `exploratory` | enough students, but one of: single class, no matched pre/post, < `min_students_topic` pairs, pairing coverage < 50% |
| `supported` | enough students, ≥ 2 classes, tested pre/post direction, coverage ≥ 50% |
| `incomparable` | textbook pairs without common items or in different grades. No winner is computed |
| `stale` | a saved artifact whose evidence fingerprint differs from the current one |

These are readiness labels, not probabilities.

### Decision rules (`decisions.topic_candidates`)
| Problem (from existing interpretation codes) | Primary action | Rejected alternative (reason shown) |
|---|---|---|
| insufficient evidence | collect more evidence (+ diagnostic) | more hours: diagnosis not established |
| low + significant decline / ok + significant decline | review methodology | more hours: the cause is unknown, so hours are held unless an expert overrides |
| low + change not established | review methodology (+ hours only inside a reviewed scenario) | hours as the primary remedy |
| low + no baseline / too few pairs | additional diagnostic assessment | methodology review: cannot separate weak start from weak learning |
| low + significant increase | increase hours by reallocating within the budget | methodology review is not the first priority |
| weak topic that precedes weak topics | + "consolidate before dependent topics" | — |
| topic with weak prerequisites | + "check prerequisite mastery" | — |
| textbook pair with an observed difference | review textbook suitability | replace textbook: the association is observational |

Each candidate carries the balanced-plan hour change for the topic. It also shows the change when the budget is
±2 h (an actual optimizer re-run), so the user can see what would happen if the available hours changed.

### Curriculum priority heuristic (`curriculum_graph.priority_score`)
`score = 100 · evidence · gap · (0.6 + 0.2·curriculum + 0.2·dependency)`. The components are
`gap = clip((target − mastery)/target, 0, 1)`, `curriculum = (priority − 1)/2`,
`dependency = downstream / max_downstream` and `evidence ∈ {1, 0.6, 0}`.
It is a transparent ranking aid. It was not trained and does not predict achievement.
On the demo, grade 7 ranks «Формулы сокращённого умножения» first (38.6; it precedes the weak topic «Разложение на
множители»).

### Scenarios (`scenarios.build_scenarios`)
| Scenario | Change band | Extra holds | Need weight |
|---|---|---|---|
| Conservative | ½ × setting | topics whose evidence is not `supported` | 1 |
| Balanced | setting | — | 1 (identical to `POST /optimizer/run`) |
| Gap-focused | min(100, 1.5 × setting) | — | 1 + 0.25·min(weak downstream topics, 4)/4 |

The same projection algorithm (bisection + largest remainder) is used throughout. No scenario claims global
optimality. Identical allocations are reported as identical, with the reason.

### Outcome evaluation (`interventions.evaluate`)
The analysis is a before/after comparison on the affected topics of the same subject and grade, split at
`implemented_on`. It reports:
* descriptive change against the **frozen** baseline mastery;
* a paired t-interval for students seen in both periods (Bonferroni over the affected topics);
* lost and new students;
* whether recomputing the before-period still matches the frozen snapshot.

There is no comparison group, so the result is always labelled as an observed association. It is never described as
"impact".

**Simulated follow-up file.** `scripts/generate_followup.py` (seed 20261111) generates
`synthetic_followup.csv`. The scores are binomial draws around each student's A7-POST level **+3 p.p. (a simulation
parameter)**. Any "change" measured on it exists by construction and is not validation.
