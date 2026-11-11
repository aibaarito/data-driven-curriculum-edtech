// UX corrections from the 11 Nov 2026 design review (F1–F12). Runs after journey.spec.ts on the same isolated stack;
// imports the synthetic demo itself if the database is empty. AI responses are mocked — no provider is called.
import fs from "node:fs";
import path from "node:path";

import { expect, test, type Page, type Route } from "@playwright/test";

const DEMO = path.resolve(__dirname, "../../backend/app/assets/data/synthetic_assessments.csv");
const SHOTS = path.resolve(process.env.E2E_ARTIFACT_DIR ?? path.join(__dirname, "screenshots"));

test.describe.configure({ mode: "serial" });

let classId7A = 0;

test.beforeAll(async ({ request }) => {
  let meta = await (await request.get("/api/meta")).json();
  if (!meta.has_data) {
    const preview = await (await request.post("/api/imports/preview", {
      multipart: { file: { name: "demo.csv", mimeType: "text/csv", buffer: fs.readFileSync(DEMO) } },
    })).json();
    expect(preview.ok).toBe(true);
    expect((await request.post(`/api/imports/${preview.batch_id}/commit`)).ok()).toBe(true);
    meta = await (await request.get("/api/meta")).json();
  }
  classId7A = meta.classes.find((c: { name: string }) => c.name === "7А").id;
});

async function pickGrade(page: Page, label: string) {
  await page.locator("#f-grade").click();
  await page.getByRole("option", { name: label, exact: true }).click();
}

test("F5: analysis scope travels with navigation, unsupported filters are explained, Back restores scope", async ({ page }) => {
  await page.goto("/topics?grade=7");
  await expect(page.getByTestId("scope-summary").filter({ visible: true })).toContainText("7 класс");
  await page.getByRole("link", { name: "Сравнение учебников" }).first().click();
  await expect(page).toHaveURL(/\/textbooks\?grade=7$/);
  await expect(page.getByTestId("scope-summary").filter({ visible: true })).toContainText("7 класс");
  await page.getByRole("link", { name: "Отчёты" }).first().click();
  await expect(page).toHaveURL(/\/reports\?grade=7$/);
  await page.goBack();
  await expect(page).toHaveURL(/\/textbooks\?grade=7$/);
  await page.goBack();
  await expect(page).toHaveURL(/\/topics\?grade=7$/);

  // A class filter is kept but explained where it cannot apply.
  await page.goto(`/topics?grade=7&class_id=${classId7A}`);
  await expect(page.getByTestId("scope-summary").filter({ visible: true })).toContainText("класс 7А");
  await page.getByRole("link", { name: "Сравнение учебников" }).first().click();
  await expect(page.getByTestId("filters-not-applied").filter({ visible: true })).toContainText("класс 7А");
  await page.getByRole("link", { name: "Оптимизатор часов" }).first().click();
  await expect(page.getByTestId("plan-scope-note").filter({ visible: true })).toContainText("План составляется для всей параллели 7");
  await expect(page.getByTestId("plan-scope-note").filter({ visible: true })).toContainText("Здесь не применяется: класс 7А");
  await page.getByRole("link", { name: "Анализ тем" }).first().click();
  await expect(page).toHaveURL(new RegExp(`class_id=${classId7A}`));

  // Filter changes are history entries; Back returns to the previous scope.
  await page.goto("/topics?grade=7");
  await pickGrade(page, "8 класс");
  await expect(page).toHaveURL(/grade=8/);
  await page.goBack();
  await expect(page).toHaveURL(/\/topics\?grade=7$/);
  await expect(page.getByTestId("scope-summary").filter({ visible: true })).toContainText("7 класс");

  // Incompatible dependent values are reported (results are empty, never silently broadened).
  await page.goto(`/topics?grade=8&class_id=${classId7A}`);
  await expect(page.getByTestId("filter-conflicts").filter({ visible: true })).toContainText("Класс 7А относится к 7 параллели");
  await page.getByTestId("filter-conflicts").filter({ visible: true }).getByRole("button", { name: "Убрать этот фильтр" }).click();
  await expect(page).toHaveURL(/\/topics\?grade=8$/);

  // Clearing is explicit and predictable.
  await page.getByTestId("reset-filters").filter({ visible: true }).click();
  await expect(page).toHaveURL(/\/topics$/);
  await expect(page.getByTestId("scope-summary").filter({ visible: true })).toContainText("Все предметы · все параллели · все классы · весь период");
});

