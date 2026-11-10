import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { STATUS_META } from "@/lib/format";
import type { TopicStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

export function StatCard({ label, value, hint, icon: Icon, testId }: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  icon?: LucideIcon;
  testId?: string;
}) {
  return (
    <Card className="gap-0 py-4">
      <CardContent className="px-4">
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span>{label}</span>
          {Icon && <Icon className="size-4" aria-hidden />}
        </div>
        <div className="mt-2 text-2xl font-semibold tracking-tight tabular-nums" data-testid={testId}>
          {value}
        </div>
        {hint && <div className="mt-1 text-xs text-muted-foreground">{hint}</div>}
      </CardContent>
    </Card>
  );
}

export function StatusBadge({ status }: { status: TopicStatus }) {
  const m = STATUS_META[status];
  return (
    <Badge variant="outline" className={cn("gap-1.5 font-medium", m.className)}>
      <span className={cn("size-1.5 rounded-full", m.dot)} aria-hidden />
      {m.label}
    </Badge>
  );
}

export function KindTag({ kind }: { kind: "observation" | "recommendation" | "limitation" | "prediction" }) {
  const map = {
    observation: { label: "Наблюдение", cls: "bg-chart-1/10 text-primary border-primary/20" },
    recommendation: { label: "Рекомендация", cls: "bg-success/10 text-emerald-700 border-success/30" },
    limitation: { label: "Ограничение", cls: "bg-muted text-muted-foreground border-border" },
    prediction: { label: "Прогноз", cls: "bg-warning/15 text-amber-800 border-warning/40" },
  } as const;
  return (
    <Badge variant="outline" className={map[kind].cls}>
      {map[kind].label}
    </Badge>
  );
}

export function MasteryBar({ value, threshold }: { value: number | null; threshold?: number }) {
  const v = value ?? 0;
  const color = threshold !== undefined && v < threshold ? "bg-danger" : "bg-primary";
  return (
    <div className="relative h-1.5 w-full min-w-16 overflow-hidden rounded-full bg-muted" aria-hidden>
      <div className={cn("h-full rounded-full", color)} style={{ width: `${Math.max(0, Math.min(100, v))}%` }} />
    </div>
  );
}
