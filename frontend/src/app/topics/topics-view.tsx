"use client";

import { ChevronRight, Info } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMemo, useRef, useState } from "react";

import { DistributionChart, MultiSeriesTrend } from "@/components/charts";
import { TopicPassportButton } from "@/components/evidence-passport";
import { FilterBar, useFilters } from "@/components/filter-bar";
import { RequireData } from "@/components/page-frame";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { MasteryBar, StatusBadge } from "@/components/ui-bits";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useApi } from "@/hooks/use-api";
import { t } from "@/i18n";
import { toQuery } from "@/lib/filters";
import { KIND_LABEL, ci, date, int, num, pct } from "@/lib/format";
import { summarizeGain, type GainSummary } from "@/lib/gain";
import type { TopicStat, TopicsResponse } from "@/lib/types";
import { cn } from "@/lib/utils";

export function TopicsView() {
  return (
    <RequireData>
      <FilterBar />
      <TopicsContent />
    </RequireData>
  );
}

const TONE: Record<GainSummary["tone"], string> = {
  positive: "text-foreground",
  negative: "text-danger",
  neutral: "text-muted-foreground",
  unknown: "text-muted-foreground",
};

function GainInline({ tp }: { tp: TopicStat }) {
  const g = summarizeGain(tp.gain);
  return (
    <span className={cn("tabular-nums", TONE[g.tone])} data-testid={`gain-${tp.code}`}>
      {g.estimate && <b className="font-semibold">{g.estimate}</b>}
      {g.estimate && " · "}
      <span>{g.status}</span>
    </span>
  );
}

