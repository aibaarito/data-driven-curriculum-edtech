"use client";

import { Bot, Cpu, History, Loader2, ShieldCheck, Sparkles, Square, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { FilterBar, useFilters } from "@/components/filter-bar";
import { useMeta } from "@/components/meta-provider";
import { RequireData } from "@/components/page-frame";
import { ErrorState } from "@/components/states";
import { KindTag } from "@/components/ui-bits";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useScopedRequest } from "@/hooks/use-scoped-request";
import { api } from "@/lib/api";
import { factLabel } from "@/lib/facts";
import { toQuery } from "@/lib/filters";
import { scopeLabel } from "@/lib/scope";
import type { InsightsResponse } from "@/lib/types";
import { cn } from "@/lib/utils";

export function InsightsView() {
  return (
    <RequireData>
      <FilterBar />
      <Content />
    </RequireData>
  );
}

const fetchInsights = (body: unknown, signal: AbortSignal) =>
  api.post<InsightsResponse>("/api/ai/insights", body, undefined, signal);

/** Seconds since `startedAt`, ticking while active. Real elapsed time only — no estimate or progress percentage. */
function useElapsed(startedAt: number | null): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (startedAt === null) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [startedAt]);
  return startedAt === null ? 0 : Math.max(0, Math.floor((now - startedAt) / 1000));
}

export function modeView(data: InsightsResponse): { title: string; text: string; tone: "ok" | "template" | "warn" } {
  const local = data.provider === "ollama";
  if (data.mode === "llm") {
    return {
      title: local
        ? `Пояснения написала локальная модель ${data.model ?? ""} (Ollama, на этом компьютере)`
        : `Пояснения написала языковая модель (${data.model ?? "модель"})`,
      tone: "ok",
      text: `Ответ прошёл проверку структуры и сверку чисел с расчётами (попыток: ${data.attempts}).`,
    };
  }
  const reason = (fallback: string) => data.fallback_reason ?? fallback;
  const service = local ? "Локальная модель" : "Модель";
  switch (data.fallback_kind) {
    case "rejected":
      return { title: "Ответ модели отклонён — показаны пояснения по шаблонам", tone: "warn",
        text: reason("Ответ модели не прошёл проверку. Пояснения сформированы по шаблонам; расчёты сохранены.") };
    case "unavailable":
      return { title: `${service} недоступна — показаны пояснения по шаблонам`, tone: "warn",
        text: reason("Сервис модели не отвечает. Пояснения сформированы по шаблонам; расчёты сохранены.") };
    case "model_missing":
      return { title: "Модель не установлена — показаны пояснения по шаблонам", tone: "warn",
        text: reason("Модель не найдена в локальном сервисе. Пояснения сформированы по шаблонам; расчёты сохранены.") };
    case "timeout":
      return { title: "Модель не ответила вовремя — показаны пояснения по шаблонам", tone: "warn",
        text: reason("Время ожидания ответа истекло. Пояснения сформированы по шаблонам; расчёты сохранены.") };
    case "busy":
      return { title: "Модель занята — показаны пояснения по шаблонам", tone: "warn",
        text: reason("Модель обрабатывает другой запрос. Пояснения сформированы по шаблонам; расчёты сохранены.") };
    case "too_large":
      return { title: "Слишком много фактов для модели — показаны пояснения по шаблонам", tone: "warn",
        text: reason("Набор фактов превышает лимит модели. Пояснения сформированы по шаблонам; расчёты сохранены.") };
    case "provider_error":
      return { title: "Модель недоступна — показаны пояснения по шаблонам", tone: "warn",
        text: reason("Сервис модели не ответил. Пояснения сформированы по шаблонам; расчёты сохранены.") };
    default:
      return { title: "Пояснения по шаблонам (без языковой модели)", tone: "template",
        text: "Пояснения сформированы по шаблонам без языковой модели. Числа взяты из расчётов для указанной группы." };
  }
}

