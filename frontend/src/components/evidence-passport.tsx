"use client";

import { FileSearch, ShieldAlert, ShieldCheck, ShieldQuestion } from "lucide-react";
import type { ReactNode } from "react";

import { ErrorState, LoadingState } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { useApi } from "@/hooks/use-api";
import type { EvidenceAssessment, EvidenceCategory, Passport } from "@/lib/decision-types";
import { int, num } from "@/lib/format";
import { cn } from "@/lib/utils";

export const EVIDENCE_META: Record<EvidenceCategory, { label: string; className: string }> = {
  supported: { label: "Доказательства достаточны", className: "border-success/30 bg-success/10 text-emerald-800" },
  exploratory: { label: "Предварительные данные", className: "border-warning/40 bg-warning/15 text-amber-800" },
  insufficient: { label: "Недостаточно данных", className: "border-border bg-muted text-muted-foreground" },
  incomparable: { label: "Несопоставимые данные", className: "border-danger/25 bg-danger/10 text-danger" },
  stale: { label: "Устаревшие данные", className: "border-danger/25 bg-danger/10 text-danger" },
};

/** Evidence readiness — not a probability that an intervention works. */
export function EvidenceBadge({ category, className }: { category: EvidenceCategory; className?: string }) {
  const m = EVIDENCE_META[category];
  const Icon = category === "supported" ? ShieldCheck : category === "exploratory" ? ShieldQuestion : ShieldAlert;
  return (
    <Badge variant="outline" className={cn("gap-1 font-medium", m.className, className)} data-testid={`evidence-${category}`}>
      <Icon className="size-3" aria-hidden />
      {m.label}
    </Badge>
  );
}

const STAT_LABEL: Record<string, string> = {
  mastery: "Освоение, %",
  mean: "Среднее по ученикам, %",
  median: "Медиана, %",
  class_mean: "Среднее по классам, %",
  sd: "Ст. отклонение",
  ci_low: "95% ДИ (нижн.)",
  ci_high: "95% ДИ (верхн.)",
  pre_mean: "Входная, %",
  post_mean: "Итоговая, %",
  mean_gain: "Изменение, п.п.",
  gain_ci_low: "ДИ изменения (нижн.)",
  gain_ci_high: "ДИ изменения (верхн.)",
  gain_ci_level: "Уровень ДИ изменения, %",
  p_value_adjusted: "p (с поправкой)",
  family_size: "Тем в семействе сравнений",
  n_paired: "Пар pre/post",
  common_items: "Общих заданий",
  classes_a: "Классов A",
  classes_b: "Классов B",
  baseline_diff: "Разница исходного уровня, п.п.",
  ci_level: "Уровень ДИ, %",
};

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-1.5">
      <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{title}</h3>
      {children}
    </section>
  );
}

export function GateNotice({ gate }: { gate: EvidenceAssessment }) {
  return (
    <div className={cn("rounded-lg border p-3 text-sm", gate.allows_action ? "border-success/30 bg-success/5" : "border-warning/40 bg-warning/10")}
      data-testid="passport-gate">
      <div className="mb-1 flex flex-wrap items-center gap-2">
        <EvidenceBadge category={gate.category} />
        <span className="font-medium">{gate.allows_action ? "Действие допускается (с проверкой методиста)" : "Автоматическое действие заблокировано"}</span>
      </div>
      <ul className="list-disc pl-5 text-muted-foreground">
        {gate.reasons.map((r) => <li key={r}>{r}</li>)}
      </ul>
      {gate.hint && <p className="mt-1 text-xs text-muted-foreground">{gate.hint}</p>}
    </div>
  );
}

