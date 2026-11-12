"""General and aggregate datasets: deterministic exploration, kept separate from assessment records.

Stored values are the original cell texts. Types are confirmed by the user and only control how values are read for
summaries; a value that does not match its column type stays as text and is excluded from typed calculations.
Nothing here feeds the educational recommendation services.
"""
from __future__ import annotations

import csv
import io
import math
import statistics
from collections import Counter
from typing import Any

from app.services import import_rules as rules_mod
from app.services.importer import NAME_LIKE, parse_number

BOOL_TRUE = {"да", "true", "1", "yes", "верно", "+"}
BOOL_FALSE = {"нет", "false", "0", "no", "неверно", "-"}
PAGE_SIZE = 50
TOP_CATEGORIES = 10
HIST_BINS = 10


def typed(value: str, t: str) -> Any:
    """Value read under the column type, or None if it does not match (never coerced)."""
    if value is None or value == "":
        return None
    if t == "number":
        x, err = parse_number(value)
        return None if err else x
    if t == "date":
        iso, err = rules_mod.parse_date_rule(value, "auto")
        return None if err else iso
    if t == "boolean":
        v = value.strip().casefold()
        return True if v in BOOL_TRUE else False if v in BOOL_FALSE else None
    return value


def type_matches(value: str, t: str) -> bool:
    return t in ("text", "category", "identifier") or typed(value, t) is not None


def profile(columns: list[dict[str, Any]], rows: list[list[str]]) -> dict[str, Any]:
    n = len(rows)
    out_cols = []
    for i, c in enumerate(columns):
        t = c.get("type", "text")
        vals = [r[i] if i < len(r) else "" for r in rows]
        filled = [v for v in vals if v != ""]
        col: dict[str, Any] = {"id": c["id"], "letter": c["letter"], "label": c["label"], "type": t,
                               "missing": n - len(filled), "missing_pct": round((n - len(filled)) / n * 100, 1) if n
                               else 0, "distinct": len(set(filled))}
        if t == "number":
            nums = [x for x in (typed(v, "number") for v in filled) if x is not None]
            col["mismatched"] = len(filled) - len(nums)
            if nums:
                col["numeric"] = {"count": len(nums), "mean": round(statistics.fmean(nums), 4),
                                  "median": round(statistics.median(nums), 4), "min": min(nums), "max": max(nums),
                                  "sd": round(statistics.stdev(nums), 4) if len(nums) > 1 else None}
                col["histogram"] = _histogram(nums)
        elif t == "date":
            ds = sorted(x for x in (typed(v, "date") for v in filled) if x is not None)
            col["mismatched"] = len(filled) - len(ds)
            if ds:
                col["date_range"] = {"from": ds[0], "to": ds[-1]}
        elif t in ("category", "boolean"):
            freq = Counter(_safe(v) for v in filled).most_common(TOP_CATEGORIES)
            col["frequencies"] = [{"value": v, "count": k} for v, k in freq]
            col["other_count"] = len(filled) - sum(k for _, k in freq)
        elif t == "text":
            lengths = [len(v) for v in filled]
            col["avg_length"] = round(statistics.fmean(lengths), 1) if lengths else None
        # identifiers: no numeric summary and no frequency list (each value identifies a row)
        out_cols.append(col)
    keyed = Counter(tuple(r) for r in rows)
    duplicates = sum(k - 1 for k in keyed.values() if k > 1)
    return {"rows": n, "columns": len(columns), "duplicate_rows": duplicates, "column_profiles": out_cols}


def _histogram(nums: list[float]) -> list[dict[str, Any]]:
    lo, hi = min(nums), max(nums)
    if lo == hi:
        return [{"from": lo, "to": hi, "count": len(nums)}]
    width = (hi - lo) / HIST_BINS
    counts = [0] * HIST_BINS
    for x in nums:
        counts[min(int((x - lo) / width), HIST_BINS - 1)] += 1
    return [{"from": round(lo + i * width, 4), "to": round(lo + (i + 1) * width, 4), "count": k}
            for i, k in enumerate(counts)]


