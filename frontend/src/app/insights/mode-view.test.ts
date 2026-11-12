import { describe, expect, it } from "vitest";

import type { InsightsResponse } from "@/lib/types";

import { modeView } from "./insights-view";

const base: InsightsResponse = {
  mode: "deterministic", model: null, provider: "ollama", attempts: 0,
  payload: { summary: "", findings: [], limitations: [], next_steps: [] }, facts: {},
  fallback_reason: null, fallback_kind: null, fallback_detail: null, optimizer_status: null,
};

describe("modeView", () => {
  it("names the local model only for accepted model output", () => {
    const v = modeView({ ...base, mode: "llm", model: "qwen3:8b", attempts: 1 });
    expect(v.tone).toBe("ok");
    expect(v.title).toContain("локальная модель qwen3:8b");
  });

  it.each([
    ["unavailable", "недоступна"],
    ["model_missing", "не установлена"],
    ["timeout", "не ответила вовремя"],
    ["rejected", "отклонён"],
    ["busy", "занята"],
    ["too_large", "Слишком много фактов"],
  ] as const)("fallback %s is a warning and never claims model success", (kind, phrase) => {
    const v = modeView({ ...base, fallback_kind: kind, attempts: kind === "rejected" ? 2 : 1,
      fallback_reason: "Причина с сервера. Показаны пояснения по шаблонам; расчёты не изменились." });
    expect(v.tone).toBe("warn");
    expect(v.title).toContain(phrase);
    expect(v.title).toContain("шаблонам");
    expect(v.title).not.toContain("написала");
    expect(v.text).toBe("Причина с сервера. Показаны пояснения по шаблонам; расчёты не изменились.");
  });

  it("template mode without a model is neutral", () => {
    const v = modeView({ ...base, provider: null, fallback_kind: "not_configured" });
    expect(v.tone).toBe("template");
    expect(v.title).not.toContain("написала");
  });
});