test("F1/F6/F11: overview leads with a qualified finding; assessments are not joined into one line", async ({ page }) => {
  await page.goto("/");
  const first = page.getByTestId("first-checks");
  await expect(first.getByTestId("priority-topic").first()).toContainText("Формулы сокращённого умножения");
  await expect(first.getByTestId("priority-topic").first()).toContainText("изменение не установлено");
  await expect(first.getByRole("link", { name: /Анализ темы/ }).first()).toHaveAttribute("href", /topic=T7-05/);
  await expect(page.getByText("Темы с самым низким освоением", { exact: true })).toBeVisible();

  await expect(page.getByTestId("trend-caution")).toContainText("Этот график не показывает индивидуальный прогресс");
  const chart = page.getByTestId("assessment-observations");
  await expect(chart).toHaveAttribute("data-series", "g7,g8");
  const strokes = await chart.locator("path.recharts-line-curve").evaluateAll((els) => els.map((e) => e.getAttribute("stroke")));
  expect(strokes.length).toBeGreaterThan(0);
  expect(strokes.every((s) => s === "none")).toBe(true); // markers only, no connecting line

  // Chart values are also available as text (no reliance on colour or hover).
  await page.getByText("Показать данные диаграммы таблицей").last().click();
  await expect(page.getByRole("table", { name: /Освоение по оцениваниям/ })).toContainText("8 класс");

  // Functional warning-colour marks meet 3:1 against the white card.
  const fills = await page.locator(".recharts-bar-rectangle path").evaluateAll((els) => [...new Set(els.map((e) => e.getAttribute("fill")))]);
  expect(fills).not.toContain("#f59e0b");
  await page.screenshot({ path: path.join(SHOTS, "ux-01-dashboard.png"), fullPage: true });

  // The first-check link opens the topic directly.
  await first.getByRole("link", { name: /Анализ темы/ }).first().click();
  await expect(page.getByTestId("topic-detail")).toContainText("Формулы сокращённого умножения");
});

function insightsBody(scope: string, overrides: Record<string, unknown> = {}) {
  return {
    mode: "deterministic", model: null, attempts: 0, fallback_reason: null, fallback_kind: "not_configured", fallback_detail: null,
    optimizer_status: null,
    facts: { "topic.T7-05.name": "Формулы сокращённого умножения", "topic.T7-05.mastery": 40.9 },
    payload: {
      summary: `Резюме для ${scope}`,
      findings: [{ entity: "topic.T7-05", title: "Трудная тема", text: "Освоение ниже порога.", kind: "observation", metric_keys: ["topic.T7-05.mastery"] }],
      limitations: ["Данные синтетические."], next_steps: ["Проверить задания."],
    },
    ...overrides,
  };
}

test("F2/F9: AI results stay bound to their scope; a slow old response cannot replace a newer one", async ({ page }) => {
  await page.route("**/api/ai/insights", async (route: Route) => {
    const body = route.request().postDataJSON() as { grade?: number };
    if (body.grade === 7) await new Promise((r) => setTimeout(r, 2500));
    try {
      await route.fulfill({ json: insightsBody(`${body.grade} класс`) });
    } catch {
      /* the browser aborted this request after the scope changed */
    }
  });
  await page.goto("/insights?grade=7");
  await expect(page.getByTestId("insights-request-scope")).toContainText("7 класс");
  await page.getByTestId("generate-insights").click();
  await expect(page.getByTestId("insights-status")).toContainText("Готовим пояснения для выбранной группы");
  await pickGrade(page, "8 класс");
  await expect(page.getByTestId("insights-interrupted")).toContainText("Фильтры изменены");
  await page.getByTestId("generate-insights").click();
  await expect(page.getByTestId("insights-result-scope")).toContainText("8 класс");
  await expect(page.getByTestId("insights-result")).toContainText("Резюме для 8 класс");
  await page.waitForTimeout(3000); // longer than the delayed grade-7 response
  await expect(page.getByTestId("insights-result")).toContainText("Резюме для 8 класс");
  await expect(page.getByTestId("insights-result")).not.toContainText("Резюме для 7 класс");

  // Changing filters marks the existing result as belonging to the previous group.
  await pickGrade(page, "7 класс");
  await expect(page.getByTestId("insights-stale")).toContainText("Фильтры изменены");
  await expect(page.getByTestId("insights-result-scope")).toContainText("8 класс");

  // Human-readable fact with unit and a link carrying the result's own scope; raw keys in details.
  const facts = page.getByTestId("finding-facts").first();
  await expect(facts).toContainText("Формулы сокращённого умножения — освоение");
  await expect(facts).toContainText("40,9%");
  await expect(facts.getByRole("link").first()).toHaveAttribute("href", "/topics?grade=8&topic=T7-05");
});

