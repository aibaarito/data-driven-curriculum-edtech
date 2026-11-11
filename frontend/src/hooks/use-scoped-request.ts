"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api";

export interface ScopedValue<T> {
  requestId: number;
  /** Normalized filter query the request was made for, e.g. "?grade=7". */
  scopeKey: string;
  /** Human-readable scope shown with the result, e.g. "Математика · 7 класс · все классы · весь период". */
  scopeLabel: string;
  value: T;
}

export interface ScopedRequestState<T> {
  /** Last successful result, always labelled with its own scope (may differ from the current one). */
  result: ScopedValue<T> | null;
  /** Request in flight, if any. */
  pending: { requestId: number; scopeKey: string; scopeLabel: string; startedAt: number } | null;
  error: ScopedValue<ApiError> | null;
  /** Set when waiting stopped before a response: by the user, or because the filters changed. */
  interrupted: { scopeLabel: string; reason: "user" | "scope" } | null;
  run: (scopeLabel: string, body: unknown) => void;
  /** Stops waiting (aborts the browser request). The server may still finish its own processing. */
  stop: () => void;
}

type Fetcher<T> = (body: unknown, signal: AbortSignal) => Promise<T>;

/**
 * Binds every result to the request identity and scope that produced it.
 * - A newer request supersedes older ones: an older response can never replace a newer result.
 * - When the current scope changes, the in-flight request is aborted and its response (if any) ignored.
 * - Results are kept with their own scope label; the caller decides how to present a result from another scope.
 */
export function useScopedRequest<T>(currentScopeKey: string, fetcher: Fetcher<T>): ScopedRequestState<T> {
  const [result, setResult] = useState<ScopedValue<T> | null>(null);
  const [pending, setPending] = useState<ScopedRequestState<T>["pending"]>(null);
  const [error, setError] = useState<ScopedValue<ApiError> | null>(null);
  const [interrupted, setInterrupted] = useState<ScopedRequestState<T>["interrupted"]>(null);
  const latest = useRef(0);
  const ctrl = useRef<AbortController | null>(null);
  const fetcherRef = useRef(fetcher);
  useEffect(() => {
    fetcherRef.current = fetcher;
  }, [fetcher]);

  // Scope changed: abort the request made for the previous scope (no state is set synchronously here).
  useEffect(() => () => ctrl.current?.abort("scope"), [currentScopeKey]);

  const run = useCallback((scopeLabel: string, body: unknown) => {
    ctrl.current?.abort("superseded");
    const c = new AbortController();
    ctrl.current = c;
    const requestId = ++latest.current;
    const scopeKey = currentScopeKey;
    setPending({ requestId, scopeKey, scopeLabel, startedAt: Date.now() });
    setError(null);
    setInterrupted(null);
    fetcherRef.current(body, c.signal).then(
      (value) => {
        if (requestId !== latest.current || c.signal.aborted) return; // obsolete response: ignore
        setResult({ requestId, scopeKey, scopeLabel, value });
        setPending(null);
      },
      (e: unknown) => {
        if (requestId !== latest.current) return;
        if (c.signal.aborted || (e as Error)?.name === "AbortError") {
          setPending(null);
          if (c.signal.reason === "user" || c.signal.reason === "scope") {
            setInterrupted({ scopeLabel, reason: c.signal.reason });
          }
          return;
        }
        setError({ requestId, scopeKey, scopeLabel, value: e instanceof ApiError ? e : new ApiError("Ошибка.", 0) });
        setPending(null);
      },
    );
  }, [currentScopeKey]);

  const stop = useCallback(() => ctrl.current?.abort("user"), []);

  return { result, pending, error, interrupted, run, stop };
}
