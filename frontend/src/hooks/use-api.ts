"use client";

import { useCallback, useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";

export interface ApiState<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  reload: () => void;
}

interface Settled<T> {
  key: string;
  data: T | null;
  error: ApiError | null;
}

/**
 * GET a JSON resource; refetches when `path` changes and aborts stale requests. `null` path = skip.
 * Loading is derived (request key differs from the last settled key), so no state is set synchronously in effects.
 */
export function useApi<T>(path: string | null): ApiState<T> {
  const [nonce, setNonce] = useState(0);
  const [settled, setSettled] = useState<Settled<T>>({ key: "", data: null, error: null });
  const key = path === null ? "" : `${path}#${nonce}`;

  useEffect(() => {
    if (path === null) return;
    const ctrl = new AbortController();
    api
      .get<T>(path, ctrl.signal)
      .then((d) => setSettled({ key, data: d, error: null }))
      .catch((e: unknown) => {
        if ((e as Error).name === "AbortError") return;
        setSettled((prev) => ({ key, data: prev.data, error: e instanceof ApiError ? e : new ApiError("Неизвестная ошибка.", 0) }));
      });
    return () => ctrl.abort();
  }, [path, key]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  const loading = path !== null && settled.key !== key;
  return { data: settled.data, error: loading ? null : settled.error, loading, reload };
}
