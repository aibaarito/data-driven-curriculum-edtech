"""No-effect and power simulation for the textbook verdict (reproducible; documented in docs/ANALYTICS.md).

Model per scenario (two textbooks, one topic, one pre and one post assessment):
  ability_i ~ N(0, 13); class effects on level and on gain ~ N(0, class_sd) each, independent;
  pre  = 40 + ability + class_level + e1,          e1 ~ N(0, 7)
  post = 65 + ability + class_level + class_gain + effect*[textbook B] + e2,   e2 ~ N(0, 7)
  scores rounded and clipped to 0..100. Class sizes ~ Uniform{18..30} (unequal).
The verdict counts as a false positive when the true effect is 0 and verdict == "observed_difference".
Monte Carlo standard error = sqrt(p(1-p)/n).

    python scripts/simulate_textbook_fpr.py [--sims 500] [--seed 20261111]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.services import analytics as an  # noqa: E402
from app.services.settings_store import AnalysisSettings  # noqa: E402
from app.services.textbooks import compare_textbooks  # noqa: E402


def make_school(rng: np.random.Generator, classes_per_tb: int, class_sd: float, effect: float = 0.0) -> pd.DataFrame:
    rows, sid = [], 0
    for tb in (1, 2):
        for c in range(classes_per_tb):
            lvl, gain = rng.normal(0, class_sd), rng.normal(0, class_sd)
            for _ in range(int(rng.integers(18, 31))):
                sid += 1
                ab = rng.normal(0, 13)
                pre = np.clip(round(40 + ab + lvl + rng.normal(0, 7)), 0, 100)
                post = np.clip(round(65 + ab + lvl + gain + (effect if tb == 2 else 0) + rng.normal(0, 7)), 0, 100)
                for kind, aid, v in (("pre", 1, pre), ("post", 2, post)):
                    rows.append((sid, tb * 100 + c, kind, aid, tb, float(v)))
    f = pd.DataFrame(rows, columns=["student_id", "class_id", "kind", "assessment_id", "textbook_id", "score"])
    f = f.assign(student_ext=f.student_id.astype(str), class_name=f.class_id.astype(str), grade=7, subject_id=1,
                 subject_name="M", topic_id=1, topic_code="T", topic_name="T", topic_order=1,
                 assessment_code=f.assessment_id.astype(str), assessment_date=None, comparison_group="G",
                 textbook_code="TB" + f.textbook_id.astype(str), textbook_name="TB" + f.textbook_id.astype(str),
                 item_id="_total", max_score=100.0)
    return f[an.COLUMNS]


def rate(rng: np.random.Generator, sims: int, k: int, sd: float, effect: float) -> tuple[float, float]:
    s = AnalysisSettings()
    hits = sum(compare_textbooks(make_school(rng, k, sd, effect), s)["pairs"][0]["verdict"] == "observed_difference"
               for _ in range(sims))
    p = hits / sims
    return p, float(np.sqrt(p * (1 - p) / sims))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=500)
    ap.add_argument("--seed", type=int, default=20261111)
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)
    t0 = time.time()
    print(f"seed={args.seed} sims/scenario={args.sims}")
    print("classes/textbook  class_sd  true_effect  P(observed_difference)  MC s.e.")
    for effect in (0.0, 6.0):
        for k in (3, 4, 6):
            for sd in (1.5, 4.0, 8.0):
                p, se = rate(rng, args.sims, k, sd, effect)
                print(f"{k:>16}  {sd:>8}  {effect:>11}  {p:>22.3f}  {se:.3f}")
    print(f"elapsed {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