test("F9: waiting, provider failure, rejected output and model output are distinct", async ({ page }) => {
  let next: Record<string, unknown> = {};
  let hold = false;
  await page.route("**/api/ai/insights", async (route: Route) => {
    if (hold) await new Promise((r) => setTimeout(r, 1500));
    await route.fulfill({ json: insightsBody("7 класс", next) });
  });
  await page.goto("/insights?grade=7");

  hold = true;
  next = { fallback_kind: "provider_error", fallback_detail: "ConnectTimeout", attempts: 1,
    fallback_reason: "Сервис языковой модели недоступен или не ответил вовремя. Показаны пояснения по шаблонам; расчёты не изменились." };
  await page.getByTestId("generate-insights").click();
  await expect(page.getByRole("status").filter({ hasText: "Прошло" })).toBeVisible();
  await expect(page.getByTestId("stop-waiting")).toBeVisible();
  await expect(page.getByTestId("insights-mode-title")).toContainText("Модель недоступна — показаны пояснения по шаблонам");
  await expect(page.getByTestId("insights-mode-title")).not.toContainText("ConnectTimeout");
  await expect(page.getByTestId("insights-mode")).toHaveText("Числа сверены с расчётами");
  await expect(page.getByTestId("insights-result")).toContainText("не подтверждает причинные выводы");
  hold = false;

  next = { fallback_kind: "rejected", fallback_detail: "GroundingError", attempts: 2,
    fallback_reason: "Ответ модели отклонён проверкой соответствия расчётам. Показаны пояснения по шаблонам; расчёты не изменились." };
  await page.getByTestId("generate-insights").click();
  await expect(page.getByTestId("insights-mode-title")).toContainText("Ответ модели отклонён");

  next = { mode: "llm", model: "test-model", attempts: 1, fallback_kind: null, fallback_reason: null };
  await page.getByTestId("generate-insights").click();
  await expect(page.getByTestId("insights-mode-title")).toContainText("языковая модель (test-model)");

  // Stopping the wait is described honestly.
  hold = true;
  await page.getByTestId("generate-insights").click();
  await page.getByTestId("stop-waiting").click();
  await expect(page.getByTestId("insights-interrupted")).toContainText("Обработка на сервере могла продолжиться");
  await page.screenshot({ path: path.join(SHOTS, "ux-07-insights.png"), fullPage: true });
});

