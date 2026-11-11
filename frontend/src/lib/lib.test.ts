import { describe, expect, it } from "vitest";

import { ApiError, errorFromBody } from "./api";
import { activeFilterCount, parseFilters, toQuery } from "./filters";
import { ci, pct, signed } from "./format";
import { settingsSchema, totalHoursSchema, uploadSchema } from "./schemas";

describe("filters", () => {
  it("parses valid params and drops malformed ones", () => {
    const f = parseFilters(new URLSearchParams("subject_id=2&grade=7&class_id=abc&textbook_id=-1&date_from=2025-09-01&date_to=bad"));
    expect(f).toEqual({ subject_id: 2, grade: 7, date_from: "2025-09-01" });
  });
  it("round-trips through the query string", () => {
    const q = toQuery({ grade: 7, textbook_id: 3 });
    expect(q).toBe("?grade=7&textbook_id=3");
    expect(parseFilters(new URLSearchParams(q.slice(1)))).toEqual({ grade: 7, textbook_id: 3 });
    expect(toQuery({})).toBe("");
  });
  it("counts active filters", () => {
    expect(activeFilterCount({ grade: 7, date_to: "2026-01-01" })).toBe(2);
  });
});

describe("format", () => {
  it("formats percentages and missing values", () => {
    expect(pct(67.4)).toBe("67,4%");
    expect(pct(null)).toBe("—");
  });
  it("formats signed values with a real minus sign", () => {
    expect(signed(5.3, " п.п.")).toBe("+5,3 п.п.");
    expect(signed(-2.17)).toBe("−2,17");
    expect(signed(0)).toBe("±0");
  });
  it("formats confidence intervals", () => {
    expect(ci(3.8, 6.8)).toBe("3,8 … 6,8");
    expect(ci(null, 1)).toBe("—");
  });
});

describe("api errors", () => {
  it("uses the server message and field errors", () => {
    const e = errorFromBody(422, { detail: "Некорректные входные данные.", errors: [{ field: "grade", message: "too big" }] });
    expect(e).toBeInstanceOf(ApiError);
    expect(e.message).toBe("Некорректные входные данные.");
    expect(e.details).toEqual(["grade: too big"]);
  });
  it("reads structured infeasibility errors", () => {
    const e = errorFromBody(422, { detail: { message: "Невозможно", details: ["нужно 50 ч"], code: "INFEASIBLE" } });
    expect(e.code).toBe("INFEASIBLE");
    expect(e.details).toEqual(["нужно 50 ч"]);
  });
  it("never exposes raw server output for 5xx", () => {
    expect(errorFromBody(500, "<html>Traceback</html>").message).toBe("Сервер временно недоступен. Повторите попытку.");
  });
});

describe("schemas", () => {
  const file = (name: string, size: number) => new File([new Uint8Array(size)], name);
  it("accepts csv and xlsx", () => {
    expect(uploadSchema.safeParse({ file: file("a.csv", 10) }).success).toBe(true);
    expect(uploadSchema.safeParse({ file: file("a.XLSX", 10) }).success).toBe(true);
  });
  it("rejects wrong extension, empty and oversized files", () => {
    expect(uploadSchema.safeParse({ file: file("a.pdf", 10) }).success).toBe(false);
    expect(uploadSchema.safeParse({ file: file("a.csv", 0) }).success).toBe(false);
    expect(uploadSchema.safeParse({ file: file("a.csv", 10 * 1024 * 1024 + 1) }).success).toBe(false);
  });
  it("validates threshold order", () => {
    const base = { difficult_threshold: 50, watch_threshold: 65, target_mastery: 75, min_students_topic: 10,
      min_students_textbook: 30, min_classes_textbook: 3, max_change_pct: 30 };
    expect(settingsSchema.safeParse(base).success).toBe(true);
    expect(settingsSchema.safeParse({ ...base, difficult_threshold: 70 }).success).toBe(false);
    expect(settingsSchema.safeParse({ ...base, min_students_topic: 2.5 }).success).toBe(false);
  });
  it("requires total hours in half-hour steps", () => {
    expect(totalHoursSchema.safeParse(82.5).success).toBe(true);
    expect(totalHoursSchema.safeParse(82.3).success).toBe(false);
    expect(totalHoursSchema.safeParse(0).success).toBe(false);
  });
  it.each([1, 2])("rejects fewer than three classes per textbook (%s)", (count) => {
    const base = { difficult_threshold: 50, watch_threshold: 65, target_mastery: 75, min_students_topic: 10,
      min_students_textbook: 30, min_classes_textbook: count, max_change_pct: 30 };
    expect(settingsSchema.safeParse(base).success).toBe(false);
  });
});

describe("changed contracts", () => {
  it("preserves the sign of small confidence bounds and gains", () => {
    expect(ci(0.04, 0.08)).toBe("0,04 … 0,1");
    expect(ci(-0.08, -0.04)).toBe("-0,1 … -0,04");
    expect(signed(0.0004)).toBe("+0,0004");
    expect(signed(-0.0004)).toBe("−0,0004");
  });
  it("surfaces optimizer policy infeasibility with its code and details", () => {
    const e = errorFromBody(422, { detail: { message: "Нельзя распределить", details: ["правило"], code: "POLICY_INFEASIBLE" } });
    expect(e.code).toBe("POLICY_INFEASIBLE");
    expect(e.details).toEqual(["правило"]);
  });
  it("sends the admin token only as a request header", async () => {
    const calls: { url: string; init: RequestInit }[] = [];
    const orig = globalThis.fetch;
    globalThis.fetch = (async (url: string, init: RequestInit) => {
      calls.push({ url, init });
      return new Response(JSON.stringify({ reset: true }), { status: 200 });
    }) as typeof fetch;
    try {
      const { api } = await import("./api");
      await api.post("/api/admin/reset", { confirm: "УДАЛИТЬ" }, { "X-Admin-Token": "secret-token" });
    } finally {
      globalThis.fetch = orig;
    }
    const headers = calls[0].init.headers as Record<string, string>;
    expect(headers["X-Admin-Token"]).toBe("secret-token");
    expect(String(calls[0].init.body)).not.toContain("secret-token");
  });
});
