"""Guided import endpoints: upload a source, inspect a worksheet/header row, validate a mapping.

Lifecycle (one ImportBatch row per upload, status "preview" until committed, discarded or expired):
  POST /api/imports/sources              -> stores the file, returns sheets, suggestions and a session key
  POST /api/imports/{id}/inspect         -> preview + columns + suggestions for a sheet and header row (read-only)
  POST /api/imports/{id}/validate        -> applies the configuration, runs the existing validator, stages rows
  POST /api/imports/{id}/commit          -> (routes.py) commits only if config_hash matches the last validation
Nothing here writes to the analytical tables. Cell contents are never logged.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import undefer

from app import models as m
from app.api.deps import DB
from app.config import get_settings
from app.services import import_prep as prep
from app.services.import_store import load_existing_state
from app.services.importer import FileFormatError, Issue, rows_to_json, validate_dataframe
from app.services.previews import expiry_from_now, purge_expired

router = APIRouter(prefix="/api/imports")
log = logging.getLogger("ddc.import")


class InspectBody(BaseModel):
    session_key: str = Field(..., max_length=128)
    sheet: str = Field(..., max_length=255)
    header_row: int | None = Field(None, ge=1, le=1_048_576)


class ValidateBody(BaseModel):
    session_key: str = Field(..., max_length=128)
    sheet: str = Field(..., max_length=255)
    header_row: int = Field(..., ge=1, le=1_048_576)
    fields: dict[str, dict[str, Any]] = Field(default_factory=dict, max_length=64)
    confirm_shared: bool = False


def _key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _err(status: int, code: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message, **extra})


def guided_batch(db, batch_id: int, session_key: str | None, *, lock: bool = False) -> m.ImportBatch:
    """Load an open guided preview owned by the caller (session key), enforcing expiry. Raises HTTPException."""
    q = db.query(m.ImportBatch).options(undefer(m.ImportBatch.source_file)).filter(m.ImportBatch.id == batch_id)
    batch = q.with_for_update().first() if lock else q.first()
    if batch is None or batch.session_key_hash is None:
        raise _err(404, "PREVIEW_NOT_FOUND", "Импорт не найден.")
    if not session_key or not hmac.compare_digest(batch.session_key_hash, _key_hash(session_key)):
        raise _err(403, "PREVIEW_FORBIDDEN", "Этот предпросмотр принадлежит другому сеансу загрузки.")
    expired = batch.status == "expired" or (batch.status == "preview" and batch.expires_at is not None
                                            and batch.expires_at < datetime.now(timezone.utc))
    if expired:
        batch.status, batch.staged_rows, batch.source_file, batch.prep_config = "expired", None, None, None
        db.commit()
        raise _err(410, "PREVIEW_EXPIRED", "Срок действия предпросмотра истёк. Загрузите файл заново.")
    if batch.status != "preview" or batch.source_file is None:
        raise _err(409, "PREVIEW_CLOSED", "Этот импорт уже подтверждён или отменён.")
    return batch


def _read(batch: m.ImportBatch, sheet: str | None = None, formulas: bool = False) -> prep.Workbook:
    try:
        return prep.read_workbook(batch.source_file, batch.filename, max_data_rows=get_settings().max_upload_rows,
                                  sheet_name=sheet, detect_formulas=formulas)
    except prep.FileFormatError as exc:
        raise _err(422, "UNREADABLE_FILE", str(exc)) from exc


def _auto_ready(inspection: dict[str, Any] | None) -> bool:
    """True when sheet, header row and every required field are unambiguous (the standard template)."""
    if not inspection or inspection.get("problem") or inspection.get("header_row") is None:
        return False
    if inspection["header_suggestion"].get("confidence") != "high":
        return False
    sugg = inspection["suggestions"]
    if any(n["severity"] == "error" for n in inspection["notices"]):
        return False
    return all(f in sugg["suggested"] and f not in sugg["ambiguous"] for f in prep.REQUIRED_COLUMNS)


@router.post("/sources")
def upload_source(db: DB, file: UploadFile) -> dict[str, Any]:
    settings = get_settings()
    limit = settings.max_upload_bytes
    content = file.file.read(limit + 1)
    if len(content) > limit:
        raise _err(413, "FILE_TOO_LARGE", f"Файл больше {settings.max_upload_mb:g} МБ.")
    filename = (file.filename or "upload").replace("\\", "/").split("/")[-1][:255]
    try:
        wb = prep.read_workbook(content, filename, max_data_rows=settings.max_upload_rows)
    except FileFormatError as exc:
        raise _err(422, "UNREADABLE_FILE", str(exc)) from exc
    purge_expired(db)
    key = secrets.token_urlsafe(24)
    batch = m.ImportBatch(filename=filename, status="preview", total_rows=0, valid_rows=0, validation={},
                          staged_rows=None, expires_at=expiry_from_now(settings.preview_ttl_minutes),
                          source_file=content, source_sha256=hashlib.sha256(content).hexdigest(),
                          session_key_hash=_key_hash(key))
    db.add(batch)
    db.commit()
    suggestion = prep.suggest_sheet(wb.sheets)
    inspection = None
    if suggestion["name"] is not None:
        sheet = wb.get(suggestion["name"])
        inspection = prep.inspect_sheet(sheet, prep.suggest_header_row(sheet)["row"])
    log.info("Import source stored: batch=%s kind=%s sheets=%s bytes=%s", batch.id, wb.kind, len(wb.sheets),
             len(content))
    return {"batch_id": batch.id, "session_key": key, "filename": filename, "kind": wb.kind,
            "expires_at": batch.expires_at.isoformat(), "sheets": [prep.sheet_summary(s) for s in wb.sheets],
            "sheet_suggestion": suggestion, "inspection": inspection, "auto_ready": _auto_ready(inspection),
            "fields": prep.field_catalogue(), "limits": _limits()}


def _limits() -> dict[str, Any]:
    s = get_settings()
    return {"max_upload_mb": s.max_upload_mb, "max_rows": s.max_upload_rows, "max_columns": prep.MAX_COLUMNS,
            "max_sheets": prep.MAX_SHEETS, "header_scan_rows": prep.HEADER_SCAN_ROWS,
            "preview_ttl_minutes": s.preview_ttl_minutes}


@router.post("/{batch_id}/inspect")
def inspect(db: DB, batch_id: int, body: InspectBody) -> dict[str, Any]:
    batch = guided_batch(db, batch_id, body.session_key)
    wb = _read(batch, sheet=body.sheet)
    sheet = wb.get(body.sheet)
    if sheet is None:
        raise _err(422, "UNKNOWN_SHEET", "Выбранный лист не найден в файле.")
    header_row = body.header_row
    if header_row is None and not sheet.problem:
        header_row = prep.suggest_header_row(sheet)["row"]
    allowed = {r for r, c in sheet.rows if r <= prep.HEADER_SCAN_ROWS and c}
    if header_row is not None and header_row not in allowed:
        raise _err(422, "INVALID_HEADER_ROW",
                   f"Строка заголовка должна быть непустой строкой среди первых {prep.HEADER_SCAN_ROWS}.")
    inspection = prep.inspect_sheet(sheet, header_row)
    return {"batch_id": batch.id, "inspection": inspection, "auto_ready": _auto_ready(inspection)}


@router.post("/{batch_id}/validate")
def validate(db: DB, batch_id: int, body: ValidateBody) -> dict[str, Any]:
    settings = get_settings()
    batch = guided_batch(db, batch_id, body.session_key, lock=True)
    # Any new validation request invalidates the previous result first, whatever its outcome.
    batch.config_hash, batch.prep_config, batch.staged_rows = None, None, None
    batch.validation, batch.total_rows, batch.valid_rows = {}, 0, 0
    db.flush()
    wb = _read(batch, sheet=body.sheet, formulas=True)
    try:
        cfg = prep.check_config(body.model_dump(exclude={"session_key"}), wb)
    except prep.ConfigError as exc:
        db.commit()
        raise _err(422, "INVALID_CONFIGURATION", "Сопоставление не завершено или содержит ошибки.",
                   issues=exc.issues) from exc
    sheet = wb.get(cfg.sheet)
    prepared = prep.prepare_frame(sheet, cfg)
    if len(prepared.frame) > settings.max_upload_rows:
        db.commit()
        raise _err(413, "TOO_MANY_ROWS",
                   f"Слишком много строк: {len(prepared.frame)} (максимум {settings.max_upload_rows}).")
    result = validate_dataframe(prepared.frame, existing_loader=lambda rows: load_existing_state(db, rows),
                                row_numbers=prepared.row_numbers)
    for e in prepared.errors:
        result.errors.append(Issue(e["row"], e["column"], e["code"], e["message"]))
    result.errors.sort(key=lambda i: (i.row or 0))
    summary = prep.config_summary(sheet, cfg, prepared.ignored_columns)
    for w in prepared.warnings:
        result.warnings.append(Issue(w["row"], w["column"], w["code"], w["message"]))
    report = result.as_dict()
    batch.prep_config = cfg.canonical()
    batch.config_hash = prep.config_hash(batch.source_sha256, cfg)
    batch.total_rows, batch.valid_rows = result.total_rows, report["valid_rows"]
    batch.validation = report | {"config": summary}
    batch.staged_rows = rows_to_json(result.rows) if result.ok else None
    db.commit()
    return {"batch_id": batch.id, "filename": batch.filename, "expires_at": batch.expires_at.isoformat(),
            "config_hash": batch.config_hash, "config": summary, **report}
