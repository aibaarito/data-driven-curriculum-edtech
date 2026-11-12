"""Guided import, stage 2: explicit layout adapters that turn a selected region into records.

* ``long``      — one row = one student's result (topic/item/assessment). Records go to the existing validator.
* ``wide``      — one row = one student, several result columns. Each non-empty result cell becomes one record,
                  traced to its source row AND column. Per-column metadata (topic, item, maximum…) is explicit.
* ``aggregate`` — one row = a class/topic/textbook group with an average, percentage or count. Stored as an
                  aggregate dataset; never turned into student records.
* ``general``   — any other structured table. Stored as a general dataset for exploration only.

Nothing here writes to the database. Every rejected configuration raises ConfigError with per-field issues; every
data problem becomes an issue with worksheet, original row, source column, a bounded value preview and a suggestion.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from app.services import import_prep as prep
from app.services import import_rules as rules_mod
from app.services.importer import CODE_RE, NAME_LIKE, REQUIRED_COLUMNS, ASSESSMENT_KINDS, _date, parse_number
from app.services.import_prep import FIELD_INFO, Selection, text_of

LAYOUTS = ("long", "wide", "aggregate", "general")
LAYOUT_LABEL = {"long": "Записи (одна строка — один результат)", "wide": "Журнал (широкая таблица)",
                "aggregate": "Сводная таблица (показатели групп)", "general": "Общая таблица"}
MAX_DATASET_ROWS = 50_000
MAX_DATASET_CELLS = 2_000_000
PRIVATE_FIELDS = {"student_id", "school"}
DATE_FIELDS = {"assessment_date"}


class ConfigError(ValueError):
    def __init__(self, issues: list[dict[str, Any]]):
        super().__init__("invalid configuration")
        self.issues = issues


def _issue(code: str, message: str, fld: str | None = None, column: str | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "field": fld, "column": column}


def validate_shared_value(fld: str, value: str) -> str | None:
    """Russian error if a shared value would not pass row validation; None if acceptable."""
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
    elif fld in ("assessment_id", "school", "comparison_group", "topic_id", "item_id"):
        if not CODE_RE.match(v):
            return f"Недопустимый код в поле «{label}» (буквы, цифры, «-», «_», «.»; без пробелов)."
        if NAME_LIKE.match(v):
            return "Похоже на ФИО — используйте код."
    elif fld == "class" and len(v) > 64:
        return "Название класса слишком длинное."
    return None


# --------------------------------------------------------------------------- configuration


@dataclass
class PrepConfig:
    sheet: str
    sel: Selection
    layout: str
    csv: dict[str, str]
    fields: dict[str, dict[str, Any]] = field(default_factory=dict)
    result_columns: list[dict[str, Any]] = field(default_factory=list)
    roles: dict[str, str] = field(default_factory=dict)
    metric: dict[str, Any] = field(default_factory=dict)
    types: dict[str, str] = field(default_factory=dict)
    dataset_name: str = ""
    rules: rules_mod.Rules = field(default_factory=rules_mod.Rules)
    confirm_shared: bool = False

    def canonical(self) -> dict[str, Any]:
        return {"sheet": self.sheet, "selection": self.sel.canonical(), "layout": self.layout, "csv": self.csv,
                "fields": {f: self.fields[f] for f in sorted(self.fields)}, "result_columns": self.result_columns,
                "roles": dict(sorted(self.roles.items())), "metric": self.metric,
                "types": dict(sorted(self.types.items())), "dataset_name": self.dataset_name,
                "rules": self.rules.canonical(), "confirm_shared": self.confirm_shared}


def config_hash(source_sha256: str, cfg: PrepConfig) -> str:
    payload = json.dumps({"source": source_sha256, "config": cfg.canonical()}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def selection_from(raw: dict[str, Any], sheet: prep.Sheet) -> Selection:
    """Validate the region selection against the sheet. Raises ConfigError."""
    header_row = raw.get("header_row")
    allowed = {r for r, c in sheet.rows if r <= prep.HEADER_SCAN_ROWS and c}
    if not isinstance(header_row, int) or isinstance(header_row, bool) or header_row not in allowed:
        raise ConfigError([_issue("INVALID_HEADER_ROW",
                                  f"Строка заголовка должна быть непустой строкой среди первых "
                                  f"{prep.HEADER_SCAN_ROWS}.")])
    header_rows = raw.get("header_rows", 1)
    if header_rows not in (1, 2) or (header_rows == 2 and header_row < 2):
        raise ConfigError([_issue("INVALID_HEADER_ROWS", "Двухстрочный заголовок требует строку групп над "
                                                         "строкой заголовка.")])
    first_col = raw.get("first_col") or 0
    last_col = raw.get("last_col")
    last_row = raw.get("last_row")
    width = max(sheet.width, 1)
    if not isinstance(first_col, int) or isinstance(first_col, bool) or not 0 <= first_col < width:
        raise ConfigError([_issue("INVALID_RANGE", "Первый столбец диапазона вне листа.")])
    if last_col is not None and (not isinstance(last_col, int) or isinstance(last_col, bool)
                                 or not first_col <= last_col < width):
        raise ConfigError([_issue("INVALID_RANGE", "Последний столбец диапазона должен быть не левее первого.")])
    if last_row is not None and (not isinstance(last_row, int) or isinstance(last_row, bool) or last_row <= header_row):
        raise ConfigError([_issue("INVALID_RANGE", "Последняя строка данных должна быть ниже заголовка.")])
    exclude = raw.get("exclude") or []
    if not isinstance(exclude, list) or not set(exclude) <= set(prep.FLAG_LABEL):
        raise ConfigError([_issue("INVALID_EXCLUSION", "Неизвестный вид исключаемых строк.")])
    return Selection(header_row, header_rows, first_col, last_col, last_row, frozenset(exclude))


def _check_fields(fields_raw: Any, columns: dict[str, prep.Column], allowed_fields: list[str],
                  issues: list[dict[str, Any]], used: dict[str, str]) -> dict[str, dict[str, Any]]:
    if not isinstance(fields_raw, dict):
        issues.append(_issue("INVALID_MAPPING", "Сопоставление столбцов не передано."))
        return {}
    fields: dict[str, dict[str, Any]] = {}
    for fld, spec in fields_raw.items():
        if fld not in prep.ALL_FIELDS:
            issues.append(_issue("UNKNOWN_FIELD", "Неизвестное поле приложения.", fld))
            continue
        label = FIELD_INFO[fld][0]
        if fld not in allowed_fields:
            issues.append(_issue("FIELD_NOT_ALLOWED", f"Поле «{label}» для этой структуры задаётся иначе "
                                                      "(для столбцов результатов).", fld))
            continue
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
                issues.append(_issue("COLUMN_REUSED", f"Столбец «{columns[cid].label}» уже выбран для "
                                                      f"«{used[cid]}». Один столбец — одно поле.", fld, cid))
                continue
            used[cid] = label
            fields[fld] = {"source": "column", "column": cid}
        elif src == "value":
            if fld not in prep.SHARED_ELIGIBLE:
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
            if fld not in prep.NONE_ALLOWED:
                issues.append(_issue("MISSING_MAPPING", f"Выберите столбец для поля «{label}».", fld))
                continue
            fields[fld] = {"source": "none"}
    return fields


def _require(fields: dict[str, Any], required: list[str], issues: list[dict[str, Any]],
             covered: set[str] = frozenset()) -> None:
    for fld in required:
        if fld in fields or fld in covered or any(i["field"] == fld for i in issues):
            continue
        hint = " или задайте одно значение для всего файла" if fld in prep.SHARED_ELIGIBLE else ""
        if fld == "textbook_id":
            hint = " или отметьте, что учебника в файле нет"
        issues.append(_issue("MISSING_MAPPING", f"Выберите источник для поля «{FIELD_INFO[fld][0]}»{hint}.", fld))


def check_config(raw: dict[str, Any], wb: prep.Workbook) -> PrepConfig:
    """Validate a configuration submitted by the client against the stored source. Raises ConfigError."""
    sheet = wb.get(raw.get("sheet")) if isinstance(raw.get("sheet"), str) else None
    if sheet is None:
        raise ConfigError([_issue("UNKNOWN_SHEET", "Выбранный лист не найден в файле.")])
    if sheet.problem:
        raise ConfigError([_issue("UNSUPPORTED_SHEET", sheet.problem)])
    sel = selection_from(raw, sheet)
    layout = raw.get("layout", "long")
    if layout not in LAYOUTS:
        raise ConfigError([_issue("INVALID_LAYOUT", "Неизвестная структура таблицы.")])
    try:
        rules = rules_mod.parse_rules(raw.get("rules"))
    except rules_mod.RuleError as exc:
        raise ConfigError([_issue("INVALID_RULES", str(exc))]) from exc
    columns = {c.id: c for c in prep.header_columns(sheet, sel)}
    if not columns:
        raise ConfigError([_issue("NO_COLUMNS", "В выбранном диапазоне нет столбцов.")])
    csv_opts = raw.get("csv") or {}
    cfg = PrepConfig(sheet.name, sel, layout, {"encoding": csv_opts.get("encoding", "auto"),
                                                "delimiter": csv_opts.get("delimiter", "auto")} if wb.kind == "csv"
                     else {}, rules=rules, confirm_shared=raw.get("confirm_shared") is True)
    issues: list[dict[str, Any]] = []
    used: dict[str, str] = {}
    if layout == "long":
        cfg.fields = _check_fields(raw.get("fields"), columns, prep.ALL_FIELDS, issues, used)
        required = list(REQUIRED_COLUMNS)
        if rules.score_mode != "points":
            required.remove("max_score")
            if "max_score" in cfg.fields:
                issues.append(_issue("MAX_NOT_USED", "При выбранном способе записи результата максимальный балл "
                                                     "задаётся правилом; уберите сопоставление.", "max_score"))
        _require(cfg.fields, required, issues)
    elif layout == "wide":
        identity_fields = [f for f in prep.ALL_FIELDS if f not in prep.WIDE_RESULT_FIELDS]
        cfg.fields = _check_fields(raw.get("fields"), columns, identity_fields, issues, used)
        cfg.result_columns = _check_result_columns(raw.get("result_columns"), columns, cfg, issues, used)
        covered = {f for f in ("assessment_id", "assessment_type", "assessment_date")
                   if cfg.result_columns and all(rc.get(f) for rc in cfg.result_columns)}
        _require(cfg.fields, [f for f in REQUIRED_COLUMNS if f not in prep.WIDE_RESULT_FIELDS], issues, covered)
    elif layout == "aggregate":
        _check_aggregate(raw, columns, cfg, issues)
    else:
        _check_general(raw, columns, sheet, cfg, issues)
    if any(s["source"] == "value" for s in cfg.fields.values()) and not cfg.confirm_shared:
        issues.append(_issue("SHARED_NOT_CONFIRMED",
                             "Подтвердите, что заданные вручную значения относятся ко всем строкам файла."))
    if issues:
        raise ConfigError(issues)
    return cfg


def _check_result_columns(raw: Any, columns: dict[str, prep.Column], cfg: PrepConfig,
                          issues: list[dict[str, Any]], used: dict[str, str]) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        issues.append(_issue("NO_RESULT_COLUMNS", "Выберите хотя бы один столбец с результатами."))
        return []
    if len(raw) > prep.MAX_COLUMNS:
        issues.append(_issue("TOO_MANY_RESULT_COLUMNS", "Слишком много столбцов результатов."))
        return []
    out = []
    for rc in raw:
        cid = rc.get("column") if isinstance(rc, dict) else None
        if not isinstance(cid, str) or cid not in columns:
            issues.append(_issue("UNKNOWN_COLUMN", "Выбран несуществующий столбец результатов."))
            continue
        col = columns[cid]
        if cid in used:
            issues.append(_issue("COLUMN_REUSED", f"Столбец «{col.label}» уже выбран для «{used[cid]}».", None, cid))
            continue
        used[cid] = "результаты"
        spec: dict[str, Any] = {"column": cid}
        for fld in prep.WIDE_PER_COLUMN:
            v = rc.get(fld)
            if v is None or (isinstance(v, str) and not v.strip()):
                continue
            if not isinstance(v, str):
                v = str(v)
            v = v.strip()
            if fld == "max_score":
                if cfg.rules.score_mode != "points":
                    issues.append(_issue("MAX_NOT_USED", f"Столбец {col.letter}: максимум задаётся правилом "
                                                         "записи результата — уберите его.", fld, cid))
                    continue
                x, err = rules_mod.parse_num(v, cfg.rules.decimal)
                if err or x is None or x <= 0:
                    issues.append(_issue("INVALID_MAX", f"Столбец {col.letter}: максимальный балл должен быть "
                                                        "числом больше нуля.", fld, cid))
                    continue
                spec[fld] = v
                continue
            if fld == "topic_name":
                if len(v) > 255:
                    issues.append(_issue("INVALID_TOPIC", f"Столбец {col.letter}: слишком длинное название.", fld,
                                         cid))
                    continue
                spec[fld] = v
                continue
            msg = validate_shared_value(fld, v)
            if msg:
                issues.append(_issue("INVALID_COLUMN_VALUE", f"Столбец {col.letter}: {msg}", fld, cid))
                continue
            spec[fld] = v
        for req in ("topic_id", "topic_name") + (("max_score",) if cfg.rules.score_mode == "points" else ()):
            if req not in spec and not any(i["column"] == cid and i["field"] == req for i in issues):
                issues.append(_issue("MISSING_COLUMN_META", f"Столбец {col.letter} «{col.label}»: укажите "
                                                            f"«{FIELD_INFO[req][0]}».", req, cid))
        for fld in ("assessment_id", "assessment_type", "assessment_date"):
            # A per-column value may not silently override a row column or shared value of the same field.
            if fld in spec and fld in cfg.fields:
                issues.append(_issue("CONFLICTING_SOURCES", f"Столбец {col.letter}: «{FIELD_INFO[fld][0]}» уже "
                                                            "задано для всех строк — уберите одно из значений.",
                                     fld, cid))
        out.append(spec)
    return out


def _check_aggregate(raw: dict[str, Any], columns: dict[str, prep.Column], cfg: PrepConfig,
                     issues: list[dict[str, Any]]) -> None:
    roles = raw.get("roles") or {}
    if not isinstance(roles, dict):
        issues.append(_issue("INVALID_ROLES", "Роли столбцов не переданы."))
        return
    seen: dict[str, str] = {}
    for cid, role in roles.items():
        if cid not in columns:
            issues.append(_issue("UNKNOWN_COLUMN", "Выбран несуществующий столбец.", None, cid))
            continue
        if role not in prep.AGG_ROLES:
            issues.append(_issue("UNKNOWN_ROLE", "Неизвестная роль столбца.", None, cid))
            continue
        if role in seen:
            issues.append(_issue("ROLE_REUSED", f"Роль «{prep.AGG_ROLES[role][0]}» уже назначена столбцу "
                                                f"{columns[seen[role]].letter}.", None, cid))
            continue
        seen[role] = cid
    cfg.roles = {cid: r for r, cid in seen.items()}
    if "value" not in seen:
        issues.append(_issue("MISSING_ROLE", "Выберите столбец с показателем (средний балл, процент и т. п.)."))
    if not ({"class", "topic_name", "topic_id", "textbook", "grade"} & set(seen)):
        issues.append(_issue("MISSING_ROLE", "Выберите хотя бы один столбец группы: класс, тему, параллель или "
                                             "учебник."))
    metric = raw.get("metric") or {}
    kind = metric.get("kind")
    if kind not in ("percent", "mean_points"):
        issues.append(_issue("MISSING_METRIC", "Укажите, что означает показатель: процент (0–100) или средний "
                                               "балл с известным максимумом."))
    cfg.metric = {"kind": kind}
    if kind == "percent":
        cfg.metric["percent_scale"] = metric.get("percent_scale", "0-100")
        if cfg.metric["percent_scale"] not in ("0-100", "0-1"):
            issues.append(_issue("INVALID_METRIC", "Неизвестная шкала процентов."))
    if kind == "mean_points" and "max" not in seen:
        mx = metric.get("max_value")
        x, err = rules_mod.parse_num(str(mx), cfg.rules.decimal) if mx not in (None, "") else (None, "missing")
        if err or x is None or x <= 0:
            issues.append(_issue("MISSING_MAX", "Для среднего балла укажите столбец максимума или максимальный балл "
                                                "(он не определяется по данным)."))
        else:
            cfg.metric["max_value"] = str(mx).strip()
    if kind == "percent" and "max" in seen:
        issues.append(_issue("MAX_NOT_USED", "Для процентов столбец максимума не нужен — снимите роль."))
    cfg.dataset_name = _dataset_name(raw)


def _dataset_name(raw: dict[str, Any]) -> str:
    name = raw.get("dataset_name")
    return name.strip()[:120] if isinstance(name, str) and name.strip() else ""


def _check_general(raw: dict[str, Any], columns: dict[str, prep.Column], sheet: prep.Sheet, cfg: PrepConfig,
                   issues: list[dict[str, Any]]) -> None:
    types = raw.get("types") or {}
    if not isinstance(types, dict):
        issues.append(_issue("INVALID_TYPES", "Типы столбцов переданы неверно."))
        return
    for cid, t in types.items():
        if cid not in columns:
            issues.append(_issue("UNKNOWN_COLUMN", "Выбран несуществующий столбец.", None, cid))
        elif t not in prep.GENERAL_TYPES:
            issues.append(_issue("UNKNOWN_TYPE", "Неизвестный тип столбца.", None, cid))
    if issues:
        return
    rows = [(r, c) for r, c in prep.data_rows(sheet, cfg.sel) if c][:prep.PROFILE_ROWS]
    resolved = {}
    for cid, col in columns.items():
        if cid in types:
            resolved[cid] = types[cid]
        else:
            p = prep.profile_column([cells[col.index] if col.index < len(cells) else None for _, cells in rows])
            resolved[cid] = prep.suggest_type(col, p, len(rows))
    cfg.types = resolved
    cfg.dataset_name = _dataset_name(raw)


# --------------------------------------------------------------------------- preparation


SUGGESTIONS = {
    "MISSING_VALUE": "Заполните ячейку в файле или выберите другой столбец для этого поля.",
    "INVALID_IDENTIFIER": "Используйте код из букв, цифр, «-», «_», «.» без пробелов.",
    "POSSIBLE_PERSONAL_DATA": "Замените ФИО анонимным кодом ученика.",
    "INVALID_NUMBER": "Проверьте запись числа или правило десятичного разделителя.",
    "AMBIGUOUS_NUMBER": "Укажите десятичный разделитель в правилах разбора.",
    "NEGATIVE_SCORE": "Исправьте балл в файле.",
    "NON_POSITIVE_MAX": "Максимальный балл должен быть больше нуля.",
    "SCORE_EXCEEDS_MAX": "Проверьте балл и максимальный балл (или шкалу результата).",
    "INVALID_DATE": "Исправьте дату или выберите формат даты в правилах разбора.",
    "INVALID_GRADE": "Параллель — целое число 1–12. Если в столбце «7А», выберите его для поля «Класс».",
    "INVALID_ASSESSMENT_TYPE": "Используйте pre, post или current либо задайте тип одним значением.",
    "DUPLICATE_ROW": "Удалите повторяющуюся строку или проверьте коды задания и темы.",
    "MIXED_GRANULARITY": "Не выбирайте одновременно столбец итога и столбцы заданий одной темы.",
    "CONFLICT": "Исправьте противоречие между строками в файле.",
    "CONFLICT_WITH_DB": "Файл противоречит уже загруженным данным; исправления не выполняются автоматически.",
    "FORMULA_WITHOUT_VALUE": "Откройте файл в Excel, пересчитайте и сохраните — формулы не вычисляются.",
    "REPEATED_HEADER": "Исключите повторы заголовка на шаге «Данные» или ограничьте диапазон.",
    "FLAGGED_ROW": "Исключите строки этого вида на шаге «Данные», если это не результаты.",
}
SUGGESTIONS.update({k: v[1] for k, v in rules_mod.RULE_MESSAGES.items()})


@dataclass
class Prepared:
    kind: str  # "assessment" | "dataset"
    frame: pd.DataFrame | None = None
    row_numbers: list[int] = field(default_factory=list)
    source_columns: list[str | None] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    ignored_columns: list[str] = field(default_factory=list)
    counts: dict[str, Any] = field(default_factory=dict)
    dataset: dict[str, Any] | None = None
    field_columns: dict[str, str] = field(default_factory=dict)  # field -> source column letter


def _err(row: int | None, col: str | None, code: str, message: str | None = None, fld: str | None = None,
         value: Any = None, stage: str = "transform") -> dict[str, Any]:
    msg = message or rules_mod.RULE_MESSAGES.get(code, ("Ошибка в данных.",))[0]
    return {"row": row, "column": fld, "code": code, "message": msg, "source_column": col,
            "value": preview_value(value, fld), "stage": stage}


def preview_value(v: Any, fld: str | None = None) -> str | None:
    """Bounded preview of a cell. Identifiers and name-like values are never echoed."""
    if v is None:
        return None
    if fld in PRIVATE_FIELDS:
        return "(скрыто)"
    t = text_of(v)
    if not t:
        return "(пусто)"
    if NAME_LIKE.match(t):
        return "(скрыто: похоже на ФИО)"
    return t[:40] + ("…" if len(t) > 40 else "")


def _selected_rows(sheet: prep.Sheet, cfg: PrepConfig, columns: list[prep.Column]
                   ) -> tuple[list[tuple[int, list[Any]]], dict[str, Any], dict[int, str]]:
    rows = prep.data_rows(sheet, cfg.sel)
    flags = prep.row_flags(rows, columns)
    kept, excluded = [], {k: [] for k in prep.FLAG_LABEL}
    for r, cells in rows:
        kind = flags.get(r)
        if kind and kind in cfg.sel.exclude:
            excluded[kind].append(r)
            continue
        kept.append((r, cells))
    source_rows = sum(1 for _, c in rows if any(not prep._is_empty(x) for x in c))
    counts = {"source_rows": source_rows,
              "excluded_rows": sum(len(v) for v in excluded.values()),
              "excluded_by_kind": {k: len(v) for k, v in excluded.items() if v},
              "excluded_row_numbers": sorted(r for v in excluded.values() for r in v)[:200],
              "outside_range_last_row": cfg.sel.last_row}
    return kept, counts, {r: k for r, k in flags.items() if k not in cfg.sel.exclude}


def _cell(cells: list[Any], idx: int) -> Any:
    return cells[idx] if idx < len(cells) else None


def _formula_errors(sheet: prep.Sheet, cols: dict[str, prep.Column], used: dict[str, str], header_row: int
                    ) -> list[dict[str, Any]]:
    errors = []
    for cid, fld in used.items():
        col = cols[cid]
        hit = sorted(r for r, c in sheet.formula_cells if c == col.index and r > header_row)
        if hit:
            errors.append(_err(hit[0], col.letter, "FORMULA_WITHOUT_VALUE",
                               f"Столбец «{col.label}»: {len(hit)} ячеек с формулой без сохранённого значения "
                               f"(первая — строка {hit[0]}). Формулы при импорте не вычисляются.", fld,
                               stage="structure"))
    return errors


def prepare(sheet: prep.Sheet, cfg: PrepConfig, max_records: int) -> Prepared:
    if cfg.layout == "long":
        return _prepare_long(sheet, cfg)
    if cfg.layout == "wide":
        return _prepare_wide(sheet, cfg, max_records)
    if cfg.layout == "aggregate":
        return _prepare_aggregate(sheet, cfg)
    return _prepare_general(sheet, cfg)


def _flag_warnings(flags_kept: dict[int, str], rows_used: set[int]) -> list[dict[str, Any]]:
    out = []
    for kind in prep.FLAG_LABEL:
        rr = sorted(r for r, k in flags_kept.items() if k == kind and r in rows_used)
        if rr:
            out.append({"row": rr[0], "column": None, "code": "FLAGGED_ROW", "stage": "structure",
                        "message": f"{len(rr)} строк вида «{prep.FLAG_LABEL[kind]}» оставлены в данных (например, "
                                   f"строки {', '.join(map(str, rr[:5]))}).",
                        "suggestion": SUGGESTIONS["FLAGGED_ROW"]})
    return out


def _apply_record_rules(rec: dict[str, Any], raw_score: Any, raw_max: Any, cfg: PrepConfig, row: int,
                        letters: dict[str, str | None]) -> dict[str, Any] | None:
    """Apply confirmed rules to one record in place. Returns an error dict or None. Default rules change nothing."""
    r = cfg.rules
    if not r.is_default:
        if r.score_mode == "points" and r.decimal == "auto":
            pass  # the validator applies the default number rules itself (same codes as before)
        else:
            s, mx, code = rules_mod.interpret_score(raw_score, raw_max, r)
            if code:
                fld = "max_score" if code in ("MISSING_MAX_SCORE", "INVALID_MAX_SCORE") else "score"
                return _err(row, letters.get(fld), code, fld=fld, value=raw_max if fld == "max_score" else raw_score)
            rec["score"], rec["max_score"] = s, mx
        if r.decimal != "auto" and rec.get("teaching_hours") not in (None, ""):
            h, code = rules_mod.parse_num(rec["teaching_hours"], r.decimal)
            if code:
                return _err(row, letters.get("teaching_hours"), code, fld="teaching_hours",
                            value=rec["teaching_hours"])
            rec["teaching_hours"] = h
    d = rec.get("assessment_date")
    if d not in (None, "") and not (isinstance(d, str) and not d.strip()):
        iso, code = rules_mod.parse_date_rule(d, r.date_format)
        if code == "DATE_FORMAT_REQUIRED" or (code and r.date_format != "auto"):
            return _err(row, letters.get("assessment_date"), code, fld="assessment_date", value=d)
        if iso:
            rec["assessment_date"] = iso
    return None


def _prepare_long(sheet: prep.Sheet, cfg: PrepConfig) -> Prepared:
    cols = {c.id: c for c in prep.header_columns(sheet, cfg.sel)}
    rows, counts, flags_kept = _selected_rows(sheet, cfg, list(cols.values()))
    out = Prepared("assessment")
    mapped = {f: cols[s["column"]] for f, s in cfg.fields.items() if s["source"] == "column"}
    out.field_columns = {f: c.letter for f, c in mapped.items()}
    letters = dict(out.field_columns)
    has_mapped = [any(not prep._is_empty(_cell(cells, c.index)) for c in mapped.values()) for _, cells in rows]
    records, row_numbers, missing = [], [], 0
    for i, (r, cells) in enumerate(rows):
        rec: dict[str, Any] = {}
        for fld, spec in cfg.fields.items():
            if spec["source"] == "column":
                rec[fld] = _cell(cells, mapped[fld].index)
            elif spec["source"] == "value":
                rec[fld] = spec["value"] if has_mapped[i] else None
            else:
                rec[fld] = None
        if has_mapped[i]:
            raw_score = rec.get("score")
            if rules_mod.is_missing(raw_score, cfg.rules):
                missing += 1
                continue
            e = _apply_record_rules(rec, raw_score, rec.get("max_score"), cfg, r, letters)
            if e:
                out.errors.append(e)
                continue
        records.append(rec)
        row_numbers.append(r)
    # Score rules other than "points" set max_score per record, so the column exists even when it is not mapped.
    names = list(dict.fromkeys(list(cfg.fields) + ["score", "max_score"]))
    out.frame = pd.DataFrame(records, columns=names, dtype=object) if records else \
        pd.DataFrame(columns=names, dtype=object)
    out.row_numbers = row_numbers
    out.source_columns = [None] * len(records)
    used = {s["column"]: f for f, s in cfg.fields.items() if s["source"] == "column"}
    out.errors.extend(_formula_errors(sheet, cols, used, cfg.sel.header_row))
    only_ignored = [r for i, (r, cells) in enumerate(rows) if cells and not has_mapped[i]
                    and any(not prep._is_empty(x) for x in cells)]
    if only_ignored:
        out.warnings.append({"row": None, "column": None, "code": "ROWS_WITHOUT_MAPPED_DATA", "stage": "structure",
                             "message": f"{len(only_ignored)} строк содержат данные только в неиспользуемых столбцах и "
                                        "не будут импортированы (например, строки "
                                        f"{', '.join(map(str, only_ignored[:5]))}).",
                             "suggestion": "Проверьте, не пропущено ли сопоставление."})
    if missing:
        out.warnings.append({"row": None, "column": "score", "code": "MISSING_RESULTS", "stage": "transform",
                             "message": f"{missing} строк содержат отметку отсутствия результата: записи не "
                                        "создаются, нулём они не считаются."})
    out.warnings.extend(_flag_warnings(flags_kept, set(row_numbers)))
    out.ignored_columns = [c.label for cid, c in cols.items() if cid not in used and c.header]
    counts.update(missing_results=missing, transform_errors=len([e for e in out.errors if e["stage"] == "transform"]))
    out.counts = counts
    return out


def _prepare_wide(sheet: prep.Sheet, cfg: PrepConfig, max_records: int) -> Prepared:
    cols = {c.id: c for c in prep.header_columns(sheet, cfg.sel)}
    rows, counts, flags_kept = _selected_rows(sheet, cfg, list(cols.values()))
    out = Prepared("assessment")
    mapped = {f: cols[s["column"]] for f, s in cfg.fields.items() if s["source"] == "column"}
    out.field_columns = {f: c.letter for f, c in mapped.items()}
    result_cols = [(rc, cols[rc["column"]]) for rc in cfg.result_columns]
    non_blank = [(r, c) for r, c in rows if any(not prep._is_empty(x) for x in c)]
    if len(non_blank) * len(result_cols) > max_records:
        raise ConfigError([_issue("TOO_MANY_RECORDS",
                                  f"Преобразование даст до {len(non_blank) * len(result_cols)} записей — больше лимита "
                                  f"{max_records}. Выберите меньше столбцов результатов или разделите файл.")])
    records, row_numbers, src_cols = [], [], []
    empty_cells = missing = 0
    rows_without_results = []
    for r, cells in non_blank:
        identity: dict[str, Any] = {}
        for fld, spec in cfg.fields.items():
            if spec["source"] == "column":
                identity[fld] = _cell(cells, mapped[fld].index)
            elif spec["source"] == "value":
                identity[fld] = spec["value"]
            else:
                identity[fld] = None
        produced = 0
        for rc, col in result_cols:
            raw = _cell(cells, col.index)
            if prep._is_empty(raw):
                empty_cells += 1
                continue
            if rules_mod.is_missing(raw, cfg.rules):
                missing += 1
                continue
            rec = dict(identity)
            for fld in ("topic_id", "topic_name", "item_id", "assessment_id", "assessment_type", "assessment_date"):
                if rc.get(fld):
                    rec[fld] = rc[fld]
            rec.setdefault("item_id", None)
            letters = dict(out.field_columns) | {"score": col.letter, "max_score": col.letter}
            if cfg.rules.score_mode == "points":
                s, e = rules_mod.parse_num(raw, cfg.rules.decimal)
                if e:
                    out.errors.append(_err(r, col.letter, e, fld="score", value=raw))
                    continue
                mx, _ = rules_mod.parse_num(rc["max_score"], cfg.rules.decimal)
                rec["score"], rec["max_score"] = s, mx
                e2 = _apply_record_rules(rec, None, None, _date_only(cfg), r, letters)
            else:
                rec["score"], rec["max_score"] = raw, None
                e2 = _apply_record_rules(rec, raw, None, cfg, r, letters)
            if e2:
                out.errors.append(e2)
                continue
            records.append(rec)
            row_numbers.append(r)
            src_cols.append(col.letter)
            produced += 1
        if not produced:
            rows_without_results.append(r)
    names = sorted({k for rec in records for k in rec} | set(cfg.fields) | set(prep.WIDE_RESULT_FIELDS))
    out.frame = pd.DataFrame(records, columns=names, dtype=object) if records else pd.DataFrame(columns=names,
                                                                                               dtype=object)
    out.row_numbers, out.source_columns = row_numbers, src_cols
    used = {s["column"]: f for f, s in cfg.fields.items() if s["source"] == "column"}
    used.update({rc["column"]: "score" for rc in cfg.result_columns})
    out.errors.extend(_formula_errors(sheet, cols, used, cfg.sel.header_row))
    if missing:
        out.warnings.append({"row": None, "column": "score", "code": "MISSING_RESULTS", "stage": "transform",
                             "message": f"{missing} ячеек содержат отметку отсутствия результата: записи не создаются, "
                                        "нулём они не считаются."})
    if rows_without_results:
        out.warnings.append({"row": rows_without_results[0], "column": None, "code": "ROWS_WITHOUT_RESULTS",
                             "stage": "transform",
                             "message": f"{len(rows_without_results)} строк без единого результата в выбранных "
                                        "столбцах — записи не созданы (например, строки "
                                        f"{', '.join(map(str, rows_without_results[:5]))})."})
    out.warnings.extend(_flag_warnings(flags_kept, set(row_numbers)))
    out.ignored_columns = [c.label for cid, c in cols.items() if cid not in used and c.header]
    counts.update(missing_results=missing, empty_result_cells=empty_cells, result_columns=len(result_cols),
                  transform_errors=len([e for e in out.errors if e["stage"] == "transform"]),
                  wide_explanation=(f"Каждая непустая ячейка из {len(result_cols)} столбцов результатов становится "
                                    f"отдельной записью, поэтому записей может быть больше, чем строк "
                                    f"({len(non_blank)} строк × {len(result_cols)} столбцов; пустых ячеек: "
                                    f"{empty_cells}, отметок отсутствия: {missing})."))
    out.counts = counts
    return out


def _date_only(cfg: PrepConfig) -> PrepConfig:
    """Rules with default score handling (score already parsed) but the user's date format."""
    clone = PrepConfig(cfg.sheet, cfg.sel, cfg.layout, cfg.csv)
    clone.rules = rules_mod.Rules(date_format=cfg.rules.date_format)
    return clone


