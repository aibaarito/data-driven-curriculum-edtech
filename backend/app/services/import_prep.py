"""Guided import, stage 1: reading a source file and interpreting its structure (nothing is written here).

Responsibilities:
* Read CSV (encoding and delimiter detected, user can override) and XLSX (read-only, bounded, formulas never executed).
* Describe a selected region: worksheet, header row (one row or a two-row header with merged group headings),
  column range and last data row.
* Flag rows that need a decision (repeated headers, totals, explanatory text) without removing them.
* Profile columns and suggest a layout (long records, wide gradebook, aggregate table, general table) and mappings.

All suggestions are proposals shown to the user; nothing is applied silently. Interpretation into records is done by
``import_layouts``; parsing rules live in ``import_rules``. Documented in docs/IMPORT_FORMAT.md.
"""
from __future__ import annotations

import csv
import io
import math
import re
import time
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime
from typing import Any
from xml.etree import ElementTree as ET

from app.services.importer import (
    MAX_XLSX_MEMBERS,
    MAX_XLSX_UNCOMPRESSED_BYTES,
    OPTIONAL_COLUMNS,
    REQUIRED_COLUMNS,
    FileFormatError,
    parse_number,
)

# --------------------------------------------------------------------------- limits

MAX_SHEETS = 50
MAX_COLUMNS = 200  # columns beyond this make the sheet unsupported (reported, never truncated silently)
MAX_CELLS = 4_000_000  # cells actually iterated across the workbook
MAX_ROW_SCAN = 1_048_576  # Excel's own row limit; iteration stops here at the latest
PARSE_SECONDS = 60.0  # wall-clock budget for one workbook pass
PREVIEW_ROWS = 60  # rows kept for the preview and header detection when scanning all sheets
HEADER_SCAN_ROWS = 50  # the header row must be one of the first rows
SAMPLE_VALUES = 3
PROFILE_ROWS = 500  # data rows used for column profiling and suggestions
MAX_MERGES = 20_000

ENCODINGS = ("auto", "utf-8", "cp1251")
DELIMITERS = {"auto": None, ",": ",", ";": ";", "\t": "\t"}
DELIMITER_LABEL = {",": "запятая", ";": "точка с запятой", "\t": "табуляция"}

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
    "assessment_date": ("Дата оценивания", "Формат задаётся в правилах разбора; дата Excel читается как есть."),
    "score": ("Полученный балл", "Результат; его смысл (баллы, проценты, верно/неверно, шкала) задаётся явно."),
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
SHARED_ELIGIBLE = ["subject", "grade", "class", "assessment_id", "assessment_type", "assessment_date",
                   "comparison_group", "school"]
NONE_ALLOWED = set(OPTIONAL_COLUMNS) | {"textbook_id"}
# In a wide gradebook these come from the selected result columns (per-column metadata), not from row columns.
WIDE_RESULT_FIELDS = ["topic_id", "topic_name", "item_id", "score", "max_score"]
# Fields that may be given per result column in a wide gradebook (fall back to the row/shared mapping).
WIDE_PER_COLUMN = ["topic_id", "topic_name", "item_id", "max_score", "assessment_id", "assessment_type",
                   "assessment_date"]

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
    "max_score": _n("max_score", "max score", "максимальный балл", "макс балл", "максимум баллов", "максимум",
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
    norm_header("Оценка"): (["score"], "«Оценка» может быть отметкой по 5-балльной шкале, баллом или другой "
                                       "характеристикой — укажите смысл явно."),
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
    norm_header("%"): (["score"], "Процент не является баллом; выберите правило «проценты»."),
    norm_header("Процент"): (["score"], "Процент не является баллом; выберите правило «проценты»."),
}
_ALIAS_INDEX = {alias: f for f, aliases in ALIASES.items() for alias in aliases}

