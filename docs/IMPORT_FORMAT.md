# Import format and integrity rules

One row = points of one anonymous student on one topic (or one item of a topic) in one assessment.
Columns are listed on the Import page and in `GET /api/imports/schema`.

## Flexible guided import (Импорт данных page)

The importer accepts common school spreadsheets without converting them to the template first. It recognises common
layouts and proposes an interpretation; the user confirms or corrects every part; only analyses the data actually
supports are offered. **Nothing is written until the final confirmation**, and nothing is guessed silently.

### Workflow
| Step | What the user does | What the application does |
|---|---|---|
| 1. Файл | Uploads `.csv` or `.xlsx` (≤ `MAX_UPLOAD_MB`, default 10 MB) | Stores the file with the open preview only (dropped on confirm, cancel or expiry) |
| 2. Данные | Chooses the worksheet; for CSV confirms encoding/delimiter; chooses the header row, optionally a two-row header, a column range and the last data row; decides on flagged rows | Shows the first 60 rows with **original row numbers**, suggests the sheet and header, flags rows that need a decision |
| 3. Структура | Confirms or changes the layout: records, gradebook, aggregate table, general table | Suggests a layout with a reason |
| 4. Сопоставление и правила | Maps columns (or sets confirmed shared values), configures result columns, roles or types; declares how results, numbers, dates and missing marks are written | Shows sample values, ambiguity and per-field problems |
| 5. Проверка | Clicks «Проверить данные» | Validates structure → transformations → records → cross-record and database conflicts; shows counts, traceable issues and an **analysis capability assessment** |
| 6. Импорт | Reviews the summary and confirms | Commits exactly the validated result in one transaction |
| 7. Анализ | Opens an available analysis | Lists what the stored data supports and why other analyses are unavailable |

Any change to the sheet, CSV options, header, range, excluded rows, layout, mapping or rules discards the previous
validation in the page **and on the server**; an earlier validation can never be confirmed (`409 STALE_PREVIEW`).
Users can go back to any step without uploading the file again. The standard template is recognised; its validation
runs immediately after upload (still read-only).

### Input variations
* **CSV:** delimiter detected among comma, semicolon and tab from consistent field counts (quotes respected); encoding
  UTF-8 (with or without BOM) or Windows-1251. Low-confidence detection is shown, and both can be overridden. Cells stay
  text, so quoted values and identifiers with leading zeros (`007`) are preserved.
* **XLSX:** read-only; worksheets listed with size and hidden/empty labels (hidden sheets are never auto-selected).
  **Two-row headers:** the column label becomes «Группа · Подзаголовок»; the group comes from a merged range in the
  upper row (read from the sheet XML) or from the cell directly above — never extended by guessing. Cells merged
  vertically over both header rows keep their label. Merged *data* cells are not forward-filled.
* **Titles, blank rows, explanations, repeated headers, totals:** rows above the header are not imported; blank rows are
  counted; rows that repeat the header, look like totals («Итого», «Всего», «Среднее», «Total»…) or contain only
  explanatory text are **flagged, not removed**. The user excludes a kind explicitly; excluded row numbers are listed
  in the result. A **range** (first/last column, last data row) isolates one table when a sheet holds several.
* Duplicate and empty headers are shown; columns are identified by position (`c0` = column A), so equal headers work.

### Layouts (explicit adapters)
**A. Records (`long`)** — one row = one student's result for one topic or item in one assessment.
```
Код ученика | Класс | Код темы | Тема | Код работы | Дата | Баллы | Максимальный балл
SYN-01      | 7А    | T-FR     | Дроби| KR-1       | 20.05.2026 | 3 | 4
```
**B. Gradebook (`wide`)** — one row = one student, several result columns.
```
Код ученика | Класс | Контрольная 1 (merged)           | Итого
            |       | Задание 1 | Задание 2 | Задание 3 |
SYN-01      | 7А    | 1         | 2         | н         | 3
```
The user selects identity columns (or shared values) and result columns; for each result column gives the topic code
and name (name pre-filled from the header), an optional item code and the maximum score (points mode); assessment
id/type/date can be per column when columns are different assessments. Each non-empty cell becomes one record traced to
its **sheet row and column** (stored in `assessment_results.source_row/source_column`). Empty cells create no record;
declared missing marks create no record and are not zero. Columns that look like totals/averages are listed but not
preselected; selecting a total together with its items of the same topic is rejected (`MIXED_GRANULARITY`). The review
explains why there are more records than rows. Expansion is bounded by `MAX_UPLOAD_ROWS` (`413 TOO_MANY_RECORDS`).
«Заполнить пустые коды тем из названий» creates deterministic transliterated codes only on request; equal codes mean the
same topic in the database, so the user checks them.

