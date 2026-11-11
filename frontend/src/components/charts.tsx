"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { ReactNode } from "react";

import { KIND_LABEL, STATUS_META, date, num, pct } from "@/lib/format";
import type { Bin, TopicStatus, TrendPoint } from "@/lib/types";
import { cn } from "@/lib/utils";

// Functional colours are checked for at least 3:1 contrast against the white card background
// (e.g. amber #b45309 ≈ 5.0:1, teal #0d9488 ≈ 3.7:1, slate #64748b ≈ 4.8:1). Values and statuses are also
// available as text in the data tables below each chart, so no information depends on colour or hover alone.
export const PALETTE = ["#4f46e5", "#0d9488", "#b45309", "#e11d48", "#16a34a", "#7c3aed"];
export const WARNING_MARK = "#b45309";
export const NEUTRAL_MARK = "#64748b";
export const STATUS_COLOR: Record<TopicStatus, string> = {
  difficult: "#e11d48",
  watch: WARNING_MARK,
  ok: "#4f46e5",
  insufficient_data: NEUTRAL_MARK,
  no_outcome_data: NEUTRAL_MARK,
};
const AXIS = { fontSize: 12, fill: "#64748b" };
const GRID = "#e2e8f0";

const tooltipStyle = {
  contentStyle: { borderRadius: 10, border: "1px solid #e2e8f0", fontSize: 12, boxShadow: "0 4px 16px rgb(15 23 42 / 0.08)" },
  labelStyle: { fontWeight: 600, color: "#0f172a" },
};

