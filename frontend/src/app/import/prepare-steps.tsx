"use client";

// Guided import steps beyond the column mapping: data selection (CSV options, header rows, range, flagged rows),
// table structure, wide-gradebook result columns, aggregate roles, general column types and scoring rules.
// All user-provided text is rendered as React text nodes.

import { useId, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  codeFromHeader,
  emptyResultColumn,
  type MetricState,
  observedValues,
  type ResultColumnSpec,
  type RulesState,
} from "@/lib/import-wizard";
import type { CsvInfo, ImportCatalog, Layout, RegionSelection, SheetInspection } from "@/lib/types";
import { cn } from "@/lib/utils";

import { selectClass } from "./guided-steps";

// --------------------------------------------------------------------------- data selection

export function CsvOptions({ info, value, disabled, onChange }: {
  info: CsvInfo;
  value: { encoding: string; delimiter: string };
  disabled: boolean;
  onChange: (v: { encoding: string; delimiter: string }) => void;
}) {
  const id = useId();
  const delimLabel: Record<string, string> = { auto: "определить автоматически", ",": "запятая", ";": "точка с запятой", "\t": "табуляция" };
  return (
    <fieldset className="grid gap-3 sm:grid-cols-2" data-testid="csv-options">
      <legend className="sr-only">Параметры CSV</legend>
      <div className="grid gap-1">
        <label htmlFor={`${id}-enc`} className="text-sm font-medium">Кодировка</label>
        <select id={`${id}-enc`} className={selectClass} value={value.encoding} disabled={disabled}
          aria-describedby={`${id}-enc-hint`} onChange={(e) => onChange({ ...value, encoding: e.target.value })}>
          <option value="auto">определить автоматически</option>
          <option value="utf-8">UTF-8</option>
          <option value="cp1251">Windows-1251</option>
        </select>
        <p id={`${id}-enc-hint`} className={cn("text-xs", info.encoding_confidence === "low" ? "text-amber-800 dark:text-amber-300" : "text-muted-foreground")}>
          Сейчас: {info.encoding === "cp1251" ? "Windows-1251" : "UTF-8"}
          {info.encoding_confidence === "low" && " — определено неуверенно; проверьте буквы в предпросмотре."}
        </p>
      </div>
      <div className="grid gap-1">
        <label htmlFor={`${id}-del`} className="text-sm font-medium">Разделитель</label>
        <select id={`${id}-del`} className={selectClass} value={value.delimiter} disabled={disabled}
          aria-describedby={`${id}-del-hint`} onChange={(e) => onChange({ ...value, delimiter: e.target.value })}>
          {Object.entries(delimLabel).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <p id={`${id}-del-hint`} className={cn("text-xs", info.delimiter_confidence === "low" ? "text-amber-800 dark:text-amber-300" : "text-muted-foreground")}>
          Сейчас: {info.delimiter_label}
          {info.delimiter_confidence === "low" && info.delimiter_alternatives.length > 0 &&
            ` — подходит и «${info.delimiter_alternatives.map((a) => a.label).join("», «")}»; выберите вручную, если столбцы разделены неверно.`}
        </p>
      </div>
    </fieldset>
  );
}

export function RegionOptions({ inspection, region, disabled, onChange }: {
  inspection: SheetInspection;
  region: RegionSelection;
  disabled: boolean;
  onChange: (r: Partial<RegionSelection>) => void;
}) {
  const id = useId();
  const cols = inspection.all_columns ?? [];
  const [lastRowText, setLastRowText] = useState(region.last_row ? String(region.last_row) : "");
  return (
    <div className="space-y-3" data-testid="region-options">
      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" className="mt-1" checked={region.header_rows === 2} disabled={disabled || region.header_row < 2}
          onChange={(e) => onChange({ header_rows: e.target.checked ? 2 : 1 })} data-testid="two-row-header" />
        <span>
          Двухстрочный заголовок: строка {Math.max(region.header_row - 1, 1)} — группы (например, «Контрольная 1»), строка {region.header_row} — названия столбцов.
          <span className="block text-xs text-muted-foreground">Группа берётся из объединённых ячеек Excel или из ячейки прямо над столбцом; ничего не протягивается по догадке.</span>
        </span>
      </label>
      <details className="rounded-lg border" open={region.first_col > 0 || region.last_col !== null || region.last_row !== null || undefined}>
        <summary className="cursor-pointer rounded-lg px-3 py-2 text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring">
          Диапазон данных {region.first_col > 0 || region.last_col !== null || region.last_row !== null ? "(ограничен)" : "(весь лист)"}
        </summary>
        <div className="grid gap-3 px-3 pb-3 sm:grid-cols-3">
          <div className="grid gap-1">
            <label htmlFor={`${id}-fc`} className="text-xs font-medium">Первый столбец</label>
            <select id={`${id}-fc`} className={selectClass} value={region.first_col} disabled={disabled}
              onChange={(e) => onChange({ first_col: Number(e.target.value) })}>
              {cols.map((c) => <option key={c.index} value={c.index}>{c.letter}</option>)}
            </select>
          </div>
          <div className="grid gap-1">
            <label htmlFor={`${id}-lc`} className="text-xs font-medium">Последний столбец</label>
            <select id={`${id}-lc`} className={selectClass} value={region.last_col ?? ""} disabled={disabled}
              onChange={(e) => onChange({ last_col: e.target.value === "" ? null : Number(e.target.value) })}>
              <option value="">до конца</option>
              {cols.filter((c) => c.index >= region.first_col).map((c) => <option key={c.index} value={c.index}>{c.letter}</option>)}
            </select>
          </div>
          <div className="grid gap-1">
            <label htmlFor={`${id}-lr`} className="text-xs font-medium">Последняя строка данных</label>
            <Input id={`${id}-lr`} inputMode="numeric" value={lastRowText} disabled={disabled} placeholder="до конца"
              aria-describedby={`${id}-lr-hint`}
              onChange={(e) => setLastRowText(e.target.value.replace(/\D/g, ""))}
              onBlur={() => {
                const n = lastRowText ? Number(lastRowText) : null;
                if (n !== region.last_row && (n === null || n > region.header_row)) onChange({ last_row: n });
                else if (n !== null && n <= region.header_row) setLastRowText(region.last_row ? String(region.last_row) : "");
              }} />
            <p id={`${id}-lr-hint`} className="text-[11px] text-muted-foreground">
              Используйте, если под таблицей есть другая таблица или примечания. Последняя строка с данными: {inspection.last_data_row ?? "—"}.
            </p>
          </div>
        </div>
      </details>
    </div>
  );
}

export function FlaggedRows({ inspection, region, catalog, disabled, onChange }: {
  inspection: SheetInspection;
  region: RegionSelection;
  catalog?: ImportCatalog;
  disabled: boolean;
  onChange: (exclude: string[]) => void;
}) {
  const flags = inspection.flags ?? [];
  if (!flags.length) return null;
  const labels = Object.fromEntries((catalog?.flags ?? []).map((f) => [f.value, f.label]));
  const kinds = Object.entries(inspection.flag_counts ?? {});
  return (
    <fieldset className="rounded-lg border border-warning/50 bg-warning/10 p-3 text-sm" data-testid="flagged-rows">
      <legend className="px-1 font-medium">Строки, требующие решения</legend>
      <p className="mb-2 text-xs text-muted-foreground">
        Такие строки не удаляются автоматически. Отметьте, какие исключить; исключённые строки будут перечислены в итоге проверки.
      </p>
      <ul className="space-y-1.5">
        {kinds.map(([kind, n]) => {
          const rows = flags.filter((f) => f.kind === kind).map((f) => f.row);
          return (
            <li key={kind}>
              <label className="flex items-start gap-2">
                <input type="checkbox" className="mt-1" disabled={disabled} checked={region.exclude.includes(kind)}
                  data-testid={`exclude-${kind}`}
                  onChange={(e) => onChange(e.target.checked ? [...region.exclude, kind] : region.exclude.filter((k) => k !== kind))} />
                <span>Исключить: {labels[kind] ?? kind} — {n} (строки {rows.slice(0, 8).join(", ")}{rows.length > 8 ? "…" : ""})</span>
              </label>
            </li>
          );
        })}
      </ul>
    </fieldset>
  );
}

// --------------------------------------------------------------------------- structure

const LAYOUT_HELP: Record<Layout, { title: string; example: string }> = {
  long: { title: "Записи: одна строка — один результат ученика по теме или заданию", example: "Код ученика | Тема | Работа | Балл | Максимум" },
  wide: { title: "Журнал: одна строка — ученик, результаты в нескольких столбцах", example: "Код ученика | Класс | Дроби | Уравнения | Проценты" },
  aggregate: { title: "Сводная таблица: строка — класс, тема или группа со средним, процентом или числом учеников", example: "Класс | Тема | Средний % | Учеников" },
  general: { title: "Общая таблица: просмотр, сводки и графики без образовательного анализа", example: "Любая таблица с заголовком" },
};

export function LayoutStep({ value, suggestion, disabled, onChange }: {
  value: Layout;
  suggestion?: { layout: Layout; confidence: string; reason: string } | null;
  disabled: boolean;
  onChange: (l: Layout) => void;
}) {
  const name = useId();
  return (
    <fieldset className="space-y-2" data-testid="layout-step">
      <legend className="text-sm font-semibold">Структура таблицы</legend>
      {suggestion && (
        <p className="text-xs text-muted-foreground">Предложено: «{LAYOUT_HELP[suggestion.layout].title.split(":")[0]}». {suggestion.reason}</p>
      )}
      <div className="grid gap-2 md:grid-cols-2">
        {(Object.keys(LAYOUT_HELP) as Layout[]).map((l) => (
          <label key={l} className="flex cursor-pointer items-start gap-2 rounded-lg border p-3 text-sm has-[:checked]:border-primary has-[:checked]:bg-primary/5 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring">
            <input type="radio" name={name} className="mt-1" checked={value === l} disabled={disabled} onChange={() => onChange(l)}
              data-testid={`layout-${l}`} />
            <span className="min-w-0">
              <span className="block font-medium">{LAYOUT_HELP[l].title}{suggestion?.layout === l && <Badge variant="secondary" className="ml-1">предложено</Badge>}</span>
              <span className="block break-words font-mono text-[11px] text-muted-foreground">{LAYOUT_HELP[l].example}</span>
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

// --------------------------------------------------------------------------- wide gradebook

export function WideResultsStep({ inspection, results, usedIdentity, scoreMode, problems, disabled, onChange }: {
  inspection: SheetInspection;
  results: ResultColumnSpec[];
  usedIdentity: Set<string>;
  scoreMode: string;
  problems: Record<string, string[]>;
  disabled: boolean;
  onChange: (r: ResultColumnSpec[]) => void;
}) {
  const [allMax, setAllMax] = useState("");
  const selected = new Set(results.map((r) => r.column));
  const totals = new Set((inspection.wide_suggestion?.total_columns ?? []).map((c) => c.column));
  const update = (column: string, patch: Partial<ResultColumnSpec>) =>
    onChange(results.map((r) => (r.column === column ? { ...r, ...patch } : r)));
  const toggle = (column: string, on: boolean) => {
    const col = inspection.columns.find((c) => c.id === column);
    onChange(on ? [...results, emptyResultColumn(column, col?.group || col?.sub || col?.header || "")]
      .sort((a, b) => Number(a.column.slice(1)) - Number(b.column.slice(1))) : results.filter((r) => r.column !== column));
  };
  return (
    <section className="space-y-3" aria-labelledby="wide-title" data-testid="wide-step">
      <h3 id="wide-title" className="text-sm font-semibold">Столбцы с результатами</h3>
      <p className="text-xs text-muted-foreground">
        Каждая непустая ячейка выбранного столбца станет отдельной записью «ученик × тема». Код темы и максимальный балл задаются явно;
        название темы предложено из заголовка. Пустые ячейки записей не создают.
      </p>
      <div className="flex flex-wrap gap-2">
        <Button type="button" size="sm" variant="outline" disabled={disabled || !results.length}
          onClick={() => { const taken = new Set<string>(); onChange(results.map((r) => ({ ...r, topic_id: r.topic_id || codeFromHeader(r.topic_name, taken) }))); }}>
          Заполнить пустые коды тем из названий
        </Button>
        {scoreMode === "points" && (
          <span className="flex items-center gap-1">
            <label htmlFor="wide-all-max" className="sr-only">Максимальный балл для всех выбранных столбцов</label>
            <Input id="wide-all-max" className="h-8 w-24" placeholder="макс." value={allMax} disabled={disabled} onChange={(e) => setAllMax(e.target.value)} />
            <Button type="button" size="sm" variant="outline" disabled={disabled || !allMax.trim() || !results.length}
              onClick={() => onChange(results.map((r) => ({ ...r, max_score: allMax.trim() })))}>
              Применить максимум ко всем
            </Button>
          </span>
        )}
      </div>
      <ul className="divide-y rounded-lg border">
        {inspection.columns.filter((c) => !usedIdentity.has(c.id) && c.header).map((c) => {
          const spec = results.find((r) => r.column === c.id);
          const errs = problems[c.id] ?? [];
          const base = `rc-${c.id}`;
          return (
            <li key={c.id} className="grid gap-2 p-3 lg:grid-cols-[minmax(0,14rem)_minmax(0,1fr)]" data-testid={`result-${c.id}`}>
              <label className="flex items-start gap-2 text-sm">
                <input type="checkbox" className="mt-1" checked={selected.has(c.id)} disabled={disabled}
                  aria-describedby={`${base}-samples`} onChange={(e) => toggle(c.id, e.target.checked)} />
                <span className="min-w-0">
                  <span className="block break-words font-medium">{c.letter} · {c.label}</span>
                  {totals.has(c.id) && <Badge variant="outline">похоже на итог или среднее</Badge>}
                  <span id={`${base}-samples`} className="block truncate text-xs text-muted-foreground">
                    {c.samples.length ? `Примеры: ${c.samples.join(" · ")}` : "пустой столбец"}
                  </span>
                </span>
              </label>
              {spec && (
                <div className="space-y-1">
                  <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
                    <SmallInput id={`${base}-tid`} label="Код темы" value={spec.topic_id} disabled={disabled} onChange={(v) => update(c.id, { topic_id: v })} />
                    <SmallInput id={`${base}-tname`} label="Название темы" value={spec.topic_name} disabled={disabled} onChange={(v) => update(c.id, { topic_name: v })} />
                    <SmallInput id={`${base}-item`} label="Код задания (необяз.)" value={spec.item_id} disabled={disabled} onChange={(v) => update(c.id, { item_id: v })} />
                    {scoreMode === "points" && (
                      <SmallInput id={`${base}-max`} label="Максимальный балл" value={spec.max_score} disabled={disabled} onChange={(v) => update(c.id, { max_score: v })} />
                    )}
                  </div>
                  <details>
                    <summary className="cursor-pointer text-xs text-muted-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring">
                      Оценивание для этого столбца (если столбцы — разные работы)
                    </summary>
                    <div className="mt-1 grid gap-2 sm:grid-cols-3">
                      <SmallInput id={`${base}-aid`} label="Код работы" value={spec.assessment_id} disabled={disabled} onChange={(v) => update(c.id, { assessment_id: v })} />
                      <SmallInput id={`${base}-atype`} label="Тип (pre/post/current)" value={spec.assessment_type} disabled={disabled} onChange={(v) => update(c.id, { assessment_type: v })} />
                      <SmallInput id={`${base}-adate`} label="Дата" value={spec.assessment_date} disabled={disabled} onChange={(v) => update(c.id, { assessment_date: v })} />
                    </div>
                  </details>
                  {errs.length > 0 && (
                    <ul id={`${base}-problem`} className="text-xs text-danger" role="list">
                      {errs.map((m, i) => <li key={i}>{m}</li>)}
                    </ul>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function SmallInput({ id, label, value, disabled, onChange }: { id: string; label: string; value: string; disabled: boolean; onChange: (v: string) => void }) {
  return (
    <div className="grid gap-0.5">
      <label htmlFor={id} className="text-[11px] font-medium text-muted-foreground">{label}</label>
      <Input id={id} className="h-8" value={value} maxLength={255} disabled={disabled} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

// --------------------------------------------------------------------------- aggregate

export function AggregateStep({ inspection, catalog, roles, metric, name, disabled, onRoles, onMetric, onName }: {
  inspection: SheetInspection;
  catalog?: ImportCatalog;
  roles: Record<string, string>;
  metric: MetricState;
  name: string;
  disabled: boolean;
  onRoles: (r: Record<string, string>) => void;
  onMetric: (m: MetricState) => void;
  onName: (n: string) => void;
}) {
  const options = catalog?.aggregate_roles ?? [];
  const taken = new Map(Object.entries(roles).map(([c, r]) => [r, c]));
  return (
    <section className="space-y-3" data-testid="aggregate-step" aria-labelledby="agg-title">
      <h3 id="agg-title" className="text-sm font-semibold">Роли столбцов сводной таблицы</h3>
      <p className="text-xs text-muted-foreground">
        Строки останутся показателями групп. Они не превращаются в записи учеников, а распределения, интервалы и прирост по ним не считаются.
      </p>
      <DatasetName value={name} disabled={disabled} onChange={onName} />
      <ul className="divide-y rounded-lg border">
        {inspection.columns.map((c) => (
          <li key={c.id} className="grid gap-2 p-2 sm:grid-cols-[minmax(0,1fr)_14rem] sm:items-center">
            <label htmlFor={`role-${c.id}`} className="min-w-0 text-sm">
              <span className="block break-words font-medium">{c.letter} · {c.label}</span>
              <span className="block truncate text-xs text-muted-foreground">{c.samples.join(" · ")}</span>
            </label>
            <select id={`role-${c.id}`} className={selectClass} value={roles[c.id] ?? ""} disabled={disabled}
              onChange={(e) => {
                const next = { ...roles };
                if (e.target.value) next[c.id] = e.target.value;
                else delete next[c.id];
                onRoles(next);
              }}>
              <option value="">не использовать</option>
              {options.map((o) => (
                <option key={o.value} value={o.value} disabled={taken.has(o.value) && taken.get(o.value) !== c.id}>{o.label}</option>
              ))}
            </select>
          </li>
        ))}
      </ul>
      <fieldset className="grid gap-2 sm:grid-cols-3">
        <legend className="mb-1 text-sm font-medium">Что означает показатель</legend>
        <div className="grid gap-1">
          <label htmlFor="metric-kind" className="text-xs font-medium">Вид показателя</label>
          <select id="metric-kind" className={selectClass} value={metric.kind} disabled={disabled}
            onChange={(e) => onMetric({ ...metric, kind: e.target.value as MetricState["kind"] })}>
            <option value="">— выберите —</option>
            <option value="percent">процент выполнения (0–100)</option>
            <option value="mean_points">средний балл с известным максимумом</option>
          </select>
        </div>
        {metric.kind === "percent" && (
          <div className="grid gap-1">
            <label htmlFor="metric-scale" className="text-xs font-medium">Запись процентов</label>
            <select id="metric-scale" className={selectClass} value={metric.percent_scale} disabled={disabled}
              onChange={(e) => onMetric({ ...metric, percent_scale: e.target.value as MetricState["percent_scale"] })}>
              <option value="0-100">числа 0–100 или «85%»</option>
              <option value="0-1">доли 0–1 (ячейки Excel в формате %)</option>
            </select>
          </div>
        )}
        {metric.kind === "mean_points" && !Object.values(roles).includes("max") && (
          <SmallInput id="metric-max" label="Максимальный балл" value={metric.max_value} disabled={disabled}
            onChange={(v) => onMetric({ ...metric, max_value: v })} />
        )}
      </fieldset>
    </section>
  );
}

function DatasetName({ value, disabled, onChange }: { value: string; disabled: boolean; onChange: (v: string) => void }) {
  return (
    <div className="grid max-w-md gap-1">
      <label htmlFor="dataset-name" className="text-xs font-medium">Название набора данных (необязательно)</label>
      <Input id="dataset-name" value={value} maxLength={120} disabled={disabled} placeholder="По умолчанию — имя файла и листа"
        onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

// --------------------------------------------------------------------------- general table

export function GeneralStep({ inspection, catalog, types, name, disabled, onTypes, onName }: {
  inspection: SheetInspection;
  catalog?: ImportCatalog;
  types: Record<string, string>;
  name: string;
  disabled: boolean;
  onTypes: (t: Record<string, string>) => void;
  onName: (n: string) => void;
}) {
  const options = catalog?.types ?? [];
  return (
    <section className="space-y-3" data-testid="general-step" aria-labelledby="gen-title">
      <h3 id="gen-title" className="text-sm font-semibold">Типы столбцов</h3>
      <p className="text-xs text-muted-foreground">
        Таблица сохраняется отдельно от результатов оценивания и доступна в разделе «Наборы данных». Тип определяет, как читать значения для
        сводок и графиков; идентификаторы не суммируются как числа. Исходные значения не изменяются.
      </p>
      <DatasetName value={name} disabled={disabled} onChange={onName} />
      <ul className="grid gap-2 sm:grid-cols-2">
        {inspection.columns.map((c) => (
          <li key={c.id} className="grid gap-1 rounded-lg border p-2">
            <label htmlFor={`type-${c.id}`} className="min-w-0 text-sm">
              <span className="block break-words font-medium">{c.letter} · {c.label}</span>
              <span className="block truncate text-xs text-muted-foreground">{c.samples.join(" · ") || "пусто"}</span>
            </label>
            <select id={`type-${c.id}`} className={selectClass} value={types[c.id] ?? "text"} disabled={disabled}
              onChange={(e) => onTypes({ ...types, [c.id]: e.target.value })}>
              {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </li>
        ))}
      </ul>
    </section>
  );
}

// --------------------------------------------------------------------------- rules

const DATE_LABEL: Record<string, string> = {
  auto: "ГГГГ-ММ-ДД или ДД.ММ.ГГГГ (даты с «/» потребуют выбора)", "DD.MM.YYYY": "ДД.ММ.ГГГГ", "YYYY-MM-DD": "ГГГГ-ММ-ДД",
  "DD/MM/YYYY": "ДД/ММ/ГГГГ (день первым)", "MM/DD/YYYY": "ММ/ДД/ГГГГ (месяц первым)", "DD-MM-YYYY": "ДД-ММ-ГГГГ",
};
const MARKER_HINTS = ["н", "н/я", "-", "отс", "нет"];

function splitList(v: string): string[] {
  return v.split(",").map((x) => x.trim()).filter(Boolean);
}

export function RulesStep({ rules, inspection, scoreColumns, layout, disabled, onChange }: {
  rules: RulesState;
  inspection: SheetInspection;
  scoreColumns: string[];
  layout: Layout;
  disabled: boolean;
  onChange: (r: RulesState) => void;
}) {
  const id = useId();
  const [markersText, setMarkersText] = useState(rules.missing_markers.join(", "));
  const [trueText, setTrueText] = useState(rules.true_tokens.join(", "));
  const [falseText, setFalseText] = useState(rules.false_tokens.join(", "));
  const observed = observedValues(inspection, scoreColumns);
  const set = (patch: Partial<RulesState>) => onChange({ ...rules, ...patch });
  const showScore = layout === "long" || layout === "wide";
  return (
    <section className="space-y-4" aria-labelledby={`${id}-title`} data-testid="rules-step">
      <h3 id={`${id}-title`} className="text-sm font-semibold">Правила чтения результатов</h3>
      {showScore && (
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">Что записано в столбце результата</legend>
          {([
            ["points", "Баллы при известном максимуме", "Максимум берётся из столбца или задаётся для каждого столбца журнала."],
            ["percent", "Проценты", "Сохраняются как балл из 100."],
            ["binary", "Верно / неверно", "Сохраняются как 1 или 0 из 1; значения перечисляются ниже."],
            ["scale", "Отметки по шкале (например, 2–5)", "Перевод в проценты задаётся таблицей; без таблицы не выполняется."],
          ] as const).map(([v, t, h]) => (
            <label key={v} className="flex items-start gap-2 text-sm">
              <input type="radio" name={`${id}-mode`} className="mt-1" checked={rules.score_mode === v} disabled={disabled}
                onChange={() => set({ score_mode: v })} data-testid={`score-mode-${v}`} />
              <span><span className="font-medium">{t}</span><span className="block text-xs text-muted-foreground">{h}</span></span>
            </label>
          ))}
          {rules.score_mode === "percent" && (
            <div className="grid max-w-sm gap-1 pl-6">
              <label htmlFor={`${id}-pscale`} className="text-xs font-medium">Запись процентов</label>
              <select id={`${id}-pscale`} className={selectClass} value={rules.percent_scale} disabled={disabled}
                onChange={(e) => set({ percent_scale: e.target.value as RulesState["percent_scale"] })}>
                <option value="0-100">числа 0–100 или «85%»</option>
                <option value="0-1">доли 0–1 (ячейки Excel в формате %)</option>
              </select>
            </div>
          )}
          {rules.score_mode === "binary" && (
            <div className="grid gap-2 pl-6 sm:grid-cols-2">
              <div className="grid gap-1">
                <label htmlFor={`${id}-true`} className="text-xs font-medium">Означает «верно» (через запятую)</label>
                <Input id={`${id}-true`} value={trueText} disabled={disabled} placeholder="1, да, верно"
                  onChange={(e) => setTrueText(e.target.value)} onBlur={() => set({ true_tokens: splitList(trueText) })} />
              </div>
              <div className="grid gap-1">
                <label htmlFor={`${id}-false`} className="text-xs font-medium">Означает «неверно» (через запятую)</label>
                <Input id={`${id}-false`} value={falseText} disabled={disabled} placeholder="0, нет, неверно"
                  onChange={(e) => setFalseText(e.target.value)} onBlur={() => set({ false_tokens: splitList(falseText) })} />
              </div>
              {observed.length > 0 && <p className="text-xs text-muted-foreground sm:col-span-2">Встречаются значения: {observed.join(", ")}</p>}
            </div>
          )}
          {rules.score_mode === "scale" && (
            <div className="space-y-1 pl-6" data-testid="scale-table">
              <p className="text-xs text-muted-foreground">Укажите процент для каждой отметки. Отметки без перевода будут ошибками, а не нулями.</p>
              <ul className="grid gap-1 sm:grid-cols-3">
                {[...new Set([...observed, ...Object.keys(rules.scale)])].map((v) => (
                  <li key={v} className="flex items-center gap-2">
                    <label htmlFor={`${id}-scale-${v}`} className="w-16 truncate text-sm font-medium">«{v}» →</label>
                    <Input id={`${id}-scale-${v}`} className="h-8 w-20" inputMode="decimal" value={rules.scale[v] ?? ""} disabled={disabled}
                      onChange={(e) => set({ scale: { ...rules.scale, [v]: e.target.value } })} />
                    <span className="text-xs text-muted-foreground">%</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </fieldset>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="grid gap-1">
          <label htmlFor={`${id}-dec`} className="text-xs font-medium">Десятичный разделитель</label>
          <select id={`${id}-dec`} className={selectClass} value={rules.decimal} disabled={disabled}
            onChange={(e) => set({ decimal: e.target.value as RulesState["decimal"] })}>
            <option value="auto">«.» или «,»; неоднозначные записи (1,000) — ошибка</option>
            <option value="comma">запятая (1,5); точка и пробел — разряды</option>
            <option value="dot">точка (1.5); запятая и пробел — разряды</option>
          </select>
        </div>
        {showScore && (
          <div className="grid gap-1">
            <label htmlFor={`${id}-date`} className="text-xs font-medium">Формат дат в тексте</label>
            <select id={`${id}-date`} className={selectClass} value={rules.date_format} disabled={disabled}
              onChange={(e) => set({ date_format: e.target.value })}>
              {Object.entries(DATE_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
        )}
        <div className="grid gap-1 sm:col-span-2">
          <label htmlFor={`${id}-miss`} className="text-xs font-medium">Отметки отсутствия результата (через запятую)</label>
          <Input id={`${id}-miss`} value={markersText} disabled={disabled} placeholder="например: н, н/я" aria-describedby={`${id}-miss-hint`}
            onChange={(e) => setMarkersText(e.target.value)} onBlur={() => set({ missing_markers: splitList(markersText) })} />
          <p id={`${id}-miss-hint`} className="text-[11px] text-muted-foreground">
            Для таких значений запись не создаётся; они не считаются нулём и не означают проваленную работу. Частые варианты:{" "}
            {MARKER_HINTS.map((m) => (
              <button key={m} type="button" className="mx-0.5 rounded border px-1 underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
                disabled={disabled || rules.missing_markers.includes(m)}
                onClick={() => { const next = [...rules.missing_markers, m]; setMarkersText(next.join(", ")); set({ missing_markers: next }); }}>
                {m}
              </button>
            ))}
          </p>
        </div>
      </div>
    </section>
  );
}
