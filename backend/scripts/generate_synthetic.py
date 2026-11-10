"""Generate the SYNTHETIC demonstration dataset (deterministic seed).

Everything produced here is invented. School code "SYNTH-DEMO" marks it as synthetic everywhere in the UI.

Built-in patterns (by design, so the platform has something to find):
* T7-05 "Формулы сокращённого умножения": consistently low (~39%) with no measurable pre→post gain.
* T7-06 "Разложение на множители": low result but large measurable gain (improving after instruction).
* T7-01 "Линейные уравнения": strong improvement (≈34% → 80%).
* Textbook B classes start ~3 p.p. lower (baseline) but gain ~6 p.p. more — raw averages look similar,
  baseline-adjusted comparison shows a difference.
* T7-07 "Линейная функция" gets the most hours while already mastered → allocation worth reviewing.
* Grade 8 has one class per textbook → "insufficient evidence" for that comparison.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np

SEED = 20251110
OUT = Path(__file__).resolve().parent.parent / "app" / "assets" / "data"
HEADER = ["school", "student_id", "grade", "class", "subject", "topic_id", "topic_name", "assessment_id",
          "assessment_type", "assessment_date", "comparison_group", "item_id", "score", "max_score", "textbook_id",
          "textbook_name", "teaching_hours", "topic_order", "topic_min_hours", "topic_max_hours", "topic_priority",
          "topic_prerequisites"]

# code, name, pre%, post%, hours, min, max, priority, prerequisites
TOPICS_7 = [
    ("T7-01", "Линейные уравнения", 34, 80, 12, 8, 16, 3, ""),
    ("T7-02", "Степень с натуральным показателем", 45, 77, 10, 6, 14, 2, ""),
    ("T7-03", "Одночлены", 41, 73, 8, 5, 12, 2, "T7-02"),
    ("T7-04", "Многочлены", 31, 63, 12, 8, 16, 3, "T7-03"),
    ("T7-05", "Формулы сокращённого умножения", 38, 39.5, 6, 4, 12, 3, "T7-04"),
    ("T7-06", "Разложение на множители", 18, 47, 8, 5, 12, 2, "T7-05"),
    ("T7-07", "Линейная функция", 56, 87, 16, 8, 16, 2, ""),
    ("T7-08", "Системы линейных уравнений", 26, 66, 10, 6, 14, 3, "T7-01"),
]
TOPICS_8 = [
    ("T8-01", "Квадратные корни", 30, 70, 10, 6, 14, 2, ""),
    ("T8-02", "Квадратные уравнения", 25, 64, 14, 10, 18, 3, "T8-01"),
    ("T8-03", "Рациональные дроби", 28, 58, 12, 8, 16, 2, ""),
    ("T8-04", "Неравенства", 35, 71, 10, 6, 14, 2, ""),
]
# code, type, date, group, topics, item max points, progress fraction (current only)
ASSESS_7 = [
    ("A7-PRE", "pre", "2025-09-12", "G7-2025-26", [t[0] for t in TOPICS_7], [1, 2, 2, 3], None),
    ("A7-Q1", "current", "2025-10-24", None, ["T7-01", "T7-02"], [1, 2, 2], 0.9),
    ("A7-MID", "current", "2025-12-19", None, ["T7-01", "T7-02", "T7-03", "T7-04"], [1, 2, 2], 0.95),
    ("A7-Q3", "current", "2026-03-13", None, ["T7-05", "T7-06", "T7-07"], [1, 2, 2], 0.9),
    ("A7-POST", "post", "2026-05-15", "G7-2025-26", [t[0] for t in TOPICS_7], [1, 2, 2, 3], None),
]
ASSESS_8 = [
    ("A8-PRE", "pre", "2025-09-15", "G8-2025-26", [t[0] for t in TOPICS_8], [1, 2, 2, 3], None),
    ("A8-MID", "current", "2026-01-23", None, ["T8-01", "T8-02"], [1, 2, 2], 0.9),
    ("A8-POST", "post", "2026-05-18", "G8-2025-26", [t[0] for t in TOPICS_8], [1, 2, 2, 3], None),
]
TEXTBOOKS = {
    "TB-A7": "Алгебра 7 — учебник А (условный)", "TB-B7": "Алгебра 7 — учебник Б (условный)",
    "TB-A8": "Алгебра 8 — учебник А (условный)", "TB-B8": "Алгебра 8 — учебник Б (условный)",
}
# class, grade, textbook, size, ability shift (SD), hours overrides
CLASSES = [
    ("7А", 7, "TB-A7", 27, 0.25, {}),
    ("7Б", 7, "TB-A7", 25, 0.30, {}),
    ("7В", 7, "TB-A7", 26, 0.20, {"T7-05": 7, "T7-07": 15}),
    ("7Г", 7, "TB-B7", 28, 0.0, {}),
    ("7Д", 7, "TB-B7", 24, -0.05, {}),
    ("7Е", 7, "TB-B7", 26, 0.05, {"T7-04": 13, "T7-07": 15}),
    ("8А", 8, "TB-A8", 22, 0.0, {}),
    ("8Б", 8, "TB-B8", 21, 0.0, {}),
]
TEXTBOOK_GAIN = {"TB-A7": -3.0, "TB-B7": 3.0, "TB-A8": 0.0, "TB-B8": 1.5}
ABILITY_PP = 13.0  # percentage points per SD of ability
SUBJECT = "Математика"


def generate() -> list[list[str]]:
    rng = np.random.default_rng(SEED)
    rows: list[list[str]] = []
    for cls, grade, tb, size, shift, overrides in CLASSES:
        topics = TOPICS_7 if grade == 7 else TOPICS_8
        assessments = ASSESS_7 if grade == 7 else ASSESS_8
        class_eff = rng.normal(0, 1.5)
        letter = {"А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D", "Е": "E"}[cls[1]]
        for i in range(1, size + 1):
            sid = f"S{grade}{letter}-{i:03d}"
            theta = rng.normal(shift, 1.0)
            for code, kind, d, group, tcodes, items, frac in assessments:
                for tc in tcodes:
                    t = next(x for x in topics if x[0] == tc)
                    pre = t[2] + ABILITY_PP * theta + class_eff + rng.normal(0, 7)
                    post = t[3] + ABILITY_PP * theta + class_eff + TEXTBOOK_GAIN[tb] + rng.normal(0, 7)
                    if kind == "pre":
                        p = pre
                    elif kind == "post":
                        p = post
                    else:
                        p = pre + (post - pre) * frac + rng.normal(0, 4)
                    p = float(np.clip(p, 2, 98)) / 100
                    hours = overrides.get(tc, t[4])
                    for k, mx in enumerate(items, start=1):
                        p_item = float(np.clip(p + (0.08 if k == 1 else -0.04 if k == len(items) else 0), 0.01, 0.99))
                        score = int(rng.binomial(mx, p_item))
                        rows.append(["SYNTH-DEMO", sid, str(grade), cls, SUBJECT, tc, t[1], code, kind, d, group or "",
                                     f"{tc}-Q{k}", str(score), str(mx), tb, TEXTBOOKS[tb], f"{hours:g}",
                                     str(topics.index(t) + 1), f"{t[5]:g}", f"{t[6]:g}", str(t[7]), t[8]])
    return rows


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = generate()
    with open(OUT / "synthetic_assessments.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(HEADER)
        w.writerows(rows)
    with open(OUT / "template.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(HEADER)
        w.writerow(["my-school", "STU-0001", "7", "7А", SUBJECT, "T7-01", "Линейные уравнения", "A7-PRE", "pre",
                    "2025-09-12", "G7-2025-26", "T7-01-Q1", "1", "2", "TB-A7", "Учебник А", "12", "1", "8", "16", "3", ""])
        w.writerow(["my-school", "STU-0001", "7", "7А", SUBJECT, "T7-01", "Линейные уравнения", "A7-POST", "post",
                    "2026-05-15", "G7-2025-26", "T7-01-Q1", "2", "2", "TB-A7", "Учебник А", "12", "1", "8", "16", "3", ""])
    print(f"wrote {len(rows)} synthetic rows to {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
