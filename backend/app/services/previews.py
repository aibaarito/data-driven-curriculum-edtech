"""Import-preview lifecycle: expiry and purging of staged rows."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.orm import Session

from app import models as m

log = logging.getLogger(__name__)
COMMIT_LOCK_KEY = 715_001  # pg_advisory_xact_lock key serializing import commits


def expiry_from_now(ttl_minutes: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)


def purge_expired(db: Session) -> int:
    """Mark open previews past their expiry as expired and drop their staged rows. Returns the count.

    Only rows still in status 'preview' are touched, so committed batches and a commit holding the row lock
    (SELECT ... FOR UPDATE in the commit endpoint) are never affected.
    """
    res = db.execute(
        update(m.ImportBatch)
        .where(m.ImportBatch.status == "preview", m.ImportBatch.expires_at < datetime.now(timezone.utc))
        .values(status="expired", staged_rows=None)
    )
    db.commit()
    if res.rowcount:
        log.info("Expired %s import preview(s)", res.rowcount)
    return res.rowcount or 0