**C. Aggregate (`aggregate`)** — one row = a class, topic, textbook group or cohort with an average, percentage or count.
```
Класс | Тема  | Средний % | Количество учеников
7А    | Дроби | 58,5      | 24
```
Roles: class, grade, subject, topic code/name, textbook, assessment, date, **value**, maximum, number of students.
The value is declared as a percentage (0–100 or fractions 0–1) or a mean score with a known maximum (column or entered
value). Stored as an **aggregate dataset**, never as student records; the summary shows per-group values, the unweighted
mean of group values, and a weighted mean only when every row has a number of students. No distributions, confidence
intervals, paired gains or textbook inference are computed from aggregates.

**D. General table (`general`)** — anything else. Stored as a **general dataset** (separate tables `datasets` /
`dataset_rows`, original cell texts) and explored on the «Наборы данных» page: row/column counts, editable column types
(number, date, category, text, identifier, yes/no), missing values, duplicate rows, numeric summaries and histograms
(identifiers excluded), category frequencies, date ranges, search, typed sorting, exact-value filters and CSV export.
General data never feeds the educational recommendation services.

**Unsupported (explained, not imported as records):** complex cross-tabulations (topics × classes with student
counts in cells), several unrelated tables in one region (restrict the range or exclude repeated headers), printed
reports with subtotals that cannot be separated. Such sheets can still be explored as a general table.

### Column mapping
Suggestions use canonical field names, a small Russian/English alias list (`ALIASES` in
`backend/app/services/import_prep.py`), conservative header normalisation (BOM, spaces, case, ё/е, separators) and
column profiles (numeric/percent/date share, distinct values, leading zeros). Examples: «ID ученика», «Student ID» →
`student_id`; «Предмет», «Subject» → `subject`; «Тема», «Topic» → `topic_name`; «Баллы», «Points» → `score`;
«Максимум», «Max points» → `max_score`; «Дата», «Assessment date» → `assessment_date`. Never preselected:
«Оценка», «Отметка», «Результат», «%» (mark, points or percent?), «Учебник» (code or title?), «ФИО», «Ученик»
(personal data is not an identifier), «Работа», «Тип», and any field matched by two columns. One column feeds one field.
Shared values are allowed only for subject, grade, class, assessment id/type/date, comparison group and school, require
an explicit confirmation, and never replace cell values (one source per field). Student identities, topics, scores,
maximum scores and textbook assignments are never invented; the textbook can only be explicitly marked as absent.

### Score interpretation and parsing rules
| Rule | Options | Default |
|---|---|---|
| Result | points with a known maximum · percentages (0–100 or 0–1; «85%» accepted) → stored as score of 100 · correct/incorrect with user-listed tokens → 1/0 of 1 · grading scale with a user-entered table «mark → %» | points |
| Decimal separator | auto (`.` or `,`; `1,000` is ambiguous and rejected) · comma (`1.000,5`) · dot (`1,000.5`) | auto |
| Date format | auto (`ГГГГ-ММ-ДД`, `ДД.ММ.ГГГГ`, Excel dates) · ДД.ММ.ГГГГ · ГГГГ-ММ-ДД · ДД/ММ/ГГГГ · ММ/ДД/ГГГГ · ДД-ММ-ГГГГ | auto |
| Missing marks | user list, e.g. «н», «н/я», «-» → no record, counted, never zero or "failed" | none |
Never done: maximum = largest observed value; 1–5 → % without a table; guessing `03/04/2026` (auto mode reports
`DATE_FORMAT_REQUIRED`); missing → 0. Formulas are never executed: cached values are used; a mapped formula cell without
a cached value is `FORMULA_WITHOUT_VALUE`. The confirmation summary lists the rules in Russian.

