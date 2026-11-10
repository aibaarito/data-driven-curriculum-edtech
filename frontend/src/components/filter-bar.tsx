"use client";

import { FilterX } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo } from "react";

import { useMeta } from "@/components/meta-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { t } from "@/i18n";
import { activeFilterCount, parseFilters, toQuery, type Filters } from "@/lib/filters";

const ALL = "__all";

export function useFilters(): [Filters, (patch: Partial<Filters>) => void, () => void] {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const filters = useMemo(() => parseFilters(params), [params]);
  const update = useCallback(
    (patch: Partial<Filters>) => {
      const next: Filters = { ...filters, ...patch };
      for (const k of Object.keys(next) as (keyof Filters)[]) if (next[k] === undefined) delete next[k];
      router.replace(`${pathname}${toQuery(next)}`, { scroll: false });
    },
    [filters, pathname, router],
  );
  const reset = useCallback(() => router.replace(pathname, { scroll: false }), [pathname, router]);
  return [filters, update, reset];
}

type Field = "subject" | "grade" | "class" | "textbook" | "period";

export function FilterBar({ fields = ["subject", "grade", "class", "textbook", "period"] }: { fields?: Field[] }) {
  const { data: meta } = useMeta();
  const [f, update, reset] = useFilters();
  const classes = (meta?.classes ?? []).filter((c) => !f.grade || c.grade === f.grade);
  const textbooks = (meta?.textbooks ?? []).filter((tb) => !f.subject_id || tb.subject_id === f.subject_id);
  const n = activeFilterCount(f);

  const sel = (
    id: string,
    label: string,
    value: number | undefined,
    options: { value: number; label: string }[],
    onChange: (v: number | undefined) => void,
  ) => (
    <div className="flex min-w-0 flex-col gap-1.5">
      <Label htmlFor={id} className="text-xs text-muted-foreground">
        {label}
      </Label>
      <Select value={value ? String(value) : ALL} onValueChange={(v) => onChange(v === ALL ? undefined : Number(v))}>
        <SelectTrigger id={id} className="w-full bg-card" aria-label={label}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>{t.filters.all}</SelectItem>
          {options.map((o) => (
            <SelectItem key={o.value} value={String(o.value)}>
              {o.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );

  return (
    <section
      aria-label="Фильтры"
      className="mb-6 grid grid-cols-2 gap-3 rounded-xl border bg-card/60 p-3 sm:grid-cols-3 lg:grid-cols-[repeat(6,minmax(0,1fr))_auto]"
    >
      {fields.includes("subject") &&
        sel("f-subject", t.filters.subject, f.subject_id, (meta?.subjects ?? []).map((s) => ({ value: s.id, label: s.name })),
          (v) => update({ subject_id: v, textbook_id: undefined }))}
      {fields.includes("grade") &&
        sel("f-grade", t.filters.grade, f.grade, (meta?.grades ?? []).map((g) => ({ value: g, label: t.filters.gradeN(g) })),
          (v) => update({ grade: v, class_id: undefined }))}
      {fields.includes("class") &&
        sel("f-class", t.filters.class, f.class_id, classes.map((c) => ({ value: c.id, label: c.name })), (v) =>
          update({ class_id: v }))}
      {fields.includes("textbook") &&
        sel("f-textbook", t.filters.textbook, f.textbook_id, textbooks.map((tb) => ({ value: tb.id, label: tb.name })),
          (v) => update({ textbook_id: v }))}
      {fields.includes("period") && (
        <>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="f-from" className="text-xs text-muted-foreground">
              {t.filters.from}
            </Label>
            <Input id="f-from" type="date" className="bg-card" value={f.date_from ?? ""}
              min={meta?.date_from ?? undefined} max={f.date_to ?? meta?.date_to ?? undefined}
              onChange={(e) => update({ date_from: e.target.value || undefined })} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="f-to" className="text-xs text-muted-foreground">
              {t.filters.to}
            </Label>
            <Input id="f-to" type="date" className="bg-card" value={f.date_to ?? ""}
              min={f.date_from ?? meta?.date_from ?? undefined} max={meta?.date_to ?? undefined}
              onChange={(e) => update({ date_to: e.target.value || undefined })} />
          </div>
        </>
      )}
      <div className="flex items-end">
        <Button variant="ghost" onClick={reset} disabled={n === 0} className="w-full">
          <FilterX className="size-4" /> {t.filters.reset}
          {n > 0 && <span className="text-xs text-muted-foreground">({n})</span>}
        </Button>
      </div>
    </section>
  );
}
