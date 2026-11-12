"use client";

import { Download, Loader2, Search, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { CapabilityList } from "@/components/capabilities";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useApi } from "@/hooks/use-api";
import { api, ApiError } from "@/lib/api";
import { dateTime, int } from "@/lib/format";
import type { AggregateGroup, ColumnSummary, DatasetDetail, DatasetMeta, DatasetRowsPage } from "@/lib/types";

import { selectClass } from "../import/guided-steps";

const TYPE_LABEL: Record<string, string> = {
  number: "число", date: "дата", category: "категория", text: "текст", identifier: "идентификатор", boolean: "да/нет",
};

export function DatasetsView() {
  const params = useSearchParams();
  const id = Number(params.get("id")) || null;
  return id ? <DatasetDetailView id={id} /> : <DatasetList />;
}

function DatasetList() {
  const list = useApi<DatasetMeta[]>("/api/datasets");
  if (list.loading) return <LoadingState />;
  if (list.error) return <ErrorState error={list.error} onRetry={list.reload} />;
  if (!list.data?.length) {
    return <EmptyState title="Наборов данных пока нет" text="Импортируйте сводную или любую другую таблицу на странице «Импорт данных», выбрав соответствующую структуру." />;
  }
  return (
    <ul className="grid gap-3 md:grid-cols-2" data-testid="dataset-list">
      {list.data.map((d) => (
        <li key={d.id}>
          <Link href={`/datasets?id=${d.id}`} className="block rounded-xl border p-4 hover:bg-accent/40 focus-visible:ring-2 focus-visible:ring-ring">
            <span className="flex flex-wrap items-center gap-2 font-medium">
              <span className="break-words">{d.name}</span>
              <Badge variant={d.kind === "aggregate" ? "secondary" : "outline"}>{d.kind === "aggregate" ? "сводная таблица" : "общая таблица"}</Badge>
            </span>
            <span className="mt-1 block text-xs text-muted-foreground">
              {d.source_filename} · лист «{d.sheet}» · {int(d.row_count)} строк · {dateTime(d.created_at)}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

function DatasetDetailView({ id }: { id: number }) {
  const router = useRouter();
  const ds = useApi<DatasetDetail>(`/api/datasets/${id}`);
  const [override, setOverride] = useState<DatasetDetail | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const data = override && override.id === id ? override : ds.data;
  if (ds.loading && !data) return <LoadingState />;
  if (ds.error) return <ErrorState error={ds.error} onRetry={ds.reload} />;
  if (!data) return null;

  async function changeType(col: string, type: string) {
    setSaving(true);
    try {
      setOverride(await api.put<DatasetDetail>(`/api/datasets/${id}/columns`, { types: { [col]: type } }));
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Не удалось изменить тип.");
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    await api.del(`/api/datasets/${id}`);
    toast.info("Набор данных удалён.");
    router.push("/datasets");
  }

  const p = data.profile;
  return (
    <div className="space-y-6" data-testid="dataset-detail">
      <div className="flex flex-wrap items-center gap-2">
        <Button asChild size="sm" variant="outline"><Link href="/datasets">← Все наборы</Link></Button>
        <Button asChild size="sm" variant="outline">
          <a href={`/api/datasets/${id}/export.csv`} download><Download className="size-4" /> Экспорт CSV</a>
        </Button>
        {confirmDelete ? (
          <span className="flex items-center gap-2 text-sm">
            Удалить набор безвозвратно?
            <Button size="sm" variant="destructive" onClick={remove}>Удалить</Button>
            <Button size="sm" variant="outline" onClick={() => setConfirmDelete(false)}>Отмена</Button>
          </span>
        ) : (
          <Button size="sm" variant="outline" onClick={() => setConfirmDelete(true)}><Trash2 className="size-4" /> Удалить</Button>
        )}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex flex-wrap items-center gap-2">
            <span className="break-words">{data.name}</span>
            <Badge variant={data.kind === "aggregate" ? "secondary" : "outline"}>{data.kind === "aggregate" ? "сводная таблица" : "общая таблица"}</Badge>
          </CardTitle>
          <CardDescription className="break-words">
            Источник: {data.source_filename}, лист «{data.sheet}». Хранится отдельно от результатов оценивания; исходные значения не изменяются.
            Экспорт защищён от выполнения формул в Excel.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4" data-testid="dataset-stats">
            {([["Строк", int(p.rows)], ["Столбцов", int(p.columns)], ["Повторяющихся строк", int(p.duplicate_rows)],
              ["Пропусков", int(p.column_profiles.reduce((a, c) => a + c.missing, 0))]] as [string, string][]).map(([k, v]) => (
              <div key={k} className="rounded-lg bg-muted/60 p-2.5"><dt className="text-xs text-muted-foreground">{k}</dt><dd className="font-semibold">{v}</dd></div>
            ))}
          </dl>
        </CardContent>
      </Card>

      {data.aggregate && <AggregateView agg={data.aggregate} />}

      <Card>
        <CardHeader>
          <CardTitle>Столбцы</CardTitle>
          <CardDescription>
            {data.kind === "general" ? "Тип определяет, как читаются значения для сводок и графиков. Идентификаторы не суммируются." : "Роли столбцов заданы при импорте."}
            {saving && <Loader2 className="ml-2 inline size-4 animate-spin" aria-label="Сохранение" />}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="grid gap-3 lg:grid-cols-2" data-testid="column-profiles">
            {p.column_profiles.map((c) => (
              <ColumnCard key={c.id} col={c} role={data.columns.find((x) => x.id === c.id)?.role ?? null}
                editable={data.kind === "general"} disabled={saving} onType={(t) => changeType(c.id, t)} />
            ))}
          </ul>
        </CardContent>
      </Card>

      <RowBrowser id={id} detail={data} />

      <Card><CardContent className="pt-6"><CapabilityList items={data.capabilities} title="Доступный анализ этого набора" /></CardContent></Card>
    </div>
  );
}

function ColumnCard({ col, role, editable, disabled, onType }: {
  col: ColumnSummary;
  role: string | null;
  editable: boolean;
  disabled: boolean;
  onType: (t: string) => void;
}) {
  const id = `coltype-${col.id}`;
  return (
    <li className="space-y-2 rounded-lg border p-3 text-sm" data-testid={`profile-${col.letter}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="min-w-0 break-words font-medium">{col.letter} · {col.label}</span>
        {editable ? (
          <span className="flex items-center gap-1">
            <label htmlFor={id} className="sr-only">Тип столбца {col.label}</label>
            <select id={id} className={`${selectClass} h-8 w-40`} value={col.type} disabled={disabled} onChange={(e) => onType(e.target.value)}>
              {Object.entries(TYPE_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </span>
        ) : <Badge variant="outline">{role ?? TYPE_LABEL[col.type] ?? col.type}</Badge>}
      </div>
      <p className="text-xs text-muted-foreground">
        Пропусков: {int(col.missing)} ({col.missing_pct}%) · различных значений: {int(col.distinct)}
        {col.mismatched ? ` · не соответствуют типу: ${int(col.mismatched)}` : ""}
      </p>
      {col.numeric && (
        <p className="text-xs">Среднее {fmt(col.numeric.mean)} · медиана {fmt(col.numeric.median)} · мин {fmt(col.numeric.min)} · макс {fmt(col.numeric.max)}
          {col.numeric.sd !== null ? ` · ст. откл. ${fmt(col.numeric.sd)}` : ""}</p>
      )}
      {col.date_range && <p className="text-xs">Период: {col.date_range.from} — {col.date_range.to}</p>}
      {col.histogram && <Bars caption={`Распределение значений «${col.label}»`} items={col.histogram.map((h) => ({ label: `${fmt(h.from)}–${fmt(h.to)}`, count: h.count }))} />}
      {col.frequencies && (
        <Bars caption={`Частоты «${col.label}»`} items={[...col.frequencies.map((f) => ({ label: f.value || "(пусто)", count: f.count })),
          ...(col.other_count ? [{ label: "другие", count: col.other_count }] : [])]} />
      )}
    </li>
  );
}

function fmt(x: number): string {
  return Number.isInteger(x) ? String(x) : x.toLocaleString("ru-RU", { maximumFractionDigits: 2 });
}

/** Accessible horizontal bars: the numbers are always shown as text next to each bar. */
function Bars({ caption, items }: { caption: string; items: { label: string; count: number }[] }) {
  const max = Math.max(1, ...items.map((i) => i.count));
  return (
    <figure>
      <figcaption className="sr-only">{caption}</figcaption>
      <ul className="space-y-0.5">
        {items.map((i, k) => (
          <li key={k} className="grid grid-cols-[minmax(0,7rem)_minmax(0,1fr)_2.5rem] items-center gap-2 text-[11px]">
            <span className="truncate" title={i.label}>{i.label}</span>
            <span className="h-2 rounded bg-muted"><span className="block h-2 rounded bg-primary" style={{ width: `${(i.count / max) * 100}%` }} /></span>
            <span className="text-right tabular-nums">{i.count}</span>
          </li>
        ))}
      </ul>
    </figure>
  );
}

function AggregateView({ agg }: { agg: NonNullable<DatasetDetail["aggregate"]> }) {
  const sections: [string, AggregateGroup[]][] = [["По темам", agg.by_topic], ["По классам", agg.by_class], ["По учебникам", agg.by_textbook]];
  return (
    <Card data-testid="aggregate-summary">
      <CardHeader>
        <CardTitle>Сводка показателей <Badge variant="secondary">агрегированные данные</Badge></CardTitle>
        <CardDescription>{agg.note}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {sections.filter(([, g]) => g.length).map(([title, groups]) => (
          <div key={title}>
            <h3 className="mb-1 text-sm font-medium">{title}</h3>
            <div className="overflow-auto rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow><TableHead>Группа</TableHead><TableHead>Строк</TableHead><TableHead>Среднее по группам, %</TableHead>
                    <TableHead>Мин–макс, %</TableHead><TableHead>Взвешенное по числу учеников, %</TableHead></TableRow>
                </TableHeader>
                <TableBody>
                  {groups.map((g) => (
                    <TableRow key={g.group}>
                      <TableCell className="whitespace-normal">{g.group}</TableCell><TableCell>{g.rows}</TableCell>
                      <TableCell>{fmt(g.mean_of_groups_pct)}</TableCell><TableCell>{fmt(g.min_pct)}–{fmt(g.max_pct)}</TableCell>
                      <TableCell>{g.weighted_pct === null ? "нет числа учеников" : `${fmt(g.weighted_pct)} (n = ${g.students_total})`}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function RowBrowser({ id, detail }: { id: number; detail: DatasetDetail }) {
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState("");
  const [dir, setDir] = useState<"asc" | "desc">("asc");
  const [fcol, setFcol] = useState("");
  const [fval, setFval] = useState("");
  const [page, setPage] = useState(0);
  const qs = new URLSearchParams({ page: String(page), direction: dir });
  if (query) qs.set("q", query);
  if (sort) qs.set("sort", sort);
  if (fcol && fval) {
    qs.set("filter_col", fcol);
    qs.set("filter_value", fval);
  }
  const rows = useApi<DatasetRowsPage>(`/api/datasets/${id}/rows?${qs.toString()}`);
  const cols = detail.columns;
  const pages = rows.data ? Math.max(1, Math.ceil(rows.data.total / rows.data.page_size)) : 1;
  return (
    <Card>
      <CardHeader><CardTitle>Строки</CardTitle><CardDescription>Поиск по всем столбцам, сортировка по типу столбца и фильтр по точному значению.</CardDescription></CardHeader>
      <CardContent className="space-y-3">
        <form className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5" onSubmit={(e) => { e.preventDefault(); setQuery(q); setPage(0); }}>
          <div className="grid gap-1 lg:col-span-2">
            <label htmlFor="ds-q" className="text-xs font-medium">Поиск</label>
            <span className="flex gap-1">
              <Input id="ds-q" value={q} maxLength={200} onChange={(e) => setQ(e.target.value)} />
              <Button type="submit" size="sm" variant="outline" aria-label="Искать"><Search className="size-4" /></Button>
            </span>
          </div>
          <div className="grid gap-1">
            <label htmlFor="ds-sort" className="text-xs font-medium">Сортировка</label>
            <span className="flex gap-1">
              <select id="ds-sort" className={selectClass} value={sort} onChange={(e) => { setSort(e.target.value); setPage(0); }}>
                <option value="">как в файле</option>
                {cols.map((c) => <option key={c.id} value={c.id}>{c.letter} · {c.label}</option>)}
              </select>
              <label htmlFor="ds-dir" className="sr-only">Направление сортировки</label>
              <select id="ds-dir" className={`${selectClass} w-24`} value={dir} onChange={(e) => setDir(e.target.value as "asc" | "desc")}>
                <option value="asc">↑</option><option value="desc">↓</option>
              </select>
            </span>
          </div>
          <div className="grid gap-1">
            <label htmlFor="ds-fcol" className="text-xs font-medium">Фильтр: столбец</label>
            <select id="ds-fcol" className={selectClass} value={fcol} onChange={(e) => { setFcol(e.target.value); setPage(0); }}>
              <option value="">без фильтра</option>
              {cols.map((c) => <option key={c.id} value={c.id}>{c.letter} · {c.label}</option>)}
            </select>
          </div>
          <div className="grid gap-1">
            <label htmlFor="ds-fval" className="text-xs font-medium">Фильтр: значение</label>
            <Input id="ds-fval" value={fval} maxLength={200} disabled={!fcol} onChange={(e) => { setFval(e.target.value); setPage(0); }} />
          </div>
        </form>
        {rows.error && <ErrorState error={rows.error} onRetry={rows.reload} />}
        {rows.data && (
          <>
            <p className="text-xs text-muted-foreground" aria-live="polite">Найдено строк: {int(rows.data.total)}</p>
            <div className="max-h-[28rem] overflow-auto rounded-lg border" role="region" aria-label="Строки набора данных" tabIndex={0}>
              <Table data-testid="dataset-rows">
                <TableHeader>
                  <TableRow><TableHead>Строка файла</TableHead>{cols.map((c) => <TableHead key={c.id} className="whitespace-nowrap">{c.label}</TableHead>)}</TableRow>
                </TableHeader>
                <TableBody>
                  {rows.data.rows.map((r) => (
                    <TableRow key={r.source_row}>
                      <TableCell className="text-muted-foreground">{r.source_row}</TableCell>
                      {cols.map((c, i) => <TableCell key={c.id} className="max-w-64 truncate text-xs" title={r.values[i] ?? ""}>{r.values[i] ?? ""}</TableCell>)}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            {pages > 1 && (
              <div className="flex items-center justify-between text-sm text-muted-foreground">
                <span>Страница {page + 1} из {pages}</span>
                <span className="flex gap-2">
                  <Button size="sm" variant="outline" disabled={page === 0} onClick={() => setPage(page - 1)}>Назад</Button>
                  <Button size="sm" variant="outline" disabled={page >= pages - 1} onClick={() => setPage(page + 1)}>Далее</Button>
                </span>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
