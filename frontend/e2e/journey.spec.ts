import fs from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

const DEMO = path.resolve(__dirname, "../../backend/app/assets/data/synthetic_assessments.csv");
const SHOTS = path.resolve(__dirname, "screenshots");
fs.mkdirSync(SHOTS, { recursive: true });

function watchErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => {
    // Browsers log handled 4xx API responses (e.g. the deliberate infeasible-optimizer request) as
    // "Failed to load resource"; those are expected. Everything else counts as an error.
    if (m.type() === "error" && !/Failed to load resource: .*status of 422/.test(m.text())) errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

async function shot(page: Page, name: string) {
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: true });
}

test.describe.configure({ mode: "serial" });

test.beforeAll(async ({ request }) => {
  // 1. Clean environment: wipe all data through the API (requires explicit confirmation word).
  const r = await request.post("/api/admin/reset", { data: { confirm: "УДАЛИТЬ" } });
  expect(r.ok()).toBeTruthy();
  const health = await (await request.get("/api/health")).json();
  expect(health.database).toBe(true);
});

test("full methodologist journey", async ({ page }) => {
  const errors = watchErrors(page);

  // 2. Dashboard on an empty database shows an empty state, not fake numbers.
  await page.goto("/");
  await expect(page.getByTestId("empty-state")).toBeVisible();
  await shot(page, "01-empty-dashboard");

  // 3-4. Upload, validate and import the synthetic dataset.
  await page.getByRole("link", { name: "Импорт данных" }).first().click();
  await page.getByTestId("file-input").setInputFiles(DEMO);
  await page.getByTestId("validate-button").click();
  const preview = page.getByTestId("import-preview");
  await expect(preview).toContainText("Файл прошёл проверку");
  await expect(preview).toContainText("15");
  await shot(page, "02-import-preview");
  await page.getByTestId("commit-button").click();
  await expect(page.getByTestId("import-success")).toBeVisible();
  await expect(page.getByTestId("synthetic-badge").first()).toBeVisible();

  // 5. Calculated statistics on the dashboard.
  await page.getByRole("link", { name: "Открыть обзор" }).click();
  await expect(page.getByTestId("kpi-students")).toHaveText("199");
  await expect(page.getByTestId("kpi-assessments")).toHaveText("8");
  await expect(page.getByTestId("kpi-mastery")).toHaveText("67,4%");
  await shot(page, "03-dashboard");

  // 6. Difficult topics.
  await expect(page.getByTestId("difficult-topics")).toContainText("Формулы сокращённого умножения");
  await page.goto("/topics?grade=7");
  const row = page.getByTestId("topics-table").getByRole("row", { name: /Формулы сокращённого умножения/ });
  await expect(row).toContainText("Трудная");
  await row.click();
  await expect(page.getByTestId("topic-detail")).toContainText("нет статистически значимого прироста");
  await shot(page, "04-topics");

  // 7. Textbook comparison: grade 7 has enough evidence for an adjusted estimate, grade 8 does not.
  await page.goto("/textbooks?grade=7");
  await expect(page.getByTestId("verdict-text").first()).toContainText("После поправки на исходный уровень");
  await expect(page.getByTestId("verdict-text").first()).toContainText("не доказательство");
  await expect(page.getByTestId("verdict-text").first()).toContainText("Средний прирост от входной к итоговой диагностике");
  await expect(page.getByText("Разница прироста pre→post").first()).toBeVisible();
  await shot(page, "05-textbooks-grade7");
  await page.goto("/textbooks?grade=8");
  await expect(page.getByTestId("verdict-text").first()).toHaveText("Недостаточно данных, чтобы определить, какой учебник эффективнее.");

  // 8. Curriculum allocation recommendation; every constraint satisfied; accept it.
  await page.goto("/optimizer?subject_id=999&grade=7");
  await expect(page.getByTestId("optimizer-inputs")).toContainText("Линейная функция");
  await page.getByTestId("run-optimizer").click();
  const result = page.getByTestId("optimizer-result");
  await expect(result).toBeVisible();
  const checks = result.getByTestId("constraint-checks").first();
  await expect(checks).toContainText("Сумма часов равна заданной — 82 из 82 ч");
  await expect(checks.locator("li")).toHaveCount(5);
  await expect(checks.locator("svg.text-danger")).toHaveCount(0);
  await expect(page.getByTestId("allocation-table")).toContainText("не значим — нужен пересмотр методики");
  await shot(page, "06-optimizer");
  await page.getByTestId("accept-run").click();
  await expect(page.getByTestId("run-status")).toHaveText("Принята");

  // Infeasible constraints produce an explicit error.
  await page.locator("#total").fill("10");
  await page.getByTestId("run-optimizer").click();
  await expect(page.getByTestId("optimizer-error")).toContainText("меньше суммы минимумов");

  // 9. Explanation grounded in verified data (deterministic mode — no API key in this environment).
  await page.goto("/insights?grade=7");
  await page.getByTestId("generate-insights").click();
  const insights = page.getByTestId("insights-result");
  await expect(insights).toContainText("детерминированный");
  await expect(insights).toContainText("Формулы сокращённого умножения");
  await expect(insights).toContainText("принято методистом");
  await shot(page, "07-insights");

  // 10-11. Generate and export the report.
  await page.goto("/reports?grade=7");
  await page.getByTestId("create-report").click();
  await expect(page.getByTestId("report-view")).toContainText("Ограничения данных");
  await shot(page, "08-report");
  const [download] = await Promise.all([page.waitForEvent("download"), page.getByTestId("download-pdf").click()]);
  const file = await download.path();
  const head = fs.readFileSync(file).subarray(0, 5).toString();
  expect(head).toBe("%PDF-");
  expect(fs.statSync(file).size).toBeGreaterThan(20_000);
  fs.copyFileSync(file, path.join(SHOTS, "report.pdf"));

  // 12. Stability: every navigation link opens a real page without errors.
  for (const name of ["Обзор", "Импорт данных", "Анализ тем", "Сравнение учебников", "Оптимизатор часов", "ИИ-пояснения", "Отчёты", "Настройки"]) {
    await page.getByRole("link", { name }).first().click();
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByText("This page could not be found")).toHaveCount(0);
  }
  const health = await (await page.request.get("/api/health")).json();
  expect(health.status).toBe("ok");
  expect(errors, errors.join("\n")).toEqual([]);
});

