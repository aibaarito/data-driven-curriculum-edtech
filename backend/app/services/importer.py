"""Parsing and strict validation of uploaded assessment files.

Principles:
* Nothing is silently corrected. A file with errors cannot be committed.
* Every problem is reported with a spreadsheet row number, a column and a code.
"""
from __future__ import annotations

import csv
import io
import zipfile
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from collections.abc import Callable
from typing import Any

import pandas as pd

REQUIRED_COLUMNS = [
    "student_id",
    "grade",
    "class",
    "subject",
    "topic_id",
    "topic_name",
    "assessment_id",
    "assessment_type",
    "assessment_date",
    "score",
    "max_score",
    "textbook_id",
]
OPTIONAL_COLUMNS = [
    "school",
    "item_id",
    "teaching_hours",
    "comparison_group",
    "textbook_name",
    "topic_order",
    "topic_min_hours",
    "topic_max_hours",
    "topic_priority",
    "topic_prerequisites",
]
ALL_COLUMNS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS
# Columns that must be non-empty in every row (textbook_id may be empty -> warning).
NON_EMPTY = [c for c in REQUIRED_COLUMNS if c != "textbook_id"]
ASSESSMENT_KINDS = {"pre", "post", "current"}
MAX_LISTED_ISSUES = 300
MAX_XLSX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024  # guard against zip bombs
MAX_XLSX_MEMBERS = 2000
DEFAULT_SCHOOL = "default"
NAME_LIKE = re.compile(r"^[A-ZА-ЯЁ][a-zа-яё]+\s+[A-ZА-ЯЁ][a-zа-яё]+")
CODE_RE = re.compile(r"^[A-Za-z0-9А-Яа-яЁё_.\-]{1,64}$")


class FileFormatError(ValueError):
    """Raised when the file cannot be read as a table at all."""


@dataclass
class Issue:
    row: int | None
    column: str | None
    code: str
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {"row": self.row, "column": self.column, "code": self.code, "message": self.message}


@dataclass
class ValidationResult:
    total_rows: int = 0
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)  # normalized rows (only meaningful if ok)
    summary: dict[str, Any] = field(default_factory=dict)
    columns_found: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors and self.total_rows > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "total_rows": self.total_rows,
            "valid_rows": len(self.rows) if self.ok else 0,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "error_counts": dict(Counter(e.code for e in self.errors)),
            "warning_counts": dict(Counter(w.code for w in self.warnings)),
            "errors": [e.as_dict() for e in self.errors[:MAX_LISTED_ISSUES]],
            "warnings": [w.as_dict() for w in self.warnings[:MAX_LISTED_ISSUES]],
            "summary": self.summary,
            "columns_found": self.columns_found,
            "preview": [_preview_row(r) for r in self.rows[:20]],
        }


def _preview_row(r: dict[str, Any]) -> dict[str, Any]:
    return {k: (v.isoformat() if isinstance(v, date) else v) for k, v in r.items() if k != "_row"} | {
        "row": r["_row"]
    }


# --------------------------------------------------------------------------- parsing


def normalize_header(name: str) -> str:
    return re.sub(r"\s+", "_", str(name).strip().lower())


def read_table(content: bytes, filename: str) -> pd.DataFrame:
    """Read CSV or XLSX into a DataFrame of strings. Raises FileFormatError."""
    if not content:
        raise FileFormatError("Файл пустой.")
    lower = filename.lower()
    if lower.endswith(".xlsx"):
        if not content.startswith(b"PK"):
            raise FileFormatError("Файл имеет расширение .xlsx, но не является корректной книгой Excel.")
        _check_xlsx_size(content)
        try:
            # dtype=object keeps Excel's native numbers (no locale ambiguity) and strings as typed.
            df = pd.read_excel(io.BytesIO(content), dtype=object, engine="openpyxl", keep_default_na=False)
        except Exception as exc:  # corrupted workbook
            raise FileFormatError("Не удалось прочитать файл Excel: файл повреждён или имеет неверный формат.") from exc
    elif lower.endswith(".csv"):
        if content.startswith(b"PK") or b"\x00" in content[:4096]:
            raise FileFormatError("Файл имеет расширение .csv, но содержит двоичные данные.")
        text: str | None = None
        for enc in ("utf-8-sig", "cp1251"):
            try:
                text = content.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None or not text.strip():
            raise FileFormatError("Файл пустой или имеет неподдерживаемую кодировку (ожидается UTF-8 или Windows-1251).")
        first_line = text.splitlines()[0] if text.splitlines() else ""
        delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
        try:
            df = pd.read_csv(
                io.StringIO(text), dtype=str, sep=delimiter, keep_default_na=False, quoting=csv.QUOTE_MINIMAL
            )
        except Exception as exc:
            raise FileFormatError("Не удалось разобрать CSV: проверьте разделители и кавычки.") from exc
    else:
        raise FileFormatError("Неподдерживаемый формат. Загрузите файл .csv или .xlsx.")
    df.columns = [normalize_header(c) for c in df.columns]
    # drop fully empty rows (common trailing rows in Excel) - reported as count, not silently
    return df