# Aggregate tables: roles of columns (class/topic averages, shares, counts).
AGG_ROLES: dict[str, tuple[str, set[str]]] = {
    "class": ("Класс", ALIASES["class"]),
    "grade": ("Параллель", ALIASES["grade"]),
    "subject": ("Предмет", ALIASES["subject"]),
    "topic_id": ("Код темы", ALIASES["topic_id"]),
    "topic_name": ("Тема", ALIASES["topic_name"]),
    "textbook": ("Учебник", ALIASES["textbook_id"] | ALIASES["textbook_name"] | _n("учебник", "textbook")),
    "assessment": ("Оценивание", ALIASES["assessment_id"] | _n("работа", "контрольная", "assessment")),
    "date": ("Дата", ALIASES["assessment_date"]),
    "value": ("Показатель", _n("средний балл", "средний процент", "средний %", "% выполнения",
                               "процент выполнения", "успеваемость", "успеваемость %", "качество знаний",
                               "качество %", "доля", "average", "average score", "mean", "mean score",
                               "avg", "percent", "% correct", "результат %", "процент", "%")),
    "max": ("Максимум показателя", ALIASES["max_score"]),
    "count": ("Число учеников", _n("количество учеников", "кол во учеников", "число учеников",
                                   "количество участников", "участников", "n", "count", "students",
                                   "кол во", "количество")),
}
AGG_GROUP_ROLES = ["class", "grade", "subject", "topic_id", "topic_name", "textbook", "assessment", "date"]
_TOTAL_RE = re.compile(r"^(итог|итого|всего|сумма|среднее|средний балл по|в среднем|total|sum|average|mean)\b")
_AVERAGE_HEADER = re.compile(r"(итог|сумма|всего|total|sum|средн|average|mean)")
_ID_HEADER = re.compile(r"(^| )(id|код|номер|идентификатор|code)( |$)")


def field_catalogue() -> list[dict[str, Any]]:
    return [{"field": f, "label": FIELD_INFO[f][0], "description": FIELD_INFO[f][1],
             "required": f in REQUIRED_COLUMNS, "shared_allowed": f in SHARED_ELIGIBLE,
             "none_allowed": f in NONE_ALLOWED, "wide_result": f in WIDE_RESULT_FIELDS,
             "wide_per_column": f in WIDE_PER_COLUMN} for f in ALL_FIELDS]


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
    merges: list[tuple[int, int, int, int]] = field(default_factory=list)  # (row1, col1, row2, col2); cols 0-based
    complete: bool = False  # all rows read (not only the preview)

    def preview_rows(self) -> list[tuple[int, list[Any]]]:
        return self.rows[:PREVIEW_ROWS]


@dataclass
class Workbook:
    kind: str  # "xlsx" | "csv"
    sheets: list[Sheet]
    csv_info: dict[str, Any] | None = None

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
    # Macro parts (vbaProject.bin) are never executed: openpyxl only reads cell values.


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
            if keep_all and sheet.rows:
                sheet.rows.append((r_idx, []))
            continue
        sheet.non_empty_rows += 1
        sheet.width = max(sheet.width, len(cells))
        if sheet.non_empty_rows > max_data_rows + HEADER_SCAN_ROWS:
            sheet.problem = f"На листе больше {max_data_rows} строк данных — превышен лимит импорта."
            sheet.rows = sheet.rows[:PREVIEW_ROWS]
            return
        if keep_all or len(sheet.rows) < PREVIEW_ROWS:
            sheet.rows.append((r_idx, cells))
    if keep_all:  # trailing empty rows are not "blank rows inside the data"
        while sheet.rows and not sheet.rows[-1][1]:
            sheet.rows.pop()
        sheet.complete = True


_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def _merged_ranges(content: bytes, sheet_name: str) -> list[tuple[int, int, int, int]]:
    """Merged ranges of one worksheet, read from the sheet XML (openpyxl's read-only mode does not expose them)."""
    from openpyxl.utils.cell import range_boundaries

    out: list[tuple[int, int, int, int]] = []
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            wb = ET.fromstring(zf.read("xl/workbook.xml"))
            rid = next((s.get(f"{{{_REL_NS}}}id") for s in wb.iter(f"{{{_MAIN_NS}}}sheet")
                        if s.get("name") == sheet_name), None)
            rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
            target = next((r.get("Target") for r in rels.iter(f"{{{_PKG_REL_NS}}}Relationship")
                           if r.get("Id") == rid), None)
            if not target:
                return []
            path = target.lstrip("/") if target.startswith("/") else "xl/" + target
            with zf.open(path) as fh:
                for _, el in ET.iterparse(fh):
                    if el.tag == f"{{{_MAIN_NS}}}mergeCell" and el.get("ref"):
                        c1, r1, c2, r2 = range_boundaries(el.get("ref"))
                        out.append((r1, c1 - 1, r2, c2 - 1))
                        if len(out) >= MAX_MERGES:
                            break
                    el.clear()
    except (KeyError, ET.ParseError, ValueError, zipfile.BadZipFile):
        return []  # merges are only used for header labels; without them labels use the cells themselves
    return out


