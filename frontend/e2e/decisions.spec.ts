import fs from "node:fs";
import path from "node:path";

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

// Decision-intelligence journey on the isolated stack: diagnose → passport → graph → textbooks → scenarios →
// approve → intervention → (SIMULATED) follow-up → evaluation → stale detection → mobile layout.
const DATA = path.resolve(__dirname, "../../backend/app/assets/data");
const SHOTS = path.resolve(process.env.E2E_ARTIFACT_DIR ?? path.join(__dirname, "screenshots"));
fs.mkdirSync(SHOTS, { recursive: true });

function watchErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error" && !/Failed to load resource: .*status of (409|422)/.test(m.text())) errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

async function importFile(request: APIRequestContext, file: string) {
  const preview = await request.post("/api/imports/preview", {
    multipart: { file: { name: path.basename(file), mimeType: "text/csv", buffer: fs.readFileSync(file) } },
  });
  const body = await preview.json();
  expect(body.ok, JSON.stringify(body.errors?.slice(0, 2))).toBe(true);
  expect((await request.post(`/api/imports/${body.batch_id}/commit`)).ok()).toBeTruthy();
}

test.describe.configure({ mode: "serial" });

let subjectId = 0;

test.beforeAll(async ({ request }) => {
  const adminToken = process.env.E2E_ADMIN_TOKEN;
  if (!adminToken) throw new Error("E2E_ADMIN_TOKEN is required (the journey resets the dedicated E2E database)");
  const r = await request.post("/api/admin/reset", { data: { confirm: "УДАЛИТЬ" }, headers: { "X-Admin-Token": adminToken } });
  expect(r.ok()).toBeTruthy();
  await importFile(request, path.join(DATA, "synthetic_assessments.csv"));
  subjectId = (await (await request.get("/api/meta")).json()).subjects[0].id;
});

test("diagnose → evidence passport → curriculum map → textbook evidence", async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto(`/topics?subject_id=${subjectId}&grade=7`);
  await page.getByRole("row", { name: /Формулы сокращённого умножения/ }).first().click();
  const detail = page.getByTestId("topic-detail");
  await detail.getByRole("button", { name: /Паспорт доказательств/ }).click();
  const passport = page.getByTestId("evidence-passport");
  await expect(passport).toContainText("Освоение 40.9%");
  await expect(passport).toContainText("не доказывают его отсутствие");
  await expect(page.getByTestId("passport-fingerprint")).toContainText("СИНТЕТИЧЕСКИЕ");
  await expect(passport).toContainText("Пересмотреть методику");
  await page.screenshot({ path: path.join(SHOTS, "di-01-passport.png") });
  await page.keyboard.press("Escape");

  await page.goto(`/curriculum?subject_id=${subjectId}&grade=7`);
  const node = page.getByTestId("node-T7-05");
  await node.focus();
  await page.keyboard.press("Enter"); // keyboard selection
  await expect(page.getByTestId("selected-topic")).toContainText("Формулы сокращённого умножения");
  await expect(page.getByTestId("why-priority")).toContainText("причинное влияние");
  await expect(page).toHaveURL(/topic=\d+/);
  await page.getByTestId("chain").first().click();
  await expect(page.getByTestId("graph-table")).toContainText("слабый пререквизит");
  await page.screenshot({ path: path.join(SHOTS, "di-02-curriculum-map.png"), fullPage: true });
  await page.reload();
  await expect(page.getByTestId("selected-topic")).toContainText("Формулы сокращённого умножения"); // URL-persisted

  await page.goto(`/textbooks?subject_id=${subjectId}&grade=7`);
  await page.getByTestId("pair-passport").click();
  await expect(page.getByTestId("passport-gate")).toContainText("Предварительные данные");
  await page.keyboard.press("Escape");
  await page.goto(`/textbooks?subject_id=${subjectId}&grade=8`);
  await expect(page.getByTestId("evidence-insufficient")).toBeVisible();
  expect(errors).toEqual([]);
});

