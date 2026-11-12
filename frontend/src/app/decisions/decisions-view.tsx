"use client";

import { ArrowRight, CheckCircle2, ClipboardCheck, GitBranch, Layers, Loader2, ThumbsDown, ThumbsUp } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { EvidenceBadge, TopicPassportButton } from "@/components/evidence-passport";
import { RequireData } from "@/components/page-frame";
import { PlanScope } from "@/components/plan-scope";
import { ErrorState, LoadingState } from "@/components/states";
import { KindTag, StatusBadge } from "@/components/ui-bits";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useApi } from "@/hooks/use-api";
import { api, ApiError } from "@/lib/api";
import type { DecisionCandidate, DecisionOverview, EvidenceCategory, Intervention, RunSummary } from "@/lib/decision-types";
import { ci, date, dateTime, int, num, pct, signed } from "@/lib/format";
import { cn } from "@/lib/utils";

const SCENARIO_RU: Record<string, string> = { conservative: "Консервативный", balanced: "Сбалансированный", gap_focused: "Фокус на пробелах" };
const RUN_RU = { proposed: "Ожидает решения", accepted: "Принята", rejected: "Отклонена" } as const;
const READINESS_ORDER: EvidenceCategory[] = ["supported", "exploratory", "insufficient", "incomparable", "stale"];

export function DecisionsView() {
  return (
    <RequireData>
      <PlanScope screen="/decisions" idPrefix="dc">
        {({ subjectId, grade }) => <Center key={`${subjectId}-${grade}`} subjectId={subjectId} grade={grade} />}
      </PlanScope>
    </RequireData>
  );
}

function Center({ subjectId, grade }: { subjectId: number; grade: number }) {
  const s = useApi<DecisionOverview>(`/api/decisions/overview?subject_id=${subjectId}&grade=${grade}`);
  if (s.error) return <ErrorState error={s.error} onRetry={s.reload} />;
  if (s.loading && !s.data) return <LoadingState rows={3} />;
  if (!s.data) return null;
  const d = s.data;
  const q = `?subject_id=${subjectId}&grade=${grade}`;
  const topicCands = d.candidates.filter((c) => c.kind === "topic");
  const otherCands = d.candidates.filter((c) => c.kind !== "topic");
  return (
    <div className="space-y-6" aria-busy={s.loading}>
      <section aria-label="Контекст доказательств" className="flex flex-wrap items-center gap-2 text-sm">
        {READINESS_ORDER.filter((k) => d.readiness[k] > 0).map((k) => (
          <span key={k} className="flex items-center gap-1"><EvidenceBadge category={k} /><span className="tabular-nums">{d.readiness[k]} тем</span></span>
        ))}
        <span className="text-xs text-muted-foreground" data-testid="dc-fingerprint">
          Отпечаток {d.context.fingerprint.slice(0, 12)}… · {int(d.context.revision.results)} результатов · алгоритм {d.context.algorithm_version}
          {d.context.synthetic && " · СИНТЕТИЧЕСКИЕ данные"}
        </span>
      </section>

      <div className="grid gap-4 md:grid-cols-3">
        <WorkflowCard icon={GitBranch} title="Зависимости" href={`/curriculum${q}`} cta="Карта программы">
          {d.graph.foundational_gaps.length ? <>Слабые пререквизиты слабых тем: {d.graph.foundational_gaps.map((x) => `«${x.name}»`).join(", ")}.</>
            : "Слабых пререквизитов со слабыми зависимыми темами нет."}
        </WorkflowCard>
        <WorkflowCard icon={Layers} title="Сценарии плана" href={`/scenarios${q}`} cta="Сравнить сценарии">
          {d.plan.available ? <>Текущий план {num(d.plan.total_hours)} ч. Три варианта распределения при одном бюджете.</> : "План часов недоступен для среза."}
        </WorkflowCard>
        <WorkflowCard icon={ClipboardCheck} title="Решения" href="#approvals" cta="К утверждению">
          Ожидают решения: {d.pending_approvals.length}; принято: {d.approved.length}; вмешательств: {d.interventions.length}.
        </WorkflowCard>
      </div>

      <section aria-labelledby="dc-issues" className="space-y-3">
        <div className="flex items-baseline justify-between gap-2">
          <h2 id="dc-issues" className="text-lg font-semibold">Требуют внимания</h2>
          <span className="text-sm text-muted-foreground">Действие допускается: {d.actionable} из {d.candidates.length}</span>
        </div>
        {d.candidates.length === 0 && <p className="text-sm text-muted-foreground" data-testid="no-issues">Проблем по правилам не найдено.</p>}
        <div className="grid gap-4 xl:grid-cols-2">
          {topicCands.map((c) => <CandidateCard key={c.id} c={c} query={q} />)}
        </div>
        {otherCands.map((c) => <CandidateCard key={c.id} c={c} query={q} />)}
      </section>

      <Approvals d={d} reload={s.reload} />
      <Interventions d={d} reload={s.reload} />
    </div>
  );
}

