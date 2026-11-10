import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";

import { EmptyState, ErrorState, PageHeader } from "./states";
import { KindTag, MasteryBar, StatusBadge } from "./ui-bits";

describe("state components", () => {
  it("ErrorState shows the message, details and retries", async () => {
    const retry = vi.fn();
    render(<ErrorState error={new ApiError("База данных недоступна.", 503, ["попробуйте позже"])} onRetry={retry} />);
    expect(screen.getByRole("alert")).toHaveTextContent("База данных недоступна.");
    expect(screen.getByText("попробуйте позже")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Повторить/ }));
    expect(retry).toHaveBeenCalledOnce();
  });

  it("EmptyState links to the import page", () => {
    render(<EmptyState />);
    expect(screen.getByRole("link", { name: "Перейти к импорту" })).toHaveAttribute("href", "/import");
  });

  it("EmptyState can hide the import link", () => {
    render(<EmptyState showImport={false} text="Нет данных для фильтров" />);
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByText("Нет данных для фильтров")).toBeInTheDocument();
  });

  it("PageHeader renders a level-1 heading", () => {
    render(<PageHeader title="Отчёты" description="desc" />);
    expect(screen.getByRole("heading", { level: 1, name: "Отчёты" })).toBeInTheDocument();
  });
});

describe("ui bits", () => {
  it("StatusBadge uses Russian labels", () => {
    render(<><StatusBadge status="difficult" /><StatusBadge status="insufficient_data" /></>);
    expect(screen.getByText("Трудная")).toBeInTheDocument();
    expect(screen.getByText("Мало данных")).toBeInTheDocument();
  });

  it("KindTag distinguishes observations, recommendations and predictions", () => {
    render(<><KindTag kind="observation" /><KindTag kind="recommendation" /><KindTag kind="prediction" /></>);
    expect(screen.getByText("Наблюдение")).toBeInTheDocument();
    expect(screen.getByText("Рекомендация")).toBeInTheDocument();
    expect(screen.getByText("Прогноз")).toBeInTheDocument();
  });

  it("MasteryBar clamps width and colors values under the threshold", () => {
    const { container } = render(<MasteryBar value={140} threshold={50} />);
    const bar = container.querySelector("[style]") as HTMLElement;
    expect(bar.style.width).toBe("100%");
    const { container: low } = render(<MasteryBar value={30} threshold={50} />);
    expect((low.querySelector("[style]") as HTMLElement).className).toContain("bg-danger");
  });
});
