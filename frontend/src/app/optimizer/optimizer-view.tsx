"use client";

import { Check, CircleAlert, Loader2, Lock, Play, Save, ShieldCheck, ThumbsDown, ThumbsUp, X } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { GroupedBars } from "@/components/charts";
import { useFilters } from "@/components/filter-bar";
import { useMeta } from "@/components/meta-provider";
import { RequireData } from "@/components/page-frame";
import { ErrorState, LoadingState } from "@/components/states";
import { KindTag, StatusBadge } from "@/components/ui-bits";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useApi } from "@/hooks/use-api";
import { t } from "@/i18n";
import { api, ApiError } from "@/lib/api";
import { dateTime, num, pct, signed } from "@/lib/format";
import { topicConstraintSchema, totalHoursSchema } from "@/lib/schemas";
import type { ConstraintCheck, OptimizerInputs, OptimizerRun, RunListItem } from "@/lib/types";
import { cn } from "@/lib/utils";

interface Edit {
  current_hours: number;
  min_hours: number;
  max_hours: number;
  priority: number;
  locked: boolean;
}

interface CustomChecks {
  ok: boolean;
  constraints: ConstraintCheck[];
  total: number;
  policy_checks: { policy: string; name: string; ok: boolean; affected_topics: string[] }[];
}

const STATUS_RU = { proposed: "Предложена", accepted: "Принята", rejected: "Отклонена" } as const;

export function OptimizerView() {
  return (
    <RequireData>
      <Scope />
    </RequireData>
  );
}

function Scope() {
  const { data: meta } = useMeta();
  const [f] = useFilters();
  const subjects = meta?.subjects ?? [];
  const grades = meta?.grades ?? [];
  // URL params may be stale (e.g. after data was re-imported): only accept values that exist.
  const [subjectId, setSubjectId] = useState<number | undefined>(
    subjects.some((s) => s.id === f.subject_id) ? f.subject_id : subjects[0]?.id);
  const [grade, setGrade] = useState<number | undefined>(
    f.grade !== undefined && grades.includes(f.grade) ? f.grade : grades[0]);

  return (
    <>
      <div className="mb-6 grid grid-cols-2 gap-3 rounded-xl border bg-card/60 p-3 sm:max-w-md">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="o-subject" className="text-xs text-muted-foreground">{t.filters.subject}</Label>
          <Select value={subjectId ? String(subjectId) : undefined} onValueChange={(v) => setSubjectId(Number(v))}>
            <SelectTrigger id="o-subject" className="w-full bg-card"><SelectValue placeholder="Выберите" /></SelectTrigger>
            <SelectContent>{subjects.map((s) => <SelectItem key={s.id} value={String(s.id)}>{s.name}</SelectItem>)}</SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="o-grade" className="text-xs text-muted-foreground">{t.filters.grade}</Label>
          <Select value={grade ? String(grade) : undefined} onValueChange={(v) => setGrade(Number(v))}>
            <SelectTrigger id="o-grade" className="w-full bg-card"><SelectValue placeholder="Выберите" /></SelectTrigger>
            <SelectContent>{grades.map((g) => <SelectItem key={g} value={String(g)}>{t.filters.gradeN(g)}</SelectItem>)}</SelectContent>
          </Select>
        </div>
      </div>
      {subjectId && grade ? <Optimizer key={`${subjectId}-${grade}`} subjectId={subjectId} grade={grade} /> :
        <p className="text-sm text-muted-foreground">Выберите предмет и параллель.</p>}
    </>
  );
}

function Optimizer({ subjectId, grade }: { subjectId: number; grade: number }) {
  const inputs = useApi<OptimizerInputs>(`/api/optimizer/inputs?subject_id=${subjectId}&grade=${grade}`);
  if (inputs.error) return <ErrorState error={inputs.error} onRetry={inputs.reload} />;
  if (inputs.loading || !inputs.data) return <LoadingState rows={2} />;
  if (inputs.data.topics.length === 0) return <p className="text-sm text-muted-foreground">Для выбранной параллели нет тем.</p>;
  const version = inputs.data.topics.map((x) => `${x.topic_id}:${x.min_hours}:${x.max_hours}:${x.priority}`).join("|");
  return <OptimizerForm key={version} data={inputs.data} reloadInputs={inputs.reload} subjectId={subjectId} grade={grade} />;
}

