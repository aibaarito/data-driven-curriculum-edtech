# Import format and integrity rules

One row = points of one anonymous student on one topic (or one item of a topic) in one assessment.
Columns are listed on the Import page and in `GET /api/imports/schema`.

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