def _prepare_aggregate(sheet: prep.Sheet, cfg: PrepConfig) -> Prepared:
    cols = {c.id: c for c in prep.header_columns(sheet, cfg.sel)}
    rows, counts, flags_kept = _selected_rows(sheet, cfg, list(cols.values()))
    out = Prepared("dataset")
    by_role = {role: cols[cid] for cid, role in cfg.roles.items()}
    columns_meta = [{"id": c.id, "letter": c.letter, "label": c.label, "role": cfg.roles.get(c.id)}
                    for c in cols.values()]
    kind = cfg.metric["kind"]
    shared_max = None
    if kind == "mean_points" and "max" not in by_role:
        shared_max, _ = rules_mod.parse_num(cfg.metric["max_value"], cfg.rules.decimal)
    data_rows, seen_keys = [], {}
    for r, cells in rows:
        if not any(not prep._is_empty(x) for x in cells):
            continue
        rec: dict[str, Any] = {g: text_of(_cell(cells, by_role[g].index)) or None
                               for g in prep.AGG_GROUP_ROLES if g in by_role}
        vcol = by_role["value"]
        raw = _cell(cells, vcol.index)
        if prep._is_empty(raw) or rules_mod.is_missing(raw, cfg.rules):
            out.errors.append(_err(r, vcol.letter, "AGG_MISSING_VALUE", "Нет значения показателя.", "value", raw,
                                   "record"))
            continue
        if kind == "percent":
            text = raw.strip()[:-1] if isinstance(raw, str) and raw.strip().endswith("%") else raw
            x, e = rules_mod.parse_num(text, cfg.rules.decimal)
            if not e and cfg.metric.get("percent_scale") == "0-1" and not (isinstance(raw, str) and "%" in raw):
                x = x * 100
            if e or x is None or not 0 <= x <= 100:
                out.errors.append(_err(r, vcol.letter, e or "PERCENT_OUT_OF_RANGE", fld="value", value=raw,
                                       stage="record"))
                continue
            rec.update(value=x, max=None, pct=round(x, 4))
        else:
            x, e = rules_mod.parse_num(raw, cfg.rules.decimal)
            mx = shared_max
            if "max" in by_role:
                mraw = _cell(cells, by_role["max"].index)
                mx, e2 = rules_mod.parse_num(mraw, cfg.rules.decimal) if not prep._is_empty(mraw) else (None, "M")
                if e2 or mx is None or mx <= 0:
                    out.errors.append(_err(r, by_role["max"].letter, "INVALID_MAX_SCORE",
                                           "Максимум не указан или не является числом больше нуля.", "max", mraw,
                                           "record"))
                    continue
            if e or x is None or x < 0 or x > mx:
                out.errors.append(_err(r, vcol.letter, e or "VALUE_OUT_OF_RANGE",
                                       f"Средний балл должен быть числом от 0 до {mx:g}.", "value", raw, "record"))
                continue
            rec.update(value=x, max=mx, pct=round(x / mx * 100, 4))
        if "count" in by_role:
            craw = _cell(cells, by_role["count"].index)
            if not prep._is_empty(craw):
                n, e = rules_mod.parse_num(craw, cfg.rules.decimal)
                if e or n is None or n < 0 or n != int(n):
                    out.errors.append(_err(r, by_role["count"].letter, "INVALID_COUNT",
                                           "Число учеников должно быть целым неотрицательным.", "count", craw,
                                           "record"))
                    continue
                rec["n"] = int(n)
        if not any(rec.get(g) for g in ("class", "topic_name", "topic_id", "textbook", "grade")):
            out.errors.append(_err(r, None, "AGG_NO_GROUP", "В строке не указана группа (класс, тема, параллель или "
                                                             "учебник).", stage="record"))
            continue
        key = tuple(rec.get(g) for g in prep.AGG_GROUP_ROLES)
        if key in seen_keys:
            out.warnings.append({"row": r, "column": None, "code": "DUPLICATE_GROUP", "stage": "record",
                                 "message": f"Та же группа, что в строке {seen_keys[key]}: обе строки сохраняются; "
                                            "проверьте, не задвоены ли данные."})
        else:
            seen_keys[key] = r
        data_rows.append({"source_row": r, "values": [text_of(_cell(cells, c.index)) for c in cols.values()],
                          "data": rec})
    out.dataset = {"kind": "aggregate", "columns": columns_meta, "rows": data_rows,
                   "metric": cfg.metric, "name": cfg.dataset_name}
    out.warnings.extend(_flag_warnings(flags_kept, {d["source_row"] for d in data_rows}))
    out.warnings.append({"row": None, "column": None, "code": "AGGREGATE_DATA", "stage": "structure",
                         "message": "Это агрегированные данные: каждая строка — показатель группы, а не ученика. "
                                    "Распределения по ученикам, парный прирост и доверительные интервалы по ним не "
                                    "рассчитываются."})
    counts.update(records=len(data_rows) + len(out.errors))
    out.counts = counts
    out.ignored_columns = [c.label for cid, c in cols.items() if cid not in cfg.roles and c.header]
    return out


