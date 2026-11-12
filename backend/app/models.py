"""Normalized relational schema. All tables are created by Alembic migrations only."""
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class School(Base):
    __tablename__ = "schools"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(255))


class Subject(Base):
    __tablename__ = "subjects"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(255))


class Textbook(Base):
    __tablename__ = "textbooks"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="RESTRICT"), index=True)


class SchoolClass(Base):
    __tablename__ = "classes"
    __table_args__ = (
        UniqueConstraint("school_id", "name", name="uq_class_school_name"),
        CheckConstraint("grade BETWEEN 1 AND 12", name="ck_class_grade"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    grade: Mapped[int] = mapped_column(Integer, index=True)


class ClassSubject(Base):
    """Which textbook a class uses for a subject (one textbook per class and subject)."""

    __tablename__ = "class_subjects"
    __table_args__ = (UniqueConstraint("class_id", "subject_id", name="uq_class_subject"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="RESTRICT"))
    textbook_id: Mapped[int | None] = mapped_column(
        ForeignKey("textbooks.id", ondelete="SET NULL"), nullable=True, index=True
    )


class Student(Base):
    __tablename__ = "students"
    __table_args__ = (UniqueConstraint("school_id", "external_id", name="uq_student_school_ext"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id", ondelete="CASCADE"), index=True)
    external_id: Mapped[str] = mapped_column(String(64))  # anonymous identifier only
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), index=True)


class Topic(Base):
    __tablename__ = "topics"
    __table_args__ = (
        CheckConstraint("min_hours >= 0", name="ck_topic_min_nonneg"),
        CheckConstraint("max_hours >= min_hours", name="ck_topic_max_ge_min"),
        CheckConstraint("priority BETWEEN 1 AND 3", name="ck_topic_priority"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="RESTRICT"), index=True)
    grade: Mapped[int] = mapped_column(Integer, index=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    min_hours: Mapped[float] = mapped_column(Float, default=0)
    max_hours: Mapped[float] = mapped_column(Float, default=0)
    priority: Mapped[int] = mapped_column(Integer, default=2)


class TopicPrerequisite(Base):
    __tablename__ = "topic_prerequisites"
    __table_args__ = (
        UniqueConstraint("topic_id", "prerequisite_id", name="uq_topic_prereq"),
        CheckConstraint("topic_id <> prerequisite_id", name="ck_prereq_not_self"),
        CheckConstraint("origin IN ('import','expert','suggested')", name="ck_prereq_origin"),
        CheckConstraint("review_status IN ('approved','pending','rejected')", name="ck_prereq_review"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), index=True)
    prerequisite_id: Mapped[int] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), index=True)
    # Provenance of the relationship. Only approved edges are used by diagnostics and the optimizer;
    # suggested edges (e.g. from an assistant) stay pending until an expert approves them.
    origin: Mapped[str] = mapped_column(String(16), default="import", server_default="import")
    review_status: Mapped[str] = mapped_column(String(16), default="approved", server_default="approved")
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                        nullable=True)


class ClassTopicHours(Base):
    """Teaching hours actually allocated to a topic in a class (from imported data)."""

    __tablename__ = "class_topic_hours"
    __table_args__ = (
        UniqueConstraint("class_id", "topic_id", name="uq_class_topic_hours"),
        CheckConstraint("hours >= 0", name="ck_hours_nonneg"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), index=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), index=True)
    hours: Mapped[float] = mapped_column(Float)


class Assessment(Base):
    __tablename__ = "assessments"
    __table_args__ = (CheckConstraint("kind IN ('pre','post','current')", name="ck_assessment_kind"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="RESTRICT"), index=True)
    assessment_date: Mapped[date] = mapped_column(Date, index=True)
    kind: Mapped[str] = mapped_column(String(16))
    comparison_group: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)


