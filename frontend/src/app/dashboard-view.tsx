"use client";

import { AlertTriangle, ArrowRight, BookOpen, ClipboardList, Gauge, Lightbulb, Users } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { AssessmentObservations, MasteryChart } from "@/components/charts";
import { FilterBar, useFilters } from "@/components/filter-bar";
import { useMeta } from "@/components/meta-provider";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { KindTag, MasteryBar, StatCard, StatusBadge } from "@/components/ui-bits";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useApi } from "@/hooks/use-api";
import { t } from "@/i18n";
import { toQuery } from "@/lib/filters";
import { date, int, pct } from "@/lib/format";
import { summarizeGain } from "@/lib/gain";
import type { Opportunity, OverviewResponse, TopicStat } from "@/lib/types";
import { cn } from "@/lib/utils";

const SEVERITY = {
  high: "border-l-danger",
  medium: "border-l-warning",
  low: "border-l-primary",
} as const;

const OPPORTUNITY_LABEL: Record<Opportunity["type"], string> = {
  hours_review: "Распределение часов",
  difficult_topic: "Трудная тема",
  decline: "Снижение результатов",
  watch_topic: "Требует внимания",
};

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

function topicHref(query: string, code: string) {
  return `/topics${query}${query ? "&" : "?"}topic=${encodeURIComponent(code)}`;
}

/** Up to two topics flagged by the existing classification (difficult, else watch), lowest mastery first. */
function priorityTopics(data: OverviewResponse): TopicStat[] {
  const flagged = data.difficult_topics.filter((x) => x.status === "difficult");
  const list = flagged.length ? flagged : data.difficult_topics.filter((x) => x.status === "watch");
  return list.slice(0, 2);
}