def _prepare_general(sheet: prep.Sheet, cfg: PrepConfig) -> Prepared:
    cols = list(prep.header_columns(sheet, cfg.sel))
    rows, counts, flags_kept = _selected_rows(sheet, cfg, cols)
    out = Prepared("dataset")
    data_rows = [{"source_row": r, "values": [text_of(_cell(cells, c.index)) for c in cols]}
                 for r, cells in rows if any(not prep._is_empty(x) for x in cells)]
    if len(data_rows) > MAX_DATASET_ROWS or len(data_rows) * len(cols) > MAX_DATASET_CELLS:
        raise ConfigError([_issue("DATASET_TOO_LARGE", f"Общая таблица ограничена {MAX_DATASET_ROWS} строками и "
                                                       f"{MAX_DATASET_CELLS} ячейками. Ограничьте диапазон.")])
    from app.services.datasets import type_matches  # local import: datasets depends on this module's output only

    for i, c in enumerate(cols):
        t = cfg.types.get(c.id, "text")
        bad = [d["source_row"] for d in data_rows if d["values"][i] and not type_matches(d["values"][i], t)]
        if bad:
            out.warnings.append({"row": bad[0], "column": None, "source_column": c.letter, "code": "TYPE_MISMATCH",
                                 "stage": "record",
                                 "message": f"Столбец «{c.label}»: {len(bad)} значений не соответствуют типу "
                                            f"«{prep.TYPE_LABEL[t]}» (первое — строка {bad[0]}). Они сохраняются как "
                                            "текст и не участвуют в расчётах этого типа.",
                                 "suggestion": "Проверьте тип столбца."})
    out.dataset = {"kind": "general", "name": cfg.dataset_name, "rows": data_rows,
                   "columns": [{"id": c.id, "letter": c.letter, "label": c.label, "type": cfg.types.get(c.id, "text")}
                               for c in cols]}
    out.warnings.extend(_flag_warnings(flags_kept, {d["source_row"] for d in data_rows}))
    counts.update(records=len(data_rows))
    out.counts = counts
    return out


