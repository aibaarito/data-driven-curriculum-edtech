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
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import CondPageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from xml.sax.saxutils import escape

from app.services.report_summary import DIRECTION_RU as GAIN_DIRECTION_RU, discussion_points

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
        "cell": ParagraphStyle("cell", parent=base, fontSize=8, leading=10, splitLongWords=False),
        "head": ParagraphStyle("head", parent=base, fontName="DejaVu-Bold", fontSize=7, leading=9,
                               splitLongWords=False),
    }


# Usable frame width: A4 minus 2 × 16 mm margins minus the frame's 2 × 6 pt padding (≈ 173.8 mm).
FRAME_W = 172 * mm


def _h2(el: list[Any], text: str, st: dict[str, ParagraphStyle]) -> None:
    """Section heading that never sits alone at a page bottom, while long tables below may still split."""
    el.append(CondPageBreak(40 * mm))
    el.append(_p(text, st["h2"]))


def _p(text: Any, st: ParagraphStyle) -> Paragraph:
    return Paragraph(escape("" if text is None else str(text)), st)


def _table(header: list[str], rows: list[list[Any]], st, widths=None) -> Table:
    data = [[_p(h, st["head"]) for h in header]] + [[_p(c if c is not None else "—", st["cell"]) for c in r] for r in rows]
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f7")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9d2de")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


# Same wording as the topic screen, the on-screen report and the discussion section.
DIRECTION_RU = GAIN_DIRECTION_RU
KIND_RU = {"observation": "Наблюдение", "recommendation": "Рекомендация", "limitation": "Ограничение"}


