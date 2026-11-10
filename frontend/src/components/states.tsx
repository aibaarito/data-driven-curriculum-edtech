import { AlertTriangle, Inbox, RefreshCw } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { t } from "@/i18n";
import type { ApiError } from "@/lib/api";

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-balance">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function LoadingState({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-4" role="status" aria-live="polite" aria-label={t.states.loading}>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-24 rounded-xl" />
        ))}
      </div>
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-56 rounded-xl" />
      ))}
      <span className="sr-only">{t.states.loading}</span>
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: ApiError | Error; onRetry?: () => void }) {
  const details = "details" in error ? (error as ApiError).details : [];
  return (
    <div role="alert" className="flex flex-col items-center rounded-xl border border-danger/25 bg-danger/5 px-6 py-10 text-center">
      <AlertTriangle className="mb-3 size-8 text-danger" aria-hidden />
      <h2 className="font-semibold">{t.states.errorTitle}</h2>
      <p className="mt-1 max-w-lg text-sm text-muted-foreground">{error.message}</p>
      {details.length > 0 && (
        <ul className="mt-2 max-w-lg list-disc text-left text-sm text-muted-foreground">
          {details.map((d) => (
            <li key={d}>{d}</li>
          ))}
        </ul>
      )}
      {onRetry && (
        <Button variant="outline" className="mt-4" onClick={onRetry}>
          <RefreshCw className="size-4" /> {t.states.retry}
        </Button>
      )}
    </div>
  );
}

export function EmptyState({ title = t.states.emptyTitle, text = t.states.emptyText, showImport = true }: {
  title?: string;
  text?: string;
  showImport?: boolean;
}) {
  return (
    <div className="flex flex-col items-center rounded-xl border border-dashed bg-card px-6 py-14 text-center" data-testid="empty-state">
      <Inbox className="mb-3 size-9 text-muted-foreground" aria-hidden />
      <h2 className="font-semibold">{title}</h2>
      <p className="mt-1 max-w-md text-sm text-muted-foreground">{text}</p>
      {showImport && (
        <Button asChild className="mt-5">
          <Link href="/import">{t.states.goImport}</Link>
        </Button>
      )}
    </div>
  );
}
