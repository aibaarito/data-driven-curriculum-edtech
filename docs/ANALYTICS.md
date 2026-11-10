# Analytical methods

All numbers are computed by deterministic backend code (`backend/app/services/`). The LLM never computes or alters a number.

## Data model of a result
One row = points obtained by one anonymous student on one topic (optionally one item) of one assessment.
Assessment kinds: `pre` (diagnostic before instruction), `post` (final), `current` (during the year).
`comparison_group` links a `pre` and a `post` assessment that measure the same skills.

## Topic mastery — `analytics.mastery`
```
mastery = Σ obtained points / Σ available points × 100
```
* computed over **outcome** assessments only (`post`, `current`); `pre` is the baseline, not mastery;
* validated on import: `max_score > 0`, `0 ≤ score ≤ max_score` (also DB CHECK constraints);
* empty denominators return "no data" instead of dividing by zero.

Also reported per topic: mean / median / SD of per-student percentages (student × topic, points-weighted),
95% CI of the mean (t-distribution), number of students and assessments, histogram in 10-point bins,
mastery per assessment (trend).

## Learning gains — `analytics.learning_gains`
Only students who have **both** a `pre` and a `post` result on the same topic in the **same** comparison group are paired.
* mean gain = mean(post% − pre%), 95% CI (t), paired t-test p-value;
* normalized class-average gain g = (post̄ − pr̄e) / (100 − pr̄e) (Hake).

## Topic classification (thresholds configurable in Settings)
| Condition | Status |
|---|---|
| no outcome data | `no_outcome_data` |
| students < `min_students_topic` (10) | `insufficient_data` |
| mastery < `difficult_threshold` (50) | `difficult` |
| mastery < `watch_threshold` (65) | `watch` |
| otherwise | `ok` |

Low results are further split, without causal claims:
* `low_no_baseline` — no diagnostic; weak prior knowledge and instruction problems cannot be told apart;
* `low_but_improving` — significant positive gain: learning happens, slowly;
* `low_no_measurable_gain` — no significant gain: signal for methodological review, cause not established.

## Textbook comparison — `textbooks.compare_textbooks`
1. Only textbooks used in the **same grade and subject** are paired.
2. Only outcome items (assessment × topic) taken by students of **both** textbooks are used (controls assessment difficulty).
3. Raw difference: Welch 95% CI and Hedges' g.
4. Headline: **baseline-adjusted** difference — OLS `outcome% ~ 1 + textbook + pre% (+ grade)` with CR1
   **cluster-robust** standard errors by class and t(G−1) critical values (students in a class are not independent).
5. **Learning improvement**: per-student gain (post% − pre%) on the common topics, paired within the same comparison
   group; per-textbook mean gain with 95% CI and a gain difference `gain ~ 1 + textbook (+ grade)` with cluster-robust
   SEs (Welch fallback, labelled approximate, when there are fewer than 3 classes).
6. Verdict `observed_difference` only if: ≥ `min_students_textbook` (30) per textbook, ≥ `min_classes_textbook` (2)
   classes per textbook, a baseline exists, ≥ 3 classes overall, and the adjusted 95% CI excludes 0.
   and the gain estimate does not point significantly in the opposite direction (Lord's-paradox guard).
   Otherwise: **«Недостаточно данных, чтобы определить, какой учебник эффективнее.»** with the reasons.
7. Confounders always listed: baseline gap, teaching-hours gap, class-size gap (≥ 15%), non-random assignment of classes (teacher, class composition).
   The text explicitly states that the result is an association, not a causal effect.

## Hours optimizer — `optimizer.optimize`
Integer arithmetic in 0.5 h units (the total is preserved exactly).
1. Validation → explicit `InfeasibleError` (min > max, locks outside bounds, total not reachable, total not a multiple of 0.5).
2. need = priority × max(0, target − mastery)/100; ×1.25 for prerequisites of below-target topics.
3. Below-target topics may only grow: d = h × (1 + max_change × need/max_need).
   At/above-target topics may only shrink by their surplus: d = h × (1 − max_change × (mastery − target)/(100 − target)).
   Topics without reliable data (or < min students) keep their hours. Prerequisites of weak topics are never reduced.
4. Projection: bisection on a uniform shift λ so Σ clip(d + λ, lo, hi) = total, then largest-remainder rounding inside bounds.
   If the ±max_change band makes the total unreachable, the band is relaxed to the hard min/max with a warning.
5. Gain evidence: each below-target topic's explanation states its pre→post gain; when the gain is not significant
   the explanation and warnings say that extra hours alone may not help and a methodological review is needed.
6. Every allocation (proposed or manual) is re-checked: total, bounds, locks, 0.5 h steps, non-negativity.
No predicted score improvement is ever produced.

## AI explanations — `ai.generate_insights`
* Input: a flat dictionary of verified aggregate facts (no student identifiers).
* Output schema (`InsightPayload`) validated with Pydantic.
* Grounding check: every cited metric key must exist; every number in the text must equal a fact value
  (±0.05, small integers 0–10 and 95/100 allowed); causal/guarantee wording is rejected.
* One retry with the validation error; then the deterministic explainer (which passes the same check).
