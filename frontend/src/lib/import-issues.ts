// Russian explanations for import validation codes; codes stay available as technical details.

import type { ImportPreview, ValidationIssue } from "./types";

export const ISSUE_TITLE: Record<string, string> = {
  MISSING_COLUMN: "Нет обязательного столбца",
  UNKNOWN_COLUMN: "Неизвестный столбец",
  DUPLICATE_COLUMN: "Столбец повторяется",
  EMPTY_FILE: "Файл пустой",
  BLANK_ROWS: "Пустые строки",
  MISSING_VALUE: "Не заполнено обязательное значение",
  INVALID_IDENTIFIER: "Недопустимый идентификатор",
  POSSIBLE_PERSONAL_DATA: "Похоже на персональные данные (ФИО)",
  INVALID_NUMBER: "Не число",
  AMBIGUOUS_NUMBER: "Неоднозначная запись числа",
  NEGATIVE_SCORE: "Отрицательный балл",
  NON_POSITIVE_MAX: "Максимальный балл должен быть больше нуля",
  SCORE_EXCEEDS_MAX: "Балл больше максимального",
  INVALID_DATE: "Неверная дата",
  INVALID_GRADE: "Неверная параллель",
  INVALID_ASSESSMENT_TYPE: "Неверный тип оценивания",
  INVALID_HOURS: "Неверное число часов",
  MISSING_HOURS: "Не указаны часы",
  INVALID_TOPIC_SETTING: "Неверный параметр темы",
  INVALID_PREREQUISITE: "Неверная предшествующая тема",
  UNKNOWN_PREREQUISITE: "Неизвестная предшествующая тема",
  MISSING_COMPARISON_GROUP: "Не указана группа сравнения",
  MISSING_TEXTBOOK: "Не указан учебник",
  DUPLICATE_ROW: "Повторяющаяся строка",
  MIXED_GRANULARITY: "Смешаны итог по теме и отдельные задания",
  CONFLICT: "Противоречие внутри файла",
  CONFLICT_WITH_DB: "Противоречит уже загруженным данным",
  TOPIC_SETTINGS_DIFFER: "Параметры темы отличаются от сохранённых",
  TEXTBOOK_NAME_DIFFERS: "Название учебника отличается от сохранённого",
  TEACHING_HOURS_REPLACED: "Часы темы будут заменены",
  ALREADY_IMPORTED: "Строки уже загружены",
  FORMULA_WITHOUT_VALUE: "Формула без сохранённого значения",
  REPEATED_HEADER: "Повтор заголовка внутри данных",
  ROWS_WITHOUT_MAPPED_DATA: "Строки без данных в выбранных столбцах",
  WIDE_LAYOUT_SUSPECTED: "Неподдерживаемая структура таблицы",
  MISSING_MAPPING: "Не выбран источник поля",
  COLUMN_REUSED: "Столбец выбран дважды",
  INVALID_SHARED_VALUE: "Неверное значение для всего файла",
  SHARED_NOT_CONFIRMED: "Значения для всего файла не подтверждены",
  STALE_PREVIEW: "Предпросмотр устарел",
  PREVIEW_EXPIRED: "Срок предпросмотра истёк",
};

/** Plain-language names for the exact spreadsheet headers (the header itself is always shown too). */
export const COLUMN_LABEL: Record<string, string> = {
  school: "Школа",
  student_id: "Идентификатор ученика",
  grade: "Параллель",
  class: "Класс",
  subject: "Предмет",
  topic_id: "Код темы",
  topic_name: "Название темы",
  assessment_id: "Код оценивания",
  assessment_type: "Тип оценивания",
  assessment_date: "Дата оценивания",
  comparison_group: "Группа сравнения",
  item_id: "Код задания",
  score: "Балл",
  max_score: "Максимальный балл",
  textbook_id: "Код учебника",
  textbook_name: "Название учебника",
  teaching_hours: "Часы на тему",
  topic_min_hours: "Мин. часов темы",
  topic_max_hours: "Макс. часов темы",
  topic_priority: "Приоритет темы",
  topic_prerequisites: "Предшествующие темы",
  topic_order: "Порядок темы",
};

export function issueTitle(code: string): string {
  return ISSUE_TITLE[code] ?? "Ошибка в данных";
}

export function columnLabel(column: string | null): { label: string; header: string } | null {
  if (!column) return null;
  const headers = column.split(",").map((c) => c.trim()).filter(Boolean);
  return { header: headers.join(", "), label: headers.map((h) => COLUMN_LABEL[h] ?? h).join(", ") };
}

export interface RowGroup {
  row: number | null;
  issues: ValidationIssue[];
}

/** Group listed issues by spreadsheet row; file-level issues (row = null) come first. */
export function groupByRow(issues: ValidationIssue[]): RowGroup[] {
  const map = new Map<number | null, ValidationIssue[]>();
  for (const i of issues) map.set(i.row, [...(map.get(i.row) ?? []), i]);
  return [...map.entries()]
    .sort(([a], [b]) => (a === null ? -1 : b === null ? 1 : a - b))
    .map(([row, list]) => ({ row, issues: list }));
}

export interface ErrorSummary {
  /** Distinct affected rows among listed errors. */
  rows: number;
  /** True when the server listed every error, so the row count is exact. */
  rowsExact: boolean;
  errors: number;
  fileLevel: number;
  /** "Исправьте 2 строки. Найдено 4 ошибки; данные ещё не импортированы." */
  headline: string;
}

function plural(n: number, one: string, few: string, many: string): string {
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
  return many;
}

export function summarizeErrors(p: Pick<ImportPreview, "errors" | "error_count">): ErrorSummary {
  const rowSet = new Set(p.errors.filter((e) => e.row !== null).map((e) => e.row));
  const rowsExact = p.errors.length >= p.error_count;
  const fileLevel = p.errors.filter((e) => e.row === null).length;
  const rows = rowSet.size;
  const errors = p.error_count;
  const rowPart = rows === 0 ? "" : rowsExact
    ? `Исправьте ${rows} ${plural(rows, "строку", "строки", "строк")}`
    : `Исправьте не менее ${rows} ${plural(rows, "строки", "строк", "строк")}`;
  const filePart = fileLevel ? `${rowPart ? " и " : "Исправьте "}структуру файла` : "";
  const errPart = `Найдено ${errors} ${plural(errors, "ошибка", "ошибки", "ошибок")}; данные ещё не импортированы.`;
  return { rows, rowsExact, errors, fileLevel, headline: `${rowPart}${filePart}. ${errPart}`.replace(/^\. /, "") };
}

export function pluralRu(n: number, one: string, few: string, many: string): string {
  return plural(n, one, few, many);
}