test("F3: manual evaluation never saves; opened saved run is distinct from the draft form", async ({ page }) => {
  await page.goto("/optimizer?grade=7");
  await page.getByTestId("run-optimizer").click();
  const accept = page.getByTestId("accept-run");
  const runId = await accept.getAttribute("data-run-id");
  await expect(page.getByTestId("manual-panel")).toContainText("Ручной вариант · проверка без сохранения");
  await expect(page.getByTestId("manual-panel")).toContainText(`Проверка не изменяет сохранённую рекомендацию #${runId}`);

  const writes: string[] = [];
  page.on("request", (r) => {
    if (r.method() !== "GET" && /\/optimizer\/(run|runs\/\d+\/decision)$/.test(new URL(r.url()).pathname)) writes.push(r.url());
  });
  await page.getByLabel("Ручной вариант: Линейная функция", { exact: true }).fill("10");
  const evaluated = page.waitForResponse((r) => r.url().endsWith("/api/optimizer/evaluate"));
  await page.getByTestId("evaluate-custom").click();
  await evaluated;
  await expect(page.getByTestId("manual-panel")).toContainText("не сохранён");
  expect(writes).toEqual([]);
  await expect(page.getByTestId("run-status")).toHaveText("Предложена");

  // Changed rows come first; all rows stay reachable.
  const rows = page.getByTestId("allocation-table").locator("tbody tr");
  const total = await rows.count();
  await page.getByRole("button", { name: "Показать только изменённые" }).click();
  expect(await rows.count()).toBeLessThanOrEqual(total);
  await page.getByRole("button", { name: /Показать все темы/ }).click();
  await expect(rows).toHaveCount(total);

  // Opening an earlier run from history is labelled as such, with its own total.
  await page.locator("#total").fill("80");
  await page.getByRole("button", { name: /^Открыть рекомендацию #/ }).last().click();
  await expect(page.getByTestId("optimizer-result")).toContainText("Открыта из истории");
  await expect(page.getByTestId("optimizer-result")).toContainText("Форма выше — черновик на 80 ч");
  await page.screenshot({ path: path.join(SHOTS, "ux-06-optimizer.png"), fullPage: true });
});

test("F10: narrow screens keep topic identity, change status and details together", async ({ browser }) => {
  for (const width of [390, 494]) {
    const ctx = await browser.newContext({ viewport: { width, height: 844 } });
    const page = await ctx.newPage();
    await page.goto("/topics?grade=7");
    const cards = page.getByTestId("topics-cards");
    await expect(cards).toBeVisible();
    const card = cards.locator("li").filter({ hasText: "Формулы сокращённого умножения" });
    await expect(card).toContainText("изменение не установлено");
    await expect(card).toContainText("Трудная");
    expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(1);

    const more = card.getByRole("button", { name: "Подробнее: Формулы сокращённого умножения" });
    await more.focus();
    await page.keyboard.press("Enter");
    const dialog = page.getByRole("dialog", { name: "Формулы сокращённого умножения" });
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText("Это не доказывает отсутствие эффекта.");
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(more).toBeFocused(); // focus returns to the opening control
    if (width === 390) await page.screenshot({ path: path.join(SHOTS, "ux-10-mobile-topics.png"), fullPage: false });

    // Optimizer editing on a narrow screen: tables scroll inside their container, the page does not.
    await page.goto("/optimizer?grade=7");
    await page.getByLabel("Часы: Линейная функция").fill("16");
    await expect(page.getByLabel("Часы: Линейная функция")).toHaveValue("16");
    expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(1);
    await ctx.close();
  }
});

test("F4/F12: an older snapshot without stored change status says so instead of inventing a conclusion", async ({ page }) => {
  await page.goto("/reports?grade=7");
  await page.getByTestId("create-report").click();
  await expect(page.getByTestId("report-view")).toBeVisible();
  const created = await (await page.request.get("/api/reports")).json();
  const id = created[0].id;
  const real = await (await page.request.get(`/api/reports/${id}`)).json();
  const legacy = structuredClone(real);
  legacy.title = "Аналитический отчёт — 10.11.2026 18:00";
  delete legacy.discussion;
  for (const t of legacy.content.topics) if (t.gain) delete t.gain.direction;
  await page.route(`**/api/reports/${id}`, (route) => route.fulfill({ json: legacy }));
  await page.reload();
  await page.getByTestId("report-list").locator("li").first().getByRole("button", { name: /^Открыть отчёт/ }).click();
  await expect(page.getByTestId("report-gain-T7-05")).toContainText("статус изменения в этом снимке не сохранён");
  await expect(page.getByTestId("report-gain-T7-05")).not.toContainText("изменение не установлено");
  await expect(page.getByTestId("report-discussion")).toHaveCount(0);
});

test("F8: textbook verdict keeps scope-specific interval levels and insufficient-evidence reasons visible", async ({ page }) => {
  const all = await (await page.request.get("/api/analytics/textbooks")).json();
  const g7 = await (await page.request.get("/api/analytics/textbooks?grade=7")).json();
  await page.goto("/textbooks");
  const levelAll = String(all.pairs[0].ci_level).replace(".", ",");
  await expect(page.getByTestId("textbook-pair").first().getByTestId("pair-verdict")).toContainText(`${levelAll}% ДИ`);
  await page.goto("/textbooks?grade=7");
  const level7 = String(g7.pairs[0].ci_level).replace(".", ",");
  await expect(page.getByTestId("textbook-pair").first().getByTestId("pair-verdict")).toContainText(`${level7}% ДИ`);
  await page.goto("/textbooks?grade=8");
  const pair8 = page.getByTestId("textbook-pair").first();
  await expect(pair8.getByTestId("pair-verdict")).toContainText("Недостаточно данных");
  await expect(pair8.getByTestId("pair-verdict").locator("li").first()).toBeVisible();
  await page.screenshot({ path: path.join(SHOTS, "ux-05-textbooks-grade8.png"), fullPage: true });
});