function Content() {
  const [f] = useFilters();
  const { data: meta } = useMeta();
  const scopeKey = toQuery(f);
  const currentLabel = scopeLabel(f, meta, "/insights");
  const req = useScopedRequest<InsightsResponse>(scopeKey, fetchInsights);
  const elapsed = useElapsed(req.pending?.startedAt ?? null);
  const generate = useCallback(() => req.run(currentLabel, f), [req, currentLabel, f]);

  const result = req.result;
  const stale = result !== null && result.scopeKey !== scopeKey;
  const loading = req.pending !== null;
  const errorForCurrent = req.error && req.error.scopeKey === scopeKey ? req.error : null;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Sparkles className="size-4 text-primary" aria-hidden /> Пояснения к результатам</CardTitle>
          <CardDescription>
            Все числа рассчитывает сервер. Языковая модель (если подключена) получает только агрегированные метрики без
            идентификаторов учеников; её ответ проверяется по структуре и числам, иначе показываются пояснения по шаблонам.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm">
            <span className="text-muted-foreground">Будут сформированы для: </span>
            <span className="font-medium" data-testid="insights-request-scope">{currentLabel}</span>
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={generate} disabled={loading} data-testid="generate-insights">
              {loading ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Sparkles className="size-4" aria-hidden />}
              {result && !stale ? "Обновить пояснения" : "Сформировать пояснения"}
            </Button>
            {loading && (
              <Button variant="outline" onClick={req.stop} data-testid="stop-waiting">
                <Square className="size-3.5" aria-hidden /> Прекратить ожидание
              </Button>
            )}
          </div>
          <div role="status" aria-live="polite" className="text-sm" data-testid="insights-status">
            {loading && req.pending && (
              <div className="rounded-md bg-muted/60 p-2.5">
                <p>Готовим пояснения для выбранной группы: {req.pending.scopeLabel}…</p>
                <p className="text-xs text-muted-foreground">
                  Прошло {elapsed} с. Ответ языковой модели может занять десятки секунд (локальной модели при первом запуске — дольше); если она
                  недоступна или не ответит вовремя, сервер вернёт пояснения по шаблонам.{result ? " Предыдущий результат ниже остаётся видимым до получения нового." : ""}
                </p>
              </div>
            )}
            {!loading && req.interrupted && (
              <p className="rounded-md bg-muted/60 p-2.5 text-muted-foreground" data-testid="insights-interrupted">
                {req.interrupted.reason === "scope"
                  ? `Фильтры изменены — ожидание пояснений для «${req.interrupted.scopeLabel}» прекращено, ответ не будет показан.`
                  : `Ожидание прекращено. Обработка на сервере могла продолжиться, но её результат не будет показан.`}
              </p>
            )}
          </div>
        </CardContent>
      </Card>

      {errorForCurrent && (
        <div>
          <p className="mb-2 text-sm text-muted-foreground">Запрос для: {errorForCurrent.scopeLabel}</p>
          <ErrorState error={errorForCurrent.value} onRetry={generate} />
        </div>
      )}
      {loading && !result && <div className="space-y-3" aria-hidden><Skeleton className="h-24" /><Skeleton className="h-40" /></div>}

      {result && (
        <ResultView data={result.value} label={result.scopeLabel} query={result.scopeKey} stale={stale}
          refreshing={loading} onRefresh={generate} />
      )}
    </div>
  );
}

