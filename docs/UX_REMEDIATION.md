# UX corrections from the 11 November 2026 design review

Source copy: this working copy (`data-driven-curriculum-mvp/`), branch `ux/design-review-fixes`, based on `dc8b6e9`.
Review: `../ux-review-2026-11-11/DESIGN_REVIEW.md`. The original demonstration on port 3010 (scratch workspace,
database `ddc_e2e`) and this copy's earlier preview on 3011 were **not** modified, rebuilt, restarted, migrated or reset.

Behavioural checks below are automated observations on synthetic data. User-comprehension benefits remain hypotheses
until tested with participants (see the review's validation plan). No full WCAG audit or screen-reader session was run.

## Isolated verification stack

| Purpose | Database (PostgreSQL 55434, verification instance) | API | Web |
|---|---|---:|---:|
| Backend pytest | `ddc_ux_test` (new) | in-process | — |
| Browser / screenshots / PDFs | `ddc_ux_browser_test` (new) | 8012 | 3012 |

The 3012 frontend is a production build of an APFS clone of `frontend/` under `verification/ux-fixes/frontend-build`
so the 3011 preview's `.next` stayed untouched. Private tokens are in `verification/ux-fixes/ux.env` (mode 0600,
git-ignored). LLM provider disabled; every AI state in the browser tests uses mocked `/api/ai/insights` responses.

## Findings → changes → verification

| # | Implemented | Verification | Remaining limitations |
|---|---|---|---|
| F1 | Overview trend API now returns `grades` and `comparison_group` per assessment. The chart shows **unconnected markers**, one series per population (distinct colour **and** shape), an HTML legend, a visible caution («Оценивания относятся к разным группам учеников… не показывает индивидуальный прогресс») with a link to paired analysis, and a data table (assessment, group, date, type, pupils, mastery). Topic-page per-assessment chart is also unconnected. | `observationSeries` unit tests (grade 7 and 8 never share a series); E2E asserts `data-series="g7,g8"` and every line path has `stroke="none"`; backend test of population metadata. | Same-grade assessments are also not joined: metadata does not prove item comparability. Cohort tracking is not modelled. |
| F2 | `useScopedRequest`: each result stores normalized scope key, label and request id; a newer request supersedes older ones; scope change aborts the in-flight request and ignores any late response; result header «Пояснения для: …»; stale banner «Фильтры изменены…» with refresh; errors carry their scope. | 5 hook tests incl. B-before-A reverse completion; E2E with a 2.5 s mocked grade-7 response, switch to grade 8, generate, wait past A's completion → result stays grade 8. | Aborting stops the browser waiting; the server may still finish its call (stated in the UI). |
| F3 | «Принять рекомендацию системы» with `data-run-id`, `aria-describedby` text naming run #, total; summary strip (run #, subject, grade, total, changed topics, relaxed rules); «Открыта из истории (создана …)» vs «только что сформирована»; note when the draft form total differs. Manual variant moved to a separate dashed panel «Ручной вариант · проверка без сохранения» with «Проверка не изменяет сохранённую рекомендацию #N». Changed rows first, «Показать только изменённые / все темы». | E2E: label equals, decision POST URL contains the displayed run id and body `{decision: accept}`; manual evaluation issues no run/decision writes and status stays «Предложена»; history-opened run labelled; row toggle keeps all rows reachable. | Manual plans still cannot be saved (out of scope by design). |
| F4 | Shared `summarizeGain`: estimate + status («установлен рост», «установлено снижение», «изменение не установлено», «недостаточно пар для оценки») + interval level, pairs, and «Это не доказывает отсутствие эффекта». Used on topics, dashboard, optimizer inputs, on-screen report and (same words) PDF and discussion text. Older snapshots without a stored direction show «статус изменения в этом снимке не сохранён». | Unit tests for every direction and legacy; backend `gain_phrase` tests; E2E report cell for T7-05; E2E legacy snapshot (direction removed via mocked response) shows the unavailable wording and no conclusion. | Older snapshots that predate stored intervals show only the estimate + unavailable status. |
| F5 | Navigation carries all filters (`Suspense`-wrapped, per Next 16 docs). Screen rules in `lib/scope.ts`: textbooks ignore class/textbook; optimizer uses subject+grade only and explains «План составляется для всей параллели 7 по предмету «Математика»… Здесь не применяется: класс 7А». Compact «Группа анализа: …» summary, «Дата оценивания: с/по», «Сбросить фильтры», filter changes are history entries (Back restores scope), dependent filters cleared only when incompatible, contradictions reported with «Убрать этот фильтр». Optimizer subject/grade now live in the URL. | Unit tests for labels, carried query, inapplicable filters, conflicts; E2E topics→textbooks→reports with Back, class filter explained on textbooks and optimizer and restored on topics, grade change + Back, conflict removal, reset. | Exhaustive filter combinations not tested. |
| F6 | «Что проверить в первую очередь» directly under KPIs: up to two topics from the existing classification (difficult, else watch) with mastery, change qualification and links «→ Анализ темы» (opens the topic) and, when an existing hours opportunity exists, «→ Оптимизатор». List renamed «Темы с самым низким освоением», full names wrap. Explicit chart order toggle «По программе / По освоению». Opportunities moved above lower-priority charts/prose. | E2E: first priority item is «Формулы сокращённого умножения» with «изменение не установлено» and a link to `topic=T7-05`, link opens its detail. | No new ranking algorithm; textbook verdict prose on the overview is unchanged (moved lower). |
| F7 | Russian titles for every importer code, Russian column labels next to exact headers, issues grouped by row with file-level issues first, headline «Исправьте 2 строки. Найдено 4 ошибки; данные ещё не импортированы.» (says «не менее» when the server truncated the list), «блокирует импорт» vs «Предупреждения — не блокируют импорт», warnings grouped by cause (hours replacement keeps class/topic and old → new), codes in «Технические сведения». | Unit tests for counts/truncation/grouping/labels; E2E invalid file: headline, 2 row groups, Russian title, header label, identifier not echoed, codes present but collapsed. | Spreadsheet correction export / column mapping not added. |
| F8 | Compact verdict first: headline («Предварительная связь, не доказательство эффекта» / «Недостаточно данных для вывода о различии»), А/Б legend, classes and pupils, adjusted Б − А with the **API's** interval level and comparison-family note, short non-causal caution. Consistent cards «Без поправки», «С поправкой на исходный уровень», «Разница прироста», «Разница исходного уровня». Reasons and confounders always visible; ANCOVA/Welch/df/p/Hedges and full verdict text in «Как рассчитано». | E2E: all-grades and grade-7 pages display each scope's own `ci_level` from the API; grade 8 shows insufficient reasons visibly; existing verdict assertions pass. | No statistical change. |
| F9 | Accessible status «Готовим пояснения для выбранной группы: …», real elapsed seconds (no ETA/percent), «Прекратить ожидание» with honest wording, previous result labelled during refresh. Backend adds `fallback_kind` (`not_configured` / `rejected` / `provider_error`) and `fallback_detail`; primary reasons are plain Russian (exception class only in «Технические сведения»). Badge «Числа сверены с расчётами» + «не подтверждает причинные выводы и не гарантирует корректность каждого утверждения». Facts shown as «Тема — показатель: значение с единицей» with links that keep the result's scope; raw keys in a disclosure. | Backend tests for the three causes and no class names in primary text; E2E with mocked waiting, provider failure, rejected output, model output and stop-waiting; fact label/unit/link. | No live Gemini call was made. |
| F10 | Below 768 px topics are summary cards (full name, code, pupils, mastery bar, change status, status) with «Подробнее» opening a bottom Sheet (named dialog, Escape closes, focus returns to the opening button); optional full table with scroll cue; sticky topic column on desktop table; collapsible filter panel with scope always visible; filter header wraps. | E2E at 390 and 494 px: card association, Sheet open via keyboard, focus return, no page overflow; optimizer editing at both widths. Measured page overflow 0 px on 8 screens at 720/390/360/320 px. | Emulated viewport widths, not real browser zoom; touch not studied. |
| F11 | Warning marks #f59e0b → #b45309, neutral #94a3b8 → #64748b, teal → #0d9488; chart data tables; Settings hint/error IDs with `aria-describedby`/`aria-errormessage`, announced error summary, RHF focuses first invalid field; optimizer field/row errors linked; upload error linked; focus rings on nav, brand, disclosures, toggles, topic buttons, date inputs; Sheet/Dialog «Закрыть». | Measured on white card: #b45309 **5.02:1** (was 2.15:1), #e11d48 4.70, #4f46e5 6.29, #0d9488 3.74. Settings RTL test (focus, error id, summary). All 7 settings inputs' described-by ids resolve. Keyboard Tab through 40 stops on topics and optimizer: every stop has a visible indicator (Chrome's native date-picker button verified by screenshot). | No screen-reader session; full-site contrast not audited. |
| F12 | Default title from stored scope («Математика · 7 класс · все классы · весь период»); «Снимок результатов на …» line; «Выводы для обсуждения» computed by the server **from the stored snapshot only** (observation / recommendation / limitation; plan recommendation only when the snapshot holds a scoped plan). PDF: same section, page footer «Стр. N из M», column widths fit the frame without split words, conditional page breaks instead of orphan headings/gaps. | Backend tests: title, discussion kinds, no recommendation for grade-7-without-plan and all-grades reports, legacy snapshot, page numbering on every page; four PDFs rendered and inspected. | Older reports keep their timestamp titles (not rewritten). |

