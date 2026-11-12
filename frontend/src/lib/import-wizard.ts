// Pure logic of the guided import (no React): initial mappings from server suggestions, preserving choices when
// the header row changes, client-side mapping problems and the request payload. The backend re-validates all of it.

import type { ConfigIssue, FieldChoice, ImportFieldInfo, Layout, RegionSelection, SheetInspection } from "./types";

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

// ----------------------------------------------------------------------------- layouts, rules and payload

export type ScoreMode = "points" | "percent" | "binary" | "scale";

export interface RulesState {
  decimal: "auto" | "comma" | "dot";
  date_format: string;
  missing_markers: string[];
  score_mode: ScoreMode;
  percent_scale: "0-100" | "0-1";
  true_tokens: string[];
  false_tokens: string[];
  /** source value -> percent text, entered by the user */
  scale: Record<string, string>;
}

export const DEFAULT_RULES: RulesState = {
  decimal: "auto", date_format: "auto", missing_markers: [], score_mode: "points", percent_scale: "0-100",
  true_tokens: [], false_tokens: [], scale: {},
};

export interface ResultColumnSpec {
  column: string;
  topic_id: string;
  topic_name: string;
  item_id: string;
  max_score: string;
  assessment_id: string;
  assessment_type: string;
  assessment_date: string;
}

export interface MetricState { kind: "" | "percent" | "mean_points"; max_value: string; percent_scale: "0-100" | "0-1" }

export interface PrepState {
  layout: Layout;
  mapping: Mapping;
  resultColumns: ResultColumnSpec[];
  roles: Record<string, string>;
  metric: MetricState;
  types: Record<string, string>;
  datasetName: string;
  rules: RulesState;
  confirmShared: boolean;
}

export function emptyResultColumn(column: string, topicName = ""): ResultColumnSpec {
  return { column, topic_id: "", topic_name: topicName, item_id: "", max_score: "", assessment_id: "", assessment_type: "", assessment_date: "" };
}

/** Initial interpretation from the server's suggestions. Every suggestion stays visible and editable. */
export function initialPrep(inspection: SheetInspection | null): PrepState {
  const layout = inspection?.layout_suggestion?.layout ?? "long";
  const wide = inspection?.wide_suggestion;
  const mapping = initialMapping(inspection);
  if (layout === "wide") {
    for (const f of ["topic_id", "topic_name", "item_id", "score", "max_score"]) delete mapping[f];
  }
  return {
    layout,
    mapping,
    // Result columns are proposed with the header as topic name; codes and maxima are never invented.
    resultColumns: (wide?.result_columns ?? []).map((r) => emptyResultColumn(r.column, r.topic_name)),
    roles: Object.fromEntries(Object.entries(inspection?.aggregate_suggestion ?? {})),
    metric: { kind: "", max_value: "", percent_scale: "0-100" },
    types: { ...(inspection?.type_suggestion ?? {}) },
    datasetName: "",
    rules: { ...DEFAULT_RULES },
    confirmShared: false,
  };
}

/** Field list for a layout: wide gradebooks take topic/item/score/maximum from result columns. */
export function fieldsForLayout(fields: ImportFieldInfo[], layout: Layout, rules: RulesState): ImportFieldInfo[] {
  if (layout === "wide") return fields.filter((f) => !f.wide_result);
  if (layout !== "long") return [];
  return fields.map((f) => (f.field === "max_score" && rules.score_mode !== "points" ? { ...f, required: false } : f));
}

const PER_COLUMN_ASSESSMENT = ["assessment_id", "assessment_type", "assessment_date"] as const;

/** Wide: an assessment field is covered when every selected result column has its own value. */
export function coveredByColumns(prep: PrepState): Set<string> {
  const out = new Set<string>();
  if (!prep.resultColumns.length) return out;
  for (const f of PER_COLUMN_ASSESSMENT) {
    if (prep.resultColumns.every((rc) => rc[f].trim() !== "")) out.add(f);
  }
  return out;
}

