"""decision intelligence: edge provenance, run evidence, interventions, audit events

Revision ID: b7c1d2e3f4a5
Revises: 6129d2b374e8
Create Date: 2026-11-11 19:00:00

Additive only: existing rows keep their meaning (prerequisites become origin='import', review_status='approved';
existing recommendation runs get NULL evidence provenance and are treated as "provenance unknown").
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7c1d2e3f4a5"
down_revision: Union[str, Sequence[str], None] = "6129d2b374e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("topic_prerequisites", sa.Column("origin", sa.String(16), nullable=False, server_default="import"))
    op.add_column("topic_prerequisites",
                  sa.Column("review_status", sa.String(16), nullable=False, server_default="approved"))
    op.add_column("topic_prerequisites", sa.Column("created_at", sa.DateTime(timezone=True),
                                                   server_default=sa.func.now(), nullable=True))
    op.create_check_constraint("ck_prereq_origin", "topic_prerequisites", "origin IN ('import','expert','suggested')")
    op.create_check_constraint("ck_prereq_review", "topic_prerequisites",
                               "review_status IN ('approved','pending','rejected')")

    op.add_column("recommendation_runs", sa.Column("scenario_key", sa.String(32), nullable=True))
    op.add_column("recommendation_runs", sa.Column("evidence_fingerprint", sa.String(64), nullable=True))
    op.add_column("recommendation_runs",
                  sa.Column("evidence_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("recommendation_runs", sa.Column("idempotency_key", sa.String(64), nullable=True))
    op.add_column("recommendation_runs", sa.Column("review_note", sa.Text(), nullable=True))
    op.create_index("ix_recommendation_runs_evidence_fingerprint", "recommendation_runs", ["evidence_fingerprint"])
    op.create_unique_constraint("uq_recommendation_runs_idempotency_key", "recommendation_runs", ["idempotency_key"])

    op.create_table(
        "interventions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("recommendation_runs.id", ondelete="RESTRICT"),
                  nullable=False, unique=True),
        sa.Column("subject_id", sa.Integer(), sa.ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("grade", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("reviewer", sa.String(120), nullable=True),
        sa.Column("planned_on", sa.Date(), nullable=True),
        sa.Column("implemented_on", sa.Date(), nullable=True),
        sa.Column("baseline", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evaluation", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("synthetic", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('planned','implemented','awaiting_outcome','evaluated','cancelled')",
                           name="ck_intervention_status"),
    )
    op.create_index("ix_intervention_scope", "interventions", ["subject_id", "grade"])
    op.create_index("ix_interventions_status", "interventions", ["status"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("from_status", sa.String(24), nullable=True),
        sa.Column("to_status", sa.String(24), nullable=True),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_audit_entity", "audit_events", ["entity_type", "entity_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_entity", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_interventions_status", table_name="interventions")
    op.drop_index("ix_intervention_scope", table_name="interventions")
    op.drop_table("interventions")
    op.drop_constraint("uq_recommendation_runs_idempotency_key", "recommendation_runs", type_="unique")
    op.drop_index("ix_recommendation_runs_evidence_fingerprint", table_name="recommendation_runs")
    for col in ("review_note", "idempotency_key", "evidence_snapshot", "evidence_fingerprint", "scenario_key"):
        op.drop_column("recommendation_runs", col)
    op.drop_constraint("ck_prereq_review", "topic_prerequisites", type_="check")
    op.drop_constraint("ck_prereq_origin", "topic_prerequisites", type_="check")
    for col in ("created_at", "review_status", "origin"):
        op.drop_column("topic_prerequisites", col)
