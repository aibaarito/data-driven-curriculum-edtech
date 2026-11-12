import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MetaProvider } from "@/components/meta-provider";
import type { ImportFieldInfo, ImportSource, SheetInspection } from "@/lib/types";

import { ImportView } from "./import-view";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));
const uploadMock = vi.fn();
vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), uploadFile: (...a: unknown[]) => uploadMock(...a) }));

const META = { subjects: [], grades: [], classes: [], textbooks: [], date_from: null, date_to: null, synthetic: false, has_data: false };
const f = (field: string, label: string, required: boolean, shared = false, none = false): ImportFieldInfo =>
  ({ field, label, description: `Описание ${label}`, required, shared_allowed: shared, none_allowed: none });
const FIELDS: ImportFieldInfo[] = [
  f("student_id", "Идентификатор ученика", true), f("subject", "Предмет", true, true), f("score", "Полученный балл", true),
  f("textbook_id", "Идентификатор учебника", true, false, true), f("item_id", "Код задания", false, false, true),
];
const HEADERS = ["Код ученика", "Баллы", "Учебник", "Примечание"];

function inspection(headerRow = 3, extra: Partial<SheetInspection> = {}): SheetInspection {
  return {
    sheet: "Результаты", hidden: false, problem: null, width: 4,
    header_suggestion: { row: 3, confidence: "high", reason: "В строке 3 найдено 3 знакомых названий столбцов." },
    preview: [{ row: 1, cells: ["Отчёт"] }, { row: 3, cells: HEADERS }, { row: 4, cells: ["SYN-1", "3", "SYN-TB", ""] }],
    header_rows_allowed: [1, 3, 4], header_row: headerRow,
    columns: HEADERS.map((h, i) => ({ id: `c${i}`, letter: "ABCD"[i], header: h, label: h, samples: [["SYN-1", "3", "SYN-TB", ""][i]].filter(Boolean), empty: i === 3 })),
    suggestions: { suggested: { student_id: { column: "c0", confidence: "alias" }, score: { column: "c1", confidence: "alias" } },
      ambiguous: { textbook_id: [{ column: "c2", reason: "Может быть кодом учебника или его названием." }] } },
    notices: [], duplicate_headers: [], ...extra,
  };
}

const SOURCE: ImportSource = {
  batch_id: 7, session_key: "key-7", filename: "школа.xlsx", kind: "xlsx", expires_at: "2026-11-12T12:00:00Z",
  sheets: [
    { name: "Пояснение", hidden: false, empty: false, non_empty_rows: 2, columns: 1, problem: null, known_headers: 0 },
    { name: "Результаты", hidden: false, empty: false, non_empty_rows: 30, columns: 4, problem: null, known_headers: 3 },
    { name: "Служебный", hidden: true, empty: false, non_empty_rows: 2, columns: 2, problem: null, known_headers: 0 },
  ],
  sheet_suggestion: { name: "Результаты", reason: "На этом листе больше всего знакомых названий столбцов." },
  inspection: inspection(), auto_ready: false, fields: FIELDS,
  catalog: {
    layouts: [], date_formats: ["auto"], encodings: ["auto"], delimiters: [],
    aggregate_roles: [{ value: "class", label: "Класс" }, { value: "value", label: "Показатель" }],
    types: ["number", "date", "category", "text", "identifier", "boolean"].map((t) => ({ value: t, label: t })),
    flags: [{ value: "total", label: "итоговая строка" }, { value: "note", label: "пояснительный текст" }],
  },
  limits: { max_upload_mb: 10, max_rows: 200000, max_columns: 200, max_sheets: 50, header_scan_rows: 50, preview_ttl_minutes: 60 },
};

const REPORT = {
  batch_id: 7, filename: "школа.xlsx", ok: true, total_rows: 2, valid_rows: 2, error_count: 0, warning_count: 0,
  records_validated: true, rows_with_errors: 0, error_counts: {}, warning_counts: {}, errors: [], warnings: [],
  summary: { students: 2, classes: 1, topics: 1, assessments: 1, textbooks: ["SYN-TB"], date_from: "2026-09-15", date_to: "2026-09-15", item_level: false },
  columns_found: [], preview: [{ row: 4, student_id: "SYN-1" }], config_hash: "hash-1", expires_at: "2026-11-12T12:00:00Z",
  config: { sheet: "Результаты", sheet_hidden: false, header_row: 3, mapped: [], shared: [{ field: "subject", label: "Предмет", value: "Математика" }],
    not_in_file: [], ignored_columns: ["Примечание"] },
};

