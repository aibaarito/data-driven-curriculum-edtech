"""Deterministic SYNTHETIC follow-up assessment for demonstrating the intervention loop (seed 20261111).

Writes app/assets/data/synthetic_followup.csv: one 'current' assessment A7-FOLLOWUP-SIM dated 2026-10-20 for the
grade-7 students of the synthetic demo, on topics T7-05 and T7-06 (the topics the demo plan changes).

THIS IS SIMULATED DATA. Each student's latent topic level is their observed A7-POST percentage plus a fixed simulation
shift (SHIFT_PP) and noise; item scores are binomial draws. Any change an evaluation reports on this file is produced
by construction of the simulation and is NOT evidence that an intervention works.

    python scripts/generate_followup.py
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

import numpy as np

SEED = 20261111
SHIFT_PP = 3.0  # simulation parameter, documented in docs/ANALYTICS.md; not an estimate of any real effect
NOISE_SD = 8.0
TOPICS = ("T7-05", "T7-06")
ITEMS = 4
ITEM_MAX = 2
DATE = "2026-10-20"
ASSESSMENT = "A7-FOLLOWUP-SIM"
DATA = Path(__file__).resolve().parent.parent / "app" / "assets" / "data"
HEADER = ["school", "student_id", "grade", "class", "subject", "topic_id", "topic_name", "assessment_id",
          "assessment_type", "assessment_date", "comparison_group", "item_id", "score", "max_score", "textbook_id",
          "textbook_name"]


def build(source: Path = DATA / "synthetic_assessments.csv") -> list[list[str]]:
    obtained: dict[tuple[str, str], float] = defaultdict(float)
    available: dict[tuple[str, str], float] = defaultdict(float)
    info: dict[str, dict[str, str]] = {}
    names: dict[str, str] = {}
    with open(source, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["grade"] != "7" or r["topic_id"] not in TOPICS:
                continue
            names[r["topic_id"]] = r["topic_name"]
            info[r["student_id"]] = {k: r[k] for k in ("school", "grade", "class", "subject", "textbook_id",
                                                       "textbook_name")}
            if r["assessment_id"] == "A7-POST":
                obtained[(r["student_id"], r["topic_id"])] += float(r["score"])
                available[(r["student_id"], r["topic_id"])] += float(r["max_score"])
    rng = np.random.default_rng(SEED)
    rows: list[list[str]] = []
    for sid in sorted(info):
        s = info[sid]
        for tid in TOPICS:
            if available[(sid, tid)] <= 0:
                continue
            level = obtained[(sid, tid)] / available[(sid, tid)] * 100 + SHIFT_PP + rng.normal(0, NOISE_SD)
            p = min(0.99, max(0.01, level / 100))
            for q in range(1, ITEMS + 1):
                score = int(rng.binomial(ITEM_MAX, p))
                rows.append([s["school"], sid, s["grade"], s["class"], s["subject"], tid, names[tid], ASSESSMENT,
                             "current", DATE, "", f"{tid}-FU-Q{q}", str(score), str(ITEM_MAX), s["textbook_id"],
                             s["textbook_name"]])
    return rows


def main() -> None:
    out = DATA / "synthetic_followup.csv"
    with open(out, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(HEADER)
        w.writerows(build())
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