def read_workbook(content: bytes, filename: str, *, max_data_rows: int, sheet_name: str | None = None,
                  detect_formulas: bool = False, encoding: str = "auto", delimiter: str = "auto",
                  merges: bool = False) -> Workbook:
    """Read a CSV or XLSX file. With ``sheet_name`` only that sheet is read completely; otherwise every sheet is
    scanned (counts and the first PREVIEW_ROWS rows only). Raises FileFormatError."""
    if not content:
        raise FileFormatError("Файл пустой.")
    lower = filename.lower()
    if lower.endswith(".csv"):
        sheet, info = _read_csv(content, max_data_rows, encoding, delimiter)
        return Workbook("csv", [sheet], info)
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
        worksheets = list(wb.worksheets)
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
    for s in sheets:
        if (merges or sheet_name is not None) and (sheet_name is None or s.name == sheet_name) and not s.problem \
                and s.non_empty_rows:
            s.merges = _merged_ranges(content, s.name)
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


def _decode(content: bytes, encoding: str) -> tuple[str, str, str]:
    """Return (text, encoding used, confidence)."""
    if encoding not in ENCODINGS:
        raise FileFormatError("Неизвестная кодировка.")
    if encoding == "cp1251":
        return content.decode("cp1251", errors="strict"), "cp1251", "user"
    if encoding == "utf-8":
        try:
            return content.decode("utf-8-sig"), "utf-8", "user"
        except UnicodeDecodeError as exc:
            raise FileFormatError("Файл не является корректным UTF-8. Выберите кодировку Windows-1251.") from exc
    try:
        text = content.decode("utf-8-sig")
        return text, "utf-8", "high"
    except UnicodeDecodeError:
        pass
    try:
        text = content.decode("cp1251")
    except UnicodeDecodeError as exc:
        raise FileFormatError("Не удалось определить кодировку (ожидается UTF-8 или Windows-1251).") from exc
    # cp1251 decodes almost any bytes: confident only if the text is mostly Cyrillic/ASCII letters.
    letters = sum(ch.isalpha() for ch in text[:20000])
    cyr = sum("а" <= ch.lower() <= "я" or ch.lower() == "ё" for ch in text[:20000])
    ascii_letters = sum(ch.isascii() and ch.isalpha() for ch in text[:20000])
    confident = letters and (cyr + ascii_letters) / letters > 0.95
    return text, "cp1251", "high" if confident else "low"


def _detect_delimiter(lines: list[str]) -> tuple[str, str, list[str]]:
    """Choose among comma, semicolon and tab by consistent field counts (quotes respected)."""
    scores: dict[str, tuple[float, int]] = {}
    sample = [line for line in lines if line.strip()][:HEADER_SCAN_ROWS]
    for d in (",", ";", "\t"):
        try:
            counts = [len(r) for r in csv.reader(sample, delimiter=d)]
        except csv.Error:
            continue
        multi = [c for c in counts if c > 1]
        if not multi:
            scores[d] = (0.0, 1)
            continue
        mode = max(set(multi), key=multi.count)
        scores[d] = (multi.count(mode) / len(counts) * min(mode, 50), mode)
    ranked = sorted(scores.items(), key=lambda kv: kv[1][0], reverse=True)
    if not ranked or ranked[0][1][0] == 0:
        return ",", "low", []
    best, (score, _) = ranked[0]
    alternatives = [d for d, (s, _) in ranked[1:] if s > 0 and s >= 0.8 * score]
    return best, "low" if alternatives else "high", alternatives