type Call = { url: string; body: Record<string, unknown> };
let calls: Call[] = [];
let responder: (url: string, body: Record<string, unknown>) => { status: number; body: unknown } | undefined;

beforeEach(() => {
  calls = [];
  responder = () => undefined;
  uploadMock.mockReset();
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const body = init?.body ? JSON.parse(String(init.body)) : {};
    if (init?.method === "POST") calls.push({ url, body });
    const custom = responder(url, body);
    if (custom) return new Response(JSON.stringify(custom.body), { status: custom.status });
    if (url.includes("/inspect")) return new Response(JSON.stringify({ inspection: inspection(body.header_row as number ?? 3) }), { status: 200 });
    if (url.includes("/validate")) return new Response(JSON.stringify(REPORT), { status: 200 });
    if (url.includes("/commit")) return new Response(JSON.stringify({ inserted_rows: 2, skipped_rows: 0 }), { status: 200 });
    if (url.endsWith("/api/imports")) return new Response("[]", { status: 200 });
    return new Response(JSON.stringify(META), { status: 200 });
  }));
});
afterEach(() => vi.unstubAllGlobals());

async function uploadWorkbook(src: ImportSource = SOURCE) {
  uploadMock.mockResolvedValueOnce(src);
  const user = userEvent.setup();
  render(<MetaProvider><ImportView /></MetaProvider>);
  await user.upload(screen.getByTestId("file-input"), new File(["x"], "школа.xlsx"));
  await user.click(screen.getByTestId("validate-button"));
  await screen.findByTestId("prepare-panel");
  return user;
}

