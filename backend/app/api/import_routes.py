"""Guided import endpoints: upload a source, inspect a region, validate an interpretation.

Lifecycle (one ImportBatch row per upload, status "preview" until committed, discarded or expired):
  POST /api/imports/sources              -> stores the file, returns sheets, CSV options, suggestions, session key
  POST /api/imports/{id}/inspect         -> preview, columns, flags and suggestions for a region (read-only)
  POST /api/imports/{id}/validate        -> applies the layout, mapping and rules; validates; stages the result
  POST /api/imports/{id}/commit          -> (routes.py) commits only if config_hash matches the last validation
Nothing here writes to the analytical tables or datasets. Cell contents are never logged.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import undefer

from app import models as m
from app.api.deps import DB
from app.config import get_settings
from app.services import capabilities as caps_mod
from app.services import import_layouts as lay
from app.services import import_prep as prep
from app.services.import_store import load_existing_state
from app.services.importer import MAX_LISTED_ISSUES, FileFormatError, Issue, rows_to_json, validate_dataframe
from app.services.previews import expiry_from_now, purge_expired
from app.services.settings_store import get_analysis_settings

router = APIRouter(prefix="/api/imports")
log = logging.getLogger("ddc.import")


class CsvOptions(BaseModel):
    encoding: str = Field("auto", max_length=16)
    delimiter: str = Field("auto", max_length=4)


class RegionBody(BaseModel):
    session_key: str = Field(..., max_length=128)
    sheet: str = Field(..., max_length=255)
    header_row: int | None = Field(None, ge=1, le=1_048_576)
    header_rows: int = Field(1, ge=1, le=2)
    first_col: int | None = Field(None, ge=0, le=prep.MAX_COLUMNS)
    last_col: int | None = Field(None, ge=0, le=prep.MAX_COLUMNS)
    last_row: int | None = Field(None, ge=1, le=1_048_576)
    exclude: list[str] = Field(default_factory=list, max_length=5)
    csv: CsvOptions = Field(default_factory=CsvOptions)


class ValidateBody(RegionBody):
    header_row: int = Field(..., ge=1, le=1_048_576)
    layout: str = Field("long", max_length=16)
    fields: dict[str, dict[str, Any]] = Field(default_factory=dict, max_length=64)
    result_columns: list[dict[str, Any]] = Field(default_factory=list, max_length=prep.MAX_COLUMNS)
    roles: dict[str, str] = Field(default_factory=dict, max_length=prep.MAX_COLUMNS)
    metric: dict[str, Any] = Field(default_factory=dict, max_length=8)
    types: dict[str, str] = Field(default_factory=dict, max_length=prep.MAX_COLUMNS)
    dataset_name: str | None = Field(None, max_length=255)
    rules: dict[str, Any] = Field(default_factory=dict, max_length=16)
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


def _read(batch: m.ImportBatch, sheet: str | None = None, formulas: bool = False,
          csv: CsvOptions | None = None) -> prep.Workbook:
    csv = csv or CsvOptions()
    try:
        return prep.read_workbook(batch.source_file, batch.filename, max_data_rows=get_settings().max_upload_rows,
                                  sheet_name=sheet, detect_formulas=formulas, encoding=csv.encoding,
                                  delimiter=csv.delimiter)
    except FileFormatError as exc:
        raise _err(422, "UNREADABLE_FILE", str(exc)) from exc


def _auto_ready(inspection: dict[str, Any] | None) -> bool:
    """True when sheet, header row and every required field are unambiguous (the standard template)."""
    if not inspection or inspection.get("problem") or inspection.get("header_row") is None:
        return False
    if inspection["header_suggestion"].get("confidence") != "high":
        return False
    if (inspection.get("layout_suggestion") or {}).get("layout") != "long":
        return False
    if inspection["flags"] or any(n["severity"] == "error" for n in inspection["notices"]):
        return False
    sugg = inspection["suggestions"]
    return all(f in sugg["suggested"] and f not in sugg["ambiguous"] for f in prep.REQUIRED_COLUMNS)


def _selection(body: RegionBody, sheet: prep.Sheet, header_row: int | None) -> prep.Selection | None:
    if header_row is None:
        return None
    raw = {"header_row": header_row, "header_rows": body.header_rows, "first_col": body.first_col,
           "last_col": body.last_col, "last_row": body.last_row, "exclude": body.exclude}
    try:
        return lay.selection_from(raw, sheet)
    except lay.ConfigError as exc:
        raise _err(422, exc.issues[0]["code"], exc.issues[0]["message"]) from exc


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
        suggestion = prep.suggest_sheet(wb.sheets)
        inspection = None
        if suggestion["name"] is not None:
            full = wb if wb.kind == "csv" else prep.read_workbook(content, filename, sheet_name=suggestion["name"],
                                                                   max_data_rows=settings.max_upload_rows)
            sheet = full.get(suggestion["name"])
            hdr = prep.suggest_header_row(sheet)
            sel = prep.Selection(hdr["row"], hdr.get("header_rows", 1)) if hdr["row"] else None
            inspection = prep.inspect_sheet(sheet, sel)
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
    log.info("Import source stored: batch=%s kind=%s sheets=%s bytes=%s", batch.id, wb.kind, len(wb.sheets),
             len(content))
    return {"batch_id": batch.id, "session_key": key, "filename": filename, "kind": wb.kind,
            "expires_at": batch.expires_at.isoformat(), "sheets": [prep.sheet_summary(s) for s in wb.sheets],
            "csv_info": wb.csv_info, "sheet_suggestion": suggestion, "inspection": inspection,
            "auto_ready": _auto_ready(inspection), "fields": prep.field_catalogue(), "catalog": _catalog(),
            "limits": _limits()}


def _catalog() -> dict[str, Any]:
    return {"layouts": [{"value": k, "label": v} for k, v in lay.LAYOUT_LABEL.items()],
            "aggregate_roles": [{"value": k, "label": v[0]} for k, v in prep.AGG_ROLES.items()],
            "types": [{"value": t, "label": prep.TYPE_LABEL[t]} for t in prep.GENERAL_TYPES],
            "flags": [{"value": k, "label": v} for k, v in prep.FLAG_LABEL.items()],
            "date_formats": list(lay.rules_mod.DATE_FORMATS),
            "encodings": list(prep.ENCODINGS), "delimiters": [{"value": k, "label": prep.DELIMITER_LABEL.get(k, "авто")}
                                                              for k in prep.DELIMITERS]}


def _limits() -> dict[str, Any]:
    s = get_settings()
    return {"max_upload_mb": s.max_upload_mb, "max_rows": s.max_upload_rows, "max_columns": prep.MAX_COLUMNS,
            "max_sheets": prep.MAX_SHEETS, "header_scan_rows": prep.HEADER_SCAN_ROWS,
            "preview_ttl_minutes": s.preview_ttl_minutes, "max_dataset_rows": lay.MAX_DATASET_ROWS,
            "max_records": s.max_upload_rows}


@router.post("/{batch_id}/inspect")
def inspect(db: DB, batch_id: int, body: RegionBody) -> dict[str, Any]:
    batch = guided_batch(db, batch_id, body.session_key)
    wb = _read(batch, sheet=body.sheet, csv=body.csv)
    sheet = wb.get(body.sheet)
    if sheet is None:
        raise _err(422, "UNKNOWN_SHEET", "Выбранный лист не найден в файле.")
    header_row = body.header_row
    header_rows = body.header_rows
    if header_row is None and not sheet.problem:
        hdr = prep.suggest_header_row(sheet)
        header_row = hdr["row"]
        header_rows = hdr.get("header_rows", 1)
        body = body.model_copy(update={"header_rows": header_rows})
    sel = _selection(body, sheet, header_row) if not sheet.problem else None
    inspection = prep.inspect_sheet(sheet, sel)
    return {"batch_id": batch.id, "inspection": inspection, "csv_info": wb.csv_info,
            "auto_ready": _auto_ready(inspection)}


# --------------------------------------------------------------------------- validation


def _enrich(issues: list[Issue], sheet: prep.Sheet, prepared: lay.Prepared, cfg: lay.PrepConfig) -> list[Issue]:
    """Add worksheet, source column, bounded value preview and a suggestion; collapse identical issues."""
    by_row = {r: cells for r, cells in sheet.rows}
    cols = {c.letter: c for c in prep.header_columns(sheet, cfg.sel)}
    shared = {f: s["value"] for f, s in cfg.fields.items() if s["source"] == "value"}
    merged: dict[tuple, Issue] = {}
    for i in issues:
        i.sheet = sheet.name if sheet.name != "CSV" else None
        if i.source_column is None and i.column in prepared.field_columns:
            i.source_column = prepared.field_columns[i.column]
        if i.value is None and i.row is not None and i.column:
            if i.column in shared:
                i.value = lay.preview_value(shared[i.column], i.column) + " (общее значение)"
            elif i.source_column in cols:
                cells = by_row.get(i.row, [])
                idx = cols[i.source_column].index
                i.value = lay.preview_value(cells[idx] if idx < len(cells) else "", i.column)
        if i.suggestion is None:
            i.suggestion = lay.SUGGESTIONS.get(i.code)
        i.stage = i.stage or ("database" if i.code == "CONFLICT_WITH_DB" else
                              "cross_record" if i.code in ("DUPLICATE_ROW", "MIXED_GRANULARITY", "CONFLICT",
                                                           "CYCLIC_PREREQUISITE", "UNKNOWN_PREREQUISITE",
                                                           "INVALID_PREREQUISITE") else "record")
        key = (i.row, i.column, i.code, i.message, i.source_column if i.column in ("score", "max_score") else None)
        if key in merged:
            merged[key].count = (merged[key].count or 1) + 1
        else:
            merged[key] = i
    return list(merged.values())


def _issue_from(d: dict[str, Any]) -> Issue:
    return Issue(d.get("row"), d.get("column"), d["code"], d["message"], source_column=d.get("source_column"),
                 value=d.get("value"), suggestion=d.get("suggestion"), stage=d.get("stage"))


def _validate_assessment(db, sheet, cfg, prepared) -> tuple[dict[str, Any], list | None]:
    settings = get_settings()
    frame = prepared.frame
    if len(frame) > settings.max_upload_rows:
        raise _err(413, "TOO_MANY_ROWS", f"Слишком много записей: {len(frame)} (максимум {settings.max_upload_rows}).")
    result = validate_dataframe(frame, existing_loader=lambda rows: load_existing_state(db, rows),
                                row_numbers=prepared.row_numbers,
                                source_columns=prepared.source_columns if cfg.layout == "wide" else None)
    if result.total_rows == 0 and prepared.errors:
        # Every record failed a transformation rule: the validator saw nothing, but records were checked.
        result.errors = [e for e in result.errors if e.code != "EMPTY_FILE"]
        result.records_validated = True
    result.errors = _enrich(result.errors + [_issue_from(e) for e in prepared.errors], sheet, prepared, cfg)
    result.errors.sort(key=lambda i: (i.row or 0, i.source_column or ""))
    result.warnings = _enrich(result.warnings + [_issue_from(w) for w in prepared.warnings], sheet, prepared, cfg)
    report = result.as_dict()
    transform_invalid = prepared.counts.get("transform_errors", 0)
    per_record_valid = len(result.rows)
    already = sum(1 for r in result.rows if r.get("_skip"))
    records = result.total_rows + transform_invalid
    report["counts"] = prepared.counts | {
        "records": records, "valid_records": per_record_valid,
        "invalid_records": max(0, result.total_rows - per_record_valid) + transform_invalid,
        "cross_record_errors": sum(1 for e in result.errors if e.stage in ("cross_record", "database")),
        "existing_duplicates": already,
        "eligible": (per_record_valid - already) if report["ok"] else 0,
    }
    report["total_rows"] = records
    caps_df = caps_mod.frame_from_staged(result.rows)
    report["capabilities"] = caps_mod.assessment_capabilities(
        caps_df, get_analysis_settings(db),
        has_hours=any(r.get("teaching_hours") is not None for r in result.rows),
        has_prereqs=any(r.get("topic_prerequisites") for r in result.rows))
    report["capabilities_scope"] = "file"
    return report, (rows_to_json(result.rows) if result.ok else None)


def _validate_dataset(db, batch, sheet, cfg, prepared, config_hash: str) -> tuple[dict[str, Any], dict | None]:
    ds = prepared.dataset
    errors = _enrich([_issue_from(e) for e in prepared.errors], sheet, prepared, cfg)
    warnings = [_issue_from(w) for w in prepared.warnings]
    dup = db.scalar(select(m.Dataset.id).where(m.Dataset.source_sha256 == batch.source_sha256,
                                               m.Dataset.config_hash == config_hash))
    if dup:
        warnings.append(Issue(None, None, "DATASET_ALREADY_IMPORTED",
                              f"Этот файл с такими же настройками уже импортирован (набор данных № {dup}). "
                              "Повторный импорт создаст ещё один набор.", stage="database"))
    warnings = _enrich(warnings, sheet, prepared, cfg)
    n = len(ds["rows"])
    ok = not errors and n > 0
    if n == 0 and not errors:
        errors.append(Issue(None, None, "EMPTY_FILE", "В выбранном диапазоне нет строк с данными.", stage="structure",
                            suggestion="Проверьте строку заголовка, диапазон и исключённые строки."))
    preview = [{"row": d["source_row"], **({k: v for k, v in (d.get("data") or {}).items()} if ds["kind"] ==
                                             "aggregate" else {c["label"][:40]: d["values"][i]
                                                               for i, c in enumerate(ds["columns"][:12])})}
               for d in ds["rows"][:20]]
    records = prepared.counts.get("records", n)
    roles = {c.get("role") for c in ds["columns"] if c.get("role")}
    report = {
        "ok": ok, "total_rows": records, "valid_rows": n if ok else 0, "error_count": len(errors),
        "warning_count": len(warnings), "records_validated": True,
        "rows_with_errors": len({e.row for e in errors if e.row is not None}),
        "error_counts": dict(Counter(e.code for e in errors)), "warning_counts": dict(Counter(w.code for w in warnings)),
        "errors": [e.as_dict() for e in errors[:MAX_LISTED_ISSUES]],
        "warnings": [w.as_dict() for w in warnings[:MAX_LISTED_ISSUES]],
        "summary": {"dataset_kind": ds["kind"], "columns": len(ds["columns"]), "rows": n},
        "columns_found": [c["label"] for c in ds["columns"]], "preview": preview,
        "counts": prepared.counts | {"records": records, "valid_records": n, "invalid_records": records - n,
                                     "cross_record_errors": 0, "existing_duplicates": 0, "eligible": n if ok else 0},
        "capabilities": caps_mod.dataset_capabilities(ds["kind"], roles), "capabilities_scope": "dataset",
    }
    return report, ({"dataset": ds} if ok else None)


@router.post("/{batch_id}/validate")
def validate(db: DB, batch_id: int, body: ValidateBody) -> dict[str, Any]:
    settings = get_settings()
    batch = guided_batch(db, batch_id, body.session_key, lock=True)
    # Any new validation request invalidates the previous result first, whatever its outcome.
    batch.config_hash, batch.prep_config, batch.staged_rows = None, None, None
    batch.validation, batch.total_rows, batch.valid_rows = {}, 0, 0
    db.flush()
    wb = _read(batch, sheet=body.sheet, formulas=True, csv=body.csv)
    raw = body.model_dump(exclude={"session_key"})
    raw["csv"] = body.csv.model_dump()
    try:
        cfg = lay.check_config(raw, wb)
        sheet = wb.get(cfg.sheet)
        prepared = lay.prepare(sheet, cfg, max_records=settings.max_upload_rows)
    except lay.ConfigError as exc:
        db.commit()
        status = 413 if exc.issues and exc.issues[0]["code"] in ("TOO_MANY_RECORDS", "DATASET_TOO_LARGE") else 422
        raise _err(status, "INVALID_CONFIGURATION" if status == 422 else exc.issues[0]["code"],
                   "Настройки импорта не завершены или содержат ошибки." if status == 422 else exc.issues[0]["message"],
                   issues=exc.issues) from exc
    chash = lay.config_hash(batch.source_sha256, cfg)
    try:
        if prepared.kind == "assessment":
            report, staged = _validate_assessment(db, sheet, cfg, prepared)
        else:
            report, staged = _validate_dataset(db, batch, sheet, cfg, prepared, chash)
    except HTTPException:
        db.commit()  # keep the invalidation of the earlier result
        raise
    summary = lay.config_summary(sheet, cfg, prepared, prepared.kind)
    batch.prep_config = cfg.canonical()
    batch.config_hash = chash
    batch.total_rows, batch.valid_rows = report["total_rows"], report["valid_rows"]
    batch.validation = report | {"config": summary}
    batch.staged_rows = staged
    db.commit()
    return {"batch_id": batch.id, "filename": batch.filename, "expires_at": batch.expires_at.isoformat(),
            "config_hash": batch.config_hash, "config": summary, **report}
