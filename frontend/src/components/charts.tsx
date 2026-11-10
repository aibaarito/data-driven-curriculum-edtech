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

import { KIND_LABEL, date, num, pct } from "@/lib/format";
import type { Bin, TopicStatus, TrendPoint } from "@/lib/types";

export const PALETTE = ["#4f46e5", "#0ea5a4", "#f59e0b", "#e11d48", "#16a34a", "#7c3aed"];
const STATUS_COLOR: Record<TopicStatus, string> = {
  difficult: "#e11d48",
  watch: "#f59e0b",
  ok: "#4f46e5",
  insufficient_data: "#94a3b8",
  no_outcome_data: "#cbd5e1",
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

export function MasteryChart({ data, difficult, watch }: {
  data: { name: string; mastery: number | null; status: TopicStatus; student_count: number }[];
  difficult: number;
  watch: number;
}) {
  const rows = data.filter((d) => d.mastery !== null);
  const height = Math.max(220, rows.length * 34 + 40);
  return (
    <div style={{ height }} role="img" aria-label="Освоение по темам, процентов">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} layout="vertical" margin={{ left: 8, right: 24, top: 22, bottom: 8 }} barCategoryGap={8}>
          <CartesianGrid horizontal={false} stroke={GRID} />
          <XAxis type="number" domain={[0, 100]} tick={AXIS} tickFormatter={(v: number) => `${v}%`} />
          <YAxis type="category" dataKey="name" width={190} tick={AXIS} tickFormatter={(v: string) => short(v)} />
          <Tooltip
            {...tooltipStyle}
            formatter={(v) => [pct(Number(v)), "Освоение"]}
            labelFormatter={(l) => String(l)}
          />
          <ReferenceLine x={difficult} stroke="#e11d48" strokeDasharray="4 4" label={{ value: `${difficult}%`, fontSize: 11, fill: "#e11d48", position: "top" }} />
          <ReferenceLine x={watch} stroke="#f59e0b" strokeDasharray="4 4" label={{ value: `${watch}%`, fontSize: 11, fill: "#b45309", position: "top" }} />
          <Bar dataKey="mastery" radius={[0, 6, 6, 0]} isAnimationActive={false}>
            {rows.map((d) => (
              <Cell key={d.name} fill={STATUS_COLOR[d.status]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function TrendChart({ data }: { data: TrendPoint[] }) {
  const rows = data.map((d) => ({ ...d, label: `${d.assessment}` }));
  return (
    <div className="h-64" role="img" aria-label="Динамика освоения по оцениваниям">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={rows} margin={{ left: 0, right: 16, top: 12, bottom: 4 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="label" tick={AXIS} />
          <YAxis domain={[0, 100]} tick={AXIS} tickFormatter={(v: number) => `${v}%`} width={44} />
          <Tooltip
            {...tooltipStyle}
            formatter={(v) => [pct(Number(v)), "Освоение"]}
            labelFormatter={(_, p) => {
              const d = p?.[0]?.payload as TrendPoint | undefined;
              return d ? `${d.assessment} · ${date(d.date)} · ${KIND_LABEL[d.kind]} · ${d.students} уч.` : "";
            }}
          />
          <Line type="monotone" dataKey="mastery" stroke={PALETTE[0]} strokeWidth={2.5} dot={{ r: 4 }} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
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

export function MultiSeriesTrend({ data, series }: {
  data: Record<string, string | number | null>[];
  series: { key: string; name: string }[];
}) {
  return (
    <div className="h-72" role="img" aria-label="Динамика освоения тем">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ left: 0, right: 16, top: 8, bottom: 4 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="label" tick={AXIS} />
          <YAxis domain={[0, 100]} tick={AXIS} tickFormatter={(v: number) => `${v}%`} width={44} />
          <Tooltip {...tooltipStyle} formatter={(v, n) => [pct(Number(v)), String(n)]} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          {series.map((s, i) => (
            <Line key={s.key} type="monotone" dataKey={s.key} name={s.name} stroke={PALETTE[i % PALETTE.length]}
              strokeWidth={2} dot={{ r: 3 }} connectNulls isAnimationActive={false} />
          ))}
        </LineChart>
      </ResponsiveContainer>
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