function WorkflowCard({ icon: Icon, title, href, cta, children }: {
  icon: typeof GitBranch; title: string; href: string; cta: string; children: React.ReactNode;
}) {
  return (
    <Card className="gap-3 py-4">
      <CardHeader className="px-4"><CardTitle className="flex items-center gap-2 text-base"><Icon className="size-4" aria-hidden />{title}</CardTitle></CardHeader>
      <CardContent className="space-y-2 px-4 text-sm">
        <p className="text-muted-foreground">{children}</p>
        <Button asChild variant="outline" size="sm"><Link href={href}>{cta} <ArrowRight className="size-3.5" /></Link></Button>
      </CardContent>
    </Card>
  );
}

function CandidateCard({ c, query }: { c: DecisionCandidate; query: string }) {
  const impact = c.constraint_impact;
  return (
    <Card data-testid={`candidate-${c.topic_code ?? c.id}`} className={cn(!c.evidence.allows_action && "border-dashed")}>
      <CardHeader>
        <CardTitle className="text-base">{c.topic_name ?? c.title}</CardTitle>
        <CardAction className="flex flex-col items-end gap-1">
          {c.status && <StatusBadge status={c.status} />}
          <EvidenceBadge category={c.evidence.category} />
        </CardAction>
        <CardDescription>{c.problem.label}{c.priority.score > 0 && <> · приоритет {num(c.priority.score)}</>}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <div className="rounded-lg border bg-muted/40 p-3">
          <div className="mb-1 flex flex-wrap items-center gap-2"><KindTag kind="recommendation" /><span className="font-medium" data-testid="candidate-action">{c.action.label}</span></div>
          {c.secondary_actions.length > 0 && <p className="text-muted-foreground">Дополнительно: {c.secondary_actions.map((a) => a.label.toLowerCase()).join("; ")}.</p>}
          <p className="text-xs text-muted-foreground">Проверка: {c.required_review}</p>
        </div>
        <ul className="space-y-1">
          {c.observations.map((o) => <li key={o} className="flex gap-2"><KindTag kind="observation" /><span>{o}</span></li>)}
        </ul>
        {c.interpretation && <p className="text-muted-foreground">{c.interpretation}</p>}
        {c.hypothesis && <p className="flex gap-2 text-muted-foreground"><KindTag kind="prediction" /><span>{c.hypothesis}</span></p>}
        {impact && impact.balanced_delta !== null && (
          <p className="text-xs" data-testid="candidate-impact">
            Сбалансированный план: {num(impact.current_hours)} → {num(impact.balanced_proposed)} ч ({impact.balanced_delta === 0 ? "без изменений" : signed(impact.balanced_delta, " ч")}).
            {impact.sensitivity && <> Если бюджет −2 ч: {fmtDelta(impact.sensitivity.minus_2h)}; +2 ч: {fmtDelta(impact.sensitivity.plus_2h)}.</>}
          </p>
        )}
        <details className="text-xs">
          <summary className="cursor-pointer text-muted-foreground">Почему не другие действия и ограничения</summary>
          <ul className="mt-1 list-disc space-y-0.5 pl-5">
            {c.rejected_alternatives.map((r) => <li key={r.code}><span className="font-medium">{r.label}:</span> {r.reason}</li>)}
            {c.limitations.map((l) => <li key={l} className="text-muted-foreground">{l}</li>)}
            {!c.evidence.allows_action && c.evidence.reasons.map((r) => <li key={r}>{r}</li>)}
          </ul>
        </details>
        {c.kind === "topic" && c.topic_id && <TopicPassportButton topicId={c.topic_id} topicName={c.topic_name ?? ""} query={query} />}
      </CardContent>
    </Card>
  );
}

