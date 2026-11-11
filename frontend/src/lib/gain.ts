// One vocabulary for paired pre→post change across topics, dashboard, reports and AI facts (matches the PDF).

import { ci, num, signed } from "./format";
import type { Gain, GainDirection } from "./types";

export const DIRECTION_LABEL: Record<GainDirection, string> = {
  increase: "установлен рост",
  decline: "установлено снижение",
  inconclusive: "изменение не установлено",
  insufficient: "недостаточно пар для оценки",
};

export const LEGACY_GAIN_LABEL = "статус изменения в этом снимке не сохранён";

export interface GainSummary {
  /** Signed estimate in p.p., or null when no estimate should be shown. */
  estimate: string | null;
  /** Qualification that must always accompany the estimate. */
  status: string;
  tone: "positive" | "negative" | "neutral" | "unknown";
  /** Interval level, interval and pair count, when available. */
  detail: string | null;
  /** Extra caution for an inconclusive change. */
  note: string | null;
}

export function summarizeGain(g: Gain | null | undefined): GainSummary {
  if (!g) {
    return { estimate: null, status: "не оценивалось", tone: "unknown", note: null,
      detail: "Нет пар входной и итоговой диагностики" };
  }
  if (!g.direction) {
    return { estimate: signed(g.mean_gain, " п.п."), status: LEGACY_GAIN_LABEL, tone: "unknown", detail: null, note: null };
  }
  if (g.direction === "insufficient") {
    return { estimate: null, status: DIRECTION_LABEL.insufficient, tone: "unknown", note: null,
      detail: `${g.n_paired} пар — меньше минимума для оценки` };
  }
  const parts: string[] = [];
  if (g.ci_low !== null && g.ci_high !== null) parts.push(`${num(g.ci_level, 2)}% ДИ ${ci(g.ci_low, g.ci_high)}`);
  parts.push(`${g.n_paired} пар`);
  return {
    estimate: signed(g.mean_gain, " п.п."),
    status: DIRECTION_LABEL[g.direction],
    tone: g.direction === "increase" ? "positive" : g.direction === "decline" ? "negative" : "neutral",
    detail: parts.join(" · "),
    note: g.direction === "inconclusive" ? "Это не доказывает отсутствие эффекта." : null,
  };
}

/** "+0,6 п.п. · изменение не установлено" */
export function gainText(g: Gain | null | undefined): string {
  const s = summarizeGain(g);
  return s.estimate ? `${s.estimate} · ${s.status}` : s.status;
}
