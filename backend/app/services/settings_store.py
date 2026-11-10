from typing import Any

from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app import models as m

KEY = "analysis"


class AnalysisSettings(BaseModel):
    difficult_threshold: float = Field(50, ge=0, le=100, description="Освоение ниже — тема трудная")
    watch_threshold: float = Field(65, ge=0, le=100, description="Освоение ниже — тема требует внимания")
    target_mastery: float = Field(75, ge=0, le=100, description="Целевой уровень освоения для оптимизатора")
    min_students_topic: int = Field(10, ge=1, le=10_000)
    min_students_textbook: int = Field(30, ge=2, le=100_000)
    min_classes_textbook: int = Field(2, ge=1, le=1000)
    max_change_pct: float = Field(30, ge=0, le=100, description="Макс. изменение часов темы за один шаг, %")

    @model_validator(mode="after")
    def _order(self) -> "AnalysisSettings":
        if self.difficult_threshold > self.watch_threshold:
            raise ValueError("Порог «трудная тема» не может быть выше порога «требует внимания».")
        return self


def get_analysis_settings(db: Session) -> AnalysisSettings:
    row = db.get(m.AppSetting, KEY)
    if row is None:
        return AnalysisSettings()
    return AnalysisSettings(**{**AnalysisSettings().model_dump(), **row.value})


def save_analysis_settings(db: Session, s: AnalysisSettings) -> AnalysisSettings:
    row = db.get(m.AppSetting, KEY)
    data: dict[str, Any] = s.model_dump()
    if row is None:
        db.add(m.AppSetting(key=KEY, value=data))
    else:
        row.value = data
    db.commit()
    return s