export interface PrepProblems {
  fields: Record<string, FieldProblem[]>;
  general: string[];
  columns: Record<string, string[]>;
}

export function prepProblems(fields: ImportFieldInfo[], prep: PrepState, inspection: SheetInspection | null,
  serverIssues: ConfigIssue[] = []): PrepProblems {
  const out: PrepProblems = { fields: {}, general: [], columns: {} };
  const addCol = (c: string, m: string) => (out.columns[c] = [...(out.columns[c] ?? []), m]);
  if (prep.layout === "long" || prep.layout === "wide") {
    const covered = prep.layout === "wide" ? coveredByColumns(prep) : new Set<string>();
    const fl = fieldsForLayout(fields, prep.layout, prep.rules).map((f) => (covered.has(f.field) ? { ...f, required: false } : f));
    out.fields = fieldProblems(fl, prep.mapping, inspection, serverIssues.filter((i) => !i.column || prep.layout === "long"));
    if (prep.layout === "long" && prep.rules.score_mode !== "points" && prep.mapping.max_score) {
      out.fields.max_score = [...(out.fields.max_score ?? []), { kind: "value", message: "При выбранном способе записи результата максимум задаётся правилом — уберите сопоставление." }];
    }
  }
  if (prep.layout === "wide") {
    if (!prep.resultColumns.length) out.general.push("Выберите хотя бы один столбец с результатами.");
    for (const rc of prep.resultColumns) {
      if (!rc.topic_id.trim()) addCol(rc.column, "Укажите код темы.");
      if (!rc.topic_name.trim()) addCol(rc.column, "Укажите название темы.");
      if (prep.rules.score_mode === "points" && !rc.max_score.trim()) addCol(rc.column, "Укажите максимальный балл.");
      if (prep.rules.score_mode !== "points" && rc.max_score.trim()) addCol(rc.column, "Максимум задаётся правилом результата — очистите поле.");
      for (const f of PER_COLUMN_ASSESSMENT) {
        if (rc[f].trim() && prep.mapping[f]) addCol(rc.column, `«${f}» уже задано для всех строк — очистите одно из значений.`);
      }
    }
  }
  if (prep.layout === "aggregate") {
    const roles = Object.values(prep.roles);
    if (!roles.includes("value")) out.general.push("Выберите столбец с показателем (средний балл, процент…).");
    if (!roles.some((r) => ["class", "topic_name", "topic_id", "textbook", "grade"].includes(r))) {
      out.general.push("Выберите хотя бы один столбец группы: класс, тему, параллель или учебник.");
    }
    if (!prep.metric.kind) out.general.push("Укажите, что означает показатель: процент или средний балл.");
    if (prep.metric.kind === "mean_points" && !roles.includes("max") && !prep.metric.max_value.trim()) {
      out.general.push("Для среднего балла укажите максимальный балл или столбец максимума.");
    }
    const dup = roles.filter((r, i) => roles.indexOf(r) !== i);
    if (dup.length) out.general.push("Каждая роль может быть назначена только одному столбцу.");
  }
  if (prep.layout === "long" || prep.layout === "wide") {
    const r = prep.rules;
    if (r.score_mode === "binary" && (!r.true_tokens.length || !r.false_tokens.length)) {
      out.general.push("Укажите значения «верно» и «неверно».");
    }
    if (r.score_mode === "scale") {
      const entries = Object.entries(r.scale).filter(([, v]) => v.trim() !== "");
      if (!entries.length) out.general.push("Заполните таблицу перевода отметок в проценты.");
      if (entries.some(([, v]) => !/^\d+([.,]\d+)?$/.test(v.trim()) || Number(v.replace(",", ".")) > 100)) {
        out.general.push("Проценты в таблице шкалы — числа от 0 до 100.");
      }
    }
  }
  for (const i of serverIssues) {
    if (i.column && prep.layout !== "long") addCol(i.column, i.message);
    else if (!i.field) out.general.push(i.message);
  }
  return out;
}

