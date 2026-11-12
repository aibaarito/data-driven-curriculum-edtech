"""guided import: stored source file and configuration-bound validation

Revision ID: c3e8f1a2b9d0
Revises: b7c1d2e3f4a5
Create Date: 2026-11-12 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c3e8f1a2b9d0"
down_revision: Union[str, Sequence[str], None] = "b7c1d2e3f4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Additive and nullable: existing batches are unaffected (they keep the one-step preview semantics).
    op.add_column("import_batches", sa.Column("source_file", sa.LargeBinary(), nullable=True))
    op.add_column("import_batches", sa.Column("source_sha256", sa.String(length=64), nullable=True))
    op.add_column("import_batches", sa.Column("session_key_hash", sa.String(length=64), nullable=True))
    op.add_column("import_batches", sa.Column("prep_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("import_batches", sa.Column("config_hash", sa.String(length=64), nullable=True))


def downgrade() -> None:
    for col in ("config_hash", "prep_config", "session_key_hash", "source_sha256", "source_file"):
        op.drop_column("import_batches", col)
