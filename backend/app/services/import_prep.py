"""Guided import preparation: worksheet and header-row selection, column mapping and shared values.

The preparation step only turns a stored source file plus an explicit, user-confirmed configuration into a table with
the canonical column names. Validation and commit are done by the existing pipeline (``importer.validate_dataframe``
and ``import_store.commit_rows``); nothing here writes to the analytical dataset.

Rules (documented in docs/IMPORT_FORMAT.md):
* Workbooks are read with openpyxl in read-only mode. Formulas are never executed: the value cached by the
  spreadsheet program is used; a formula cell without a cached value is reported, never recalculated.
* Merged cells are not forward-filled: only the top-left cell of a merged range has a value.
* Source columns are identified by position ("c0" = column A), so equal or empty headers stay distinguishable.
* Header detection and mapping suggestions are suggestions only. Ambiguous candidates are never preselected.
* A field gets its values from exactly one source: a column, an explicitly confirmed shared value (only for the
  fields in SHARED_ELIGIBLE), or — only where the schema already permits an empty value — "not in file".
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import time
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime
from typing import Any

import pandas as pd

from app.services.importer import (
    ASSESSMENT_KINDS,
    CODE_RE,
    MAX_XLSX_MEMBERS,
    MAX_XLSX_UNCOMPRESSED_BYTES,
    NAME_LIKE,
    OPTIONAL_COLUMNS,
    REQUIRED_COLUMNS,
    FileFormatError,
    _date,
    parse_number,
)

# --------------------------------------------------------------------------- limits

MAX_SHEETS = 50
MAX_COLUMNS = 200  # columns beyond this make the sheet unsupported (reported, never truncated silently)
MAX_CELLS = 4_000_000  # non-empty + empty cells actually iterated across the workbook
MAX_ROW_SCAN = 1_048_576  # Excel's own row limit; iteration stops here at the latest
PARSE_SECONDS = 60.0  # wall-clock budget for one workbook pass
PREVIEW_ROWS = 60  # rows kept for the preview and header detection
HEADER_SCAN_ROWS = 50  # the header row must be one of the first rows
SAMPLE_VALUES = 3

# --------------------------------------------------------------------------- field catalogue

FIELD_INFO: dict[str, tuple[str, str]] = {
    "student_id": ("Идентификатор ученика", "Анонимный код ученика. ФИО не допускается."),
    "grade": ("Параллель", "Год обучения — целое число от 1 до 12 (например, 7)."),
    "class": ("Класс", "Название класса, например 7А."),
    "subject": ("Предмет", "Название предмета."),
    "topic_id": ("Код темы", "Устойчивый код темы (буквы, цифры, «-», «_», «.»)."),
    "topic_name": ("Название темы", "Название темы."),
    "assessment_id": ("Идентификатор оценивания", "Код работы (контрольной, диагностики)."),
    "assessment_type": ("Тип оценивания", "pre — входная, post — итоговая, current — текущая."),
    "assessment_date": ("Дата оценивания", "ГГГГ-ММ-ДД, ДД.ММ.ГГГГ или дата Excel."),
    "score": ("Полученный балл", "Набранный балл: число от 0 до максимального."),
    "max_score": ("Максимальный балл", "Максимально возможный балл (> 0). Не подставляется автоматически."),
    "textbook_id": ("Идентификатор учебника", "Код учебника. Можно явно указать, что учебника в файле нет."),
    "school": ("Школа", "Код школы (если не указан — школа по умолчанию)."),
    "item_id": ("Код задания", "Для данных по отдельным заданиям; пусто — итог по теме."),
    "teaching_hours": ("Часы на тему", "Часы, выделенные на тему в классе."),
    "comparison_group": ("Группа сравнения", "Связывает входную и итоговую работы для расчёта прироста."),
    "textbook_name": ("Название учебника", "Отображаемое название учебника."),
    "topic_order": ("Порядок темы", "Порядковый номер темы в программе."),
    "topic_min_hours": ("Мин. часов темы", "Ограничение для оптимизатора."),
    "topic_max_hours": ("Макс. часов темы", "Ограничение для оптимизатора."),
    "topic_priority": ("Приоритет темы", "1–3, ограничение для оптимизатора."),
    "topic_prerequisites": ("Предшествующие темы", "Коды тем через «;»."),
}
ALL_FIELDS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS

# Fields where "one value for the whole file" is meaningful and cannot invent identities or results.
# Deliberately NOT eligible: student_id, topic_id, topic_name, score, max_score, textbook_id, item_id, hours and topic
# settings — those differ per row or would fabricate identities, results or textbook assignments.
SHARED_ELIGIBLE = ["subject", "grade", "class", "assessment_id", "assessment_type", "assessment_date",
                   "comparison_group", "school"]
# Fields whose values may legitimately be empty. Required "textbook_id" is a column the schema requires but whose
# values may be empty (-> MISSING_TEXTBOOK warning); choosing "not in file" states that explicitly.
NONE_ALLOWED = set(OPTIONAL_COLUMNS) | {"textbook_id"}

# --------------------------------------------------------------------------- header normalisation & aliases

_SEP = re.compile(r"[\s_\-./,:;()\[\]«»\"'№#]+")


def norm_header(value: Any) -> str:
    """Conservative normalisation: BOM, outer spaces, case, ё/е and separator differences only."""
    s = "" if value is None else str(value)
    s = s.replace("﻿", "").strip().casefold().replace("ё", "е")
    return _SEP.sub(" ", s).strip()


def _n(*names: str) -> set[str]:
    return {norm_header(x) for x in names}


# Unambiguous aliases -> one field. Kept small and explicit on purpose.
ALIASES: dict[str, set[str]] = {
    "student_id": _n("student_id", "student id", "id ученика", "код ученика", "идентификатор ученика",
                     "ученик id", "номер ученика", "student code", "pupil id"),
    "grade": _n("grade", "параллель", "год обучения", "grade level"),
    "class": _n("class", "класс", "class name", "название класса", "группа класса"),
    "subject": _n("subject", "предмет", "дисциплина", "учебный предмет"),
    "topic_id": _n("topic_id", "topic id", "код темы", "идентификатор темы", "topic code", "номер темы"),
    "topic_name": _n("topic_name", "topic name", "тема", "название темы", "topic"),
    "assessment_id": _n("assessment_id", "assessment id", "идентификатор оценивания", "код оценивания",
                        "код работы", "идентификатор работы", "assessment code"),
    "assessment_type": _n("assessment_type", "assessment type", "тип оценивания", "тип работы", "вид оценивания"),
    "assessment_date": _n("assessment_date", "assessment date", "дата", "дата оценивания", "дата работы", "date"),
    "score": _n("score", "балл", "баллы", "набранный балл", "полученный балл", "points"),
    "max_score": _n("max_score", "max score", "максимальный балл", "макс балл", "максимум баллов",
                    "максимальный балл за задание", "max points"),
    "textbook_id": _n("textbook_id", "textbook id", "код учебника", "идентификатор учебника", "textbook code"),
    "school": _n("school", "школа", "код школы"),
    "item_id": _n("item_id", "item id", "код задания", "номер задания", "задание", "item"),
    "teaching_hours": _n("teaching_hours", "teaching hours", "часы", "часы на тему", "количество часов"),
    "comparison_group": _n("comparison_group", "comparison group", "группа сравнения"),
    "textbook_name": _n("textbook_name", "textbook name", "название учебника"),
    "topic_order": _n("topic_order", "порядок темы"),
    "topic_min_hours": _n("topic_min_hours", "мин часов темы", "минимум часов"),
    "topic_max_hours": _n("topic_max_hours", "макс часов темы", "максимум часов"),
    "topic_priority": _n("topic_priority", "приоритет темы", "приоритет"),
    "topic_prerequisites": _n("topic_prerequisites", "предшествующие темы", "пререквизиты"),
}
# Headers that plausibly mean a field but must never be preselected: header -> (candidate fields, explanation).
AMBIGUOUS: dict[str, tuple[list[str], str]] = {
    norm_header("Оценка"): (["score"], "«Оценка» может быть отметкой по 5-балльной шкале, а не баллом."),
    norm_header("Отметка"): (["score"], "Отметка по шкале оценивания — не то же, что набранный балл."),
    norm_header("Результат"): (["score"], "Неясно, балл это, процент или отметка."),
    norm_header("Учебник"): (["textbook_id", "textbook_name"],
                             "Может быть кодом учебника или его названием; название не является кодом."),
    norm_header("Textbook"): (["textbook_id", "textbook_name"],
                              "Может быть кодом учебника или его названием; название не является кодом."),
    norm_header("ФИО"): (["student_id"], "ФИО — персональные данные, а не анонимный идентификатор."),
    norm_header("Ученик"): (["student_id"], "Если в столбце ФИО, используйте анонимный код вместо него."),
    norm_header("Student"): (["student_id"], "Если в столбце имя, используйте анонимный код вместо него."),
    norm_header("Работа"): (["assessment_id"], "Название работы может не быть устойчивым кодом."),
    norm_header("Тип"): (["assessment_type"], "Неясно, к чему относится «Тип»."),
    norm_header("%"): (["score"], "Процент не является баллом; правило пересчёта не задано."),
    norm_header("Процент"): (["score"], "Процент не является баллом; правило пересчёта не задано."),
}
_ALIAS_INDEX = {alias: f for f, aliases in ALIASES.items() for alias in aliases}


def field_catalogue() -> list[dict[str, Any]]:
    return [{"field": f, "label": FIELD_INFO[f][0], "description": FIELD_INFO[f][1],
             "required": f in REQUIRED_COLUMNS, "shared_allowed": f in SHARED_ELIGIBLE,
             "none_allowed": f in NONE_ALLOWED} for f in ALL_FIELDS]


# --------------------------------------------------------------------------- reading


def col_letter(idx: int) -> str:
    s = ""
    idx += 1
    while idx:
        idx, rem = divmod(idx - 1, 26)
        s = chr(65 + rem) + s
    return s


def _is_empty(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip()) or (isinstance(v, float) and math.isnan(v))


@dataclass
class Sheet:
    name: str
    hidden: bool = False
    rows: list[tuple[int, list[Any]]] = field(default_factory=list)  # (1-based sheet row, cells)
    non_empty_rows: int = 0
    width: int = 0
    problem: str | None = None  # Russian explanation when the sheet cannot be used
    formula_cells: set[tuple[int, int]] = field(default_factory=set)  # formulas without a cached value

    def preview_rows(self) -> list[tuple[int, list[Any]]]:
        return self.rows[:PREVIEW_ROWS]


@dataclass
class Workbook:
    kind: str  # "xlsx" | "csv"
    sheets: list[Sheet]

    def get(self, name: str) -> Sheet | None:
        return next((s for s in self.sheets if s.name == name), None)


class _Budget:
    def __init__(self) -> None:
        self.cells = 0
        self.deadline = time.monotonic() + PARSE_SECONDS

    def spend(self, n: int) -> None:
        self.cells += n
        if self.cells > MAX_CELLS:
            raise FileFormatError("Книга слишком велика для разбора: превышен лимит ячеек. Удалите лишние листы или "
                                  "сохраните нужный лист в CSV.")
        if time.monotonic() > self.deadline:
            raise FileFormatError("Разбор книги занял слишком много времени. Удалите лишние листы или сохраните "
                                  "нужный лист в CSV.")


def _check_zip(content: bytes) -> None:
    if not content.startswith(b"PK"):
        raise FileFormatError("Файл имеет расширение .xlsx, но не является корректной книгой Excel.")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            infos = zf.infolist()
    except zipfile.BadZipFile as exc:
        raise FileFormatError("Файл имеет расширение .xlsx, но не является корректной книгой Excel.") from exc
    if len(infos) > MAX_XLSX_MEMBERS or sum(i.file_size for i in infos) > MAX_XLSX_UNCOMPRESSED_BYTES:
        raise FileFormatError("Книга Excel слишком велика после распаковки. Сохраните данные в CSV или уменьшите файл.")


def _cell(v: Any) -> Any:
    """Normalise a cell to a JSON-friendly native value (numbers stay numbers; dates become date/datetime)."""
    if isinstance(v, str):
        return v
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return str(v)  # rejected later as INVALID_NUMBER, never treated as a value
    if isinstance(v, (int, float, datetime, date)):
        return v
    if isinstance(v, dtime):
        return v.isoformat()
    return None if v is None else str(v)


def _read_sheet_rows(ws, sheet: Sheet, budget: _Budget, keep_all: bool, max_data_rows: int) -> None:
    trailing_blank = 0
    for r_idx, values in enumerate(ws.iter_rows(max_col=MAX_COLUMNS + 1, values_only=True), start=1):
        if r_idx > MAX_ROW_SCAN:
            break
        budget.spend(len(values))
        if len(values) > MAX_COLUMNS and not _is_empty(values[MAX_COLUMNS]):
            sheet.problem = f"На листе больше {MAX_COLUMNS} столбцов — такой лист не поддерживается."
            sheet.rows = sheet.rows[:PREVIEW_ROWS]
            return
        cells = [_cell(v) for v in values[:MAX_COLUMNS]]
        while cells and _is_empty(cells[-1]):
            cells.pop()
        if not cells:
            trailing_blank += 1
            if keep_all and sheet.rows:
                sheet.rows.append((r_idx, []))
            continue
        trailing_blank = 0
        sheet.non_empty_rows += 1
        sheet.width = max(sheet.width, len(cells))
        if sheet.non_empty_rows > max_data_rows + HEADER_SCAN_ROWS:
            sheet.problem = f"На листе больше {max_data_rows} строк данных — превышен лимит импорта."
            sheet.rows = sheet.rows[:PREVIEW_ROWS]
            return
        if keep_all or len(sheet.rows) < PREVIEW_ROWS:
            sheet.rows.append((r_idx, cells))
    if keep_all and trailing_blank:  # drop trailing empty rows: they are not "blank rows inside the data"
        while sheet.rows and not sheet.rows[-1][1]:
            sheet.rows.pop()


def read_workbook(content: bytes, filename: str, *, max_data_rows: int, sheet_name: str | None = None,
                  detect_formulas: bool = False) -> Workbook:
    """Read a CSV or XLSX file. With ``sheet_name`` only that sheet is read completely; otherwise every sheet is
    scanned (counts and the first PREVIEW_ROWS rows only). Raises FileFormatError."""
    if not content:
        raise FileFormatError("Файл пустой.")
    lower = filename.lower()
    if lower.endswith(".csv"):
        return Workbook("csv", [_read_csv(content, max_data_rows)])
    if not lower.endswith(".xlsx"):
        raise FileFormatError("Неподдерживаемый формат. Загрузите файл .csv или .xlsx.")
    _check_zip(content)
    import openpyxl  # local import keeps module import cheap

    budget = _Budget()
    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True, keep_links=False)
    except Exception as exc:  # corrupted workbook
        raise FileFormatError("Не удалось прочитать файл Excel: файл повреждён или имеет неверный формат.") from exc
    try:
        worksheets = [ws for ws in wb.worksheets]
        if len(worksheets) > MAX_SHEETS:
            raise FileFormatError(f"В книге больше {MAX_SHEETS} листов. Оставьте только нужные листы.")
        sheets: list[Sheet] = []
        for ws in worksheets:
            sheet = Sheet(name=str(ws.title), hidden=getattr(ws, "sheet_state", "visible") != "visible")
            if sheet_name is None or sheet.name == sheet_name:
                if not hasattr(ws, "iter_rows"):
                    sheet.problem = "Это не лист с таблицей (например, диаграмма)."
                else:
                    try:
                        _read_sheet_rows(ws, sheet, budget, keep_all=sheet_name is not None,
                                         max_data_rows=max_data_rows)
                    except FileFormatError:
                        raise
                    except Exception as exc:
                        raise FileFormatError("Не удалось прочитать лист «%s»: файл повреждён." % sheet.name) from exc
            sheets.append(sheet)
    finally:
        wb.close()
    if sheet_name is not None and detect_formulas:
        target = next((s for s in sheets if s.name == sheet_name), None)
        if target is not None and target.problem is None:
            target.formula_cells = _uncached_formulas(content, target, budget)
    return Workbook("xlsx", sheets)


def _uncached_formulas(content: bytes, sheet: Sheet, budget: _Budget) -> set[tuple[int, int]]:
    """Positions of formula cells for which the file holds no cached value. Formulas are never evaluated."""
    import openpyxl

    empty_positions = {(r, c) for r, cells in sheet.rows for c in range(sheet.width)
                       if c >= len(cells) or _is_empty(cells[c])}
    if not empty_positions:
        return set()
    out: set[tuple[int, int]] = set()
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=False, keep_links=False)
    try:
        ws = wb[sheet.name]
        last = sheet.rows[-1][0] if sheet.rows else 0
        for r_idx, values in enumerate(ws.iter_rows(max_row=last, max_col=sheet.width, values_only=True), start=1):
            budget.spend(len(values))
            for c, v in enumerate(values):
                if isinstance(v, str) and v.startswith("=") and (r_idx, c) in empty_positions:
                    out.add((r_idx, c))
    finally:
        wb.close()
    return out


def _read_csv(content: bytes, max_data_rows: int) -> Sheet:
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
    head = text.splitlines()[:HEADER_SCAN_ROWS]
    # Delimiter: the one used more often in the first lines (title rows may contain neither).
    delimiter = ";" if sum(line.count(";") for line in head) > sum(line.count(",") for line in head) else ","
    sheet = Sheet(name="CSV")
    try:
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        for r_idx, values in enumerate(reader, start=1):
            if len(values) > MAX_COLUMNS and any(v.strip() for v in values[MAX_COLUMNS:]):
                raise FileFormatError(f"В файле больше {MAX_COLUMNS} столбцов — такой файл не поддерживается.")
            cells: list[Any] = list(values[:MAX_COLUMNS])
            while cells and _is_empty(cells[-1]):
                cells.pop()
            if not cells:
                if sheet.rows:
                    sheet.rows.append((r_idx, []))
                continue
            sheet.non_empty_rows += 1
            sheet.width = max(sheet.width, len(cells))
            if sheet.non_empty_rows > max_data_rows + HEADER_SCAN_ROWS:
                raise FileFormatError(f"Слишком много строк (максимум {max_data_rows}).")
            sheet.rows.append((r_idx, cells))
    except csv.Error as exc:
        raise FileFormatError("Не удалось разобрать CSV: проверьте разделители и кавычки.") from exc
    while sheet.rows and not sheet.rows[-1][1]:
        sheet.rows.pop()
    return sheet


# --------------------------------------------------------------------------- inspection


def _text(v: Any) -> str:
    if _is_empty(v):
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, datetime):
        return v.date().isoformat() if v.time() == dtime() else v.isoformat(sep=" ")
    if isinstance(v, date):
        return v.isoformat()
    return str(v).strip()


def _row_header_score(cells: list[Any]) -> tuple[int, int]:
    """(known header matches, non-empty text cells) for a candidate header row."""
    texts = [norm_header(c) for c in cells if isinstance(c, str) and c.strip()]
    known = sum(1 for t in texts if t in _ALIAS_INDEX or t in AMBIGUOUS)
    return known, len(texts)


def suggest_header_row(sheet: Sheet) -> dict[str, Any]:
    """Suggest a header row among the first HEADER_SCAN_ROWS rows. Returns {row, confidence, reason}."""
    candidates = [(r, cells) for r, cells in sheet.rows if r <= HEADER_SCAN_ROWS and cells]
    if not candidates:
        return {"row": None, "confidence": "none", "reason": "Лист пустой."}
    best = max(candidates, key=lambda rc: (_row_header_score(rc[1])[0], -rc[0]))
    known, _ = _row_header_score(best[1])
    if known >= 3:
        return {"row": best[0], "confidence": "high",
                "reason": f"В строке {best[0]} найдено {known} знакомых названий столбцов."}
    # Fall back to the first row that has at least two text cells and is followed by a non-empty row.
    for i, (r, cells) in enumerate(candidates):
        _, texts = _row_header_score(cells)
        if texts >= 2 and texts >= 0.6 * len([c for c in cells if not _is_empty(c)]):
            return {"row": r, "confidence": "low",
                    "reason": f"Строка {r} — первая строка, похожая на заголовок. Проверьте выбор."}
    return {"row": candidates[0][0], "confidence": "low",
            "reason": "Заголовок не распознан уверенно. Выберите строку с названиями столбцов."}


def sheet_summary(sheet: Sheet) -> dict[str, Any]:
    hdr = suggest_header_row(sheet) if not sheet.problem else {"row": None, "confidence": "none"}
    known = 0
    if hdr["row"] is not None:
        cells = next(c for r, c in sheet.rows if r == hdr["row"])
        known = _row_header_score(cells)[0]
    return {"name": sheet.name, "hidden": sheet.hidden, "empty": sheet.non_empty_rows == 0 and not sheet.problem,
            "non_empty_rows": sheet.non_empty_rows, "columns": sheet.width, "problem": sheet.problem,
            "known_headers": known}


def suggest_sheet(sheets: list[Sheet]) -> dict[str, Any]:
    """Automatic choice only among visible, usable, non-empty sheets; ties are left to the user."""
    usable = [s for s in sheets if not s.hidden and not s.problem and s.non_empty_rows > 0]
    if not usable:
        return {"name": None, "reason": "Нет видимых листов с данными."}
    if len(usable) == 1:
        return {"name": usable[0].name, "reason": "Единственный видимый лист с данными."}
    scored = sorted(((sheet_summary(s)["known_headers"], s.name) for s in usable), reverse=True)
    if scored[0][0] >= 3 and scored[0][0] > scored[1][0]:
        return {"name": scored[0][1], "reason": "На этом листе больше всего знакомых названий столбцов."}
    return {"name": None, "reason": "Несколько листов с данными — выберите нужный."}


@dataclass
class Column:
    id: str
    index: int
    letter: str
    header: str
    label: str  # display text: header or "Столбец B (без заголовка)"


def header_columns(sheet: Sheet, header_row: int) -> list[Column]:
    cells = next((c for r, c in sheet.rows if r == header_row), None)
    if cells is None:
        return []
    width = sheet.width
    out = []
    for i in range(width):
        h = _text(cells[i]) if i < len(cells) else ""
        letter = col_letter(i)
        out.append(Column(f"c{i}", i, letter, h, h or f"Столбец {letter} (без заголовка)"))
    return out


def _data_rows(sheet: Sheet, header_row: int) -> list[tuple[int, list[Any]]]:
    return [(r, c) for r, c in sheet.rows if r > header_row]


def suggest_mapping(columns: list[Column]) -> dict[str, Any]:
    """Return {field: {column, confidence}} for unambiguous suggestions and per-field ambiguity notes."""
    by_field: dict[str, list[tuple[Column, str]]] = {}
    notes: dict[str, list[dict[str, str]]] = {}
    for col in columns:
        n = norm_header(col.header)
        if not n:
            continue
        f = _ALIAS_INDEX.get(n)
        if f:
            by_field.setdefault(f, []).append((col, "exact" if n == norm_header(f) else "alias"))
            continue
        if n in AMBIGUOUS:
            fields, why = AMBIGUOUS[n]
            for f2 in fields:
                notes.setdefault(f2, []).append({"column": col.id, "reason": why})
    suggestions: dict[str, dict[str, str]] = {}
    for f, cands in by_field.items():
        if len(cands) == 1:
            suggestions[f] = {"column": cands[0][0].id, "confidence": cands[0][1]}
        else:
            for col, _ in cands:
                notes.setdefault(f, []).append(
                    {"column": col.id, "reason": "Подходят несколько столбцов с похожими заголовками — выберите один."})
    return {"suggested": suggestions, "ambiguous": notes}


def layout_notices(sheet: Sheet, header_row: int, columns: list[Column], suggested: dict[str, Any]) -> list[dict]:
    """Detect layouts that cannot be mapped to one-record-per-row honestly (advisory, shown before mapping)."""
    notices: list[dict[str, Any]] = []
    rows = _data_rows(sheet, header_row)
    header_cells = [norm_header(c.header) for c in columns]
    repeated = [r for r, cells in rows
                if sum(1 for i, c in enumerate(cells) if header_cells[i] and norm_header(c) == header_cells[i]) >= 3]
    if repeated:
        notices.append({"code": "REPEATED_HEADER", "severity": "error",
                        "message": f"Строки {', '.join(map(str, repeated[:5]))} повторяют заголовок — похоже, на листе "
                                   "несколько таблиц. Оставьте одну таблицу на листе или вынесите остальные на другие "
                                   "листы.", "rows": repeated[:20]})
    mapped_cols = {s["column"] for s in suggested.values()}
    if "score" not in suggested:
        numeric_unmapped = []
        for col in columns:
            if col.id in mapped_cols or not col.header:
                continue
            vals = [cells[col.index] for _, cells in rows[:PREVIEW_ROWS] if col.index < len(cells)
                    and not _is_empty(cells[col.index])]
            if vals and sum(1 for v in vals if parse_number(v)[0] is not None) >= 0.8 * len(vals):
                numeric_unmapped.append(col.label)
        if len(numeric_unmapped) >= 3:
            notices.append({"code": "WIDE_LAYOUT_SUSPECTED", "severity": "warning",
                            "message": "Похоже, что баллы по разным темам или заданиям записаны в отдельных столбцах "
                                       f"({', '.join(numeric_unmapped[:5])}{'…' if len(numeric_unmapped) > 5 else ''}). "
                                       "Импорт ожидает одну строку на результат ученика по одной теме. Такую таблицу "
                                       "нужно преобразовать по шаблону; автоматическое преобразование не выполняется."})
    if len(rows) == 0:
        notices.append({"code": "NO_DATA_ROWS", "severity": "error",
                        "message": "Под выбранной строкой заголовка нет строк с данными."})
    return notices


def inspect_sheet(sheet: Sheet, header_row: int | None) -> dict[str, Any]:
    """Preview, columns with sample values, suggestions and layout notices for one sheet and header row."""
    hdr = suggest_header_row(sheet)
    preview = [{"row": r, "cells": [_text(v) for v in cells]} for r, cells in sheet.preview_rows()]
    out: dict[str, Any] = {"sheet": sheet.name, "hidden": sheet.hidden, "problem": sheet.problem,
                           "width": sheet.width, "header_suggestion": hdr, "preview": preview,
                           "header_rows_allowed": [r for r, c in sheet.rows if r <= HEADER_SCAN_ROWS and c],
                           "header_row": header_row, "columns": [], "suggestions": {"suggested": {}, "ambiguous": {}},
                           "notices": [], "duplicate_headers": []}
    if sheet.problem or header_row is None:
        return out
    columns = header_columns(sheet, header_row)
    rows = _data_rows(sheet, header_row)
    cols_out = []
    for col in columns:
        samples: list[str] = []
        for _, cells in rows:
            if col.index < len(cells) and not _is_empty(cells[col.index]):
                t = _text(cells[col.index])
                if t not in samples:
                    samples.append(t[:60])
            if len(samples) >= SAMPLE_VALUES:
                break
        cols_out.append({"id": col.id, "letter": col.letter, "header": col.header, "label": col.label,
                         "samples": samples, "empty": not samples})
    sugg = suggest_mapping(columns)
    counts: dict[str, list[str]] = {}
    for col in columns:
        if col.header:
            counts.setdefault(norm_header(col.header), []).append(col.letter)
    out["duplicate_headers"] = [{"header": next(c.header for c in columns if norm_header(c.header) == k),
                                 "letters": v} for k, v in counts.items() if len(v) > 1]
    out.update(columns=cols_out, suggestions=sugg, notices=layout_notices(sheet, header_row, columns,
                                                                           sugg["suggested"]),
               data_rows=sum(1 for _, c in rows if c))
    return out


# --------------------------------------------------------------------------- configuration


class ConfigError(ValueError):
    def __init__(self, issues: list[dict[str, Any]]):
        super().__init__("invalid configuration")
        self.issues = issues


def _issue(code: str, message: str, fld: str | None = None, column: str | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "field": fld, "column": column}


def validate_shared_value(fld: str, value: str) -> str | None:
    """Return a Russian error message if the shared value would not pass row validation; None if acceptable."""
    v = value.strip()
    label = FIELD_INFO[fld][0]
    if not v:
        return f"Введите значение для поля «{label}»."
    if len(v) > 255:
        return f"Значение поля «{label}» слишком длинное."
    if fld == "grade":
        g, _ = parse_number(v)
        if g is None or g != int(g) or not 1 <= g <= 12:
            return "Параллель должна быть целым числом от 1 до 12."
    elif fld == "assessment_type":
        if v.lower() not in ASSESSMENT_KINDS:
            return "Тип оценивания должен быть pre, post или current."
    elif fld == "assessment_date":
        if _date(v) is None:
            return "Дата должна быть в формате ГГГГ-ММ-ДД или ДД.ММ.ГГГГ."
    elif fld in ("assessment_id", "school", "comparison_group"):
        if not CODE_RE.match(v):
            return f"Недопустимый код в поле «{label}» (буквы, цифры, «-», «_», «.»; без пробелов)."
        if NAME_LIKE.match(v):
            return "Похоже на ФИО — используйте код."
    elif fld == "class" and len(v) > 64:
        return "Название класса слишком длинное."
    return None


@dataclass
class PrepConfig:
    sheet: str
    header_row: int
    fields: dict[str, dict[str, Any]]  # field -> {"source": "column"|"value"|"none", "column"?, "value"?}
    confirm_shared: bool

    def canonical(self) -> dict[str, Any]:
        return {"sheet": self.sheet, "header_row": self.header_row,
                "fields": {f: self.fields[f] for f in sorted(self.fields)}, "confirm_shared": self.confirm_shared}


def config_hash(source_sha256: str, cfg: PrepConfig) -> str:
    payload = json.dumps({"source": source_sha256, "config": cfg.canonical()}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def check_config(raw: dict[str, Any], wb: Workbook) -> PrepConfig:
    """Validate a configuration submitted by the client against the stored source. Raises ConfigError."""
    issues: list[dict[str, Any]] = []
    sheet_name = raw.get("sheet")
    sheet = wb.get(sheet_name) if isinstance(sheet_name, str) else None
    if sheet is None:
        raise ConfigError([_issue("UNKNOWN_SHEET", "Выбранный лист не найден в файле.")])
    if sheet.problem:
        raise ConfigError([_issue("UNSUPPORTED_SHEET", sheet.problem)])
    header_row = raw.get("header_row")
    allowed_rows = {r for r, c in sheet.rows if r <= HEADER_SCAN_ROWS and c}
    if not isinstance(header_row, int) or isinstance(header_row, bool) or header_row not in allowed_rows:
        raise ConfigError([_issue("INVALID_HEADER_ROW",
                                  f"Строка заголовка должна быть непустой строкой среди первых {HEADER_SCAN_ROWS}.")])
    columns = {c.id: c for c in header_columns(sheet, header_row)}
    fields_raw = raw.get("fields")
    if not isinstance(fields_raw, dict):
        raise ConfigError([_issue("INVALID_MAPPING", "Сопоставление столбцов не передано.")])
    fields: dict[str, dict[str, Any]] = {}
    used: dict[str, str] = {}
    for fld, spec in fields_raw.items():
        if fld not in ALL_FIELDS:
            issues.append(_issue("UNKNOWN_FIELD", "Неизвестное поле приложения.", fld))
            continue
        label = FIELD_INFO[fld][0]
        if not isinstance(spec, dict) or spec.get("source") not in ("column", "value", "none"):
            issues.append(_issue("INVALID_MAPPING", f"Неверное сопоставление для поля «{label}».", fld))
            continue
        src = spec["source"]
        if src == "column":
            cid = spec.get("column")
            if not isinstance(cid, str) or cid not in columns:
                issues.append(_issue("UNKNOWN_COLUMN", f"Для поля «{label}» выбран несуществующий столбец.", fld))
                continue
            if cid in used:
                issues.append(_issue("COLUMN_REUSED",
                                     f"Столбец «{columns[cid].label}» уже выбран для поля "
                                     f"«{FIELD_INFO[used[cid]][0]}». Один столбец — одно поле.", fld, cid))
                continue
            used[cid] = fld
            fields[fld] = {"source": "column", "column": cid}
        elif src == "value":
            if fld not in SHARED_ELIGIBLE:
                issues.append(_issue("SHARED_NOT_ALLOWED",
                                     f"Для поля «{label}» нельзя задать одно значение на весь файл.", fld))
                continue
            value = spec.get("value")
            msg = validate_shared_value(fld, value) if isinstance(value, str) else "Значение не передано."
            if msg:
                issues.append(_issue("INVALID_SHARED_VALUE", msg, fld))
                continue
            fields[fld] = {"source": "value", "value": value.strip()}
        else:
            if fld not in NONE_ALLOWED:
                issues.append(_issue("MISSING_MAPPING", f"Выберите столбец для поля «{label}».", fld))
                continue
            fields[fld] = {"source": "none"}
    for fld in REQUIRED_COLUMNS:
        if fld not in fields and not any(i["field"] == fld for i in issues):
            hint = " или задайте одно значение для всего файла" if fld in SHARED_ELIGIBLE else ""
            if fld == "textbook_id":
                hint = " или отметьте, что учебника в файле нет"
            issues.append(_issue("MISSING_MAPPING", f"Выберите столбец для поля «{FIELD_INFO[fld][0]}»{hint}.", fld))
    confirm = raw.get("confirm_shared") is True
    if any(s["source"] == "value" for s in fields.values()) and not confirm:
        issues.append(_issue("SHARED_NOT_CONFIRMED",
                             "Подтвердите, что заданные вручную значения относятся ко всем строкам файла."))
    if issues:
        raise ConfigError(issues)
    return PrepConfig(sheet.name, header_row, fields, confirm)


@dataclass
class Prepared:
    frame: pd.DataFrame
    row_numbers: list[int]
    errors: list[dict[str, Any]]  # preparation errors (Issue-like dicts)
    ignored_columns: list[str]
    warnings: list[dict[str, Any]] = field(default_factory=list)


def prepare_frame(sheet: Sheet, cfg: PrepConfig) -> Prepared:
    """Build a DataFrame with canonical column names from the selected sheet, header row, mapping and values."""
    columns = {c.id: c for c in header_columns(sheet, cfg.header_row)}
    rows = _data_rows(sheet, cfg.header_row)
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    mapped_idx = [columns[s["column"]].index for s in cfg.fields.values() if s["source"] == "column"]
    has_mapped = [any(i < len(cells) and not _is_empty(cells[i]) for i in mapped_idx) for _, cells in rows]
    data: dict[str, list[Any]] = {}
    for fld, spec in cfg.fields.items():
        if spec["source"] == "column":
            idx = columns[spec["column"]].index
            data[fld] = [cells[idx] if idx < len(cells) else None for _, cells in rows]
        elif spec["source"] == "value":
            # A shared value never turns a row without mapped data (blank row, note, footer) into a record.
            data[fld] = [spec["value"] if has_mapped[i] else None for i in range(len(rows))]
        else:
            data[fld] = [None] * len(rows)
    only_ignored = [r for i, (r, cells) in enumerate(rows) if cells and not has_mapped[i]]
    if only_ignored:
        warnings.append({"row": None, "column": None, "code": "ROWS_WITHOUT_MAPPED_DATA",
                         "message": f"{len(only_ignored)} строк содержат данные только в неиспользуемых столбцах и не "
                                    "будут импортированы (например, строки "
                                    f"{', '.join(map(str, only_ignored[:5]))}). Проверьте, не пропущено ли "
                                    "сопоставление."})
    frame = pd.DataFrame(data, dtype=object) if rows else pd.DataFrame(columns=list(cfg.fields), dtype=object)
    # Formula cells without a cached value in mapped columns: reported, never recalculated.
    for fld, spec in cfg.fields.items():
        if spec["source"] != "column":
            continue
        col = columns[spec["column"]]
        hit = sorted(r for r, c in sheet.formula_cells if c == col.index and r > cfg.header_row)
        if hit:
            errors.append({"row": hit[0], "column": fld, "code": "FORMULA_WITHOUT_VALUE",
                           "message": f"Столбец «{col.label}»: {len(hit)} ячеек с формулой без сохранённого значения "
                                      f"(первая — строка {hit[0]}). Откройте файл в Excel, пересчитайте и сохраните "
                                      "его заново; формулы при импорте не вычисляются."})
    header_norm = [norm_header(c.header) for c in columns.values()]
    for r, cells in rows:
        if sum(1 for i, c in enumerate(cells) if i < len(header_norm) and header_norm[i]
               and norm_header(c) == header_norm[i]) >= 3:
            errors.append({"row": r, "column": None, "code": "REPEATED_HEADER",
                           "message": "Строка повторяет заголовок — похоже, на листе несколько таблиц."})
    used = {s["column"] for s in cfg.fields.values() if s["source"] == "column"}
    ignored = [c.label for cid, c in columns.items() if cid not in used and (c.header or _column_has_data(rows, c))]
    return Prepared(frame, [r for r, _ in rows], errors, ignored, warnings)


def _column_has_data(rows: list[tuple[int, list[Any]]], col: Column) -> bool:
    return any(col.index < len(cells) and not _is_empty(cells[col.index]) for _, cells in rows)


def config_summary(sheet: Sheet, cfg: PrepConfig, ignored: list[str]) -> dict[str, Any]:
    columns = {c.id: c for c in header_columns(sheet, cfg.header_row)}
    mapped, shared, absent = [], [], []
    for fld in ALL_FIELDS:
        spec = cfg.fields.get(fld)
        if spec is None:
            continue
        label = FIELD_INFO[fld][0]
        if spec["source"] == "column":
            c = columns[spec["column"]]
            mapped.append({"field": fld, "label": label, "column": c.id, "letter": c.letter, "header": c.label})
        elif spec["source"] == "value":
            shared.append({"field": fld, "label": label, "value": spec["value"]})
        else:
            absent.append({"field": fld, "label": label})
    return {"sheet": sheet.name, "sheet_hidden": sheet.hidden, "header_row": cfg.header_row, "mapped": mapped,
            "shared": shared, "not_in_file": absent, "ignored_columns": ignored}