function ResultView({ data, label, query, stale, refreshing, onRefresh }: {
  data: InsightsResponse; label: string; query: string; stale: boolean; refreshing: boolean; onRefresh: () => void;
}) {
  const mode = modeView(data);
  return (
    <div className="space-y-6" data-testid="insights-result" data-scope={query} aria-busy={refreshing}>
      <div className={cn("rounded-lg border p-3", stale ? "border-warning/50 bg-warning/10" : "bg-card")}>
        <p className="text-sm">
          <span className="text-muted-foreground">Пояснения для: </span>
          <span className="font-semibold" data-testid="insights-result-scope">{label}</span>
        </p>
        {stale && (
          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm" role="alert" data-testid="insights-stale">
            <TriangleAlert className="size-4 text-amber-700" aria-hidden />
            Фильтры изменены. Эти пояснения относятся к прежней группе. Обновите пояснения для выбранной группы.
            <Button size="sm" variant="outline" onClick={onRefresh} disabled={refreshing}>Обновить для выбранной группы</Button>
          </div>
        )}
        {refreshing && !stale && (
          <p className="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground"><History className="size-3.5" aria-hidden />
            Показан предыдущий результат; новый формируется.</p>
        )}
      </div>

      <div className={cn("space-y-6", stale && "opacity-60")}>
        <Alert className={mode.tone === "ok" ? "border-primary/30" : mode.tone === "warn" ? "border-warning/60 bg-warning/10" : "border-border bg-muted/40"}>
          {data.mode === "llm" ? <Bot className="size-4" aria-hidden /> : <Cpu className="size-4" aria-hidden />}
          <AlertTitle className="flex flex-wrap items-center gap-2" data-testid="insights-mode-title">
            {mode.title}
            <Badge variant="outline" className="gap-1" data-testid="insights-mode"><ShieldCheck className="size-3" aria-hidden /> Числа сверены с расчётами</Badge>
          </AlertTitle>
          <AlertDescription>
            <p>{mode.text}</p>
            <p className="text-xs">Сверка проверяет числа и их привязку к темам; она не подтверждает причинные выводы и не гарантирует
              корректность каждого утверждения.</p>
            {(data.fallback_detail || data.attempts > 0) && (
              <details className="mt-1 text-xs">
                <summary className="cursor-pointer outline-none focus-visible:ring-2 focus-visible:ring-ring">Технические сведения</summary>
                <p>Режим: {data.mode}{data.provider ? `; провайдер: ${data.provider}` : ""}; обращений к модели: {data.attempts}
                  {data.fallback_kind ? `; причина: ${data.fallback_kind}` : ""}{data.fallback_detail ? ` (${data.fallback_detail})` : ""}.</p>
              </details>
            )}
          </AlertDescription>
        </Alert>

        <Card>
          <CardHeader><CardTitle>Резюме</CardTitle></CardHeader>
          <CardContent><p className="leading-relaxed">{data.payload.summary}</p></CardContent>
        </Card>

        <div className="grid gap-4 md:grid-cols-2">
          {data.payload.findings.map((fd, i) => (
            <Card key={i}>
              <CardHeader>
                <div className="mb-1"><KindTag kind={fd.kind} /></div>
                <CardTitle className="text-base">{fd.title}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                <p className="leading-relaxed">{fd.text}</p>
                {fd.metric_keys.length > 0 && (
                  <div className="rounded-md bg-muted/60 p-2.5" data-testid="finding-facts">
                    <div className="mb-1 text-xs font-medium text-muted-foreground">Опирается на расчёты (группа: {label})</div>
                    <ul className="space-y-1 text-xs">
                      {fd.metric_keys.map((k) => {
                        const fl = factLabel(k, data.facts, query);
                        return (
                          <li key={k} className="flex flex-wrap justify-between gap-x-3">
                            <span>{fl.href ? <Link href={fl.href} className="underline-offset-2 hover:underline">{fl.label}</Link> : fl.label}</span>
                            <b className="tabular-nums">{fl.value}</b>
                          </li>
                        );
                      })}
                    </ul>
                    <details className="mt-1 text-[11px] text-muted-foreground">
                      <summary className="cursor-pointer outline-none focus-visible:ring-2 focus-visible:ring-ring">Ключи метрик</summary>
                      <ul className="font-mono">{fd.metric_keys.map((k) => <li key={k}>{k} = {String(data.facts[k] ?? "—")}</li>)}</ul>
                    </details>
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>

        <div className="grid gap-6 md:grid-cols-2">
          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2">Ограничения данных <KindTag kind="limitation" /></CardTitle></CardHeader>
            <CardContent><ul className="list-disc space-y-1 pl-5 text-sm">{data.payload.limitations.map((l) => <li key={l}>{l}</li>)}</ul></CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2">Следующие шаги <KindTag kind="recommendation" /></CardTitle></CardHeader>
            <CardContent><ul className="list-disc space-y-1 pl-5 text-sm">{data.payload.next_steps.map((l) => <li key={l}>{l}</li>)}</ul></CardContent>
          </Card>
        </div>
        {data.optimizer_status === null && (
          <p className="text-sm text-muted-foreground">Совет: сформируйте рекомендацию в оптимизаторе часов (выберите предмет и параллель), чтобы пояснения включали её.</p>
        )}
      </div>
    </div>
  );
}
