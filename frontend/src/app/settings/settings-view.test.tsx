import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MetaProvider } from "@/components/meta-provider";

import { SettingsView } from "./settings-view";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));

const SETTINGS = {
  analysis: { difficult_threshold: 50, watch_threshold: 65, target_mastery: 75, min_students_topic: 10,
    min_students_textbook: 20, min_classes_textbook: 3, max_change_pct: 25 },
  notices: [], llm: { enabled: false, provider: null, model: null },
  limits: { max_upload_mb: 10, max_upload_rows: 200000, preview_ttl_minutes: 60 },
  access: { mode: "token", reset_enabled: false },
};
const META = { subjects: [], grades: [], classes: [], textbooks: [], date_from: null, date_to: null, synthetic: true, has_data: true };

afterEach(() => vi.unstubAllGlobals());

describe("F11 settings form accessibility", () => {
  it("links every field to its help text, announces errors and focuses the first invalid field", async () => {
    const put = vi.fn();
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "PUT") put();
      const body = url.includes("/api/settings") ? SETTINGS : META;
      return new Response(JSON.stringify(body), { status: 200 });
    }));
    render(<MetaProvider><SettingsView /></MetaProvider>);

    const difficult = await screen.findByLabelText("Порог «трудная тема», %");
    await waitFor(() => expect(difficult).toHaveValue(50));
    const hint = document.getElementById(difficult.getAttribute("aria-describedby")!.split(" ").pop()!);
    expect(hint).toHaveTextContent("Освоение ниже — тема трудная");

    const classes = screen.getByLabelText("Мин. классов на учебник");
    await userEvent.clear(classes);
    await userEvent.type(classes, "2");
    await userEvent.clear(difficult);
    await userEvent.type(difficult, "90"); // above the watch threshold
    await userEvent.click(screen.getByRole("button", { name: /Сохранить/ }));

    await waitFor(() => expect(difficult).toHaveFocus());
    expect(difficult).toHaveAttribute("aria-invalid", "true");
    const errId = difficult.getAttribute("aria-errormessage")!;
    expect(document.getElementById(errId)).toHaveTextContent("не может быть выше");
    expect(classes.getAttribute("aria-describedby")).toContain("min_classes_textbook-error");
    expect(document.getElementById("min_classes_textbook-error")).toHaveTextContent("не менее трёх классов");
    expect(screen.getByTestId("settings-error-summary")).toHaveTextContent("Настройки не сохранены: исправьте поля (2)");
    expect(put).not.toHaveBeenCalled();
  });
});