def _read_csv(content: bytes, max_data_rows: int, encoding: str = "auto", delimiter: str = "auto"
              ) -> tuple[Sheet, dict[str, Any]]:
    if content.startswith(b"PK") or b"\x00" in content[:4096]:
        raise FileFormatError("Файл имеет расширение .csv, но содержит двоичные данные.")
    text, enc, enc_conf = _decode(content, encoding)
    if not text.strip():
        raise FileFormatError("Файл пустой.")
    if delimiter not in DELIMITERS:
        raise FileFormatError("Неизвестный разделитель.")
    head = text.splitlines()[:HEADER_SCAN_ROWS * 2]
    if delimiter == "auto":
        delim, d_conf, alts = _detect_delimiter(head)
    else:
        delim, d_conf, alts = delimiter, "user", []
    sheet = Sheet(name="CSV")
    try:
        # Cells stay text: quoted values and identifiers with leading zeros are preserved exactly.
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=delim)
        for r_idx, values in enumerate(reader, start=1):
            if len(values) > MAX_COLUMNS and any(v.strip() for v in values[MAX_COLUMNS:]):
                raise FileFormatError(f"В файле больше {MAX_COLUMNS} столбцов — проверьте разделитель или уменьшите "
                                      "таблицу.")
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
        raise FileFormatError("Не удалось разобрать CSV: проверьте разделитель и кавычки.") from exc
    while sheet.rows and not sheet.rows[-1][1]:
        sheet.rows.pop()
    sheet.complete = True
    info = {"encoding": enc, "encoding_confidence": enc_conf, "delimiter": delim,
            "delimiter_label": DELIMITER_LABEL[delim], "delimiter_confidence": d_conf,
            "delimiter_alternatives": [{"value": a, "label": DELIMITER_LABEL[a]} for a in alts]}
    return sheet, info


# --------------------------------------------------------------------------- structure


def text_of(v: Any) -> str:
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
    known = sum(1 for t in texts if t in _ALIAS_INDEX or t in AMBIGUOUS or any(t in a for _, a in AGG_ROLES.values()))
    return known, len(texts)


def suggest_header_row(sheet: Sheet) -> dict[str, Any]:
    """Suggest a header row among the first HEADER_SCAN_ROWS rows. Returns {row, confidence, reason, rows}."""
    candidates = [(r, cells) for r, cells in sheet.rows if r <= HEADER_SCAN_ROWS and cells]
    if not candidates:
        return {"row": None, "confidence": "none", "reason": "Лист пустой.", "header_rows": 1}
    best = max(candidates, key=lambda rc: (_row_header_score(rc[1])[0], -rc[0]))
    known, _ = _row_header_score(best[1])
    if known >= 3:
        out = {"row": best[0], "confidence": "high",
               "reason": f"В строке {best[0]} найдено {known} знакомых названий столбцов.", "header_rows": 1}
    else:
        out = None
        for r, cells in candidates:
            _, texts = _row_header_score(cells)
            if texts >= 2 and texts >= 0.6 * len([c for c in cells if not _is_empty(c)]):
                out = {"row": r, "confidence": "low",
                       "reason": f"Строка {r} — первая строка, похожая на заголовок. Проверьте выбор.",
                       "header_rows": 1}
                break
        out = out or {"row": candidates[0][0], "confidence": "low",
                      "reason": "Заголовок не распознан уверенно. Выберите строку с названиями столбцов.",
                      "header_rows": 1}
    # Two-row header: a row with merged group headings spanning several columns, followed by the column headings.
    r0 = out["row"]
    if any(m[0] == r0 and m[2] == r0 and m[3] > m[1] for m in sheet.merges):
        nxt = next((c for r, c in sheet.rows if r == r0 + 1), [])
        if r0 + 1 <= HEADER_SCAN_ROWS and sum(1 for c in nxt if isinstance(c, str) and c.strip()) >= 2:
            out["row"] = r0 + 1
    above = out["row"] - 1
    if above >= 1 and any(m[0] == above and m[2] == above and m[3] > m[1] for m in sheet.merges):
        group_cells = next((c for r, c in sheet.rows if r == above), [])
        if sum(1 for c in group_cells if isinstance(c, str) and c.strip()) >= 1:
            out["header_rows"] = 2
            out["reason"] += f" Строка {above} содержит объединённые заголовки групп — предложен двухстрочный заголовок."
    return out