function fmtDelta(v: number | null): string {
  if (v === null) return "план недопустим по правилам";
  return v === 0 ? "без изменений" : signed(v, " ч");
}

function Approvals({ d, reload }: { d: DecisionOverview; reload: () => void }) {
  const runs = [...d.pending_approvals, ...d.approved, ...d.rejected].sort((a, b) => b.run_id - a.run_id);
  return (
    <section id="approvals" aria-labelledby="dc-approvals" className="space-y-3 scroll-mt-20">
      <h2 id="dc-approvals" className="text-lg font-semibold">Рекомендации по плану часов</h2>
      {runs.length === 0 ? (
        <p className="text-sm text-muted-foreground">Сохранённых рекомендаций нет. Выберите сценарий на странице «Сценарии плана».</p>
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">{runs.map((r) => <RunCard key={r.run_id} r={r} reload={reload} />)}</div>
      )}
    </section>
  );
}

function RunCard({ r, reload }: { r: RunSummary; reload: () => void }) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [staleAsk, setStaleAsk] = useState(false);
  const decide = async (decision: "accept" | "reject", acknowledge = false) => {
    setBusy(true);
    try {
      await api.post(`/api/optimizer/runs/${r.run_id}/decision`, { decision, note: note || null, acknowledge_stale: acknowledge });
      toast.success(decision === "accept" ? "Рекомендация принята." : "Рекомендация отклонена.");
      reload();
    } catch (e) {
      if (e instanceof ApiError && e.code === "STALE_RECOMMENDATION") setStaleAsk(true);
      else toast.error(e instanceof ApiError ? e.message : "Ошибка.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card data-testid={`run-${r.run_id}`}>
      <CardHeader>
        <CardTitle className="text-base">№{r.run_id} · {r.scenario_key ? SCENARIO_RU[r.scenario_key] ?? r.scenario_key : "план"} · {num(r.total_hours)} ч</CardTitle>
        <CardAction className="flex flex-col items-end gap-1">
          <Badge variant="outline">{RUN_RU[r.status]}</Badge>
          {r.evidence_status === "stale" && <EvidenceBadge category="stale" />}
        </CardAction>
        <CardDescription>{dateTime(r.created_at)} · изменено тем: {r.changed_topics}{r.review_note && <> · «{r.review_note}»</>}</CardDescription>
      </CardHeader>
      {r.status === "proposed" && (
        <CardContent className="space-y-2">
          <Label htmlFor={`note-${r.run_id}`} className="text-xs text-muted-foreground">Комментарий проверяющего (необязательно)</Label>
          <Input id={`note-${r.run_id}`} value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} />
          {staleAsk && (
            <Alert className="border-warning/40" data-testid="stale-ack">
              <AlertTitle>Данные изменились после расчёта</AlertTitle>
              <AlertDescription className="space-y-2">
                <p>Лучше пересчитать сценарии. Можно принять и по сохранённому снимку доказательств — это будет записано в журнал.</p>
                <Button size="sm" variant="outline" onClick={() => decide("accept", true)} disabled={busy}>Принять по снимку</Button>
              </AlertDescription>
            </Alert>
          )}
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={() => decide("accept")} disabled={busy} data-testid={`accept-${r.run_id}`}>
              {busy ? <Loader2 className="size-4 animate-spin" /> : <ThumbsUp className="size-4" />} Утвердить
            </Button>
            <Button size="sm" variant="outline" onClick={() => decide("reject")} disabled={busy} data-testid={`reject-${r.run_id}`}>
              <ThumbsDown className="size-4" /> Отклонить
            </Button>
          </div>
        </CardContent>
      )}
    </Card>
  );
}

