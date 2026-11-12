"""Which analyses the available data supports — derived from the requirements of the actual analytical code.

Requirements (see analytics.py, textbooks.py, optimizer.py, context.py):
* overview / mastery    — outcome results (kind post|current) with max_score > 0.
* topic analysis        — outcome results linked to topics; a topic status needs >= min_students_topic students.
* learning gains        — the same student and topic in a 'pre' and a 'post' assessment of one comparison group;
                          a tested gain needs >= min_students_topic pairs (Bonferroni across topics).
* trends                — outcome results on at least two different dates.
* textbook comparison   — textbooks assigned per class and subject; >= 2 textbooks in the same subject and grade,
                          each with >= min_classes_textbook classes, sharing common outcome items.
* hours optimizer       — teaching hours per class and topic for a subject and grade (bounds per topic).
* curriculum map        — topics; prerequisite links make the map informative.
Nothing is relaxed here: a feature is "available" only when the existing safeguards can actually produce a result.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from app.services.settings_store import AnalysisSettings

OUTCOME = ("post", "current")


def _cap(key: str, title: str, available: bool, level: str, missing: list[str] | None = None,
         limitations: list[str] | None = None, link: str | None = None, partial: bool = False) -> dict[str, Any]:
    return {"key": key, "title": title, "available": available, "partial": partial and available, "level": level,
            "missing": missing or [], "limitations": limitations or [], "link": link if available else None}


def assessment_capabilities(df: pd.DataFrame, s: AnalysisSettings, *, has_hours: bool, has_prereqs: bool
                            ) -> list[dict[str, Any]]:
    """``df`` columns: student, class, grade, subject, topic, kind, group, textbook, item, max_score, date."""
    caps: list[dict[str, Any]] = []
    if df.empty:
        msg = "Нет проверенных результатов оценивания."
        for key, title, level in (("overview", "Обзор и средний уровень освоения", "student"),
                                  ("topics", "Анализ тем", "topic"), ("gains", "Прирост «входная → итоговая»", "student"),
                                  ("trends", "Динамика по датам", "topic"),
                                  ("textbooks", "Сравнение учебников", "class"),
                                  ("optimizer", "Оптимизация часов", "topic"),
                                  ("curriculum", "Карта программы", "topic")):
            caps.append(_cap(key, title, False, level, [msg]))
        return caps
    out = df[df["kind"].isin(OUTCOME) & (df["max_score"] > 0)]
    has_outcome = not out.empty
    no_outcome = "Нужны итоговые или текущие оценивания (тип post или current); сейчас есть только входная " \
                 "диагностика (pre)."
    caps.append(_cap("overview", "Обзор и средний уровень освоения", has_outcome, "student",
                     [] if has_outcome else [no_outcome], link="/"))

    limitations = []
    if has_outcome:
        per_topic = out.groupby("topic")["student"].nunique()
        reliable = int((per_topic >= s.min_students_topic).sum())
        if reliable < len(per_topic):
            limitations.append(f"Статус «трудная / требует внимания» определяется только для тем, где не меньше "
                               f"{s.min_students_topic} учеников ({reliable} из {len(per_topic)} тем); для "
                               "остальных — «мало данных».")
    caps.append(_cap("topics", "Анализ тем", has_outcome, "topic", [] if has_outcome else [no_outcome],
                     limitations, "/topics", partial=bool(limitations)))

    pp = df[df["kind"].isin(("pre", "post"))]
    gains_missing, gains_lim = [], []
    pairs_ok = False
    if pp.empty or not (pp["kind"] == "pre").any() or not (pp["kind"] == "post").any():
        gains_missing.append("Нужны входная (pre) и итоговая (post) работы по одним и тем же темам.")
    elif pp["group"].isna().all():
        gains_missing.append("Укажите группу сравнения (comparison_group), связывающую входную и итоговую работы.")
    else:
        g = pp[pp["group"].notna()]
        pre = g[g["kind"] == "pre"][["group", "student", "topic"]].drop_duplicates()
        post = g[g["kind"] == "post"][["group", "student", "topic"]].drop_duplicates()
        paired = pre.merge(post, on=["group", "student", "topic"])
        if paired.empty:
            gains_missing.append("Нет учеников, у которых есть и входная, и итоговая работа по одной теме в одной "
                                 "группе сравнения.")
        else:
            per = paired.groupby("topic").size()
            ok = int((per >= max(2, s.min_students_topic)).sum())
            pairs_ok = ok > 0
            if not pairs_ok:
                gains_missing.append(f"Для проверки прироста нужно не меньше {max(2, s.min_students_topic)} пар "
                                     "«входная–итоговая» на тему.")
            elif ok < len(per):
                gains_lim.append(f"Прирост проверяется для {ok} из {len(per)} тем; у остальных слишком мало пар.")
    caps.append(_cap("gains", "Прирост «входная → итоговая»", pairs_ok, "student", gains_missing, gains_lim,
                     "/topics", partial=bool(gains_lim)))

    dates = out["date"].nunique() if has_outcome else 0
    caps.append(_cap("trends", "Динамика по датам", dates >= 2, "topic",
                     [] if dates >= 2 else ["Нужны итоговые или текущие результаты как минимум за две даты."],
                     link="/topics"))

    tb_missing, tb_lim = [], []
    tb = df[df["textbook"].notna()]
    tb_ok = False
    if tb.empty:
        tb_missing.append("Для сравнения учебников укажите столбец с учебником.")
    else:
        groups = tb.groupby(["subject", "grade"])
        best = 0
        for _, grp in groups:
            classes = grp.groupby("textbook")["class"].nunique()
            enough = classes[classes >= s.min_classes_textbook]
            best = max(best, len(enough))
        if tb["textbook"].nunique() < 2:
            tb_missing.append("Нужны как минимум два разных учебника в одном предмете и параллели.")
        elif best < 2:
            tb_missing.append(f"Для статистического сравнения у каждого учебника должно быть не меньше "
                              f"{s.min_classes_textbook} классов одного предмета и параллели.")
        else:
            tb_ok = True
            tb_lim.append("Сравнение описательное и по классам; общие итоговые задания и другие ограничения "
                          "проверяются на странице сравнения.")
    caps.append(_cap("textbooks", "Сравнение учебников", tb_ok, "class", tb_missing, tb_lim, "/textbooks"))

    caps.append(_cap("optimizer", "Оптимизация часов", has_hours and has_outcome, "topic",
                     ([] if has_hours else ["Нужны часы, выделенные на темы в классах (teaching_hours)."])
                     + ([] if has_outcome else [no_outcome]),
                     ["Общее число часов и ограничения задаются в оптимизаторе."] if has_hours else [], "/optimizer"))
    caps.append(_cap("curriculum", "Карта программы", True, "topic", [],
                     [] if has_prereqs else ["Связи между темами (topic_prerequisites) не указаны — карта покажет "
                                             "темы без зависимостей."], "/curriculum", partial=not has_prereqs))
    return caps


def frame_from_staged(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["student", "class", "grade", "subject", "topic", "kind", "group", "textbook",
                                     "item", "max_score", "date"])
    return pd.DataFrame({
        "student": [(r["school"], r["student_id"]) for r in rows],
        "class": [(r["school"], r["class"]) for r in rows],
        "grade": [r["grade"] for r in rows], "subject": [r["subject"] for r in rows],
        "topic": [r["topic_id"] for r in rows], "kind": [r["assessment_type"] for r in rows],
        "group": [r.get("comparison_group") for r in rows], "textbook": [r.get("textbook_id") for r in rows],
        "item": [r.get("item_id") for r in rows], "max_score": [float(r["max_score"]) for r in rows],
        "date": [r["assessment_date"] for r in rows],
    })


def frame_from_results(df: pd.DataFrame) -> pd.DataFrame:
    """Adapter from analytics.load_results() columns."""
    if df.empty:
        return frame_from_staged([])
    return pd.DataFrame({"student": df["student_id"], "class": df["class_id"], "grade": df["grade"],
                         "subject": df["subject_id"], "topic": df["topic_id"], "kind": df["kind"],
                         "group": df["comparison_group"], "textbook": df["textbook_id"], "item": df["item_id"],
                         "max_score": df["max_score"], "date": df["assessment_date"]})


def dataset_capabilities(kind: str, roles: set[str] | None = None) -> list[dict[str, Any]]:
    """Capabilities of a general or aggregate dataset. Educational student-level analyses are never available."""
    roles = roles or set()
    no_students = "В таблице нет результатов отдельных учеников."
    caps = [_cap("explore", "Обзор таблицы: типы, пропуски, частоты, графики", True, "table")]
    if kind == "aggregate":
        caps.append(_cap("aggregate", "Сводка показателей по группам", True, "aggregate", [],
                         ["Показатели описательные; распределения, доверительные интервалы и парный прирост не "
                          "рассчитываются."]))
        tb = "textbook" in roles
        caps.append(_cap("textbooks", "Сравнение учебников", False, "class",
                         ["Статистическое сравнение учебников требует результатов учеников и классов; по средним "
                          "значениям групп оно не выполняется." + ("" if tb else " Кроме того, нет столбца с "
                                                                                 "учебником.")]))
    else:
        caps.append(_cap("aggregate", "Сводка показателей по группам", False, "aggregate",
                         ["Таблица не сопоставлена как сводная (нет столбца показателя и групп)."]))
        caps.append(_cap("textbooks", "Сравнение учебников", False, "class",
                         ["Таблица не сопоставлена с результатами оценивания."]))
    reason = no_students if kind == "aggregate" else "Таблица не сопоставлена с результатами оценивания."
    for key, title, level in (("overview", "Обзор и средний уровень освоения", "student"),
                              ("topics", "Анализ тем", "topic"), ("gains", "Прирост «входная → итоговая»", "student"),
                              ("optimizer", "Оптимизация часов", "topic")):
        caps.append(_cap(key, title, False, level, [reason]))
    return caps