def sheet_summary(sheet: Sheet) -> dict[str, Any]:
    hdr = suggest_header_row(sheet) if not sheet.problem else {"row": None}
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
class Selection:
    """Which part of a sheet is the table. Columns are 0-based positions; rows are original sheet rows."""
    header_row: int
    header_rows: int = 1
    first_col: int = 0
    last_col: int | None = None
    last_row: int | None = None
    exclude: frozenset[str] = frozenset()  # row-flag kinds the user chose to exclude

    def canonical(self) -> dict[str, Any]:
        return {"header_row": self.header_row, "header_rows": self.header_rows, "first_col": self.first_col,
                "last_col": self.last_col, "last_row": self.last_row, "exclude": sorted(self.exclude)}


@dataclass
class Column:
    id: str
    index: int
    letter: str
    header: str  # combined label text used for matching ("Группа · Подзаголовок" for two-row headers)
    label: str  # display text
    group: str = ""
    sub: str = ""


def _group_label(sheet: Sheet, row: int, col: int) -> str:
    for r1, c1, r2, c2 in sheet.merges:
        if r1 <= row <= r2 and c1 <= col <= c2:
            cells = next((c for r, c in sheet.rows if r == r1), [])
            return text_of(cells[c1]) if c1 < len(cells) else ""
    cells = next((c for r, c in sheet.rows if r == row), [])
    return text_of(cells[col]) if col < len(cells) else ""


def header_columns(sheet: Sheet, sel: Selection) -> list[Column]:
    cells = next((c for r, c in sheet.rows if r == sel.header_row), None)
    if cells is None:
        return []
    last = sheet.width - 1 if sel.last_col is None else min(sel.last_col, sheet.width - 1)
    out = []
    for i in range(sel.first_col, last + 1):
        sub = text_of(cells[i]) if i < len(cells) else ""
        if not sub:
            # A heading merged vertically over both header rows keeps its value in the upper row.
            sub = _group_label(sheet, sel.header_row, i) if sheet.merges else ""
        group = ""
        if sel.header_rows == 2:
            group = _group_label(sheet, sel.header_row - 1, i)
            if group == sub:
                group = ""
        header = f"{group} · {sub}" if group and sub else (group or sub)
        letter = col_letter(i)
        out.append(Column(f"c{i}", i, letter, header, header or f"Столбец {letter} (без заголовка)", group, sub))
    return out


def data_rows(sheet: Sheet, sel: Selection) -> list[tuple[int, list[Any]]]:
    """Rows below the header inside the selected range (blank rows included, flags not yet applied)."""
    out = []
    for r, cells in sheet.rows:
        if r <= sel.header_row or (sel.last_row is not None and r > sel.last_row):
            continue
        last = len(cells) if sel.last_col is None else min(len(cells), sel.last_col + 1)
        out.append((r, [None] * sel.first_col + list(cells[sel.first_col:last])))
    while out and not any(not _is_empty(c) for c in out[-1][1]):
        out.pop()
    return out


FLAG_LABEL = {"repeated_header": "повтор заголовка", "total": "итоговая строка", "note": "пояснительный текст"}


def row_flags(rows: list[tuple[int, list[Any]]], columns: list[Column]) -> dict[int, str]:
    """Rows that need a decision. They are reported, never removed unless the user excludes their kind."""
    header_norm = {c.index: norm_header(c.sub or c.header) for c in columns}
    width = len(columns)
    flags: dict[int, str] = {}
    for r, cells in rows:
        filled = [(i, c) for i, c in enumerate(cells) if not _is_empty(c)]
        if not filled:
            continue
        if sum(1 for i, c in filled if header_norm.get(i) and norm_header(c) == header_norm[i]) >= min(3, width):
            flags[r] = "repeated_header"
            continue
        first_texts = [norm_header(c) for _, c in filled[:3] if isinstance(c, str)]
        if any(_TOTAL_RE.match(t) for t in first_texts):
            flags[r] = "total"
            continue
        if width >= 3 and len(filled) == 1 and isinstance(filled[0][1], str) and len(filled[0][1].split()) >= 2:
            flags[r] = "note"
    return flags


# --------------------------------------------------------------------------- column profiles & suggestions


