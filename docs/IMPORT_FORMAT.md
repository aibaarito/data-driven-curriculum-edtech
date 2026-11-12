# Import format and integrity rules

One row = points of one anonymous student on one topic (or one item of a topic) in one assessment.
Columns are listed on the Import page and in `GET /api/imports/schema`.

## Guided import (Импорт данных page)

The import page accepts school spreadsheets whose layout differs from the template, through an explicit sequence.
Nothing is written to the analytical data until step 6.

| Step | What you do | What the app does |
|---|---|---|
| 1. Файл | Choose a `.csv` or `.xlsx` file (≤ `MAX_UPLOAD_MB`, default 10 MB) | Stores the file with the open preview only; lists worksheets |
| 2. Лист | Choose one worksheet (xlsx only) | Suggests a sheet only if it is the single visible sheet with data or clearly has the most recognised headers. Hidden sheets are never suggested; they can be chosen manually and are labelled «скрытый лист». Empty sheets cannot be chosen. One sheet is imported, never all |
| 3. Заголовок | Confirm or change the header row | Shows the first rows with **original row numbers** and suggests a header row (confidence high/low with the reason). Rows above the header are not imported. The header must be one of the first 50 rows |
| 4. Сопоставление | Map each application field to a source column, a confirmed shared value, or (where allowed) "not in file" | Suggests columns from a small alias list; shows sample values, required/optional status and problems per field |
| 5. Проверка | Click «Проверить данные» | Runs the **same validator** as before on the mapped rows; reports counts, errors and warnings with original sheet row numbers |
| 6. Импорт | Review the summary and confirm | Commits exactly the validated rows in one transaction |

**Standard template:** if the worksheet, header row and every required field are unambiguous (e.g. `template.csv` or the
demo dataset), everything is preselected and validation runs immediately after upload; the settings stay visible
under «Показать и изменить…». Validation is read-only, so this needs no extra click.

### Expected record structure
One row per student × topic (or item) × assessment. Not supported in this version, and not silently "mapped":
one column per topic or item (wide tables), several tables on one sheet, printed reports with subtotals.
The page warns when it detects a likely wide table (several unmapped numeric columns and no score column) and blocks
validation rows that repeat the header inside the data (`REPEATED_HEADER`). Convert such sheets to the template layout
first; there is no automatic wide-to-long reshaping.

### Columns, headers and suggestions
* Source columns are identified by position (`c0` = column A), so two columns with the same or an empty header stay
  distinct. Empty headers are shown as «Столбец C (без заголовка)»; duplicated headers are listed.
* Header comparison ignores a UTF‑8 BOM, outer spaces, letter case, `ё/е` and separators (`_ - . / , : ; ( ) № #`).
  Nothing else is fuzzy-matched.
* Aliases (examples): `ID ученика`, `Код ученика`, `Student ID` → `student_id`; `Предмет`, `Subject` → `subject`;
  `Тема`, `Topic name` → `topic_name`; `Баллы`, `Набранный балл`, `Score` → `score`; `Максимальный балл`, `Max score`
  → `max_score`; `Дата`, `Дата оценивания` → `assessment_date`; `Параллель` → `grade`; `Класс` → `class`.
  The full list is `ALIASES` in `backend/app/services/import_prep.py`.
* Never preselected (shown as "возможные столбцы", the user must choose): `Оценка`/`Отметка`/`Результат`/`%`
  (may be a 5‑point mark or a percentage), `Учебник` (code or title?), `ФИО`/`Ученик` (personal data, not an ID),
  `Работа`, `Тип`, and any field for which two columns match.
* One source column can feed only one field (the other fields show it as «уже выбран для …»). Unused columns are
  listed as ignored and shown again in the confirmation summary.
* Changing the worksheet resets the mapping. Changing the header row keeps a column choice only if that column
  position still has the same header text; other fields get the new suggestions. Any change discards the previous
  validation result.

### Shared values («Одно значение для всего файла»)
Allowed only for `subject`, `grade`, `class`, `assessment_id`, `assessment_type`, `assessment_date`,
`comparison_group`, `school`. A field takes its values from exactly one source, so a shared value can never overwrite
a cell. The value is validated with the same rules as a cell (grade 1–12, type pre/post/current, date
`ГГГГ-ММ-ДД`/`ДД.ММ.ГГГГ`, codes without spaces), applied only to rows that contain mapped data, shown in the record
preview and the confirmation summary, and requires the explicit checkbox «Подтверждаю…».
Not eligible (never invented): `student_id`, `topic_id`, `topic_name`, `score`, `max_score`, `textbook_id`, `item_id`,
hours and topic settings. For `textbook_id` the only alternative to a column is the explicit choice «В файле нет
учебника» — the same as the template's empty textbook column (warning `MISSING_TEXTBOOK`; those classes are not
compared). No field was made optional for the guided flow.