function initialEdits(data: OptimizerInputs): Record<number, Edit> {
  const e: Record<number, Edit> = {};
  for (const tp of data.topics) e[tp.topic_id] = { current_hours: tp.current_hours, min_hours: tp.min_hours, max_hours: tp.max_hours, priority: tp.priority, locked: false };
  return e;
}

function OptimizerForm({ data, reloadInputs, subjectId, grade }: {
  data: OptimizerInputs; reloadInputs: () => void; subjectId: number; grade: number;
}) {
  const runs = useApi<RunListItem[]>(`/api/optimizer/runs?subject_id=${subjectId}&grade=${grade}`);
  const [edits, setEdits] = useState<Record<number, Edit>>(() => initialEdits(data));
  const [total, setTotal] = useState<string>(String(data.total_hours));
  const [target, setTarget] = useState<string>(String(data.target_mastery));
  const [maxChange, setMaxChange] = useState<string>(String(data.max_change_pct));
  const [run, setRun] = useState<OptimizerRun | null>(null);
  const [runError, setRunError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [allowRelax, setAllowRelax] = useState(false);
  const [custom, setCustom] = useState<Record<number, string>>({});
  const [customChecks, setCustomChecks] = useState<CustomChecks | null>(null);

  const names = useMemo(() => Object.fromEntries(data.topics.map((x) => [x.topic_id, x.name])), [data]);
  const totalParsed = totalHoursSchema.safeParse(Number(total.replace(",", ".")));
  const rowErrors = useMemo(() => {
    const out: Record<number, string> = {};
    for (const [id, e] of Object.entries(edits)) {
      const r = topicConstraintSchema.safeParse(e);
      if (!r.success) out[Number(id)] = r.error.issues[0]?.message ?? "Ошибка";
      else if (e.locked && !Number.isInteger(e.current_hours * 2)) out[Number(id)] = "Зафиксированные часы должны быть кратны 0,5";
    }
    return out;
  }, [edits]);
  const inRange = (v: string) => v.trim() !== "" && Number.isFinite(Number(v)) && Number(v) >= 0 && Number(v) <= 100;
  const formValid = totalParsed.success && Object.keys(rowErrors).length === 0 && inRange(target) && inRange(maxChange);

  const setEdit = (id: number, patch: Partial<Edit>) => setEdits((s) => ({ ...s, [id]: { ...s[id], ...patch } }));
  const currentSum = Object.values(edits).reduce((a, e) => a + e.current_hours, 0);

  async function generate() {
    if (!formValid) return;
    setBusy(true);
    setRunError(null);
    setCustomChecks(null);
    try {
      const body = {
        subject_id: subjectId, grade, total_hours: Number(total.replace(",", ".")), allow_policy_relaxation: allowRelax,
        target_mastery: Number(target), max_change_pct: Number(maxChange),
        topics: data.topics.map((tp) => {
          const e = edits[tp.topic_id];
          return { topic_id: tp.topic_id, current_hours: e.current_hours, min_hours: e.min_hours, max_hours: e.max_hours, priority: e.priority, locked: e.locked };
        }),
      };
      const r = await api.post<OptimizerRun>("/api/optimizer/run", body);
      setRun(r);
      setCustom(Object.fromEntries(r.rows.map((x) => [x.topic_id, String(x.proposed_hours)])));
      runs.reload();
      toast.success("Рекомендация сформирована");
    } catch (e) {
      setRunError(e instanceof ApiError ? e : new ApiError("Ошибка оптимизации.", 0));
      setRun(null);
    } finally {
      setBusy(false);
    }
  }

  async function saveConstraints() {
    const changed = data.topics.filter((tp) => {
      const e = edits[tp.topic_id];
      return e.min_hours !== tp.min_hours || e.max_hours !== tp.max_hours || e.priority !== tp.priority;
    });
    if (changed.length === 0) {
      toast.info("Ограничения не изменялись.");
      return;
    }
    try {
      for (const tp of changed) {
        const e = edits[tp.topic_id];
        await api.put(`/api/topics/${tp.topic_id}`, { min_hours: e.min_hours, max_hours: e.max_hours, priority: e.priority });
      }
      toast.success(`Сохранены ограничения для тем: ${changed.length}`);
      reloadInputs();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Не удалось сохранить");
    }
  }

  async function decide(decision: "accept" | "reject") {
    if (!run) return;
    try {
      const r = await api.post<{ status: OptimizerRun["status"] }>(`/api/optimizer/runs/${run.run_id}/decision`, { decision });
      setRun({ ...run, status: r.status });
      runs.reload();
      toast.success(decision === "accept" ? "Распределение принято" : "Рекомендация отклонена");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Ошибка");
    }
  }

  async function evaluateCustom() {
    if (!run) return;
    const allocation: Record<number, number> = {};
    for (const r of run.rows) {
      const v = Number((custom[r.topic_id] ?? "").replace(",", "."));
      if (!Number.isFinite(v) || v < 0) {
        toast.error(`Некорректное значение часов: «${r.name}»`);
        return;
      }
      allocation[r.topic_id] = v;
    }
    try {
      const body = {
        subject_id: subjectId, grade, total_hours: run.total_hours,
        topics: run.rows.map((r) => ({ topic_id: r.topic_id, current_hours: r.current_hours, min_hours: r.min_hours, max_hours: r.max_hours, priority: r.priority, locked: r.locked })),
        allocation,
      };
      setCustomChecks(await api.post("/api/optimizer/evaluate", body));
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Ошибка проверки");
    }
  }

  const chartData = run ? run.rows.map((r) => ({
    label: r.name, current: r.current_hours, proposed: r.proposed_hours,
    custom: customChecks ? Number((custom[r.topic_id] ?? "0").replace(",", ".")) : null,
  })) : [];

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Исходные данные и ограничения</CardTitle>
          <CardDescription>
            Текущие часы — медиана по классам параллели (единый план параллели). Освоение рассчитано по данным. Можно изменить часы, границы,
            приоритет и зафиксировать темы. Сумма текущих часов: {num(currentSum, 2)} ч.
          </CardDescription>
          <CardAction>
            <Button variant="outline" size="sm" onClick={saveConstraints}><Save className="size-4" /> Сохранить ограничения</Button>
          </CardAction>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-3">
            <Field id="total" label="Всего часов (кратно 0,5)" value={total} onChange={setTotal}
              error={totalParsed.success ? undefined : totalParsed.error.issues[0]?.message} />
            <Field id="target" label="Целевое освоение, %" value={target} onChange={setTarget} error={inRange(target) ? undefined : "От 0 до 100"} />
            <Field id="maxchange" label="Макс. изменение темы за шаг, %" value={maxChange} onChange={setMaxChange} error={inRange(maxChange) ? undefined : "От 0 до 100"} />
          </div>
          <div className="overflow-x-auto">
            <Table data-testid="optimizer-inputs">
              <TableHeader>
                <TableRow>
                  <TableHead>Тема</TableHead><TableHead>Освоение</TableHead><TableHead className="text-right">Прирост</TableHead><TableHead className="w-24">Часы</TableHead>
                  <TableHead className="w-20">Мин.</TableHead><TableHead className="w-20">Макс.</TableHead>
                  <TableHead className="w-24">Приоритет</TableHead><TableHead className="w-20 text-center">Фикс.</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.topics.map((tp) => {
                  const e = edits[tp.topic_id];
                  if (!e) return null;
                  return (
                    <TableRow key={tp.topic_id}>
                      <TableCell className="whitespace-normal">
                        <div className="font-medium">{tp.name}</div>
                        {tp.prerequisites.length > 0 && <div className="text-xs text-muted-foreground">после: {tp.prerequisites.map((p) => names[p] ?? p).join(", ")}</div>}
                        {rowErrors[tp.topic_id] && <div className="text-xs text-danger">{rowErrors[tp.topic_id]}</div>}
                      </TableCell>
                      <TableCell><div className="flex items-center gap-2"><span className="tabular-nums">{pct(tp.mastery)}</span><StatusBadge status={tp.status} /></div></TableCell>
                      <TableCell className={cn("text-right tabular-nums", tp.gain_significant === false && "text-danger")}>
                        {tp.gain === null ? "—" : tp.gain_direction === "insufficient" ? "мало пар" :
                          `${signed(tp.gain)}${tp.gain_direction === "inconclusive" ? " (н.у.)" : tp.gain_direction === "decline" ? " ↓" : ""}`}
                      </TableCell>
                      <TableCell>
                        <NumIn label={`Часы: ${tp.name}`} value={e.current_hours} onChange={(v) => setEdit(tp.topic_id, { current_hours: v })} />
                        {tp.class_hours_min !== null && tp.class_hours_min !== tp.class_hours_max && (
                          <div className="mt-0.5 text-[11px] text-muted-foreground">классы: {num(tp.class_hours_min)}–{num(tp.class_hours_max)} ч</div>
                        )}
                      </TableCell>
                      <TableCell><NumIn label={`Минимум: ${tp.name}`} value={e.min_hours} onChange={(v) => setEdit(tp.topic_id, { min_hours: v })} /></TableCell>
                      <TableCell><NumIn label={`Максимум: ${tp.name}`} value={e.max_hours} onChange={(v) => setEdit(tp.topic_id, { max_hours: v })} /></TableCell>
                      <TableCell>
                        <Select value={String(e.priority)} onValueChange={(v) => setEdit(tp.topic_id, { priority: Number(v) })}>
                          <SelectTrigger className="h-8 w-20" aria-label={`Приоритет: ${tp.name}`}><SelectValue /></SelectTrigger>
                          <SelectContent>{[1, 2, 3].map((p) => <SelectItem key={p} value={String(p)}>{p}</SelectItem>)}</SelectContent>
                        </Select>
                      </TableCell>
                      <TableCell className="text-center">
                        <Checkbox checked={e.locked} aria-label={`Зафиксировать: ${tp.name}`}
                          onCheckedChange={(c) => setEdit(tp.topic_id, { locked: c === true, current_hours: c === true ? Math.round(e.current_hours * 2) / 2 : e.current_hours })} />
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
          <p className="text-xs text-muted-foreground">
            План — единый для параллели: текущие часы темы — медиана по классам, округлённая до 0,5 ч (разброс по классам
            показан под значением). Приоритет: 1 — низкий, 3 — высокий. «Сохранить ограничения» записывает мин./макс./приоритет в базу.
          </p>
          <div className="flex items-start gap-2">
            <Checkbox id="relax" checked={allowRelax} onCheckedChange={(c) => setAllowRelax(c === true)} />
            <Label htmlFor="relax" className="text-sm font-normal leading-snug">
              Разрешить явное ослабление правил оптимизатора, если заданный объём часов иначе не распределить
              (например, при сокращении часов). Жёсткие ограничения не ослабляются никогда; ослабленные правила и
              затронутые темы будут перечислены.
            </Label>
          </div>
          <Button onClick={generate} disabled={!formValid || busy} data-testid="run-optimizer">
            {busy ? <Loader2 className="size-4 animate-spin" /> : <Play className="size-4" />} Сформировать рекомендацию
          </Button>
          {runError && (
            <Alert variant="destructive" data-testid="optimizer-error">
              <CircleAlert className="size-4" />
              <AlertTitle>{runError.message}</AlertTitle>
              {runError.details.length > 0 && <AlertDescription><ul className="list-disc pl-4">{runError.details.map((d) => <li key={d}>{d}</li>)}</ul></AlertDescription>}
            </Alert>
          )}
        </CardContent>
      </Card>

      {run && <RunResult run={run} chartData={chartData} custom={custom} setCustom={setCustom} customChecks={customChecks}
        onEvaluate={evaluateCustom} onDecide={decide} />}

      <Card>
        <CardHeader>
          <CardTitle>История рекомендаций</CardTitle>
          <CardDescription>Альтернативные варианты для этой параллели; откройте, чтобы сравнить</CardDescription>
        </CardHeader>
        <CardContent>
          {runs.data?.length ? (
            <ul className="divide-y text-sm">
              {runs.data.map((r) => (
                <li key={r.run_id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                  <span>#{r.run_id} · {dateTime(r.created_at)} · {num(r.total_hours)} ч · изменено тем: {r.changed_topics}</span>
                  <span className="flex items-center gap-2">
                    <Badge variant={r.status === "accepted" ? "default" : "outline"}>{STATUS_RU[r.status]}</Badge>
                    <Button size="sm" variant="ghost" onClick={() => {
                      setRun({ ...r.result, run_id: r.run_id, status: r.status });
                      setCustom(Object.fromEntries(r.result.rows.map((x) => [x.topic_id, String(x.proposed_hours)])));
                      setCustomChecks(null);
                    }}>Открыть</Button>
                  </span>
                </li>
              ))}
            </ul>
          ) : <p className="text-sm text-muted-foreground">Рекомендаций пока нет.</p>}
        </CardContent>
      </Card>
    </div>
  );
}

function RunResult({ run, chartData, custom, setCustom, customChecks, onEvaluate, onDecide }: {
  run: OptimizerRun;
  chartData: Record<string, string | number | null>[];
  custom: Record<number, string>;
  setCustom: (fn: (s: Record<number, string>) => Record<number, string>) => void;
  customChecks: CustomChecks | null;
  onEvaluate: () => void;
  onDecide: (d: "accept" | "reject") => void;
}) {
  const series = [
    { key: "current", name: "Сейчас", color: "#94a3b8" },
    { key: "proposed", name: "Рекомендация", color: "#4f46e5" },
    ...(customChecks ? [{ key: "custom", name: "Ручной вариант", color: "#0ea5a4" }] : []),
  ];
  const allOk = run.constraints.every((c) => c.ok);
  return (
    <div className="space-y-6" data-testid="optimizer-result">
      <Card>
        <CardHeader>
          <CardTitle className="flex flex-wrap items-center gap-2">
            Рекомендация #{run.run_id} <KindTag kind="recommendation" />
            <Badge variant={run.status === "accepted" ? "default" : "outline"} data-testid="run-status">{STATUS_RU[run.status]}</Badge>
          </CardTitle>
          <CardDescription>Всего {num(run.proposed_total)} ч из {num(run.total_hours)} ч. Это рекомендация, а не прогноз результатов.</CardDescription>
          <CardAction className="flex gap-2">
            <Button size="sm" onClick={() => onDecide("accept")} disabled={run.status !== "proposed" || !allOk} data-testid="accept-run">
              <ThumbsUp className="size-4" /> Принять
            </Button>
            <Button size="sm" variant="outline" onClick={() => onDecide("reject")} disabled={run.status !== "proposed"}>
              <ThumbsDown className="size-4" /> Отклонить
            </Button>
          </CardAction>
        </CardHeader>
        <CardContent className="space-y-5">
          <GroupedBars data={chartData} series={series} unit="ч" height={320} />
          <div className="overflow-x-auto">
            <Table data-testid="allocation-table">
              <TableHeader>
                <TableRow>
                  <TableHead>Тема</TableHead><TableHead className="text-right">Сейчас</TableHead><TableHead className="text-right">Предлагается</TableHead>
                  <TableHead className="text-right">Δ</TableHead><TableHead className="w-28">Ручной вариант</TableHead><TableHead>Обоснование</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {run.rows.map((r) => (
                  <TableRow key={r.topic_id}>
                    <TableCell className="font-medium whitespace-normal">{r.locked && <Lock className="mr-1 inline size-3.5 text-muted-foreground" />}{r.name}</TableCell>
                    <TableCell className="text-right tabular-nums">{num(r.current_hours, 2)}</TableCell>
                    <TableCell className="text-right font-semibold tabular-nums">{num(r.proposed_hours)}</TableCell>
                    <TableCell className={cn("text-right tabular-nums", r.delta > 0 ? "text-emerald-700" : r.delta < 0 ? "text-danger" : "text-muted-foreground")}>{signed(r.delta)}</TableCell>
                    <TableCell>
                      <Input inputMode="decimal" className="h-8 w-20" aria-label={`Ручной вариант: ${r.name}`} value={custom[r.topic_id] ?? ""}
                        onChange={(e) => setCustom((s) => ({ ...s, [r.topic_id]: e.target.value }))} />
                    </TableCell>
                    <TableCell className="min-w-72 whitespace-normal text-sm text-muted-foreground">{r.explanation}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" onClick={onEvaluate} data-testid="evaluate-custom"><ShieldCheck className="size-4" /> Проверить ручной вариант</Button>
            {customChecks && (
              <Badge variant={customChecks.ok ? "default" : "destructive"}>
                {customChecks.ok ? "Ручной вариант соблюдает все ограничения" : "Ручной вариант нарушает ограничения"} · сумма {num(customChecks.total, 2)} ч
              </Badge>
            )}
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Проверка ограничений</CardTitle></CardHeader>
          <CardContent>
            <Checks title="Жёсткие ограничения — рекомендация" checks={run.constraints} />
            <div className="mt-4">
              <div className="mb-2 text-sm font-medium">Правила оптимизатора</div>
              <ul className="space-y-1.5 text-sm" data-testid="policy-checks">
                {run.policy_checks.map((p) => (
                  <li key={p.policy} className="flex items-start gap-2">
                    {p.status === "applied" ? <Check className="mt-0.5 size-4 text-success" /> : <CircleAlert className="mt-0.5 size-4 text-amber-600" />}
                    <span>{p.name} <span className="text-muted-foreground">— {p.status === "applied" ? "соблюдено" :
                      `ослаблено по запросу${p.affected_topics.length ? `: ${p.affected_topics.join(", ")}` : ""}`}</span></span>
                  </li>
                ))}
              </ul>
            </div>
            {customChecks && (
              <div className="mt-4 space-y-3">
                <Checks title="Жёсткие ограничения — ручной вариант" checks={customChecks.constraints} />
                <Checks title="Правила — ручной вариант (рекомендательные)" checks={customChecks.policy_checks.map((p) => ({
                  name: p.name, ok: p.ok, detail: p.ok ? "соблюдено" : `нарушено: ${p.affected_topics.join(", ")}` }))} />
              </div>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Предупреждения и метод</CardTitle></CardHeader>
          <CardContent className="space-y-3 text-sm">
            <ul className="space-y-2">{run.warnings.map((w) => <li key={w} className="flex gap-2"><CircleAlert className="mt-0.5 size-4 shrink-0 text-amber-600" />{w}</li>)}</ul>
            <p className="rounded-lg bg-muted/60 p-3 text-xs text-muted-foreground">{run.method}</p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function Checks({ title, checks }: { title: string; checks: ConstraintCheck[] }) {
  return (
    <div>
      <div className="mb-2 text-sm font-medium">{title}</div>
      <ul className="space-y-1.5 text-sm" data-testid="constraint-checks">
        {checks.map((c) => (
          <li key={c.name} className="flex items-start gap-2">
            {c.ok ? <Check className="mt-0.5 size-4 text-success" /> : <X className="mt-0.5 size-4 text-danger" />}
            <span>{c.name} <span className="text-muted-foreground">— {c.detail}</span></span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Field({ id, label, value, onChange, error }: { id: string; label: string; value: string; onChange: (v: string) => void; error?: string }) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id} className="text-xs text-muted-foreground">{label}</Label>
      <Input id={id} inputMode="decimal" value={value} onChange={(e) => onChange(e.target.value)} aria-invalid={!!error} />
      {error && <span className="text-xs text-danger">{error}</span>}
    </div>
  );
}

function NumIn({ value, onChange, label }: { value: number; onChange: (v: number) => void; label: string }) {
  const [text, setText] = useState(String(value));
  const [prev, setPrev] = useState(value);
  if (value !== prev) {
    // adopt external changes (e.g. rounding on lock) without clobbering partial input like "1,"
    setPrev(value);
    if (Number(text.replace(",", ".")) !== value) setText(String(value));
  }
  return (
    <Input className="h-8 w-20" inputMode="decimal" aria-label={label} value={text}
      onChange={(e) => {
        setText(e.target.value);
        const v = Number(e.target.value.replace(",", "."));
        if (e.target.value.trim() !== "" && Number.isFinite(v)) onChange(v);
      }} />
  );
}