_DATE_TEXT = re.compile(r"^\d{1,4}[./-]\d{1,2}[./-]\d{1,4}$")
_PERCENT_TEXT = re.compile(r"^-?\d+(?:[.,]\d+)?\s*%$")
BINARY_TOKENS = {"0", "1", "да", "нет", "верно", "неверно", "+", "-", "true", "false", "yes", "no"}


def profile_column(values: list[Any]) -> dict[str, Any]:
    vals = [v for v in values if not _is_empty(v)]
    n = len(vals)
    if not n:
        return {"filled": 0, "numeric": 0.0, "percent_text": 0.0, "date": 0.0, "distinct": [], "distinct_count": 0,
                "integers": False, "leading_zero": False, "max": None, "min": None}
    numbers = []
    for v in vals:
        x = float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else parse_number(v)[0]
        if x is not None:
            numbers.append(x)
    texts = [text_of(v) for v in vals]
    distinct: list[str] = []
    seen: set[str] = set()
    for t in texts:
        if t not in seen:
            seen.add(t)
            if len(distinct) < 13:
                distinct.append(t[:40])
    return {
        "filled": n,
        "numeric": round(len(numbers) / n, 3),
        "percent_text": round(sum(1 for t in texts if _PERCENT_TEXT.match(t)) / n, 3),
        "date": round(sum(1 for v, t in zip(vals, texts) if isinstance(v, (datetime, date)) or _DATE_TEXT.match(t))
                      / n, 3),
        "distinct": distinct,
        "distinct_count": len(seen),
        "integers": bool(numbers) and all(float(x).is_integer() for x in numbers),
        "leading_zero": any(isinstance(v, str) and len(v) > 1 and v.startswith("0") and v.isdigit() for v in vals),
        "binary": seen <= BINARY_TOKENS and len(seen) <= 2,
        "max": max(numbers) if numbers else None,
        "min": min(numbers) if numbers else None,
    }


def suggest_mapping(columns: list[Column]) -> dict[str, Any]:
    """Return {suggested: {field: {column, confidence}}, ambiguous: {field: [{column, reason}]}}."""
    by_field: dict[str, list[tuple[Column, str]]] = {}
    notes: dict[str, list[dict[str, str]]] = {}
    for col in columns:
        for cand in dict.fromkeys([norm_header(col.header), norm_header(col.sub)]):
            if not cand:
                continue
            f = _ALIAS_INDEX.get(cand)
            if f:
                by_field.setdefault(f, []).append((col, "exact" if cand == norm_header(f) else "alias"))
                break
            if cand in AMBIGUOUS:
                fields, why = AMBIGUOUS[cand]
                for f2 in fields:
                    notes.setdefault(f2, []).append({"column": col.id, "reason": why})
                break
    suggestions: dict[str, dict[str, str]] = {}
    for f, cands in by_field.items():
        if len(cands) == 1:
            suggestions[f] = {"column": cands[0][0].id, "confidence": cands[0][1]}
        else:
            for col, _ in cands:
                notes.setdefault(f, []).append(
                    {"column": col.id, "reason": "Подходят несколько столбцов с похожими заголовками — выберите один."})
    return {"suggested": suggestions, "ambiguous": notes}


def suggest_wide(columns: list[Column], profiles: dict[str, dict[str, Any]], mapping: dict[str, Any]) -> dict:
    """Wide gradebook proposal: identity columns from aliases, numeric columns as result candidates."""
    identity = {f: s for f, s in mapping["suggested"].items() if f not in WIDE_RESULT_FIELDS}
    used = {s["column"] for s in identity.values()}
    results, totals = [], []
    for col in columns:
        p = profiles.get(col.id) or {}
        if col.id in used or not col.header or not p.get("filled"):
            continue
        if p["numeric"] + p["percent_text"] < 0.6 and not p.get("binary"):
            continue
        entry = {"column": col.id, "topic_name": col.group or col.sub or col.header,
                 "item_hint": col.sub if col.group else ""}
        (totals if _AVERAGE_HEADER.search(norm_header(col.header)) else results).append(entry)
    return {"identity": identity, "result_columns": results, "total_columns": totals}


