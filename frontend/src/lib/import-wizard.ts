// Pure logic of the guided import (no React): initial mappings from server suggestions, preserving choices when
// the header row changes, client-side mapping problems and the request payload. The backend re-validates all of it.

import type { ConfigIssue, FieldChoice, ImportFieldInfo, SheetInspection } from "./types";

export type Mapping = Record<string, FieldChoice | undefined>;

/** Suggested mapping: only unambiguous suggestions are preselected; ambiguous fields stay unresolved. */
export function initialMapping(inspection: SheetInspection | null): Mapping {
  const out: Mapping = {};
  if (!inspection) return out;
  const { suggested, ambiguous } = inspection.suggestions;
  for (const [field, s] of Object.entries(suggested)) {
    if (!ambiguous[field]) out[field] = { source: "column", column: s.column };
  }
  return out;
}

/**
 * After a header-row change keep a column choice only if the same column position still has the same header text;
 * shared values and "not in file" choices do not depend on the header and are kept. Otherwise use new suggestions.
 */
export function remapAfterHeaderChange(prev: Mapping, before: SheetInspection, after: SheetInspection): Mapping {
  const headerOf = (ins: SheetInspection, id: string) => ins.columns.find((c) => c.id === id)?.header;
  const next: Mapping = {};
  const used = new Set<string>();
  for (const [field, choice] of Object.entries(prev)) {
    if (!choice) continue;
    if (choice.source !== "column") {
      next[field] = choice;
      continue;
    }
    const h = headerOf(before, choice.column);
    if (h && h === headerOf(after, choice.column)) {
      next[field] = choice;
      used.add(choice.column);
    }
  }
  // New suggestions fill only fields without a kept choice and never reuse a kept column.
  for (const [field, choice] of Object.entries(initialMapping(after))) {
    if (!next[field] && choice?.source === "column" && !used.has(choice.column)) next[field] = choice;
  }
  return next;
}

export function usedColumns(mapping: Mapping, exceptField?: string): Map<string, string> {
  const m = new Map<string, string>();
  for (const [field, c] of Object.entries(mapping)) {
    if (field !== exceptField && c?.source === "column") m.set(c.column, field);
  }
  return m;
}

export interface FieldProblem {
  kind: "missing" | "ambiguous" | "value" | "server";
  message: string;
}

/** Problems shown next to each field before the request is sent (the server repeats every check). */
export function fieldProblems(fields: ImportFieldInfo[], mapping: Mapping, inspection: SheetInspection | null,
  serverIssues: ConfigIssue[] = []): Record<string, FieldProblem[]> {
  const out: Record<string, FieldProblem[]> = {};
  const add = (f: string, p: FieldProblem) => (out[f] = [...(out[f] ?? []), p]);
  for (const f of fields) {
    const c = mapping[f.field];
    if (f.required && !c) {
      const extra = f.shared_allowed ? " или задайте одно значение для всего файла"
        : f.none_allowed ? " или отметьте, что учебника в файле нет" : "";
      add(f.field, { kind: "missing", message: `Выберите столбец для поля «${f.label}»${extra}.` });
    }
    if (c?.source === "value" && !c.value.trim()) add(f.field, { kind: "value", message: `Введите значение для поля «${f.label}».` });
    const amb = inspection?.suggestions.ambiguous[f.field];
    if (amb && !c) {
      const cols = amb.map((a) => {
        const col = inspection?.columns.find((x) => x.id === a.column);
        return col ? `${col.letter} «${col.label}»` : a.column;
      });
      add(f.field, { kind: "ambiguous", message: `Возможные столбцы: ${cols.join(", ")}. ${amb[0].reason}` });
    }
  }
  for (const i of serverIssues) {
    if (i.field) add(i.field, { kind: "server", message: i.message });
  }
  return out;
}

export function sharedChoices(fields: ImportFieldInfo[], mapping: Mapping): { field: string; label: string; value: string }[] {
  return fields.flatMap((f) => {
    const c = mapping[f.field];
    return c?.source === "value" ? [{ field: f.field, label: f.label, value: c.value }] : [];
  });
}

export function requiredResolved(fields: ImportFieldInfo[], mapping: Mapping): boolean {
  return fields.every((f) => {
    const c = mapping[f.field];
    if (!f.required) return c?.source !== "value" || c.value.trim() !== "";
    return !!c && (c.source !== "value" || c.value.trim() !== "");
  });
}

/** Request body for POST /api/imports/{id}/validate. Unresolved optional fields are simply omitted. */
export function validatePayload(sessionKey: string, sheet: string, headerRow: number, mapping: Mapping,
  confirmShared: boolean) {
  const fields: Record<string, FieldChoice> = {};
  for (const [f, c] of Object.entries(mapping)) {
    if (!c) continue;
    fields[f] = c.source === "value" ? { source: "value", value: c.value.trim() } : c;
  }
  return { session_key: sessionKey, sheet, header_row: headerRow, fields, confirm_shared: confirmShared };
}

/** Columns that no field uses; shown as "will be ignored". */
export function ignoredColumns(inspection: SheetInspection | null, mapping: Mapping) {
  if (!inspection) return [];
  const used = usedColumns(mapping);
  return inspection.columns.filter((c) => !used.has(c.id) && !(c.empty && !c.header));
}

export const SELECT_NONE = "";
export const SELECT_VALUE = "__value";
export const SELECT_ABSENT = "__none";

export function choiceToSelect(c: FieldChoice | undefined): string {
  if (!c) return SELECT_NONE;
  if (c.source === "column") return c.column;
  return c.source === "value" ? SELECT_VALUE : SELECT_ABSENT;
}

export function selectToChoice(v: string, prev: FieldChoice | undefined): FieldChoice | undefined {
  if (v === SELECT_NONE) return undefined;
  if (v === SELECT_VALUE) return { source: "value", value: prev?.source === "value" ? prev.value : "" };
  if (v === SELECT_ABSENT) return { source: "none" };
  return { source: "column", column: v };
}
