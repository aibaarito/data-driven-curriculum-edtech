"use client";

import { Check, CircleAlert, Equal, Loader2, Lock, Play, Save, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useRef, useState } from "react";
import { toast } from "sonner";

import { EvidenceBadge } from "@/components/evidence-passport";
import { RequireData } from "@/components/page-frame";
import { PlanScope } from "@/components/plan-scope";
import { ErrorState, LoadingState } from "@/components/states";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useApi } from "@/hooks/use-api";
import { useScopedRequest } from "@/hooks/use-scoped-request";
import { api, ApiError } from "@/lib/api";
import type { Scenario, ScenarioKey, ScenarioPreview } from "@/lib/decision-types";
import { num, pct, signed } from "@/lib/format";
import type { OptimizerInputs } from "@/lib/types";
import { cn } from "@/lib/utils";

const ORDER: ScenarioKey[] = ["conservative", "balanced", "gap_focused"];

export function ScenariosView() {
  return (
    <RequireData>
      <PlanScope screen="/scenarios" idPrefix="sc">
        {({ subjectId, grade, subjectName }) => (
          <Loader key={`${subjectId}-${grade}`} subjectId={subjectId} grade={grade} subjectName={subjectName} />
        )}
      </PlanScope>
    </RequireData>
  );
}

function Loader({ subjectId, grade, subjectName }: { subjectId: number; grade: number; subjectName: string }) {
  const inputs = useApi<OptimizerInputs>(`/api/optimizer/inputs?subject_id=${subjectId}&grade=${grade}`);
  if (inputs.error) return <ErrorState error={inputs.error} onRetry={inputs.reload} />;
  if (inputs.loading || !inputs.data) return <LoadingState rows={2} />;
  if (inputs.data.topics.length === 0) return <p className="text-sm text-muted-foreground">Для выбранной параллели нет тем.</p>;
  return <Workspace data={inputs.data} subjectId={subjectId} grade={grade} subjectName={subjectName} />;
}

interface Body {
  subject_id: number;
  grade: number;
  total_hours: number;
  target_mastery: number;
  allow_policy_relaxation: boolean;
  topics: { topic_id: number; locked: boolean }[];
}

function newKey(): string {
  const c = globalThis.crypto;
  return c?.randomUUID ? c.randomUUID().replace(/-/g, "") : `${Date.now()}${Math.random().toString(36).slice(2, 12)}`;
}

function Workspace({ data, subjectId, grade, subjectName }: { data: OptimizerInputs; subjectId: number; grade: number; subjectName: string }) {
  const [total, setTotal] = useState(String(data.total_hours));
  const [target, setTarget] = useState(String(data.target_mastery));
  const [relax, setRelax] = useState(false);
  const [locked, setLocked] = useState<Set<number>>(new Set());
  const scopeKey = `${subjectId}-${grade}`;
  const fetcher = useCallback((body: unknown, signal: AbortSignal) =>
    api.post<ScenarioPreview>("/api/optimizer/scenarios/preview", body, undefined, signal), []);
  const req = useScopedRequest<ScenarioPreview>(scopeKey, fetcher);
  const [lastBody, setLastBody] = useState<Body | null>(null);

  const totalNum = Number(total.replace(",", "."));
  const targetNum = Number(target.replace(",", "."));
  const totalOk = Number.isFinite(totalNum) && totalNum > 0 && Math.abs(totalNum * 2 - Math.round(totalNum * 2)) < 1e-9;
  const targetOk = Number.isFinite(targetNum) && targetNum >= 0 && targetNum <= 100;

  const preview = () => {
    if (!totalOk || !targetOk) return;
    const body: Body = {
      subject_id: subjectId, grade, total_hours: totalNum, target_mastery: targetNum, allow_policy_relaxation: relax,
      topics: [...locked].map((id) => ({ topic_id: id, locked: true })),
    };
    setLastBody(body);
    req.run(`«${subjectName}», ${grade} класс, ${num(totalNum)} ч`, body);
  };
  const result = req.result?.scopeKey === scopeKey ? req.result : null;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Параметры</CardTitle>
          <CardDescription>
            Предпросмотр ничего не сохраняет. Все три сценария — реальные расчёты одного оптимизатора с разными
            явными параметрами; жёсткие ограничения (сумма, мин./макс., фиксации, шаг 0,5 ч) соблюдаются всегда.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="sc-total">Бюджет часов</Label>
              <Input id="sc-total" inputMode="decimal" value={total} onChange={(e) => setTotal(e.target.value)} aria-invalid={!totalOk}
                aria-describedby="sc-total-hint" />
              <span id="sc-total-hint" className={cn("text-xs", totalOk ? "text-muted-foreground" : "text-danger")}>
                {totalOk ? `Текущий план: ${num(data.total_hours)} ч` : "Положительное число, кратное 0,5"}
              </span>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="sc-target">Целевое освоение, %</Label>
              <Input id="sc-target" inputMode="decimal" value={target} onChange={(e) => setTarget(e.target.value)} aria-invalid={!targetOk} />
              {!targetOk && <span className="text-xs text-danger">От 0 до 100</span>}
            </div>
            <div className="flex items-center gap-2 pt-6">
              <Checkbox id="sc-relax" checked={relax} onCheckedChange={(v) => setRelax(v === true)} />
              <Label htmlFor="sc-relax" className="text-sm font-normal">Разрешить явное ослабление правил</Label>
            </div>
          </div>
          <fieldset>
            <legend className="mb-2 text-sm font-medium">Зафиксировать темы (часы не меняются)</legend>
            <div className="grid gap-x-4 gap-y-1.5 sm:grid-cols-2 lg:grid-cols-3">
              {data.topics.map((tp) => (
                <label key={tp.topic_id} className="flex items-center gap-2 text-sm">
                  <Checkbox checked={locked.has(tp.topic_id)} aria-label={`Зафиксировать «${tp.name}»`}
                    onCheckedChange={(v) => setLocked((s) => { const n = new Set(s); if (v === true) n.add(tp.topic_id); else n.delete(tp.topic_id); return n; })} />
                  <span className="truncate">{tp.name}</span>
                  <span className="ml-auto text-xs text-muted-foreground tabular-nums">{num(tp.current_hours)} ч</span>
                </label>
              ))}
            </div>
          </fieldset>
          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={preview} disabled={!totalOk || !targetOk || req.pending !== null} data-testid="scenarios-preview">
              {req.pending ? <Loader2 className="size-4 animate-spin" /> : <Play className="size-4" />} Рассчитать сценарии
            </Button>
            {req.pending && <Button variant="ghost" onClick={req.stop}>Остановить</Button>}
          </div>
        </CardContent>
      </Card>
      {req.error && req.error.scopeKey === scopeKey && <ErrorState error={req.error.value} onRetry={preview} />}
      {result && lastBody && <Comparison preview={result.value} body={lastBody} subjectId={subjectId} grade={grade} onRecompute={preview} />}
    </div>
  );
}