def suggest_aggregate(columns: list[Column]) -> dict[str, str]:
    roles: dict[str, str] = {}
    taken: set[str] = set()
    for col in columns:
        n = norm_header(col.header)
        for role, (_, aliases) in AGG_ROLES.items():
            if role in taken:
                continue
            if n in aliases or (role == "value" and ("средн" in n or n.endswith("%") or "процент" in n)):
                roles[col.id] = role
                taken.add(role)
                break
    return roles


GENERAL_TYPES = ["number", "date", "category", "text", "identifier", "boolean"]
TYPE_LABEL = {"number": "число", "date": "дата", "category": "категория", "text": "текст",
              "identifier": "идентификатор", "boolean": "да/нет"}


def suggest_type(col: Column, p: dict[str, Any], rows: int) -> str:
    n = norm_header(col.header)
    if not p.get("filled"):
        return "text"
    if _ID_HEADER.search(n) or p.get("leading_zero"):
        return "identifier"
    if p.get("binary") and p["distinct_count"] <= 2 and not (p["numeric"] == 1 and p["distinct_count"] > 2):
        return "boolean"
    if p["date"] >= 0.9:
        return "date"
    if p["numeric"] >= 0.9:
        # Unique integers in every row are more likely row numbers or codes than measurements.
        if p["integers"] and p["distinct_count"] == p["filled"] and p["filled"] >= 20:
            return "identifier"
        return "number"
    if p["distinct_count"] <= max(20, int(0.05 * rows)):
        return "category"
    if p["distinct_count"] == p["filled"] and all(" " not in d for d in p["distinct"]):
        return "identifier"
    return "text"


def suggest_layout(columns: list[Column], mapping: dict[str, Any], wide: dict[str, Any],
                   aggregate: dict[str, str]) -> dict[str, str]:
    s = mapping["suggested"]
    has_student = "student_id" in s or "student_id" in mapping["ambiguous"]
    if has_student and "score" in s and ("topic_id" in s or "topic_name" in s):
        return {"layout": "long", "confidence": "high",
                "reason": "Есть столбцы ученика, темы и балла — одна строка соответствует одному результату."}
    if has_student and "score" not in s and len(wide["result_columns"]) >= 2:
        return {"layout": "wide", "confidence": "medium",
                "reason": f"Есть столбец ученика и {len(wide['result_columns'])} числовых столбцов с результатами — "
                          "похоже на журнал (одна строка — один ученик)."}
    if not has_student and "value" in aggregate.values() and any(r in aggregate.values()
                                                                  for r in ("class", "topic_name", "topic_id")):
        return {"layout": "aggregate", "confidence": "medium",
                "reason": "Нет столбца ученика, есть показатели по классам или темам — похоже на сводную таблицу."}
    if has_student and "score" in s:
        return {"layout": "long", "confidence": "low",
                "reason": "Есть столбцы ученика и балла, но тема не распознана — проверьте сопоставление."}
    return {"layout": "general", "confidence": "low",
            "reason": "Структура не похожа на результаты оценивания — предложен общий просмотр таблицы. Выберите "
                      "другую структуру, если это результаты учеников."}


def layout_notices(rows: list[tuple[int, list[Any]]], flags: dict[int, str], wide: dict[str, Any],
                   mapping: dict[str, Any]) -> list[dict]:
    notices: list[dict[str, Any]] = []
    counts: dict[str, list[int]] = {}
    for r, kind in sorted(flags.items()):
        counts.setdefault(kind, []).append(r)
    if counts.get("repeated_header"):
        rr = counts["repeated_header"]
        notices.append({"code": "REPEATED_HEADER", "severity": "warning", "rows": rr[:20],
                        "message": f"Строки {', '.join(map(str, rr[:5]))} повторяют заголовок — возможно, на листе "
                                   "несколько таблиц. Исключите эти строки или ограничьте диапазон одной таблицей."})
    if counts.get("total"):
        rr = counts["total"]
        notices.append({"code": "TOTAL_ROWS", "severity": "warning", "rows": rr[:20],
                        "message": f"Строки {', '.join(map(str, rr[:5]))} похожи на итоговые (Итого, Среднее…). Они "
                                   "не являются результатами учеников; исключите их явно."})
    if counts.get("note"):
        rr = counts["note"]
        notices.append({"code": "NOTE_ROWS", "severity": "warning", "rows": rr[:20],
                        "message": f"Строки {', '.join(map(str, rr[:5]))} содержат только пояснительный текст."})
    if "score" not in mapping["suggested"] and len(wide["result_columns"]) >= 3:
        notices.append({"code": "WIDE_LAYOUT_SUSPECTED", "severity": "info",
                        "message": "Баллы по разным темам или заданиям записаны в отдельных столбцах. Выберите "
                                   "структуру «Журнал (широкая таблица)», чтобы преобразовать их в записи."})
    if not any(c for _, c in rows):
        notices.append({"code": "NO_DATA_ROWS", "severity": "error",
                        "message": "Под выбранной строкой заголовка нет строк с данными."})
    return notices


