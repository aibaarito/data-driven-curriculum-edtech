"use client";

import type { ReactNode } from "react";

import { useFilters } from "@/components/filter-bar";
import { useMeta } from "@/components/meta-provider";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { t } from "@/i18n";
import { inapplicableFilters } from "@/lib/scope";

/**
 * Subject + grade selector bound to the URL (same convention as the optimizer). Values from the URL that no longer
 * exist are never used silently: the first available value is chosen and the substitution is stated.
 */
export function PlanScope({ screen, idPrefix, children }: {
  screen: string;
  idPrefix: string;
  children: (scope: { subjectId: number; grade: number; subjectName: string }) => ReactNode;
}) {
  const { data: meta } = useMeta();
  const [f, update] = useFilters();
  const subjects = meta?.subjects ?? [];
  const grades = meta?.grades ?? [];
  const urlSubjectValid = subjects.some((x) => x.id === f.subject_id);
  const urlGradeValid = f.grade !== undefined && grades.includes(f.grade);
  const subjectId = urlSubjectValid ? f.subject_id : subjects[0]?.id;
  const grade = urlGradeValid ? f.grade : grades[0];
  const subjectName = subjects.find((x) => x.id === subjectId)?.name ?? "";
  const notApplied = inapplicableFilters(screen, f, meta);
  return (
    <>
      <section aria-label="Срез анализа" className="mb-6 space-y-3 rounded-xl border bg-card/60 p-3">
        <div className="grid grid-cols-2 gap-3 sm:max-w-md">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`${idPrefix}-subject`} className="text-xs text-muted-foreground">{t.filters.subject}</Label>
            <Select value={subjectId ? String(subjectId) : undefined} onValueChange={(v) => update({ subject_id: Number(v), textbook_id: undefined })}>
              <SelectTrigger id={`${idPrefix}-subject`} className="w-full bg-card"><SelectValue placeholder="Выберите" /></SelectTrigger>
              <SelectContent>{subjects.map((x) => <SelectItem key={x.id} value={String(x.id)}>{x.name}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`${idPrefix}-grade`} className="text-xs text-muted-foreground">{t.filters.grade}</Label>
            <Select value={grade ? String(grade) : undefined} onValueChange={(v) => update({ grade: Number(v), class_id: undefined })}>
              <SelectTrigger id={`${idPrefix}-grade`} className="w-full bg-card"><SelectValue placeholder="Выберите" /></SelectTrigger>
              <SelectContent>{grades.map((g) => <SelectItem key={g} value={String(g)}>{t.filters.gradeN(g)}</SelectItem>)}</SelectContent>
            </Select>
          </div>
        </div>
        {subjectId && grade && (
          <p className="text-sm text-muted-foreground" data-testid={`${idPrefix}-scope-note`}>
            Срез: «{subjectName}», параллель {grade}.
            {notApplied.length > 0 && <> Здесь не применяется: {notApplied.join(", ")}; фильтр сохранён для других разделов.</>}
            {(f.subject_id === undefined || f.grade === undefined || !urlSubjectValid || !urlGradeValid) &&
              " Предмет или параллель не заданы (или не найдены) — выбраны первые доступные."}
          </p>
        )}
      </section>
      {subjectId && grade ? children({ subjectId, grade, subjectName }) :
        <p className="text-sm text-muted-foreground">Выберите предмет и параллель.</p>}
    </>
  );
}
