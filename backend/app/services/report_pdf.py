"""PDF rendering of a stored report (Cyrillic via bundled DejaVu Sans)."""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from xml.sax.saxutils import escape

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
_registered = False


def _fonts() -> None:
    global _registered
    if not _registered:
        pdfmetrics.registerFont(TTFont("DejaVu", str(FONT_DIR / "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(FONT_DIR / "DejaVuSans-Bold.ttf")))
        _registered = True


def _styles() -> dict[str, ParagraphStyle]:
    base = ParagraphStyle("base", fontName="DejaVu", fontSize=9.5, leading=13, alignment=TA_LEFT)
    return {
        "body": base,
        "small": ParagraphStyle("small", parent=base, fontSize=8, leading=10.5, textColor=colors.HexColor("#555555")),
        "h1": ParagraphStyle("h1", parent=base, fontName="DejaVu-Bold", fontSize=17, leading=22, spaceAfter=4),
        "h2": ParagraphStyle("h2", parent=base, fontName="DejaVu-Bold", fontSize=12.5, leading=16, spaceBefore=10,
                             spaceAfter=4, textColor=colors.HexColor("#1e3a5f")),
        "tag": ParagraphStyle("tag", parent=base, fontName="DejaVu-Bold", fontSize=8, textColor=colors.HexColor("#8a5a00")),
        "cell": ParagraphStyle("cell", parent=base, fontSize=8, leading=10),
    }


def _p(text: Any, st: ParagraphStyle) -> Paragraph:
    return Paragraph(escape("" if text is None else str(text)), st)


def _table(header: list[str], rows: list[list[Any]], st, widths=None) -> Table:
    data = [[_p(h, st["cell"]) for h in header]] + [[_p(c if c is not None else "—", st["cell"]) for c in r] for r in rows]
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f7")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9d2de")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


STATUS_RU = {"difficult": "трудная", "watch": "внимание", "ok": "норма", "insufficient_data": "мало данных",
             "no_outcome_data": "нет данных"}


def render_pdf(report: dict[str, Any]) -> bytes:
    _fonts()
    st = _styles()
    c = report["content"]
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=14 * mm,
                            bottomMargin=14 * mm, title=report["title"], author="Data-Driven Curriculum")
    created = str(report["created_at"]).replace("T", " ")[:16]
    el: list[Any] = [_p(report["title"], st["h1"]), _p(f"Сформирован: {created}", st["small"])]
    if c.get("synthetic"):
        el.append(_p("ВНИМАНИЕ: отчёт построен на синтетических демонстрационных данных, а не на данных реальной школы.",
                     st["tag"]))
    el.append(Spacer(1, 4))
    el.append(_p("Фильтры", st["h2"]))
    el.append(_table(["Параметр", "Значение"], [[k, v] for k, v in c["filter_labels"].items()], st, [45 * mm, 120 * mm]))

    ov = c["overview"]
    el.append(_p("1. Сводка оцениваний (наблюдаемые данные)", st["h2"]))
    el.append(_table(["Учеников", "Оцениваний", "Классов", "Тем", "Учебников", "Среднее освоение, %", "Период"], [[
        ov["students"], ov["assessments"], ov["classes"], ov["topics"], ov["textbooks"], ov["average_mastery"],
        f"{ov['date_from']} — {ov['date_to']}" if ov.get("date_from") else "—"]], st))
    el.append(_p("Освоение = Σ набранных баллов / Σ максимальных баллов × 100 по итоговым и текущим оцениваниям; "
                 "входная диагностика используется только как исходный уровень.", st["small"]))

    el.append(_p("2. Результаты по темам (наблюдаемые данные)", st["h2"]))
    rows = []
    for t in c["topics"]:
        g = t.get("gain") or {}
        rows.append([t["name"], t["mastery"], t["median"], t["student_count"], t["assessment_count"],
                     g.get("mean_gain"), f"{g['ci_low']}…{g['ci_high']}" if g.get("ci_low") is not None else None,
                     t.get("hours"), STATUS_RU.get(t["status"], t["status"])])
    el.append(_table(["Тема", "Освоение %", "Медиана %", "Учен.", "Оцен.", "Прирост п.п.", "95% ДИ", "Часы", "Статус"],
                     rows, st, [44 * mm, 15 * mm, 15 * mm, 11 * mm, 11 * mm, 16 * mm, 20 * mm, 11 * mm, 16 * mm]))
    th = c["settings"]
    el.append(_p(f"Пороги: трудная < {th['difficult_threshold']}%, внимание < {th['watch_threshold']}%, минимум "
                 f"{th['min_students_topic']} учеников для классификации.", st["small"]))
    for t in c["topics"]:
        if t["status"] in ("difficult", "watch"):
            el.append(_p(f"• {t['name']}: {t['interpretation']}", st["body"]))

    el.append(_p("3. Сравнение учебников (наблюдаемые данные)", st["h2"]))
    tb = c["textbooks"]
    if tb["textbooks"]:
        el.append(_table(["Учебник", "Учеников", "Классов", "Среднее %", "95% ДИ", "Исходный уровень %", "Часов/класс"], [
            [s["name"], s["students"], s["classes"], s["mean"],
             f"{s['ci_low']}…{s['ci_high']}" if s.get("ci_low") is not None else None, s["baseline_mean"],
             s["mean_hours_per_class"]] for s in tb["textbooks"]], st))
        for pr in tb["pairs"]:
            el.append(Spacer(1, 3))
            el.append(_p(f"{pr['name_a']} vs {pr['name_b']}: {pr['verdict_text']}", st["body"]))
            for r in pr.get("reasons") or []:
                el.append(_p(f"– {r}", st["small"]))
            for r in pr.get("confounders") or []:
                el.append(_p(f"– Возможный искажающий фактор: {r}", st["small"]))
    else:
        el.append(_p(tb.get("message") or "Нет данных.", st["body"]))

    el.append(_p("4. Рекомендации по учебным часам (рекомендация, не прогноз)", st["h2"]))
    opt = c.get("optimizer")
    if opt:
        el.append(_p(f"Статус рекомендации: {c.get('optimizer_status_label', c.get('optimizer_status'))}. "
                     f"Всего часов: {opt['total_hours']}.", st["body"]))
        el.append(_table(["Тема", "Сейчас, ч", "Предлагается, ч", "Изменение", "Обоснование"], [
            [r["name"], r["current_hours"], r["proposed_hours"], f"{r['delta']:+g}", r["explanation"]] for r in opt["rows"]],
            st, [38 * mm, 16 * mm, 20 * mm, 16 * mm, 88 * mm]))
        for w in opt.get("warnings") or []:
            el.append(_p(f"⚠ {w}", st["small"]))
    else:
        el.append(_p("Рекомендация по часам для выбранных фильтров ещё не сформирована (выберите предмет и "
                     "параллель в оптимизаторе).", st["body"]))

    ins = c.get("insights")
    if ins:
        mode = "языковая модель (проверено по метрикам)" if ins["mode"] == "llm" else "детерминированный режим"
        el.append(_p(f"5. Пояснения ({mode})", st["h2"]))
        el.append(_p(ins["payload"]["summary"], st["body"]))
        for f in ins["payload"]["findings"]:
            label = {"observation": "Наблюдение", "recommendation": "Рекомендация", "limitation": "Ограничение"}[f["kind"]]
            el.append(_p(f"[{label}] {f['title']}: {f['text']}", st["body"]))
        if ins["payload"]["next_steps"]:
            el.append(_p("Следующие шаги:", st["body"]))
            for s_ in ins["payload"]["next_steps"]:
                el.append(_p(f"• {s_}", st["body"]))

    el.append(_p("6. Ограничения данных", st["h2"]))
    for lim in c["limitations"]:
        el.append(_p(f"• {lim}", st["body"]))
    doc.build(el)
    return buf.getvalue()
