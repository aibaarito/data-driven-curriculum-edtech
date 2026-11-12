"""Deterministic SYNTHETIC example files for the flexible importer (docs/examples/). No real people or schools.

* example_wide_gradebook.xlsx  — title row, two-row header with merged group «Контрольная 1», «Итого» row, «н» marks.
* example_aggregate_topics.xlsx — class × topic table with «Средний %» and number of students.
* example_general_table.csv    — a non-educational table (Windows-1251, «;», decimal comma, leading zeros).

    python backend/scripts/generate_import_examples.py
"""
from __future__ import annotations

import random
from datetime import datetime
from pathlib import Path

import openpyxl
from openpyxl.styles import Font

OUT = Path(__file__).resolve().parents[2] / "docs" / "examples"


def wide(path: Path) -> None:
    rng = random.Random(20261113)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Журнал 7А"
    ws["A1"] = "Журнал контрольной работы, 7 классы (СИНТЕТИЧЕСКИЕ ДАННЫЕ)"
    ws["A1"].font = Font(bold=True)
    ws.merge_cells("A1:G1")
    ws.append(["Код ученика", "Класс", "Контрольная 1", None, None, "Итого"])  # row 2: groups
    ws.append([None, None, "Задание 1", "Задание 2", "Задание 3", None])  # row 3: column headings
    for rng_ in ("C2:E2", "A2:A3", "B2:B3", "F2:F3"):
        ws.merge_cells(rng_)
    for i in range(1, 13):
        cls = "7А" if i <= 6 else "7Б"
        scores = [rng.randint(0, 2), rng.randint(0, 3), rng.randint(0, 5)]
        if i == 4:
            scores[2] = "н"  # absent: not zero
        ws.append([f"SYN-W{i:02d}", cls, *scores, sum(s for s in scores if isinstance(s, int))])
    ws.append(["Итого по классу", None, None, None, None, None])
    wb.properties.created = wb.properties.modified = datetime(2026, 11, 13)
    wb.save(path)


def aggregate(path: Path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Сводка"
    ws.append(["Класс", "Тема", "Средний %", "Количество учеников"])
    data = [("7А", "Дроби", 58.5, 24), ("7Б", "Дроби", 63.0, 22), ("7В", "Дроби", 71.2, 25),
            ("7А", "Уравнения", 76.4, 24), ("7Б", "Уравнения", 69.9, 22), ("7В", "Уравнения", 81.0, 25)]
    for row in data:
        ws.append(list(row))
    ws.append(["Среднее", None, 70.0, None])
    wb.properties.created = wb.properties.modified = datetime(2026, 11, 13)
    wb.save(path)


def general(path: Path) -> None:
    lines = ["Код заявки;Город;Дата;Сумма, тг;Статус"]
    rng = random.Random(7)
    for i in range(1, 31):
        city = ["Алматы", "Астана", "Шымкент"][i % 3]
        lines.append(f"{i:05d};{city};{1 + i % 28:02d}.0{1 + i % 3}.2026;{rng.randint(1000, 9000)},{rng.randint(0, 99):02d};"
                     f"{['новая', 'в работе', 'закрыта'][i % 3]}")
    path.write_bytes(("\n".join(lines) + "\n").encode("cp1251"))


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    wide(OUT / "example_wide_gradebook.xlsx")
    aggregate(OUT / "example_aggregate_topics.xlsx")
    general(OUT / "example_general_table.csv")
    print(*sorted(p.name for p in OUT.iterdir()), sep="\n")