## Results

| Check | Result |
|---|---|
| Backend pytest (`ddc_ux_test`) | **244 passed** (238 existing + 6 new) |
| Frontend unit (Vitest) | **59 passed**, 7 files (38 existing + 21 new) |
| TypeScript (`tsc --noEmit`) / ESLint (`src e2e playwright.config.ts`) | Passed / no findings |
| Production build (`next build`) | Passed |
| Playwright, isolated 3012 | **16 passed** (8 existing + 8 new), repeated 4 times on successive builds |

One existing test assertion changed for intended wording: the PDF header regex now accepts «Освоение, %».
Existing E2E steps were updated to the new labels (accept button, `Открыть отчёт`, `Разница прироста`, template mode,
mobile cards) and strengthened (run-id agreement, Russian import summary). No assertion was removed.

Defects found while verifying and fixed: Sheet without a Radix trigger did not return focus; 35 px page overflow at
320 px from the filter header; date inputs showed no ring on keyboard focus; PDF header words overflowed and table
cells split words; unconnected series lost their legend symbols.

## Artifacts (local, git-ignored)

`verification/ux-fixes/`: `before/` (read-only captures of the unchanged 3011 preview), `after-screens/` (same
routes on 3012), `after/` (E2E screenshots incl. `ux-*`), `pdf-final/` (4 reports + rendered pages),
`measurements.json`, `e2e-final.log`, `build.log`.