function TopicsContent() {
  const [filters] = useFilters();
  const params = useSearchParams();
  const { data, error, loading, reload } = useApi<TopicsResponse>(`/api/analytics/topics${toQuery(filters)}`);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [mobileTable, setMobileTable] = useState(false);
  const opener = useRef<HTMLButtonElement | null>(null);

  const trend = useMemo(() => {
    if (!data) return { rows: [], series: [] as { key: string; name: string }[] };
    const focus = data.topics.filter((x) => x.status === "difficult" || x.status === "watch").slice(0, 4);
    const chosen = focus.length ? focus : data.topics.slice(0, 4);
    const byAssessment = new Map<string, Record<string, string | number | null>>();
    for (const p of data.trends) {
      if (!chosen.some((c) => c.topic_id === p.topic_id)) continue;
      const row = byAssessment.get(p.assessment) ?? { label: p.assessment, date: p.date };
      row[`t${p.topic_id}`] = p.mastery;
      byAssessment.set(p.assessment, row);
    }
    const rows = [...byAssessment.values()].sort((a, b) => String(a.date).localeCompare(String(b.date)));
    return { rows, series: chosen.map((c) => ({ key: `t${c.topic_id}`, name: c.name })) };
  }, [data]);

  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (loading || !data) return <LoadingState />;
  if (data.topics.length === 0) return <EmptyState text={t.states.emptyFiltered} showImport={false} />;

  const s = data.settings;
  const fromUrl = params.get("topic");
  const selected = data.topics.find((x) => x.topic_id === selectedId)
    ?? data.topics.find((x) => x.code === fromUrl)
    ?? data.topics.find((x) => x.status === "difficult") ?? data.topics[0];

  const openMobile = (id: number, button: HTMLButtonElement) => {
    opener.current = button;
    setSelectedId(id);
    setSheetOpen(true);
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Показатели по темам</CardTitle>
          <CardDescription>
            Освоение — объединённые баллы итоговых и текущих оцениваний (Σ/Σ). Изменение — у одних и тех же учеников от
            входной к итоговой диагностике, с поправкой на число тем. Пороги: трудная &lt; {s.difficult_threshold}%,
            внимание &lt; {s.watch_threshold}%, минимум {s.min_students_topic} учеников —{" "}
            <Link href="/settings" className="text-primary underline-offset-4 hover:underline">изменить</Link>.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {/* Narrow screens: one summary per topic keeps name, mastery, change and status together. */}
          <div className="md:hidden">
            <div className="mb-3 flex items-center justify-between gap-2 text-xs text-muted-foreground">
              <span>{data.topics.length} тем</span>
              <Button size="sm" variant="ghost" aria-pressed={mobileTable} onClick={() => setMobileTable((v) => !v)}>
                {mobileTable ? "Показать карточками" : "Показать полной таблицей"}
              </Button>
            </div>
            {!mobileTable && (
              <ul className="space-y-2" data-testid="topics-cards">
                {data.topics.map((tp) => (
                  <li key={tp.topic_id} className={cn("rounded-lg border p-3", selected?.topic_id === tp.topic_id && "border-primary/40 bg-accent/40")}>
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="font-medium break-words">{tp.name}</div>
                        <div className="text-xs text-muted-foreground">{tp.code} · {tp.grade} класс · {int(tp.student_count)} уч.</div>
                      </div>
                      <StatusBadge status={tp.status} />
                    </div>
                    <div className="mt-2 flex items-center gap-2 text-sm">
                      <span className="w-14 shrink-0 tabular-nums">{pct(tp.mastery)}</span>
                      <MasteryBar value={tp.mastery} threshold={s.difficult_threshold} />
                    </div>
                    <div className="mt-1.5 text-sm">
                      <span className="text-muted-foreground">Изменение: </span><GainInline tp={tp} />
                    </div>
                    <Button size="sm" variant="outline" className="mt-2 w-full" onClick={(e) => openMobile(tp.topic_id, e.currentTarget)}
                      aria-label={`Подробнее: ${tp.name}`} data-testid="topic-more">
                      Подробнее <ChevronRight className="size-4" aria-hidden />
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className={cn(mobileTable ? "block" : "hidden", "md:block")}>
            <p className="mb-2 text-xs text-muted-foreground md:hidden">Таблица прокручивается по горизонтали.</p>
            <div className="overflow-x-auto">
              <Table data-testid="topics-table">
                <caption className="sr-only">Показатели по темам; выберите тему, чтобы открыть подробности ниже таблицы</caption>
                <TableHeader>
                  <TableRow>
                    <TableHead className="sticky left-0 z-10 bg-card">Тема</TableHead>
                    <TableHead className="w-40">Освоение</TableHead>
                    <TableHead className="text-right">Медиана</TableHead>
                    <TableHead className="text-right">Учеников</TableHead>
                    <TableHead className="text-right">Оценив.</TableHead>
                    <TableHead>Изменение от входной диагностики</TableHead>
                    <TableHead className="text-right">Часы (ср. по классам)</TableHead>
                    <TableHead>Статус</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.topics.map((tp) => {
                    const isSel = selected?.topic_id === tp.topic_id;
                    return (
                      <TableRow key={tp.topic_id} onClick={() => setSelectedId(tp.topic_id)}
                        className={cn("cursor-pointer", isSel && "bg-accent/60")} aria-selected={isSel}>
                        <TableCell className={cn("sticky left-0 z-10 max-w-64 font-medium whitespace-normal", isSel ? "bg-accent" : "bg-card")}>
                          <button type="button" aria-pressed={isSel} aria-controls="topic-detail"
                            className="rounded text-left outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
                            onClick={() => setSelectedId(tp.topic_id)}>
                            {tp.name}
                          </button>
                          <div className="text-xs text-muted-foreground">{tp.code} · {tp.grade} класс</div>
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-2">
                            <span className="w-12 tabular-nums">{pct(tp.mastery)}</span>
                            <MasteryBar value={tp.mastery} threshold={s.difficult_threshold} />
                          </div>
                        </TableCell>
                        <TableCell className="text-right tabular-nums">{pct(tp.median)}</TableCell>
                        <TableCell className="text-right tabular-nums">{int(tp.student_count)}</TableCell>
                        <TableCell className="text-right tabular-nums">{tp.assessment_count}</TableCell>
                        <TableCell className="min-w-44 whitespace-normal text-sm"><GainInline tp={tp} /></TableCell>
                        <TableCell className="text-right tabular-nums">{num(tp.hours)}</TableCell>
                        <TableCell><StatusBadge status={tp.status} /></TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            «Изменение не установлено» — интервал с поправкой на число тем включает ноль; это не доказывает отсутствие эффекта.
            Оценка в п.п. всегда показана вместе со статусом. <span className="hidden md:inline">Выберите тему — подробности
            откроются <a href="#topic-detail" className="text-primary underline-offset-2 hover:underline">ниже таблицы</a>.</span>
          </p>
        </CardContent>
      </Card>

      {selected && (
        <div className="hidden md:block">
          <TopicDetail topic={selected} data={data} />
        </div>
      )}

      <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
        <SheetContent side="bottom" className="max-h-[88dvh] overflow-y-auto p-4 md:hidden" data-testid="topic-sheet"
          onCloseAutoFocus={(e) => {
            // Return focus to the "Подробнее" button that opened the sheet (there is no Radix trigger here).
            e.preventDefault();
            opener.current?.focus();
          }}>
          <SheetHeader className="p-0 pb-2">
            <SheetTitle>{selected?.name}</SheetTitle>
            <SheetDescription>Подробности темы для текущей группы анализа</SheetDescription>
          </SheetHeader>
          {selected && <TopicDetail topic={selected} data={data} compact />}
        </SheetContent>
      </Sheet>

      <Card>
        <CardHeader>
          <CardTitle>Результаты проблемных тем по оцениваниям</CardTitle>
          <CardDescription>
            Освоение по каждому оцениванию (включая входную диагностику) для тем со статусом «трудная» или «внимание». Точки
            не соединены: оценивания содержат разные задания, поэтому это не траектория прогресса — для неё служит парное
            изменение в таблице выше.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {trend.rows.length ? <MultiSeriesTrend data={trend.rows} series={trend.series} connect={false} /> :
            <p className="text-sm text-muted-foreground">Недостаточно данных для динамики.</p>}
        </CardContent>
      </Card>
    </div>
  );
}

function TopicDetail({ topic, data, compact = false }: { topic: TopicStat; data: TopicsResponse; compact?: boolean }) {
  const points = data.trends.filter((p) => p.topic_id === topic.topic_id);
  const g = topic.gain;
  const gs = summarizeGain(g);
  return (
    <div className={cn("grid gap-6", !compact && "lg:grid-cols-3")} id={compact ? undefined : "topic-detail"}
      data-testid={compact ? "topic-detail-sheet" : "topic-detail"} tabIndex={-1}>
      <Card className={cn(!compact && "lg:col-span-2")}>
        <CardHeader>
          <CardTitle className="flex flex-wrap items-center gap-2">{topic.name} <StatusBadge status={topic.status} /></CardTitle>
          <CardDescription>Распределение результатов учеников (процент баллов по итоговым и текущим оцениваниям)</CardDescription>
        </CardHeader>
        <CardContent>
          {topic.distribution.length ? <DistributionChart bins={topic.distribution} /> :
            <p className="text-sm text-muted-foreground">Нет итоговых оцениваний по теме.</p>}
          <div className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            <Metric k="Освоение" v={pct(topic.mastery)} />
            <Metric k="Среднее (95% ДИ)" v={`${pct(topic.mean)}`} sub={ci(topic.ci_low, topic.ci_high)} />
            <Metric k="Медиана" v={pct(topic.median)} />
            <Metric k="Среднее по классам" v={pct(topic.class_mean)} sub={`${topic.class_count} кл., каждый с равным весом`} />
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Интерпретация</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 text-sm">
          <div className="flex gap-2 rounded-lg bg-muted/60 p-3">
            <Info className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
            <p>{topic.interpretation}</p>
          </div>
          <PassportForTopic topic={topic} />
          {g ? (
            <div className="space-y-1">
              <div className="font-medium">Изменение: входная → итоговая диагностика ({g.n_paired} пар)</div>
              <div>{pct(g.pre_mean)} → {pct(g.post_mean)}{gs.estimate && <>: <b>{gs.estimate}</b></>}</div>
              <Badge variant="outline" data-testid="gain-direction">{gs.status}</Badge>
              {gs.note && <p>{gs.note}</p>}
              <div className="text-muted-foreground">
                {num(g.ci_level, 2)}% ДИ (поправка на {g.family_size} тем): {ci(g.ci_low, g.ci_high)}; p с поправкой ={" "}
                {g.p_value_adjusted ?? "—"}; нормализованный прирост g = {num(g.normalized_gain, 2)}. ДИ — диапазон
                статистической неопределённости; он не учитывает все возможные искажения.
              </div>
            </div>
          ) : (
            <p className="text-muted-foreground">Нет пары входной и итоговой диагностики — изменение не рассчитывается.</p>
          )}
          <div>
            <div className="mb-1 font-medium">По оцениваниям</div>
            <ul className="space-y-1">
              {points.map((p) => (
                <li key={p.assessment_id} className="flex justify-between gap-2 text-xs">
                  <span>{p.assessment} · {date(p.date)} · {KIND_LABEL[p.kind]}</span>
                  <span className="tabular-nums">{pct(p.mastery)} ({p.students} уч.)</span>
                </li>
              ))}
            </ul>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

/** Evidence Passport for the same scope as the topic analysis (subject and grade pinned to the topic). */
function PassportForTopic({ topic }: { topic: TopicStat }) {
  const [filters] = useFilters();
  const q = toQuery({ ...filters, subject_id: filters.subject_id, grade: topic.grade });
  return <TopicPassportButton topicId={topic.topic_id} topicName={topic.name} query={q} />;
}

function Metric({ k, v, sub }: { k: string; v: string; sub?: string }) {
  return (
    <div className="rounded-lg border p-2.5">
      <div className="text-xs text-muted-foreground">{k}</div>
      <div className="font-semibold tabular-nums">{v}</div>
      {sub && <div className="text-xs text-muted-foreground tabular-nums">{sub}</div>}
    </div>
  );
}
