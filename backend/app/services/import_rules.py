"""Guided import: explicit, user-confirmed parsing rules and score interpretation.

Defaults reproduce the strict rules of ``importer`` exactly (decimal "auto", dates ГГГГ-ММ-ДД / ДД.ММ.ГГГГ, scores as
points with a known maximum). Every other interpretation must be chosen by the user; nothing is inferred from the
data (no "largest observed value = maximum", no guessed day/month order, no 1–5 → % conversion without a table,
no missing → 0).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from app.services.importer import parse_number

DECIMALS = ("auto", "comma", "dot")
DATE_FORMATS = {"auto": None, "DD.MM.YYYY": "%d.%m.%Y", "YYYY-MM-DD": "%Y-%m-%d", "DD/MM/YYYY": "%d/%m/%Y",
                "MM/DD/YYYY": "%m/%d/%Y", "DD-MM-YYYY": "%d-%m-%Y"}
SCORE_MODES = ("points", "percent", "binary", "scale")
MAX_MARKERS = 20
MAX_SCALE_ENTRIES = 50

_COMMA_GROUPED = re.compile(r"^-?\d{1,3}(?:[.   ]\d{3})+(?:,\d+)?$")
_DOT_GROUPED = re.compile(r"^-?\d{1,3}(?:[,   ]\d{3})+(?:\.\d+)?$")
_COMMA_PLAIN = re.compile(r"^-?\d+(?:,\d+)?$")
_DOT_PLAIN = re.compile(r"^-?\d+(?:\.\d+)?$")
_SLASH_DATE = re.compile(r"^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}$")


class RuleError(ValueError):
    pass


@dataclass
class Rules:
    decimal: str = "auto"
    date_format: str = "auto"
    missing_markers: tuple[str, ...] = ()
    score_mode: str = "points"
    percent_scale: str = "0-100"  # or "0-1" (Excel percentage cells are stored as fractions)
    true_tokens: tuple[str, ...] = ()
    false_tokens: tuple[str, ...] = ()
    scale: dict[str, float] = field(default_factory=dict)  # normalised source value -> percent 0..100

    @property
    def is_default(self) -> bool:
        return (self.decimal, self.date_format, self.missing_markers, self.score_mode) == ("auto", "auto", (),
                                                                                          "points")

    def canonical(self) -> dict[str, Any]:
        return {"decimal": self.decimal, "date_format": self.date_format,
                "missing_markers": list(self.missing_markers), "score_mode": self.score_mode,
                "percent_scale": self.percent_scale, "true_tokens": list(self.true_tokens),
                "false_tokens": list(self.false_tokens), "scale": dict(sorted(self.scale.items()))}

    def describe(self) -> list[str]:
        """Russian description shown in the confirmation summary."""
        out = [{"points": "Результат — баллы с известным максимумом.",
                "percent": f"Результат — проценты ({'0–100' if self.percent_scale == '0-100' else 'доли 0–1'}); "
                           "сохраняется как балл из 100.",
                "binary": "Результат — верно/неверно; сохраняется как 1 или 0 из 1.",
                "scale": "Результат — отметка по шкале; перевод в проценты задан таблицей."}[self.score_mode]]
        if self.score_mode == "binary":
            out.append(f"Верно: {', '.join(self.true_tokens)}; неверно: {', '.join(self.false_tokens)}.")
        if self.score_mode == "scale":
            out.append("Шкала: " + "; ".join(f"{k} → {v:g}%" for k, v in sorted(self.scale.items())) + ".")
        out.append({"auto": "Числа: «.» или «,» как десятичный знак; неоднозначные записи отклоняются.",
                    "comma": "Числа: десятичная запятая; точка и пробел — разделители разрядов.",
                    "dot": "Числа: десятичная точка; запятая и пробел — разделители разрядов."}[self.decimal])
        out.append("Даты: " + ("ГГГГ-ММ-ДД, ДД.ММ.ГГГГ или дата Excel." if self.date_format == "auto"
                               else f"{self.date_format} (или дата Excel)."))
        if self.missing_markers:
            out.append("Отметки отсутствия результата (запись не создаётся, не считается нулём): "
                       + ", ".join(f"«{m}»" for m in self.missing_markers) + ".")
        return out


def _token(v: Any) -> str:
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip().casefold()


def parse_rules(raw: dict[str, Any] | None) -> Rules:
    """Validate client-supplied rules. Raises RuleError with a Russian message."""
    raw = raw or {}
    r = Rules()
    r.decimal = raw.get("decimal", "auto")
    if r.decimal not in DECIMALS:
        raise RuleError("Неизвестное правило для десятичного разделителя.")
    r.date_format = raw.get("date_format", "auto")
    if r.date_format not in DATE_FORMATS:
        raise RuleError("Неизвестный формат даты.")
    markers = raw.get("missing_markers") or []
    if not isinstance(markers, list) or len(markers) > MAX_MARKERS or not all(isinstance(m, str) for m in markers):
        raise RuleError("Отметки отсутствия результата заданы неверно.")
    r.missing_markers = tuple(dict.fromkeys(m.strip().casefold() for m in markers if m.strip()))
    if any(len(m) > 20 for m in r.missing_markers):
        raise RuleError("Отметка отсутствия результата слишком длинная.")
    r.score_mode = raw.get("score_mode", "points")
    if r.score_mode not in SCORE_MODES:
        raise RuleError("Неизвестный способ записи результата.")
    r.percent_scale = raw.get("percent_scale", "0-100")
    if r.percent_scale not in ("0-100", "0-1"):
        raise RuleError("Неизвестная шкала процентов.")
    if r.score_mode == "binary":
        t = tuple(dict.fromkeys(_token(x) for x in raw.get("true_tokens") or [] if str(x).strip()))
        f = tuple(dict.fromkeys(_token(x) for x in raw.get("false_tokens") or [] if str(x).strip()))
        if not t or not f:
            raise RuleError("Укажите значения, которые означают «верно» и «неверно».")
        if set(t) & set(f):
            raise RuleError("Одно и то же значение указано и как «верно», и как «неверно».")
        if (set(t) | set(f)) & set(r.missing_markers):
            raise RuleError("Значение указано и как результат, и как отметка отсутствия.")
        r.true_tokens, r.false_tokens = t, f
    if r.score_mode == "scale":
        scale = raw.get("scale") or {}
        if not isinstance(scale, dict) or not scale or len(scale) > MAX_SCALE_ENTRIES:
            raise RuleError("Задайте таблицу перевода отметок в проценты (каждая отметка → процент 0–100).")
        out: dict[str, float] = {}
        for k, v in scale.items():
            key = _token(k)
            x, err = parse_number(v) if not isinstance(v, (int, float)) else (float(v), None)
            if not key or x is None or err or not 0 <= x <= 100:
                raise RuleError(f"Для отметки «{str(k)[:10]}» укажите процент от 0 до 100.")
            out[key] = x
        r.scale = out
    return r


def is_missing(v: Any, rules: Rules) -> bool:
    return bool(rules.missing_markers) and isinstance(v, str) and v.strip().casefold() in rules.missing_markers


def parse_num(v: Any, decimal: str) -> tuple[float | None, str | None]:
    """Number under the confirmed decimal rule. Native spreadsheet numbers are taken as stored."""
    if isinstance(v, bool):
        return None, "INVALID_NUMBER"
    if isinstance(v, (int, float)):
        x = float(v)
        return (None, "INVALID_NUMBER") if (math.isnan(x) or math.isinf(x)) else (x, None)
    if decimal == "auto":
        return parse_number(v)
    s = str(v).strip()
    if decimal == "comma":
        if _COMMA_GROUPED.match(s):
            s = re.sub(r"[.   ]", "", s)
        elif not _COMMA_PLAIN.match(s):
            return None, "INVALID_NUMBER"
        s = s.replace(",", ".")
    else:
        if _DOT_GROUPED.match(s):
            s = re.sub(r"[,   ]", "", s)
        elif not _DOT_PLAIN.match(s):
            return None, "INVALID_NUMBER"
    x = float(s)
    return (None, "INVALID_NUMBER") if (math.isnan(x) or math.isinf(x)) else (x, None)


def parse_date_rule(v: Any, fmt: str) -> tuple[str | None, str | None]:
    """ISO date string under the confirmed format, or (None, code). Spreadsheet date cells are taken as stored."""
    if isinstance(v, datetime):
        return v.date().isoformat(), None
    if isinstance(v, date):
        return v.isoformat(), None
    s = str(v).strip()
    if " " in s:
        s = s.split(" ")[0]
    if fmt == "auto":
        if _SLASH_DATE.match(s):
            return None, "DATE_FORMAT_REQUIRED"
        for f in ("%Y-%m-%d", "%d.%m.%Y"):
            try:
                return datetime.strptime(s, f).date().isoformat(), None
            except ValueError:
                continue
        return None, "INVALID_DATE"
    try:
        return datetime.strptime(s, DATE_FORMATS[fmt]).date().isoformat(), None
    except ValueError:
        return None, "INVALID_DATE"


def interpret_score(raw: Any, raw_max: Any, rules: Rules) -> tuple[float | None, float | None, str | None]:
    """(score, max_score, error_code) under the confirmed interpretation. Missing markers are handled by callers."""
    mode = rules.score_mode
    if mode == "points":
        s, e = parse_num(raw, rules.decimal)
        if e:
            return None, None, e
        if raw_max is None or (isinstance(raw_max, str) and not raw_max.strip()):
            return s, None, "MISSING_MAX_SCORE"
        m, e2 = parse_num(raw_max, rules.decimal)
        return s, m, ("INVALID_MAX_SCORE" if e2 else None)
    if mode == "percent":
        text = str(raw).strip() if isinstance(raw, str) else raw
        if isinstance(text, str) and text.endswith("%"):
            x, e = parse_num(text[:-1].strip(), rules.decimal)
            if e:
                return None, None, e
            return x, 100.0, (None if 0 <= x <= 100 else "PERCENT_OUT_OF_RANGE")
        x, e = parse_num(text, rules.decimal)
        if e:
            return None, None, e
        if rules.percent_scale == "0-1":
            x = x * 100
        return x, 100.0, (None if 0 <= x <= 100 else "PERCENT_OUT_OF_RANGE")
    if mode == "binary":
        t = _token(raw)
        if t in rules.true_tokens:
            return 1.0, 1.0, None
        if t in rules.false_tokens:
            return 0.0, 1.0, None
        return None, None, "BINARY_VALUE_UNDEFINED"
    t = _token(raw)
    if t not in rules.scale:
        x, _ = parse_num(raw, "auto")
        alt = _token(x) if x is not None else None
        if alt in rules.scale:
            return rules.scale[alt], 100.0, None
        return None, None, "SCALE_VALUE_UNDEFINED"
    return rules.scale[t], 100.0, None


RULE_MESSAGES = {
    "INVALID_NUMBER": ("Значение не распознано как число по выбранному правилу.",
                       "Проверьте запись числа или правило десятичного разделителя."),
    "AMBIGUOUS_NUMBER": ("Неоднозначная запись числа (например, 1,000).",
                         "Укажите десятичный разделитель в правилах разбора."),
    "MISSING_MAX_SCORE": ("Не указан максимальный балл.",
                          "Укажите столбец или значение максимального балла; он не подставляется автоматически."),
    "INVALID_MAX_SCORE": ("Максимальный балл не распознан как число.", "Исправьте значение в файле."),
    "PERCENT_OUT_OF_RANGE": ("Процент вне диапазона 0–100.",
                             "Проверьте шкалу процентов (0–100 или доли 0–1) и значение в файле."),
    "BINARY_VALUE_UNDEFINED": ("Значение не входит ни в «верно», ни в «неверно».",
                               "Добавьте значение в правило или в отметки отсутствия результата."),
    "SCALE_VALUE_UNDEFINED": ("Для этой отметки не задан перевод в проценты.",
                              "Добавьте отметку в таблицу шкалы."),
    "DATE_FORMAT_REQUIRED": ("Дата записана через «/» или «-»: порядок дня и месяца неизвестен.",
                             "Выберите формат даты в правилах разбора (например, ДД/ММ/ГГГГ)."),
    "INVALID_DATE": ("Дата не соответствует выбранному формату.", "Исправьте дату или выберите другой формат."),
}