# --------------------------------------------------------------------------- summary


def config_summary(sheet: prep.Sheet, cfg: PrepConfig, prepared: Prepared, kind: str) -> dict[str, Any]:
    cols = {c.id: c for c in prep.header_columns(sheet, cfg.sel)}
    mapped, shared, absent = [], [], []
    for fld in prep.ALL_FIELDS:
        spec = cfg.fields.get(fld)
        if spec is None:
            continue
        label = FIELD_INFO[fld][0]
        if spec["source"] == "column":
            c = cols[spec["column"]]
            mapped.append({"field": fld, "label": label, "column": c.id, "letter": c.letter, "header": c.label})
        elif spec["source"] == "value":
            shared.append({"field": fld, "label": label, "value": spec["value"]})
        else:
            absent.append({"field": fld, "label": label})
    sel = cfg.sel
    return {
        "sheet": sheet.name, "sheet_hidden": sheet.hidden, "header_row": sel.header_row, "header_rows": sel.header_rows,
        "range": {"first_col": prep.col_letter(sel.first_col),
                  "last_col": prep.col_letter(sel.last_col) if sel.last_col is not None else None,
                  "last_row": sel.last_row},
        "excluded_kinds": [label for k, label in prep.FLAG_LABEL.items() if k in sel.exclude],
        "layout": cfg.layout, "layout_label": LAYOUT_LABEL[cfg.layout], "kind": kind,
        "csv": cfg.csv, "mapped": mapped, "shared": shared, "not_in_file": absent,
        "result_columns": [{"letter": cols[rc["column"]].letter, "header": cols[rc["column"]].label,
                            **{k: v for k, v in rc.items() if k != "column"}} for rc in cfg.result_columns],
        "roles": [{"letter": cols[cid].letter, "header": cols[cid].label, "role": r,
                   "role_label": prep.AGG_ROLES[r][0]} for cid, r in cfg.roles.items()],
        "metric": cfg.metric, "types": [{"letter": cols[cid].letter, "header": cols[cid].label, "type": t,
                                         "type_label": prep.TYPE_LABEL[t]} for cid, t in cfg.types.items()],
        "dataset_name": cfg.dataset_name, "rules": cfg.rules.describe() if kind == "assessment" else [],
        "ignored_columns": prepared.ignored_columns,
    }

