"use client";

import { AlertTriangle, CheckCircle2, HelpCircle } from "lucide-react";

import { DistributionChart, GroupedBars, PALETTE } from "@/components/charts";
import { FilterBar, useFilters } from "@/components/filter-bar";
import { RequireData } from "@/components/page-frame";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
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
        <HelpCircle className="size-4" aria-hidden />
        <AlertTitle>Как читать сравнение</AlertTitle>
        <AlertDescription>
          Сравниваются учебники одной параллели по общим итоговым заданиям. Главная оценка — разница с поправкой на исходный
          уровень; её дополняет разница прироста. Учебник назначается классу, поэтому выводы строятся по классам. Это
          наблюдательные данные: связь не доказывает эффект учебника.
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
            {" "}*Среднее и его интервал — описательные, по ученикам, без учёта группировки по классам; выводы о
            различии — только в карточках сравнения выше.
          </CardDescription>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Учебник</TableHead><TableHead>Классы</TableHead><TableHead className="text-right">Учеников</TableHead>
                <TableHead className="text-right">Среднее</TableHead><TableHead className="text-right">95% ДИ*</TableHead>
                <TableHead className="text-right">Медиана</TableHead><TableHead className="text-right">Исходный уровень</TableHead>
                <TableHead className="text-right">Прирост pre→post (по классам)</TableHead>
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
                    {tb.gain_class_mean !== null ? <>{signed(tb.gain_class_mean, " п.п.")}<div className="text-xs text-muted-foreground">{ci(tb.gain_ci_low, tb.gain_ci_high)}</div></> : "—"}
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

const EVIDENCE_LABEL = {
  insufficient: "Недостаточно данных",
  exploratory: "Предварительный вывод",
  observational: "Наблюдаемая связь",
} as const;

const HEADLINE = {
  insufficient: "Недостаточно данных для вывода о различии",
  exploratory: "Предварительная связь, не доказательство эффекта",
  observational: "Наблюдаемая связь, не доказательство эффекта",
} as const;

