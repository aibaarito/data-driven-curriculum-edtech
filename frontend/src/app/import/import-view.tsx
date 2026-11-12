"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Download, FileSpreadsheet, Loader2, UploadCloud, XCircle } from "lucide-react";
import Link from "next/link";
import { useRef, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";

import { CapabilityList } from "@/components/capabilities";
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
import {
  buildPayload,
  coveredByColumns,
  fieldsForLayout,
  initialPrep,
  type PrepState,
  prepProblems,
  prepReady,
  remapAfterHeaderChange,
  sharedChoices,
} from "@/lib/import-wizard";
import { MAX_UPLOAD_MB, uploadSchema, type UploadForm } from "@/lib/schemas";
import type {
  Capability,
  ConfigIssue,
  FieldChoice,
  GuidedValidation,
  ImportBatch,
  ImportSource,
  Layout,
  RegionSelection,
  SheetInspection,
} from "@/lib/types";
import { cn } from "@/lib/utils";

import { HeaderStep, MappingStep, SheetStep } from "./guided-steps";
import { AggregateStep, CsvOptions, FlaggedRows, GeneralStep, LayoutStep, RegionOptions, RulesStep, WideResultsStep } from "./prepare-steps";
import { ReviewPanel, SuccessPanel } from "./review-panel";

const SCHEMA_DOC: [string, string, boolean][] = [
  ["student_id", "Анонимный идентификатор ученика (без ФИО)", true],
  ["grade", "Параллель, 1–12", true],
  ["class", "Класс, например 7А", true],
  ["subject", "Предмет", true],
  ["topic_id / topic_name", "Код и название темы", true],
  ["assessment_id", "Код оценивания", true],
  ["assessment_type", "pre (входная), post (итоговая), current (текущая)", true],
  ["assessment_date", "Дата; формат задаётся в правилах разбора", true],
  ["score / max_score", "Результат и максимальный балл (или проценты, верно/неверно, шкала — по правилу)", true],
  ["textbook_id", "Код учебника (можно явно отметить, что его нет)", true],
  ["item_id", "Код задания — для данных на уровне заданий", false],
  ["comparison_group", "Связывает pre и post для расчёта прироста", false],
  ["teaching_hours", "Часы на тему в классе (для оптимизатора)", false],
  ["topic_min_hours / topic_max_hours / topic_priority / topic_prerequisites / topic_order", "Ограничения для оптимизатора и карты программы", false],
  ["school / textbook_name", "Код школы и название учебника", false],
];

type Phase = "idle" | "uploading" | "inspecting" | "ready" | "validating" | "committing" | "done";
const STEPS = ["Файл", "Данные", "Структура", "Сопоставление", "Проверка", "Импорт", "Анализ"] as const;
type CsvOpts = { encoding: string; delimiter: string };
type CommitResult = { inserted_rows: number; skipped_rows: number; kind?: string; dataset_id?: number };

function regionFrom(ins: SheetInspection | null): RegionSelection | null {
  if (!ins || ins.header_row === null) return null;
  const s = ins.selection;
  return {
    header_row: ins.header_row, header_rows: (s?.header_rows ?? 1) as 1 | 2, first_col: s?.first_col ?? 0,
    last_col: s?.last_col ?? null, last_row: s?.last_row ?? null, exclude: s?.exclude ?? [],
  };
}

export function ImportView() {
  const meta = useMeta();
  const history = useApi<ImportBatch[]>("/api/imports");
  const [phase, setPhase] = useState<Phase>("idle");
  const [progress, setProgress] = useState(0);
  const [source, setSource] = useState<ImportSource | null>(null);
  const [sheet, setSheet] = useState<string | null>(null);
  const [csv, setCsv] = useState<CsvOpts>({ encoding: "auto", delimiter: "auto" });
  const [inspection, setInspection] = useState<SheetInspection | null>(null);
  const [region, setRegion] = useState<RegionSelection | null>(null);
  const [prep, setPrep] = useState<PrepState>(initialPrep(null));
  const [report, setReport] = useState<GuidedValidation | null>(null);
  const [configIssues, setConfigIssues] = useState<ConfigIssue[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [result, setResult] = useState<CommitResult | null>(null);
  const [afterCaps, setAfterCaps] = useState<Capability[] | null>(null);
  const [page, setPage] = useState(0);
  const [prepOpen, setPrepOpen] = useState(true);
  const requestSeq = useRef(0);

  const form = useForm<UploadForm>({ resolver: zodResolver(uploadSchema) });
  const fileError = form.formState.errors.file?.message;
  const selectedFile = useWatch({ control: form.control, name: "file" });

  const busy = phase === "uploading" || phase === "inspecting" || phase === "validating" || phase === "committing";
  const fields = source?.fields ?? [];
  const shared = (prep.layout === "long" || prep.layout === "wide") ? sharedChoices(fields, prep.mapping) : [];
  const problems = prepProblems(fields, prep, inspection, configIssues);
  const ready = !!source && !!sheet && !!region && !!inspection && !inspection.problem && prepReady(fields, prep, inspection);
  const canValidate = ready && !busy;

  function reset() {
    setSource(null);
    setSheet(null);
    setInspection(null);
    setRegion(null);
    setPrep(initialPrep(null));
    setReport(null);
    setConfigIssues([]);
    setCsv({ encoding: "auto", delimiter: "auto" });
    setPage(0);
  }

  /** Any change of data selection, structure, mapping or rules makes an earlier validation unusable. */
  function invalidate(reason: string) {
    setConfigIssues([]);
    if (report) setNotice(`Предпросмотр устарел после изменения: ${reason}. Проверьте данные снова.`);
    setReport(null);
    setPage(0);
  }

  function handleLifecycleError(e: unknown, fallback: string) {
    const err = e instanceof ApiError ? e : new ApiError(fallback, 0);
    if (err.status === 410 || err.status === 404 || err.status === 403) {
      reset();
      setPhase("idle");
    }
    setError(err);
  }

  async function runValidate(src: ImportSource, sheetName: string, r: RegionSelection, p: PrepState, c: CsvOpts) {
    setPhase("validating");
    setError(null);
    setNotice(null);
    setConfigIssues([]);
    try {
      const v = await api.post<GuidedValidation>(`/api/imports/${src.batch_id}/validate`, buildPayload(src.session_key, sheetName, c, r, p));
      setReport(v);
      setPage(0);
      setPhase("ready");
    } catch (e) {
      setPhase("ready");
      if (e instanceof ApiError && e.issues.length && (e.code === "INVALID_CONFIGURATION" || e.status === 413)) {
        setConfigIssues(e.issues);
        setPrepOpen(true);
        setNotice(e.status === 413 ? e.message : "Проверка не выполнена: настройки импорта не завершены. Исправьте отмеченные поля.");
        return;
      }
      handleLifecycleError(e, "Ошибка проверки.");
    }
  }

  const onSubmit = form.handleSubmit(async ({ file }) => {
    if (source) void discardQuietly(source);
    reset();
    setError(null);
    setNotice(null);
    setResult(null);
    setAfterCaps(null);
    setPhase("uploading");
    setProgress(0);
    try {
      const src = await uploadFile<ImportSource>("/api/imports/sources", file, setProgress);
      const p = initialPrep(src.inspection);
      const r = regionFrom(src.inspection);
      const c = src.csv_info ? { encoding: "auto", delimiter: "auto" } : csv;
      setSource(src);
      setSheet(src.sheet_suggestion.name);
      setInspection(src.inspection);
      setRegion(r);
      setPrep(p);
      setPrepOpen(!src.auto_ready);
      if (src.auto_ready && r && src.sheet_suggestion.name) {
        // Standard template: everything is unambiguous, so validation starts right away (nothing is saved).
        await runValidate(src, src.sheet_suggestion.name, r, p, c);
      } else {
        setPhase("ready");
      }
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError("Ошибка загрузки.", 0));
      setPhase("idle");
    }
  });

  async function inspect(sheetName: string, r: Partial<RegionSelection> | null, c: CsvOpts): Promise<SheetInspection | null> {
    if (!source) return null;
    const seq = ++requestSeq.current;
    setPhase("inspecting");
    setError(null);
    try {
      const res = await api.post<{ inspection: SheetInspection }>(`/api/imports/${source.batch_id}/inspect`,
        { session_key: source.session_key, sheet: sheetName, csv: c, ...(r ?? {}) });
      if (seq !== requestSeq.current) return null;
      setPhase("ready");
      return res.inspection;
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
    setRegion(null);
    invalidate("выбран другой лист");
    const ins = await inspect(name, null, csv);
    if (ins) {
      setInspection(ins);
      setRegion(regionFrom(ins));
      setPrep(initialPrep(ins));
    }
  }

  async function changeCsv(next: CsvOpts) {
    if (!sheet) return;
    setCsv(next);
    invalidate("изменены параметры CSV");
    const ins = await inspect(sheet, null, next);
    if (ins) {
      setInspection(ins);
      setRegion(regionFrom(ins));
      setPrep(initialPrep(ins));
    }
  }

  /** Header row, two-row header or range changed: re-read columns; keep choices whose column header is unchanged. */
  async function changeRegion(patch: Partial<RegionSelection>) {
    if (!sheet || !region || !inspection) return;
    const next = { ...region, ...patch };
    if (patch.exclude && Object.keys(patch).length === 1) {
      setRegion(next);
      invalidate("изменён выбор исключаемых строк");
      return;
    }
    invalidate(patch.header_row ? "изменена строка заголовка" : "изменён диапазон или заголовок");
    const before = inspection;
    const ins = await inspect(sheet, next, csv);
    if (!ins) return;
    setInspection(ins);
    setRegion({ ...next, exclude: next.exclude.filter((k) => (ins.flag_counts ?? {})[k]) });
    const headerOf = (i: SheetInspection, id: string) => i.columns.find((c) => c.id === id)?.header;
    setPrep((p) => ({
      ...p,
      mapping: remapAfterHeaderChange(p.mapping, before, ins),
      resultColumns: p.resultColumns.filter((rc) => headerOf(before, rc.column) === headerOf(ins, rc.column) && headerOf(ins, rc.column) !== undefined),
      roles: Object.fromEntries(Object.entries(p.roles).filter(([c]) => headerOf(before, c) === headerOf(ins, c) && headerOf(ins, c) !== undefined)),
      types: { ...(ins.type_suggestion ?? {}), ...Object.fromEntries(Object.entries(p.types).filter(([c]) => headerOf(before, c) === headerOf(ins, c))) },
    }));
  }

  function updatePrep(patch: Partial<PrepState>, reason: string) {
    setPrep((p) => ({ ...p, ...patch }));
    invalidate(reason);
  }

  function changeLayout(layout: Layout) {
    if (layout === prep.layout) return;
    const base = initialPrep(inspection);
    const mapping = { ...prep.mapping };
    if (layout === "wide") for (const f of ["topic_id", "topic_name", "item_id", "score", "max_score"]) delete mapping[f];
    updatePrep({
      layout, mapping: layout === "long" ? { ...base.mapping, ...mapping } : mapping,
      resultColumns: prep.resultColumns.length ? prep.resultColumns : base.resultColumns,
    }, "изменена структура таблицы");
  }

  function changeField(field: string, choice: FieldChoice | undefined) {
    const wasShared = prep.mapping[field]?.source === "value";
    setPrep((p) => ({ ...p, mapping: { ...p.mapping, [field]: choice }, confirmShared: choice?.source === "value" || wasShared ? false : p.confirmShared }));
    invalidate("изменено сопоставление");
  }

  async function commit() {
    if (!source || !report) return;
    setPhase("committing");
    setError(null);
    try {
      const r = await api.post<CommitResult>(`/api/imports/${source.batch_id}/commit`, { session_key: source.session_key, config_hash: report.config_hash });
      setResult(r);
      setPhase("done");
      toast.success(r.kind === "assessment" || !r.kind ? `Импортировано записей: ${int(r.inserted_rows)}` : `Сохранён набор данных: ${int(r.inserted_rows)} строк`);
      meta.reload();
      history.reload();
      if (r.kind !== "general" && r.kind !== "aggregate") {
        try {
          setAfterCaps((await api.get<{ capabilities: Capability[] }>("/api/analytics/capabilities")).capabilities);
        } catch {
          setAfterCaps(null); /* the import itself succeeded; capabilities are informational */
        }
      }
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

  const stepIndex = phase === "done" ? 6 : report ? 4 : inspection?.header_row ? 3 : sheet ? 1 : source ? 1 : 0;
  const showSheetStep = !!source && source.kind === "xlsx" && (source.sheets.length > 1 || !sheet);
  const usedIdentity = new Set(Object.values(prep.mapping).flatMap((c) => (c?.source === "column" ? [c.column] : [])));
  const covered = coveredByColumns(prep);
  const mappingFields = fieldsForLayout(fields, prep.layout, prep.rules).map((f) => (prep.layout === "wide" && covered.has(f.field) ? { ...f, required: false } : f));
  // Flagged rows are decided in «Строки, требующие решения»; only structural hints are repeated here.
  const structureNotices = (inspection?.notices ?? []).filter((n) => n.severity !== "error" && !["TOTAL_ROWS", "NOTE_ROWS", "REPEATED_HEADER"].includes(n.code));
  const scoreColumns = prep.layout === "wide" ? prep.resultColumns.map((r) => r.column)
    : prep.mapping.score?.source === "column" ? [prep.mapping.score.column] : [];

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
              CSV (UTF-8 или Windows-1251; запятая, точка с запятой или табуляция) либо Excel .xlsx, до {MAX_UPLOAD_MB} МБ. Дальше вы выберете
              данные и структуру таблицы и сопоставите столбцы. В базу ничего не записывается до подтверждения; формулы и макросы не выполняются.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={onSubmit} className="space-y-4" noValidate>
              <label htmlFor="file" className={cn(
                "flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors hover:border-primary/50 hover:bg-accent/40 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring",
                fileError && "border-danger/50")}>
                <UploadCloud className="mb-2 size-8 text-primary" aria-hidden />
                <span className="font-medium break-all">{selectedFile?.name ?? "Выберите файл .csv или .xlsx"}</span>
                <span id="file-hint" className="mt-1 text-xs text-muted-foreground">Нажмите, чтобы выбрать файл</span>
                <input id="file" type="file" accept=".csv,.xlsx" className="sr-only" data-testid="file-input" disabled={busy}
                  aria-invalid={!!fileError} aria-describedby={fileError ? "file-error" : "file-hint"}
                  onChange={(e) => { const f = e.target.files?.[0]; if (f) form.setValue("file", f, { shouldValidate: true }); }} />
              </label>
              {fileError && <p id="file-error" className="text-sm text-danger" role="alert">{fileError}</p>}
              {phase === "uploading" && (
                <div className="space-y-1" aria-live="polite">
                  <Progress value={progress} aria-label="Загрузка файла" />
                  <p className="text-xs text-muted-foreground">{progress < 100 ? `Загрузка: ${progress}%` : "Чтение листов и поиск заголовка…"}</p>
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
            <CardTitle>Шаблоны и примеры</CardTitle>
            <CardDescription>Все примеры полностью синтетические и не описывают реальную школу.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Button asChild variant="outline" className="w-full justify-start">
              <a href="/api/imports/template.csv" download><Download className="size-4" /> Шаблон CSV</a>
            </Button>
            <Button asChild variant="outline" className="h-auto w-full justify-start py-1.5 text-left whitespace-normal">
              <a href="/api/imports/example-workbook.xlsx" download data-testid="example-download"><Download className="size-4 shrink-0" /> Пример Excel (русские заголовки)</a>
            </Button>
            <Button asChild variant="outline" className="w-full justify-start">
              <a href="/api/imports/demo-dataset.csv" download data-testid="demo-download"><Download className="size-4" /> Демо-набор (синтетический)</a>
            </Button>
            <p className="text-xs text-muted-foreground">
              Также поддерживаются журналы (ученик × столбцы тем), сводные таблицы по классам и темам и любые другие таблицы — для общего просмотра в разделе{" "}
              <Link href="/datasets" className="underline underline-offset-2">«Наборы данных»</Link>.
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
              {inspection?.header_row ? ` · заголовок в строке ${inspection.header_row}` : ""}. Предпросмотр действует до {dateTime(source.expires_at)}.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <details open={prepOpen} onToggle={(e) => setPrepOpen((e.target as HTMLDetailsElement).open)}>
              <summary className="mb-3 cursor-pointer rounded-md text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring" data-testid="prepare-toggle">
                {prepOpen ? "Скрыть настройки данных, структуры и столбцов" : "Показать и изменить данные, структуру и сопоставление"}
              </summary>
              <div className="space-y-8">
                <section aria-labelledby="data-title" className="space-y-4">
                  <h3 id="data-title" className="text-base font-semibold">2. Данные</h3>
                  {showSheetStep && <SheetStep sheets={source.sheets} selected={sheet} suggestion={source.sheet_suggestion} disabled={busy} onSelect={chooseSheet} />}
                  {source.kind === "csv" && source.csv_info && <CsvOptions info={source.csv_info} value={csv} disabled={busy} onChange={changeCsv} />}
                  {phase === "inspecting" && !inspection && (
                    <p className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" aria-hidden /> Чтение листа…</p>
                  )}
                  {inspection?.problem && (
                    <Alert variant="destructive"><XCircle className="size-4" /><AlertTitle>Лист не может быть импортирован</AlertTitle><AlertDescription>{inspection.problem}</AlertDescription></Alert>
                  )}
                  {inspection && !inspection.problem && (
                    <>
                      <HeaderStep inspection={inspection} disabled={busy} onChange={(row) => changeRegion({ header_row: row, header_rows: 1 })} />
                      {region && <RegionOptions key={`${sheet}-${region.header_row}`} inspection={inspection} region={region} disabled={busy} onChange={changeRegion} />}
                      {region && <FlaggedRows inspection={inspection} region={region} catalog={source.catalog} disabled={busy} onChange={(exclude) => changeRegion({ exclude })} />}
                      {inspection.notices.filter((n) => n.severity === "error").map((n) => (
                        <Alert key={n.code} variant="destructive"><XCircle className="size-4" /><AlertTitle>Нет данных для импорта</AlertTitle><AlertDescription>{n.message}</AlertDescription></Alert>
                      ))}
                    </>
                  )}
                </section>

                {inspection && !inspection.problem && region && (
                  <>
                    <section aria-labelledby="structure-title" className="space-y-3">
                      <h3 id="structure-title" className="text-base font-semibold">3. Структура</h3>
                      {structureNotices.length > 0 && (
                        <ul className="space-y-1 text-sm" data-testid="layout-notices">
                          {structureNotices.map((n) => <li key={n.code} className="rounded-md border border-warning/50 bg-warning/10 p-2">{n.message}</li>)}
                        </ul>
                      )}
                      <LayoutStep value={prep.layout} suggestion={inspection.layout_suggestion} disabled={busy} onChange={changeLayout} />
                    </section>

                    <section aria-labelledby="map-title" className="space-y-3">
                      <h3 id="map-title" className="text-base font-semibold">4. Сопоставление{prep.layout === "long" || prep.layout === "wide" ? " и правила" : ""}</h3>
                      {problems.general.length > 0 && (
                        <ul className="space-y-1 rounded-lg border border-danger/30 bg-danger/5 p-3 text-sm" data-testid="prep-problems" role="alert">
                          {problems.general.map((m, i) => <li key={i}>{m}</li>)}
                        </ul>
                      )}
                      {(prep.layout === "long" || prep.layout === "wide") && (
                        <MappingStep fields={mappingFields} inspection={inspection} mapping={prep.mapping} issues={configIssues} disabled={busy}
                          onChange={changeField} problemsOverride={problems.fields}
                          title={prep.layout === "wide" ? "Поля строки ученика. Тема, задание, результат и максимум задаются для столбцов результатов ниже." :
                            "Предложения основаны на названиях столбцов и примерах значений и не применяются, если подходит несколько вариантов. «Оценка» может быть отметкой, а не баллом; ФИО не является идентификатором ученика."} />
                      )}
                      {prep.layout === "wide" && (
                        <WideResultsStep inspection={inspection} results={prep.resultColumns} usedIdentity={usedIdentity} scoreMode={prep.rules.score_mode}
                          problems={problems.columns} disabled={busy} onChange={(resultColumns) => updatePrep({ resultColumns }, "изменены столбцы результатов")} />
                      )}
                      {prep.layout === "aggregate" && (
                        <AggregateStep inspection={inspection} catalog={source.catalog} roles={prep.roles} metric={prep.metric} name={prep.datasetName} disabled={busy}
                          onRoles={(roles) => updatePrep({ roles }, "изменены роли столбцов")} onMetric={(metric) => updatePrep({ metric }, "изменён показатель")}
                          onName={(datasetName) => updatePrep({ datasetName }, "изменено название")} />
                      )}
                      {prep.layout === "general" && (
                        <GeneralStep inspection={inspection} catalog={source.catalog} types={prep.types} name={prep.datasetName} disabled={busy}
                          onTypes={(types) => updatePrep({ types }, "изменены типы столбцов")} onName={(datasetName) => updatePrep({ datasetName }, "изменено название")} />
                      )}
                      {prep.layout !== "general" && (
                        <RulesStep rules={prep.rules} inspection={inspection} scoreColumns={scoreColumns} layout={prep.layout} disabled={busy}
                          onChange={(rules) => updatePrep({ rules }, "изменены правила чтения результатов")} />
                      )}
                    </section>
                  </>
                )}
              </div>
            </details>

            {shared.length > 0 && (
              <div className="mt-4 rounded-lg border border-primary/30 bg-primary/5 p-3 text-sm" data-testid="shared-confirm">
                <p className="font-medium">Значения, заданные вручную для всего файла</p>
                <ul className="my-1 list-disc pl-5">{shared.map((s) => <li key={s.field}>{s.label}: <strong>{s.value.trim() || "—"}</strong></li>)}</ul>
                <label className="flex items-start gap-2">
                  <input type="checkbox" className="mt-1" checked={prep.confirmShared} disabled={busy} data-testid="confirm-shared"
                    onChange={(e) => updatePrep({ confirmShared: e.target.checked }, "изменено подтверждение значений")} />
                  <span>Подтверждаю: эти значения верны для всех строк с данными в выбранном диапазоне.</span>
                </label>
              </div>
            )}

            <div className="mt-4 flex flex-wrap items-center gap-2 border-t pt-4">
              <Button onClick={() => source && sheet && region && runValidate(source, sheet, region, prep, csv)} disabled={!canValidate}
                data-testid="run-validation" aria-describedby="validate-hint">
                {phase === "validating" && <Loader2 className="size-4 animate-spin" aria-hidden />}
                {report ? "Проверить снова" : "Проверить данные"}
              </Button>
              <Button variant="outline" onClick={cancel} disabled={phase === "committing"} data-testid="cancel-import">Отменить</Button>
              <span id="validate-hint" className="text-xs text-muted-foreground">
                {!sheet ? "Выберите лист." : !region ? "Выберите строку заголовка." : !ready
                  ? (shared.length > 0 && !prep.confirmShared && !problems.general.length ? "Подтвердите значения, заданные вручную." : "Завершите сопоставление: проблемы отмечены выше.")
                  : "Проверка не изменяет данные."}
              </span>
            </div>
            {notice && !report && <p className="mt-3 rounded-md border border-warning/50 bg-warning/10 p-2 text-sm" data-testid="stale-notice">{notice}</p>}
          </CardContent>
        </Card>
      )}

      {report && source && (
        <ReviewPanel report={report} source={source} page={page} setPage={setPage} committing={phase === "committing"} done={phase === "done"}
          onCommit={commit} onDiscard={cancel} />
      )}

      {phase === "done" && result && (
        <SuccessPanel>
          {result.dataset_id ? (
            <>
              <p>Сохранён набор данных ({result.kind === "aggregate" ? "сводная таблица" : "общая таблица"}): {int(result.inserted_rows)} строк. Он хранится отдельно от результатов оценивания.</p>
              <div className="mt-2 flex flex-wrap gap-2">
                <Button asChild size="sm" data-testid="open-dataset"><Link href={`/datasets?id=${result.dataset_id}`}>7. Открыть набор данных</Link></Button>
              </div>
            </>
          ) : (
            <>
              <p>Добавлено записей: {int(result.inserted_rows)}{result.skipped_rows ? `, пропущено уже загруженных: ${int(result.skipped_rows)}` : ""}.</p>
              {afterCaps && <div className="mt-3"><CapabilityList items={afterCaps} title="7. Анализ: что доступно по всем загруженным данным" testId="after-capabilities" /></div>}
              <div className="mt-2 flex flex-wrap gap-2">
                <Button asChild size="sm"><Link href="/">Открыть обзор</Link></Button>
                <Button asChild size="sm" variant="outline"><Link href="/topics">Анализ тем</Link></Button>
              </div>
            </>
          )}
        </SuccessPanel>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Поля результатов оценивания</CardTitle>
            <CardDescription>
              Записи: одна строка — результат одного ученика по одной теме (или заданию) одного оценивания. Журналы преобразуются в такие записи;
              сводные и прочие таблицы сохраняются как наборы данных и не смешиваются с результатами.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader><TableRow><TableHead>Поле</TableHead><TableHead>Описание</TableHead><TableHead className="w-28">Обязательно</TableHead></TableRow></TableHeader>
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
            ) : <p className="text-sm text-muted-foreground">Загрузок пока не было.</p>}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
