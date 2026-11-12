import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Passport } from "@/lib/decision-types";
import { inapplicableFilters, SCREEN_FILTERS } from "@/lib/scope";

import { EvidenceBadge, EvidencePassport } from "./evidence-passport";

const passport = (over: Partial<Passport> = {}): Passport => ({
  subject_kind: "topic",
  subject_id: 5,
  title: "«Формулы»",
  observation: ["Освоение 40.9% (Σ набранных / Σ максимальных баллов)."],
  interpretation: "Изменение не установлено.",
  statistics: { mastery: 40.9, mean_gain: 0.6, gain_ci_low: -5.2, gain_ci_high: 6.5 },
  method: "Парный t-тест с поправкой Бонферрони.",
  dataset: {
    fingerprint: "63deb0d24aef863f9ef39688dddef0d5",
    revision: { hash: "f7b69f1bd4138d53", results: 14196, students: 156, assessments: 5, topics: 8, prerequisites: 5, hours_records: 48 },
    scope: { grade: 7 },
    algorithm_version: "ddc-2.0.0",
    synthetic: true,
  },
  sample: { students: 156, classes: 6, paired: 156 },
  uncertainty: ["Интервал включает ноль: данные не устанавливают изменения, но и не доказывают его отсутствие."],
  gate: { category: "supported", label: "Доказательства достаточны", reasons: ["Достаточная выборка."], allows_action: true },
  strengthen: ["Проверить на следующем оценивании."],
  limitations: ["Данные наблюдательные."],
  ...over,
});

describe("Evidence Passport", () => {
  it("shows observation, statistics, uncertainty, version and synthetic flag", () => {
    render(<EvidencePassport passport={passport()} />);
    expect(screen.getByTestId("passport-gate")).toHaveTextContent("Действие допускается");
    expect(screen.getByText(/Освоение 40.9%/)).toBeInTheDocument();
    expect(screen.getByText(/не доказывают его отсутствие/)).toBeInTheDocument();
    const fp = screen.getByTestId("passport-fingerprint");
    expect(fp).toHaveTextContent("63deb0d24aef863f9ef39688dddef0d5");
    expect(fp).toHaveTextContent("СИНТЕТИЧЕСКИЕ");
    expect(fp).toHaveTextContent("ddc-2.0.0");
  });

  it("states that an action is blocked when evidence is insufficient", () => {
    render(<EvidencePassport passport={passport({ gate: { category: "insufficient", label: "Недостаточно данных", reasons: ["Учеников: 4 (минимум 10)."], allows_action: false } })} />);
    expect(screen.getByTestId("passport-gate")).toHaveTextContent("Автоматическое действие заблокировано");
    expect(screen.getByTestId("passport-gate")).toHaveTextContent("Учеников: 4");
    expect(screen.getByTestId("evidence-insufficient")).toBeInTheDocument();
  });

  it("labels every evidence category without implying probability of success", () => {
    for (const c of ["supported", "exploratory", "insufficient", "incomparable", "stale"] as const) {
      const { unmount } = render(<EvidenceBadge category={c} />);
      expect(screen.getByTestId(`evidence-${c}`).textContent).not.toMatch(/%|вероятн/);
      unmount();
    }
  });
});

describe("decision screens scope", () => {
  it("apply only subject and grade, and explain dropped filters", () => {
    for (const s of ["/decisions", "/curriculum", "/scenarios"]) expect(SCREEN_FILTERS[s]).toEqual(["subject_id", "grade"]);
    const meta = { subjects: [], grades: [7], classes: [{ id: 3, name: "7А", grade: 7 }], textbooks: [], date_from: null, date_to: null, synthetic: true, has_data: true };
    expect(inapplicableFilters("/curriculum", { grade: 7, class_id: 3, date_from: "2026-01-01" }, meta))
      .toEqual(["класс 7А", "период 01.01.2026 — …"]);
  });
});
