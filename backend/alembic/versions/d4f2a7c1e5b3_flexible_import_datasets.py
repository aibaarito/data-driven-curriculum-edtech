"""flexible import: datasets for general/aggregate tables, source traceability of results

Revision ID: d4f2a7c1e5b3
Revises: c3e8f1a2b9d0
Create Date: 2026-11-12 20:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d4f2a7c1e5b3"
down_revision: Union[str, Sequence[str], None] = "c3e8f1a2b9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Additive only: existing results keep NULL source coordinates.
    op.add_column("assessment_results", sa.Column("source_row", sa.Integer(), nullable=True))
    op.add_column("assessment_results", sa.Column("source_column", sa.String(length=8), nullable=True))
    op.create_table(
        "datasets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("source_filename", sa.String(length=255), nullable=False),
        sa.Column("sheet", sa.String(length=255), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column("import_batch_id", sa.Integer(), sa.ForeignKey("import_batches.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("columns", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint("kind in ('general', 'aggregate')", name="ck_dataset_kind"),
    )
    op.create_index("ix_datasets_import_batch_id", "datasets", ["import_batch_id"])
    op.create_table(
        "dataset_rows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dataset_id", sa.Integer(), sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("row_index", sa.Integer(), nullable=False),
        sa.Column("source_row", sa.Integer(), nullable=False),
        sa.Column("values", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index("ix_dataset_rows_dataset_id", "dataset_rows", ["dataset_id"])


def downgrade() -> None:
    op.drop_index("ix_dataset_rows_dataset_id", table_name="dataset_rows")
    op.drop_table("dataset_rows")
    op.drop_index("ix_datasets_import_batch_id", table_name="datasets")
    op.drop_table("datasets")
    op.drop_column("assessment_results", "source_column")
    op.drop_column("assessment_results", "source_row")
