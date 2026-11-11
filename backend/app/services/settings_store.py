from typing import Any

from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app import models as m

KEY = "analysis"
# Statistical floor for textbook inference: with fewer independent classes per textbook the between-class
# variance cannot be estimated. Stored settings below this value are raised at load time (and reported).
MIN_CLASSES_FOR_INFERENCE = 3


class AnalysisSettings(BaseModel):
    difficult_threshold: float = Field(50, ge=0, le=100, description="Освоение ниже — тема трудная")
    watch_threshold: float = Field(65, ge=0, le=100, description="Освоение ниже — тема требует внимания")
    target_mastery: float = Field(75, ge=0, le=100, description="Целевой уровень освоения для оптимизатора")
    min_students_topic: int = Field(10, ge=1, le=10_000)
    min_students_textbook: int = Field(30, ge=2, le=100_000)
    min_classes_textbook: int = Field(MIN_CLASSES_FOR_INFERENCE, ge=MIN_CLASSES_FOR_INFERENCE, le=1000)
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
    values = {**AnalysisSettings().model_dump(), **row.value}
    # Installations created before the class-level floor may hold min_classes_textbook < 3: never keep
    # that unsafe value silently; the effective value is used and exposed via settings_notices().
    if int(values.get("min_classes_textbook", MIN_CLASSES_FOR_INFERENCE)) < MIN_CLASSES_FOR_INFERENCE:
        values["min_classes_textbook"] = MIN_CLASSES_FOR_INFERENCE
    return AnalysisSettings(**values)


def settings_notices(db: Session) -> list[str]:
    row = db.get(m.AppSetting, KEY)
    if row is not None and int(row.value.get("min_classes_textbook", MIN_CLASSES_FOR_INFERENCE)) < MIN_CLASSES_FOR_INFERENCE:
        return [f"Сохранённое значение «мин. классов на учебник» ({row.value['min_classes_textbook']}) ниже "
                f"статистического минимума; используется {MIN_CLASSES_FOR_INFERENCE}. Сохраните настройки, "
                "чтобы обновить значение."]
    return []


def save_analysis_settings(db: Session, s: AnalysisSettings) -> AnalysisSettings:
    row = db.get(m.AppSetting, KEY)
    data: dict[str, Any] = s.model_dump()
    if row is None:
        db.add(m.AppSetting(key=KEY, value=data))
    else:
        row.value = data
    db.commit()
    return s
