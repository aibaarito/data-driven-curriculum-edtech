import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

// Flexible layouts on the isolated E2E stack (the database is reset first; see playwright.config.ts).
const EX = path.resolve(__dirname, "../../docs/examples");

test.describe.configure({ mode: "serial" });

function watchErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error" && !/Failed to load resource: .*status of (409|422)/.test(m.text())) errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

async function upload(page: Page, file: string) {
  await page.goto("/import");
  await page.getByTestId("file-input").setInputFiles(file);
  await page.getByTestId("validate-button").click();
  await expect(page.getByTestId("prepare-panel")).toBeVisible();
}

test.beforeAll(async ({ request }) => {
  const adminToken = process.env.E2E_ADMIN_TOKEN;
  if (!adminToken) throw new Error("E2E_ADMIN_TOKEN is required (the scenario resets the dedicated E2E database)");
  const r = await request.post("/api/admin/reset", { data: { confirm: "УДАЛИТЬ" }, headers: { "X-Admin-Token": adminToken } });
  expect(r.ok()).toBeTruthy();
});

test("wide gradebook with a two-row header → records traced to row and column → import → open analysis", async ({ page, request }) => {
  const errors = watchErrors(page);
  await upload(page, path.join(EX, "example_wide_gradebook.xlsx"));
  await expect(page.getByLabel("Строка с названиями столбцов")).toHaveValue("3");
  await expect(page.getByTestId("two-row-header")).toBeChecked();
  await expect(page.getByTestId("layout-wide")).toBeChecked();
  await expect(page.getByTestId("flagged-rows")).toContainText("итоговая строка");
  await page.getByTestId("exclude-total").check();

  // Row fields: two columns from the sheet, the rest as explicitly confirmed shared values.
  await expect(page.getByLabel("Идентификатор ученика")).toHaveValue("c0");
  for (const [label, value] of [["Параллель", "7"], ["Предмет", "Математика"], ["Идентификатор оценивания", "SYN-KR1"],
    ["Дата оценивания", "20.05.2026"]] as const) {
    await page.getByLabel(label, { exact: true }).selectOption("__value");
    await page.getByLabel(`Значение для всех строк: ${label}`).fill(value);
  }
  await page.getByLabel("Тип оценивания", { exact: true }).selectOption("__value");
  await page.getByLabel("Значение для всех строк: Тип оценивания").selectOption("post");
  await page.getByLabel("Идентификатор учебника").selectOption("__none");

  // Result columns: tasks of one topic with explicit item codes and maxima (never inferred from the data).
  const tasks = [["c2", "Q1", "2"], ["c3", "Q2", "3"], ["c4", "Q3", "5"]] as const;
  for (const [col, item, max] of tasks) {
    const rc = page.getByTestId(`result-${col}`);
    await expect(rc.getByRole("checkbox")).toBeChecked();
    await rc.getByLabel("Код темы").fill("SYN-FR");
    await rc.getByLabel("Название темы").fill("Дроби");
    await rc.getByLabel("Код задания (необяз.)").fill(item);
    await rc.getByLabel("Максимальный балл").fill(max);
  }
  await expect(page.getByTestId("result-c5")).toContainText("похоже на итог или среднее");
  await expect(page.getByTestId("result-c5").getByRole("checkbox")).not.toBeChecked();
  await page.getByLabel("Отметки отсутствия результата (через запятую)").fill("н");
  await page.getByLabel("Отметки отсутствия результата (через запятую)").blur();
  await page.getByTestId("confirm-shared").check();
  await page.getByTestId("run-validation").click();

  const review = page.getByTestId("import-preview");
  await expect(review).toContainText("Файл прошёл проверку");
  await expect(page.getByTestId("wide-explanation")).toContainText("12 строк × 3 столбцов");
  await expect(page.getByTestId("record-counts")).toContainText("Будет импортировано35");
  await expect(page.getByTestId("record-counts")).toContainText("Исключено строк1");
  await expect(page.getByTestId("import-warnings")).toContainText("отметку отсутствия результата");
  await expect(page.getByTestId("cap-textbooks")).toContainText("Для сравнения учебников укажите столбец с учебником.");
  await expect(page.getByTestId("cap-topics")).toHaveAttribute("data-available", "true");
  await page.screenshot({ path: path.join(process.env.E2E_ARTIFACT_DIR ?? "e2e/screenshots", "flex-01-wide-review.png"), fullPage: true });
  await page.getByTestId("commit-button").click();
  await expect(page.getByTestId("import-success")).toContainText("Добавлено записей: 35");
  await expect(page.getByTestId("after-capabilities")).toContainText("Анализ тем");

  // Analyse: the imported topic is available on the topic page.
  await page.getByTestId("after-capabilities").getByTestId("cap-topics").getByRole("link", { name: "Открыть" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Анализ тем" })).toBeVisible();
  await expect(page.getByTestId("topics-table")).toContainText("Дроби");
  const caps = await (await request.get("/api/analytics/capabilities")).json();
  expect(caps.capabilities.find((c: { key: string }) => c.key === "gains").available).toBe(false);
  expect(errors).toEqual([]);
});

test("aggregate topic table stays aggregate and opens as a dataset summary", async ({ page, request }) => {
  const before = (await (await request.get("/api/analytics/overview")).json()).overview;
  await upload(page, path.join(EX, "example_aggregate_topics.xlsx"));
  await expect(page.getByTestId("layout-aggregate")).toBeChecked();
  await expect(page.getByLabel(/C · Средний %/)).toHaveValue("value");
  await page.getByTestId("exclude-total").check();
  await page.getByLabel("Вид показателя").selectOption("percent");
  await page.getByTestId("run-validation").click();
  await expect(page.getByTestId("import-preview")).toContainText("Файл прошёл проверку");
  await expect(page.getByTestId("import-warnings")).toContainText("агрегированные данные");
  await expect(page.getByTestId("cap-gains")).toHaveAttribute("data-available", "false");
  await page.getByTestId("commit-button").click();
  await page.getByTestId("open-dataset").click();
  const summary = page.getByTestId("aggregate-summary");
  await expect(summary).toContainText("Дроби");
  await expect(summary).toContainText("взвешенное");
  expect((await (await request.get("/api/analytics/overview")).json()).overview).toEqual(before);
});

test("non-educational Windows-1251 table → general exploration with search, filter and type change", async ({ page }) => {
  const errors = watchErrors(page);
  await upload(page, path.join(EX, "example_general_table.csv"));
  await expect(page.getByTestId("csv-options")).toContainText("Windows-1251");
  await expect(page.getByTestId("csv-options")).toContainText("точка с запятой");
  await expect(page.getByTestId("layout-general")).toBeChecked();
  await expect(page.getByLabel(/A · Код заявки/)).toHaveValue("identifier");
  await page.getByLabel("Название набора данных (необязательно)").fill("Заявки (пример)");
  await page.getByTestId("run-validation").click();
  await expect(page.getByTestId("cap-explore")).toHaveAttribute("data-available", "true");
  await expect(page.getByTestId("cap-topics")).toHaveAttribute("data-available", "false");
  await page.getByTestId("commit-button").click();
  await page.getByTestId("open-dataset").click();
  await expect(page.getByTestId("dataset-detail")).toContainText("Заявки (пример)");
  await expect(page.getByTestId("profile-A")).not.toContainText("Среднее");  // identifiers are not summed
  await expect(page.getByTestId("profile-D")).toContainText("Среднее");
  await expect(page.getByTestId("dataset-rows")).toContainText("00001");  // leading zeros preserved
  await page.getByLabel("Поиск").fill("Шымкент");
  await page.getByRole("button", { name: "Искать" }).click();
  await expect(page.getByText("Найдено строк: 10")).toBeVisible();
  await page.getByLabel("Тип столбца Статус").selectOption("text");
  await expect(page.getByTestId("profile-E")).not.toContainText("закрыта");
  expect(errors).toEqual([]);
});

test("narrow screen: wide mapping and dataset pages have no horizontal page scroll", async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await ctx.newPage();
  await upload(page, path.join(EX, "example_wide_gradebook.xlsx"));
  await expect(page.getByTestId("wide-step")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(1);
  await page.getByTestId("cancel-import").click();
  await page.goto("/datasets");
  await expect(page.getByTestId("dataset-list")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(1);
  await ctx.close();
});
