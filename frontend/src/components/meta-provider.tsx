"use client";

import { createContext, useContext, type ReactNode } from "react";

import { useApi, type ApiState } from "@/hooks/use-api";
import type { Meta } from "@/lib/types";

const MetaContext = createContext<ApiState<Meta> | null>(null);

export function MetaProvider({ children }: { children: ReactNode }) {
  const state = useApi<Meta>("/api/meta");
  return <MetaContext.Provider value={state}>{children}</MetaContext.Provider>;
}

export function useMeta(): ApiState<Meta> {
  const ctx = useContext(MetaContext);
  if (!ctx) throw new Error("useMeta must be used inside MetaProvider");
  return ctx;
}
