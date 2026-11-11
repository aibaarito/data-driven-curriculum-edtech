// Human-readable labels for the verified facts behind AI explanations (raw keys stay in technical details).

import { DIRECTION_LABEL } from "./gain";
import { num } from "./format";
import type { GainDirection } from "./types";

type Unit = "%" | "п.п." | "ч" | "" | "уч." | "кл." | "пар";

interface MetricMeta {
  label: string;
  unit: Unit;
}

const TOPIC: Record<string, MetricMeta> = {
  mastery: { label: "освоение", unit: "%" },
  median: { label: "медиана по ученикам", unit: "%" },
  class_mean: { label: "среднее по классам", unit: "%" },
  students: { label: "учеников", unit: "уч." },
  status: { label: "статус темы", unit: "" },
  hours: { label: "часы (среднее по классам)", unit: "ч" },
  gain: { label: "изменение от входной к итоговой диагностике", unit: "п.п." },
  gain_direction: { label: "статус изменения", unit: "" },
  gain_ci_low: { label: "нижняя граница интервала изменения", unit: "п.п." },
  gain_ci_high: { label: "верхняя граница интервала изменения", unit: "п.п." },
  gain_ci_level: { label: "уровень интервала изменения", unit: "%" },
  pre_mean: { label: "входная диагностика (пары)", unit: "%" },
  post_mean: { label: "итоговая диагностика (пары)", unit: "%" },
  gain_n: { label: "пар входной и итоговой диагностики", unit: "пар" },
};

const TEXTBOOK: Record<string, MetricMeta> = {
  students: { label: "учеников", unit: "уч." },
  classes: { label: "классов", unit: "кл." },
  mean: { label: "среднее (описательно)", unit: "%" },
  baseline_mean: { label: "исходный уровень", unit: "%" },
  gain_mean: { label: "средний прирост", unit: "п.п." },
};

const COMPARISON: Record<string, MetricMeta> = {
  verdict: { label: "вывод", unit: "" },
  evidence_level: { label: "уровень доказательности", unit: "" },
  ci_level: { label: "уровень интервалов", unit: "%" },
  classes_a: { label: "классов: «{A}»", unit: "кл." },
  classes_b: { label: "классов: «{B}»", unit: "кл." },
  total_classes: { label: "классов всего", unit: "кл." },
  excluded_small_classes: { label: "исключено малых классов", unit: "кл." },
  raw_diff: { label: "разница без поправки («{B}» − «{A}»)", unit: "п.п." },
  students_a: { label: "учеников: «{A}»", unit: "уч." },
  students_b: { label: "учеников: «{B}»", unit: "уч." },
  adjusted_diff: { label: "разница с поправкой на исходный уровень («{B}» − «{A}»)", unit: "п.п." },
  adjusted_ci_low: { label: "нижняя граница интервала с поправкой", unit: "п.п." },
  adjusted_ci_high: { label: "верхняя граница интервала с поправкой", unit: "п.п." },
  gain_mean_a: { label: "прирост классов: «{A}»", unit: "п.п." },
  gain_mean_b: { label: "прирост классов: «{B}»", unit: "п.п." },
  gain_diff: { label: "разница прироста («{B}» − «{A}»)", unit: "п.п." },
  gain_ci_low: { label: "нижняя граница интервала прироста", unit: "п.п." },
  gain_ci_high: { label: "верхняя граница интервала прироста", unit: "п.п." },
  baseline_diff: { label: "разница исходного уровня («{B}» − «{A}»)", unit: "п.п." },
  min_class_size: { label: "минимальный размер класса", unit: "уч." },
};

const OVERVIEW: Record<string, MetricMeta> = {
  students: { label: "учеников", unit: "уч." },
  assessments: { label: "оцениваний", unit: "" },
  classes: { label: "классов", unit: "кл." },
  topics: { label: "тем", unit: "" },
  textbooks: { label: "учебников", unit: "" },
  average_mastery: { label: "среднее освоение", unit: "%" },
  difficult_topics: { label: "трудных тем", unit: "" },
};