### Cells, dates and formulas
* Excel numbers and dates are used as stored (no locale guessing); text cells follow the number rules below.
* Dates: `ГГГГ-ММ-ДД`, `ДД.ММ.ГГГГ` or an Excel date cell. Other formats (e.g. `09/15/2026`) are `INVALID_DATE`; the app
  does not guess between day-first and month-first.
* `85%` is not a score; `7А` is not split into grade and class; a missing maximum is never assumed to be 100.
* Merged cells are not forward-filled: only the top-left cell has a value, the others are empty (and usually produce
  `MISSING_VALUE`).
* Formulas are **never executed**. The value cached by Excel is used; a formula without a cached value (files written
  by some generators) in a mapped column is `FORMULA_WITHOUT_VALUE` — open the file in Excel, recalculate, save.
* Rows with data only in ignored columns are not records and are reported (`ROWS_WITHOUT_MAPPED_DATA` warning);
  fully empty rows are counted (`BLANK_ROWS`). Invalid rows are never skipped: any error blocks the whole import.

### Counts in the result
«Найдено записей» = non-blank data rows; «С ошибками» = distinct rows with at least one error; «Без ошибок» = the
difference; «Будет импортировано» = all records if there are no errors, otherwise 0 (partial imports are not allowed).
If validation stops at the structure level, the counts say «не проверены» instead of showing 0.

### Common errors and how to fix them
| Message | What to do |
|---|---|
| «Выберите столбец для поля “…”» | Choose the column, or a shared value / «нет в файле» where offered |
| «Столбец … уже выбран для поля …» | Clear the other field first; one column feeds one field |
| «Подтвердите, что заданные вручную значения…» | Tick the confirmation under the shared values |
| «Лист “…”, строка 18: Балл больше максимального» | Correct the cell in the source file and upload again |
| «Неверная дата» | Use `ДД.ММ.ГГГГ` or a real Excel date |
| «Предпросмотр устарел после изменения…» | Click «Проверить снова»; an older result cannot be committed |
| «Срок действия предпросмотра истёк» | Upload the file again |

### Safety properties (enforced by the backend, not only the page)
* Every configuration is re-validated on the server: sheet exists, header row is a non-empty row among the first 50,
  column IDs exist, fields are known, required fields resolved, no column reused, shared values eligible, valid and
  confirmed (`422 INVALID_CONFIGURATION` with per-field issues).
* Each upload gets a random session key (only its hash is stored); inspect/validate/commit/discard of a guided preview
  require it (`403`). Validation is bound to `config_hash = sha256(file sha256 + configuration)`; a new validation
  request first clears the previous result; commit requires the hash of the **last** validation (`409 STALE_PREVIEW`).
* Commit uses the unchanged existing path: advisory lock, conflict re-check, single transaction, staged rows only.
* The stored file is deleted on commit, discard and expiry. Cell values are not logged.
* Workbook limits: ≤ 50 sheets, ≤ 200 columns, ≤ 4 000 000 iterated cells, 60 s per read, uncompressed size ≤ 100 MB
  and ≤ 2000 zip members, row limit `MAX_UPLOAD_ROWS` (default 200 000). Files are read locally with openpyxl in
  read-only mode; nothing is sent to external services or an AI model.

### API
`POST /api/imports/sources` (multipart `file`) → sheets, suggestions, `session_key` ·
`POST /api/imports/{id}/inspect` `{session_key, sheet, header_row?}` ·
`POST /api/imports/{id}/validate` `{session_key, sheet, header_row, fields: {field: {source: "column", column} |
{source: "value", value} | {source: "none"}}, confirm_shared}` ·
`POST /api/imports/{id}/commit` `{session_key, config_hash}` · `POST /api/imports/{id}/discard` `{session_key}`.
The one-step `POST /api/imports/preview` (exact template headers in row 1, first sheet) is unchanged for scripts; its
previews commit without a body as before.

### Example workbook
`GET /api/imports/example-workbook.xlsx` (button «Пример Excel» on the page; source
`backend/app/assets/data/example_guided_import.xlsx`, regenerate with `python backend/scripts/generate_example_workbook.py`).
Fully synthetic (`SYN-…` codes). It has an instruction sheet, the sheet «Результаты» with a merged title row, a blank
row and Russian headers in row 3, an ambiguous «Учебник» column and an «Примечание» column to ignore, and a hidden
sheet. Subject and assessment type are absent. To try it: upload → keep «Результаты» and row 3 → Предмет: «Одно
значение…» = `Математика` → Тип оценивания: «Одно значение…» = `pre` → Идентификатор учебника: column J «Учебник» →
tick the confirmation → «Проверить данные» (36 records) → confirm or «Отменить».

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
