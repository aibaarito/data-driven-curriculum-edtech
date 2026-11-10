"use client";

import { Bot, Cpu, Loader2, ShieldCheck, Sparkles } from "lucide-react";
import { useState } from "react";

import { FilterBar, useFilters } from "@/components/filter-bar";
import { RequireData } from "@/components/page-frame";
import { ErrorState } from "@/components/states";
import { KindTag } from "@/components/ui-bits";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, ApiError } from "@/lib/api";
import type { InsightsResponse } from "@/lib/types";

export function InsightsView() {
  return (
    <RequireData>
      <FilterBar />
      <Content />
    </RequireData>
  );
}

function Content() {
  const [f] = useFilters();
  const [data, setData] = useState<InsightsResponse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(false);

  async function generate() {
    setLoading(true);
    setError(null);
    try {
      setData(await api.post<InsightsResponse>("/api/ai/insights", f));
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError("Ошибка.", 0));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Sparkles className="size-4 text-primary" /> Пояснения к результатам</CardTitle>
          <CardDescription>
            Все числа рассчитывает сервер. Языковая модель (если подключена) получает только агрегированные проверенные
            метрики без идентификаторов учеников, а каждый её ответ проверяется: неизвестные метрики, отсутствующие в данных
            числа и причинные формулировки отклоняются. Без ключа API используется детерминированный режим.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button onClick={generate} disabled={loading} data-testid="generate-insights">
            {loading ? <Loader2 className="size-4 animate-spin" /> : <Sparkles className="size-4" />}
            {data ? "Обновить пояснения" : "Сформировать пояснения"}
          </Button>
        </CardContent>
      </Card>

      {error && <ErrorState error={error} onRetry={generate} />}
      {loading && !data && <div className="space-y-3"><Skeleton className="h-24" /><Skeleton className="h-40" /></div>}

      {data && (
        <div className="space-y-6" data-testid="insights-result">
          <Alert className={data.mode === "llm" ? "border-primary/30" : "border-warning/50 bg-warning/5"}>
            {data.mode === "llm" ? <Bot className="size-4" /> : <Cpu className="size-4" />}
            <AlertTitle className="flex flex-wrap items-center gap-2">
              Режим: {data.mode === "llm" ? `языковая модель (${data.model})` : "детерминированный (без ИИ)"}
              <Badge variant="outline" className="gap-1" data-testid="insights-mode"><ShieldCheck className="size-3" /> числа проверены</Badge>
            </AlertTitle>
            <AlertDescription>
              {data.mode === "llm"
                ? `Ответ прошёл проверку схемы и соответствия метрикам (попыток: ${data.attempts}).`
                : data.fallback_reason ?? "Тексты сформированы по шаблонам из проверенных метрик."}
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
                    <div className="rounded-md bg-muted/60 p-2">
                      <div className="mb-1 text-xs font-medium text-muted-foreground">Опирается на метрики</div>
                      <ul className="space-y-0.5 font-mono text-[11px]">
                        {fd.metric_keys.map((k) => <li key={k}>{k} = {String(data.facts[k] ?? "—")}</li>)}
                      </ul>
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
      )}
    </div>
  );
}
