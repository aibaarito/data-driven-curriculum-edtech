import { afterEach, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); vi.resetModules(); });

it("adds the server token, preserves filters, and returns only allowed response headers", async () => {
  vi.stubEnv("API_URL", "http://127.0.0.1:8011");
  vi.stubEnv("API_TOKEN", "server-private-test-token");
  const fetchMock = vi.fn().mockResolvedValue(new Response('{"has_data":true}', {
    headers: { "content-type": "application/json", "authorization": "private-upstream", "x-private": "hidden" },
  }));
  vi.stubGlobal("fetch", fetchMock);
  const { GET } = await import("../app/api/[...path]/route");
  const req = new NextRequest("http://localhost/api/analytics/topics?grade=7", {
    headers: { authorization: "Bearer browser-attempt", cookie: "private-browser-cookie" },
  });
  const response = await GET(req, { params: Promise.resolve({ path: ["analytics", "topics"] }) });
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe("http://127.0.0.1:8011/api/analytics/topics?grade=7");
  expect(init.headers.get("authorization")).toBe("Bearer server-private-test-token");
  expect(init.headers.has("cookie")).toBe(false);
  expect(response.headers.has("authorization")).toBe(false);
  expect(response.headers.has("x-private")).toBe(false);
  expect(await response.text()).not.toContain("private");
});

it("returns a useful 502 when the backend is unavailable", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("private connection detail")));
  const { GET } = await import("../app/api/[...path]/route");
  const response = await GET(new NextRequest("http://localhost/api/meta"), {
    params: Promise.resolve({ path: ["meta"] }),
  });
  expect(response.status).toBe(502);
  expect(await response.text()).not.toContain("private connection detail");
});

it("preserves error statuses and PDF attachment headers", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("%PDF-test", {
    status: 200, headers: { "content-type": "application/pdf", "content-disposition": 'attachment; filename="report.pdf"' },
  })));
  const { GET } = await import("../app/api/[...path]/route");
  const response = await GET(new NextRequest("http://localhost/api/reports/1/pdf"), {
    params: Promise.resolve({ path: ["reports", "1", "pdf"] }),
  });
  expect(response.headers.get("content-disposition")).toContain("report.pdf");
  expect(response.headers.get("content-type")).toBe("application/pdf");
});

it.each([["..", "settings"], ["imports", "..\\private"], ["\\private"]])(
  "rejects path segments that could escape the intended API route: %j", async (...segments) => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const { GET } = await import("../app/api/[...path]/route");
    const response = await GET(new NextRequest("http://localhost/api/meta"), {
      params: Promise.resolve({ path: segments }),
    });
    expect(response.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  },
);