export function prepReady(fields: ImportFieldInfo[], prep: PrepState, inspection: SheetInspection | null): boolean {
  const p = prepProblems(fields, prep, inspection);
  const blocking = Object.values(p.fields).some((list) => list.some((x) => x.kind !== "ambiguous"));
  const sharedOk = sharedChoices(fields, prep.mapping).length === 0 || prep.confirmShared;
  return !blocking && !p.general.length && !Object.keys(p.columns).length && sharedOk;
}

function rulesPayload(r: RulesState) {
  return {
    decimal: r.decimal, date_format: r.date_format, missing_markers: r.missing_markers, score_mode: r.score_mode,
    percent_scale: r.percent_scale, true_tokens: r.true_tokens, false_tokens: r.false_tokens,
    scale: Object.fromEntries(Object.entries(r.scale).filter(([, v]) => v.trim() !== "")),
  };
}

/** Full request body for POST /api/imports/{id}/validate. The server re-validates every part. */
export function buildPayload(sessionKey: string, sheet: string, csv: { encoding: string; delimiter: string },
  region: RegionSelection, prep: PrepState) {
  const base = { ...validatePayload(sessionKey, sheet, region.header_row, prep.mapping, prep.confirmShared), ...region, csv, layout: prep.layout };
  if (prep.layout === "long") return { ...base, rules: rulesPayload(prep.rules) };
  if (prep.layout === "wide") {
    return {
      ...base, rules: rulesPayload(prep.rules),
      result_columns: prep.resultColumns.map((rc) => Object.fromEntries(Object.entries(rc).filter(([, v]) => v.trim() !== ""))),
    };
  }
  if (prep.layout === "aggregate") {
    return { ...base, fields: {}, confirm_shared: false, roles: prep.roles, dataset_name: prep.datasetName,
      rules: { decimal: prep.rules.decimal }, metric: prep.metric.kind ? { kind: prep.metric.kind, percent_scale: prep.metric.percent_scale,
        ...(prep.metric.max_value.trim() ? { max_value: prep.metric.max_value.trim() } : {}) } : {} };
  }
  return { ...base, fields: {}, confirm_shared: false, types: prep.types, dataset_name: prep.datasetName };
}

const TRANSLIT: Record<string, string> = {
  а: "a", б: "b", в: "v", г: "g", д: "d", е: "e", ё: "e", ж: "zh", з: "z", и: "i", й: "y", к: "k", л: "l", м: "m",
  н: "n", о: "o", п: "p", р: "r", с: "s", т: "t", у: "u", ф: "f", х: "h", ц: "ts", ч: "ch", ш: "sh", щ: "sch",
  ъ: "", ы: "y", ь: "", э: "e", ю: "yu", я: "ya", ә: "a", ғ: "g", қ: "k", ң: "n", ө: "o", ұ: "u", ү: "u", һ: "h", і: "i",
};

/**
 * Deterministic technical code from a header, used only when the user presses «Коды из заголовков».
 * It is visible and editable; equal codes mean the same topic in the database, so the user must check them.
 */
export function codeFromHeader(header: string, taken: Set<string>): string {
  const base = header.toLowerCase().split("").map((ch) => TRANSLIT[ch] ?? ch).join("")
    .replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").toUpperCase().slice(0, 40) || "TOPIC";
  let code = base;
  for (let i = 2; taken.has(code); i++) code = `${base.slice(0, 36)}-${i}`;
  taken.add(code);
  return code;
}

/** Distinct values of the chosen result columns (from the bounded profile), to seed the scale table. */
export function observedValues(inspection: SheetInspection | null, columnIds: string[]): string[] {
  const out = new Set<string>();
  for (const c of inspection?.columns ?? []) {
    if (columnIds.includes(c.id)) for (const v of c.profile?.distinct ?? []) out.add(v);
  }
  return [...out].slice(0, 30);
}
