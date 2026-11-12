"use client";

import { Check, CircleAlert, Loader2, Lock, Play, Save, ShieldCheck, ThumbsDown, ThumbsUp, X } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { GroupedBars, NEUTRAL_MARK, PALETTE } from "@/components/charts";
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
import { DIRECTION_LABEL } from "@/lib/gain";
import { inapplicableFilters } from "@/lib/scope";
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
  const [f, update] = useFilters();
  const subjects = meta?.subjects ?? [];
  const grades = meta?.grades ?? [];
  // The plan covers one subject and one grade. URL values that no longer exist are not used silently.
  const urlSubjectValid = subjects.some((x) => x.id === f.subject_id);
  const urlGradeValid = f.grade !== undefined && grades.includes(f.grade);
  const subjectId = urlSubjectValid ? f.subject_id : subjects[0]?.id;
  const grade = urlGradeValid ? f.grade : grades[0];
  const subjectName = subjects.find((x) => x.id === subjectId)?.name ?? "";
  const notApplied = inapplicableFilters("/optimizer", f, meta);

  return (
    <>
      <section aria-label="Параметры плана" className="mb-6 space-y-3 rounded-xl border bg-card/60 p-3">
        <div className="grid grid-cols-2 gap-3 sm:max-w-md">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="o-subject" className="text-xs text-muted-foreground">{t.filters.subject}</Label>
            <Select value={subjectId ? String(subjectId) : undefined} onValueChange={(v) => update({ subject_id: Number(v), textbook_id: undefined })}>
              <SelectTrigger id="o-subject" className="w-full bg-card"><SelectValue placeholder="Выберите" /></SelectTrigger>
              <SelectContent>{subjects.map((x) => <SelectItem key={x.id} value={String(x.id)}>{x.name}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="o-grade" className="text-xs text-muted-foreground">{t.filters.grade}</Label>
            <Select value={grade ? String(grade) : undefined} onValueChange={(v) => update({ grade: Number(v), class_id: undefined })}>
              <SelectTrigger id="o-grade" className="w-full bg-card"><SelectValue placeholder="Выберите" /></SelectTrigger>
              <SelectContent>{grades.map((g) => <SelectItem key={g} value={String(g)}>{t.filters.gradeN(g)}</SelectItem>)}</SelectContent>
            </Select>
          </div>
        </div>
        {subjectId && grade && (
          <p className="text-sm">
            Нужны альтернативы?{" "}
            <Link className="font-medium underline underline-offset-2" href={`/scenarios?subject_id=${subjectId}&grade=${grade}`}>
              Сравнить три сценария плана
            </Link>{" "}
            (консервативный, сбалансированный, фокус на пробелах).
          </p>
        )}
        {subjectId && grade && (
          <p className="text-sm" data-testid="plan-scope-note">
            План составляется для всей параллели {grade} по предмету «{subjectName}» — один план для всех её классов.
            {notApplied.length > 0 && <> Здесь не применяется: {notApplied.join(", ")}; фильтр сохранён для других разделов.</>}
            {!urlSubjectValid && f.subject_id !== undefined && " Предмет из фильтра не найден — выбран первый доступный."}
            {!urlGradeValid && f.grade !== undefined && " Параллель из фильтра не найдена — выбрана первая доступная."}
            {f.subject_id === undefined || f.grade === undefined ? " Предмет или параллель не заданы фильтром — выбраны первые доступные." : ""}
          </p>
        )}
      </section>
      {subjectId && grade ? <Optimizer key={`${subjectId}-${grade}`} subjectId={subjectId} grade={grade} subjectName={subjectName} /> :
        <p className="text-sm text-muted-foreground">Выберите предмет и параллель.</p>}
    </>
  );
}

function Optimizer({ subjectId, grade, subjectName }: { subjectId: number; grade: number; subjectName: string }) {
  const inputs = useApi<OptimizerInputs>(`/api/optimizer/inputs?subject_id=${subjectId}&grade=${grade}`);
  if (inputs.error) return <ErrorState error={inputs.error} onRetry={inputs.reload} />;
  if (inputs.loading || !inputs.data) return <LoadingState rows={2} />;
  if (inputs.data.topics.length === 0) return <p className="text-sm text-muted-foreground">Для выбранной параллели нет тем.</p>;
  const version = inputs.data.topics.map((x) => `${x.topic_id}:${x.min_hours}:${x.max_hours}:${x.priority}`).join("|");
  return <OptimizerForm key={version} data={inputs.data} reloadInputs={inputs.reload} subjectId={subjectId} grade={grade}
    subjectName={subjectName} />;
}

function initialEdits(data: OptimizerInputs): Record<number, Edit> {
  const e: Record<number, Edit> = {};
  for (const tp of data.topics) e[tp.topic_id] = { current_hours: tp.current_hours, min_hours: tp.min_hours, max_hours: tp.max_hours, priority: tp.priority, locked: false };
  return e;
}

function OptimizerForm({ data, reloadInputs, subjectId, grade, subjectName }: {
  data: OptimizerInputs; reloadInputs: () => void; subjectId: number; grade: number; subjectName: string;
}) {
  const runs = useApi<RunListItem[]>(`/api/optimizer/runs?subject_id=${subjectId}&grade=${grade}`);
  const [edits, setEdits] = useState<Record<number, Edit>>(() => initialEdits(data));
  const [total, setTotal] = useState<string>(String(data.total_hours));
  const [target, setTarget] = useState<string>(String(data.target_mastery));
  const [maxChange, setMaxChange] = useState<string>(String(data.max_change_pct));
  const [run, setRun] = useState<OptimizerRun | null>(null);
  /** Where the displayed saved recommendation came from: just generated, or opened from history. */
  const [runSource, setRunSource] = useState<{ kind: "generated" } | { kind: "opened"; createdAt: string }>({ kind: "generated" });
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
      setRunSource({ kind: "generated" });
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
      toast.success(decision === "accept" ? `Рекомендация системы #${run.run_id} принята` : `Рекомендация #${run.run_id} отклонена`);
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
          <CardTitle>Новая рекомендация: исходные данные и ограничения</CardTitle>
          <CardDescription>
            Эта форма — черновик для формирования новой рекомендации; она не изменяет сохранённые рекомендации. Текущие часы — медиана по классам параллели (единый план параллели). Освоение рассчитано по данным. Можно изменить часы, границы,
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
                  <TableHead>Тема</TableHead><TableHead>Освоение</TableHead><TableHead>Изменение от входной диагностики</TableHead><TableHead className="w-24">Часы</TableHead>
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
                        {rowErrors[tp.topic_id] && <div id={`row-error-${tp.topic_id}`} className="text-xs text-danger">{rowErrors[tp.topic_id]}</div>}
                      </TableCell>
                      <TableCell><div className="flex items-center gap-2"><span className="tabular-nums">{pct(tp.mastery)}</span><StatusBadge status={tp.status} /></div></TableCell>
                      <TableCell className={cn("min-w-36 whitespace-normal text-sm", tp.gain_direction === "decline" && "text-danger")}>
                        {tp.gain === null || tp.gain_direction === null ? "не оценивалось"
                          : tp.gain_direction === "insufficient" ? DIRECTION_LABEL.insufficient
                            : <><b className="tabular-nums">{signed(tp.gain, " п.п.")}</b> · {DIRECTION_LABEL[tp.gain_direction]}</>}
                      </TableCell>
                      <TableCell>
                        <NumIn label={`Часы: ${tp.name}`} value={e.current_hours} onChange={(v) => setEdit(tp.topic_id, { current_hours: v })}
                          errorId={rowErrors[tp.topic_id] ? `row-error-${tp.topic_id}` : undefined} />
                        {tp.class_hours_min !== null && tp.class_hours_min !== tp.class_hours_max && (
                          <div className="mt-0.5 text-[11px] text-muted-foreground">классы: {num(tp.class_hours_min)}–{num(tp.class_hours_max)} ч</div>
                        )}
                      </TableCell>
                      <TableCell><NumIn label={`Минимум: ${tp.name}`} value={e.min_hours} onChange={(v) => setEdit(tp.topic_id, { min_hours: v })}
                        errorId={rowErrors[tp.topic_id] ? `row-error-${tp.topic_id}` : undefined} /></TableCell>
                      <TableCell><NumIn label={`Максимум: ${tp.name}`} value={e.max_hours} onChange={(v) => setEdit(tp.topic_id, { max_hours: v })}
                        errorId={rowErrors[tp.topic_id] ? `row-error-${tp.topic_id}` : undefined} /></TableCell>
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

      {run && (
        <>
          <RunResult run={run} source={runSource} subjectName={subjectName} grade={grade} formTotal={total} onDecide={decide} />
          <ManualPanel run={run} chartData={chartData} custom={custom} setCustom={setCustom} customChecks={customChecks}
            onEvaluate={evaluateCustom} />
        </>
      )}

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
                    <Button size="sm" variant="ghost" aria-label={`Открыть рекомендацию #${r.run_id}`} onClick={() => {
                      setRun({ ...r.result, run_id: r.run_id, status: r.status });
                      setRunSource({ kind: "opened", createdAt: r.created_at });
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

function RunResult({ run, source, subjectName, grade, formTotal, onDecide }: {
  run: OptimizerRun;
  source: { kind: "generated" } | { kind: "opened"; createdAt: string };
  subjectName: string;
  grade: number;
  formTotal: string;
  onDecide: (d: "accept" | "reject") => void;
}) {
  const [onlyChanged, setOnlyChanged] = useState(false);
  const series = [
    { key: "current", name: "Сейчас", color: NEUTRAL_MARK },
    { key: "proposed", name: "Рекомендация", color: "#4f46e5" },
  ];
  const chartData = run.rows.map((r) => ({ label: r.name, current: r.current_hours, proposed: r.proposed_hours }));
  const allOk = run.constraints.every((c) => c.ok);
  const changed = run.rows.filter((r) => r.delta !== 0);
  const ordered = [...changed, ...run.rows.filter((r) => r.delta === 0)];
  const rows = onlyChanged ? changed : ordered;
  const formDiffers = Number(formTotal.replace(",", ".")) !== run.total_hours;
  const decisionId = `decision-${run.run_id}`;
  return (
    <div className="space-y-6" data-testid="optimizer-result">
      <Card className="border-primary/30">
        <CardHeader>
          <CardTitle className="flex flex-wrap items-center gap-2">
            Сохранённая рекомендация системы #{run.run_id} <KindTag kind="recommendation" />
            <Badge variant={run.status === "accepted" ? "default" : "outline"} data-testid="run-status">{STATUS_RU[run.status]}</Badge>
          </CardTitle>
          <CardDescription>
            {source.kind === "opened"
              ? `Открыта из истории (создана ${dateTime(source.createdAt)}).`
              : "Только что сформирована и сохранена."}
            {formDiffers && ` Форма выше — черновик на ${formTotal} ч и не влияет на эту рекомендацию.`}
            {" "}Это рекомендация, а не прогноз результатов.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <dl className="grid grid-cols-2 gap-2 rounded-lg bg-muted/50 p-3 text-sm sm:grid-cols-3 lg:grid-cols-6" data-testid="saved-run-summary">
            <SummaryItem k="Номер" v={`#${run.run_id}`} />
            <SummaryItem k="Предмет" v={subjectName} />
            <SummaryItem k="Параллель" v={`${grade} класс`} />
            <SummaryItem k="Всего часов" v={`${num(run.proposed_total)} из ${num(run.total_hours)} ч`} />
            <SummaryItem k="Изменено тем" v={String(changed.length)} />
            <SummaryItem k="Ослабленные правила" v={run.relaxed_policies.length ? run.relaxed_policies.join(", ") : "нет"} />
          </dl>

          <div className="flex flex-wrap items-center gap-2 rounded-lg border p-3">
            <p id={decisionId} className="w-full text-sm text-muted-foreground sm:w-auto sm:flex-1">
              Решение относится только к сохранённой рекомендации #{run.run_id} ({num(run.total_hours)} ч) в таблице ниже.
              Ручной вариант не сохраняется и не принимается.
            </p>
            <Button size="sm" onClick={() => onDecide("accept")} disabled={run.status !== "proposed" || !allOk}
              data-testid="accept-run" data-run-id={run.run_id} aria-describedby={decisionId}>
              <ThumbsUp className="size-4" aria-hidden /> Принять рекомендацию системы
            </Button>
            <Button size="sm" variant="outline" onClick={() => onDecide("reject")} disabled={run.status !== "proposed"}
              aria-describedby={decisionId}>
              <ThumbsDown className="size-4" aria-hidden /> Отклонить
            </Button>
          </div>

          <GroupedBars data={chartData} series={series} unit="ч" height={320} />
          <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
            <span className="text-muted-foreground">Сначала темы с изменёнными часами ({changed.length} из {run.rows.length}).</span>
            <Button size="sm" variant="ghost" aria-pressed={onlyChanged} onClick={() => setOnlyChanged((v) => !v)}>
              {onlyChanged ? `Показать все темы (${run.rows.length})` : "Показать только изменённые"}
            </Button>
          </div>
          <div className="overflow-x-auto">
            <Table data-testid="allocation-table">
              <caption className="sr-only">Рекомендация #{run.run_id}: часы по темам и обоснование</caption>
              <TableHeader>
                <TableRow>
                  <TableHead>Тема</TableHead><TableHead className="text-right">Сейчас</TableHead><TableHead className="text-right">Предлагается</TableHead>
                  <TableHead className="text-right">Изменение</TableHead><TableHead>Обоснование</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((r) => (
                  <TableRow key={r.topic_id} className={cn(r.delta === 0 && "text-muted-foreground")}>
                    <TableCell className="font-medium whitespace-normal">
                      {r.locked && <Lock className="mr-1 inline size-3.5 text-muted-foreground" aria-label="зафиксирована" />}{r.name}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{num(r.current_hours, 2)}</TableCell>
                    <TableCell className="text-right font-semibold tabular-nums">{num(r.proposed_hours)}</TableCell>
                    <TableCell className={cn("text-right tabular-nums", r.delta > 0 ? "text-emerald-700" : r.delta < 0 ? "text-danger" : "")}>
                      {r.delta === 0 ? "без изменений" : `${signed(r.delta)} ч`}
                    </TableCell>
                    <TableCell className="min-w-72 whitespace-normal text-sm text-muted-foreground">{r.explanation}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Проверка рекомендации #{run.run_id}</CardTitle></CardHeader>
          <CardContent>
            <Checks title="Жёсткие ограничения" checks={run.constraints} />
            <div className="mt-4">
              <div className="mb-2 text-sm font-medium">Правила оптимизатора</div>
              <ul className="space-y-1.5 text-sm" data-testid="policy-checks">
                {run.policy_checks.map((p) => (
                  <li key={p.policy} className="flex items-start gap-2">
                    {p.status === "applied" ? <Check className="mt-0.5 size-4 text-success" aria-hidden /> : <CircleAlert className="mt-0.5 size-4 text-amber-700" aria-hidden />}
                    <span>{p.name} <span className="text-muted-foreground">— {p.status === "applied" ? "соблюдено" :
                      `ослаблено по запросу${p.affected_topics.length ? `: ${p.affected_topics.join(", ")}` : ""}`}</span></span>
                  </li>
                ))}
              </ul>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Предупреждения и метод</CardTitle></CardHeader>
          <CardContent className="space-y-3 text-sm">
            <ul className="space-y-2">{run.warnings.map((w) => <li key={w} className="flex gap-2"><CircleAlert className="mt-0.5 size-4 shrink-0 text-amber-700" aria-hidden />{w}</li>)}</ul>
            <p className="rounded-lg bg-muted/60 p-3 text-xs text-muted-foreground">{run.method}</p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function SummaryItem({ k, v }: { k: string; v: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{k}</dt>
      <dd className="font-medium break-words">{v}</dd>
    </div>
  );
}

function ManualPanel({ run, chartData, custom, setCustom, customChecks, onEvaluate }: {
  run: OptimizerRun;
  chartData: Record<string, string | number | null>[];
  custom: Record<number, string>;
  setCustom: (fn: (s: Record<number, string>) => Record<number, string>) => void;
  customChecks: CustomChecks | null;
  onEvaluate: () => void;
}) {
  const series = [
    { key: "proposed", name: `Рекомендация #${run.run_id}`, color: "#4f46e5" },
    { key: "custom", name: "Ручной вариант", color: PALETTE[1] },
  ];
  return (
    <Card className="border-dashed bg-muted/20" data-testid="manual-panel">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          Ручной вариант · проверка без сохранения <Badge variant="outline">не сохраняется</Badge>
        </CardTitle>
        <CardDescription>
          Проверка не изменяет сохранённую рекомендацию #{run.run_id}. Здесь можно проверить собственное распределение по тем же
          ограничениям; принять можно только сохранённую рекомендацию системы выше.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="overflow-x-auto">
          <Table data-testid="manual-table">
            <caption className="sr-only">Ручной вариант часов для проверки</caption>
            <TableHeader>
              <TableRow>
                <TableHead>Тема</TableHead><TableHead className="text-right">Рекомендация #{run.run_id}</TableHead>
                <TableHead className="w-32">Ручной вариант, ч</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {run.rows.map((r) => (
                <TableRow key={r.topic_id}>
                  <TableCell className="font-medium whitespace-normal">{r.name}</TableCell>
                  <TableCell className="text-right tabular-nums">{num(r.proposed_hours)}</TableCell>
                  <TableCell>
                    <Input inputMode="decimal" className="h-8 w-20" aria-label={`Ручной вариант: ${r.name}`} value={custom[r.topic_id] ?? ""}
                      onChange={(e) => setCustom((s) => ({ ...s, [r.topic_id]: e.target.value }))} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" onClick={onEvaluate} data-testid="evaluate-custom"><ShieldCheck className="size-4" aria-hidden /> Проверить ручной вариант</Button>
          <div role="status" aria-live="polite">
            {customChecks && (
              <Badge variant={customChecks.ok ? "default" : "destructive"}>
                {customChecks.ok ? "Ручной вариант соблюдает все ограничения" : "Ручной вариант нарушает ограничения"} · сумма {num(customChecks.total, 2)} ч · не сохранён
              </Badge>
            )}
          </div>
        </div>
        {customChecks && (
          <>
            <GroupedBars data={chartData} series={series} unit="ч" height={260} />
            <div className="grid gap-4 md:grid-cols-2">
              <Checks title="Жёсткие ограничения — ручной вариант" checks={customChecks.constraints} />
              <Checks title="Правила — ручной вариант (рекомендательные)" checks={customChecks.policy_checks.map((p) => ({
                name: p.name, ok: p.ok, detail: p.ok ? "соблюдено" : `нарушено: ${p.affected_topics.join(", ")}` }))} />
            </div>
          </>
        )}
      </CardContent>
    </Card>
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
      <Input id={id} inputMode="decimal" value={value} onChange={(e) => onChange(e.target.value)} aria-invalid={!!error}
        aria-describedby={error ? `${id}-error` : undefined} aria-errormessage={error ? `${id}-error` : undefined} />
      {error && <span id={`${id}-error`} className="text-xs text-danger">{error}</span>}
    </div>
  );
}

function NumIn({ value, onChange, label, errorId }: { value: number; onChange: (v: number) => void; label: string; errorId?: string }) {
  const [text, setText] = useState(String(value));
  const [prev, setPrev] = useState(value);
  if (value !== prev) {
    // adopt external changes (e.g. rounding on lock) without clobbering partial input like "1,"
    setPrev(value);
    if (Number(text.replace(",", ".")) !== value) setText(String(value));
  }
  return (
    <Input className="h-8 w-20" inputMode="decimal" aria-label={label} value={text}
      aria-invalid={errorId ? true : undefined} aria-describedby={errorId} aria-errormessage={errorId}
      onChange={(e) => {
        setText(e.target.value);
        const v = Number(e.target.value.replace(",", "."));
        if (e.target.value.trim() !== "" && Number.isFinite(v)) onChange(v);
      }} />
  );
}

