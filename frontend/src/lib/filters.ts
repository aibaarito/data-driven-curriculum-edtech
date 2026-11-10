export interface Filters {
  subject_id?: number;
  grade?: number;
  class_id?: number;
  textbook_id?: number;
  date_from?: string;
  date_to?: string;
}

export const FILTER_KEYS = ["subject_id", "grade", "class_id", "textbook_id", "date_from", "date_to"] as const;
const NUMERIC = new Set(["subject_id", "grade", "class_id", "textbook_id"]);
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

/** Parse filters from URL params, dropping anything malformed instead of sending it to the API. */
export function parseFilters(params: URLSearchParams | { get(key: string): string | null }): Filters {
  const out: Filters = {};
  for (const key of FILTER_KEYS) {
    const raw = params.get(key);
    if (!raw) continue;
    if (NUMERIC.has(key)) {
      const n = Number(raw);
      if (Number.isInteger(n) && n > 0) (out as Record<string, number>)[key] = n;
    } else if (DATE_RE.test(raw)) {
      (out as Record<string, string>)[key] = raw;
    }
  }
  return out;
}

export function toQuery(f: Filters): string {
  const p = new URLSearchParams();
  for (const key of FILTER_KEYS) {
    const v = f[key];
    if (v !== undefined && v !== null && v !== "") p.set(key, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

export function activeFilterCount(f: Filters): number {
  return FILTER_KEYS.filter((k) => f[k] !== undefined).length;
}
