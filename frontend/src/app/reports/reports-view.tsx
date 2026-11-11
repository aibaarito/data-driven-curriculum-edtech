"use client";

import { Download, Eye, FileText, Loader2, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { FilterBar, useFilters } from "@/components/filter-bar";
import { RequireData } from "@/components/page-frame";
import { ErrorState } from "@/components/states";
import { KindTag, StatusBadge } from "@/components/ui-bits";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useApi } from "@/hooks/use-api";
import { api, ApiError } from "@/lib/api";
import { dateTime, int, pct, signed } from "@/lib/format";
import type { Report, ReportListItem } from "@/lib/types";

export function ReportsView() {
  return (
    <RequireData>
      <FilterBar />
      <Content />
    </RequireData>
  );
}

function Content() {
  const [f] = useFilters();
  const list = useApi<ReportListItem[]>("/api/reports");
  const [includeAi, setIncludeAi] = useState(true);
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState<Report | null>(null);
  const [toDelete, setToDelete] = useState<ReportListItem | null>(null);

  async function create() {
    setBusy(true);
    try {
      const r = await api.post<Report>("/api/reports", { filters: f, include_ai: includeAi });
      setReport(r);
      list.reload();
      toast.success("Отчёт сформирован");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Не удалось сформировать отчёт");
    } finally {
      setBusy(false);
    }
  }

  async function open(id: number) {
    try {
      setReport(await api.get<Report>(`/api/reports/${id}`));
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Не удалось открыть отчёт");
    }
  }

  async function remove() {
    if (!toDelete) return;
    try {
      await api.del(`/api/reports/${toDelete.id}`);
      if (report?.id === toDelete.id) setReport(null);
      toast.success("Отчёт удалён");
      list.reload();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Не удалось удалить");
    } finally {
      setToDelete(null);
    }
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Новый отчёт</CardTitle>
          <CardDescription>
            Отчёт фиксирует выбранные фильтры, сводку оцениваний, результаты по темам, сравнение учебников, последнюю
            рекомендацию по часам, пояснения и ограничения данных. Наблюдения, рекомендации и ограничения разделены.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-4">
          <Button onClick={create} disabled={busy} data-testid="create-report">
            {busy ? <Loader2 className="size-4 animate-spin" /> : <FileText className="size-4" />} Сформировать отчёт
          </Button>
          <div className="flex items-center gap-2">
            <Switch id="ai" checked={includeAi} onCheckedChange={setIncludeAi} />
            <Label htmlFor="ai">Включить пояснения</Label>
          </div>
        </CardContent>
      </Card>

      {report && <ReportView report={report} />}

      <Card>
        <CardHeader><CardTitle>Сохранённые отчёты</CardTitle></CardHeader>
        <CardContent>
          {list.error ? <ErrorState error={list.error} onRetry={list.reload} /> : list.data?.length ? (
            <ul className="divide-y" data-testid="report-list">
              {list.data.map((r) => (
                <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5 text-sm">
                  <span className="min-w-0">
                    <span className="block font-medium">{r.title}</span>
                    <span className="text-xs text-muted-foreground">
                      {dateTime(r.created_at)} · {r.labels ? Object.entries(r.labels).map(([k, v]) => `${k}: ${v}`).join(" · ") : ""}
                    </span>
                  </span>
                  <span className="flex gap-1">
                    <Button size="sm" variant="ghost" onClick={() => open(r.id)}><Eye className="size-4" /> Открыть</Button>
                    <Button size="sm" variant="ghost" asChild>
                      <a href={`/api/reports/${r.id}/pdf`} download><Download className="size-4" /> PDF</a>
                    </Button>
                    <Button size="sm" variant="ghost" aria-label="Удалить отчёт" onClick={() => setToDelete(r)}><Trash2 className="size-4" /></Button>
                  </span>
                </li>
              ))}
            </ul>
          ) : <p className="text-sm text-muted-foreground">Отчётов пока нет.</p>}
        </CardContent>
      </Card>

      <Dialog open={toDelete !== null} onOpenChange={(o) => !o && setToDelete(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Удалить отчёт?</DialogTitle>
            <DialogDescription>«{toDelete?.title}» будет удалён без возможности восстановления. Исходные данные не затрагиваются.</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setToDelete(null)}>Отмена</Button>
            <Button variant="destructive" onClick={remove}>Удалить</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function ReportView({ report }: { report: Report }) {
  const c = report.content;
  return (
    <Card data-testid="report-view">
      <CardHeader>
        <CardTitle>{report.title}</CardTitle>
        <CardDescription>
          {Object.entries(c.filter_labels).map(([k, v]) => `${k}: ${v}`).join(" · ")}
          {c.synthetic && <Badge variant="outline" className="ml-2 border-warning/50 bg-warning/10 text-amber-800">синтетические данные</Badge>}
        </CardDescription>
        <CardAction>
          <Button asChild data-testid="download-pdf">
            <a href={`/api/reports/${report.id}/pdf`} download><Download className="size-4" /> Скачать PDF</a>
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-6 text-sm">
        <Section title="1. Сводка оцениваний" kind="observation">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
            {[["Учеников", int(c.overview.students)], ["Оцениваний", int(c.overview.assessments)], ["Классов", int(c.overview.classes)],
              ["Тем", int(c.overview.topics)], ["Среднее освоение", pct(c.overview.average_mastery)]].map(([k, v]) => (
              <div key={k} className="rounded-md bg-muted/60 p-2"><div className="text-xs text-muted-foreground">{k}</div><div className="font-semibold">{v}</div></div>
            ))}
          </div>
        </Section>
        <Section title="2. Результаты по темам" kind="observation">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader><TableRow><TableHead>Тема</TableHead><TableHead className="text-right">Освоение</TableHead><TableHead className="text-right">Учеников</TableHead><TableHead className="text-right">Прирост</TableHead><TableHead>Статус</TableHead></TableRow></TableHeader>
              <TableBody>
                {c.topics.map((tp) => (
                  <TableRow key={tp.topic_id}>
                    <TableCell className="whitespace-normal">{tp.name}</TableCell>
                    <TableCell className="text-right tabular-nums">{pct(tp.mastery)}</TableCell>
                    <TableCell className="text-right tabular-nums">{tp.student_count}</TableCell>
                    <TableCell className="text-right tabular-nums">{tp.gain ? signed(tp.gain.mean_gain, " п.п.") : "—"}</TableCell>
                    <TableCell><StatusBadge status={tp.status} /></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </Section>
        <Section title="3. Сравнение учебников" kind="observation">
          {c.textbooks.pairs.length ? c.textbooks.pairs.map((p) => (
            <p key={`${p.textbook_a}-${p.textbook_b}`} className="rounded-md border p-2"><b>{p.name_a} — {p.name_b}:</b> {p.verdict_text}</p>
          )) : <p className="text-muted-foreground">{c.textbooks.message ?? "Нет сопоставимых пар учебников."}</p>}
        </Section>
        <Section title="4. Рекомендации по часам" kind="recommendation">
          {c.optimizer ? (
            <>
              <p className="mb-2 text-muted-foreground">Статус: {c.optimizer_status_label}. Рекомендация не является прогнозом результатов.</p>
              {c.optimizer_scope_note && <p className="mb-2 text-muted-foreground" data-testid="plan-scope">{c.optimizer_scope_note}</p>}
              <ul className="space-y-1">
                {c.optimizer.rows.filter((r) => r.delta !== 0).map((r) => (
                  <li key={r.topic_id}><b>{r.name}</b>: {r.current_hours} → {r.proposed_hours} ч. <span className="text-muted-foreground">{r.explanation}</span></li>
                ))}
              </ul>
            </>
          ) : <p className="text-muted-foreground" data-testid="plan-scope">{c.optimizer_scope_note ?? "Рекомендация для этих фильтров не сформирована."}</p>}
        </Section>
        {c.insights && (
          <Section title={`5. Пояснения (${c.insights.mode === "llm" ? "языковая модель, проверено" : "детерминированный режим"})`} kind="observation">
            <p>{c.insights.payload.summary}</p>
          </Section>
        )}
        <Section title="6. Ограничения данных" kind="limitation">
          <ul className="list-disc space-y-1 pl-5">{c.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
        </Section>
      </CardContent>
    </Card>
  );
}

function Section({ title, kind, children }: { title: string; kind: "observation" | "recommendation" | "limitation"; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="mb-2 flex items-center gap-2 font-semibold">{title} <KindTag kind={kind} /></h3>
      {children}
    </section>
  );
}
