"""Datasets (general and aggregate tables) and the analysis-capability assessment of stored data."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from app import models as m
from app.api.deps import DB, FiltersDep
from app.services import analytics as an
from app.services import capabilities as caps_mod
from app.services import datasets as dsvc
from app.services import import_prep as prep
from app.services.settings_store import get_analysis_settings

router = APIRouter(prefix="/api")


class ColumnTypesBody(BaseModel):
    types: dict[str, str] = Field(..., max_length=prep.MAX_COLUMNS)


def _get(db, dataset_id: int) -> m.Dataset:
    ds = db.get(m.Dataset, dataset_id)
    if ds is None:
        raise HTTPException(404, "Набор данных не найден.")
    return ds


def _rows(db, ds: m.Dataset) -> list[m.DatasetRow]:
    return list(db.scalars(select(m.DatasetRow).where(m.DatasetRow.dataset_id == ds.id)
                           .order_by(m.DatasetRow.row_index)))


def _meta(ds: m.Dataset) -> dict[str, Any]:
    return {"id": ds.id, "kind": ds.kind, "name": ds.name, "source_filename": ds.source_filename, "sheet": ds.sheet,
            "created_at": ds.created_at.isoformat(), "row_count": ds.row_count, "columns": ds.columns,
            "metric": (ds.meta or {}).get("metric"), "import_batch_id": ds.import_batch_id}


@router.get("/datasets")
def list_datasets(db: DB) -> list[dict[str, Any]]:
    return [_meta(d) for d in db.scalars(select(m.Dataset).order_by(m.Dataset.created_at.desc()).limit(100))]


@router.get("/datasets/{dataset_id}")
def get_dataset(db: DB, dataset_id: int) -> dict[str, Any]:
    ds = _get(db, dataset_id)
    rows = _rows(db, ds)
    out = _meta(ds) | {"profile": dsvc.profile(ds.columns, [r.values for r in rows]),
                       "capabilities": caps_mod.dataset_capabilities(ds.kind, {c.get("role") for c in ds.columns})}
    if ds.kind == "aggregate":
        out["aggregate"] = dsvc.aggregate_summary(ds.columns, [r.data or {} for r in rows], out["metric"] or {})
    return out


@router.put("/datasets/{dataset_id}/columns")
def update_column_types(db: DB, dataset_id: int, body: ColumnTypesBody) -> dict[str, Any]:
    """Change confirmed column types of a general dataset. Stored values are not modified."""
    ds = _get(db, dataset_id)
    if ds.kind != "general":
        raise HTTPException(409, "Типы столбцов сводной таблицы задаются при импорте.")
    ids = {c["id"] for c in ds.columns}
    if not set(body.types) <= ids or not set(body.types.values()) <= set(prep.GENERAL_TYPES):
        raise HTTPException(422, "Неизвестный столбец или тип.")
    ds.columns = [c | ({"type": body.types[c["id"]]} if c["id"] in body.types else {}) for c in ds.columns]
    db.commit()
    return get_dataset(db, dataset_id)


@router.get("/datasets/{dataset_id}/rows")
def dataset_rows(db: DB, dataset_id: int, q: str | None = Query(None, max_length=200),
                 sort: str | None = Query(None, max_length=16), direction: str = Query("asc", pattern="^(asc|desc)$"),
                 filter_col: str | None = Query(None, max_length=16),
                 filter_value: str | None = Query(None, max_length=200),
                 page: int = Query(0, ge=0, le=100_000)) -> dict[str, Any]:
    ds = _get(db, dataset_id)
    rows = [(r.source_row, r.values) for r in _rows(db, ds)]
    return dsvc.query_rows(ds.columns, rows, q, sort, direction, filter_col, filter_value, page)


@router.get("/datasets/{dataset_id}/export.csv")
def export_dataset(db: DB, dataset_id: int) -> Response:
    ds = _get(db, dataset_id)
    body = dsvc.export_csv(ds.columns, [(r.source_row, r.values) for r in _rows(db, ds)])
    return Response(body, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="dataset_{ds.id}.csv"'})


@router.delete("/datasets/{dataset_id}")
def delete_dataset(db: DB, dataset_id: int) -> dict[str, Any]:
    ds = _get(db, dataset_id)
    db.execute(delete(m.DatasetRow).where(m.DatasetRow.dataset_id == ds.id))
    db.delete(ds)
    db.commit()
    return {"deleted": dataset_id}


@router.get("/analytics/capabilities")
def analysis_capabilities(db: DB, f: FiltersDep) -> dict[str, Any]:
    """Which analyses the stored assessment data supports for the current filters, and why others are not."""
    df = an.load_results(db, f)
    class_ids = df["class_id"].unique().tolist() if not df.empty else []
    topic_ids = df["topic_id"].unique().tolist() if not df.empty else []
    has_hours = bool(class_ids) and db.scalar(select(func.count()).select_from(m.ClassTopicHours).where(
        m.ClassTopicHours.class_id.in_(class_ids))) > 0
    has_prereqs = bool(topic_ids) and db.scalar(select(func.count()).select_from(m.TopicPrerequisite).where(
        m.TopicPrerequisite.topic_id.in_(topic_ids))) > 0
    caps = caps_mod.assessment_capabilities(caps_mod.frame_from_results(df), get_analysis_settings(db),
                                            has_hours=has_hours, has_prereqs=has_prereqs)
    datasets = db.scalar(select(func.count()).select_from(m.Dataset))
    return {"capabilities": caps, "filters": f.as_dict(), "datasets": datasets}
