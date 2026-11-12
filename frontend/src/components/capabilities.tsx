import { CheckCircle2, CircleSlash, TriangleAlert } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import type { Capability } from "@/lib/types";

const LEVEL: Record<string, string> = {
  student: "по ученикам", class: "по классам", topic: "по темам", aggregate: "агрегированные данные", table: "по таблице",
};

/** Which analyses the data supports, at which level, and what is missing for the others. */
export function CapabilityList({ items, title = "Доступный анализ", testId = "capabilities" }: {
  items: Capability[];
  title?: string;
  testId?: string;
}) {
  return (
    <section aria-labelledby={`${testId}-title`} data-testid={testId}>
      <h3 id={`${testId}-title`} className="mb-2 text-sm font-medium">{title}</h3>
      <ul className="grid gap-2 md:grid-cols-2">
        {items.map((c) => (
          <li key={c.key} className="rounded-lg border p-3 text-sm" data-testid={`cap-${c.key}`} data-available={c.available}>
            <div className="flex flex-wrap items-center gap-1.5 font-medium">
              {c.available ? (c.partial ? <TriangleAlert className="size-4 text-amber-700" aria-hidden /> : <CheckCircle2 className="size-4 text-success" aria-hidden />)
                : <CircleSlash className="size-4 text-muted-foreground" aria-hidden />}
              <span>{c.title}</span>
              <span className="sr-only">{c.available ? (c.partial ? " — доступно с ограничениями" : " — доступно") : " — недоступно"}</span>
              <Badge variant="outline" className="text-[10px]">{LEVEL[c.level] ?? c.level}</Badge>
            </div>
            {c.missing.length > 0 && <ul className="mt-1 list-disc pl-5 text-muted-foreground">{c.missing.map((m, i) => <li key={i}>{m}</li>)}</ul>}
            {c.limitations.length > 0 && <ul className="mt-1 list-disc pl-5 text-xs text-muted-foreground">{c.limitations.map((m, i) => <li key={i}>{m}</li>)}</ul>}
            {c.link && <Link href={c.link} className="mt-1 inline-block text-xs text-primary underline-offset-2 hover:underline">Открыть</Link>}
          </li>
        ))}
      </ul>
    </section>
  );
}
