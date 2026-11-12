import { describe, expect, it } from "vitest";

import {
  fieldProblems,
  ignoredColumns,
  initialMapping,
  remapAfterHeaderChange,
  requiredResolved,
  selectToChoice,
  validatePayload,
} from "./import-wizard";
import type { ImportFieldInfo, SheetInspection } from "./types";

const F = (field: string, required: boolean, shared = false, none = false): ImportFieldInfo =>
  ({ field, label: field.toUpperCase(), description: "", required, shared_allowed: shared, none_allowed: none });
const FIELDS = [F("student_id", true), F("subject", true, true), F("textbook_id", true, false, true), F("item_id", false, false, true)];

function ins(headers: string[], suggested: Record<string, string>, ambiguous: Record<string, string[]> = {}, headerRow = 1): SheetInspection {
  return {
    sheet: "Л", hidden: false, problem: null, width: headers.length,
    header_suggestion: { row: headerRow, confidence: "high", reason: "" }, preview: [], header_rows_allowed: [headerRow],
    header_row: headerRow,
    columns: headers.map((h, i) => ({ id: `c${i}`, letter: String.fromCharCode(65 + i), header: h, label: h || `Столбец ${i}`, samples: ["x"], empty: false })),
    suggestions: {
      suggested: Object.fromEntries(Object.entries(suggested).map(([f, c]) => [f, { column: c, confidence: "alias" as const }])),
      ambiguous: Object.fromEntries(Object.entries(ambiguous).map(([f, cs]) => [f, cs.map((c) => ({ column: c, reason: "Неоднозначно." }))])),
    },
    notices: [], duplicate_headers: [],
  };
}

describe("guided import mapping logic", () => {
  it("preselects only unambiguous suggestions", () => {
    const i = ins(["Код ученика", "Учебник"], { student_id: "c0" }, { textbook_id: ["c1"] });
    expect(initialMapping(i)).toEqual({ student_id: { source: "column", column: "c0" } });
    const p = fieldProblems(FIELDS, initialMapping(i), i);
    expect(p.textbook_id.map((x) => x.kind)).toEqual(["missing", "ambiguous"]);
    expect(p.textbook_id[1].message).toContain("B «Учебник»");
    expect(p.subject[0].message).toBe("Выберите столбец для поля «SUBJECT» или задайте одно значение для всего файла.");
  });

  it("requires every required field and non-empty shared values", () => {
    const m = { student_id: { source: "column" as const, column: "c0" }, textbook_id: { source: "none" as const },
      subject: { source: "value" as const, value: "  " } };
    expect(requiredResolved(FIELDS, m)).toBe(false);
    expect(requiredResolved(FIELDS, { ...m, subject: { source: "value", value: "Математика" } })).toBe(true);
  });

  it("keeps choices across a header change only when the column header is unchanged", () => {
    const before = ins(["ID ученика", "Учебник"], {}, {}, 1);
    const after = ins(["ID ученика", "Код учебника"], { textbook_id: "c1" }, {}, 2);
    const prev = { student_id: { source: "column" as const, column: "c0" }, item_id: { source: "column" as const, column: "c1" },
      subject: { source: "value" as const, value: "Математика" } };
    const next = remapAfterHeaderChange(prev, before, after);
    expect(next).toEqual({ student_id: { source: "column", column: "c0" }, subject: { source: "value", value: "Математика" },
      textbook_id: { source: "column", column: "c1" } });
  });

  it("does not let a new suggestion take a column already kept for another field", () => {
    const before = ins(["A", "B"], {}, {}, 1);
    const after = ins(["A", "B"], { student_id: "c0" }, {}, 2);
    const next = remapAfterHeaderChange({ item_id: { source: "column", column: "c0" } }, before, after);
    expect(next).toEqual({ item_id: { source: "column", column: "c0" } });
  });

  it("builds the request payload with trimmed shared values and lists ignored columns", () => {
    const i = ins(["Код ученика", "Примечание"], { student_id: "c0" });
    const m = { ...initialMapping(i), subject: selectToChoice("__value", undefined), item_id: undefined };
    m.subject = { source: "value", value: " Математика " };
    expect(validatePayload("k", "Л", 3, m, true)).toEqual({ session_key: "k", sheet: "Л", header_row: 3, confirm_shared: true,
      fields: { student_id: { source: "column", column: "c0" }, subject: { source: "value", value: "Математика" } } });
    expect(ignoredColumns(i, m).map((c) => c.header)).toEqual(["Примечание"]);
  });

  it("maps select values to explicit choices", () => {
    expect(selectToChoice("", undefined)).toBeUndefined();
    expect(selectToChoice("__none", undefined)).toEqual({ source: "none" });
    expect(selectToChoice("__value", { source: "value", value: "pre" })).toEqual({ source: "value", value: "pre" });
    expect(selectToChoice("c3", undefined)).toEqual({ source: "column", column: "c3" });
  });

  it("attaches server configuration issues to their field", () => {
    const p = fieldProblems(FIELDS, {}, null, [{ code: "COLUMN_REUSED", message: "Столбец уже выбран.", field: "student_id", column: "c0" }]);
    expect(p.student_id.map((x) => x.kind)).toEqual(["missing", "server"]);
  });
});