function Interventions({ d, reload }: { d: DecisionOverview; reload: () => void }) {
  const withIv = new Set(d.interventions.map((x) => x.run_id));
  const open = d.approved.filter((r) => !withIv.has(r.run_id));
  return (
    <section aria-labelledby="dc-interventions" className="space-y-3">
      <h2 id="dc-interventions" className="text-lg font-semibold">Вмешательства и результаты</h2>
      <p className="text-sm text-muted-foreground">
        Путь: запланировано → внедрено → ожидает данных → оценено. Оценка «до/после» без группы сравнения описывает
        наблюдаемое изменение и не доказывает эффект вмешательства.
      </p>
      {open.map((r) => <PlanForm key={r.run_id} run={r} reload={reload} />)}
      {d.interventions.length === 0 && open.length === 0 && <p className="text-sm text-muted-foreground">Вмешательств пока нет — сначала утвердите рекомендацию.</p>}
      {d.interventions.map((x) => <InterventionCard key={x.id} x={x} reload={reload} />)}
    </section>
  );
}

function PlanForm({ run, reload }: { run: RunSummary; reload: () => void }) {
  const [desc, setDesc] = useState(`Внедрить план часов №${run.run_id}`);
  const [planned, setPlanned] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    try {
      await api.post("/api/interventions", { run_id: run.run_id, description: desc, planned_on: planned || null });
      toast.success("Вмешательство запланировано; базовые доказательства зафиксированы.");
      reload();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Ошибка.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card data-testid={`plan-form-${run.run_id}`}>
      <CardHeader><CardTitle className="text-base">Запланировать внедрение рекомендации №{run.run_id}</CardTitle></CardHeader>
      <CardContent className="grid gap-3 sm:grid-cols-[1fr_12rem_auto] sm:items-end">
        <div className="flex flex-col gap-1.5"><Label htmlFor={`iv-desc-${run.run_id}`}>Описание</Label>
          <Input id={`iv-desc-${run.run_id}`} value={desc} onChange={(e) => setDesc(e.target.value)} maxLength={2000} /></div>
        <div className="flex flex-col gap-1.5"><Label htmlFor={`iv-date-${run.run_id}`}>Плановая дата</Label>
          <Input id={`iv-date-${run.run_id}`} type="date" value={planned} onChange={(e) => setPlanned(e.target.value)} /></div>
        <Button onClick={submit} disabled={busy || desc.trim().length < 3} data-testid={`plan-${run.run_id}`}>Запланировать</Button>
      </CardContent>
    </Card>
  );
}

const STEPS: Intervention["status"][] = ["planned", "implemented", "awaiting_outcome", "evaluated"];
const STEP_RU: Record<string, string> = { planned: "Запланировано", implemented: "Внедрено", awaiting_outcome: "Ожидает данных", evaluated: "Оценено", cancelled: "Отменено" };