test("scenarios → approve → intervention → simulated outcome → stale detection", async ({ page, request }) => {
  const errors = watchErrors(page);
  await page.goto(`/scenarios?subject_id=${subjectId}&grade=7`);
  await page.getByTestId("scenarios-preview").click();
  for (const k of ["conservative", "balanced", "gap_focused"]) {
    await expect(page.getByTestId(`scenario-${k}`)).toContainText("82 ч");
    await expect(page.getByTestId(`scenario-${k}`)).toContainText("рассчитан");
  }
  await expect(page.getByTestId("scenario-table")).toContainText("Формулы сокращённого умножения");
  expect(await (await request.get("/api/optimizer/runs")).json()).toEqual([]); // preview never persists
  await page.screenshot({ path: path.join(SHOTS, "di-03-scenarios.png"), fullPage: true });

  // a hard infeasibility is shown per scenario, not as a generic failure
  await page.getByLabel("Бюджет часов").fill("10");
  await page.getByTestId("scenarios-preview").click();
  await expect(page.getByTestId("scenario-balanced")).toContainText("INFEASIBLE");
  await page.getByLabel("Бюджет часов").fill("82");
  await page.getByTestId("scenarios-preview").click();
  await expect(page.getByTestId("scenario-gap_focused")).toContainText("рассчитан");

  await page.getByTestId("save-gap_focused").click();
  await expect(page.getByTestId("saved-gap_focused")).toContainText("рекомендация №");
  const runs = await (await request.get("/api/optimizer/runs")).json();
  expect(runs).toHaveLength(1);
  const runId = runs[0].run_id;
  expect(runs[0].scenario_key).toBe("gap_focused");

  await page.getByTestId("saved-gap_focused").getByRole("link").click();
  await expect(page).toHaveURL(/\/decisions/);
  await expect(page.getByTestId("candidate-T7-05").getByTestId("candidate-action")).toHaveText("Пересмотреть методику преподавания темы");
  await expect(page.getByTestId("candidate-T7-06").getByTestId("candidate-action")).toContainText("Увеличить часы");
  await page.screenshot({ path: path.join(SHOTS, "di-04-decision-center.png"), fullPage: true });
  await page.getByTestId(`accept-${runId}`).click();
  await expect(page.getByTestId(`run-${runId}`)).toContainText("Принята");
  await page.getByTestId(`plan-${runId}`).click();
  const iv = page.locator("[data-testid^=intervention-]").first();
  await expect(iv.getByTestId("iv-status")).toHaveText("Запланировано");
  await iv.getByLabel("Фактическая дата внедрения").fill("2026-09-01");
  await iv.getByTestId("iv-implement").click();
  await expect(iv.getByTestId("iv-status")).toHaveText("Внедрено");
  await iv.getByTestId("iv-await").click();
  await expect(iv.getByTestId("iv-status")).toHaveText("Ожидает данных");
  await iv.getByTestId("iv-evaluate").click();
  await expect(iv.getByTestId("iv-not-ready")).toBeVisible(); // honest: no post-implementation data yet

  // explicitly SIMULATED follow-up assessment (backend/scripts/generate_followup.py)
  await importFile(request, path.join(DATA, "synthetic_followup.csv"));
  await page.reload();
  const iv2 = page.locator("[data-testid^=intervention-]").first();
  await iv2.getByTestId("iv-evaluate").click();
  await expect(iv2.getByTestId("iv-status")).toHaveText("Оценено");
  const ev = iv2.getByTestId("iv-evaluation");
  await expect(ev).toContainText("НЕ доказывает");
  await expect(ev).toContainText("синтетические");
  await expect(ev).toContainText("40,9%");
  await page.screenshot({ path: path.join(SHOTS, "di-05-intervention.png"), fullPage: true });

  // the approved run keeps its frozen evidence and is now labelled stale (new data arrived)
  const detail = await (await request.get(`/api/optimizer/runs/${runId}`)).json();
  expect(detail.evidence_status).toBe("stale");
  expect(detail.evidence_snapshot.topics.find((t: { code: string }) => t.code === "T7-05").mastery).toBe(40.9);
  await expect(page.getByTestId(`run-${runId}`).getByTestId("evidence-stale")).toBeVisible();
  expect(errors).toEqual([]);
});

test("decision screens work at 390px without horizontal page scroll", async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, locale: "ru-RU" });
  const page = await ctx.newPage();
  for (const p of ["/decisions", "/curriculum", "/scenarios"]) {
    await page.goto(`${p}?subject_id=${subjectId}&grade=7`);
    await expect(page.locator("h1")).toBeVisible();
    await page.waitForLoadState("networkidle");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, p).toBeLessThanOrEqual(1);
  }
  await page.goto(`/curriculum?subject_id=${subjectId}&grade=7`);
  await expect(page.getByTestId("graph-table")).toBeVisible(); // accessible fallback present on mobile
  await page.screenshot({ path: path.join(SHOTS, "di-06-mobile-curriculum.png"), fullPage: true });
  await ctx.close();
});
