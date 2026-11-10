"""Normalized relational schema. All tables are created by Alembic migrations only."""
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
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
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), index=True)
    prerequisite_id: Mapped[int] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), index=True)


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
    status: Mapped[str] = mapped_column(String(16), default="preview")  # preview|committed|discarded
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, default=0)
    inserted_rows: Mapped[int] = mapped_column(Integer, default=0)
    validation: Mapped[dict] = mapped_column(JSONB, default=dict)
    staged_rows: Mapped[list | None] = mapped_column(JSONB, nullable=True)


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