/** Explainability panel: what was observed, on which data, how, with what uncertainty, and why an action is allowed. */
export function EvidencePassport({ passport }: { passport: Passport }) {
  const stats = Object.entries(passport.statistics).filter(([, v]) => v !== null && v !== undefined && typeof v !== "object");
  const nested = Object.entries(passport.statistics).filter(([, v]) => v !== null && typeof v === "object");
  return (
    <div className="space-y-4 text-sm" data-testid="evidence-passport">
      <GateNotice gate={passport.gate} />
      <Section title="Наблюдение">
        <ul className="list-disc space-y-0.5 pl-5">{passport.observation.map((o) => <li key={o}>{o}</li>)}</ul>
      </Section>
      {passport.interpretation && (
        <Section title="Статистическая интерпретация">
          <p>{passport.interpretation}</p>
        </Section>
      )}
      <Section title="Ключевые показатели">
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-3">
          {stats.map(([k, v]) => (
            <div key={k} className="min-w-0">
              <dt className="truncate text-xs text-muted-foreground">{STAT_LABEL[k] ?? k}</dt>
              <dd className="font-medium tabular-nums">{typeof v === "number" ? num(v, 2) : String(v)}</dd>
            </div>
          ))}
        </dl>
        {nested.length > 0 && (
          <ul className="mt-1 space-y-0.5 text-xs text-muted-foreground">
            {nested.map(([k, v]) => <li key={k}>{k}: {JSON.stringify(v)}</li>)}
          </ul>
        )}
      </Section>
      <Section title="Неопределённость">
        {passport.uncertainty.length ? <ul className="list-disc space-y-0.5 pl-5">{passport.uncertainty.map((u) => <li key={u}>{u}</li>)}</ul>
          : <p className="text-muted-foreground">Интервалы не рассчитаны.</p>}
      </Section>
      <Section title="Метод">
        <p className="text-muted-foreground">{passport.method}</p>
      </Section>
      {passport.decision && (
        <Section title="Рекомендация (правило принятия решений)">
          <p><span className="font-medium">{passport.decision.action.label}</span> — {passport.decision.problem.label}.</p>
          <p className="text-muted-foreground">Проверка: {passport.decision.required_review}</p>
        </Section>
      )}
      {passport.graph && (passport.graph.weak_downstream.length > 0 || passport.graph.prerequisites.length > 0) && (
        <Section title="Граф программы">
          <p className="text-muted-foreground">
            Пререквизитов: {passport.graph.prerequisites.length}; зависимых тем (транзитивно): {passport.graph.downstream_count}
            {passport.graph.foundational_gap ? "; тема — слабый пререквизит слабых тем (структурная связь, не доказанная причина)." : "."}
          </p>
        </Section>
      )}
      <Section title="Что усилит вывод">
        <ul className="list-disc space-y-0.5 pl-5">{passport.strengthen.map((s) => <li key={s}>{s}</li>)}</ul>
      </Section>
      <Section title="Ограничения">
        <ul className="list-disc space-y-0.5 pl-5 text-muted-foreground">{passport.limitations.map((s) => <li key={s}>{s}</li>)}</ul>
      </Section>
      <Section title="Данные и версия">
        <p className="text-xs break-all text-muted-foreground" data-testid="passport-fingerprint">
          Отпечаток анализа {passport.dataset.fingerprint} · ревизия данных {passport.dataset.revision.hash} ·
          результатов {int(passport.dataset.revision.results)}, учеников {int(passport.dataset.revision.students)} ·
          алгоритм {passport.dataset.algorithm_version}{passport.dataset.synthetic ? " · СИНТЕТИЧЕСКИЕ данные" : ""}
        </p>
      </Section>
    </div>
  );
}

function TopicPassportBody({ path }: { path: string }) {
  const s = useApi<{ passport: Passport }>(path);
  if (s.error) return <ErrorState error={s.error} onRetry={s.reload} />;
  if (s.loading || !s.data) return <LoadingState rows={1} />;
  return <EvidencePassport passport={s.data.passport} />;
}

/** Button + side sheet that loads the passport of one topic for exactly the given scope. */
export function TopicPassportButton({ topicId, topicName, query, size = "sm", label = "Паспорт доказательств" }: {
  topicId: number; topicName: string; query: string; size?: "sm" | "xs" | "default"; label?: string;
}) {
  return (
    <Sheet>
      <SheetTrigger asChild>
        <Button variant="outline" size={size === "xs" ? "sm" : size} className={size === "xs" ? "h-7 px-2 text-xs" : undefined}
          aria-label={`${label}: ${topicName}`} data-testid={`passport-open-${topicId}`}>
          <FileSearch className="size-3.5" aria-hidden /> {label}
        </Button>
      </SheetTrigger>
      <SheetContent side="right" className="w-full overflow-y-auto p-5 sm:max-w-xl">
        <SheetHeader className="p-0 pb-3">
          <SheetTitle>Паспорт доказательств: «{topicName}»</SheetTitle>
          <SheetDescription>Наблюдения, метод, неопределённость и основание решения. Это не прогноз результатов.</SheetDescription>
        </SheetHeader>
        <TopicPassportBody path={`/api/evidence/topics/${topicId}${query}`} />
      </SheetContent>
    </Sheet>
  );
}

export function PassportSheet({ passport, trigger }: { passport: Passport; trigger: ReactNode }) {
  return (
    <Sheet>
      <SheetTrigger asChild>{trigger}</SheetTrigger>
      <SheetContent side="right" className="w-full overflow-y-auto p-5 sm:max-w-xl">
        <SheetHeader className="p-0 pb-3">
          <SheetTitle>Паспорт доказательств: {passport.title}</SheetTitle>
          <SheetDescription>Наблюдения, метод, неопределённость и основание вывода.</SheetDescription>
        </SheetHeader>
        <EvidencePassport passport={passport} />
      </SheetContent>
    </Sheet>
  );
}