def _check_xlsx_size(content: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            infos = zf.infolist()
    except zipfile.BadZipFile as exc:
        raise FileFormatError("Файл имеет расширение .xlsx, но не является корректной книгой Excel.") from exc
    if len(infos) > MAX_XLSX_MEMBERS or sum(i.file_size for i in infos) > MAX_XLSX_UNCOMPRESSED_BYTES:
        raise FileFormatError("Книга Excel слишком велика после распаковки. Сохраните данные в CSV или уменьшите файл.")


# Accepted numeric text (documented in docs/IMPORT_FORMAT.md):
#   * optional leading minus, digits, optional decimal part with "." OR "," as decimal separator: 7  7.5  7,5  -0,25
#   * optional thousands grouping with spaces only (incl. non-breaking/narrow spaces): 1 000   1 000,5
# Rejected as AMBIGUOUS_NUMBER (never guessed): a single "." or "," followed by exactly three digits with a non-zero
#   integer part of 1-3 digits ("1,000", "2.500"), and values using both "." and "," ("1,000.5", "1.000,5").
# Rejected as INVALID_NUMBER: anything else, including exponents, "inf", "nan", currency or percent signs.
_GROUP_SPACES = re.compile("[ \u00a0\u202f\u2009]")
_PLAIN_NUM = re.compile(r"^-?\d+(?:[.,]\d+)?$")
_SPACE_GROUPED = re.compile("^-?\\d{1,3}(?:[ \u00a0\u202f\u2009]\\d{3})+(?:[.,]\\d+)?$")
_AMBIGUOUS = re.compile(r"^-?[1-9]\d{0,2}[.,]\d{3}$")


def parse_number(value: Any) -> tuple[float | None, str | None]:
    """Return (number, None) or (None, error_code). Native Excel numbers are accepted as is."""
    if isinstance(value, bool):
        return None, "INVALID_NUMBER"
    if isinstance(value, (int, float)):
        x = float(value)
        return (None, "INVALID_NUMBER") if (math.isnan(x) or math.isinf(x)) else (x, None)
    v = str(value).strip()
    if not v:
        return None, "INVALID_NUMBER"
    if "." in v and "," in v:
        return None, "AMBIGUOUS_NUMBER"
    if _SPACE_GROUPED.match(v):
        v = _GROUP_SPACES.sub("", v)
    elif _AMBIGUOUS.match(v):
        return None, "AMBIGUOUS_NUMBER"
    elif not _PLAIN_NUM.match(v):
        return None, "INVALID_NUMBER"
    x = float(v.replace(",", "."))
    return (None, "INVALID_NUMBER") if (math.isnan(x) or math.isinf(x)) else (x, None)


def _num(value: Any) -> float | None:
    return parse_number(value)[0]


NUMBER_HELP = "Допустимо: 7, 7.5 или 7,5; разряды — только пробелом (1 000)."


def _cell_text(v: Any) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))  # Excel stores integers as floats; keeps identifiers like 7 or 1001 readable
    return str(v).strip()


def _numeric_input(native: Any, text: str) -> Any:
    return text if isinstance(native, str) or native is None else native


def _date(value: str) -> date | None:
    v = value.strip()
    if " " in v:  # Excel may export "2025-09-10 00:00:00"
        v = v.split(" ")[0]
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    return None


# --------------------------------------------------------------------------- validation


