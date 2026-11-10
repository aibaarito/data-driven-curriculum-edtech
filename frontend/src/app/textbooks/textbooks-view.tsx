"use client";

import { AlertTriangle, CheckCircle2, HelpCircle } from "lucide-react";

import { DistributionChart, GroupedBars, PALETTE } from "@/components/charts";
import { FilterBar, useFilters } from "@/components/filter-bar";
import { RequireData } from "@/components/page-frame";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useApi } from "@/hooks/use-api";
import { toQuery } from "@/lib/filters";
import { ci, int, num, pct, signed } from "@/lib/format";
import type { TextbookPair, TextbooksResponse } from "@/lib/types";

export function TextbooksView() {
  return (
    <RequireData>
      <FilterBar fields={["subject", "grade", "period"]} />
      <Content />
    </RequireData>
  );
}

function Content() {
  const [f] = useFilters();
  const { data, error, loading, reload } = useApi<TextbooksResponse>(`/api/analytics/textbooks${toQuery({ ...f, class_id: undefined, textbook_id: undefined })}`);
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (loading || !data) return <LoadingState />;
  if (data.textbooks.length === 0) return <EmptyState title="Нет данных об учебниках" text={data.message ?? "Для выбранных фильтров нет классов с указанным учебником."} showImport={false} />;

  const matrix = data.topic_matrix.map((r) => {
    const row: Record<string, string | number | null> = { label: r.name };
    for (const tb of data.textbooks) row[`tb${tb.textbook_id}`] = r.values[String(tb.textbook_id)]?.mastery ?? null;
    return row;
  });

  return (
    <div className="space-y-6">
      <Alert>
        <HelpCircle className="size-4" />
        <AlertTitle>Как читать сравнение</AlertTitle>
        <AlertDescription>
          Сравниваются только учебники одной параллели и только по общим итоговым заданиям. Главная оценка — разница с
          поправкой на исходный уровень (входную диагностику) и стандартными ошибками с учётом классов; её дополняет
          сравнение прироста от входной к итоговой диагностике. Более высокое
          среднее само по себе не означает, что учебник эффективнее.
        </AlertDescription>
      </Alert>

      {data.pairs.length === 0 ? (
        <Card><CardContent className="py-6 text-sm text-muted-foreground">
          Нет пар учебников, используемых в одной параллели и по одному предмету. Выберите параллель, где применяются как минимум два учебника.
        </CardContent></Card>
      ) : (
        <div className="grid gap-4" data-testid="textbook-verdicts">
          {data.pairs.map((p) => <PairCard key={`${p.textbook_a}-${p.textbook_b}`} p={p} />)}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Сводка по учебникам</CardTitle>
          <CardDescription>
            {data.comparable ? `Итоговые показатели по ${data.common_items} общим заданиям (оценивание × тема).` : "Показатели по собственным заданиям каждого учебника — напрямую не сопоставимы."}
          </CardDescription>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Учебник</TableHead><TableHead>Классы</TableHead><TableHead className="text-right">Учеников</TableHead>
                <TableHead className="text-right">Среднее</TableHead><TableHead className="text-right">95% ДИ</TableHead>
                <TableHead className="text-right">Медиана</TableHead><TableHead className="text-right">Исходный уровень</TableHead>
                <TableHead className="text-right">Прирост pre→post (95% ДИ)</TableHead>
                <TableHead className="text-right">Часов на класс</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.textbooks.map((tb, i) => (
                <TableRow key={tb.textbook_id}>
                  <TableCell className="font-medium whitespace-normal">
                    <span className="mr-2 inline-block size-2.5 rounded-full" style={{ background: PALETTE[i % PALETTE.length] }} />
                    {tb.name}
                  </TableCell>
                  <TableCell className="text-sm">{tb.class_names.join(", ")}</TableCell>
                  <TableCell className="text-right tabular-nums">{int(tb.students)}</TableCell>
                  <TableCell className="text-right tabular-nums">{pct(tb.mean)}</TableCell>
                  <TableCell className="text-right tabular-nums">{ci(tb.ci_low, tb.ci_high)}</TableCell>
                  <TableCell className="text-right tabular-nums">{pct(tb.median)}</TableCell>
                  <TableCell className="text-right tabular-nums">{pct(tb.baseline_mean)}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {tb.gain_mean !== null ? <>{signed(tb.gain_mean, " п.п.")}<div className="text-xs text-muted-foreground">{ci(tb.gain_ci_low, tb.gain_ci_high)}</div></> : "—"}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{num(tb.mean_hours_per_class)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {matrix.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Освоение по темам</CardTitle>
            <CardDescription>По общим итоговым заданиям; без поправки на исходный уровень</CardDescription>
          </CardHeader>
          <CardContent>
            <GroupedBars data={matrix} domainMax={100}
              series={data.textbooks.map((tb, i) => ({ key: `tb${tb.textbook_id}`, name: tb.name, color: PALETTE[i % PALETTE.length] }))} />
          </CardContent>
        </Card>
      )}

      <div className="grid gap-6 md:grid-cols-2">
        {data.textbooks.map((tb, i) => (
          <Card key={tb.textbook_id}>
            <CardHeader>
              <CardTitle className="text-base">{tb.name}</CardTitle>
              <CardDescription>Распределение итоговых результатов, {tb.outcome_students} учеников</CardDescription>
            </CardHeader>
            <CardContent><DistributionChart bins={tb.distribution} color={PALETTE[i % PALETTE.length]} /></CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

function PairCard({ p }: { p: TextbookPair }) {
  const observed = p.verdict === "observed_difference";
  return (
    <Card className={observed ? "border-primary/30" : "border-warning/40"}>
      <CardHeader>
        <CardTitle className="flex items-start gap-2 text-base">
          {observed ? <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-primary" /> : <AlertTriangle className="mt-0.5 size-5 shrink-0 text-amber-600" />}
          <span>{p.name_a} <span className="text-muted-foreground">vs</span> {p.name_b}</span>
        </CardTitle>
        <CardDescription className="text-sm text-foreground" data-testid="verdict-text">{p.verdict_text}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Est title="Разница без поправки" sub={`«${p.name_b}» − «${p.name_a}»`} d={p.raw?.diff} lo={p.raw?.ci_low} hi={p.raw?.ci_high}
            extra={p.raw ? `n = ${p.raw.n_a} / ${p.raw.n_b}; g Хеджеса = ${num(p.raw.hedges_g, 2)}` : undefined} />
          <Est title="С поправкой на исходный уровень" sub="ANCOVA, ошибки с учётом классов" d={p.adjusted?.diff} lo={p.adjusted?.ci_low} hi={p.adjusted?.ci_high}
            extra={p.adjusted ? `n = ${p.adjusted.n}, классов = ${p.adjusted.clusters}, p = ${p.adjusted.p_value ?? "—"}` : "не рассчитана"} highlight />
          <Est title="Разница прироста pre→post" sub={p.gain ? `${signed(p.gain.mean_b, " п.п.")} против ${signed(p.gain.mean_a, " п.п.")}` : "нет пар pre/post"}
            d={p.gain?.diff} lo={p.gain?.ci_low} hi={p.gain?.ci_high}
            extra={p.gain ? `n = ${p.gain.n_a} / ${p.gain.n_b}; ${p.gain.method}` : undefined} />
          <Est title="Разница исходного уровня" sub="входная диагностика" d={p.baseline_diff}
            extra={p.hours_diff !== null ? `Разница часов на класс: ${signed(p.hours_diff, " ч")}` : undefined} />
        </div>
        {p.reasons.length > 0 && (
          <div>
            <div className="mb-1 text-sm font-medium">Почему вывод невозможен</div>
            <ul className="list-disc space-y-0.5 pl-5 text-sm text-muted-foreground">{p.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
          </div>
        )}
        <div>
          <div className="mb-1 text-sm font-medium">Возможные искажающие факторы</div>
          <ul className="list-disc space-y-0.5 pl-5 text-sm text-muted-foreground">{p.confounders.map((r) => <li key={r}>{r}</li>)}</ul>
        </div>
      </CardContent>
    </Card>
  );
}

function Est({ title, sub, d, lo, hi, extra, highlight }: {
  title: string; sub: string; d?: number | null; lo?: number | null; hi?: number | null; extra?: string; highlight?: boolean;
}) {
  return (
    <div className={highlight ? "rounded-lg border border-primary/25 bg-accent/40 p-3" : "rounded-lg border p-3"}>
      <div className="text-xs font-medium">{title}</div>
      <div className="text-[11px] text-muted-foreground">{sub}</div>
      <div className="mt-1 text-xl font-semibold tabular-nums">{signed(d ?? null, " п.п.")}</div>
      {lo !== undefined && <div className="text-xs text-muted-foreground tabular-nums">95% ДИ: {ci(lo, hi)}</div>}
      {extra && <div className="mt-1 text-xs text-muted-foreground">{extra}</div>}
    </div>
  );
}