function short(s: string, n = 26) {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

const SHAPES = ["circle", "square", "triangle", "diamond"] as const;

/** Marker with a distinct shape per series, so series differ by shape as well as colour. */
function marker(i: number, color: string) {
  const shape = SHAPES[i % SHAPES.length];
  function Dot(props: { cx?: number; cy?: number; index?: number; value?: unknown }) {
    const { cx, cy, index } = props;
    if (cx === undefined || cy === undefined || props.value === null || props.value === undefined) return <g key={`e${index}`} />;
    const r = 5.5;
    const common = { fill: color, stroke: "#ffffff", strokeWidth: 1.5 };
    if (shape === "square") return <rect key={index} x={cx - r} y={cy - r} width={r * 2} height={r * 2} {...common} />;
    if (shape === "triangle")
      return <polygon key={index} points={`${cx},${cy - r - 1} ${cx + r + 1},${cy + r} ${cx - r - 1},${cy + r}`} {...common} />;
    if (shape === "diamond")
      return <polygon key={index} points={`${cx},${cy - r - 1} ${cx + r + 1},${cy} ${cx},${cy + r + 1} ${cx - r - 1},${cy}`} {...common} />;
    return <circle key={index} cx={cx} cy={cy} r={r} {...common} />;
  }
  return Dot;
}

/** HTML legend with the same marker shapes and colours as the unconnected series (Recharts draws none without a stroke). */
function MarkerLegend({ items }: { items: string[] }) {
  return (
    <ul className="mt-2 flex flex-wrap justify-center gap-x-4 gap-y-1 text-xs text-muted-foreground" aria-label="Обозначения">
      {items.map((label, i) => {
        const color = PALETTE[i % PALETTE.length];
        const shape = SHAPES[i % SHAPES.length];
        return (
          <li key={label} className="flex items-center gap-1.5">
            <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden>
              {shape === "square" ? <rect x="1.5" y="1.5" width="9" height="9" fill={color} />
                : shape === "triangle" ? <polygon points="6,1 11,11 1,11" fill={color} />
                  : shape === "diamond" ? <polygon points="6,0.5 11.5,6 6,11.5 0.5,6" fill={color} />
                    : <circle cx="6" cy="6" r="4.5" fill={color} />}
            </svg>
            {label}
          </li>
        );
      })}
    </ul>
  );
}

const LEGEND_TYPE = { circle: "circle", square: "square", triangle: "triangle", diamond: "diamond" } as const;

export interface DataColumn<T> {
  key: string;
  label: string;
  align?: "left" | "right";
  render: (row: T) => ReactNode;
}

/** Accessible text alternative for a chart: the same values in a table inside a disclosure. */
export function ChartDataTable<T>({ caption, columns, rows, summary = "Показать данные диаграммы таблицей" }: {
  caption: string;
  columns: DataColumn<T>[];
  rows: T[];
  summary?: string;
}) {
  return (
    <details className="group mt-3 rounded-lg border bg-card text-sm">
      <summary className="cursor-pointer rounded-lg px-3 py-2 font-medium text-primary outline-none focus-visible:ring-2 focus-visible:ring-ring">
        {summary}
      </summary>
      <div className="overflow-x-auto px-3 pb-3">
        <table className="w-full text-left text-xs">
          <caption className="py-1 text-left text-muted-foreground">{caption}</caption>
          <thead>
            <tr className="border-b">
              {columns.map((c) => (
                <th key={c.key} scope="col" className={cn("py-1.5 pr-3 font-medium", c.align === "right" && "text-right")}>{c.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-b last:border-0">
                {columns.map((c, j) => {
                  const Cell = j === 0 ? "th" : "td";
                  return (
                    <Cell key={c.key} scope={j === 0 ? "row" : undefined}
                      className={cn("py-1.5 pr-3 font-normal", c.align === "right" && "text-right tabular-nums")}>{c.render(r)}</Cell>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

type MasteryRow = { name: string; mastery: number | null; status: TopicStatus; student_count: number };

export function MasteryChart({ data, difficult, watch }: {
  data: MasteryRow[];
  difficult: number;
  watch: number;
}) {
  const rows = data.filter((d) => d.mastery !== null);
  const height = Math.max(220, rows.length * 34 + 40);
  const below = rows.filter((r) => r.status === "difficult").length;
  return (
    <>
      <div style={{ height }} role="img"
        aria-label={`Освоение по ${rows.length} темам, процентов. Ниже порога «трудная» (${difficult}%): ${below}. Значения — в таблице под диаграммой.`}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} layout="vertical" margin={{ left: 8, right: 24, top: 22, bottom: 8 }} barCategoryGap={8}>
            <CartesianGrid horizontal={false} stroke={GRID} />
            <XAxis type="number" domain={[0, 100]} tick={AXIS} tickFormatter={(v: number) => `${v}%`} />
            <YAxis type="category" dataKey="name" width={200} tick={AXIS} tickFormatter={(v: string) => short(v, 30)} />
            <Tooltip
              {...tooltipStyle}
              formatter={(v, _n, item) => [`${pct(Number(v))} · ${STATUS_META[(item?.payload as MasteryRow).status].label}`, "Освоение"]}
              labelFormatter={(l) => String(l)}
            />
            <ReferenceLine x={difficult} stroke="#e11d48" strokeDasharray="4 4" label={{ value: `${difficult}%`, fontSize: 11, fill: "#be123c", position: "top" }} />
            <ReferenceLine x={watch} stroke={WARNING_MARK} strokeDasharray="4 4" label={{ value: `${watch}%`, fontSize: 11, fill: WARNING_MARK, position: "top" }} />
            <Bar dataKey="mastery" radius={[0, 6, 6, 0]} isAnimationActive={false}>
              {rows.map((d) => (
                <Cell key={d.name} fill={STATUS_COLOR[d.status]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <ChartDataTable caption={`Освоение по темам. Пороги: трудная < ${difficult}%, внимание < ${watch}%.`} rows={rows}
        columns={[
          { key: "name", label: "Тема", render: (r) => r.name },
          { key: "m", label: "Освоение", align: "right", render: (r) => pct(r.mastery) },
          { key: "s", label: "Статус", render: (r) => STATUS_META[r.status].label },
          { key: "n", label: "Учеников", align: "right", render: (r) => r.student_count },
        ]} />
    </>
  );
}

/** Population key/label for an assessment observation. */
export function populationOf(p: TrendPoint): { key: string; label: string } {
  if (!p.grades || p.grades.length === 0) return { key: "unknown", label: "Группа не указана" };
  if (p.grades.length === 1) return { key: `g${p.grades[0]}`, label: `${p.grades[0]} класс` };
  return { key: `g${p.grades.join("_")}`, label: `Параллели ${p.grades.join(" и ")} вместе` };
}

/**
 * Each assessment is a separate observation of a (possibly different) group of pupils with its own tasks, so
 * points are never joined into a trajectory — not even within one grade. Progress claims belong to the paired
 * pre/post analysis on the Topics screen.
 */
export function observationSeries(data: TrendPoint[]) {
  const pops: { key: string; label: string }[] = [];
  for (const p of data) {
    const pop = populationOf(p);
    if (!pops.some((x) => x.key === pop.key)) pops.push(pop);
  }
  const rows = data.map((d) => {
    const pop = populationOf(d);
    return { ...d, label: d.assessment, population: pop.label, [pop.key]: d.mastery } as TrendPoint & Record<string, unknown> & {
      label: string; population: string;
    };
  });
  return { pops, rows };
}

export function AssessmentObservations({ data }: { data: TrendPoint[] }) {
  const { pops, rows } = observationSeries(data);
  return (
    <>
      <div className="h-64" role="img"
        aria-label={`Освоение по ${data.length} оцениваниям, отдельные точки без соединения; группы: ${pops.map((p) => p.label).join(", ")}. Значения — в таблице под диаграммой.`}
        data-testid="assessment-observations" data-series={pops.map((p) => p.key).join(",")}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ left: 0, right: 16, top: 12, bottom: 4 }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="label" tick={AXIS} />
            <YAxis domain={[0, 100]} tick={AXIS} tickFormatter={(v: number) => `${v}%`} width={44} />
            <Tooltip
              {...tooltipStyle}
              formatter={(v, n) => [pct(Number(v)), String(n)]}
              labelFormatter={(_, p) => {
                const d = p?.[0]?.payload as (TrendPoint & { population: string }) | undefined;
                return d ? `${d.assessment} · ${d.population} · ${date(d.date)} · ${KIND_LABEL[d.kind]} · ${d.students} уч.` : "";
              }}
            />
            {pops.map((p, i) => (
              <Line key={p.key} dataKey={p.key} name={p.label} stroke="none" fill={PALETTE[i % PALETTE.length]}
                legendType={LEGEND_TYPE[SHAPES[i % SHAPES.length]]} connectNulls={false}
                dot={marker(i, PALETTE[i % PALETTE.length])} activeDot={false} isAnimationActive={false} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <MarkerLegend items={pops.map((p) => p.label)} />
      <ChartDataTable caption="Освоение по оцениваниям: группа учеников, дата, тип и число учеников" rows={rows}
        columns={[
          { key: "a", label: "Оценивание", render: (r) => r.assessment },
          { key: "g", label: "Группа", render: (r) => r.population },
          { key: "d", label: "Дата", render: (r) => date(r.date) },
          { key: "k", label: "Тип", render: (r) => KIND_LABEL[r.kind] },
          { key: "n", label: "Учеников", align: "right", render: (r) => r.students },
          { key: "m", label: "Освоение", align: "right", render: (r) => pct(r.mastery) },
        ]} />
    </>
  );
}

export function DistributionChart({ bins, color = PALETTE[0] }: { bins: Bin[]; color?: string }) {
  return (
    <div className="h-48" role="img" aria-label="Распределение результатов учеников">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={bins} margin={{ left: 0, right: 8, top: 8, bottom: 4 }} barCategoryGap={2}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="from" tick={AXIS} tickFormatter={(v: number) => `${v}`} />
          <YAxis allowDecimals={false} tick={AXIS} width={32} />
          <Tooltip {...tooltipStyle} formatter={(v) => [String(v), "Учеников"]} labelFormatter={(_, p) => {
            const b = p?.[0]?.payload as Bin | undefined;
            return b ? `${b.bin}%` : "";
          }} />
          <Bar dataKey="count" fill={color} radius={[4, 4, 0, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function MultiSeriesTrend({ data, series, connect = true }: {
  data: Record<string, string | number | null>[];
  series: { key: string; name: string }[];
  /** false: show each assessment as a separate marker (assessments differ in tasks and pupils). */
  connect?: boolean;
}) {
  return (
    <div className={connect ? "h-72" : "h-80"} role="img" aria-label={`Освоение тем по оцениваниям: ${series.map((s) => s.name).join(", ")}`}>
      <div className={connect ? "h-full" : "h-64"}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ left: 0, right: 16, top: 8, bottom: 4 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="label" tick={AXIS} />
          <YAxis domain={[0, 100]} tick={AXIS} tickFormatter={(v: number) => `${v}%`} width={44} />
          <Tooltip {...tooltipStyle} formatter={(v, n) => [pct(Number(v)), String(n)]} />
          {connect && <Legend wrapperStyle={{ fontSize: 12 }} />}
          {series.map((s, i) => (
            connect ? (
              <Line key={s.key} type="monotone" dataKey={s.key} name={s.name} stroke={PALETTE[i % PALETTE.length]}
                strokeWidth={2} dot={{ r: 3 }} connectNulls isAnimationActive={false} />
            ) : (
              <Line key={s.key} dataKey={s.key} name={s.name} stroke="none" fill={PALETTE[i % PALETTE.length]}
                legendType={LEGEND_TYPE[SHAPES[i % SHAPES.length]]} connectNulls={false}
                dot={marker(i, PALETTE[i % PALETTE.length])} activeDot={false} isAnimationActive={false} />
            )
          ))}
        </LineChart>
      </ResponsiveContainer>
      </div>
      {!connect && <MarkerLegend items={series.map((s) => s.name)} />}
    </div>
  );
}

export function GroupedBars({ data, series, unit = "%", height = 300, domainMax }: {
  data: Record<string, string | number | null>[];
  series: { key: string; name: string; color?: string }[];
  unit?: string;
  height?: number;
  domainMax?: number;
}) {
  return (
    <div style={{ height }} role="img" aria-label="Сравнительная диаграмма">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ left: 0, right: 8, top: 8, bottom: 4 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="label" tick={AXIS} interval={0} tickFormatter={(v: string) => short(v, 14)} />
          <YAxis tick={AXIS} width={44} domain={[0, domainMax ?? "auto"]}
            tickFormatter={(v: number) => `${num(v)}${unit === "%" ? "%" : ""}`} />
          <Tooltip {...tooltipStyle} formatter={(v, n) => [`${num(Number(v), 2)}${unit === "%" ? "%" : ` ${unit}`}`, String(n)]} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          {series.map((s, i) => (
            <Bar key={s.key} dataKey={s.key} name={s.name} fill={s.color ?? PALETTE[i % PALETTE.length]}
              radius={[4, 4, 0, 0]} isAnimationActive={false} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