function Comparison({ preview, body, subjectId, grade, onRecompute }: {
  preview: ScenarioPreview; body: Body; subjectId: number; grade: number; onRecompute: () => void;
}) {
  const sc = Object.fromEntries(preview.scenarios.map((s) => [s.key, s])) as Record<ScenarioKey, Scenario>;
  return (
    <div className="space-y-6" data-testid="scenario-comparison">
      <p className="text-sm text-muted-foreground" data-testid="scenario-context">
        Отпечаток доказательств {preview.fingerprint.slice(0, 12)}… · предпросмотр не сохранён
        {preview.context.synthetic ? " · СИНТЕТИЧЕСКИЕ данные" : ""}
      </p>
      <div className="grid gap-4 lg:grid-cols-3">
        {ORDER.map((k) => <ScenarioCard key={k} s={sc[k]} body={body} fingerprint={preview.fingerprint} subjectId={subjectId} grade={grade}
          onRecompute={onRecompute} />)}
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Сравнение по темам</CardTitle>
          <CardDescription>Часы в каждом сценарии и отличие от текущего плана. Пусто — сценарий не рассчитан.</CardDescription>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <Table data-testid="scenario-table">
            <TableHeader>
              <TableRow>
                <TableHead>Тема</TableHead>
                <TableHead className="text-right">Освоение</TableHead>
                <TableHead>Доказательства</TableHead>
                <TableHead className="text-right">Текущий</TableHead>
                {ORDER.map((k) => <TableHead key={k} className="text-right">{sc[k].label}</TableHead>)}
              </TableRow>
            </TableHeader>
            <TableBody>
              {preview.comparison.map((r) => (
                <TableRow key={r.topic_id}>
                  <TableCell className="font-medium">
                    {r.name}
                    {r.locked && <Lock className="ml-1 inline size-3 text-muted-foreground" aria-label="зафиксирована" />}
                    {preview.graph.foundational_gaps.includes(r.topic_id) && (
                      <Badge variant="outline" className="ml-2 border-danger/30 text-danger">слабый пререквизит</Badge>)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{pct(r.mastery)}</TableCell>
                  <TableCell><EvidenceBadge category={r.evidence} /></TableCell>
                  <TableCell className="text-right tabular-nums">{num(r.current_hours)}</TableCell>
                  {ORDER.map((k) => {
                    const v = r.scenarios[k];
                    return (
                      <TableCell key={k} className="text-right tabular-nums">
                        {v ? <>{num(v.proposed)} <span className={cn("text-xs", v.delta > 0 ? "text-emerald-700" : v.delta < 0 ? "text-danger" : "text-muted-foreground")}>
                          ({v.delta === 0 ? "0" : signed(v.delta)})</span></> : "—"}
                      </TableCell>
                    );
                  })}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

function ScenarioCard({ s, body, fingerprint, subjectId, grade, onRecompute }: {
  s: Scenario; body: Body; fingerprint: string; subjectId: number; grade: number; onRecompute: () => void;
}) {
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<number | null>(null);
  const [err, setErr] = useState<ApiError | null>(null);
  // One idempotency key per save intent: a retry after a network error reuses it and cannot create a duplicate.
  const key = useRef<string | null>(null);
  const save = async () => {
    setSaving(true);
    setErr(null);
    key.current ??= newKey();
    try {
      const r = await api.post<{ run_id: number; idempotent_replay: boolean }>("/api/optimizer/scenarios/save",
        { ...body, scenario_key: s.key, fingerprint, idempotency_key: key.current });
      setSaved(r.run_id);
      toast.success(`Сценарий «${s.label}» сохранён как рекомендация №${r.run_id} (ожидает решения методиста).`);
    } catch (e) {
      const ae = e instanceof ApiError ? e : new ApiError("Ошибка.", 0);
      setErr(ae);
      if (ae.status !== 0) key.current = null; // definitive answer from the server: a new attempt is a new intent
    } finally {
      setSaving(false);
    }
  };
  return (
    <Card className={cn(!s.ok && "border-danger/30")} data-testid={`scenario-${s.key}`}>
      <CardHeader>
        <CardTitle className="text-base">{s.label}</CardTitle>
        <CardAction>{s.ok ? <Badge variant="outline" className="border-success/30 text-emerald-700"><Check className="size-3" />рассчитан</Badge>
          : <Badge variant="outline" className="border-danger/30 text-danger"><X className="size-3" />{s.error?.code}</Badge>}</CardAction>
        <CardDescription>{s.goal}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p className="text-xs text-muted-foreground">
          Лимит изменения темы: ±{num(s.parameters.max_change_pct)}%
          {s.parameters.held_for_evidence.length > 0 && <> · часы сохранены (данные не «достаточны»): {s.parameters.held_for_evidence.join(", ")}</>}
          {Object.keys(s.parameters.need_weights).length > 0 && <> · вес потребности: {Object.entries(s.parameters.need_weights).map(([n, w]) => `${n} ×${num(w, 2)}`).join(", ")}</>}
        </p>
        {s.ok && s.result && s.diff ? (
          <>
            <dl className="grid grid-cols-3 gap-2 text-center">
              <div className="rounded-lg bg-muted/60 p-2"><dt className="text-xs text-muted-foreground">Итого</dt><dd className="font-semibold tabular-nums">{num(s.result.proposed_total)} ч</dd></div>
              <div className="rounded-lg bg-muted/60 p-2"><dt className="text-xs text-muted-foreground">Изменено тем</dt><dd className="font-semibold tabular-nums">{s.diff.changed_topics}</dd></div>
              <div className="rounded-lg bg-muted/60 p-2"><dt className="text-xs text-muted-foreground">Перенесено</dt><dd className="font-semibold tabular-nums">{num(s.diff.hours_moved)} ч</dd></div>
            </dl>
            <ul className="space-y-0.5" aria-label="Жёсткие ограничения">
              {s.result.constraints.map((c) => (
                <li key={c.name} className="flex items-start gap-1.5">
                  {c.ok ? <Check className="mt-0.5 size-3.5 text-emerald-600" aria-label="выполнено" /> : <X className="mt-0.5 size-3.5 text-danger" aria-label="нарушено" />}
                  <span>{c.name}</span>
                </li>
              ))}
            </ul>
            {s.result.relaxed_policies.length > 0 && (
              <Alert className="border-warning/40"><CircleAlert className="size-4" /><AlertTitle>Ослаблены правила</AlertTitle>
                <AlertDescription>{s.result.policy_checks.filter((p) => p.status === "relaxed").map((p) => `${p.name}${p.affected_topics.length ? `: ${p.affected_topics.join(", ")}` : ""}`).join("; ")}</AlertDescription></Alert>
            )}
            {s.identical_to.length > 0 && (
              <p className="flex items-start gap-1.5 rounded-lg border border-dashed p-2 text-xs" data-testid="identical-note"><Equal className="mt-0.5 size-3.5 shrink-0" aria-hidden />{s.identical_note}</p>
            )}
            <details className="text-xs text-muted-foreground">
              <summary className="cursor-pointer">Предупреждения ({s.result.warnings.length})</summary>
              <ul className="mt-1 list-disc pl-5">{s.result.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
            </details>
            {saved ? (
              <p className="text-sm" data-testid={`saved-${s.key}`}>Сохранено: рекомендация №{saved}. <Link className="underline" href={`/decisions?subject_id=${subjectId}&grade=${grade}`}>Перейти к решению</Link></p>
            ) : (
              <Button variant="outline" onClick={save} disabled={saving} className="w-full" data-testid={`save-${s.key}`}>
                {saving ? <Loader2 className="size-4 animate-spin" /> : <Save className="size-4" />} Выбрать для утверждения
              </Button>
            )}
            {err && (
              <div role="alert" className="text-sm text-danger">
                {err.message}
                {err.code === "STALE_SCENARIO" && <Button variant="link" className="h-auto p-0 pl-1" onClick={onRecompute}>Пересчитать</Button>}
              </div>
            )}
          </>
        ) : (
          <div role="alert" className="space-y-1">
            <p className="font-medium text-danger">{s.error?.message}</p>
            <ul className="list-disc pl-5 text-xs text-muted-foreground">{s.error?.details.map((d) => <li key={d}>{d}</li>)}</ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