function Content({ data, query }: { data: OverviewResponse; query: string }) {
  const ov = data.overview;
  const s = data.settings;
  const difficultCount = data.topics.filter((x) => x.status === "difficult").length;
  const [order, setOrder] = useState<"curriculum" | "mastery">("curriculum");
  const chartTopics = order === "curriculum" ? data.topics
    : [...data.topics].sort((a, b) => (a.mastery ?? 101) - (b.mastery ?? 101));
  const priority = priorityTopics(data);
  const declines = data.opportunities.filter((o) => o.type === "decline" && !priority.some((p) => p.topic_id === o.topic_id));
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

      <Card className="border-primary/25" data-testid="first-checks">
        <CardHeader>
          <CardTitle>Что проверить в первую очередь</CardTitle>
          <CardDescription>
            Темы с самым низким освоением среди отмеченных классификацией. Освоение и изменение от входной диагностики — разные
            показатели; это наблюдения, а не причинные выводы.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {priority.length === 0 && declines.length === 0 ? (
            <p className="text-sm text-muted-foreground">Тем ниже порогов «трудная» и «внимание» и значимых снижений нет.</p>
          ) : (
            <ul className="grid gap-3 lg:grid-cols-2">
              {priority.map((tp) => <PriorityItem key={tp.topic_id} tp={tp} data={data} query={query} />)}
              {declines.slice(0, Math.max(0, 2 - priority.length)).map((o) => (
                <li key={`d${o.topic_id}`} className="rounded-lg border border-l-4 border-l-danger p-3 text-sm">
                  <div className="mb-1 flex flex-wrap items-center gap-2"><KindTag kind="observation" />
                    <Badge variant="outline">{OPPORTUNITY_LABEL.decline}</Badge></div>
                  <p>{o.text}</p>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-6 xl:grid-cols-5">
        <Card className="xl:col-span-3">
          <CardHeader>
            <CardTitle>Освоение по темам</CardTitle>
            <CardDescription>Σ набранных / Σ максимальных баллов × 100. Пунктир — пороги «трудная» и «внимание».</CardDescription>
            <CardAction>
              <div role="group" aria-label="Порядок тем на диаграмме" className="flex rounded-md border p-0.5 text-xs">
                {([["curriculum", "По программе"], ["mastery", "По освоению"]] as const).map(([k, label]) => (
                  <button key={k} type="button" aria-pressed={order === k} onClick={() => setOrder(k)}
                    className={cn("rounded px-2 py-1 outline-none focus-visible:ring-2 focus-visible:ring-ring",
                      order === k ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground hover:text-foreground")}>
                    {label}
                  </button>
                ))}
              </div>
            </CardAction>
          </CardHeader>
          <CardContent>
            <MasteryChart data={chartTopics} difficult={s.difficult_threshold} watch={s.watch_threshold} />
          </CardContent>
        </Card>

        <Card className="xl:col-span-2">
          <CardHeader>
            <CardTitle>Темы с самым низким освоением</CardTitle>
            <CardDescription>
              Пять тем с наименьшим освоением, с их статусом (выборка не меньше {s.min_students_topic} учеников). Статус «Норма»
              означает, что тема выше порогов.
            </CardDescription>
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
                  <div className="flex items-start justify-between gap-2 text-sm">
                    <Link href={topicHref(query, tp.code)} className="min-w-0 font-medium break-words hover:underline focus-visible:underline">
                      {tp.name}
                    </Link>
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

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Lightbulb className="size-4 text-amber-700" aria-hidden /> Возможности для улучшения программы</CardTitle>
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
                  <Badge variant="outline" className="mb-1 text-[11px]">{OPPORTUNITY_LABEL[o.type]}</Badge>
                  <p>{o.text}</p>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Результаты отдельных оцениваний</CardTitle>
            <CardDescription>
              Каждая точка — отдельное оценивание своей группы учеников; точки не соединены. Входная диагностика показывает
              исходный уровень и не входит в «освоение».
            </CardDescription>
          </CardHeader>
          <CardContent>
            <p className="mb-3 rounded-md border border-warning/40 bg-warning/10 p-2.5 text-xs text-amber-900" data-testid="trend-caution">
              Оценивания относятся к разным группам учеников и содержат разные задания. Этот график не показывает
              индивидуальный прогресс. Изменение у одних и тех же учеников — в парном анализе «входная → итоговая
              диагностика» на странице <Link href={`/topics${query}`} className="font-medium underline underline-offset-2">Анализ тем</Link>.
            </p>
            <AssessmentObservations data={data.trend} />
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
                      <BookOpen className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
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
    </div>
  );
}

function PriorityItem({ tp, data, query }: { tp: TopicStat; data: OverviewResponse; query: string }) {
  const g = summarizeGain(tp.gain);
  const hours = data.opportunities.find((o) => o.topic_id === tp.topic_id && o.type === "hours_review");
  const decline = tp.gain?.direction === "decline";
  return (
    <li className={cn("rounded-lg border border-l-4 p-3 text-sm", tp.status === "difficult" ? "border-l-danger" : "border-l-warning")}
      data-testid="priority-topic">
      <div className="mb-1.5 flex flex-wrap items-center gap-2"><KindTag kind="observation" /><StatusBadge status={tp.status} /></div>
      <p className="font-semibold">{tp.name}</p>
      <p className="mt-1">
        Освоение <b className="tabular-nums">{pct(tp.mastery)}</b> ({tp.student_count} уч.). Изменение от входной диагностики:{" "}
        {g.estimate && <b className="tabular-nums">{g.estimate}</b>}{g.estimate && " · "}<span data-testid="priority-gain">{g.status}</span>
        {g.detail && <span className="text-muted-foreground"> ({g.detail})</span>}.
        {g.note && <> {g.note}</>}
      </p>
      <div className="mt-2 flex flex-wrap gap-2">
        <Button asChild size="sm" variant="outline">
          <Link href={topicHref(query, tp.code)}>{decline ? "Разобрать причины снижения" : "Проверить задания и методику"} → Анализ темы</Link>
        </Button>
        {hours && (
          <Button asChild size="sm" variant="ghost">
            <Link href={`/optimizer${query}`}>Пересмотреть часы → Оптимизатор</Link>
          </Button>
        )}
      </div>
    </li>
  );
}
