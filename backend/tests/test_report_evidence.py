"""Check report snapshots/PDFs against API data for the exact selected scope."""
import io
import re

from pypdf import PdfReader

from tests.conftest import make_csv
from tests.test_api import import_demo, upload


def test_class_pdf_displays_the_scoped_api_metrics_units_and_honest_ai_mode(client):
    import_demo(client)
    meta = client.get("/api/meta").json()
    subject = meta["subjects"][0]["id"]
    cls = next(c for c in meta["classes"] if c["name"] == "7А")
    run = client.post("/api/optimizer/run", json={"subject_id": subject, "grade": 7, "total_hours": 82}).json()
    assert client.post(f"/api/optimizer/runs/{run['run_id']}/decision", json={"decision": "accept"}).status_code == 200
    filters = {"subject_id": subject, "grade": 7, "class_id": cls["id"]}
    topics = client.get("/api/analytics/topics", params=filters).json()["topics"]
    overview = client.get("/api/analytics/overview", params=filters).json()["overview"]
    report = client.post("/api/reports", json={"filters": filters}).json()
    assert report["content"]["topics"] == topics
    assert report["content"]["overview"] == overview and overview["students"] == 27
    assert report["content"]["insights"]["mode"] == "deterministic"
    pdf = client.get(f"/api/reports/{report['id']}/pdf")
    text = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages)
    flat = re.sub(r"\s+", " ", text)
    for topic in topics:
        # Text is extracted in table-cell order; these are the selected class's actual values.
        assert f"{topic['name']} {topic['mastery']} {topic['median']}" in flat
    level = next(t["gain"]["ci_level"] for t in topics if t.get("gain"))
    assert f"ДИ {level:g}%" in flat
    assert "Всего часов: 82.0" in flat
    assert "п.п." in flat
    # The narrow table heading wraps within this word when rendered; extraction retains that space.
    assert re.search(r"Освоен\s*ие\s*%", flat)
    assert "детерминированный режим" in flat
    assert "синтетических демонстрационных данных" in flat and "не гарантирован" in flat
    assert cls["name"] in flat and "План часов для 7-й параллели" in flat


def test_report_does_not_borrow_a_plan_from_another_subject_in_same_grade(client):
    rows = ["s,S1,7,7A,Math,M1,Algebra,AM,current,2026-05-01,,Q1,5,10,TB-MATH,10",
            "s,S1,7,7A,Physics,P1,Motion,AP,current,2026-05-01,,Q1,6,10,TB-PHYS,8"]
    preview = upload(client, make_csv(rows)).json()
    assert preview["ok"]
    assert client.post(f"/api/imports/{preview['batch_id']}/commit").status_code == 200
    subjects = {s["name"]: s["id"] for s in client.get("/api/meta").json()["subjects"]}
    run = client.post("/api/optimizer/run", json={"subject_id": subjects["Math"], "grade": 7, "total_hours": 10})
    assert run.status_code == 200
    report = client.post("/api/reports", json={"filters": {"subject_id": subjects["Physics"], "grade": 7},
                                              "include_ai": False}).json()
    assert report["content"]["optimizer"] is None
    assert [t["code"] for t in report["content"]["topics"]] == ["P1"]