const SETTINGS: Record<string, MetricMeta> = {
  difficult_threshold: { label: "порог «трудная тема»", unit: "%" },
  watch_threshold: { label: "порог «внимание»", unit: "%" },
  target_mastery: { label: "целевое освоение", unit: "%" },
  min_students_topic: { label: "минимум учеников для темы", unit: "уч." },
  min_students_textbook: { label: "минимум учеников на учебник", unit: "уч." },
  min_classes_textbook: { label: "минимум классов на учебник", unit: "кл." },
};

const STATUS_RU: Record<string, string> = {
  difficult: "трудная", watch: "внимание", ok: "норма", insufficient_data: "мало данных", no_outcome_data: "нет данных",
  observed_difference: "наблюдаемая разница", insufficient_evidence: "недостаточно данных",
  exploratory: "предварительный вывод", observational: "наблюдаемая связь", insufficient: "недостаточно данных",
  proposed: "предложена", accepted: "принята", rejected: "отклонена",
};

export interface FactLabel {
  /** e.g. "Формулы сокращённого умножения — освоение" */
  label: string;
  /** e.g. "40,9%" */
  value: string;
  /** Screen with the supporting analysis, carrying the result's scope. */
  href: string | null;
  key: string;
}

function formatValue(v: number | string | undefined, unit: Unit, metric: string): string {
  if (v === undefined || v === null) return "—";
  if (typeof v === "string") {
    if (metric.endsWith("direction") && v in DIRECTION_LABEL) return DIRECTION_LABEL[v as GainDirection];
    return STATUS_RU[v] ?? v;
  }
  const n = unit === "п.п." && v > 0 ? `+${num(v, 2)}` : num(v, 2);
  if (!unit) return n;
  return unit === "%" ? `${n}%` : `${n} ${unit}`;
}

export function factLabel(key: string, facts: Record<string, number | string>, query: string): FactLabel {
  const value = facts[key];
  const parts = key.split(".");
  const metric = parts[parts.length - 1];
  const entity = parts.slice(0, -1).join(".");
  const name = typeof facts[`${entity}.name`] === "string" ? String(facts[`${entity}.name`]) : null;
  let meta: MetricMeta | undefined;
  let href: string | null = null;
  let subject: string | null = name;
  if (parts[0] === "topic") {
    meta = TOPIC[metric];
    href = `/topics${query}${query ? "&" : "?"}topic=${encodeURIComponent(parts[1])}`;
  } else if (parts[0] === "textbook") {
    meta = TEXTBOOK[metric];
    href = `/textbooks${query}`;
  } else if (parts[0] === "comparison") {
    meta = COMPARISON[metric];
    href = `/textbooks${query}`;
    subject = "Сравнение учебников";
  } else if (parts[0] === "overview") {
    meta = OVERVIEW[metric];
    href = `/${query}`;
    subject = "Вся выбранная группа";
  } else if (parts[0] === "settings") {
    meta = SETTINGS[metric];
    href = "/settings";
    subject = "Настройки анализа";
  } else if (parts[0] === "plan") {
    href = `/optimizer${query}`;
    const planMeta: Record<string, MetricMeta> = {
      total_hours: { label: "всего часов в плане", unit: "ч" },
      status: { label: "статус рекомендации", unit: "" },
      current: { label: "часы сейчас", unit: "ч" },
      proposed: { label: "предлагаемые часы", unit: "ч" },
      delta: { label: "изменение часов", unit: "ч" },
    };
    meta = planMeta[metric];
    if (parts.length === 2) subject = "План часов";
  }
  let label = meta ? (subject ? `${subject} — ${meta.label}` : meta.label) : key;
  if (parts[0] === "comparison") {
    label = label.replaceAll("{A}", String(facts[`${entity}.name_a`] ?? "А"))
      .replaceAll("{B}", String(facts[`${entity}.name_b`] ?? "Б"));
  }
  return { key, label, value: formatValue(value, meta?.unit ?? "", metric), href };
}
