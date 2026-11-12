import { describe, expect, it } from "vitest";

import { buildPayload, codeFromHeader, initialPrep, prepProblems, prepReady } from "./import-wizard";
import type { ImportFieldInfo, SheetInspection } from "./types";

const F = (field: string, required: boolean, opts: Partial<ImportFieldInfo> = {}): ImportFieldInfo =>
  ({ field, label: field, description: "", required, shared_allowed: false, none_allowed: false, ...opts });
const FIELDS = [
  F("student_id", true), F("class", true), F("subject", true, { shared_allowed: true }),
  F("topic_id", true, { wide_result: true }), F("topic_name", true, { wide_result: true }),
  F("assessment_id", true, { shared_allowed: true, wide_per_column: true }), F("score", true, { wide_result: true }),
  F("max_score", true, { wide_result: true }), F("textbook_id", true, { none_allowed: true }),
];

function ins(extra: Partial<SheetInspection>): SheetInspection {
  return {
    sheet: "Л", hidden: false, problem: null, width: 4, header_suggestion: { row: 1, confidence: "high", reason: "" },
    preview: [], header_rows_allowed: [1], header_row: 1,
    columns: ["Код ученика", "Класс", "Дроби", "Уравнения"].map((h, i) => ({ id: `c${i}`, letter: "ABCD"[i], header: h, label: h, samples: [], empty: false,
      profile: { numeric: i > 1 ? 1 : 0, percent_text: 0, date: 0, distinct: i > 1 ? ["2", "3", "5"] : [], distinct_count: 3, min: null, max: null } })),
    suggestions: { suggested: { student_id: { column: "c0", confidence: "alias" }, class: { column: "c1", confidence: "alias" } }, ambiguous: {} },
    notices: [], duplicate_headers: [], ...extra,
  };
}

const WIDE = ins({ layout_suggestion: { layout: "wide", confidence: "medium", reason: "" },
  wide_suggestion: { identity: {}, total_columns: [], result_columns: [{ column: "c2", topic_name: "Дроби", item_hint: "" }, { column: "c3", topic_name: "Уравнения", item_hint: "" }] } });

describe("wide gradebook preparation", () => {
  it("proposes result columns with header names but never invents codes or maxima", () => {
    const p = initialPrep(WIDE);
    expect(p.layout).toBe("wide");
    expect(p.resultColumns.map((r) => [r.column, r.topic_name, r.topic_id, r.max_score])).toEqual([["c2", "Дроби", "", ""], ["c3", "Уравнения", "", ""]]);
    const probs = prepProblems(FIELDS, p, WIDE);
    expect(probs.columns.c2).toEqual(["Укажите код темы.", "Укажите максимальный балл."]);
    expect(prepReady(FIELDS, p, WIDE)).toBe(false);
  });

  it("treats per-column assessment values as covering the row field and builds the payload", () => {
    const p = initialPrep(WIDE);
    p.mapping = { ...p.mapping, subject: { source: "value", value: "Математика" }, textbook_id: { source: "none" } };
    p.resultColumns = p.resultColumns.map((r, i) => ({ ...r, topic_id: `T${i}`, max_score: "5", assessment_id: `A${i}` }));
    p.confirmShared = true;
    expect(prepProblems(FIELDS, p, WIDE).fields.assessment_id).toBeUndefined();
    expect(prepReady(FIELDS, p, WIDE)).toBe(true);
    const body = buildPayload("k", "Л", { encoding: "auto", delimiter: "auto" },
      { header_row: 1, header_rows: 1, first_col: 0, last_col: null, last_row: null, exclude: ["total"] }, p);
    expect(body.layout).toBe("wide");
    expect(body.exclude).toEqual(["total"]);
    expect("result_columns" in body && body.result_columns[0]).toEqual({ column: "c2", topic_id: "T0", topic_name: "Дроби", max_score: "5", assessment_id: "A0" });
  });

  it("rejects a per-column value that would override a row mapping", () => {
    const p = initialPrep(WIDE);
    p.mapping.assessment_id = { source: "value", value: "A" };
    p.resultColumns[0] = { ...p.resultColumns[0], assessment_id: "B" };
    expect(prepProblems(FIELDS, p, WIDE).columns.c2.some((m) => m.includes("уже задано для всех строк"))).toBe(true);
  });

  it("derives deterministic, unique codes only on request", () => {
    const taken = new Set<string>();
    expect(codeFromHeader("Дроби и проценты", taken)).toBe("DROBI-I-PROTSENTY");
    expect(codeFromHeader("Дроби и проценты", taken)).toBe("DROBI-I-PROTSENTY-2");
  });
});

describe("rules, aggregate and general layouts", () => {
  it("requires an explicit scale table and binary tokens", () => {
    const p = initialPrep(ins({}));
    p.rules = { ...p.rules, score_mode: "scale", scale: {} };
    expect(prepProblems(FIELDS, p, null).general).toContain("Заполните таблицу перевода отметок в проценты.");
    p.rules = { ...p.rules, score_mode: "binary", true_tokens: ["1"], false_tokens: [] };
    expect(prepProblems(FIELDS, p, null).general).toContain("Укажите значения «верно» и «неверно».");
  });

  it("does not require a maximum column when results are percentages", () => {
    const p = initialPrep(ins({}));
    p.rules = { ...p.rules, score_mode: "percent" };
    p.mapping.max_score = { source: "column", column: "c3" };
    expect(prepProblems(FIELDS, p, null).fields.max_score?.[0].message).toContain("максимум задаётся правилом");
  });

  it("aggregate tables need a metric definition and group column", () => {
    const p = { ...initialPrep(ins({})), layout: "aggregate" as const, roles: { c1: "class" } };
    const g = prepProblems(FIELDS, p, null).general;
    expect(g).toContain("Выберите столбец с показателем (средний балл, процент…).");
    expect(g).toContain("Укажите, что означает показатель: процент или средний балл.");
    const ok = { ...p, roles: { c1: "class", c2: "value" }, metric: { kind: "mean_points" as const, max_value: "", percent_scale: "0-100" as const } };
    expect(prepProblems(FIELDS, ok, null).general).toEqual(["Для среднего балла укажите максимальный балл или столбец максимума."]);
  });

  it("general tables send confirmed types and no assessment mapping", () => {
    const p = { ...initialPrep(ins({ type_suggestion: { c0: "identifier", c2: "number" } })), layout: "general" as const };
    const body = buildPayload("k", "Л", { encoding: "cp1251", delimiter: ";" },
      { header_row: 2, header_rows: 1, first_col: 0, last_col: 3, last_row: 40, exclude: [] }, p);
    expect(body).toMatchObject({ layout: "general", fields: {}, types: { c0: "identifier", c2: "number" }, csv: { encoding: "cp1251", delimiter: ";" }, last_col: 3, last_row: 40 });
    expect(prepReady(FIELDS, p, null)).toBe(true);
  });
});
