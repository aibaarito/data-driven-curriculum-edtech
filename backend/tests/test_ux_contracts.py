"""Contracts the UX corrections rely on: population metadata, fallback causes, report titles and snapshot summaries."""
import io

import httpx
from pypdf import PdfReader

from app.config import Settings
from app.services.ai import generate_insights
from app.services.report_summary import discussion_points, gain_phrase, report_title
from tests.test_ai import CTX, GOOD_LLM, LLM_ON, llm_returning
from tests.test_api import import_demo


def test_overview_trend_labels_each_assessment_population(client):
    import_demo(client)
    trend = client.get("/api/analytics/overview").json()["trend"]
    grades = {tuple(p["grades"]) for p in trend}
    # The demo has separate grade-7 and grade-8 assessments; each observation names the grades that sat it.
    assert (7,) in grades and (8,) in grades
    assert all(len(p["grades"]) >= 1 and p["students"] > 0 for p in trend)
    scoped = client.get("/api/analytics/overview", params={"grade": 8}).json()["trend"]
    assert scoped and all(p["grades"] == [8] for p in scoped)


def test_fallback_kinds_are_distinct_and_primary_reason_has_no_exception_names():
    no_key = generate_insights(CTX, Settings(llm_api_key="", _env_file=None))
    assert no_key["fallback_kind"] == "not_configured" and no_key["fallback_detail"] is None

    def boom(*_):
        raise httpx.ConnectTimeout("timeout")
    provider = generate_insights(CTX, LLM_ON, llm=boom)
    assert provider["fallback_kind"] == "provider_error" and provider["fallback_detail"] == "ConnectTimeout"
    assert "ConnectTimeout" not in provider["fallback_reason"]

    rejected = generate_insights(CTX, LLM_ON, llm=llm_returning("not json", "still not json"))
    assert rejected["fallback_kind"] == "rejected" and rejected["attempts"] == 2
    assert "Error" not in rejected["fallback_reason"]

    import json
    ok = generate_insights(CTX, LLM_ON, llm=llm_returning(json.dumps(GOOD_LLM, ensure_ascii=False)))
    assert ok["mode"] == "llm" and ok["fallback_kind"] is None and ok["fallback_reason"] is None


def test_gain_phrase_keeps_qualification_for_every_direction():
    base = {"mean_gain": 0.6, "ci_low": -5.2, "ci_high": 6.5, "ci_level": 99.38, "n_paired": 99}
    assert "изменение не установлено" in gain_phrase({**base, "direction": "inconclusive"})
    assert "не доказывает отсутствие эффекта" in gain_phrase({**base, "direction": "inconclusive"})
    assert "установлен рост" in gain_phrase({**base, "mean_gain": 27, "ci_low": 20, "direction": "increase"})
    assert gain_phrase({**base, "mean_gain": -4, "direction": "decline"}).startswith("−4 п.п. · установлено снижение")
    assert "недостаточно пар" in gain_phrase({**base, "direction": "insufficient", "n_paired": 3})
    # Older snapshot without a stored direction: honest "not stored", never a reconstructed conclusion.
    legacy = gain_phrase({"mean_gain": 0.6})
    assert "не сохранён" in legacy and "рост" not in legacy
    assert "не оценивалось" in gain_phrase(None)


def test_report_has_scope_title_and_snapshot_discussion(client):
    import_demo(client)
    meta = client.get("/api/meta").json()
    subject = meta["subjects"][0]
    report = client.post("/api/reports", json={"filters": {"subject_id": subject["id"], "grade": 7}}).json()
    assert report["title"] == f"{subject['name']} · 7 класс · все классы · весь период"
    kinds = [p["kind"] for p in report["discussion"]]
    assert "observation" in kinds and "limitation" in kinds
    # No plan exists for this scope yet, so no recommendation is invented.
    assert "recommendation" not in kinds
    text = " ".join(p["text"] for p in report["discussion"])
    assert "Формулы сокращённого умножения" in text and "изменение не установлено" in text
    assert "не доказательство эффекта учебника" in text

    # All-grades report never carries a grade plan recommendation either.
    all_grades = client.post("/api/reports", json={"filters": {}}).json()
    assert all_grades["title"].startswith("Все предметы · все параллели")
    assert all(p["kind"] != "recommendation" for p in all_grades["discussion"])

    pdf = client.get(f"/api/reports/{report['id']}/pdf")
    reader = PdfReader(io.BytesIO(pdf.content))
    pages = [p.extract_text() for p in reader.pages]
    assert "Выводы для обсуждения" in pages[0]
    assert all(f"Стр. {i} из {len(pages)}" in t for i, t in enumerate(pages, start=1))


def test_discussion_for_legacy_snapshot_does_not_invent_conclusions():
    legacy = {"settings": {"difficult_threshold": 50, "watch_threshold": 65}, "synthetic": True,
              "topics": [{"topic_id": 1, "name": "Дроби", "mastery": 40.0, "student_count": 30, "status": "difficult",
                          "gain": {"mean_gain": 3.0, "ci_low": 1.0, "ci_high": 5.0}}],
              "textbooks": {"pairs": []}, "optimizer": None}
    pts = discussion_points(legacy)
    text = pts[0]["text"]
    assert "не сохранён" in text and "рост" not in text


def test_report_title_includes_class_textbook_and_period():
    labels = {"Предмет": "Математика", "Класс": "7А", "Учебник": "Алгебра 7"}
    title = report_title(labels, {"grade": 7, "date_from": "2025-09-01", "date_to": None})
    assert title == "Математика · 7 класс · класс 7А · Алгебра 7 · 01.09.2025 — …"
