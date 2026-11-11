import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { proxy } from "./proxy";

afterEach(() => vi.unstubAllEnvs());

describe("optional UI basic authentication", () => {
  function request(auth?: string) {
    return new NextRequest("http://localhost/settings", { headers: auth ? { authorization: auth } : {} });
  }
  function configure() {
    vi.stubEnv("DEMO_BASIC_AUTH_USER", "judge");
    vi.stubEnv("DEMO_BASIC_AUTH_PASSWORD", "test-password");
  }
  it("allows local mode without configured basic authentication", () => {
    vi.stubEnv("DEMO_BASIC_AUTH_USER", "");
    vi.stubEnv("DEMO_BASIC_AUTH_PASSWORD", "");
    expect(proxy(request()).status).toBe(200);
  });
  it.each([undefined, "Basic !!!", "Basic dQ==", "Bearer wrong", `Basic ${btoa("judge:wrong")}`])(
    "challenges invalid credentials %s without throwing", (auth) => {
      configure();
      const response = proxy(request(auth));
      expect(response.status).toBe(401);
      expect(response.headers.get("www-authenticate")).toContain("Basic");
    });
  it("allows matching credentials", () => {
    configure();
    expect(proxy(request(`Basic ${btoa("judge:test-password")}`)).status).toBe(200);
  });
});

it("allows exact readiness but protects every data route with basic auth", () => {
  vi.stubEnv("DEMO_BASIC_AUTH_USER", "judge");
  vi.stubEnv("DEMO_BASIC_AUTH_PASSWORD", "private-test");
  expect(proxy(new NextRequest("http://localhost/api/health")).status).toBe(200);
  for (const path of ["/", "/api/meta", "/api/health/extra", "/reports"]) {
    expect(proxy(new NextRequest(`http://localhost${path}`)).status).toBe(401);
  }
});
