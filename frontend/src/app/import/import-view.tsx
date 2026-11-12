"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { AlertTriangle, CheckCircle2, Download, FileSpreadsheet, Loader2, UploadCloud, XCircle } from "lucide-react";
import Link from "next/link";
import { useMemo, useRef, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";

import { useMeta } from "@/components/meta-provider";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useApi } from "@/hooks/use-api";
import { api, ApiError, uploadFile } from "@/lib/api";
import { dateTime, int } from "@/lib/format";
import { columnLabel, groupByRow, issueTitle, summarizeErrors } from "@/lib/import-issues";
import {
  initialMapping,
  type Mapping,
  remapAfterHeaderChange,
  requiredResolved,
  sharedChoices,
  validatePayload,
} from "@/lib/import-wizard";
import { MAX_UPLOAD_MB, uploadSchema, type UploadForm } from "@/lib/schemas";
import type {
  ConfigIssue,
  FieldChoice,
  GuidedValidation,
  ImportBatch,
  ImportSource,
  SheetInspection,
  ValidationIssue,
} from "@/lib/types";
import { cn } from "@/lib/utils";

import { HeaderStep, MappingStep, SheetStep } from "./guided-steps";

const PAGE = 20;
const SCHEMA_DOC: [string, string, boolean][] = [
  ["student_id", "Анонимный идентификатор ученика (без ФИО)", true],
  ["grade", "Параллель, 1–12", true],
  ["class", "Класс, например 7А", true],
  ["subject", "Предмет", true],
  ["topic_id / topic_name", "Код и название темы", true],
  ["assessment_id", "Код оценивания", true],
  ["assessment_type", "pre (входная), post (итоговая), current (текущая)", true],
  ["assessment_date", "Дата ГГГГ-ММ-ДД или ДД.ММ.ГГГГ", true],
  ["score / max_score", "Набранный и максимальный балл (max > 0, 0 ≤ score ≤ max)", true],
  ["textbook_id", "Код учебника (столбец обязателен, значение может быть пустым)", true],
  ["item_id", "Код задания — для данных на уровне заданий", false],
  ["comparison_group", "Связывает pre и post для расчёта прироста", false],
  ["teaching_hours", "Часы на тему в классе", false],
  ["topic_min_hours / topic_max_hours / topic_priority / topic_prerequisites / topic_order", "Ограничения для оптимизатора", false],
  ["school / textbook_name", "Код школы и название учебника", false],
];

type Phase = "idle" | "uploading" | "inspecting" | "ready" | "validating" | "committing" | "done";
const STEPS = ["Файл", "Лист", "Заголовок", "Сопоставление", "Проверка", "Импорт"] as const;