test("invalid upload is rejected with row-level errors and cannot be imported", async ({ page }) => {
  const errors = watchErrors(page);
  const bad = path.join(SHOTS, "bad.csv");
  fs.writeFileSync(bad,
    "student_id,grade,class,subject,topic_id,topic_name,assessment_id,assessment_type,assessment_date,score,max_score,textbook_id\n" +
    "S1,7,7А,Математика,T1,Тема,A1,pre,2025-09-10,12,10,TB\n" +
    "Иван Петров,7,7А,Математика,T1,Тема,A1,pre,2025-09-10,abc,0,TB\n");
  await page.goto("/import");
  await page.getByTestId("file-input").setInputFiles(bad);
  await page.getByTestId("validate-button").click();
  const preview = page.getByTestId("import-preview");
  await expect(preview).toContainText("В файле есть ошибки");
  await expect(preview).toContainText("SCORE_EXCEEDS_MAX");
  await expect(preview).toContainText("POSSIBLE_PERSONAL_DATA");
  await expect(page.getByTestId("commit-button")).toBeDisabled();
  await shot(page, "09-invalid-upload");

  await page.getByTestId("file-input").setInputFiles({ name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("x") });
  await expect(page.getByText("Поддерживаются только файлы .csv и .xlsx.")).toBeVisible();
  expect(errors).toEqual([]);
});

test("mobile layout has working navigation", async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await ctx.newPage();
  await page.goto("/");
  await page.getByRole("button", { name: "Открыть меню" }).click();
  await page.getByRole("link", { name: "Анализ тем" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Анализ тем" })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByTestId("topics-table")).toBeVisible();
  await page.screenshot({ path: path.join(SHOTS, "10-mobile.png"), fullPage: false });
  await ctx.close();
});
