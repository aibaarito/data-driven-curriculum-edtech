"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { AlertTriangle, CheckCircle2, Download, FileSpreadsheet, Loader2, UploadCloud, XCircle } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
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
import { MAX_UPLOAD_MB, uploadSchema, type UploadForm } from "@/lib/schemas";
import type { ImportBatch, ImportPreview, ValidationIssue } from "@/lib/types";
import { cn } from "@/lib/utils";

const PAGE = 25;
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

type Phase = "idle" | "uploading" | "preview" | "committing" | "done";

export function ImportView() {
  const meta = useMeta();
  const history = useApi<ImportBatch[]>("/api/imports");
  const [phase, setPhase] = useState<Phase>("idle");
  const [progress, setProgress] = useState(0);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [uploadError, setUploadError] = useState<ApiError | null>(null);
  const [result, setResult] = useState<{ inserted_rows: number; skipped_rows: number } | null>(null);
  const [page, setPage] = useState(0);

  const form = useForm<UploadForm>({ resolver: zodResolver(uploadSchema) });
  const fileError = form.formState.errors.file?.message;
  const selectedFile = useWatch({ control: form.control, name: "file" });

  const onSubmit = form.handleSubmit(async ({ file }) => {
    setUploadError(null);
    setPreview(null);
    setResult(null);
    setPage(0);
    setPhase("uploading");
    setProgress(0);
    try {
      const p = await uploadFile<ImportPreview>("/api/imports/preview", file, setProgress);
      setPreview(p);
      setPhase("preview");
    } catch (e) {
      setUploadError(e instanceof ApiError ? e : new ApiError("Ошибка загрузки.", 0));
      setPhase("idle");
    }
  });

  async function commit() {
    if (!preview) return;
    setPhase("committing");
    try {
      const r = await api.post<{ inserted_rows: number; skipped_rows: number }>(`/api/imports/${preview.batch_id}/commit`);
      setResult(r);
      setPhase("done");
      toast.success(`Импортировано строк: ${int(r.inserted_rows)}`);
      meta.reload();
      history.reload();
    } catch (e) {
      setUploadError(e instanceof ApiError ? e : new ApiError("Ошибка импорта.", 0));
      setPhase("preview");
    }
  }

  async function discard() {
    if (!preview) return;
    try {
      await api.post(`/api/imports/${preview.batch_id}/discard`);
      toast.info("Импорт отменён — данные не сохранены.");
    } catch {
      /* already discarded or committed — nothing to do */
    }
    setPreview(null);
    setPhase("idle");
    form.reset();
    history.reload();
  }

  const busy = phase === "uploading" || phase === "committing";

  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Загрузка файла</CardTitle>
            <CardDescription>
              CSV (UTF-8 или Windows-1251, разделитель «,» или «;») либо Excel .xlsx, до {MAX_UPLOAD_MB} МБ. Файл сначала
              проверяется — в базу ничего не записывается до подтверждения.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={onSubmit} className="space-y-4" noValidate>
              <label
                htmlFor="file"
                className={cn(
                  "flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors hover:border-primary/50 hover:bg-accent/40",
                  fileError && "border-danger/50",
                )}
              >
                <UploadCloud className="mb-2 size-8 text-primary" aria-hidden />
                <span className="font-medium">{selectedFile?.name ?? "Выберите файл .csv или .xlsx"}</span>
                <span className="mt-1 text-xs text-muted-foreground">Нажмите, чтобы выбрать файл</span>
                <input
                  id="file"
                  type="file"
                  accept=".csv,.xlsx"
                  className="sr-only"
                  data-testid="file-input"
                  disabled={busy}
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) form.setValue("file", f, { shouldValidate: true });
                  }}
                />
              </label>
              {fileError && <p className="text-sm text-danger" role="alert">{fileError}</p>}
              {phase === "uploading" && (
                <div className="space-y-1" aria-live="polite">
                  <Progress value={progress} />
                  <p className="text-xs text-muted-foreground">
                    {progress < 100 ? `Загрузка: ${progress}%` : "Проверка данных на сервере…"}
                  </p>
                </div>
              )}
              <Button type="submit" disabled={busy || !selectedFile} data-testid="validate-button">
                {phase === "uploading" ? <Loader2 className="size-4 animate-spin" /> : <FileSpreadsheet className="size-4" />}
                Проверить файл
              </Button>
            </form>
            {uploadError && (
              <Alert variant="destructive" className="mt-4">
                <XCircle className="size-4" />
                <AlertTitle>{uploadError.message}</AlertTitle>
                {uploadError.details.length > 0 && <AlertDescription>{uploadError.details.join("; ")}</AlertDescription>}
              </Alert>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Шаблоны</CardTitle>
            <CardDescription>Начните с шаблона или синтетического демонстрационного набора.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Button asChild variant="outline" className="w-full justify-start">
              <a href="/api/imports/template.csv" download><Download className="size-4" /> Шаблон CSV</a>
            </Button>
            <Button asChild variant="outline" className="w-full justify-start">
              <a href="/api/imports/demo-dataset.csv" download data-testid="demo-download">
                <Download className="size-4" /> Демо-набор (синтетический)
              </a>
            </Button>
            <p className="text-xs text-muted-foreground">
              Демо-набор полностью сгенерирован (seed 20251110) и помечен как синтетический. Он не описывает реальную школу.
            </p>
          </CardContent>
        </Card>
      </div>

      {preview && <PreviewPanel preview={preview} page={page} setPage={setPage} phase={phase} onCommit={commit} onDiscard={discard} />}

      {phase === "done" && result && (
        <Alert className="border-success/40 bg-success/5" data-testid="import-success">
          <CheckCircle2 className="size-4 text-success" />
          <AlertTitle>Данные импортированы</AlertTitle>
          <AlertDescription>
            <p>Добавлено строк: {int(result.inserted_rows)}{result.skipped_rows ? `, пропущено уже загруженных: ${int(result.skipped_rows)}` : ""}.</p>
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
            <CardDescription>Одна строка — балл одного ученика по одной теме (или заданию) одного оценивания.</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow><TableHead>Столбец</TableHead><TableHead>Описание</TableHead><TableHead className="w-28">Обязателен</TableHead></TableRow>
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
                      <span className="text-xs text-muted-foreground">{dateTime(b.created_at)} · {int(b.total_rows)} строк</span>
                    </span>
                    <Badge variant={b.status === "committed" ? "default" : "outline"}>
                      {b.status === "committed" ? "импорт" : b.status === "preview" ? "проверка" : "отменён"}
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

function PreviewPanel({ preview, page, setPage, phase, onCommit, onDiscard }: {
  preview: ImportPreview;
  page: number;
  setPage: (n: number) => void;
  phase: Phase;
  onCommit: () => void;
  onDiscard: () => void;
}) {
  const s = preview.summary;
  const pages = Math.max(1, Math.ceil(preview.errors.length / PAGE));
  const errors = preview.errors.slice(page * PAGE, page * PAGE + PAGE);
  const cols = useMemo(() => (preview.preview[0] ? Object.keys(preview.preview[0]).filter((k) => k !== "row") : []), [preview]);
  const done = phase === "done";

  return (
    <Card data-testid="import-preview">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          {preview.ok ? <CheckCircle2 className="size-5 text-success" /> : <XCircle className="size-5 text-danger" />}
          {preview.ok ? "Файл прошёл проверку" : "В файле есть ошибки — импорт невозможен"}
        </CardTitle>
        <CardDescription>
          {preview.filename}: {int(preview.total_rows)} строк, ошибок {int(preview.error_count)}, предупреждений {int(preview.warning_count)}.
          {!preview.ok && " Данные не исправляются автоматически: исправьте файл и загрузите его снова."}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {preview.ok && (
          <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4 lg:grid-cols-7">
            {[
              ["Учеников", s.students], ["Классов", s.classes], ["Тем", s.topics], ["Оцениваний", s.assessments],
              ["Учебников", s.textbooks?.length], ["Период", `${s.date_from} — ${s.date_to}`],
              ["Уровень", s.item_level ? "задания" : "темы"],
            ].map(([k, v]) => (
              <div key={String(k)} className="rounded-lg bg-muted/60 p-2.5">
                <div className="text-xs text-muted-foreground">{k}</div>
                <div className="font-semibold">{String(v ?? "—")}</div>
              </div>
            ))}
          </div>
        )}

        {Object.keys(preview.error_counts).length > 0 && (
          <div className="flex flex-wrap gap-2">
            {Object.entries(preview.error_counts).map(([code, n]) => (
              <Badge key={code} variant="destructive">{code}: {n}</Badge>
            ))}
          </div>
        )}

        {preview.warnings.length > 0 && (
          <Alert className="border-warning/50 bg-warning/10">
            <AlertTriangle className="size-4 text-amber-600" />
            <AlertTitle>Предупреждения</AlertTitle>
            <AlertDescription>
              <ul className="list-disc pl-4">
                {preview.warnings.map((w, i) => <li key={i}>{w.message}</li>)}
              </ul>
            </AlertDescription>
          </Alert>
        )}

        {preview.errors.length > 0 && (
          <div>
            <IssueTable issues={errors} />
            {pages > 1 && (
              <div className="mt-2 flex items-center justify-between text-sm text-muted-foreground">
                <span>Показаны {page * PAGE + 1}–{Math.min(preview.errors.length, (page + 1) * PAGE)} из {preview.errors.length}
                  {preview.error_count > preview.errors.length && ` (всего ошибок ${preview.error_count})`}</span>
                <span className="flex gap-2">
                  <Button size="sm" variant="outline" disabled={page === 0} onClick={() => setPage(page - 1)}>Назад</Button>
                  <Button size="sm" variant="outline" disabled={page >= pages - 1} onClick={() => setPage(page + 1)}>Далее</Button>
                </span>
              </div>
            )}
          </div>
        )}

        {preview.ok && cols.length > 0 && (
          <div>
            <h3 className="mb-2 text-sm font-medium">Предпросмотр (первые {preview.preview.length} строк после нормализации)</h3>
            <div className="max-h-80 overflow-auto rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Строка</TableHead>
                    {cols.map((c) => <TableHead key={c} className="font-mono text-xs">{c}</TableHead>)}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {preview.preview.map((r) => (
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
          <div className="flex flex-wrap gap-2 border-t pt-4">
            <Button onClick={onCommit} disabled={!preview.ok || phase === "committing"} data-testid="commit-button">
              {phase === "committing" && <Loader2 className="size-4 animate-spin" />}
              Подтвердить импорт ({int(preview.valid_rows)} строк)
            </Button>
            <Button variant="outline" onClick={onDiscard} disabled={phase === "committing"}>Отменить</Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function IssueTable({ issues }: { issues: ValidationIssue[] }) {
  return (
    <div className="overflow-auto rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow><TableHead className="w-20">Строка</TableHead><TableHead className="w-36">Столбец</TableHead><TableHead className="w-44">Код</TableHead><TableHead>Сообщение</TableHead></TableRow>
        </TableHeader>
        <TableBody>
          {issues.map((e, i) => (
            <TableRow key={i}>
              <TableCell>{e.row ?? "—"}</TableCell>
              <TableCell className="font-mono text-xs">{e.column ?? "—"}</TableCell>
              <TableCell><Badge variant="outline" className="font-mono text-[11px]">{e.code}</Badge></TableCell>
              <TableCell className="whitespace-normal text-sm">{e.message}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
