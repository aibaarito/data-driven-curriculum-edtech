"use client";

import type { ReactNode } from "react";

import { useMeta } from "@/components/meta-provider";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";

/** Shows meta loading/error/empty states; renders children only when data exists. */
export function RequireData({ children }: { children: ReactNode }) {
  const meta = useMeta();
  if (meta.error) return <ErrorState error={meta.error} onRetry={meta.reload} />;
  if (meta.loading && !meta.data) return <LoadingState />;
  if (!meta.data?.has_data) return <EmptyState />;
  return <>{children}</>;
}
