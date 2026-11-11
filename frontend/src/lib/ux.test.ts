import { describe, expect, it } from "vitest";

import { observationSeries } from "@/components/charts";

import { factLabel } from "./facts";
import { ci } from "./format";
import { gainText, summarizeGain } from "./gain";
import { columnLabel, groupByRow, summarizeErrors } from "./import-issues";
import { filterConflicts, inapplicableFilters, scopeLabel, scopedHref } from "./scope";
import type { Gain, Meta, TrendPoint } from "./types";

const META: Meta = {
  subjects: [{ id: 1, name: "Математика" }, { id: 2, name: "Физика" }],
  grades: [7, 8],
  classes: [{ id: 10, name: "7А", grade: 7 }, { id: 20, name: "8А", grade: 8 }],
  textbooks: [{ id: 5, code: "A7", name: "Алгебра 7 — А", subject_id: 1 }, { id: 6, code: "P7", name: "Физика 7", subject_id: 2 }],
  date_from: "2025-09-01", date_to: "2026-05-30", synthetic: true, has_data: true,
};

const gain = (direction: Gain["direction"], mean_gain: number | null, extra: Partial<Gain> = {}): Gain => ({
  direction, ci_level: 99.38, family_size: 8, p_value_adjusted: 0.5, n_paired: 99, pre_mean: 40, post_mean: 41,
  mean_gain, ci_low: -5.2, ci_high: 6.5, p_value: 0.4, normalized_gain: 0.01, significant: false, groups: ["g"], ...extra,
});

describe("F1 assessment observations", () => {
  const point = (assessment: string, grades: number[] | undefined, mastery: number): TrendPoint => ({
    assessment, date: "2025-09-10", kind: "current", mastery, students: 20, topics: 3, grades,
  });

  it("puts grade-7 and grade-8 observations in different series so no line can bridge them", () => {
    const { pops, rows } = observationSeries([point("A7-PRE", [7], 38), point("A8-PRE", [8], 30), point("A7-Q1", [7], 74)]);
    expect(pops.map((p) => p.label)).toEqual(["7 класс", "8 класс"]);
    for (const r of rows) {
      const filled = pops.filter((p) => r[p.key] !== undefined && r[p.key] !== null);
      expect(filled).toHaveLength(1); // each assessment belongs to exactly one population series
    }
    expect(rows[1].g7).toBeUndefined();
    expect(rows[1].g8).toBe(30);
  });

  it("labels assessments taken by several grades together, and older data without population metadata", () => {
    const { pops } = observationSeries([point("JOINT", [7, 8], 50), point("OLD", undefined, 60)]);
    expect(pops.map((p) => p.label)).toEqual(["Параллели 7 и 8 вместе", "Группа не указана"]);
  });
});

describe("F4 gain qualification", () => {
  it.each([
    ["increase", 27.1, "+27,1 п.п. · установлен рост"],
    ["decline", -4, "−4 п.п. · установлено снижение"],
    ["inconclusive", 0.6, "+0,6 п.п. · изменение не установлено"],
  ] as const)("%s keeps the estimate with its status", (direction, value, text) => {
    expect(gainText(gain(direction, value))).toBe(text);
  });

  it("inconclusive change carries the 'not evidence of no effect' caution and the interval level", () => {
    const s = summarizeGain(gain("inconclusive", 0.6));
    expect(s.note).toBe("Это не доказывает отсутствие эффекта.");
    expect(s.detail).toBe(`99,38% ДИ ${ci(-5.2, 6.5)} · 99 пар`);
  });

  it("insufficient evidence shows no estimate", () => {
    const s = summarizeGain(gain("insufficient", 3.2, { n_paired: 4 }));
    expect(s.estimate).toBeNull();
    expect(gainText(gain("insufficient", 3.2))).toBe("недостаточно пар для оценки");
  });

  it("older snapshots without a stored direction never present a conclusion", () => {
    const legacy = { ...gain("increase", 5), direction: undefined };
    expect(gainText(legacy)).toBe("+5 п.п. · статус изменения в этом снимке не сохранён");
    expect(summarizeGain(null).status).toBe("не оценивалось");
  });
});

