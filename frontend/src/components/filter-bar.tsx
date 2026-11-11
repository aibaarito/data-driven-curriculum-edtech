"use client";

import { ChevronDown, FilterX, Info, SlidersHorizontal, TriangleAlert, X } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useId, useMemo, useState } from "react";

import { useMeta } from "@/components/meta-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { t } from "@/i18n";
import { activeFilterCount, parseFilters, toQuery, type Filters } from "@/lib/filters";
import { filterConflicts, inapplicableFilters, scopeLabel } from "@/lib/scope";
import { cn } from "@/lib/utils";

const ALL = "__all";
// Chrome moves keyboard focus into the date input's inner fields, where :focus-visible does not match the host,
// so date inputs show their focus ring on :focus.
const DATE_FOCUS = "bg-card focus:border-ring focus:ring-3 focus:ring-ring/50";

/**
 * Filters live in the URL. Each change is a history entry (router.push), so the browser Back button restores the
 * previous analysis scope; navigation links carry the same query to the next screen.
 */
export function useFilters(): [Filters, (patch: Partial<Filters>) => void, () => void] {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const filters = useMemo(() => parseFilters(params), [params]);
  const update = useCallback(
    (patch: Partial<Filters>) => {
      const next: Filters = { ...filters, ...patch };
      for (const k of Object.keys(next) as (keyof Filters)[]) if (next[k] === undefined) delete next[k];
      const extra = params.get("topic");
      const q = toQuery(next);
      router.push(`${pathname}${q}${extra && !("grade" in patch || "subject_id" in patch) ? `${q ? "&" : "?"}topic=${encodeURIComponent(extra)}` : ""}`,
        { scroll: false });
    },
    [filters, params, pathname, router],
  );
  const reset = useCallback(() => router.push(pathname, { scroll: false }), [pathname, router]);
  return [filters, update, reset];
}

type Field = "subject" | "grade" | "class" | "textbook" | "period";

export function FilterBar({ fields = ["subject", "grade", "class", "textbook", "period"] }: { fields?: Field[] }) {
  const { data: meta } = useMeta();
  const pathname = usePathname();
  const [f, update, reset] = useFilters();
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const classes = (meta?.classes ?? []).filter((c) => !f.grade || c.grade === f.grade || c.id === f.class_id);
  const textbooks = (meta?.textbooks ?? []).filter((tb) => !f.subject_id || tb.subject_id === f.subject_id || tb.id === f.textbook_id);
  const n = activeFilterCount(f);
  const conflicts = filterConflicts(f, meta);
  const notApplied = inapplicableFilters(pathname, f, meta);
  const summary = scopeLabel(f, meta, pathname);

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
          {value !== undefined && !options.some((o) => o.value === value) && (
            <SelectItem value={String(value)}>не найдено в данных</SelectItem>
          )}
        </SelectContent>
      </Select>
    </div>
  );

  return (
    <section aria-label="Фильтры" className="mb-6 rounded-xl border bg-card/60 p-3">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <p className="min-w-0 text-sm" data-testid="scope-summary">
          <span className="text-muted-foreground">Группа анализа: </span>
          <span className="font-medium">{summary}</span>
        </p>
        <div className="flex flex-wrap items-center gap-1">
          <Button variant="outline" size="sm" className="sm:hidden" aria-expanded={open} aria-controls={panelId}
            onClick={() => setOpen((o) => !o)}>
            <SlidersHorizontal className="size-4" /> Фильтры{n > 0 && ` (${n})`}
            <ChevronDown className={cn("size-3.5 transition-transform", open && "rotate-180")} />
          </Button>
          <Button variant="ghost" size="sm" onClick={reset} disabled={n === 0} data-testid="reset-filters">
            <FilterX className="size-4" /> {t.filters.reset}
            {n > 0 && <span className="text-xs text-muted-foreground">({n})</span>}
          </Button>
        </div>
      </div>
      <div id={panelId}
        className={cn("grid-cols-2 gap-3 sm:grid sm:grid-cols-3 lg:grid-cols-[repeat(6,minmax(0,1fr))]", open ? "grid" : "hidden")}>
        {fields.includes("subject") &&
          sel("f-subject", t.filters.subject, f.subject_id, (meta?.subjects ?? []).map((s) => ({ value: s.id, label: s.name })),
            (v) => {
              const tb = meta?.textbooks.find((x) => x.id === f.textbook_id);
              update({ subject_id: v, ...(tb && v && tb.subject_id !== v ? { textbook_id: undefined } : {}) });
            })}
        {fields.includes("grade") &&
          sel("f-grade", t.filters.grade, f.grade, (meta?.grades ?? []).map((g) => ({ value: g, label: t.filters.gradeN(g) })),
            (v) => {
              const cls = meta?.classes.find((c) => c.id === f.class_id);
              update({ grade: v, ...(cls && v && cls.grade !== v ? { class_id: undefined } : {}) });
            })}
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
              <Input id="f-from" type="date" className={DATE_FOCUS} value={f.date_from ?? ""}
                min={meta?.date_from ?? undefined} max={f.date_to ?? meta?.date_to ?? undefined}
                onChange={(e) => update({ date_from: e.target.value || undefined })} />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="f-to" className="text-xs text-muted-foreground">
                {t.filters.to}
              </Label>
              <Input id="f-to" type="date" className={DATE_FOCUS} value={f.date_to ?? ""}
                min={f.date_from ?? meta?.date_from ?? undefined} max={meta?.date_to ?? undefined}
                onChange={(e) => update({ date_to: e.target.value || undefined })} />
            </div>
          </>
        )}
      </div>
      {conflicts.length > 0 && (
        <div role="alert" className="mt-3 rounded-lg border border-danger/30 bg-danger/5 p-3 text-sm" data-testid="filter-conflicts">
          <div className="mb-1 flex items-center gap-2 font-medium">
            <TriangleAlert className="size-4 text-danger" aria-hidden /> Фильтры противоречат друг другу — результаты будут пустыми, а не расширенными
          </div>
          <ul className="space-y-1">
            {conflicts.map((c) => (
              <li key={c.key} className="flex flex-wrap items-center gap-2">
                <span>{c.message}</span>
                <Button size="sm" variant="outline" className="h-7" onClick={() => update({ [c.key]: undefined })}>
                  <X className="size-3.5" /> Убрать этот фильтр
                </Button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {notApplied.length > 0 && (
        <p className="mt-3 flex gap-2 text-xs text-muted-foreground" data-testid="filters-not-applied">
          <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          <span>
            На этом экране не применяется: {notApplied.join(", ")}. Фильтр сохранён и снова действует в разделах, где он поддерживается.
          </span>
        </p>
      )}
    </section>
  );
}