def validate_dataframe(df: pd.DataFrame, existing_loader: "Callable[[list[dict[str, Any]]], ExistingState] | None" = None) -> ValidationResult:
    res = ValidationResult()
    res.columns_found = list(df.columns)
    dup_cols = [c for c, n in Counter(df.columns).items() if n > 1]
    if dup_cols:
        res.errors.append(Issue(None, ", ".join(dup_cols), "DUPLICATE_COLUMN", "Столбцы повторяются в заголовке."))
        return res
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        res.errors.append(
            Issue(None, ", ".join(missing), "MISSING_COLUMN", f"Отсутствуют обязательные столбцы: {', '.join(missing)}.")
        )
        return res
    unknown = [c for c in df.columns if c not in ALL_COLUMNS]
    if unknown:
        res.warnings.append(
            Issue(None, ", ".join(unknown), "UNKNOWN_COLUMN", "Неизвестные столбцы будут проигнорированы при импорте.")
        )

    records = df.to_dict(orient="records")
    blank_rows = 0
    normalized: list[dict[str, Any]] = []
    for idx, raw in enumerate(records):
        rownum = idx + 2  # header is row 1
        native = {c: raw.get(c) for c in ALL_COLUMNS}
        rec = {c: _cell_text(native[c]) for c in ALL_COLUMNS}
        if not any(rec[c] for c in ALL_COLUMNS):
            blank_rows += 1
            continue
        row_ok = True

        def err(col: str | None, code: str, msg: str) -> None:
            nonlocal row_ok
            row_ok = False
            res.errors.append(Issue(rownum, col, code, msg))

        for c in NON_EMPTY:
            if not rec[c]:
                err(c, "MISSING_VALUE", f"Пустое значение в обязательном столбце «{c}».")
        if not row_ok:
            continue

        out: dict[str, Any] = {"_row": rownum}
        out["school"] = rec["school"] or DEFAULT_SCHOOL
        for c in ("student_id", "topic_id", "assessment_id"):
            if not CODE_RE.match(rec[c]):
                err(c, "INVALID_IDENTIFIER", f"Недопустимый идентификатор в столбце «{c}» (до 64 символов: буквы, "
                                             "цифры, «-», «_», «.»; без пробелов). Значение не показывается.")
        if NAME_LIKE.match(rec["student_id"]):
            err("student_id", "POSSIBLE_PERSONAL_DATA", "Похоже на ФИО. Используйте только анонимные идентификаторы.")
        out["student_id"] = rec["student_id"]
        out["topic_id"] = rec["topic_id"]
        out["assessment_id"] = rec["assessment_id"]
        out["class"] = rec["class"][:64]
        out["subject"] = rec["subject"][:255]
        out["topic_name"] = rec["topic_name"][:255]
        out["item_id"] = rec["item_id"] or "_total"
        if rec["item_id"] and not CODE_RE.match(rec["item_id"]):
            err("item_id", "INVALID_IDENTIFIER", "Недопустимый идентификатор задания.")

        g = _num(_numeric_input(native["grade"], rec["grade"]))
        if g is None or g != int(g) or not 1 <= g <= 12:
            err("grade", "INVALID_GRADE", "Параллель должна быть целым числом от 1 до 12.")
        else:
            out["grade"] = int(g)

        kind = rec["assessment_type"].lower()
        if kind not in ASSESSMENT_KINDS:
            err("assessment_type", "INVALID_ASSESSMENT_TYPE", "Тип оценивания должен быть pre, post или current.")
        out["assessment_type"] = kind

        d = _date(rec["assessment_date"])
        if d is None:
            err("assessment_date", "INVALID_DATE", "Неверная дата (ожидается ГГГГ-ММ-ДД или ДД.ММ.ГГГГ).")
        out["assessment_date"] = d

        score, score_err = parse_number(_numeric_input(native["score"], rec["score"]))
        max_score, max_err = parse_number(_numeric_input(native["max_score"], rec["max_score"]))
        if score_err:
            err("score", score_err, "Балл не распознан как число. " + NUMBER_HELP)
        if max_err:
            err("max_score", max_err, "Максимальный балл не распознан как число. " + NUMBER_HELP)
        if score is not None and max_score is not None:
            if max_score <= 0:
                err("max_score", "NON_POSITIVE_MAX", "Максимальный балл должен быть больше нуля.")
            if score < 0:
                err("score", "NEGATIVE_SCORE", "Балл не может быть отрицательным.")
            if max_score > 0 and score > max_score:
                err("score", "SCORE_EXCEEDS_MAX", f"Балл {score:g} превышает максимум {max_score:g}.")
        out["score"] = score
        out["max_score"] = max_score

        out["textbook_id"] = rec["textbook_id"] or None
        out["textbook_name"] = rec["textbook_name"] or None
        if out["textbook_id"] and not CODE_RE.match(out["textbook_id"]):
            err("textbook_id", "INVALID_IDENTIFIER", "Недопустимый код учебника.")

        if rec["teaching_hours"]:
            h, h_err = parse_number(_numeric_input(native["teaching_hours"], rec["teaching_hours"]))
            if h_err == "AMBIGUOUS_NUMBER":
                err("teaching_hours", h_err, "Часы записаны неоднозначно. " + NUMBER_HELP)
            elif h is None or h < 0 or h > 1000:
                err("teaching_hours", "INVALID_HOURS", "Часы должны быть неотрицательным числом. " + NUMBER_HELP)
            out["teaching_hours"] = h
        else:
            out["teaching_hours"] = None

        out["comparison_group"] = rec["comparison_group"] or None

        # topic curriculum metadata (optional)
        for col, key, lo, hi, integer in (
            ("topic_order", "topic_order", 0, 10_000, True),
            ("topic_min_hours", "topic_min_hours", 0, 1000, False),
            ("topic_max_hours", "topic_max_hours", 0, 1000, False),
            ("topic_priority", "topic_priority", 1, 3, True),
        ):
            if rec[col]:
                v, v_err = parse_number(_numeric_input(native[col], rec[col]))
                if v is None or v < lo or v > hi or (integer and v != int(v)):
                    err(col, v_err if v_err == "AMBIGUOUS_NUMBER" else "INVALID_TOPIC_SETTING",
                        f"Недопустимое значение в «{col}» (допустимо от {lo} до {hi}). " + NUMBER_HELP)
                out[key] = int(v) if (v is not None and integer) else v
            else:
                out[key] = None
        if out["topic_min_hours"] is not None and out["topic_max_hours"] is not None:
            if out["topic_min_hours"] > out["topic_max_hours"]:
                err("topic_min_hours", "INVALID_TOPIC_SETTING", "Минимум часов больше максимума.")
        out["topic_prerequisites"] = tuple(
            sorted(p.strip() for p in rec["topic_prerequisites"].split(";") if p.strip())
        )

        if row_ok:
            normalized.append(out)

    res.total_rows = len(records) - blank_rows
    if blank_rows:
        res.warnings.append(Issue(None, None, "BLANK_ROWS", f"Пропущено полностью пустых строк: {blank_rows}."))
    if res.total_rows == 0:
        res.errors.append(Issue(None, None, "EMPTY_FILE", "Файл не содержит строк с данными."))
        return res

    _cross_row_checks(normalized, res)
    if existing_loader is not None and normalized:
        existing_loader(normalized).check(normalized, res)

    res.errors.sort(key=lambda i: (i.row or 0))
    res.rows = normalized
    res.summary = _summary(normalized)
    return res