describe("F5 scope rules", () => {
  it("summarises the scope a screen applies", () => {
    expect(scopeLabel({ subject_id: 1, grade: 7 }, META, "/insights")).toBe("Математика · 7 класс · все классы · весь период");
    expect(scopeLabel({ grade: 7, class_id: 10, date_from: "2025-10-01" }, META, "/topics"))
      .toBe("Все предметы · 7 класс · класс 7А · 01.10.2025 — …");
  });

  it("carries every filter through navigation and explains those a screen cannot apply", () => {
    const f = { subject_id: 1, grade: 7, class_id: 10, date_from: "2025-10-01" };
    expect(scopedHref("/textbooks", f)).toBe("/textbooks?subject_id=1&grade=7&class_id=10&date_from=2025-10-01");
    expect(inapplicableFilters("/textbooks", f, META)).toEqual(["класс 7А"]);
    expect(inapplicableFilters("/optimizer", f, META)).toEqual(["класс 7А", "период 01.10.2025 — …"]);
    expect(inapplicableFilters("/topics", f, META)).toEqual([]);
  });

  it("reports incompatible dependent values instead of silently broadening", () => {
    const c = filterConflicts({ subject_id: 1, grade: 7, class_id: 20, textbook_id: 6 }, META);
    expect(c.map((x) => x.key)).toEqual(["class_id", "textbook_id"]);
    expect(c[0].message).toContain("8А");
    expect(filterConflicts({ grade: 9 }, META)[0].key).toBe("grade");
    expect(filterConflicts({ grade: 7, class_id: 10 }, META)).toEqual([]);
  });
});

describe("F7 import issues", () => {
  const errors = [
    { row: 3, column: "student_id", code: "POSSIBLE_PERSONAL_DATA", message: "m" },
    { row: 3, column: "score", code: "SCORE_EXCEEDS_MAX", message: "m" },
    { row: 5, column: "score", code: "INVALID_NUMBER", message: "m" },
    { row: 5, column: "student_id", code: "INVALID_IDENTIFIER", message: "m" },
  ];

  it("counts affected rows separately from errors", () => {
    const s = summarizeErrors({ errors, error_count: 4 });
    expect(s.rows).toBe(2);
    expect(s.headline).toBe("Исправьте 2 строки. Найдено 4 ошибки; данные ещё не импортированы.");
  });

  it("does not claim an exact row count when the server listed only part of the errors", () => {
    const s = summarizeErrors({ errors, error_count: 900 });
    expect(s.rowsExact).toBe(false);
    expect(s.headline).toBe("Исправьте не менее 2 строк. Найдено 900 ошибок; данные ещё не импортированы.");
  });

  it("groups by row with file-level issues first and keeps exact headers", () => {
    const g = groupByRow([...errors, { row: null, column: "grade", code: "MISSING_COLUMN", message: "m" }]);
    expect(g.map((x) => x.row)).toEqual([null, 3, 5]);
    expect(columnLabel("max_score")).toEqual({ header: "max_score", label: "Максимальный балл" });
    expect(summarizeErrors({ errors: [{ row: null, column: null, code: "EMPTY_FILE", message: "m" }], error_count: 1 }).headline)
      .toBe("Исправьте структуру файла. Найдено 1 ошибка; данные ещё не импортированы.");
  });
});

describe("F9 fact labels", () => {
  const facts = {
    "topic.T7-05.name": "Формулы сокращённого умножения", "topic.T7-05.mastery": 40.9, "topic.T7-05.gain": 0.6,
    "topic.T7-05.gain_direction": "inconclusive", "comparison.0.name_a": "Учебник А", "comparison.0.name_b": "Учебник Б",
    "comparison.0.adjusted_diff": 5.1,
  };

  it("turns raw keys into topic, metric, unit and a link that keeps the result's scope", () => {
    const f = factLabel("topic.T7-05.mastery", facts, "?grade=7");
    expect(f).toMatchObject({ label: "Формулы сокращённого умножения — освоение", value: "40,9%", href: "/topics?grade=7&topic=T7-05" });
    expect(factLabel("topic.T7-05.gain", facts, "").value).toBe("+0,6 п.п.");
    expect(factLabel("topic.T7-05.gain_direction", facts, "").value).toBe("изменение не установлено");
    expect(factLabel("comparison.0.adjusted_diff", facts, "?grade=7").label)
      .toBe("Сравнение учебников — разница с поправкой на исходный уровень («Учебник Б» − «Учебник А»)");
  });
});
