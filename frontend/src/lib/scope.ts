// Analytical scope: which filters each screen applies, human-readable scope labels and filter conflicts.
// Filters travel with navigation unchanged; a screen that cannot apply one says so instead of silently dropping it.

import { FILTER_KEYS, toQuery, type Filters } from "./filters";
import type { Meta } from "./types";

type Key = (typeof FILTER_KEYS)[number];

/** Filters each screen actually applies. Screens not listed apply none (import, settings). */
export const SCREEN_FILTERS: Record<string, readonly Key[]> = {
  "/": FILTER_KEYS,
  "/topics": FILTER_KEYS,
  "/insights": FILTER_KEYS,
  "/reports": FILTER_KEYS,
  // Textbooks are compared across classes of one grade: a class or a single textbook cannot form a comparison.
  "/textbooks": ["subject_id", "grade", "date_from", "date_to"],
  // One hours plan per subject and grade: class, textbook and period do not apply.
  "/optimizer": ["subject_id", "grade"],
};

const KEY_LABEL: Record<Key, string> = {
  subject_id: "предмет",
  grade: "параллель",
  class_id: "класс",
  textbook_id: "учебник",
  date_from: "дата оценивания с",
  date_to: "дата оценивания по",
};

function dateRu(iso: string): string {
  const [y, m, d] = iso.split("-");
  return `${d}.${m}.${y}`;
}

export function periodLabel(f: Filters): string {
  if (!f.date_from && !f.date_to) return "весь период";
  return `${f.date_from ? dateRu(f.date_from) : "…"} — ${f.date_to ? dateRu(f.date_to) : "…"}`;
}

export interface ScopeParts {
  subject: string;
  grade: string;
  cls: string;
  textbook: string;
  period: string;
}

export function scopeParts(f: Filters, meta: Meta | null | undefined): ScopeParts {
  const subject = f.subject_id ? meta?.subjects.find((s) => s.id === f.subject_id)?.name ?? `предмет #${f.subject_id}` : "все предметы";
  const grade = f.grade ? `${f.grade} класс` : "все параллели";
  const cls = f.class_id ? `класс ${meta?.classes.find((c) => c.id === f.class_id)?.name ?? `#${f.class_id}`}` : "все классы";
  const textbook = f.textbook_id ? meta?.textbooks.find((t) => t.id === f.textbook_id)?.name ?? `учебник #${f.textbook_id}` : "все учебники";
  return { subject, grade, cls, textbook, period: periodLabel(f) };
}

/** "Математика · 7 класс · все классы · весь период" — only the filters the given screen applies. */
export function scopeLabel(f: Filters, meta: Meta | null | undefined, screen = "/"): string {
  const keys = SCREEN_FILTERS[screen] ?? FILTER_KEYS;
  const p = scopeParts(f, meta);
  const out = [p.subject.charAt(0).toUpperCase() + p.subject.slice(1), p.grade];
  if (keys.includes("class_id")) out.push(p.cls);
  if (keys.includes("textbook_id") && f.textbook_id) out.push(p.textbook);
  if (keys.includes("date_from")) out.push(p.period);
  return out.join(" · ");
}

/** Filters present in the URL that this screen does not apply (kept for other screens, explained here). */
export function inapplicableFilters(screen: string, f: Filters, meta: Meta | null | undefined): string[] {
  const keys = SCREEN_FILTERS[screen];
  if (!keys) return [];
  const p = scopeParts(f, meta);
  const out: string[] = [];
  if (f.class_id && !keys.includes("class_id")) out.push(p.cls);
  if (f.textbook_id && !keys.includes("textbook_id")) out.push(`учебник «${p.textbook}»`);
  if ((f.date_from || f.date_to) && !keys.includes("date_from")) out.push(`период ${p.period}`);
  return out;
}

export interface FilterConflict {
  key: Key;
  message: string;
}

/** Dependent values that contradict each other or no longer exist. Results are then empty, never broadened. */
export function filterConflicts(f: Filters, meta: Meta | null | undefined): FilterConflict[] {
  if (!meta) return [];
  const out: FilterConflict[] = [];
  if (f.subject_id && !meta.subjects.some((s) => s.id === f.subject_id))
    out.push({ key: "subject_id", message: "Выбранный предмет не найден в данных." });
  if (f.grade && !meta.grades.includes(f.grade))
    out.push({ key: "grade", message: `Параллели ${f.grade} нет в данных.` });
  const cls = f.class_id ? meta.classes.find((c) => c.id === f.class_id) : undefined;
  if (f.class_id && !cls) out.push({ key: "class_id", message: "Выбранный класс не найден в данных." });
  else if (cls && f.grade && cls.grade !== f.grade)
    out.push({ key: "class_id", message: `Класс ${cls.name} относится к ${cls.grade} параллели, а выбрана параллель ${f.grade}.` });
  const tb = f.textbook_id ? meta.textbooks.find((t) => t.id === f.textbook_id) : undefined;
  if (f.textbook_id && !tb) out.push({ key: "textbook_id", message: "Выбранный учебник не найден в данных." });
  else if (tb && f.subject_id && tb.subject_id !== f.subject_id)
    out.push({ key: "textbook_id", message: `Учебник «${tb.name}» относится к другому предмету.` });
  if (f.date_from && f.date_to && f.date_from > f.date_to)
    out.push({ key: "date_from", message: "Дата «с» позже даты «по»." });
  return out;
}

/** Navigation target carrying the current filters (subject, grade, class, textbook, period) unchanged. */
export function scopedHref(target: string, f: Filters): string {
  return `${target}${toQuery(f)}`;
}

export function filterKeyLabel(key: Key): string {
  return KEY_LABEL[key];
}
