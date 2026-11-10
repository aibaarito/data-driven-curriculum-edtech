"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Bot, Database, Loader2, Save, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { useMeta } from "@/components/meta-provider";
import { ErrorState, LoadingState } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useApi } from "@/hooks/use-api";
import { api, ApiError } from "@/lib/api";
import { settingsSchema, type SettingsForm } from "@/lib/schemas";
import type { SettingsResponse } from "@/lib/types";

const FIELDS: { name: keyof SettingsForm; label: string; hint: string }[] = [
  { name: "difficult_threshold", label: "Порог «трудная тема», %", hint: "Освоение ниже — тема трудная" },
  { name: "watch_threshold", label: "Порог «требует внимания», %", hint: "Освоение ниже — тема под наблюдением" },
  { name: "target_mastery", label: "Целевое освоение, %", hint: "Используется оптимизатором часов" },
  { name: "min_students_topic", label: "Мин. учеников для классификации темы", hint: "Меньше — «мало данных»" },
  { name: "min_students_textbook", label: "Мин. учеников на учебник", hint: "Для вывода о различии учебников" },
  { name: "min_classes_textbook", label: "Мин. классов на учебник", hint: "Чтобы отделить учебник от учителя" },
  { name: "max_change_pct", label: "Макс. изменение часов темы, %", hint: "За один шаг оптимизации" },
];

export function SettingsView() {
  const { data, error, loading, reload } = useApi<SettingsResponse>("/api/settings");
  const meta = useMeta();
  const [saving, setSaving] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);
  const [confirm, setConfirm] = useState("");
  const form = useForm<SettingsForm>({ resolver: zodResolver(settingsSchema) });

  useEffect(() => {
    if (data) form.reset(data.analysis);
  }, [data, form]);

  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (loading || !data) return <LoadingState rows={1} />;

  const onSubmit = form.handleSubmit(async (values) => {
    setSaving(true);
    try {
      await api.put("/api/settings", values);
      toast.success("Настройки сохранены");
      reload();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Не удалось сохранить");
    } finally {
      setSaving(false);
    }
  });

  async function resetData() {
    try {
      await api.post("/api/admin/reset", { confirm });
      toast.success("Все данные удалены");
      setResetOpen(false);
      setConfirm("");
      meta.reload();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Ошибка");
    }
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Параметры анализа</CardTitle>
          <CardDescription>Пороги влияют на классификацию тем, сравнение учебников и оптимизатор. Пересчёт выполняется сразу.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={onSubmit} className="space-y-5" noValidate data-testid="settings-form">
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {FIELDS.map((f) => {
                const err = form.formState.errors[f.name]?.message;
                return (
                  <div key={f.name} className="flex flex-col gap-1.5">
                    <Label htmlFor={f.name}>{f.label}</Label>
                    <Input id={f.name} type="number" step="any" aria-invalid={!!err}
                      {...form.register(f.name, { valueAsNumber: true })} />
                    <span className={err ? "text-xs text-danger" : "text-xs text-muted-foreground"}>{err ?? f.hint}</span>
                  </div>
                );
              })}
            </div>
            <Button type="submit" disabled={saving}>
              {saving ? <Loader2 className="size-4 animate-spin" /> : <Save className="size-4" />} Сохранить
            </Button>
          </form>
        </CardContent>
      </Card>

      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><Bot className="size-4" /> Языковая модель</CardTitle>
            <CardDescription>Ключ хранится только в переменных окружения сервера и не передаётся в браузер.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div className="flex items-center gap-2">Статус: {data.llm.enabled
              ? <Badge>подключена: {data.llm.provider} / {data.llm.model}</Badge>
              : <Badge variant="outline">не подключена — детерминированный режим</Badge>}</div>
            <p className="text-muted-foreground">Чтобы подключить, задайте <code>LLM_API_KEY</code> (и при необходимости <code>LLM_PROVIDER</code>, <code>LLM_MODEL</code>) в <code>backend/.env</code> и перезапустите сервер.</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><Database className="size-4" /> Данные</CardTitle>
            <CardDescription>Лимит загрузки: {data.limits.max_upload_mb} МБ, до {data.limits.max_upload_rows.toLocaleString("ru-RU")} строк.</CardDescription>
          </CardHeader>
          <CardContent>
            <Button variant="destructive" onClick={() => setResetOpen(true)} disabled={!meta.data?.has_data}>
              <Trash2 className="size-4" /> Удалить все данные
            </Button>
            <p className="mt-2 text-xs text-muted-foreground">Удаляет результаты, рекомендации и отчёты. Настройки анализа сохраняются.</p>
          </CardContent>
        </Card>
      </div>

      <Dialog open={resetOpen} onOpenChange={setResetOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Удалить все данные?</DialogTitle>
            <DialogDescription>Действие необратимо. Будут удалены все импортированные результаты, рекомендации и отчёты. Введите слово УДАЛИТЬ для подтверждения.</DialogDescription>
          </DialogHeader>
          <Input value={confirm} onChange={(e) => setConfirm(e.target.value)} placeholder="УДАЛИТЬ" aria-label="Подтверждение удаления" />
          <DialogFooter>
            <Button variant="outline" onClick={() => setResetOpen(false)}>Отмена</Button>
            <Button variant="destructive" disabled={confirm !== "УДАЛИТЬ"} onClick={resetData}>Удалить навсегда</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