class _NumberedCanvas(rl_canvas.Canvas):
    """Adds 'Стр. N из M' and the report title to every page footer."""

    def __init__(self, *args: Any, footer: str = "", **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._pages: list[dict[str, Any]] = []
        self._footer = footer

    def showPage(self) -> None:  # noqa: N802 (ReportLab API)
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total = len(self._pages)
        for state in self._pages:
            self.__dict__.update(state)
            self.setFont("DejaVu", 7.5)
            self.setFillColor(colors.HexColor("#666666"))
            self.drawString(16 * mm, 8 * mm, self._footer[:110])
            self.drawRightString(A4[0] - 16 * mm, 8 * mm, f"Стр. {self._pageNumber} из {total}")
            super().showPage()
        super().save()
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
    el: list[Any] = [_p(report["title"], st["h1"]),
                     _p(f"Снимок результатов на {created}. Последующие изменения данных и настроек не изменяют "
                        "этот отчёт.", st["small"])]
    if c.get("synthetic"):
        el.append(_p("ВНИМАНИЕ: отчёт построен на синтетических демонстрационных данных, а не на данных реальной школы.",
                     st["tag"]))
    el.append(Spacer(1, 4))
    _h2(el, "Фильтры", st)
    el.append(_table(["Параметр", "Значение"], [[k, v] for k, v in c["filter_labels"].items()], st, [45 * mm, 127 * mm]))

    points = report.get("discussion") or discussion_points(c)
    _h2(el, "Выводы для обсуждения", st)
    el.append(_table(["Тип", "Вывод (по сохранённому снимку)"], [[KIND_RU[pt["kind"]], pt["text"]] for pt in points],
                     st, [28 * mm, 144 * mm]))
    el.append(_p("Наблюдения описывают связи в данных, рекомендации требуют решения методиста, ограничения указывают, "
                 "чего данные не позволяют утверждать. Подробности — в разделах ниже.", st["small"]))

    ov = c["overview"]
    _h2(el, "1. Сводка оцениваний (наблюдаемые данные)", st)
    el.append(_table(["Учеников", "Оцениваний", "Классов", "Тем", "Учебников", "Среднее освоение, %", "Период"], [[
        ov["students"], ov["assessments"], ov["classes"], ov["topics"], ov["textbooks"], ov["average_mastery"],
        f"{ov['date_from']} — {ov['date_to']}" if ov.get("date_from") else "—"]], st,
        [21 * mm, 23 * mm, 20 * mm, 16 * mm, 22 * mm, 30 * mm, 40 * mm]))
    el.append(_p("Освоение = Σ набранных баллов / Σ максимальных баллов × 100 по итоговым и текущим оцениваниям; "
                 "входная диагностика используется только как исходный уровень.", st["small"]))

    _h2(el, "2. Результаты по темам (наблюдаемые данные)", st)
    rows = []
    level = None
    for t in c["topics"]:
        g = t.get("gain") or {}
        level = level or g.get("ci_level")
        if not g:
            direction = "не оценивалось"
        elif g.get("direction") is None:
            direction = "не сохранён в снимке"
        else:
            direction = DIRECTION_RU.get(g["direction"], "—")
        estimate = None
        if g.get("mean_gain") is not None:
            estimate = f"{g['mean_gain']:+g}"
            if g.get("ci_low") is not None:
                estimate += f" [{g['ci_low']:g}…{g['ci_high']:g}]"
        if g.get("n_paired") is not None and g.get("direction") is not None:
            direction += f"; пар: {g['n_paired']}"
        rows.append([t["name"], t["mastery"], t["median"], estimate, direction, t.get("hours"),
                     f"{STATUS_RU.get(t['status'], t['status'])}; учеников: {t['student_count']}"])
    ci_head = f"Изменение, п.п. [ДИ {level:g}%]" if level else "Изменение, п.п."
    el.append(_table(["Тема", "Освоение, %", "Медиана, %", ci_head, "Статус изменения", "Часы (ср.)", "Статус темы"],
                     rows, st, [40 * mm, 18 * mm, 18 * mm, 30 * mm, 27 * mm, 15 * mm, 24 * mm]))
    th = c["settings"]
    el.append(_p(f"Пороги: трудная < {th['difficult_threshold']}%, внимание < {th['watch_threshold']}%, минимум "
                 f"{th['min_students_topic']} учеников для классификации. Освоение — объединённые баллы (Σ/Σ), "
                 "медиана — по ученикам. «Часы (ср.)» — среднее по классам (план часов ниже использует медиану по классам). "
                 "Интервалы изменения — с поправкой Бонферрони на число тем; «не установлено» "
                 "не означает отсутствия эффекта.", st["small"]))
    for t in c["topics"]:
        if t["status"] in ("difficult", "watch"):
            el.append(_p(f"• {t['name']}: {t['interpretation']}", st["body"]))

    _h2(el, "3. Сравнение учебников (наблюдаемые данные)", st)
    tb = c["textbooks"]
    if tb["textbooks"]:
        el.append(_table(["Учебник", "Учеников", "Классов", "Среднее, %", "95% ДИ (описат.)", "Исходный уровень, %",
                          "Часов на класс"], [
            [s["name"], s["students"], s["classes"], s["mean"],
             f"{s['ci_low']}…{s['ci_high']}" if s.get("ci_low") is not None else None, s["baseline_mean"],
             s["mean_hours_per_class"]] for s in tb["textbooks"]], st,
            [48 * mm, 18 * mm, 17 * mm, 18 * mm, 25 * mm, 24 * mm, 22 * mm]))
        el.append(_p("Показатели таблицы описательные (по ученикам). Выводы о различии строятся по классам: учебник "
                     "назначается классу, поэтому независимые наблюдения — классы.", st["small"]))
        for pr in tb["pairs"]:
            el.append(Spacer(1, 3))
            el.append(_p(f"{pr['name_a']} vs {pr['name_b']}: {pr['verdict_text']}", st["body"]))
            el.append(_p(f"Классов в анализе: {pr.get('classes_a', 0)} и {pr.get('classes_b', 0)}; уровень интервалов "
                         f"{pr.get('ci_level', 95):g}%.", st["small"]))
            for r in pr.get("reasons") or []:
                el.append(_p(f"– {r}", st["small"]))
            for r in pr.get("confounders") or []:
                el.append(_p(f"– Возможный искажающий фактор: {r}", st["small"]))
    else:
        el.append(_p(tb.get("message") or "Нет данных.", st["body"]))

    _h2(el, "4. Рекомендации по учебным часам (рекомендация, не прогноз)", st)
    opt = c.get("optimizer")
    if opt:
        el.append(_p(f"Статус рекомендации: {c.get('optimizer_status_label', c.get('optimizer_status'))}. "
                     f"Всего часов: {opt['total_hours']}.", st["body"]))
        if c.get("optimizer_scope_note"):
            el.append(_p(c["optimizer_scope_note"], st["small"]))
        relaxed = opt.get("relaxed_policies") or []
        if relaxed:
            el.append(_p("Ослабленные по запросу правила: " + ", ".join(relaxed) + ".", st["small"]))
        el.append(_table(["Тема", "Сейчас, ч", "Предлагается, ч", "Изменение, ч", "Обоснование"], [
            [r["name"], r["current_hours"], r["proposed_hours"], f"{r['delta']:+g}", r["explanation"]] for r in opt["rows"]],
            st, [36 * mm, 17 * mm, 24 * mm, 20 * mm, 75 * mm]))
        for w in opt.get("warnings") or []:
            el.append(_p(f"⚠ {w}", st["small"]))
    else:
        el.append(_p(c.get("optimizer_scope_note") or "Рекомендация по часам для выбранных фильтров отсутствует.",
                     st["body"]))

    ins = c.get("insights")
    if ins:
        mode = "языковая модель, числа сверены с расчётами" if ins["mode"] == "llm" else "по шаблонам, детерминированный режим"
        _h2(el, f"5. Пояснения ({mode})", st)
        el.append(_p(ins["payload"]["summary"], st["body"]))
        for f in ins["payload"]["findings"]:
            label = {"observation": "Наблюдение", "recommendation": "Рекомендация", "limitation": "Ограничение"}[f["kind"]]
            el.append(_p(f"[{label}] {f['title']}: {f['text']}", st["body"]))
        if ins["payload"]["next_steps"]:
            el.append(_p("Следующие шаги:", st["body"]))
            for s_ in ins["payload"]["next_steps"]:
                el.append(_p(f"• {s_}", st["body"]))

    _h2(el, "6. Ограничения данных", st)
    for lim in c["limitations"]:
        el.append(_p(f"• {lim}", st["body"]))
    footer = f"{report['title']} · снимок {created}"
    doc.build(el, canvasmaker=lambda *a, **k: _NumberedCanvas(*a, footer=footer, **k))
    return buf.getvalue()
