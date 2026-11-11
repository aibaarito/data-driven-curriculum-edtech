"""Human-readable report title and "conclusions for discussion" derived ONLY from a stored report snapshot.

Nothing here queries current analytics: older snapshots that lack a field get an explicit "not stored" wording
instead of a reconstructed conclusion. Every point is labelled as an observation, recommendation or limitation.
"""
from __future__ import annotations

from datetime import date
from typing import Any

DIRECTION_RU = {
    "increase": "установлен рост",
    "decline": "установлено снижение",
    "inconclusive": "изменение не установлено",
    "insufficient": "недостаточно пар для оценки",
}
LEGACY_GAIN = "статус изменения в этом снимке не сохранён"


def fmt(x: Any, digits: int = 1) -> str:
    if x is None:
        return "—"
    v = round(float(x), digits)
    s = f"{v:.{digits}f}".rstrip("0").rstrip(".") if digits else f"{v:.0f}"
    if s in ("-0", ""):
        s = "0"
    return s.replace(".", ",").replace("-", "−")


def signed(x: Any, unit: str = " п.п.") -> str:
    if x is None:
        return "—"
    v = float(x)
    body = fmt(abs(v), 2 if 0 < abs(v) < 0.05 else 1)
    return f"{'+' if v > 0 else '−' if v < 0 else '±'}{body}{unit}"


def _date_ru(iso: str | None) -> str:
    if not iso:
        return "…"
    try:
        return date.fromisoformat(str(iso)[:10]).strftime("%d.%m.%Y")
    except ValueError:
        return str(iso)


def report_title(labels: dict[str, str], filters: dict[str, Any]) -> str:
    """'Математика · 7 класс · все классы · весь период' — built from the actual stored scope."""
    subject = labels.get("Предмет", "все")
    parts = [subject if subject != "все" else "Все предметы",
             f"{filters['grade']} класс" if filters.get("grade") else "все параллели"]
    cls = labels.get("Класс", "все")
    parts.append(f"класс {cls}" if cls != "все" else "все классы")
    tb = labels.get("Учебник", "все")
    if tb != "все":
        parts.append(tb)
    if filters.get("date_from") or filters.get("date_to"):
        parts.append(f"{_date_ru(filters.get('date_from'))} — {_date_ru(filters.get('date_to'))}")
    else:
        parts.append("весь период")
    return " · ".join(parts)


def gain_phrase(gain: dict[str, Any] | None) -> str:
    """Estimate + qualification, e.g. '+0,6 п.п. · изменение не установлено (99,4% ДИ −5,2…6,5; 99 пар)'."""
    if not gain:
        return "изменение не оценивалось (нет пар входной и итоговой диагностики)"
    direction = gain.get("direction")
    if direction is None:
        return f"{signed(gain.get('mean_gain'))} · {LEGACY_GAIN}"
    if direction == "insufficient":
        return f"{DIRECTION_RU['insufficient']} ({gain.get('n_paired', 0)} пар)"
    detail = []
    if gain.get("ci_low") is not None and gain.get("ci_level") is not None:
        detail.append(f"{fmt(gain['ci_level'])}% ДИ {fmt(gain['ci_low'])}…{fmt(gain['ci_high'])}")
    if gain.get("n_paired") is not None:
        detail.append(f"{gain['n_paired']} пар")
    out = f"{signed(gain.get('mean_gain'))} · {DIRECTION_RU[direction]}"
    if detail:
        out += f" ({'; '.join(detail)})"
    if direction == "inconclusive":
        out += ". Это не доказывает отсутствие эффекта"
    return out


def discussion_points(content: dict[str, Any]) -> list[dict[str, str]]:
    points: list[dict[str, str]] = []
    th = content.get("settings") or {}
    topics = [t for t in content.get("topics") or [] if t.get("mastery") is not None]
    flagged = sorted([t for t in topics if t.get("status") == "difficult"], key=lambda t: t["mastery"])[:2]
    if not flagged:
        flagged = sorted([t for t in topics if t.get("status") == "watch"], key=lambda t: t["mastery"])[:1]
    for t in flagged:
        label = "ниже порога «трудная»" if t["status"] == "difficult" else "ниже порога «внимание»"
        thr = th.get("difficult_threshold") if t["status"] == "difficult" else th.get("watch_threshold")
        points.append({"kind": "observation", "topic_id": str(t.get("topic_id")),
                       "text": f"«{t['name']}»: освоение {fmt(t['mastery'])}% ({label}"
                               f"{f' {fmt(thr)}%' if thr is not None else ''}, {t.get('student_count', '—')} учеников). "
                               f"Изменение относительно входной диагностики: {gain_phrase(t.get('gain'))}."})
    if not flagged and topics:
        points.append({"kind": "observation", "text": "Тем ниже порогов «трудная» и «внимание» в этом снимке нет."})

    for p in (content.get("textbooks") or {}).get("pairs") or []:
        a, b = p.get("name_a"), p.get("name_b")
        classes = f"классов {p.get('classes_a', '—')} и {p.get('classes_b', '—')}"
        if p.get("verdict") == "observed_difference" and p.get("adjusted"):
            adj = p["adjusted"]
            level = p.get("ci_level") or adj.get("ci_level")
            kind = "Предварительная связь" if p.get("evidence_level") == "exploratory" else "Наблюдаемая связь"
            interval = (f" ({fmt(level)}% ДИ {fmt(adj.get('ci_low'))}…{fmt(adj.get('ci_high'))})"
                        if level is not None else "")
            points.append({"kind": "observation",
                           "text": f"«{b}» − «{a}»: с поправкой на исходный уровень {signed(adj.get('diff'))}{interval}"
                                   f"; {classes}. {kind} в наблюдательных данных, не доказательство эффекта учебника."})
        else:
            points.append({"kind": "limitation",
                           "text": f"«{a}» и «{b}»: недостаточно данных для вывода о различии ({classes})."})

    opt = content.get("optimizer")
    if opt:
        changed = sum(1 for r in opt.get("rows") or [] if r.get("delta"))
        status = content.get("optimizer_status_label") or content.get("optimizer_status") or "статус не сохранён"
        text = (f"План часов для параллели (рекомендация системы, {status}): всего {fmt(opt.get('total_hours'))} ч, "
                f"изменены часы по темам: {changed}. Это рекомендация, а не прогноз результатов.")
        if opt.get("relaxed_policies"):
            text += " Ослаблены по запросу правила: " + ", ".join(opt["relaxed_policies"]) + "."
        points.append({"kind": "recommendation", "text": text})
    elif content.get("optimizer_scope_note"):
        points.append({"kind": "limitation", "text": f"План часов в отчёт не включён: {content['optimizer_scope_note']}"})

    if content.get("synthetic"):
        points.append({"kind": "limitation",
                       "text": "Данные синтетические и не описывают реальную школу; связи не являются причинными эффектами."})
    else:
        points.append({"kind": "limitation", "text": "Данные наблюдательные: выводы описывают связи, а не причинные эффекты."})
    return points