### Validation stages, issues and counts
Each issue shows the worksheet, original row, source column letter, a Russian message, a bounded value preview (≤ 40
characters; student identifiers and name-like values are never shown) and a corrective action; identical issues of one
row are collapsed with a count. Blocking errors and warnings are separate. Counts: source rows, excluded rows, records
after transformation, valid and invalid records, records already imported (skipped), records eligible for import.
**Partial import is not supported:** any error blocks confirmation until it is fixed in the file or the settings.

### Analysis capabilities (from the actual analytical code)
| Analysis | Level | Requires |
|---|---|---|
| Overview / mastery | student | outcome results (type `post` or `current`) with a maximum > 0 |
| Topic analysis | topic | outcome results with topics; a status needs ≥ `min_students_topic` students per topic |
| Pre → post gain | student (paired) | the same student and topic in a `pre` and a `post` assessment with one `comparison_group`; ≥ `min_students_topic` pairs per topic |
| Trends | topic | outcome results on ≥ 2 dates |
| Textbook comparison | class | textbooks per class and subject; ≥ 2 textbooks in one subject and grade, each with ≥ `min_classes_textbook` classes; common outcome items (checked on the page) |
| Hours optimizer | topic | teaching hours per class and topic, plus the total entered in the optimizer |
| Curriculum map | topic | topics; prerequisites make it informative |
| Table exploration | table | any general or aggregate dataset |
| Aggregate summary | aggregate | an aggregate dataset with a value and a group column |
The review shows this for the file being imported; after import `GET /api/analytics/capabilities` (honouring filters)
shows it for all stored data. Missing metadata disables only the analyses that need it (e.g. «Для сравнения учебников
укажите столбец с учебником.»); statistical thresholds are unchanged.

### Data handling, limits and AI
* Files are parsed locally (openpyxl read-only, Python csv); nothing is sent to external services. **AI is not used for
  import or mapping**; the workflow is fully deterministic. Cell contents are not logged.
* Limits: upload ≤ 10 MB; uncompressed xlsx ≤ 100 MB and ≤ 2000 parts; ≤ 50 sheets; ≤ 200 columns; ≤ 4 000 000
  iterated cells and 60 s per read; header within the first 50 rows; ≤ `MAX_UPLOAD_ROWS` (200 000) records after
  expansion; general datasets ≤ 50 000 rows and 2 000 000 cells; preview 60 rows.
* Each upload has a random session key (only its hash is stored); inspect/validate/confirm/cancel require it (`403`).
  Validation is bound to `sha256(file + configuration)`. Previews expire after `PREVIEW_TTL_MINUTES` (default 60):
  `410`, staged rows and the stored file are dropped. Confirmation keeps the existing advisory lock, conflict re-check
  and single transaction; datasets are written in one transaction and never touch assessment tables.
* Dataset CSV exports prefix cells beginning with `=`, `+`, `-`, `@`, tab or CR with `'` (plain numbers such as `-5`
  stay numbers); stored values are unchanged.

### API
`POST /api/imports/sources` · `POST /api/imports/{id}/inspect` `{session_key, sheet, header_row?, header_rows,
first_col, last_col, last_row, exclude, csv:{encoding, delimiter}}` · `POST /api/imports/{id}/validate` (the same plus
`layout`, `fields`, `result_columns`, `roles`, `metric`, `types`, `dataset_name`, `rules`, `confirm_shared`) ·
`POST /api/imports/{id}/commit` `{session_key, config_hash}` · `POST /api/imports/{id}/discard` `{session_key}` ·
`GET /api/datasets`, `GET|DELETE /api/datasets/{id}`, `PUT /api/datasets/{id}/columns`, `GET /api/datasets/{id}/rows`,
`GET /api/datasets/{id}/export.csv` · `GET /api/analytics/capabilities`. The one-step `POST /api/imports/preview`
(exact template headers in row 1) is unchanged for scripts.

