"use client";

import { Info } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { DistributionChart, MultiSeriesTrend } from "@/components/charts";
import { FilterBar, useFilters } from "@/components/filter-bar";
import { RequireData } from "@/components/page-frame";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { MasteryBar, StatusBadge } from "@/components/ui-bits";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useApi } from "@/hooks/use-api";
import { t } from "@/i18n";
import { toQuery } from "@/lib/filters";
import { KIND_LABEL, ci, date, int, num, pct, signed } from "@/lib/format";
import type { TopicStat, TopicsResponse } from "@/lib/types";
import { cn } from "@/lib/utils";

const DIRECTION_LABEL = {
  increase: "значимый рост",
  decline: "значимое снижение",
  inconclusive: "изменение не установлено",
  insufficient: "мало пар для оценки",
} as const;

export function TopicsView() {
  return (
    <RequireData>
      <FilterBar />
      <TopicsContent />
    </RequireData>
  );
}

function TopicsContent() {
  const [filters] = useFilters();
  const { data, error, loading, reload } = useApi<TopicsResponse>(`/api/analytics/topics${toQuery(filters)}`);
  const [selectedId, setSelectedId] = useState<number | null>(null);

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
  const selected = data.topics.find((x) => x.topic_id === selectedId) ?? data.topics.find((x) => x.status === "difficult") ?? data.topics[0];

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Показатели по темам</CardTitle>
          <CardDescription>
            Освоение — объединённые баллы по итоговым и текущим оцениваниям (Σ/Σ); медиана — по ученикам; изменение —
            парные pre/post в одной группе сравнения с поправкой Бонферрони на число тем.
            Пороги: трудная &lt; {s.difficult_threshold}%, внимание &lt; {s.watch_threshold}%, минимум {s.min_students_topic} учеников —{" "}
            <Link href="/settings" className="text-primary underline-offset-4 hover:underline">изменить</Link>.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <Table data-testid="topics-table">
              <TableHeader>
                <TableRow>
                  <TableHead>Тема</TableHead>
                  <TableHead className="w-40">Освоение</TableHead>
                  <TableHead className="text-right">Медиана</TableHead>
                  <TableHead className="text-right">Учеников</TableHead>
                  <TableHead className="text-right">Оценив.</TableHead>
                  <TableHead className="text-right">Прирост, п.п.</TableHead>
                  <TableHead className="text-right">Часы (ср. по классам)</TableHead>
                  <TableHead>Статус</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.topics.map((tp) => (
                  <TableRow key={tp.topic_id} onClick={() => setSelectedId(tp.topic_id)}
                    className={cn("cursor-pointer", selected?.topic_id === tp.topic_id && "bg-accent/60")}
                    aria-selected={selected?.topic_id === tp.topic_id}>
                    <TableCell className="font-medium">
                      <button type="button" className="text-left hover:underline" onClick={() => setSelectedId(tp.topic_id)}>
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
                    <TableCell className="text-right tabular-nums">
                      {tp.gain ? (
                        <span className={cn(tp.gain.direction === "decline" ? "text-danger" : tp.gain.significant
                          ? "text-foreground" : "text-muted-foreground")} data-testid={`gain-${tp.code}`}>
                          {tp.gain.direction === "insufficient" ? "мало пар" : signed(tp.gain.mean_gain)}
                          {tp.gain.direction === "inconclusive" && " (н.у.)"}
                          {tp.gain.direction === "decline" && " ↓"}
                        </span>
                      ) : "—"}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{num(tp.hours)}</TableCell>
                    <TableCell><StatusBadge status={tp.status} /></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">н.у. — изменение не установлено (интервал с поправкой на число тем включает ноль; это не доказывает отсутствие
            эффекта). ↓ — статистически значимое снижение. Нажмите на тему, чтобы открыть детали.</p>
        </CardContent>
      </Card>

      {selected && <TopicDetail topic={selected} data={data} />}

      <Card>
        <CardHeader>
          <CardTitle>Динамика проблемных тем</CardTitle>
          <CardDescription>Освоение по каждому оцениванию (включая входную диагностику) для тем со статусом «трудная» или «внимание»</CardDescription>
        </CardHeader>
        <CardContent>
          {trend.rows.length ? <MultiSeriesTrend data={trend.rows} series={trend.series} /> :
            <p className="text-sm text-muted-foreground">Недостаточно данных для динамики.</p>}
        </CardContent>
      </Card>
    </div>
  );
}

function TopicDetail({ topic, data }: { topic: TopicStat; data: TopicsResponse }) {
  const points = data.trends.filter((p) => p.topic_id === topic.topic_id);
  const g = topic.gain;
  return (
    <div className="grid gap-6 lg:grid-cols-3" data-testid="topic-detail">
      <Card className="lg:col-span-2">
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
            <Info className="mt-0.5 size-4 shrink-0 text-primary" />
            <p>{topic.interpretation}</p>
          </div>
          {g ? (
            <div className="space-y-1">
              <div className="font-medium">Изменение pre → post ({g.n_paired} пар)</div>
              <div>{pct(g.pre_mean)} → {pct(g.post_mean)}: <b>{signed(g.mean_gain, " п.п.")}</b></div>
              <div className="text-muted-foreground">
                {g.ci_level}% ДИ (поправка на {g.family_size} тем): {ci(g.ci_low, g.ci_high)}; p с поправкой ={" "}
                {g.p_value_adjusted ?? "—"}; нормализованный прирост g = {num(g.normalized_gain, 2)}
              </div>
              <Badge variant="outline" data-testid="gain-direction">{DIRECTION_LABEL[g.direction]}</Badge>
            </div>
          ) : (
            <p className="text-muted-foreground">Нет пары входной и итоговой диагностики — прирост не рассчитывается.</p>
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

function Metric({ k, v, sub }: { k: string; v: string; sub?: string }) {
  return (
    <div className="rounded-lg border p-2.5">
      <div className="text-xs text-muted-foreground">{k}</div>
      <div className="font-semibold tabular-nums">{v}</div>
      {sub && <div className="text-xs text-muted-foreground tabular-nums">{sub}</div>}
    </div>
  );
}
