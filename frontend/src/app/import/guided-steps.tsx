"use client";

// Guided import steps: worksheet, header row and column mapping. All user-provided text (sheet names, headers,
// cell values) is rendered as React text nodes, never as HTML.

import { AlertTriangle, EyeOff, Info } from "lucide-react";
import { useId } from "react";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  choiceToSelect,
  type FieldProblem,
  fieldProblems,
  ignoredColumns,
  type Mapping,
  selectToChoice,
  SELECT_ABSENT,
  SELECT_NONE,
  SELECT_VALUE,
  usedColumns,
} from "@/lib/import-wizard";
import type { ConfigIssue, FieldChoice, ImportFieldInfo, SheetInspection, SheetSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

export const selectClass =
  "h-9 w-full min-w-0 rounded-lg border border-input bg-background px-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 aria-invalid:border-destructive disabled:opacity-50";

// --------------------------------------------------------------------------- worksheet

export function SheetStep({ sheets, selected, suggestion, disabled, onSelect }: {
  sheets: SheetSummary[];
  selected: string | null;
  suggestion: { name: string | null; reason: string };
  disabled: boolean;
  onSelect: (name: string) => void;
}) {
  const name = useId();
  return (
    <fieldset className="space-y-2" data-testid="sheet-step">
      <legend className="mb-1 text-sm font-medium">Лист книги</legend>
      <p className="text-xs text-muted-foreground" id={`${name}-hint`}>
        {suggestion.name ? `Предложен лист «${suggestion.name}»: ${suggestion.reason}` : suggestion.reason} Импортируется только один выбранный лист.
      </p>
      <div className="grid gap-2 sm:grid-cols-2">
        {sheets.map((s) => {
          const unusable = !!s.problem || s.empty;
          const id = `${name}-${s.name}`;
          return (
            <label
              key={s.name}
              htmlFor={id}
              className={cn(
                "flex cursor-pointer items-start gap-2 rounded-lg border p-3 text-sm has-[:checked]:border-primary has-[:checked]:bg-primary/5 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring",
                unusable && "cursor-not-allowed opacity-60",
              )}
            >
              <input
                id={id}
                type="radio"
                name={name}
                className="mt-1"
                checked={selected === s.name}
                disabled={disabled || unusable}
                onChange={() => onSelect(s.name)}
                aria-describedby={`${name}-hint`}
              />
              <span className="min-w-0">
                <span className="block break-words font-medium">{s.name}</span>
                <span className="mt-1 flex flex-wrap gap-1">
                  {s.hidden && <Badge variant="outline"><EyeOff className="size-3" aria-hidden /> скрытый лист</Badge>}
                  {s.empty && <Badge variant="outline">пустой</Badge>}
                  {s.known_headers >= 3 && <Badge variant="secondary">похож на таблицу результатов</Badge>}
                </span>
                <span className="mt-1 block text-xs text-muted-foreground">
                  {s.problem ?? (s.empty ? "На листе нет данных." : `Непустых строк: ${s.non_empty_rows}, столбцов: ${s.columns}`)}
                </span>
              </span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

// --------------------------------------------------------------------------- header row

const MAX_PREVIEW_COLS = 12;

export function HeaderStep({ inspection, disabled, onChange }: {
  inspection: SheetInspection;
  disabled: boolean;
  onChange: (row: number) => void;
}) {
  const id = useId();
  const hs = inspection.header_suggestion;
  const header = inspection.header_row;
  const rows = inspection.preview.slice(0, 15);
  const width = Math.min(inspection.width, MAX_PREVIEW_COLS);
  const rowText = (r: number) => {
    const cells = inspection.preview.find((p) => p.row === r)?.cells.filter(Boolean) ?? [];
    const t = cells.slice(0, 4).join(", ");
    return t.length > 70 ? `${t.slice(0, 70)}…` : t;
  };
  return (
    <div className="space-y-3" data-testid="header-step">
      <div className="grid gap-2 sm:max-w-xl">
        <label htmlFor={id} className="text-sm font-medium">Строка с названиями столбцов</label>
        <select
          id={id}
          className={selectClass}
          value={header ?? ""}
          disabled={disabled}
          aria-describedby={`${id}-hint`}
          data-testid="header-row-select"
          onChange={(e) => onChange(Number(e.target.value))}
        >
          {header === null && <option value="">— выберите строку —</option>}
          {inspection.header_rows_allowed.map((r) => (
            <option key={r} value={r}>Строка {r}{r === hs.row ? " (предложено)" : ""} — {rowText(r)}</option>
          ))}
        </select>
        <p id={`${id}-hint`} className="text-xs text-muted-foreground">
          {hs.row !== null ? hs.reason : "Заголовок не найден."} Строки выше заголовка не импортируются.
          {hs.confidence === "low" && " Предложение неуверенное — проверьте его по таблице ниже."}
        </p>
      </div>
      <div className="max-h-72 overflow-auto rounded-lg border" role="region" aria-label="Первые строки листа" tabIndex={0}>
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-muted">
            <tr>
              <th scope="col" className="px-2 py-1 text-left font-medium">Строка</th>
              {Array.from({ length: width }, (_, i) => (
                <th key={i} scope="col" className="px-2 py-1 text-left font-medium text-muted-foreground">{colLetter(i)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const isHeader = r.row === header;
              const above = header !== null && r.row < header;
              return (
                <tr key={r.row} className={cn("border-t", isHeader && "bg-primary/10 font-semibold", above && "text-muted-foreground")}>
                  <th scope="row" className="px-2 py-1 text-left font-normal whitespace-nowrap">
                    {r.row}{isHeader && <span className="sr-only"> (строка заголовка)</span>}
                    {isHeader && <Badge className="ml-1 h-4 px-1 text-[10px]">заголовок</Badge>}
                  </th>
                  {Array.from({ length: width }, (_, i) => (
                    <td key={i} className="max-w-48 truncate px-2 py-1" title={r.cells[i] ?? ""}>{r.cells[i] ?? ""}</td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {inspection.width > MAX_PREVIEW_COLS && (
        <p className="text-xs text-muted-foreground">Показаны первые {MAX_PREVIEW_COLS} из {inspection.width} столбцов; все столбцы доступны при сопоставлении.</p>
      )}
      {inspection.duplicate_headers.length > 0 && (
        <p className="flex gap-1.5 text-xs text-amber-800 dark:text-amber-300">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          Повторяющиеся заголовки: {inspection.duplicate_headers.map((d) => `«${d.header}» (${d.letters.join(", ")})`).join("; ")}.
          Столбцы различаются по буквам; выберите нужный при сопоставлении.
        </p>
      )}
    </div>
  );
}

export function colLetter(i: number): string {
  let s = "";
  let n = i + 1;
  while (n) {
    const rem = (n - 1) % 26;
    s = String.fromCharCode(65 + rem) + s;
    n = Math.floor((n - 1) / 26);
  }
  return s;
}

// --------------------------------------------------------------------------- mapping

const TYPE_OPTIONS: [string, string][] = [["pre", "pre — входная"], ["post", "post — итоговая"], ["current", "current — текущая"]];
const VALUE_HINT: Record<string, string> = {
  assessment_date: "ГГГГ-ММ-ДД или ДД.ММ.ГГГГ",
  grade: "Целое число 1–12",
  assessment_id: "Код без пробелов, например KR-2026-09",
  comparison_group: "Код без пробелов",
  school: "Код без пробелов",
};

export function MappingStep({ fields, inspection, mapping, issues, disabled, onChange, problemsOverride, title }: {
  fields: ImportFieldInfo[];
  inspection: SheetInspection;
  mapping: Mapping;
  issues: ConfigIssue[];
  disabled: boolean;
  onChange: (field: string, choice: FieldChoice | undefined) => void;
  problemsOverride?: Record<string, FieldProblem[]>;
  title?: string;
}) {
  const problems = problemsOverride ?? fieldProblems(fields, mapping, inspection, issues);
  const required = fields.filter((f) => f.required);
  const optional = fields.filter((f) => !f.required);
  const optionalActive = optional.some((f) => mapping[f.field]);
  const ignored = ignoredColumns(inspection, mapping);
  const generalIssues = issues.filter((i) => !i.field);
  const labels = Object.fromEntries(fields.map((f) => [f.field, f.label]));
  return (
    <div className="space-y-4" data-testid="mapping-step">
      {generalIssues.length > 0 && (
        <ul className="space-y-1 rounded-lg border border-danger/30 bg-danger/5 p-3 text-sm" role="alert">
          {generalIssues.map((i, k) => <li key={k}>{i.message}</li>)}
        </ul>
      )}
      {title && <p className="text-xs text-muted-foreground">{title}</p>}
      <FieldList fields={required} labels={labels} inspection={inspection} mapping={mapping} problems={problems} disabled={disabled} onChange={onChange} />
      <details className="rounded-lg border" open={optionalActive || undefined}>
        <summary className="cursor-pointer rounded-lg px-3 py-2 text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring">
          Необязательные поля ({optional.filter((f) => mapping[f.field]).length} из {optional.length} выбрано)
        </summary>
        <div className="px-3 pb-3">
          <FieldList fields={optional} labels={labels} inspection={inspection} mapping={mapping} problems={problems} disabled={disabled} onChange={onChange} />
        </div>
      </details>
      <div className="text-sm" data-testid="ignored-columns">
        <span className="font-medium">Не будут импортированы: </span>
        {ignored.length === 0 ? <span className="text-muted-foreground">все столбцы использованы.</span> : (
          <span className="text-muted-foreground">{ignored.map((c) => `${c.letter} «${c.label}»`).join(", ")}</span>
        )}
      </div>
    </div>
  );
}

function FieldList({ fields, labels, inspection, mapping, problems, disabled, onChange }: {
  fields: ImportFieldInfo[];
  labels: Record<string, string>;
  inspection: SheetInspection;
  mapping: Mapping;
  problems: ReturnType<typeof fieldProblems>;
  disabled: boolean;
  onChange: (field: string, choice: FieldChoice | undefined) => void;
}) {
  return (
    <ul className="divide-y rounded-lg border">
      {fields.map((f) => (
        <FieldRow key={f.field} info={f} labels={labels} inspection={inspection} mapping={mapping} problems={problems[f.field] ?? []}
          disabled={disabled} onChange={onChange} />
      ))}
    </ul>
  );
}

function FieldRow({ info, labels, inspection, mapping, problems, disabled, onChange }: {
  info: ImportFieldInfo;
  labels: Record<string, string>;
  inspection: SheetInspection;
  mapping: Mapping;
  problems: { kind: string; message: string }[];
  disabled: boolean;
  onChange: (field: string, choice: FieldChoice | undefined) => void;
}) {
  const id = `map-${info.field}`;
  const choice = mapping[info.field];
  const taken = usedColumns(mapping, info.field);
  const fieldLabel = (f: string) => labels[f] ?? f;
  const col = choice?.source === "column" ? inspection.columns.find((c) => c.id === choice.column) : undefined;
  const blocking = problems.filter((p) => p.kind !== "ambiguous" || !choice);
  const invalid = blocking.some((p) => p.kind === "missing" || p.kind === "value" || p.kind === "server");
  const suggested = inspection.suggestions.suggested[info.field];
  const describedBy = [`${id}-desc`, blocking.length ? `${id}-problem` : null, col ? `${id}-samples` : null].filter(Boolean).join(" ");
  return (
    <li className="grid gap-2 p-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]" data-testid={`field-${info.field}`}>
      <div className="min-w-0">
        <label htmlFor={id} className="font-medium">{info.label}</label>{" "}
        {info.required ? <Badge className="align-middle">обязательно</Badge> : <Badge variant="outline" className="align-middle">необязательно</Badge>}
        <div className="font-mono text-[11px] text-muted-foreground">{info.field}</div>
        <p id={`${id}-desc`} className="text-xs text-muted-foreground">{info.description}</p>
      </div>
      <div className="min-w-0 space-y-1.5">
        <select
          id={id}
          className={selectClass}
          value={choiceToSelect(choice)}
          disabled={disabled}
          aria-invalid={invalid || undefined}
          aria-describedby={describedBy}
          onChange={(e) => onChange(info.field, selectToChoice(e.target.value, choice))}
        >
          <option value={SELECT_NONE}>{info.required ? "— выберите источник —" : "— не импортировать —"}</option>
          <optgroup label="Столбцы листа">
            {inspection.columns.map((c) => {
              const owner = taken.get(c.id);
              return (
                <option key={c.id} value={c.id} disabled={!!owner}>
                  {c.letter} · {c.label}{suggested?.column === c.id ? " (предложено)" : ""}{owner ? ` — уже выбран для «${fieldLabel(owner)}»` : ""}
                </option>
              );
            })}
          </optgroup>
          {(info.shared_allowed || info.none_allowed) && (
            <optgroup label="Без столбца">
              {info.shared_allowed && <option value={SELECT_VALUE}>Одно значение для всего файла…</option>}
              {info.none_allowed && info.required && <option value={SELECT_ABSENT}>В файле нет учебника (оставить пустым)</option>}
            </optgroup>
          )}
        </select>
        {choice?.source === "value" && (
          <SharedValueInput field={info.field} label={info.label} value={choice.value} disabled={disabled}
            onChange={(v) => onChange(info.field, { source: "value", value: v })} />
        )}
        {choice?.source === "none" && (
          <p className="text-xs text-muted-foreground">Значение будет пустым во всех строках; такие классы не участвуют в сравнении учебников.</p>
        )}
        {col && (
          <p id={`${id}-samples`} className="truncate text-xs text-muted-foreground" title={col.samples.join(" · ")}>
            {col.empty ? "Столбец пуст под заголовком." : <>Примеры: {col.samples.join(" · ")}</>}
          </p>
        )}
        {blocking.length > 0 && (
          <ul id={`${id}-problem`} className="space-y-0.5 text-xs">
            {blocking.map((p, i) => (
              <li key={i} className={cn("flex gap-1", p.kind === "ambiguous" ? "text-amber-800 dark:text-amber-300" : "text-danger")}>
                {p.kind === "ambiguous" ? <Info className="mt-0.5 size-3 shrink-0" aria-hidden /> : <AlertTriangle className="mt-0.5 size-3 shrink-0" aria-hidden />}
                {p.message}
              </li>
            ))}
          </ul>
        )}
      </div>
    </li>
  );
}

function SharedValueInput({ field, label, value, disabled, onChange }: {
  field: string;
  label: string;
  value: string;
  disabled: boolean;
  onChange: (v: string) => void;
}) {
  const id = `shared-${field}`;
  if (field === "assessment_type") {
    return (
      <div className="rounded-md border border-dashed p-2">
        <label htmlFor={id} className="text-xs font-medium">Значение для всех строк: {label}</label>
        <select id={id} className={selectClass} value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
          <option value="">— выберите —</option>
          {TYPE_OPTIONS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
        </select>
      </div>
    );
  }
  return (
    <div className="rounded-md border border-dashed p-2">
      <label htmlFor={id} className="text-xs font-medium">Значение для всех строк: {label}</label>
      <Input id={id} value={value} disabled={disabled} maxLength={255} placeholder={VALUE_HINT[field] ?? ""}
        aria-describedby={`${id}-hint`} onChange={(e) => onChange(e.target.value)} />
      <p id={`${id}-hint`} className="text-[11px] text-muted-foreground">
        Будет подставлено во все строки с данными. Значение проверяется по тем же правилам, что и столбец.
      </p>
    </div>
  );
}