describe("guided import wizard", () => {
  it("shows worksheets with hidden labels and the suggested sheet and header row", async () => {
    await uploadWorkbook();
    const sheets = screen.getByTestId("sheet-step");
    expect(within(sheets).getByLabelText(/Результаты/)).toBeChecked();
    expect(within(sheets).getByText("скрытый лист")).toBeInTheDocument();
    expect(screen.getByLabelText("Строка с названиями столбцов")).toHaveValue("3");
    expect(screen.getByRole("region", { name: "Первые строки листа" })).toHaveTextContent("Отчёт");
  });

  it("blocks validation until required fields are resolved, then sends an explicit configuration", async () => {
    const user = await uploadWorkbook();
    const run = screen.getByTestId("run-validation");
    expect(run).toBeDisabled();
    // Required-field errors are associated with their controls.
    const subject = screen.getByLabelText("Предмет");
    expect(subject).toHaveAttribute("aria-invalid", "true");
    const problemId = subject.getAttribute("aria-describedby")!.split(" ").find((x) => x.endsWith("-problem"))!;
    expect(document.getElementById(problemId)).toHaveTextContent("Выберите столбец для поля «Предмет»");
    // Ambiguous textbook column is listed but not preselected.
    expect(screen.getByLabelText("Идентификатор учебника")).toHaveValue("");
    expect(screen.getByTestId("field-textbook_id")).toHaveTextContent("Возможные столбцы: C «Учебник»");

    await user.selectOptions(subject, "__value");
    await user.type(screen.getByLabelText("Значение для всех строк: Предмет"), "Математика");
    await user.selectOptions(screen.getByLabelText("Идентификатор учебника"), "c2");
    expect(run).toBeDisabled(); // shared value not yet confirmed
    await user.click(screen.getByTestId("confirm-shared"));
    expect(run).toBeEnabled();
    await user.click(run);

    await screen.findByTestId("import-preview");
    const v = calls.find((c) => c.url.includes("/validate"))!;
    expect(v.body).toEqual({ session_key: "key-7", sheet: "Результаты", header_row: 3, header_rows: 1, first_col: 0, last_col: null,
      last_row: null, exclude: [], csv: { encoding: "auto", delimiter: "auto" }, layout: "long", confirm_shared: true,
      rules: { decimal: "auto", date_format: "auto", missing_markers: [], score_mode: "points", percent_scale: "0-100",
        true_tokens: [], false_tokens: [], scale: {} },
      fields: {
        student_id: { source: "column", column: "c0" }, score: { source: "column", column: "c1" },
        subject: { source: "value", value: "Математика" }, textbook_id: { source: "column", column: "c2" } } });
    expect(screen.getByTestId("confirm-summary")).toHaveTextContent("Предмет: Математика");
    expect(screen.getByTestId("confirm-summary")).toHaveTextContent("Примечание");

    await user.click(screen.getByTestId("commit-button"));
    await screen.findByTestId("import-success");
    expect(calls.find((c) => c.url.includes("/commit"))!.body).toEqual({ session_key: "key-7", config_hash: "hash-1" });
  });

  it("prevents reusing one column for two fields and lets the user correct a suggestion", async () => {
    const user = await uploadWorkbook();
    const score = screen.getByLabelText("Полученный балл");
    const opt = within(score).getByRole("option", { name: /A · Код ученика/ });
    expect(opt).toBeDisabled();
    expect(opt).toHaveTextContent("уже выбран для «Идентификатор ученика»");
    await user.selectOptions(screen.getByLabelText("Идентификатор ученика"), "");
    expect(within(score).getByRole("option", { name: /A · Код ученика/ })).toBeEnabled();
    await user.selectOptions(score, "c0");
    expect(score).toHaveValue("c0");
  });

  it("invalidates a validation result after a mapping change and requires a new check before import", async () => {
    const user = await uploadWorkbook({ ...SOURCE, inspection: inspection(3, { suggestions: {
      suggested: { student_id: { column: "c0", confidence: "alias" }, score: { column: "c1", confidence: "alias" } }, ambiguous: {} } }) });
    await user.selectOptions(screen.getByLabelText("Предмет"), "__value");
    await user.type(screen.getByLabelText("Значение для всех строк: Предмет"), "Математика");
    await user.selectOptions(screen.getByLabelText("Идентификатор учебника"), "__none");
    await user.click(screen.getByTestId("confirm-shared"));
    await user.click(screen.getByTestId("run-validation"));
    await screen.findByTestId("commit-button");

    await user.selectOptions(screen.getByLabelText("Код задания"), "c3");
    expect(screen.queryByTestId("commit-button")).not.toBeInTheDocument();
    expect(screen.getByTestId("stale-notice")).toHaveTextContent("Предпросмотр устарел после изменения: изменено сопоставление");
    expect(screen.getByRole("status")).toHaveTextContent("Предпросмотр устарел");
  });

  it("changing the header row re-inspects and keeps unchanged columns", async () => {
    const user = await uploadWorkbook();
    await user.selectOptions(screen.getByLabelText("Строка с названиями столбцов"), "4");
    await waitFor(() => expect(calls.some((c) => c.url.includes("/inspect") && c.body.header_row === 4)).toBe(true));
    await waitFor(() => expect(screen.getByLabelText("Строка с названиями столбцов")).toHaveValue("4"));
    expect(screen.getByLabelText("Идентификатор ученика")).toHaveValue("c0");
  });

  it("selecting another worksheet re-inspects it and resets the mapping", async () => {
    const user = await uploadWorkbook();
    await user.click(screen.getByLabelText(/Служебный/));
    await waitFor(() => expect(calls.some((c) => c.url.includes("/inspect") && c.body.sheet === "Служебный")).toBe(true));
  });

  it("shows configuration problems returned by the server next to the field", async () => {
    responder = (url) => url.includes("/validate") ? { status: 422, body: { detail: { code: "INVALID_CONFIGURATION",
      message: "Сопоставление не завершено или содержит ошибки.",
      issues: [{ code: "INVALID_SHARED_VALUE", message: "Недопустимое значение предмета.", field: "subject", column: null }] } } } : undefined;
    const user = await uploadWorkbook();
    await user.selectOptions(screen.getByLabelText("Предмет"), "__value");
    await user.type(screen.getByLabelText("Значение для всех строк: Предмет"), "X");
    await user.selectOptions(screen.getByLabelText("Идентификатор учебника"), "__none");
    await user.click(screen.getByTestId("confirm-shared"));
    await user.click(screen.getByTestId("run-validation"));
    expect(await screen.findByText("Недопустимое значение предмета.")).toBeInTheDocument();
    expect(screen.queryByTestId("import-preview")).not.toBeInTheDocument();
  });

  it("auto-validates an unambiguous template and shows original row numbers with the sheet name", async () => {
    responder = (url) => url.includes("/validate") ? { status: 200, body: { ...REPORT, ok: false, valid_rows: 0, error_count: 1, rows_with_errors: 1,
      error_counts: { SCORE_EXCEEDS_MAX: 1 }, errors: [{ row: 18, column: "score", code: "SCORE_EXCEEDS_MAX", message: "Балл 9 превышает максимум 4." }],
      config: { ...REPORT.config, mapped: [{ field: "score", label: "Полученный балл", column: "c1", letter: "B", header: "Баллы" }] } } } : undefined;
    await uploadWorkbook({ ...SOURCE, auto_ready: true, inspection: inspection(3, { suggestions: { suggested: {
      student_id: { column: "c0", confidence: "exact" }, subject: { column: "c3", confidence: "exact" }, score: { column: "c1", confidence: "exact" },
      textbook_id: { column: "c2", confidence: "exact" } }, ambiguous: {} } }) });
    const groups = await screen.findByTestId("issue-groups");
    expect(groups).toHaveTextContent("Лист «Результаты», строка 18");
    expect(groups).toHaveTextContent("столбец B «Баллы»");
    expect(screen.getByTestId("record-counts")).toHaveTextContent("С ошибками1");
    expect(screen.getByTestId("commit-button")).toBeDisabled();
  });

  it("explains an expired preview and returns to the upload step", async () => {
    responder = (url) => url.includes("/inspect") ? { status: 410, body: { detail: { code: "PREVIEW_EXPIRED",
      message: "Срок действия предпросмотра истёк. Загрузите файл заново." } } } : undefined;
    const user = await uploadWorkbook();
    await user.selectOptions(screen.getByLabelText("Строка с названиями столбцов"), "4");
    expect(await screen.findByTestId("import-error")).toHaveTextContent("Предпросмотр устарел — загрузите файл заново");
    expect(screen.queryByTestId("prepare-panel")).not.toBeInTheDocument();
  });
});