def _safe(v: str) -> str:
    v = v[:80]
    return "(скрыто: похоже на ФИО)" if NAME_LIKE.match(v) else v


def query_rows(columns: list[dict[str, Any]], rows: list[tuple[int, list[str]]], q: str | None, sort: str | None,
               direction: str, filter_col: str | None, filter_value: str | None, page: int) -> dict[str, Any]:
    """Search (substring, case-insensitive), filter (exact value), typed sort and paging."""
    ids = [c["id"] for c in columns]
    sel = rows
    if q:
        needle = q.casefold()
        sel = [(r, v) for r, v in sel if any(needle in x.casefold() for x in v)]
    if filter_col in ids and filter_value is not None:
        i = ids.index(filter_col)
        sel = [(r, v) for r, v in sel if (v[i] if i < len(v) else "") == filter_value]
    if sort in ids:
        i = ids.index(sort)
        t = columns[i].get("type", "text")

        def key(item: tuple[int, list[str]]) -> tuple:
            x = typed(item[1][i] if i < len(item[1]) else "", t)
            if x is None:
                return (1, "")  # missing / mismatched values last in both directions
            return (0, x if t in ("number", "date") else str(x).casefold())

        missing = [it for it in sel if key(it)[0] == 1]
        present = sorted([it for it in sel if key(it)[0] == 0], key=key, reverse=direction == "desc")
        sel = present + missing
    total = len(sel)
    start = max(page, 0) * PAGE_SIZE
    return {"total": total, "page": page, "page_size": PAGE_SIZE,
            "rows": [{"source_row": r, "values": v} for r, v in sel[start:start + PAGE_SIZE]]}


_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value: str) -> str:
    """Neutralise spreadsheet formula injection in exports; plain numbers such as -5 stay numbers."""
    if value and value.startswith(_FORMULA_START):
        x, err = parse_number(value)
        if err or x is None or not math.isfinite(x):
            return "'" + value
    return value


def export_csv(columns: list[dict[str, Any]], rows: list[tuple[int, list[str]]]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Строка источника"] + [csv_safe(c["label"]) for c in columns])
    for r, v in rows:
        w.writerow([r] + [csv_safe(x) for x in v])
    return ("﻿" + buf.getvalue()).encode("utf-8")


def aggregate_summary(columns: list[dict[str, Any]], records: list[dict[str, Any]],
                      metric: dict[str, Any]) -> dict[str, Any]:
    """Descriptive summary of an aggregate table. Group values are as stored; no student-level statistics."""
    def group_by(role: str) -> list[dict[str, Any]]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for rec in records:
            key = rec.get(role)
            if key:
                groups.setdefault(key, []).append(rec)
        out = []
        for key, recs in sorted(groups.items()):
            pcts = [r["pct"] for r in recs]
            ns = [r.get("n") for r in recs]
            weighted = None
            if all(isinstance(n, int) and n > 0 for n in ns):
                weighted = round(sum(p * n for p, n in zip(pcts, ns)) / sum(ns), 1)
            out.append({"group": key, "rows": len(recs), "mean_of_groups_pct": round(statistics.fmean(pcts), 1),
                        "min_pct": round(min(pcts), 1), "max_pct": round(max(pcts), 1),
                        "weighted_pct": weighted, "students_total": sum(ns) if weighted is not None else None})
        return out

    roles = {c.get("role") for c in columns if c.get("role")}
    return {
        "metric": metric,
        "by_topic": group_by("topic_name") if "topic_name" in roles else group_by("topic_id")
        if "topic_id" in roles else [],
        "by_class": group_by("class") if "class" in roles else [],
        "by_textbook": group_by("textbook") if "textbook" in roles else [],
        "records": len(records),
        "note": "Агрегированные данные: показатели групп, а не учеников. «Среднее по группам» — невзвешенное среднее "
                "показателей строк; «взвешенное» рассчитывается, только если для всех строк указано число учеников. "
                "Различия между группами описательные и не означают причинно-следственной связи.",
    }
