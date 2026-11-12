"use client";

import { AlertTriangle, CheckCircle2, Loader2, XCircle } from "lucide-react";
import { useMemo } from "react";

import { CapabilityList } from "@/components/capabilities";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { int } from "@/lib/format";
import { columnLabel, groupByRow, importFieldLabel, issueTitle, summarizeErrors } from "@/lib/import-issues";
import type { GuidedValidation, ImportSource, ValidationIssue } from "@/lib/types";

const PAGE = 20;

type Issue = ValidationIssue & { source_column?: string; sheet?: string; value?: string; suggestion?: string; count?: number };

export function ReviewPanel({ report, source, page, setPage, committing, done, onCommit, onDiscard }: {
  report: GuidedValidation;
  source: ImportSource;
  page: number;
  setPage: (n: number) => void;
  committing: boolean;
  done: boolean;
  onCommit: () => void;
  onDiscard: () => void;
}) {
  const s = report.summary;
  const cfg = report.config;
  const c = report.counts;
  const isDataset = cfg.kind === "dataset";
  const groups = useMemo(() => groupByRow(report.errors), [report]);
  const warningGroups = useMemo(() => {
    const m = new Map<string, Issue[]>();
    for (const w of report.warnings as Issue[]) m.set(w.code, [...(m.get(w.code) ?? []), w]);
    return [...m.entries()];
  }, [report]);
  const summary = summarizeErrors(report);
  const pages = Math.max(1, Math.ceil(groups.length / PAGE));
  const shown = groups.slice(page * PAGE, page * PAGE + PAGE);
  const cols = useMemo(() => (report.preview[0] ? Object.keys(report.preview[0]).filter((k) => k !== "row") : []), [report]);
  const where = (row: number) => (source.kind === "xlsx" ? `Лист «${cfg.sheet}», строка ${row}` : `Строка ${row}`);
  const validated = report.records_validated !== false;

  const countCells: [string, string][] = c ? [
    ["Строк в источнике", int(c.source_rows)],
    ["Исключено строк", int(c.excluded_rows)],
    [isDataset ? "Строк в наборе" : "Записей после преобразования", validated ? int(c.records) : "не проверены"],
    ["Корректных", validated ? int(c.valid_records) : "—"],
    ["С ошибками", validated ? int(c.invalid_records) : "—"],
    ...(!isDataset ? [["Уже загружены", int(c.existing_duplicates)] as [string, string]] : []),
    ["Будет импортировано", report.ok ? int(c.eligible) : "0 — импорт заблокирован"],
  ] : [
    ["Найдено записей", int(report.total_rows)], ["С ошибками", int(report.rows_with_errors ?? 0)],
    ["Будет импортировано", report.ok ? int(report.valid_rows) : "0 — импорт заблокирован"],
  ];

  return (
    <Card data-testid="import-preview">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          {report.ok ? <CheckCircle2 className="size-5 text-success" aria-hidden /> : <XCircle className="size-5 text-danger" aria-hidden />}
          5. {report.ok ? "Файл прошёл проверку" : "В файле есть ошибки — данные ещё не импортированы"}
        </CardTitle>
        <CardDescription className="break-words">
          {source.filename}{source.kind === "xlsx" ? `, лист «${cfg.sheet}»` : ""}, заголовок — строка {cfg.header_row}
          {cfg.header_rows === 2 ? " (двухстрочный)" : ""}; структура: {cfg.layout_label ?? "записи"}.{" "}
          {report.ok ? "Ничего не сохранено до подтверждения." : "Данные не исправляются автоматически; частичный импорт не выполняется."}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4 lg:grid-cols-7" data-testid="record-counts">
          {countCells.map(([k, v]) => (
            <div key={k} className="rounded-lg bg-muted/60 p-2.5">
              <dt className="text-xs text-muted-foreground">{k}</dt>
              <dd className="font-semibold">{v}</dd>
            </div>
          ))}
        </dl>
        {c?.wide_explanation && <p className="text-sm text-muted-foreground" data-testid="wide-explanation">{c.wide_explanation}</p>}
        {c && c.excluded_rows > 0 && (
          <p className="text-xs text-muted-foreground">Исключены по вашему выбору строки: {(c.excluded_row_numbers ?? []).join(", ")}.</p>
        )}
        {!validated && <p className="text-sm text-muted-foreground">Проверка остановилась на структуре таблицы, поэтому отдельные записи ещё не проверялись.</p>}

        {!report.ok && (
          <div role="alert" className="rounded-lg border border-danger/30 bg-danger/5 p-3" data-testid="import-error-summary">
            <p className="font-medium">{summary.headline}</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Номера строк и буквы столбцов — как в исходном файле. Исправьте файл или настройки чтения и проверьте снова. Идентификаторы учеников не показываются.
            </p>
          </div>
        )}

        {report.capabilities && report.capabilities.length > 0 && (
          <CapabilityList items={report.capabilities}
            title={isDataset ? "Что можно будет анализировать в этом наборе" : "Что можно будет анализировать по данным этого файла"} />
        )}

        {report.ok && (
          <section aria-labelledby="confirm-title" className="rounded-lg border p-3 text-sm" data-testid="confirm-summary">
            <h3 id="confirm-title" className="mb-2 font-medium">Что будет импортировано</h3>
            <dl className="grid gap-x-4 gap-y-1 sm:grid-cols-[max-content_minmax(0,1fr)]">
              <dt className="text-muted-foreground">Файл</dt><dd className="break-words">{source.filename}</dd>
              {source.kind === "xlsx" && (<><dt className="text-muted-foreground">Лист</dt><dd className="break-words">{cfg.sheet}{cfg.sheet_hidden ? " (скрытый)" : ""}</dd></>)}
              <dt className="text-muted-foreground">Строка заголовка</dt><dd>{cfg.header_row}{cfg.header_rows === 2 ? ` (группы — строка ${cfg.header_row - 1})` : ""}</dd>
              {cfg.range && (cfg.range.first_col !== "A" || cfg.range.last_col || cfg.range.last_row) && (
                <><dt className="text-muted-foreground">Диапазон</dt><dd>{cfg.range.first_col}–{cfg.range.last_col ?? "конец"}, до строки {cfg.range.last_row ?? "конца"}</dd></>
              )}
              <dt className="text-muted-foreground">Структура</dt><dd>{cfg.layout_label}</dd>
              {isDataset ? (
                <><dt className="text-muted-foreground">Набор данных</dt><dd>{cfg.dataset_name || `${source.filename} — ${cfg.sheet}`}, строк: {int(report.valid_rows)}</dd></>
              ) : (
                <>
                  <dt className="text-muted-foreground">Записей</dt>
                  <dd>{int(c?.eligible ?? report.valid_rows)}{c?.existing_duplicates ? ` (ещё ${int(c.existing_duplicates)} уже загружены и будут пропущены)` : ""}</dd>
                  <dt className="text-muted-foreground">Учеников / классов / тем / оцениваний</dt>
                  <dd>{s.students ?? "—"} / {s.classes ?? "—"} / {s.topics ?? "—"} / {s.assessments ?? "—"}</dd>
                  <dt className="text-muted-foreground">Период</dt><dd>{s.date_from} — {s.date_to}</dd>
                  <dt className="text-muted-foreground">Значения для всего файла</dt>
                  <dd>{cfg.shared.length ? cfg.shared.map((x) => `${x.label}: ${x.value}`).join("; ") : "нет"}</dd>
                </>
              )}
              {cfg.not_in_file.length > 0 && (<><dt className="text-muted-foreground">Нет в файле</dt><dd>{cfg.not_in_file.map((x) => x.label).join(", ")}</dd></>)}
              {(cfg.excluded_kinds ?? []).length > 0 && (<><dt className="text-muted-foreground">Исключены</dt><dd>{cfg.excluded_kinds!.join(", ")}</dd></>)}
              {(cfg.rules ?? []).length > 0 && (<><dt className="text-muted-foreground">Правила</dt><dd><ul className="list-disc pl-4">{cfg.rules!.map((r, i) => <li key={i}>{r}</li>)}</ul></dd></>)}
              <dt className="text-muted-foreground">Игнорируемые столбцы</dt>
              <dd className="break-words">{cfg.ignored_columns.length ? cfg.ignored_columns.join(", ") : "нет"}</dd>
            </dl>
            <details className="mt-2">
              <summary className="cursor-pointer text-xs text-muted-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring">Сопоставление столбцов</summary>
              <ul className="mt-1 text-xs">
                {cfg.mapped.map((x) => <li key={x.field}>{x.label} ← {x.letter} «{x.header}»</li>)}
                {(cfg.result_columns ?? []).map((x) => <li key={x.letter}>Результат {x.letter} «{x.header}» → тема {x.topic_id} «{x.topic_name}»{x.item_id ? `, задание ${x.item_id}` : ""}{x.max_score ? `, максимум ${x.max_score}` : ""}</li>)}
                {(cfg.roles ?? []).map((x) => <li key={x.letter}>{x.role_label} ← {x.letter} «{x.header}»</li>)}
                {(cfg.types ?? []).map((x) => <li key={x.letter}>{x.letter} «{x.header}»: {x.type_label}</li>)}
              </ul>
            </details>
          </section>
        )}

        {warningGroups.length > 0 && (
          <Alert className="border-warning/50 bg-warning/10" data-testid="import-warnings">
            <AlertTriangle className="size-4 text-amber-700" aria-hidden />
            <AlertTitle>Предупреждения — не блокируют импорт ({int(report.warning_count)})</AlertTitle>
            <AlertDescription>
              <ul className="w-full space-y-2">
                {warningGroups.map(([code, list]) => (
                  <li key={code}>
                    <div className="font-medium text-foreground">{issueTitle(code)}{list.length > 1 ? ` · ${list.length}` : ""}</div>
                    <ul className="list-disc pl-4">
                      {list.slice(0, 10).map((w, i) => (
                        <li key={i}>{w.row !== null && `${where(w.row)}: `}{w.message}{w.suggestion ? ` ${w.suggestion}` : ""}</li>
                      ))}
                      {list.length > 10 && <li>…и ещё {list.length - 10}</li>}
                    </ul>
                  </li>
                ))}
              </ul>
            </AlertDescription>
          </Alert>
        )}

        {groups.length > 0 && (
          <div>
            <h3 className="mb-2 flex items-center gap-2 text-sm font-medium">Что исправить <Badge variant="destructive">блокирует импорт</Badge></h3>
            <ul className="space-y-2" data-testid="issue-groups">
              {shown.map((gr) => (
                <li key={String(gr.row)} className="rounded-lg border p-3 text-sm">
                  <div className="mb-1 font-semibold">{gr.row === null ? "Файл целиком" : where(gr.row)}
                    {gr.issues.length > 1 && <span className="font-normal text-muted-foreground"> · проблем: {gr.issues.length}</span>}
                  </div>
                  <ul className="space-y-1.5">
                    {(gr.issues as Issue[]).map((e, i) => {
                      const col = columnLabel(e.column);
                      const src = cfg.mapped.find((m) => m.field === e.column);
                      return (
                        <li key={i}>
                          <span className="font-medium">{issueTitle(e.code)}</span>
                          {e.source_column && <> · столбец {e.source_column}</>}
                          {col && <> · {col.label}{src && !e.source_column ? <> (столбец {src.letter} «{src.header}»)</> : src ? <> «{src.header}»</> : null}</>}
                          {e.count && e.count > 1 ? <span className="text-muted-foreground"> · ×{e.count}</span> : null}
                          <div className="text-muted-foreground">{e.message}</div>
                          {e.value && <div className="text-xs">Значение: <code className="rounded bg-muted px-1">{e.value}</code></div>}
                          {e.suggestion && <div className="text-xs text-muted-foreground">Что сделать: {e.suggestion}</div>}
                        </li>
                      );
                    })}
                  </ul>
                </li>
              ))}
            </ul>
            {pages > 1 && (
              <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-sm text-muted-foreground">
                <span>Строки {page * PAGE + 1}–{Math.min(groups.length, (page + 1) * PAGE)} из {groups.length} в списке</span>
                <span className="flex gap-2">
                  <Button size="sm" variant="outline" disabled={page === 0} onClick={() => setPage(page - 1)}>Назад</Button>
                  <Button size="sm" variant="outline" disabled={page >= pages - 1} onClick={() => setPage(page + 1)}>Далее</Button>
                </span>
              </div>
            )}
            {!summary.rowsExact && (
              <p className="mt-2 text-xs text-muted-foreground">Показаны первые {report.errors.length} из {int(report.error_count)} ошибок.</p>
            )}
            <details className="mt-3 rounded-lg border text-sm">
              <summary className="cursor-pointer rounded-lg px-3 py-2 outline-none focus-visible:ring-2 focus-visible:ring-ring">Технические сведения (коды проверок)</summary>
              <div className="flex flex-wrap gap-2 px-3 pb-3" data-testid="error-codes">
                {Object.entries(report.error_counts).map(([code, n]) => <Badge key={code} variant="outline" className="font-mono text-[11px]">{code}: {n}</Badge>)}
                {Object.entries(report.warning_counts).map(([code, n]) => <Badge key={code} variant="outline" className="font-mono text-[11px] text-muted-foreground">{code}: {n} (предупр.)</Badge>)}
              </div>
            </details>
          </div>
        )}

        {report.ok && cols.length > 0 && (
          <div>
            <h3 className="mb-2 text-sm font-medium">Предпросмотр (первые {report.preview.length} записей после преобразования, со ссылкой на источник)</h3>
            <div className="max-h-80 overflow-auto rounded-lg border" role="region" aria-label="Предпросмотр записей" tabIndex={0}>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead scope="col">Строка</TableHead>
                    {cols.map((k) => (
                      <TableHead key={k} scope="col" className="min-w-28 whitespace-normal text-xs">
                        {k === "source_column" ? "Столбец источника" : importFieldLabel(k)}
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {report.preview.map((r, i) => (
                    <TableRow key={i}>
                      <TableCell className="text-muted-foreground">{String(r.row)}</TableCell>
                      {cols.map((k) => <TableCell key={k} className="text-xs">{r[k] === null || r[k] === undefined ? "—" : String(r[k])}</TableCell>)}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        )}

        {!done && (
          <div className="flex flex-wrap items-center gap-2 border-t pt-4">
            <Button onClick={onCommit} disabled={!report.ok || committing} data-testid="commit-button">
              {committing && <Loader2 className="size-4 animate-spin" aria-hidden />}
              6. Подтвердить импорт ({int(c?.eligible ?? report.valid_rows)} {isDataset ? "строк" : "записей"})
            </Button>
            <Button variant="outline" onClick={onDiscard} disabled={committing}>Отменить</Button>
            {report.ok && report.warning_count > 0 && <span className="text-xs text-muted-foreground">Подтверждая, вы принимаете изменения из предупреждений выше.</span>}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function SuccessPanel({ children }: { children: React.ReactNode }) {
  return (
    <Alert className="border-success/40 bg-success/5" data-testid="import-success">
      <CheckCircle2 className="size-4 text-success" />
      <AlertTitle>Данные импортированы</AlertTitle>
      <AlertDescription>{children}</AlertDescription>
    </Alert>
  );
}
