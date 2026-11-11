import type { TopicStatus } from "./types";

const nf1 = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1, minimumFractionDigits: 0 });
const nf2 = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 });
const nfInt = new Intl.NumberFormat("ru-RU");
const nfSmall = new Intl.NumberFormat("ru-RU", { maximumSignificantDigits: 3 });

function statistic(v: number, digits: 1 | 2): string {
  if (v !== 0 && Number(v.toFixed(digits)) === 0) return nfSmall.format(v);
  return (digits === 2 ? nf2 : nf1).format(v);
}

export function pct(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : `${nf1.format(v)}%`;
}

export function num(v: number | null | undefined, digits: 1 | 2 = 1): string {
  if (v === null || v === undefined) return "—";
  return (digits === 2 ? nf2 : nf1).format(v);
}

export function int(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : nfInt.format(v);
}

export function signed(v: number | null | undefined, unit = ""): string {
  if (v === null || v === undefined) return "—";
  const s = statistic(Math.abs(v), 2);
  return `${v > 0 ? "+" : v < 0 ? "−" : "±"}${s}${unit}`;
}

export function ci(lo: number | null | undefined, hi: number | null | undefined): string {
  if (lo === null || lo === undefined || hi === null || hi === undefined) return "—";
  return `${statistic(lo, 1)} … ${statistic(hi, 1)}`;
}

export function date(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00` : iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("ru-RU", { day: "2-digit", month: "short", year: "numeric" });
}

export function dateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("ru-RU", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

export const STATUS_META: Record<TopicStatus, { label: string; className: string; dot: string }> = {
  difficult: { label: "Трудная", className: "bg-danger/10 text-danger border-danger/25", dot: "bg-danger" },
  watch: { label: "Внимание", className: "bg-warning/15 text-amber-700 border-warning/40", dot: "bg-warning" },
  ok: { label: "Норма", className: "bg-success/10 text-emerald-700 border-success/25", dot: "bg-success" },
  insufficient_data: { label: "Мало данных", className: "bg-muted text-muted-foreground border-border", dot: "bg-muted-foreground" },
  no_outcome_data: { label: "Нет данных", className: "bg-muted text-muted-foreground border-border", dot: "bg-muted-foreground" },
};

export const KIND_LABEL: Record<string, string> = { pre: "входная", post: "итоговая", current: "текущая" };
