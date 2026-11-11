import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";

import { useScopedRequest } from "./use-scoped-request";

/** Fetcher whose responses are resolved manually, in any order, like a slow and a fast provider call. */
function controlledFetcher() {
  const calls: { body: unknown; signal: AbortSignal; resolve: (v: string) => void; reject: (e: unknown) => void }[] = [];
  const fetcher = (body: unknown, signal: AbortSignal) =>
    new Promise<string>((resolve, reject) => calls.push({ body, signal, resolve, reject }));
  return { fetcher, calls };
}

describe("F2 scoped AI requests", () => {
  it("a slower response for scope A never replaces or is shown as the newer result for B", async () => {
    const { fetcher, calls } = controlledFetcher();
    const { result, rerender } = renderHook(({ scope }) => useScopedRequest<string>(scope, fetcher), { initialProps: { scope: "?grade=7" } });
    act(() => result.current.run("7 класс", { grade: 7 }));
    rerender({ scope: "?grade=8" });
    act(() => result.current.run("8 класс", { grade: 8 }));
    expect(calls[0].signal.aborted).toBe(true); // A was aborted when the scope changed

    await act(async () => calls[1].resolve("B-result"));
    await act(async () => calls[0].resolve("A-result")); // late A response (a fetch that ignores abort)
    expect(result.current.result).toMatchObject({ value: "B-result", scopeKey: "?grade=8", scopeLabel: "8 класс" });
    expect(result.current.pending).toBeNull();
  });

  it("superseded requests for the same scope are ignored when they finish last", async () => {
    const { fetcher, calls } = controlledFetcher();
    const { result } = renderHook(() => useScopedRequest<string>("?grade=7", fetcher));
    act(() => result.current.run("7 класс", {}));
    act(() => result.current.run("7 класс", {}));
    await act(async () => calls[1].resolve("second"));
    await act(async () => calls[0].resolve("first"));
    expect(result.current.result?.value).toBe("second");
    expect(result.current.result?.requestId).toBe(2);
  });

  it("keeps a completed result labelled with its own scope after the filters change", async () => {
    const { fetcher, calls } = controlledFetcher();
    const { result, rerender } = renderHook(({ scope }) => useScopedRequest<string>(scope, fetcher), { initialProps: { scope: "?grade=7" } });
    act(() => result.current.run("7 класс", {}));
    await act(async () => calls[0].resolve("A"));
    rerender({ scope: "?grade=8" });
    // The caller compares scopeKey with the current scope and marks the result as belonging to the previous group.
    expect(result.current.result).toMatchObject({ value: "A", scopeKey: "?grade=7" });
  });

  it("changing the scope while waiting reports an interruption instead of a result", async () => {
    const { fetcher, calls } = controlledFetcher();
    const { result, rerender } = renderHook(({ scope }) => useScopedRequest<string>(scope, fetcher), { initialProps: { scope: "?grade=7" } });
    act(() => result.current.run("7 класс", {}));
    rerender({ scope: "?grade=8" });
    await act(async () => calls[0].reject(new DOMException("aborted", "AbortError")));
    expect(result.current.result).toBeNull();
    expect(result.current.interrupted).toEqual({ scopeLabel: "7 класс", reason: "scope" });
  });

  it("stopping the wait aborts the browser request and says so; errors carry their scope", async () => {
    const { fetcher, calls } = controlledFetcher();
    const { result } = renderHook(() => useScopedRequest<string>("?grade=7", fetcher));
    act(() => result.current.run("7 класс", {}));
    act(() => result.current.stop());
    expect(calls[0].signal.aborted).toBe(true);
    await act(async () => calls[0].reject(new DOMException("aborted", "AbortError")));
    expect(result.current.interrupted?.reason).toBe("user");

    act(() => result.current.run("7 класс", {}));
    await act(async () => calls[1].reject(new ApiError("Сервер временно недоступен.", 503)));
    expect(result.current.error).toMatchObject({ scopeKey: "?grade=7", scopeLabel: "7 класс" });
    expect(result.current.error?.value.status).toBe(503);
  });
});