class ImportBatch(Base):
    __tablename__ = "import_batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="preview")  # preview|committed|discarded|expired
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, default=0)
    inserted_rows: Mapped[int] = mapped_column(Integer, default=0)
    validation: Mapped[dict] = mapped_column(JSONB, default=dict)
    # none_as_null: clearing staged rows must store SQL NULL (not JSON null) so purges are visible to IS NULL checks
    staged_rows: Mapped[list | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    # Previews expire; expired/failed previews have their staged rows purged (see services/previews.py).
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    # Guided import (worksheet/header/mapping). The uploaded file is kept only while the preview is open and is
    # dropped on commit, discard and expiry. Validation is bound to config_hash = sha256(file + configuration).
    source_file: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True, deferred=True)
    source_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    session_key_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prep_config: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    config_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AssessmentResult(Base):
    """Item-level (or topic-level when item_id='_total') score of one student."""

    __tablename__ = "assessment_results"
    __table_args__ = (
        UniqueConstraint("student_id", "assessment_id", "topic_id", "item_id", name="uq_result"),
        CheckConstraint("max_score > 0", name="ck_result_max_positive"),
        CheckConstraint("score >= 0", name="ck_result_score_nonneg"),
        CheckConstraint("score <= max_score", name="ck_result_score_le_max"),
        Index("ix_result_assessment_topic", "assessment_id", "topic_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessments.id", ondelete="CASCADE"), index=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[str] = mapped_column(String(64), default="_total")
    score: Mapped[float] = mapped_column(Float)
    max_score: Mapped[float] = mapped_column(Float)
    import_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True, index=True
    )


class RecommendationRun(Base):
    __tablename__ = "recommendation_runs"
    __table_args__ = (
        CheckConstraint("status IN ('proposed','accepted','rejected')", name="ck_run_status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"), index=True)
    grade: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="proposed")
    params: Mapped[dict] = mapped_column(JSONB)
    result: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Decision-intelligence provenance (nullable: runs created before migration b7c1d2e3f4a5 have none).
    scenario_key: Mapped[str | None] = mapped_column(String(32), nullable=True)
    evidence_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    evidence_snapshot: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    allocations: Mapped[list["CurriculumAllocation"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class CurriculumAllocation(Base):
    """Hours per topic of an accepted recommendation run (the adopted plan)."""

    __tablename__ = "curriculum_allocations"
    __table_args__ = (
        UniqueConstraint("run_id", "topic_id", name="uq_alloc_run_topic"),
        CheckConstraint("hours >= 0", name="ck_alloc_nonneg"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("recommendation_runs.id", ondelete="CASCADE"), index=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"))
    hours: Mapped[float] = mapped_column(Float)
    run: Mapped[RecommendationRun] = relationship(back_populates="allocations")


class GeneratedReport(Base):
    __tablename__ = "generated_reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    filters: Mapped[dict] = mapped_column(JSONB)
    content: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB)


INTERVENTION_STATUSES = ("planned", "implemented", "awaiting_outcome", "evaluated", "cancelled")


class Intervention(Base):
    """A planned/implemented curriculum change derived from exactly one accepted recommendation run."""

    __tablename__ = "interventions"
    __table_args__ = (
        CheckConstraint("status IN ('planned','implemented','awaiting_outcome','evaluated','cancelled')",
                        name="ck_intervention_status"),
        Index("ix_intervention_scope", "subject_id", "grade"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    # RESTRICT: an intervention keeps its recommendation (and frozen evidence) alive.
    run_id: Mapped[int] = mapped_column(ForeignKey("recommendation_runs.id", ondelete="RESTRICT"), unique=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"))
    grade: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="planned", index=True)
    description: Mapped[str] = mapped_column(Text)
    reviewer: Mapped[str | None] = mapped_column(String(120), nullable=True)
    planned_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    implemented_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    baseline: Mapped[dict] = mapped_column(JSONB)  # frozen evidence snapshot at creation
    evaluation: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now())


class AuditEvent(Base):
    """Append-only record of human decisions and lifecycle transitions (no personal data, no free-form payloads)."""

    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_entity", "entity_type", "entity_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(32))
    from_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
