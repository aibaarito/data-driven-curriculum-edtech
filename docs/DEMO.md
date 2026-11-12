# Demo scripts (synthetic data)

Moved unchanged from the previous README. All figures below come from the bundled **synthetic** dataset
(seed 20251110, school `SYNTH-DEMO`) and apply only to that dataset. Say aloud that the data is synthetic.

## Full walkthrough (≈5 min)
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

## Three-minute decision-intelligence demo (v2.0)
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