export function ImportView() {
  const meta = useMeta();
  const history = useApi<ImportBatch[]>("/api/imports");
  const [phase, setPhase] = useState<Phase>("idle");
  const [progress, setProgress] = useState(0);
  const [source, setSource] = useState<ImportSource | null>(null);
  const [sheet, setSheet] = useState<string | null>(null);
  const [inspection, setInspection] = useState<SheetInspection | null>(null);
  const [mapping, setMapping] = useState<Mapping>({});
  const [confirmShared, setConfirmShared] = useState(false);
  const [report, setReport] = useState<GuidedValidation | null>(null);
  const [configIssues, setConfigIssues] = useState<ConfigIssue[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [result, setResult] = useState<{ inserted_rows: number; skipped_rows: number } | null>(null);
  const [page, setPage] = useState(0);
  const [prepOpen, setPrepOpen] = useState(true);
  const requestSeq = useRef(0);

  const form = useForm<UploadForm>({ resolver: zodResolver(uploadSchema) });
  const fileError = form.formState.errors.file?.message;
  const selectedFile = useWatch({ control: form.control, name: "file" });

  const busy = phase === "uploading" || phase === "inspecting" || phase === "validating" || phase === "committing";
  const shared = source ? sharedChoices(source.fields, mapping) : [];
  const resolved = source ? requiredResolved(source.fields, mapping) : false;
  const blockingNotice = inspection?.notices.some((n) => n.severity === "error") ?? false;
  const canValidate = !!source && !!sheet && !!inspection?.header_row && resolved && (shared.length === 0 || confirmShared) && !busy;

  function reset() {
    setSource(null);
    setSheet(null);
    setInspection(null);
    setMapping({});
    setConfirmShared(false);
    setReport(null);
    setConfigIssues([]);
    setPage(0);
  }

  /** Any change of sheet, header row, mapping or shared values makes an earlier validation unusable. */
  function invalidate(reason: string) {
    setConfigIssues([]);
    if (report) setNotice(`Предпросмотр устарел после изменения: ${reason}. Проверьте данные снова.`);
    setReport(null);
    setPage(0);
  }

  function handleLifecycleError(e: unknown, fallback: string) {
    const err = e instanceof ApiError ? e : new ApiError(fallback, 0);
    if (err.status === 410 || err.status === 404 || err.status === 403) {
      // The preview is gone (expired, discarded or not ours): start over with a clear explanation.
      reset();
      setPhase("idle");
    }
    setError(err);
  }

  async function runValidate(src: ImportSource, sheetName: string, headerRow: number, m: Mapping, confirm: boolean) {
    setPhase("validating");
    setError(null);
    setNotice(null);
    setConfigIssues([]);
    try {
      const r = await api.post<GuidedValidation>(`/api/imports/${src.batch_id}/validate`,
        validatePayload(src.session_key, sheetName, headerRow, m, confirm));
      setReport(r);
      setPage(0);
      setPhase("ready");
    } catch (e) {
      if (e instanceof ApiError && e.code === "INVALID_CONFIGURATION") {
        setConfigIssues(e.issues);
        setPrepOpen(true);
        setNotice("Проверка не выполнена: сопоставление не завершено. Исправьте отмеченные поля.");
        setPhase("ready");
        return;
      }
      setPhase("ready");
      handleLifecycleError(e, "Ошибка проверки.");
    }
  }

  const onSubmit = form.handleSubmit(async ({ file }) => {
    if (source) void discardQuietly(source);
    reset();
    setError(null);
    setNotice(null);
    setResult(null);
    setPhase("uploading");
    setProgress(0);
    try {
      const src = await uploadFile<ImportSource>("/api/imports/sources", file, setProgress);
      const m = initialMapping(src.inspection);
      setSource(src);
      setSheet(src.sheet_suggestion.name);
      setInspection(src.inspection);
      setMapping(m);
      setPrepOpen(!src.auto_ready);
      if (src.auto_ready && src.inspection?.header_row && src.sheet_suggestion.name) {
        // Standard template: everything is unambiguous, so validation starts right away (nothing is saved).
        await runValidate(src, src.sheet_suggestion.name, src.inspection.header_row, m, false);
      } else {
        setPhase("ready");
      }
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError("Ошибка загрузки.", 0));
      setPhase("idle");
    }
  });

  async function inspect(sheetName: string, headerRow: number | null): Promise<SheetInspection | null> {
    if (!source) return null;
    const seq = ++requestSeq.current;
    setPhase("inspecting");
    setError(null);
    try {
      const r = await api.post<{ inspection: SheetInspection }>(`/api/imports/${source.batch_id}/inspect`,
        { session_key: source.session_key, sheet: sheetName, header_row: headerRow });
      if (seq !== requestSeq.current) return null; // a newer selection superseded this response
      setPhase("ready");
      return r.inspection;
    } catch (e) {
      if (seq === requestSeq.current) {
        setPhase("ready");
        handleLifecycleError(e, "Не удалось прочитать лист.");
      }
      return null;
    }
  }

  async function chooseSheet(name: string) {
    if (name === sheet) return;
    setSheet(name);
    setInspection(null);
    setMapping({});
    setConfirmShared(false);
    invalidate("выбран другой лист");
    const ins = await inspect(name, null);
    if (ins) {
      setInspection(ins);
      setMapping(initialMapping(ins));
    }
  }

  async function chooseHeader(row: number) {
    if (!sheet || !inspection || row === inspection.header_row) return;
    invalidate("изменена строка заголовка");
    const before = inspection;
    const ins = await inspect(sheet, row);
    if (ins) {
      setInspection(ins);
      setMapping((m) => remapAfterHeaderChange(m, before, ins));
    }
  }

  function changeField(field: string, choice: FieldChoice | undefined) {
    setMapping((m) => ({ ...m, [field]: choice }));
    if (choice?.source === "value" || mapping[field]?.source === "value") setConfirmShared(false);
    invalidate("изменено сопоставление");
  }

  async function commit() {
    if (!source || !report) return;
    setPhase("committing");
    setError(null);
    try {
      const r = await api.post<{ inserted_rows: number; skipped_rows: number }>(`/api/imports/${source.batch_id}/commit`,
        { session_key: source.session_key, config_hash: report.config_hash });
      setResult(r);
      setPhase("done");
      toast.success(`Импортировано записей: ${int(r.inserted_rows)}`);
      meta.reload();
      history.reload();
    } catch (e) {
      setPhase("ready");
      if (e instanceof ApiError && e.code === "STALE_PREVIEW") {
        setReport(null);
        setNotice(e.message);
        return;
      }
      handleLifecycleError(e, "Ошибка импорта.");
    }
  }

  async function discardQuietly(src: ImportSource) {
    try {
      await api.post(`/api/imports/${src.batch_id}/discard`, { session_key: src.session_key });
    } catch {
      /* already committed, discarded or expired — nothing to undo */
    }
  }

  async function cancel() {
    if (source) await discardQuietly(source);
    toast.info("Импорт отменён — данные не сохранены.");
    reset();
    setNotice(null);
    setError(null);
    setPhase("idle");
    form.reset();
    history.reload();
  }

  const stepIndex = phase === "done" ? 5 : report ? 4 : inspection?.header_row ? 3 : sheet ? 2 : source ? 1 : 0;
  const showSheetStep = !!source && (source.kind === "xlsx" && (source.sheets.length > 1 || !sheet));

  return (
    <div className="space-y-6">
      <ol className="flex flex-wrap gap-x-4 gap-y-1 text-sm" aria-label="Шаги импорта" data-testid="import-steps">
        {STEPS.map((s, i) => (
          <li key={s} aria-current={i === stepIndex ? "step" : undefined}
            className={cn("flex items-center gap-1.5", i === stepIndex ? "font-semibold text-foreground" : i < stepIndex ? "text-foreground" : "text-muted-foreground")}>
            <span className={cn("flex size-5 items-center justify-center rounded-full border text-[11px]", i <= stepIndex && "border-primary bg-primary text-primary-foreground")} aria-hidden>{i + 1}</span>
            {s}
          </li>
        ))}
      </ol>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>1. Загрузка файла</CardTitle>
            <CardDescription>
              CSV (UTF-8 или Windows-1251, разделитель «,» или «;») либо Excel .xlsx, до {MAX_UPLOAD_MB} МБ. Дальше вы выберете
              лист и строку заголовка и сопоставите столбцы. В базу ничего не записывается до подтверждения.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={onSubmit} className="space-y-4" noValidate>
              <label
                htmlFor="file"
                className={cn(
                  "flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors hover:border-primary/50 hover:bg-accent/40 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring",
                  fileError && "border-danger/50",
                )}
              >
                <UploadCloud className="mb-2 size-8 text-primary" aria-hidden />
                <span className="font-medium break-all">{selectedFile?.name ?? "Выберите файл .csv или .xlsx"}</span>
                <span id="file-hint" className="mt-1 text-xs text-muted-foreground">Нажмите, чтобы выбрать файл</span>
                <input
                  id="file"
                  type="file"
                  accept=".csv,.xlsx"
                  className="sr-only"
                  data-testid="file-input"
                  disabled={busy}
                  aria-invalid={!!fileError}
                  aria-describedby={fileError ? "file-error" : "file-hint"}
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) form.setValue("file", f, { shouldValidate: true });
                  }}
                />
              </label>
              {fileError && <p id="file-error" className="text-sm text-danger" role="alert">{fileError}</p>}
              {phase === "uploading" && (
                <div className="space-y-1" aria-live="polite">
                  <Progress value={progress} aria-label="Загрузка файла" />
                  <p className="text-xs text-muted-foreground">
                    {progress < 100 ? `Загрузка: ${progress}%` : "Чтение листов и поиск заголовка…"}
                  </p>
                </div>
              )}
              <Button type="submit" disabled={busy || !selectedFile} data-testid="validate-button">
                {phase === "uploading" ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <FileSpreadsheet className="size-4" aria-hidden />}
                {source ? "Загрузить другой файл" : "Проверить файл"}
              </Button>
            </form>
            {error && (
              <Alert variant="destructive" className="mt-4" data-testid="import-error">
                <XCircle className="size-4" />
                <AlertTitle>{error.status === 410 ? "Предпросмотр устарел — загрузите файл заново" : error.message}</AlertTitle>
                {error.status === 410 && <AlertDescription>{error.message}</AlertDescription>}
                {error.details.length > 0 && <AlertDescription>{error.details.join("; ")}</AlertDescription>}
              </Alert>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Шаблоны</CardTitle>
            <CardDescription>Начните с шаблона, примера книги Excel или синтетического демонстрационного набора.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Button asChild variant="outline" className="w-full justify-start">
              <a href="/api/imports/template.csv" download><Download className="size-4" /> Шаблон CSV</a>
            </Button>
            <Button asChild variant="outline" className="h-auto w-full justify-start py-1.5 text-left whitespace-normal">
              <a href="/api/imports/example-workbook.xlsx" download data-testid="example-download">
                <Download className="size-4 shrink-0" /> Пример Excel (русские заголовки)
              </a>
            </Button>
            <Button asChild variant="outline" className="w-full justify-start">
              <a href="/api/imports/demo-dataset.csv" download data-testid="demo-download">
                <Download className="size-4" /> Демо-набор (синтетический)
              </a>
            </Button>
            <p className="text-xs text-muted-foreground">
              Все примеры полностью сгенерированы и помечены как синтетические. Они не описывают реальную школу.
            </p>
          </CardContent>
        </Card>
      </div>

      <p className="sr-only" aria-live="polite" role="status">
        {phase === "inspecting" ? "Чтение листа…" : phase === "validating" ? "Проверка записей…" : phase === "committing" ? "Сохранение данных…" : notice ?? ""}
      </p>

      {source && phase !== "done" && (
        <Card data-testid="prepare-panel">
          <CardHeader>
            <CardTitle className="flex flex-wrap items-center gap-2">
              2–4. Как читать файл
              {source.auto_ready && <Badge variant="secondary">распознан шаблон — всё выбрано автоматически</Badge>}
            </CardTitle>
            <CardDescription className="break-words">
              {source.filename}{sheet && source.kind === "xlsx" ? ` · лист «${sheet}»` : ""}
              {inspection?.header_row ? ` · заголовок в строке ${inspection.header_row}` : ""}. Предпросмотр действует до{" "}
              {dateTime(source.expires_at)}.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <details open={prepOpen} onToggle={(e) => setPrepOpen((e.target as HTMLDetailsElement).open)} className="space-y-5">
              <summary className="mb-3 cursor-pointer rounded-md text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring" data-testid="prepare-toggle">
                {prepOpen ? "Скрыть настройки листа, заголовка и столбцов" : "Показать и изменить лист, заголовок и сопоставление столбцов"}
              </summary>
              <div className="space-y-6">
                {showSheetStep && (
                  <SheetStep sheets={source.sheets} selected={sheet} suggestion={source.sheet_suggestion} disabled={busy} onSelect={chooseSheet} />
                )}
                {phase === "inspecting" && !inspection && (
                  <p className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" aria-hidden /> Чтение листа…</p>
                )}
                {inspection?.problem && (
                  <Alert variant="destructive"><XCircle className="size-4" /><AlertTitle>Лист не может быть импортирован</AlertTitle><AlertDescription>{inspection.problem}</AlertDescription></Alert>
                )}
                {inspection && !inspection.problem && (
                  <>
                    <section aria-labelledby="hdr-title" className="space-y-2">
                      <h3 id="hdr-title" className="text-sm font-semibold">Строка заголовка и предпросмотр</h3>
                      <HeaderStep inspection={inspection} disabled={busy} onChange={chooseHeader} />
                    </section>
                    {inspection.notices.length > 0 && (
                      <div className="space-y-2" data-testid="layout-notices">
                        {inspection.notices.map((n) => (
                          <Alert key={n.code} variant={n.severity === "error" ? "destructive" : "default"} className={n.severity === "warning" ? "border-warning/50 bg-warning/10" : undefined}>
                            <AlertTriangle className="size-4" aria-hidden />
                            <AlertTitle>{n.severity === "error" ? "Структура таблицы не поддерживается" : "Проверьте структуру таблицы"}</AlertTitle>
                            <AlertDescription>
                              <p>{n.message}</p>
                              <p>Ожидается: одна строка — результат одного ученика по одной теме (или заданию) одного оценивания. См. «Шаблон CSV» и «Пример Excel».</p>
                            </AlertDescription>
                          </Alert>
                        ))}
                      </div>
                    )}
                    {inspection.header_row !== null && (
                      <section aria-labelledby="map-title" className="space-y-2">
                        <h3 id="map-title" className="text-sm font-semibold">Сопоставление столбцов с полями приложения</h3>
                        <p className="text-xs text-muted-foreground">
                          Предложения основаны только на названиях столбцов и не применяются, если подходит несколько вариантов.
                          Проверьте примеры значений: «Оценка» может быть отметкой, а не баллом; ФИО не является идентификатором ученика.
                        </p>
                        <MappingStep fields={source.fields} inspection={inspection} mapping={mapping} issues={configIssues} disabled={busy} onChange={changeField} />
                      </section>
                    )}
                  </>
                )}
              </div>
            </details>

            {shared.length > 0 && (
              <div className="mt-4 rounded-lg border border-primary/30 bg-primary/5 p-3 text-sm" data-testid="shared-confirm">
                <p className="font-medium">Значения, заданные вручную для всего файла</p>
                <ul className="my-1 list-disc pl-5">
                  {shared.map((s) => <li key={s.field}>{s.label}: <strong>{s.value.trim() || "—"}</strong></li>)}
                </ul>
                <label className="flex items-start gap-2">
                  <input type="checkbox" className="mt-1" checked={confirmShared} disabled={busy}
                    onChange={(e) => { setConfirmShared(e.target.checked); invalidate("изменено подтверждение значений"); }}
                    data-testid="confirm-shared" />
                  <span>Подтверждаю: эти значения верны для всех строк с данными в выбранном листе.</span>
                </label>
              </div>
            )}

            <div className="mt-4 flex flex-wrap items-center gap-2 border-t pt-4">
              <Button onClick={() => source && sheet && inspection?.header_row && runValidate(source, sheet, inspection.header_row, mapping, confirmShared)}
                disabled={!canValidate} data-testid="run-validation" aria-describedby="validate-hint">
                {phase === "validating" && <Loader2 className="size-4 animate-spin" aria-hidden />}
                {report ? "Проверить снова" : "Проверить данные"}
              </Button>
              <Button variant="outline" onClick={cancel} disabled={phase === "committing"} data-testid="cancel-import">Отменить</Button>
              <span id="validate-hint" className="text-xs text-muted-foreground">
                {!sheet ? "Выберите лист." : !inspection?.header_row ? "Выберите строку заголовка."
                  : !resolved ? "Сопоставьте все обязательные поля." : shared.length > 0 && !confirmShared
                    ? "Подтвердите значения, заданные вручную." : blockingNotice ? "Структура таблицы требует исправления; проверка покажет затронутые строки." : "Проверка не изменяет данные."}
              </span>
            </div>
            {notice && !report && (
              <p className="mt-3 rounded-md border border-warning/50 bg-warning/10 p-2 text-sm" data-testid="stale-notice">{notice}</p>
            )}
          </CardContent>
        </Card>
      )}

      {report && source && (
        <ValidationPanel report={report} source={source} page={page} setPage={setPage} phase={phase} onCommit={commit} onDiscard={cancel} />
      )}

      {phase === "done" && result && (
        <Alert className="border-success/40 bg-success/5" data-testid="import-success">
          <CheckCircle2 className="size-4 text-success" />
          <AlertTitle>Данные импортированы</AlertTitle>
          <AlertDescription>
            <p>Добавлено записей: {int(result.inserted_rows)}{result.skipped_rows ? `, пропущено уже загруженных: ${int(result.skipped_rows)}` : ""}.</p>
            <div className="mt-2 flex flex-wrap gap-2">
              <Button asChild size="sm"><Link href="/">Открыть обзор</Link></Button>
              <Button asChild size="sm" variant="outline"><Link href="/topics">Анализ тем</Link></Button>
            </div>
          </AlertDescription>
        </Alert>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Схема данных</CardTitle>
            <CardDescription>
              Одна строка — балл одного ученика по одной теме (или заданию) одного оценивания. Таблицы, где каждая тема записана
              в отдельном столбце, и печатные отчёты нужно сначала привести к этому виду.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow><TableHead>Поле</TableHead><TableHead>Описание</TableHead><TableHead className="w-28">Обязательно</TableHead></TableRow>
              </TableHeader>
              <TableBody>
                {SCHEMA_DOC.map(([c, d, req]) => (
                  <TableRow key={c}>
                    <TableCell className="font-mono text-xs whitespace-normal">{c}</TableCell>
                    <TableCell className="text-sm whitespace-normal">{d}</TableCell>
                    <TableCell>{req ? <Badge>да</Badge> : <Badge variant="outline">нет</Badge>}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>История импорта</CardTitle></CardHeader>
          <CardContent>
            {history.data?.length ? (
              <ul className="space-y-2 text-sm">
                {history.data.map((b) => (
                  <li key={b.id} className="flex items-center justify-between gap-2 rounded-md border p-2">
                    <span className="min-w-0">
                      <span className="block truncate font-medium">{b.filename}</span>
                      <span className="text-xs text-muted-foreground">{dateTime(b.created_at)} · {int(b.total_rows)} записей</span>
                    </span>
                    <Badge variant={b.status === "committed" ? "default" : "outline"}>
                      {b.status === "committed" ? "импорт" : b.status === "preview" ? "проверка" : b.status === "expired" ? "истёк" : "отменён"}
                    </Badge>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">Загрузок пока не было.</p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

export function ValidationPanel({ report, source, page, setPage, phase, onCommit, onDiscard }: {
  report: GuidedValidation;
  source: ImportSource;
  page: number;
  setPage: (n: number) => void;
  phase: Phase;
  onCommit: () => void;
  onDiscard: () => void;
}) {
  const s = report.summary;
  const cfg = report.config;
  const groups = useMemo(() => groupByRow(report.errors), [report]);
  const warningGroups = useMemo(() => {
    const m = new Map<string, ValidationIssue[]>();
    for (const w of report.warnings) m.set(w.code, [...(m.get(w.code) ?? []), w]);
    return [...m.entries()];
  }, [report]);
  const summary = summarizeErrors(report);
  const pages = Math.max(1, Math.ceil(groups.length / PAGE));
  const shown = groups.slice(page * PAGE, page * PAGE + PAGE);
  const cols = useMemo(() => (report.preview[0] ? Object.keys(report.preview[0]).filter((k) => k !== "row") : []), [report]);
  const done = phase === "done";
  const where = (row: number) => (source.kind === "xlsx" ? `Лист «${cfg.sheet}», строка ${row}` : `Строка ${row}`);
  const validated = report.records_validated !== false;
  const withErrors = report.rows_with_errors ?? 0;
  const alreadyImported = report.warnings.find((w) => w.code === "ALREADY_IMPORTED");

  return (
    <Card data-testid="import-preview">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          {report.ok ? <CheckCircle2 className="size-5 text-success" aria-hidden /> : <XCircle className="size-5 text-danger" aria-hidden />}
          5. {report.ok ? "Файл прошёл проверку" : "В файле есть ошибки — данные ещё не импортированы"}
        </CardTitle>
        <CardDescription className="break-words">
          {source.filename}{source.kind === "xlsx" ? `, лист «${cfg.sheet}»` : ""}, заголовок — строка {cfg.header_row}.{" "}
          {report.ok ? "Ничего не сохранено до подтверждения." : "Данные не исправляются автоматически."}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3 lg:grid-cols-5" data-testid="record-counts">
          {([
            ["Найдено записей", validated ? int(report.total_rows) : "не проверены"],
            ["Без ошибок", validated ? int(Math.max(0, report.total_rows - withErrors)) : "—"],
            ["С ошибками", validated ? int(withErrors) : "—"],
            ["Предупреждений", int(report.warning_count)],
            ["Будет импортировано", report.ok ? int(report.valid_rows) : "0 — импорт заблокирован"],
          ] as [string, string][]).map(([k, v]) => (
            <div key={k} className="rounded-lg bg-muted/60 p-2.5">
              <dt className="text-xs text-muted-foreground">{k}</dt>
              <dd className="font-semibold">{v}</dd>
            </div>
          ))}
        </dl>
        {!validated && (
          <p className="text-sm text-muted-foreground">Проверка остановилась на структуре таблицы, поэтому отдельные записи ещё не проверялись.</p>
        )}

        {!report.ok && (
          <div role="alert" className="rounded-lg border border-danger/30 bg-danger/5 p-3" data-testid="import-error-summary">
            <p className="font-medium">{summary.headline}</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Исправьте указанные строки в исходной таблице (номера строк — как в файле) или сопоставление столбцов и проверьте
              снова. Значения идентификаторов не показываются, чтобы не раскрывать возможные персональные данные.
            </p>
          </div>
        )}

        {report.ok && (
          <section aria-labelledby="confirm-title" className="rounded-lg border p-3 text-sm" data-testid="confirm-summary">
            <h3 id="confirm-title" className="mb-2 font-medium">Что будет импортировано</h3>
            <dl className="grid gap-x-4 gap-y-1 sm:grid-cols-[max-content_minmax(0,1fr)]">
              <dt className="text-muted-foreground">Файл</dt><dd className="break-words">{source.filename}</dd>
              {source.kind === "xlsx" && (<><dt className="text-muted-foreground">Лист</dt><dd className="break-words">{cfg.sheet}{cfg.sheet_hidden ? " (скрытый)" : ""}</dd></>)}
              <dt className="text-muted-foreground">Строка заголовка</dt><dd>{cfg.header_row}</dd>
              <dt className="text-muted-foreground">Записей</dt><dd>{int(report.valid_rows)}{alreadyImported ? " (часть уже загружена и будет пропущена)" : ""}</dd>
              <dt className="text-muted-foreground">Учеников / классов / тем / оцениваний</dt>
              <dd>{s.students ?? "—"} / {s.classes ?? "—"} / {s.topics ?? "—"} / {s.assessments ?? "—"}</dd>
              <dt className="text-muted-foreground">Период</dt><dd>{s.date_from} — {s.date_to}</dd>
              <dt className="text-muted-foreground">Значения для всего файла</dt>
              <dd>{cfg.shared.length ? cfg.shared.map((x) => `${x.label}: ${x.value}`).join("; ") : "нет"}</dd>
              {cfg.not_in_file.length > 0 && (<><dt className="text-muted-foreground">Нет в файле</dt><dd>{cfg.not_in_file.map((x) => x.label).join(", ")}</dd></>)}
              <dt className="text-muted-foreground">Игнорируемые столбцы</dt>
              <dd className="break-words">{cfg.ignored_columns.length ? cfg.ignored_columns.join(", ") : "нет"}</dd>
            </dl>
            <details className="mt-2">
              <summary className="cursor-pointer text-xs text-muted-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring">Сопоставление столбцов</summary>
              <ul className="mt-1 text-xs">
                {cfg.mapped.map((x) => <li key={x.field}>{x.label} ← {x.letter} «{x.header}»</li>)}
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
                        <li key={i}>{w.row !== null && `${where(w.row)}: `}{w.message}</li>
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
            <h3 className="mb-2 flex items-center gap-2 text-sm font-medium">
              Что исправить <Badge variant="destructive">блокирует импорт</Badge>
            </h3>
            <ul className="space-y-2" data-testid="issue-groups">
              {shown.map((gr) => (
                <li key={String(gr.row)} className="rounded-lg border p-3 text-sm">
                  <div className="mb-1 font-semibold">{gr.row === null ? "Файл целиком" : where(gr.row)}
                    {gr.issues.length > 1 && <span className="font-normal text-muted-foreground"> · проблем: {gr.issues.length}</span>}
                  </div>
                  <ul className="space-y-1.5">
                    {gr.issues.map((e, i) => {
                      const col = columnLabel(e.column);
                      const src = cfg.mapped.find((m) => m.field === e.column);
                      return (
                        <li key={i}>
                          <span className="font-medium">{issueTitle(e.code)}</span>
                          {col && <> · {col.label}{src ? <> (столбец {src.letter} «{src.header}»)</> : <> <code className="rounded bg-muted px-1 text-xs">{col.header}</code></>}</>}
                          <div className="text-muted-foreground">{e.message}</div>
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
              <p className="mt-2 text-xs text-muted-foreground">
                Показаны первые {report.errors.length} из {int(report.error_count)} ошибок; остальные строки появятся после исправления.
              </p>
            )}
            <details className="mt-3 rounded-lg border text-sm">
              <summary className="cursor-pointer rounded-lg px-3 py-2 outline-none focus-visible:ring-2 focus-visible:ring-ring">
                Технические сведения (коды проверок)
              </summary>
              <div className="flex flex-wrap gap-2 px-3 pb-3" data-testid="error-codes">
                {Object.entries(report.error_counts).map(([code, n]) => (
                  <Badge key={code} variant="outline" className="font-mono text-[11px]">{code}: {n}</Badge>
                ))}
                {Object.entries(report.warning_counts).map(([code, n]) => (
                  <Badge key={code} variant="outline" className="font-mono text-[11px] text-muted-foreground">{code}: {n} (предупр.)</Badge>
                ))}
              </div>
            </details>
          </div>
        )}

        {report.ok && cols.length > 0 && (
          <div>
            <h3 className="mb-2 text-sm font-medium">Предпросмотр (первые {report.preview.length} записей после нормализации)</h3>
            <div className="max-h-80 overflow-auto rounded-lg border" role="region" aria-label="Предпросмотр записей" tabIndex={0}>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Строка</TableHead>
                    {cols.map((c) => <TableHead key={c} className="font-mono text-xs">{c}</TableHead>)}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {report.preview.map((r) => (
                    <TableRow key={String(r.row)}>
                      <TableCell className="text-muted-foreground">{String(r.row)}</TableCell>
                      {cols.map((c) => <TableCell key={c} className="text-xs">{r[c] === null ? "—" : String(r[c])}</TableCell>)}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        )}

        {!done && (
          <div className="flex flex-wrap items-center gap-2 border-t pt-4">
            <Button onClick={onCommit} disabled={!report.ok || phase === "committing"} data-testid="commit-button">
              {phase === "committing" && <Loader2 className="size-4 animate-spin" aria-hidden />}
              6. Подтвердить импорт ({int(report.valid_rows)} записей)
            </Button>
            <Button variant="outline" onClick={onDiscard} disabled={phase === "committing"}>Отменить</Button>
            {report.ok && report.warning_count > 0 && (
              <span className="text-xs text-muted-foreground">Подтверждая, вы принимаете изменения из предупреждений выше.</span>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
