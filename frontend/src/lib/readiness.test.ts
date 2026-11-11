import { afterEach, expect, it, vi } from "vitest";

vi.mock("next/server", () => ({ connection: vi.fn().mockResolvedValue(undefined) }));
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

it("checks the private backend at runtime and returns minimal readiness", async () => {
  vi.stubEnv("API_URL", "http://backend.railway.internal:8080");
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: "ok", database: true, llm_enabled: false })));
  vi.stubGlobal("fetch", fetchMock);
  const { GET } = await import("../app/api/health/route");
  const response = await GET();
  expect(fetchMock.mock.calls[0][0]).toBe("http://backend.railway.internal:8080/api/health");
  expect(response.status).toBe(200);
  expect(await response.json()).toEqual({ status: "ready" });
  expect(response.headers.get("cache-control")).toBe("no-store");
});

it.each([
  new Response('{"status":"degraded","database":false}', { status: 503 }),
  new Response('{"status":"degraded","database":false}'),
  new Response('{"status":"ok"}'),
  new Response("bad JSON"),
])("does not green-light an unhealthy or malformed backend response", async (upstream) => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(upstream));
  const { GET } = await import("../app/api/health/route");
  const response = await GET();
  expect(response.status).toBe(503);
  expect(await response.json()).toEqual({ status: "unavailable" });
});

it("hides connection/timeout details", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("private-host secret")));
  const { GET } = await import("../app/api/health/route");
  const response = await GET();
  expect(response.status).toBe(503);
  expect(await response.text()).not.toContain("secret");
});
