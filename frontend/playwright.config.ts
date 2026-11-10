import { defineConfig, devices } from "@playwright/test";

// Runs against an already running stack (frontend :3010 → backend :8010). See README "End-to-end tests".
// WARNING: the scenario resets ALL application data via /api/admin/reset before it starts.
export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"], ["html", { open: "never", outputFolder: "e2e/report" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:3010",
    locale: "ru-RU",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    acceptDownloads: true,
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
  ],
});
