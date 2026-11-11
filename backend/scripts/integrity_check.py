"""Check (and optionally repair) data imported before the integrity fixes.

    python scripts/integrity_check.py                      # read-only report (default)
    python scripts/integrity_check.py --add-missing-assignments --redact-validation --purge-expired-previews

Uses DATABASE_URL like the app. Repairs are explicit, transactional and never invent textbook assignments.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import get_db  # noqa: E402
from app.services.integrity import repair, run_integrity_checks  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--add-missing-assignments", action="store_true",
                    help="create missing (class, subject) assignments with textbook = NULL (not specified)")
    ap.add_argument("--redact-validation", action="store_true",
                    help="rewrite stored validation messages that echoed raw values")
    ap.add_argument("--purge-expired-previews", action="store_true", help="drop staged rows of stale previews")
    args = ap.parse_args()
    db = next(get_db())
    before = run_integrity_checks(db)
    print(json.dumps({"before": before["counts"]}, ensure_ascii=False, indent=2))
    if args.add_missing_assignments or args.redact_validation or args.purge_expired_previews:
        done = repair(db, add_missing_assignments=args.add_missing_assignments,
                      redact_validation=args.redact_validation, purge_previews=args.purge_expired_previews)
        after = run_integrity_checks(db)
        print(json.dumps({"repaired": done, "after": after["counts"]}, ensure_ascii=False, indent=2))
        print("Not repaired automatically (needs a human decision): mixed_granularity_results, "
              "class_topic_grade_mismatch, textbook_subject_mismatch.")
    return 0 if before["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
