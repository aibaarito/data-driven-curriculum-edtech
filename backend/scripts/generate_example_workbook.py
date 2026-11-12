"""Deterministic SYNTHETIC example workbook for the guided importer (no real students, schools or textbooks).

Demonstrates: an instruction sheet before the data, a merged title row and a blank row above the header, Russian
column names, an ambiguous "Учебник" column, a column to ignore, and a hidden service sheet.
Subject and assessment type are deliberately absent: the user supplies them as confirmed shared values.

    python backend/scripts/generate_example_workbook.py   # writes backend/app/assets/data/example_guided_import.xlsx
"""
from __future__ import annotations

import random
import sys
from datetime import datetime
from pathlib import Path

import openpyxl
from openpyxl.styles import Font

OUT = Path(__file__).resolve().parent.parent / "app" / "assets" / "data" / "example_guided_import.xlsx"
TOPICS = [("SYN-T1", "Линейные уравнения", 4), ("SYN-T2", "Степень с натуральным показателем", 5),
          ("SYN-T3", "Многочлены", 6)]
CLASSES = [("7А", "SYN-TB-A"), ("7Б", "SYN-TB-B")]


def build(path: Path = OUT) -> Path:
    rng = random.Random(20261112)
    wb = openpyxl.Workbook()
    info = wb.active
    info.title = "Инструкция"
    info["A1"] = "СИНТЕТИЧЕСКИЙ ПРИМЕР. Данные сгенерированы и не описывают реальных учеников."
    info["A3"] = "Результаты находятся на листе «Результаты». Заголовок таблицы — в строке 3."
    info["A4"] = "Предмет (Математика) и тип оценивания (pre) в таблице не указаны: задайте их в мастере импорта."

    ws = wb.create_sheet("Результаты")
    ws["A1"] = "Входная диагностика, 7 классы (синтетические данные)"
    ws["A1"].font = Font(bold=True, size=14)
    ws.merge_cells("A1:K1")
    header = ["Код ученика", "Параллель", "Класс", "Код темы", "Тема", "Код работы", "Дата", "Баллы",
              "Максимальный балл", "Учебник", "Примечание"]
    ws.append([])  # row 2 stays blank
    ws.append(header)  # row 3
    for c in ws[3]:
        c.font = Font(bold=True)
    for cls, tb in CLASSES:
        for s in range(1, 7):
            sid = f"SYN-{'A' if cls.endswith('А') else 'B'}{s:02d}"
            for code, name, mx in TOPICS:
                ws.append([sid, 7, cls, code, name, "SYN-PRE-2026", datetime(2026, 9, 15), rng.randint(0, mx), mx, tb,
                           "" if rng.random() > 0.2 else "пересдача не требуется"])
    hidden = wb.create_sheet("Служебный")
    hidden["A1"] = "Справочник учебников (синтетический)"
    hidden.append(["SYN-TB-A", "Учебник А (вымышленный)"])
    hidden.append(["SYN-TB-B", "Учебник Б (вымышленный)"])
    hidden.sheet_state = "hidden"
    # Fixed workbook metadata keeps the file reproducible apart from zip timestamps.
    wb.properties.creator = "ddc synthetic generator"
    wb.properties.created = wb.properties.modified = datetime(2026, 11, 12)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


if __name__ == "__main__":
    print(build(Path(sys.argv[1]) if len(sys.argv) > 1 else OUT))
