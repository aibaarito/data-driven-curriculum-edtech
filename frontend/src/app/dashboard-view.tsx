"use client";

import { AlertTriangle, ArrowRight, BookOpen, ClipboardList, Gauge, Lightbulb, Users } from "lucide-react";
import Link from "next/link";

import { MasteryChart, TrendChart } from "@/components/charts";
import { FilterBar, useFilters } from "@/components/filter-bar";
import { useMeta } from "@/components/meta-provider";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { MasteryBar, StatCard, StatusBadge } from "@/components/ui-bits";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useApi } from "@/hooks/use-api";
import { t } from "@/i18n";
import { toQuery } from "@/lib/filters";
import { date, int, pct } from "@/lib/format";
import type { OverviewResponse } from "@/lib/types";
import { cn } from "@/lib/utils";

const SEVERITY = {
  high: "border-l-danger",
  medium: "border-l-warning",
  low: "border-l-primary",
} as const;

export function DashboardView() {
  const meta = useMeta();
  const [filters] = useFilters();
  const q = toQuery(filters);
  const { data, error, loading, reload } = useApi<OverviewResponse>(meta.data?.has_data ? `/api/analytics/overview${q}` : null);

  if (meta.error) return <ErrorState error={meta.error} onRetry={meta.reload} />;
  if (meta.loading && !meta.data) return <LoadingState />;
  if (!meta.data?.has_data) return <EmptyState />;

  return (
    <>
      <FilterBar />
      {error ? (
        <ErrorState error={error} onRetry={reload} />
      ) : loading || !data ? (
        <LoadingState />
      ) : !data.overview.has_data ? (
        <EmptyState text={t.states.emptyFiltered} showImport={false} />
      ) : (
        <Content data={data} query={q} />
      )}
    </>
  );
}

function Content({ data, query }: { data: OverviewResponse; query: string }) {
  const ov = data.overview;
  const s = data.settings;
  const difficultCount = data.topics.filter((x) => x.status === "difficult").length;
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Учеников" value={int(ov.students)} icon={Users} hint={`${int(ov.classes)} классов`} testId="kpi-students" />
        <StatCard label="Оцениваний" value={int(ov.assessments)} icon={ClipboardList}
          hint={`${date(ov.date_from)} — ${date(ov.date_to)}`} testId="kpi-assessments" />
        <StatCard label="Среднее освоение" value={pct(ov.average_mastery)} icon={Gauge}
          hint="Итоговые и текущие оценивания" testId="kpi-mastery" />
        <StatCard label="Трудных тем" value={int(difficultCount)} icon={AlertTriangle}
          hint={`Освоение ниже ${s.difficult_threshold}%`} testId="kpi-difficult" />
      </div>

      <div className="grid gap-6 xl:grid-cols-5">
        <Card className="xl:col-span-3">
          <CardHeader>
            <CardTitle>Освоение по темам</CardTitle>
            <CardDescription>Σ набранных / Σ максимальных баллов × 100. Пунктир — пороги «трудная» и «внимание».</CardDescription>
          </CardHeader>
          <CardContent>
            <MasteryChart data={data.topics} difficult={s.difficult_threshold} watch={s.watch_threshold} />
          </CardContent>
        </Card>

        <Card className="xl:col-span-2">
          <CardHeader>
            <CardTitle>Самые трудные темы</CardTitle>
            <CardDescription>По наблюдаемому освоению (выборка не меньше {s.min_students_topic} учеников)</CardDescription>
            <CardAction>
              <Button asChild variant="ghost" size="sm">
                <Link href={`/topics${query}`}>Все темы <ArrowRight className="size-3.5" /></Link>
              </Button>
            </CardAction>
          </CardHeader>
          <CardContent>
            <ul className="space-y-3" data-testid="difficult-topics">
              {data.difficult_topics.map((tp) => (
                <li key={tp.topic_id} className="space-y-1.5">
                  <div className="flex items-center justify-between gap-2 text-sm">
                    <span className="truncate font-medium">{tp.name}</span>
                    <span className="flex shrink-0 items-center gap-2">
                      <span className="tabular-nums">{pct(tp.mastery)}</span>
                      <StatusBadge status={tp.status} />
                    </span>
                  </div>
                  <MasteryBar value={tp.mastery} threshold={s.difficult_threshold} />
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Динамика по оцениваниям</CardTitle>
            <CardDescription>Входная диагностика показывает исходный уровень и не входит в «освоение»</CardDescription>
          </CardHeader>
          <CardContent>
            <TrendChart data={data.trend} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Учебники</CardTitle>
            <CardDescription>Краткие итоги — подробности и оговорки на странице сравнения</CardDescription>
            <CardAction>
              <Button asChild variant="ghost" size="sm">
                <Link href={`/textbooks${query}`}>Сравнение <ArrowRight className="size-3.5" /></Link>
              </Button>
            </CardAction>
          </CardHeader>
          <CardContent className="space-y-4">
            {data.textbooks.length === 0 ? (
              <p className="text-sm text-muted-foreground">Нет данных с указанными учебниками.</p>
            ) : (
              <div className="grid gap-2 sm:grid-cols-2">
                {data.textbooks.map((tb) => (
                  <div key={tb.textbook_id} className="rounded-lg border p-3">
                    <div className="flex items-start gap-2 text-sm font-medium">
                      <BookOpen className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                      <span>{tb.name}</span>
                    </div>
                    <div className="mt-2 grid grid-cols-3 gap-1 text-xs text-muted-foreground">
                      <span>Учеников<br /><b className="text-foreground">{tb.students}</b></span>
                      <span>Среднее<br /><b className="text-foreground">{pct(tb.mean)}</b></span>
                      <span>Исх. уровень<br /><b className="text-foreground">{pct(tb.baseline_mean)}</b></span>
                    </div>
                  </div>
                ))}
              </div>
            )}
            {data.textbook_verdicts.map((v) => (
              <div key={`${v.name_a}-${v.name_b}`}
                className={cn("rounded-lg border p-3 text-sm",
                  v.verdict === "observed_difference" ? "border-primary/25 bg-accent/50" : "bg-muted/50")}>
                <div className="mb-1 text-xs font-medium text-muted-foreground">{v.name_a} — {v.name_b}</div>
                {v.verdict_text}
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Lightbulb className="size-4 text-amber-500" /> Возможности для улучшения программы</CardTitle>
          <CardDescription>Наблюдения по данным — не причинные выводы. Решение принимает методист.</CardDescription>
          <CardAction>
            <Button asChild size="sm">
              <Link href={`/optimizer${query}`}>Открыть оптимизатор</Link>
            </Button>
          </CardAction>
        </CardHeader>
        <CardContent>
          {data.opportunities.length === 0 ? (
            <p className="text-sm text-muted-foreground">Существенных сигналов не обнаружено.</p>
          ) : (
            <ul className="grid gap-2 md:grid-cols-2" data-testid="opportunities">
              {data.opportunities.map((o, i) => (
                <li key={i} className={cn("rounded-md border border-l-4 bg-card p-3 text-sm", SEVERITY[o.severity])}>
                  <Badge variant="outline" className="mb-1 text-[11px]">
                    {o.type === "hours_review" ? "Распределение часов" : o.type === "difficult_topic" ? "Трудная тема" :
                      o.type === "decline" ? "Снижение результатов" : "Требует внимания"}
                  </Badge>
                  <p>{o.text}</p>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
