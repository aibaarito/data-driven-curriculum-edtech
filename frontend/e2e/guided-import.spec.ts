import fs from "node:fs";
import path from "node:path";

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

// Guided import journeys on the isolated E2E stack (the database is reset first; see playwright.config.ts).
const TEMPLATE = path.resolve(__dirname, "../../backend/app/assets/data/template.csv");
const EXAMPLE = path.resolve(__dirname, "../../backend/app/assets/data/example_guided_import.xlsx");
const SHOTS = path.resolve(process.env.E2E_ARTIFACT_DIR ?? path.join(__dirname, "screenshots"));
fs.mkdirSync(SHOTS, { recursive: true });

test.describe.configure({ mode: "serial" });

function watchErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => {
    // Handled 4xx API answers (deliberate stale commit / configuration checks) are logged by the browser.
    if (m.type() === "error" && !/Failed to load resource: .*status of (409|422)/.test(m.text())) errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

async function dataState(request: APIRequestContext) {
  const ov = await (await request.get("/api/analytics/overview")).json();
  const meta = await (await request.get("/api/meta")).json();
  return { overview: ov.overview, subjects: meta.subjects.map((s: { name: string }) => s.name).sort() };
}

async function upload(page: Page, file: string | { name: string; mimeType: string; buffer: Buffer }) {
  await page.goto("/import");
  await page.getByTestId("file-input").setInputFiles(file);
  await page.getByTestId("validate-button").click();
  await expect(page.getByTestId("prepare-panel")).toBeVisible();
}

async function prepareExample(page: Page) {
  await upload(page, EXAMPLE);
  await expect(page.getByTestId("sheet-step").getByLabel(/Результаты/)).toBeChecked();
  await expect(page.getByTestId("sheet-step")).toContainText("скрытый лист");
  await expect(page.getByLabel("Строка с названиями столбцов")).toHaveValue("3");
  await expect(page.getByLabel("Идентификатор ученика")).toHaveValue("c0");
  await expect(page.getByTestId("field-textbook_id")).toContainText("Возможные столбцы: J «Учебник»");
  await expect(page.getByTestId("run-validation")).toBeDisabled();
  await page.getByLabel("Предмет", { exact: true }).selectOption("__value");
  await page.getByLabel("Значение для всех строк: Предмет").fill("Математика");
  await page.getByLabel("Тип оценивания", { exact: true }).selectOption("__value");
  await page.getByLabel("Значение для всех строк: Тип оценивания").selectOption("pre");
  await page.getByLabel("Идентификатор учебника").selectOption("c9");
  await expect(page.getByTestId("run-validation")).toBeDisabled();
  await page.getByTestId("confirm-shared").check();
  await page.getByTestId("run-validation").click();
  await expect(page.getByTestId("import-preview")).toContainText("Файл прошёл проверку");
}

test.beforeAll(async ({ request }) => {
  const adminToken = process.env.E2E_ADMIN_TOKEN;
  if (!adminToken) throw new Error("E2E_ADMIN_TOKEN is required (the scenario resets the dedicated E2E database)");
  const r = await request.post("/api/admin/reset", { data: { confirm: "УДАЛИТЬ" }, headers: { "X-Admin-Token": adminToken } });
  expect(r.ok()).toBeTruthy();
});

test("1. standard template: preselected, validated automatically, then imported", async ({ page, request }) => {
  const errors = watchErrors(page);
  await upload(page, TEMPLATE);
  const preview = page.getByTestId("import-preview");
  await expect(preview).toContainText("Файл прошёл проверку");
  await expect(page.getByTestId("prepare-panel")).toContainText("распознан шаблон");
  await expect(page.getByTestId("confirm-summary")).toContainText("Строка заголовка1");
  await shot(page, "guided-01-template");
  await page.getByTestId("commit-button").click();
  await expect(page.getByTestId("import-success")).toBeVisible();
  expect((await dataState(request)).subjects).toEqual(["Математика"]);
  expect(errors).toEqual([]);
});

test("5. cancelled preparation leaves existing data unchanged", async ({ page, request }) => {
  const before = await dataState(request);
  await prepareExample(page);
  await page.getByRole("button", { name: "Отменить" }).last().click();
  await expect(page.getByTestId("prepare-panel")).toHaveCount(0);
  expect(await dataState(request)).toEqual(before);
  const history = await (await request.get("/api/imports")).json();
  expect(history[0].status).toBe("discarded");
});

test("4. a mapping change after validation invalidates the result; the old result cannot be committed", async ({ page, request }) => {
  const before = await dataState(request);
  let lastValidation: { batch_id: number; config_hash: string } | null = null;
  page.on("response", async (r) => {
    if (r.url().endsWith("/validate") && r.ok()) lastValidation = await r.json();
  });
  let sessionKey = "";
  page.on("response", async (r) => {
    if (r.url().endsWith("/api/imports/sources") && r.ok()) sessionKey = (await r.json()).session_key;
  });
  await prepareExample(page);
  await expect(page.getByTestId("commit-button")).toBeEnabled();
  const stale = lastValidation!;
  await page.getByLabel("Идентификатор учебника").selectOption("__none");
  await expect(page.getByTestId("commit-button")).toHaveCount(0);
  await expect(page.getByTestId("stale-notice")).toContainText("Предпросмотр устарел");
  // Revalidate with the new mapping, then try the stale hash directly: the server refuses it.
  await page.getByTestId("run-validation").click();
  await expect(page.getByTestId("import-preview")).toContainText("Файл прошёл проверку");
  const r = await request.post(`/api/imports/${stale.batch_id}/commit`, { data: { session_key: sessionKey, config_hash: stale.config_hash } });
  expect(r.status()).toBe(409);
  expect((await r.json()).detail.code).toBe("STALE_PREVIEW");
  expect(await dataState(request)).toEqual(before);
  await page.getByRole("button", { name: "Отменить" }).last().click();
});

test("3. missing required data gives actionable errors and keeps the import blocked", async ({ page, request }) => {
  const errors = watchErrors(page);
  const before = await dataState(request);
  const csv = [
    "Результаты контрольной (синтетические)",
    "",
    "Код ученика;Параллель;Класс;Предмет;Код темы;Тема;Код работы;Тип оценивания;Дата;Баллы;Максимальный балл;Код учебника",
    "SYN-1;7;7А;Математика;SYN-T1;Тема 1;SYN-KR;post;20.05.2026;3;4;SYN-TB-A",
    "SYN-2;7;7А;Математика;SYN-T1;Тема 1;SYN-KR;post;20.05.2026;;4;SYN-TB-A",
    "SYN-3;7;7А;Математика;SYN-T1;Тема 1;SYN-KR;post;20.05.2026;9;4;SYN-TB-A",
  ].join("\n");
  await upload(page, { name: "контрольная.csv", mimeType: "text/csv", buffer: Buffer.from(csv, "utf-8") });
  // Header in row 3 is recognised and every field resolved: validation runs automatically.
  const groups = page.getByTestId("issue-groups");
  await expect(groups).toContainText("Строка 5");
  await expect(groups).toContainText("Не заполнено обязательное значение");
  await expect(groups).toContainText("Строка 6");
  await expect(groups).toContainText("Балл больше максимального");
  await expect(groups).toContainText("столбец J «Баллы»");
  await expect(page.getByTestId("record-counts")).toContainText("Найдено записей3");
  await expect(page.getByTestId("record-counts")).toContainText("С ошибками2");
  await expect(page.getByTestId("commit-button")).toBeDisabled();
  // Clearing a required mapping blocks the check with a field-level message instead of a combined column list.
  await page.getByTestId("prepare-toggle").click();
  await page.getByLabel("Полученный балл").selectOption("");
  await expect(page.getByTestId("run-validation")).toBeDisabled();
  await expect(page.getByTestId("field-score")).toContainText("Выберите столбец для поля «Полученный балл»");
  await shot(page, "guided-03-missing");
  expect(await dataState(request)).toEqual(before);
  expect(errors).toEqual([]);
});

test("2. multi-sheet workbook with a title row and Russian headers is mapped and imported", async ({ page, request }) => {
  const errors = watchErrors(page);
  await prepareExample(page);
  const summary = page.getByTestId("confirm-summary");
  await expect(summary).toContainText("ЛистРезультаты");
  await expect(summary).toContainText("Строка заголовка3");
  await expect(summary).toContainText("Предмет: Математика; Тип оценивания: pre");
  await expect(summary).toContainText("Примечание");
  await expect(page.getByTestId("record-counts")).toContainText("Будет импортировано36");
  await shot(page, "guided-02-confirm");
  await page.getByTestId("commit-button").click();
  await expect(page.getByTestId("import-success")).toContainText("Добавлено записей: 36");
  const ov = (await dataState(request)).overview;
  expect(ov.students).toBeGreaterThanOrEqual(12);
  expect(errors).toEqual([]);
});

test("narrow screen: mapping controls stay usable without horizontal page scroll", async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await ctx.newPage();
  await upload(page, EXAMPLE);
  const subject = page.getByLabel("Предмет", { exact: true });
  await subject.focus();
  await expect(subject).toBeFocused();
  await subject.selectOption("__value");
  await expect(page.getByLabel("Значение для всех строк: Предмет")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  await page.screenshot({ path: path.join(SHOTS, "guided-06-mobile.png"), fullPage: true });
  await page.getByRole("button", { name: "Отменить" }).last().click();
  await ctx.close();
});

async function shot(page: Page, name: string) {
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: true });
}