function InterventionCard({ x, reload }: { x: Intervention; reload: () => void }) {
  const [busy, setBusy] = useState(false);
  const [impl, setImpl] = useState("");
  const call = async (path: string, body?: unknown) => {
    setBusy(true);
    try {
      await api.post(path, body);
      reload();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Ошибка.");
    } finally {
      setBusy(false);
    }
  };
  const base = `/api/interventions/${x.id}`;
  const idx = STEPS.indexOf(x.status);
  return (
    <Card data-testid={`intervention-${x.id}`}>
      <CardHeader>
        <CardTitle className="text-base">{x.description}</CardTitle>
        <CardAction className="flex flex-col items-end gap-1">
          <Badge variant="outline" data-testid="iv-status">{x.status_label}</Badge>
          {x.synthetic && <Badge variant="outline" className="border-warning/50 text-amber-800">синтетические данные</Badge>}
        </CardAction>
        <CardDescription>Рекомендация №{x.run_id}{x.planned_on && <> · план {date(x.planned_on)}</>}{x.implemented_on && <> · внедрено {date(x.implemented_on)}</>}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        <ol className="flex flex-wrap items-center gap-1 text-xs" aria-label="Этапы">
          {STEPS.map((s, i) => (
            <li key={s} className={cn("flex items-center gap-1 rounded-full border px-2 py-0.5", x.status === "cancelled" ? "opacity-50" :
              i < idx ? "border-success/40 text-emerald-700" : i === idx ? "border-primary bg-accent font-medium" : "text-muted-foreground")}
              aria-current={i === idx ? "step" : undefined}>
              {i < idx && x.status !== "cancelled" && <CheckCircle2 className="size-3" aria-hidden />}{STEP_RU[s]}
            </li>
          ))}
          {x.status === "cancelled" && <li className="rounded-full border border-danger/30 px-2 py-0.5 text-danger">Отменено</li>}
        </ol>
        <div>
          <p className="text-xs font-semibold text-muted-foreground uppercase">Зафиксированная база</p>
          <p className="text-xs text-muted-foreground">Отпечаток {x.baseline.fingerprint.slice(0, 12)}… · {dateTime(x.baseline.captured_at)}
            {x.baseline_status === "superseded" && " · после фиксации появились новые данные (база не меняется)"}</p>
          <ul className="mt-1 list-disc pl-5">
            {x.baseline.hour_changes.map((h) => <li key={h.topic_id}>{h.name}: {num(h.from)} → {num(h.to)} ч ({signed(h.delta, " ч")})</li>)}
          </ul>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          {x.allowed_transitions.includes("implemented") && (
            <>
              <div className="flex flex-col gap-1"><Label htmlFor={`impl-${x.id}`} className="text-xs">Фактическая дата внедрения</Label>
                <Input id={`impl-${x.id}`} type="date" value={impl} onChange={(e) => setImpl(e.target.value)} className="w-44" /></div>
              <Button size="sm" disabled={busy || !impl} onClick={() => call(`${base}/transition`, { status: "implemented", implemented_on: impl })}
                data-testid="iv-implement">Отметить внедрение</Button>
            </>
          )}
          {x.allowed_transitions.includes("awaiting_outcome") && (
            <Button size="sm" disabled={busy} onClick={() => call(`${base}/transition`, { status: "awaiting_outcome" })} data-testid="iv-await">Ждать новых данных</Button>
          )}
          {(x.status === "awaiting_outcome" || x.status === "evaluated") && (
            <Button size="sm" disabled={busy} onClick={() => call(`${base}/evaluate`)} data-testid="iv-evaluate">
              {busy && <Loader2 className="size-4 animate-spin" />} {x.status === "evaluated" ? "Пересчитать оценку" : "Оценить результат"}
            </Button>
          )}
          {x.allowed_transitions.includes("cancelled") && (
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => call(`${base}/transition`, { status: "cancelled" })}>Отменить</Button>
          )}
        </div>
        {x.evaluation && <Evaluation ev={x.evaluation} />}
      </CardContent>
    </Card>
  );
}

function Evaluation({ ev }: { ev: NonNullable<Intervention["evaluation"]> }) {
  if (!ev.ready) {
    return <p className="rounded-lg border border-dashed p-3 text-muted-foreground" data-testid="iv-not-ready">
      После даты внедрения нет итоговых или текущих оцениваний по затронутым темам. Оценка невозможна — нужны новые данные.</p>;
  }
  return (
    <div className="space-y-2" data-testid="iv-evaluation">
      <Alert className="border-warning/40">
        <AlertTitle>Как читать результат</AlertTitle>
        <AlertDescription>{ev.statements.design} {ev.statements.causal} {ev.statements.inconclusive}
          {ev.synthetic && " Данные синтетические: изменение задано параметрами симуляции и не является проверкой эффекта."}</AlertDescription>
      </Alert>
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Тема</TableHead>
              <TableHead className="text-right">База (снимок)</TableHead>
              <TableHead className="text-right">После</TableHead>
              <TableHead className="text-right">Изменение</TableHead>
              <TableHead className="text-right">Пары: изменение, {num(ev.ci_level, 2)}% ДИ</TableHead>
              <TableHead className="text-right">Выбыло / новых</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {ev.topics.map((t) => (
              <TableRow key={t.topic_id}>
                <TableCell className="font-medium">{t.name}{!t.baseline_consistent && <span className="block text-xs text-danger">пересчёт базы не совпадает со снимком</span>}</TableCell>
                <TableCell className="text-right tabular-nums">{pct(t.frozen_mastery)}</TableCell>
                <TableCell className="text-right tabular-nums">{pct(t.after)}</TableCell>
                <TableCell className="text-right tabular-nums">{signed(t.descriptive_change, " п.п.")}</TableCell>
                <TableCell className="text-right tabular-nums">{t.after === null ? "—" : t.paired ? <>{signed(t.paired.mean_gain)} ({ci(t.paired.ci_low, t.paired.ci_high)}), n={t.paired.n_paired}</> : "мало пар"}</TableCell>
                <TableCell className="text-right tabular-nums">{t.lost_to_follow_up === null ? "нет оценивания после" : `${t.lost_to_follow_up} / ${t.new_students}`}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
