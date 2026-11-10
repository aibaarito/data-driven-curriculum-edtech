from datetime import date
from typing import Annotated

from fastapi import Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.analytics import Filters

DB = Annotated[Session, Depends(get_db)]


def get_filters(
    subject_id: Annotated[int | None, Query(ge=1)] = None,
    grade: Annotated[int | None, Query(ge=1, le=12)] = None,
    class_id: Annotated[int | None, Query(ge=1)] = None,
    textbook_id: Annotated[int | None, Query(ge=1)] = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> Filters:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "Дата начала периода позже даты окончания.")
    return Filters(subject_id, grade, class_id, textbook_id, date_from, date_to)


FiltersDep = Annotated[Filters, Depends(get_filters)]