describe("flexible layouts in the wizard", () => {
  const WIDE_INS = inspection(3, {
    layout_suggestion: { layout: "wide", confidence: "medium", reason: "Журнал." },
    flags: [{ row: 9, kind: "total", label: "итоговая строка" }], flag_counts: { total: 1 },
    wide_suggestion: { identity: {}, total_columns: [], result_columns: [{ column: "c1", topic_name: "Баллы", item_hint: "" }] },
    suggestions: { suggested: { student_id: { column: "c0", confidence: "alias" } }, ambiguous: {} },
    all_columns: [0, 1, 2, 3].map((i) => ({ index: i, letter: "ABCD"[i] })),
  });

  it("shows the suggested wide layout with editable result columns and flagged rows", async () => {
    const user = await uploadWorkbook({ ...SOURCE, inspection: WIDE_INS });
    expect(screen.getByTestId("layout-wide")).toBeChecked();
    const rc = screen.getByTestId("result-c1");
    expect(within(rc).getByLabelText("Название темы")).toHaveValue("Баллы");
    expect(within(rc).getByText("Укажите код темы.")).toBeInTheDocument();
    expect(screen.getByTestId("flagged-rows")).toHaveTextContent("итоговая строка — 1 (строки 9)");
    await user.click(screen.getByTestId("exclude-total"));
    expect(screen.getByTestId("exclude-total")).toBeChecked();
    await user.click(screen.getByRole("button", { name: "Заполнить пустые коды тем из названий" }));
    expect(within(rc).getByLabelText("Код темы")).toHaveValue("BALLY");
  });

  it("switching to a general table hides the assessment mapping and sends confirmed types", async () => {
    const user = await uploadWorkbook({ ...SOURCE, inspection: { ...WIDE_INS, type_suggestion: { c0: "identifier", c1: "number", c2: "text", c3: "text" } } });
    await user.click(screen.getByTestId("layout-general"));
    expect(screen.queryByTestId("mapping-step")).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText(/B · Баллы/), "category");
    await user.click(screen.getByTestId("run-validation"));
    const v = calls.find((c) => c.url.includes("/validate"))!;
    expect(v.body).toMatchObject({ layout: "general", types: { c0: "identifier", c1: "category" }, fields: {} });
  });
});