### Synthetic examples
`docs/examples/` (regenerate with `python backend/scripts/generate_import_examples.py`):
`example_wide_gradebook.xlsx` (title, two-row merged header, «Итого» row and column, «н» marks),
`example_aggregate_topics.xlsx` (class × topic «Средний %» with student counts and an «Среднее» row),
`example_general_table.csv` (non-educational, Windows-1251, `;`, decimal comma, leading zeros). The page also offers
`example_guided_import.xlsx` (records with a title row, Russian headers and a hidden sheet).

## Numbers
| Input | Result |
|---|---|
| `7`, `7.5`, `7,5`, `-0,25`, `0,125` | accepted ("." or "," as decimal separator) |
| `1 000`, `1 000,5` (space, non-breaking or narrow space as thousands separator) | accepted |
| `1,000`, `2.500`, `10,000` (one separator + exactly three digits, non-zero integer part) | **AMBIGUOUS_NUMBER** — rejected, never guessed |
| `1,000.5`, `1.000,5` (both separators) | **AMBIGUOUS_NUMBER** |
| `1e3`, `inf`, `nan`, `12%`, text | **INVALID_NUMBER** |
| Excel cells that are real numbers (e.g. 1.125) | accepted as numbers (no locale ambiguity) |

The same parser is used in preview and commit (commit uses the rows staged by the preview).

## Hard rules (errors — the file cannot be imported)
* Required values present; anonymous identifiers only (name-like IDs are rejected; values are **not** echoed in messages).
* `max_score > 0`, `0 ≤ score ≤ max_score`; dates `YYYY-MM-DD` or `DD.MM.YYYY`; grade 1–12.
* No duplicate (student, assessment, topic, item) rows.
* **MIXED_GRANULARITY**: a (student, assessment, topic) must be either one topic-total row (empty `item_id`) or item rows — never both, in the file or combined with stored results.
* Consistency inside the file: a topic, assessment, class, student, textbook and (class, topic) hours each have one definition.
* **CONFLICT_WITH_DB**: the file contradicts stored data — different grade for an existing class, an existing textbook used for another subject, a different textbook for an existing (class, subject), different metadata for an existing topic/assessment, a student in another class, or a different score for an already imported result.

## Announced changes (warnings shown in the preview before you confirm)
* **TOPIC_SETTINGS_DIFFER** — min/max hours, priority, order or prerequisites in the file differ from the stored topic: the stored values are kept; change them explicitly in the optimizer (`PUT /api/topics/{id}`).
* **TEXTBOOK_NAME_DIFFERS** — stored name is kept.
* **TEACHING_HOURS_REPLACED** — the file's hours replace the stored hours of that class and topic.
* **ALREADY_IMPORTED** — identical rows are skipped (safe re-import).

## Atomicity and previews
* Commits run in one transaction under a PostgreSQL advisory lock; conflicts are re-checked under the lock. Any conflict aborts the whole import.
* Previews expire after `PREVIEW_TTL_MINUTES` (default 60): an expired preview returns **410** and its staged rows are purged; staged rows are also dropped for previews with errors and after commit/discard.
* Upload size is enforced while the body is received (the declared Content-Length is not trusted); `.xlsx` files are also limited by uncompressed size.

## Existing data
`python backend/scripts/integrity_check.py` (read-only) reports data imported before these rules:
missing (class, subject) textbook assignments, mixed topic-total/item results, textbook/subject and class/topic grade
mismatches, stored validation messages that echoed raw values, stale previews. Opt-in repairs:
`--add-missing-assignments` (creates the assignment with **textbook = NULL**, never a guessed textbook),
`--redact-validation`, `--purge-expired-previews`. Mixed results and grade mismatches are reported only — a person must
decide which rows are correct. The same read-only report is at `GET /api/admin/integrity`.