def _consistency(rows, key_fn, val_fn, res: ValidationResult, column: str, what: str) -> None:
    first: dict[Any, tuple[Any, int]] = {}
    for r in rows:
        k = key_fn(r)
        v = val_fn(r)
        if k in first:
            fv, frow = first[k]
            if fv != v:
                res.errors.append(
                    Issue(r["_row"], column, "CONFLICT", f"{what}: значение отличается от строки {frow}.")
                )
        else:
            first[k] = (v, r["_row"])


def _cross_row_checks(rows: list[dict[str, Any]], res: ValidationResult) -> None:
    seen: dict[tuple, int] = {}
    for r in rows:
        key = (r["school"], r["student_id"], r["assessment_id"], r["topic_id"], r["item_id"])
        if key in seen:
            res.errors.append(
                Issue(r["_row"], "student_id", "DUPLICATE_ROW",
                      f"Дубликат строки {seen[key]} (ученик, оценивание, тема, задание совпадают).")
            )
        else:
            seen[key] = r["_row"]

    gran: dict[tuple, set[str]] = defaultdict(set)
    first_row: dict[tuple, int] = {}
    for r in rows:
        k4 = (r["school"], r["student_id"], r["assessment_id"], r["topic_id"])
        gran[k4].add("total" if r["item_id"] == "_total" else "items")
        first_row.setdefault(k4, r["_row"])
    for k4, kinds in gran.items():
        if len(kinds) > 1:
            res.errors.append(Issue(first_row[k4], "item_id", "MIXED_GRANULARITY",
                                    "Для одного ученика, оценивания и темы есть и строка-итог (без item_id), и строки "
                                    "по заданиям — баллы были бы учтены дважды. Оставьте один вариант."))

    _consistency(rows, lambda r: r["topic_id"],
                 lambda r: (r["topic_name"], r["subject"], r["grade"]), res, "topic_id",
                 "Тема с этим кодом имеет другое название, предмет или параллель")
    _consistency(rows, lambda r: r["assessment_id"],
                 lambda r: (r["assessment_date"], r["assessment_type"], r["subject"], r["comparison_group"]),
                 res, "assessment_id", "Оценивание с этим кодом имеет другую дату, тип, предмет или группу сравнения")
    _consistency(rows, lambda r: (r["school"], r["class"]), lambda r: r["grade"], res, "class",
                 "Класс указан с разной параллелью")
    _consistency(rows, lambda r: (r["school"], r["class"], r["subject"]), lambda r: r["textbook_id"], res,
                 "textbook_id", "Для класса и предмета указаны разные учебники")
    _consistency(rows, lambda r: (r["school"], r["student_id"]), lambda r: r["class"], res, "class",
                 "Ученик указан в разных классах")
    _consistency(rows, lambda r: r["textbook_id"], lambda r: r["subject"], res, "textbook_id",
                 "Учебник используется для разных предметов")
    _consistency([r for r in rows if r["teaching_hours"] is not None],
                 lambda r: (r["school"], r["class"], r["topic_id"]), lambda r: r["teaching_hours"], res,
                 "teaching_hours", "Для класса и темы указаны разные часы")
    for col in ("topic_order", "topic_min_hours", "topic_max_hours", "topic_priority", "topic_prerequisites"):
        _consistency([r for r in rows if r[col] is not None and r[col] != ()], lambda r: r["topic_id"], lambda r, c=col: r[c], res, col,
                     "Параметр темы отличается между строками")

    topic_ids = {r["topic_id"] for r in rows}
    topic_subject = {r["topic_id"]: r["subject"] for r in rows}
    for r in rows:
        for p in r["topic_prerequisites"]:
            if p == r["topic_id"]:
                res.errors.append(Issue(r["_row"], "topic_prerequisites", "INVALID_PREREQUISITE",
                                        "Тема не может быть пререквизитом самой себя."))
            elif p not in topic_ids:
                res.errors.append(Issue(r["_row"], "topic_prerequisites", "UNKNOWN_PREREQUISITE",
                                        f"Пререквизит «{p}» не найден среди тем файла."))
            elif topic_subject.get(p) != r["subject"]:
                res.errors.append(Issue(r["_row"], "topic_prerequisites", "INVALID_PREREQUISITE",
                                        f"Пререквизит «{p}» относится к другому предмету."))

    # Prerequisites must form a directed acyclic graph: a cycle makes "learn A before B" contradictory.
    first_row: dict[str, int] = {}
    edges: set[tuple[str, str]] = set()
    for r in rows:
        for p in r["topic_prerequisites"]:
            if p != r["topic_id"] and p in topic_ids:
                edges.add((p, r["topic_id"]))
                first_row.setdefault(r["topic_id"], r["_row"])
    if edges:
        from app.services.curriculum_graph import find_cycle  # local import: keeps the importer standalone

        cycle = find_cycle(sorted(topic_ids), sorted(edges))
        if cycle:
            res.errors.append(Issue(first_row.get(cycle[1]), "topic_prerequisites", "CYCLIC_PREREQUISITE",
                                    "Пререквизиты образуют цикл: " + " → ".join(cycle) + "."))

    no_tb = {(r["school"], r["class"], r["subject"]) for r in rows if not r["textbook_id"]}
    if no_tb:
        res.warnings.append(Issue(None, "textbook_id", "MISSING_TEXTBOOK",
                                  f"Для {len(no_tb)} пар «класс–предмет» не указан учебник; "
                                  "они не участвуют в сравнении учебников."))
    no_hours = sum(1 for r in rows if r["teaching_hours"] is None)
    if no_hours:
        res.warnings.append(Issue(None, "teaching_hours", "MISSING_HOURS",
                                  f"В {no_hours} строках не указаны часы; анализ часов будет неполным."))
    no_group = {r["assessment_id"] for r in rows if r["assessment_type"] in ("pre", "post") and not r["comparison_group"]}
    if no_group:
        res.warnings.append(Issue(None, "comparison_group", "MISSING_COMPARISON_GROUP",
                                  f"Оценивания {', '.join(sorted(no_group))} имеют тип pre/post без группы сравнения "
                                  "и не будут использованы для расчёта прироста."))


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}
    dates = [r["assessment_date"] for r in rows if r["assessment_date"]]
    return {
        "students": len({(r["school"], r["student_id"]) for r in rows}),
        "classes": len({(r["school"], r["class"]) for r in rows}),
        "subjects": sorted({r["subject"] for r in rows}),
        "topics": len({r["topic_id"] for r in rows}),
        "assessments": len({r["assessment_id"] for r in rows}),
        "textbooks": sorted({r["textbook_id"] for r in rows if r["textbook_id"]}),
        "date_from": min(dates).isoformat() if dates else None,
        "date_to": max(dates).isoformat() if dates else None,
        "item_level": any(r["item_id"] != "_total" for r in rows),
    }