def inspect_sheet(sheet: Sheet, sel: Selection | None) -> dict[str, Any]:
    """Preview, columns with samples and profiles, flags and suggestions for one sheet and selection."""
    hdr = suggest_header_row(sheet)
    preview = [{"row": r, "cells": [text_of(v)[:200] for v in cells]} for r, cells in sheet.preview_rows()]
    out: dict[str, Any] = {
        "sheet": sheet.name, "hidden": sheet.hidden, "problem": sheet.problem, "width": sheet.width,
        "header_suggestion": hdr, "preview": preview,
        "header_rows_allowed": [r for r, c in sheet.rows if r <= HEADER_SCAN_ROWS and c],
        "selection": sel.canonical() if sel else None, "header_row": sel.header_row if sel else None,
        "all_columns": [{"index": i, "letter": col_letter(i)} for i in range(sheet.width)],
        "columns": [], "suggestions": {"suggested": {}, "ambiguous": {}}, "notices": [], "duplicate_headers": [],
        "flags": [], "flag_counts": {}, "layout_suggestion": None, "wide_suggestion": None,
        "aggregate_suggestion": {}, "type_suggestion": {}, "data_rows": 0, "last_data_row": None,
    }
    if sheet.problem or sel is None:
        return out
    columns = header_columns(sheet, sel)
    rows = data_rows(sheet, sel)
    flags = row_flags(rows, columns)
    sample_rows = [(r, c) for r, c in rows if c and r not in flags][:PROFILE_ROWS]
    cols_out, profiles = [], {}
    for col in columns:
        values = [cells[col.index] if col.index < len(cells) else None for _, cells in sample_rows]
        p = profile_column(values)
        profiles[col.id] = p
        samples = []
        for v in values:
            t = text_of(v)
            if t and t not in samples:
                samples.append(t[:60])
            if len(samples) >= SAMPLE_VALUES:
                break
        cols_out.append({"id": col.id, "letter": col.letter, "header": col.header, "label": col.label,
                         "group": col.group, "sub": col.sub, "samples": samples, "empty": not p["filled"],
                         "profile": {k: p.get(k) for k in ("numeric", "percent_text", "date", "distinct",
                                                           "distinct_count", "binary", "integers", "min", "max")}})
    mapping = suggest_mapping(columns)
    wide = suggest_wide(columns, profiles, mapping)
    aggregate = suggest_aggregate(columns)
    counts: dict[str, list[str]] = {}
    for col in columns:
        if col.header:
            counts.setdefault(norm_header(col.header), []).append(col.letter)
    non_blank = [r for r, c in rows if any(not _is_empty(x) for x in c)]
    out.update(
        columns=cols_out, suggestions=mapping, wide_suggestion=wide, aggregate_suggestion=aggregate,
        type_suggestion={c.id: suggest_type(c, profiles[c.id], len(rows)) for c in columns},
        layout_suggestion=suggest_layout(columns, mapping, wide, aggregate),
        notices=layout_notices(rows, flags, wide, mapping),
        duplicate_headers=[{"header": next(c.header for c in columns if norm_header(c.header) == k), "letters": v}
                           for k, v in counts.items() if len(v) > 1],
        flags=[{"row": r, "kind": k, "label": FLAG_LABEL[k]} for r, k in sorted(flags.items())][:200],
        flag_counts={k: sum(1 for v in flags.values() if v == k) for k in FLAG_LABEL if k in flags.values()},
        data_rows=len(non_blank), last_data_row=non_blank[-1] if non_blank else None,
        empty_header_columns=[c.letter for c in columns if not c.header],
    )
    return out
