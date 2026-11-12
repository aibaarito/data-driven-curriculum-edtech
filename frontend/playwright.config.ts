import { defineConfig, devices } from "@playwright/test";

// Runs against an explicitly selected isolated stack. See docs/VERIFICATION.md.
// WARNING: the scenario resets ALL application data via /api/admin/reset before it starts.
const baseURL = process.env.E2E_BASE_URL;
if (!baseURL || process.env.E2E_ALLOW_RESET !== "isolated-database") {
  throw new Error("Set E2E_BASE_URL and E2E_ALLOW_RESET=isolated-database after verifying the target database.");
}
const target = new URL(baseURL);
if (!["127.0.0.1", "localhost", "[::1]"].includes(target.hostname) || ["3010", ""].includes(target.port)) {
  throw new Error("Refusing destructive E2E tests: use an explicit loopback verification port other than demo port 3010.");
}
export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"], ["html", { open: "never", outputFolder: "e2e/report" }]],
  use: {
    baseURL,
    locale: "ru-RU",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    acceptDownloads: true,
    // Optional: use a preinstalled Chromium when the pinned Playwright build is not downloaded (CI/sandbox images).
    ...(process.env.E2E_CHROMIUM_PATH ? { launchOptions: { executablePath: process.env.E2E_CHROMIUM_PATH } } : {}),
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
  ],
});