# --------------------------------------------------------------------------- existing-DB checks


class ExistingState:
    """Snapshot of what is already in the database, used to detect conflicts before commit.

    Hard conflicts (errors) block the import; differing curriculum settings of existing topics and differing
    textbook display names are reported as warnings because the stored values are kept and can only be changed
    through the explicit topic-settings operation (PUT /api/topics/{id}).
    """

    def __init__(self, topics: dict, assessments: dict, students: dict, class_tb: dict, results: dict,
                 classes: dict | None = None, textbooks: dict | None = None, topic_settings: dict | None = None,
                 granularity: dict | None = None, hours: dict | None = None):
        self.topics = topics  # code -> (name, subject_name, grade)
        self.assessments = assessments  # code -> (date, kind, subject_name, group)
        self.students = students  # (school, ext) -> class_name
        self.class_tb = class_tb  # (school, class, subject_name) -> textbook_code | None
        self.results = results  # (school, ext, assessment, topic, item) -> (score, max)
        self.classes = classes or {}  # (school, class) -> grade
        self.textbooks = textbooks or {}  # code -> (subject_name, name)
        self.topic_settings = topic_settings or {}  # code -> {order, min, max, priority, prerequisites}
        self.granularity = granularity or {}  # (school, ext, assessment, topic) -> {"total"} | {"items"}
        self.hours = hours or {}  # (school, class, topic_code) -> hours

    def check(self, rows: list[dict[str, Any]], res: ValidationResult) -> None:
        dup_existing = 0
        reported: set[tuple] = set()

        def once(key: tuple) -> bool:
            if key in reported:
                return False
            reported.add(key)
            return True

        for r in rows:
            t = self.topics.get(r["topic_id"])
            if t and t != (r["topic_name"], r["subject"], r["grade"]) and once(("t", r["topic_id"])):
                res.errors.append(Issue(r["_row"], "topic_id", "CONFLICT_WITH_DB",
                                        "Тема с этим кодом уже существует с другим названием, предметом или параллелью."))
            ts = self.topic_settings.get(r["topic_id"])
            if ts is not None:
                differs = []
                for col, key in (("topic_order", "order"), ("topic_min_hours", "min"), ("topic_max_hours", "max"),
                                 ("topic_priority", "priority")):
                    if r[col] is not None and float(r[col]) != float(ts[key]):
                        differs.append(col)
                if r["topic_prerequisites"] and frozenset(r["topic_prerequisites"]) != ts["prerequisites"]:
                    differs.append("topic_prerequisites")
                if differs and once(("ts", r["topic_id"])):
                    res.warnings.append(Issue(r["_row"], ", ".join(differs), "TOPIC_SETTINGS_DIFFER",
                                              f"Параметры темы {r['topic_id']} в файле отличаются от сохранённых. "
                                              "Сохранённые значения НЕ будут изменены импортом; измените их явно в "
                                              "оптимизаторе часов."))
            a = self.assessments.get(r["assessment_id"])
            if a and a != (r["assessment_date"], r["assessment_type"], r["subject"], r["comparison_group"]) and once(
                    ("a", r["assessment_id"])):
                res.errors.append(Issue(r["_row"], "assessment_id", "CONFLICT_WITH_DB",
                                        "Оценивание с этим кодом уже загружено с другими параметрами."))
            s = self.students.get((r["school"], r["student_id"]))
            if s is not None and s != r["class"] and once(("s", r["school"], r["student_id"])):
                res.errors.append(Issue(r["_row"], "class", "CONFLICT_WITH_DB",
                                        "Ученик уже числится в другом классе."))
            g = self.classes.get((r["school"], r["class"]))
            if g is not None and g != r["grade"] and once(("g", r["school"], r["class"])):
                res.errors.append(Issue(r["_row"], "grade", "CONFLICT_WITH_DB",
                                        f"Класс {r['class']} уже записан в параллели {g}; в файле указана другая."))
            if r["textbook_id"]:
                tb = self.textbooks.get(r["textbook_id"])
                if tb is not None and tb[0] != r["subject"] and once(("tbs", r["textbook_id"])):
                    res.errors.append(Issue(r["_row"], "textbook_id", "CONFLICT_WITH_DB",
                                            f"Учебник {r['textbook_id']} уже используется для другого предмета."))
                if (tb is not None and r["textbook_name"] and tb[1] != r["textbook_name"]
                        and once(("tbn", r["textbook_id"]))):
                    res.warnings.append(Issue(r["_row"], "textbook_name", "TEXTBOOK_NAME_DIFFERS",
                                              f"Название учебника {r['textbook_id']} отличается от сохранённого; "
                                              "сохранённое название не изменяется."))
            key_ct = (r["school"], r["class"], r["subject"])
            if key_ct in self.class_tb and self.class_tb[key_ct] != r["textbook_id"] and once(("c",) + key_ct):
                res.errors.append(Issue(r["_row"], "textbook_id", "CONFLICT_WITH_DB",
                                        "Для класса уже записан другой учебник (или его отсутствие) по этому предмету."))
            hk = (r["school"], r["class"], r["topic_id"])
            if r["teaching_hours"] is not None and hk in self.hours and self.hours[hk] != r["teaching_hours"] \
                    and once(("h",) + hk):
                res.warnings.append(Issue(r["_row"], "teaching_hours", "TEACHING_HOURS_REPLACED",
                                          f"Часы темы {r['topic_id']} для класса {r['class']} изменятся: "
                                          f"{self.hours[hk]:g} → {r['teaching_hours']:g} ч."))
            k4 = (r["school"], r["student_id"], r["assessment_id"], r["topic_id"])
            stored = self.granularity.get(k4)
            incoming = "total" if r["item_id"] == "_total" else "items"
            if stored and incoming not in stored and once(("gr",) + k4):
                res.errors.append(Issue(r["_row"], "item_id", "MIXED_GRANULARITY",
                                        "Для этого ученика, оценивания и темы в базе уже есть результаты в другом виде "
                                        "(итог по теме или по заданиям) — баллы были бы учтены дважды."))
            k = (r["school"], r["student_id"], r["assessment_id"], r["topic_id"], r["item_id"])
            if k in self.results:
                if self.results[k] == (r["score"], r["max_score"]):
                    dup_existing += 1
                    r["_skip"] = True
                else:
                    res.errors.append(Issue(r["_row"], "score", "CONFLICT_WITH_DB",
                                            "Результат уже загружен с другим баллом. Исправления данных не "
                                            "выполняются автоматически."))
            else:
                r.pop("_skip", None)
        if dup_existing:
            res.warnings.append(Issue(None, None, "ALREADY_IMPORTED",
                                      f"{dup_existing} строк уже есть в базе с теми же значениями и будут пропущены."))


def rows_to_json(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        d = dict(r)
        if isinstance(d.get("assessment_date"), date):
            d["assessment_date"] = d["assessment_date"].isoformat()
        d["topic_prerequisites"] = list(d["topic_prerequisites"])
        out.append(d)
    return out


def rows_from_json(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        d = dict(r)
        d["assessment_date"] = date.fromisoformat(d["assessment_date"])
        d["topic_prerequisites"] = tuple(d.get("topic_prerequisites") or ())
        out.append(d)
    return out


def group_count(rows: list[dict[str, Any]], key: str) -> dict[Any, int]:
    c: dict[Any, int] = defaultdict(int)
    for r in rows:
        c[r[key]] += 1
    return dict(c)