function PairCard({ p }: { p: TextbookPair }) {
  const observed = p.verdict === "observed_difference";
  const lvl = p.ci_level;
  const levelNote = p.pairs_in_family > 1 ? ` (поправка на ${p.pairs_in_family} сравнения в выбранной группе)` : "";
  const students = p.raw ? `; учеников ${int(p.raw.n_a)} и ${int(p.raw.n_b)}` : "";
  return (
    <Card className={observed ? "border-primary/30" : "border-warning/40"} data-testid="textbook-pair">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-start gap-2 text-base">
          {observed ? <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-primary" aria-hidden />
            : <AlertTriangle className="mt-0.5 size-5 shrink-0 text-amber-700" aria-hidden />}
          <span>{HEADLINE[p.evidence_level]}</span>
          <Badge variant="outline" data-testid="evidence-level">{EVIDENCE_LABEL[p.evidence_level]}</Badge>
        </CardTitle>
        <CardDescription className="text-sm">
          <span className="font-medium text-foreground">А</span> — {p.name_a}; <span className="font-medium text-foreground">Б</span> — {p.name_b}.
          Единица анализа — класс: классов {p.classes_a} и {p.classes_b}{students}
          {p.excluded_small_classes ? `; исключено малых классов: ${p.excluded_small_classes}` : ""}.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {observed && p.adjusted ? (
          <div className="rounded-lg border border-primary/25 bg-accent/40 p-3" data-testid="pair-verdict">
            <div className="text-xs text-muted-foreground">С поправкой на исходный уровень, Б − А</div>
            <div className="text-2xl font-semibold tabular-nums">{signed(p.adjusted.diff, " п.п.")}</div>
            <div className="text-sm tabular-nums">{num(lvl, 2)}% ДИ: {ci(p.adjusted.ci_low, p.adjusted.ci_high)}{levelNote}</div>
            <p className="mt-2 text-sm">
              Различия могут быть связаны с учителем, составом класса и исходным уровнем: учебники не распределялись случайно.
            </p>
          </div>
        ) : (
          <div className="rounded-lg border border-warning/40 bg-warning/10 p-3 text-sm" data-testid="pair-verdict">
            <p className="font-medium" data-testid="verdict-text">{p.verdict_text}</p>
            {p.reasons.length > 0 && (
              <ul className="mt-1 list-disc space-y-0.5 pl-5">{p.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
            )}
          </div>
        )}

        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Est title="Без поправки" sub="средние классов, Б − А" level={lvl} d={p.raw?.diff} lo={p.raw?.ci_low} hi={p.raw?.ci_high} />
          <Est title="С поправкой на исходный уровень" sub="средние классов, Б − А" level={lvl}
            d={p.adjusted?.diff} lo={p.adjusted?.ci_low} hi={p.adjusted?.ci_high}
            extra={p.adjusted ? undefined : "не оценивается"} highlight />
          <Est title="Разница прироста" level={lvl} sub="входная → итоговая, средние классов, Б − А"
            d={p.gain?.diff} lo={p.gain?.ci_low} hi={p.gain?.ci_high}
            extra={p.gain ? `Прирост: Б ${signed(p.gain.mean_b, " п.п.")}, А ${signed(p.gain.mean_a, " п.п.")}` : "не оценивается"} />
          <Est title="Разница исходного уровня" sub="входная диагностика, Б − А" d={p.baseline_diff}
            extra={p.hours_diff !== null ? `Разница часов на класс: ${signed(p.hours_diff, " ч")}` : undefined} />
        </div>

        {observed && p.reasons.length > 0 && (
          <ul className="list-disc space-y-0.5 pl-5 text-sm text-muted-foreground">{p.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
        )}
        <div>
          <div className="mb-1 text-sm font-medium">Возможные искажающие факторы</div>
          <ul className="list-disc space-y-0.5 pl-5 text-sm text-muted-foreground">{p.confounders.map((r) => <li key={r}>{r}</li>)}</ul>
        </div>

        <details className="rounded-lg border text-sm">
          <summary className="cursor-pointer rounded-lg px-3 py-2 font-medium text-primary outline-none focus-visible:ring-2 focus-visible:ring-ring">
            Как рассчитано
          </summary>
          <div className="space-y-2 px-3 pb-3 text-muted-foreground">
            {observed && <p className="text-foreground" data-testid="verdict-text">{p.verdict_text}</p>}
            <p>
              Интервалы — {num(lvl, 2)}% ДИ{levelNote}; уровень зависит от выбранной группы, поэтому интервалы для всех параллелей
              и для одной параллели могут различаться.
            </p>
            {p.adjusted && <p>С поправкой: ANCOVA по средним классов (классов = {p.adjusted.n_classes}, df = {p.adjusted.df}, p = {p.adjusted.p_value ?? "—"}).</p>}
            {p.gain && <p>Прирост: критерий Уэлча по средним приростам классов ({p.gain.n_a} и {p.gain.n_b} кл., df = {p.gain.df ?? "—"}).</p>}
            {p.raw && <p>Описательно по ученикам: {signed(p.raw.student_level_diff, " п.п.")}; g Хеджеса = {num(p.raw.hedges_g, 2)}. Вывод по ученикам не делается: учебник назначается классу.</p>}
            <p>Общих итоговых заданий в сравнении: {p.common_items}.</p>
          </div>
        </details>
      </CardContent>
    </Card>
  );
}

function Est({ title, sub, d, lo, hi, extra, highlight, level }: {
  title: string; sub: string; d?: number | null; lo?: number | null; hi?: number | null; extra?: string; highlight?: boolean;
  level?: number;
}) {
  return (
    <div className={highlight ? "rounded-lg border border-primary/25 p-3" : "rounded-lg border p-3"}>
      <div className="text-xs font-medium">{title}</div>
      <div className="text-[11px] text-muted-foreground">{sub}</div>
      <div className="mt-1 text-lg font-semibold tabular-nums">{signed(d ?? null, " п.п.")}</div>
      {level !== undefined && <div className="text-xs text-muted-foreground tabular-nums">{num(level, 2)}% ДИ: {ci(lo, hi)}</div>}
      {extra && <div className="mt-1 text-xs text-muted-foreground">{extra}</div>}
    </div>
  );
}
