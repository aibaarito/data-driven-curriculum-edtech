from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, FiniteFloat, model_validator

from app.services.analytics import Filters


class FiltersBody(BaseModel):
    subject_id: int | None = Field(None, ge=1)
    grade: int | None = Field(None, ge=1, le=12)
    class_id: int | None = Field(None, ge=1)
    textbook_id: int | None = Field(None, ge=1)
    date_from: date | None = None
    date_to: date | None = None

    @model_validator(mode="after")
    def ordered_dates(self) -> "FiltersBody":
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("Дата начала периода позже даты окончания.")
        return self

    def to_filters(self) -> Filters:
        return Filters(self.subject_id, self.grade, self.class_id, self.textbook_id, self.date_from, self.date_to)


class TopicOverride(BaseModel):
    topic_id: int
    current_hours: float | None = Field(None, ge=0, le=1000)
    min_hours: float | None = Field(None, ge=0, le=1000)
    max_hours: float | None = Field(None, ge=0, le=1000)
    priority: int | None = Field(None, ge=1, le=3)
    locked: bool = False


class OptimizerRunBody(BaseModel):
    subject_id: int = Field(ge=1)
    grade: int = Field(ge=1, le=12)
    total_hours: float = Field(gt=0, le=10_000)
    target_mastery: float | None = Field(None, ge=0, le=100)
    max_change_pct: float | None = Field(None, ge=0, le=100)
    allow_policy_relaxation: bool = False
    topics: list[TopicOverride] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_topics(self) -> "OptimizerRunBody":
        ids = [t.topic_id for t in self.topics]
        if len(ids) != len(set(ids)):
            raise ValueError("Темы повторяются.")
        return self


class EvaluateBody(OptimizerRunBody):
    allocation: dict[int, FiniteFloat]


class DecisionBody(BaseModel):
    decision: Literal["accept", "reject"]
    note: str | None = Field(None, max_length=1000)
    # Accepting a recommendation whose evidence changed since it was computed requires an explicit acknowledgement.
    acknowledge_stale: bool = False


class ScenarioSaveBody(OptimizerRunBody):
    scenario_key: Literal["conservative", "balanced", "gap_focused"]
    fingerprint: str = Field(min_length=8, max_length=64, pattern=r"^[0-9a-f]+$")
    idempotency_key: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")


class PrerequisiteBody(BaseModel):
    topic_id: int = Field(ge=1)
    prerequisite_id: int = Field(ge=1)
    origin: Literal["expert", "suggested"] = "expert"


class EdgeReviewBody(BaseModel):
    decision: Literal["approve", "reject"]


class InterventionCreate(BaseModel):
    run_id: int = Field(ge=1)
    description: str = Field(min_length=3, max_length=2000)
    reviewer: str | None = Field(None, max_length=120)
    planned_on: date | None = None
    synthetic: bool = False


class InterventionTransition(BaseModel):
    status: Literal["implemented", "awaiting_outcome", "cancelled"]  # "evaluated" only via /evaluate
    implemented_on: date | None = None


class TopicUpdate(BaseModel):
    min_hours: float = Field(ge=0, le=1000)
    max_hours: float = Field(ge=0, le=1000)
    priority: int = Field(ge=1, le=3)


class ReportBody(BaseModel):
    filters: FiltersBody = Field(default_factory=FiltersBody)
    include_ai: bool = True
    title: str | None = Field(None, max_length=200)


class ResetBody(BaseModel):
    confirm: str


class CommitBody(BaseModel):
    """Guided imports must present the session key and the configuration hash returned by the last validation."""
    session_key: str | None = Field(None, max_length=128)
    config_hash: str | None = Field(None, max_length=64)
