"""Independent functional checks added during the November 2026 verification.

Real PostgreSQL via conftest; provider traffic mocked at the HTTP boundary.
"""
import io
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from pypdf import PdfReader
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings
from app.services.ai import generate_insights
from tests.conftest import ADMIN_TOKEN, make_csv
from tests.test_ai import CTX, GOOD_LLM
from tests.test_api import OK, import_demo, upload


@pytest.mark.parametrize("path,body", [
    ("/api/ai/insights", {"date_from": "2026-02-01", "date_to": "2025-01-01"}),
    ("/api/reports", {"filters": {"date_from": "2026-02-01", "date_to": "2025-01-01"}}),
])
def test_post_filters_reject_reversed_dates(client, path, body):
    assert client.post(path, json=body).status_code == 422


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_manual_allocation_rejects_nonfinite_values(client, value):
    p = upload(client, make_csv([OK])).json()
    assert client.post(f"/api/imports/{p['batch_id']}/commit").status_code == 200
    tid = client.get("/api/optimizer/inputs?subject_id=1&grade=7").json()["topics"][0]["topic_id"]
    r = client.post("/api/optimizer/evaluate", json={
        "subject_id": 1, "grade": 7, "total_hours": 10, "allocation": {str(tid): value}})
    assert r.status_code == 422


def test_duplicate_topic_overrides_rejected(client):
    r = client.post("/api/optimizer/run", json={"subject_id": 1, "grade": 7, "total_hours": 10,
        "topics": [{"topic_id": 1, "locked": True}, {"topic_id": 1, "locked": False}]})
    assert r.status_code == 422


@pytest.mark.parametrize("envelope", [
    {"choices": []}, {"choices": None}, {"choices": [{}]},
    {"choices": [{"message": {"content": None}}]},
    {"choices": [{"message": {"content": []}}]},
])
def test_malformed_openai_provider_envelopes_fall_back(monkeypatch, envelope):
    def fake_post(url, **kwargs):
        return httpx.Response(200, json=envelope, request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "post", fake_post)
    out = generate_insights(CTX, Settings(_env_file=None, llm_provider="openai_compatible",
        llm_api_key="fake-test-key", llm_base_url="https://provider.invalid/v1/"))
    assert out["mode"] == "deterministic"
    assert out["attempts"] >= 1


def test_provider_request_contract_and_no_student_rows(monkeypatch):
    calls = []
    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(GOOD_LLM)}}]},
                              request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "post", fake_post)
    out = generate_insights(CTX, Settings(_env_file=None, llm_provider="openai_compatible",
        llm_api_key="fake-test-key", llm_model="test-model", llm_base_url="https://provider.invalid/v1/",
        llm_timeout_seconds=7))
    assert out["mode"] == "llm" and out["attempts"] == 1
    url, kw = calls[0]
    assert url == "https://provider.invalid/v1/chat/completions"
    assert kw["timeout"] == 7 and kw["json"]["model"] == "test-model"
    assert kw["headers"]["Authorization"] == "Bearer fake-test-key"
    assert "student_id" not in kw["json"]["messages"][1]["content"]
    assert "fake-test-key" not in json.dumps(out)


def test_rejected_output_has_bounded_retry_and_truthful_attempt_count():
    calls = []
    def malformed(*args):
        calls.append(args)
        return "not json"
    out = generate_insights(CTX, Settings(_env_file=None, llm_api_key="fake-test-key"), llm=malformed)
    assert len(calls) == 2 and out["mode"] == "deterministic"
    assert out["attempts"] == 2


def test_preview_conflict_after_preview_is_atomic(client, migrated_db):
    first = upload(client, make_csv([OK])).json()
    second = upload(client, make_csv([OK.replace(",2,4,", ",3,4,")])).json()
    assert first["ok"] and second["ok"]
    assert client.post(f"/api/imports/{first['batch_id']}/commit").status_code == 200
    assert client.post(f"/api/imports/{second['batch_id']}/commit").status_code == 409
    with migrated_db.connect() as c:
        assert c.execute(text("SELECT score FROM assessment_results")).scalars().all() == [2]


def test_double_commit_cannot_duplicate_results_and_history_clears_staging(client, migrated_db):
    p = upload(client, make_csv([OK])).json()
    path = f"/api/imports/{p['batch_id']}/commit"
    assert client.post(path).status_code == 200
    assert client.post(path).status_code == 409
    history = client.get("/api/imports").json()
    assert len(history) == 1 and history[0]["status"] == "committed"
    with migrated_db.connect() as c:
        assert c.execute(text("SELECT count(*) FROM assessment_results")).scalar() == 1
        assert c.execute(text("SELECT staged_rows IS NULL FROM import_batches")).scalar() is True


def test_report_snapshot_pdf_scope_and_delete_lifecycle(client):
    import_demo(client)
    created = client.post("/api/reports", json={"filters": {"grade": 8}, "include_ai": False,
                                              "title": "Проверка — параллель 8"})
    assert created.status_code == 200
    report = created.json()
    assert report["content"]["insights"] is None
    assert all(t["grade"] == 8 for t in report["content"]["topics"])
    path = f"/api/reports/{report['id']}"
    pdf = client.get(path + "/pdf")
    assert pdf.headers["content-type"] == "application/pdf"
    reader = PdfReader(io.BytesIO(pdf.content))
    content = "\n".join(page.extract_text() for page in reader.pages)
    assert "Проверка — параллель 8" in content and "Ограничения" in content
    assert "Формулы сокращённого умножения" not in content
    # Stored report remains a snapshot when thresholds change.
    settings = client.get("/api/settings").json()["analysis"]
    assert client.put("/api/settings", json={**settings, "target_mastery": 80}).status_code == 200
    assert client.get(path).json() == report
    assert client.delete(path).status_code == 200
    for suffix in ("", "/pdf"):
        assert client.get(path + suffix).status_code == 404
    assert client.delete(path).status_code == 404
    assert client.get("/api/reports").json() == []


@pytest.mark.parametrize("query", ["grade=12", "subject_id=99999", "class_id=99999", "textbook_id=99999",
                                       "date_from=2030-01-01"])
def test_empty_filter_scope_has_no_invented_metrics(client, query):
    p = upload(client, make_csv([OK])).json()
    assert client.post(f"/api/imports/{p['batch_id']}/commit").status_code == 200
    for route in ("overview", "topics", "textbooks"):
        r = client.get(f"/api/analytics/{route}?{query}")
        assert r.status_code == 200
        data = r.json()
        if route == "overview":
            assert data["overview"]["has_data"] is False
        elif route == "topics":
            assert data["topics"] == []
        else:
            assert data["pairs"] == []


def test_reset_preserves_analysis_settings(client):
    saved = client.put("/api/settings", json={"target_mastery": 81}).json()["analysis"]
    assert client.post("/api/admin/reset", json={"confirm": "УДАЛИТЬ"},
                       headers={"X-Admin-Token": ADMIN_TOKEN}).status_code == 200
    assert client.get("/api/settings").json()["analysis"] == saved


@pytest.mark.parametrize("path", ["/api/imports/schema", "/api/imports/template.csv", "/api/imports/demo-dataset.csv"])
def test_import_help_and_download_endpoints(client, path):
    r = client.get(path)
    assert r.status_code == 200 and len(r.content) > 100
    if path.endswith(".csv"):
        assert "student_id" in r.text.splitlines()[0]


@pytest.mark.parametrize("path", ["/api/imports/999/discard", "/api/optimizer/runs/999/decision"])
def test_missing_resources_return_404(client, path):
    assert client.post(path, json={"decision": "reject"}).status_code == 404


def test_security_headers_and_validation_redaction(client):
    r = client.post("/api/reports", json={"filters": {"grade": "SENSITIVE-RAW-INPUT"}})
    assert r.status_code == 422 and "SENSITIVE-RAW-INPUT" not in r.text
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"


def test_concurrent_conflicting_imports_serialize_without_partial_rows(client, migrated_db):
    previews = [upload(client, make_csv([row])).json() for row in (OK, OK.replace(",2,4,", ",3,4,"))]
    assert all(p["ok"] for p in previews)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda p: client.post(f"/api/imports/{p['batch_id']}/commit"), previews))
    assert sorted(r.status_code for r in responses) == [200, 409]
    with migrated_db.connect() as c:
        assert c.execute(text("SELECT count(*) FROM assessment_results")).scalar() == 1


def test_import_database_failure_rolls_back_all_inserted_entities(client, migrated_db, monkeypatch):
    from app.api import routes
    original = routes.commit_rows
    def fail_after_inserts(db, rows, batch_id):
        original(db, rows, batch_id)
        db.flush()
        raise SQLAlchemyError("private database failure detail")
    monkeypatch.setattr(routes, "commit_rows", fail_after_inserts)
    p = upload(client, make_csv([OK])).json()
    r = client.post(f"/api/imports/{p['batch_id']}/commit")
    assert r.status_code == 500 and "private database failure detail" not in r.text
    with migrated_db.connect() as c:
        for table in ("assessment_results", "students", "topics", "classes", "schools"):
            assert c.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0
        assert c.execute(text("SELECT status FROM import_batches")).scalar() == "preview"


@pytest.mark.parametrize("status", [401, 429, 500])
def test_provider_http_failures_fall_back_once_without_leaking_key(monkeypatch, status):
    calls = []
    def fake_post(url, **kwargs):
        calls.append(url)
        return httpx.Response(status, text="private provider detail", request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "post", fake_post)
    out = generate_insights(CTX, Settings(_env_file=None, llm_api_key="fake-private-key"))
    assert out["mode"] == "deterministic" and out["attempts"] == 1 and len(calls) == 1
    assert "fake-private-key" not in json.dumps(out) and "private provider detail" not in json.dumps(out)


@pytest.mark.parametrize("envelope", [{"content": None}, {"content": [None]}, {"content": []},
                                        {"content": [{"type": "text", "text": None}]}])
def test_malformed_anthropic_envelopes_fall_back(monkeypatch, envelope):
    monkeypatch.setattr(httpx, "post", lambda url, **kw: httpx.Response(
        200, json=envelope, request=httpx.Request("POST", url)))
    out = generate_insights(CTX, Settings(_env_file=None, llm_api_key="fake-private-key"))
    assert out["mode"] == "deterministic" and out["attempts"] == 2


def test_pdf_section_heading_is_kept_with_following_content(client):
    import_demo(client)
    run = client.post("/api/optimizer/run", json={"subject_id": 1, "grade": 7, "total_hours": 82}).json()
    assert client.post(f"/api/optimizer/runs/{run['run_id']}/decision", json={"decision": "accept"}).status_code == 200
    rep = client.post("/api/reports", json={"filters": {"grade": 7}}).json()
    pdf = client.get(f"/api/reports/{rep['id']}/pdf")
    reader = PdfReader(io.BytesIO(pdf.content))
    for page in reader.pages:
        last_line = page.extract_text().strip().splitlines()[-1]
        assert not last_line.startswith("3. Сравнение учебников"), "Orphaned section heading at page bottom"


@pytest.mark.parametrize("limit", ["MAX_XLSX_MEMBERS", "MAX_XLSX_UNCOMPRESSED_BYTES"])
def test_excel_unpack_guard_rejects_before_workbook_parser(client, monkeypatch, limit):
    from app.services import importer
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/worksheets/sheet1.xml", "x" * 1000)
        archive.writestr("xl/workbook.xml", "x")
    monkeypatch.setattr(importer, limit, 1)
    monkeypatch.setattr(importer.pd, "read_excel", lambda *a, **kw: pytest.fail("must reject before unpacking"))
    r = upload(client, buffer.getvalue(), "compressed.xlsx")
    assert r.status_code == 422 and "после распаковки" in r.json()["detail"]
    assert client.get("/api/imports").json() == []


def test_row_limit_rejects_without_staging(client, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "max_upload_rows", 1)
    r = upload(client, make_csv([OK, OK.replace("STU-1", "STU-2")]))
    assert r.status_code == 413
    assert client.get("/api/imports").json() == []


def test_database_unavailable_is_a_sanitized_503(client):
    from sqlalchemy.exc import OperationalError
    from app.db import get_db
    from app.main import app
    def unavailable():
        raise OperationalError("private SQL", {}, RuntimeError("private connection detail"))
    app.dependency_overrides[get_db] = unavailable
    try:
        r = client.get("/api/meta")
        assert r.status_code == 503 and "private" not in r.text and "Traceback" not in r.text
    finally:
        app.dependency_overrides.pop(get_db)


def test_optimizer_history_scope_and_rejected_decision_persist(client):
    p = upload(client, make_csv([OK])).json()
    assert client.post(f"/api/imports/{p['batch_id']}/commit").status_code == 200
    r = client.post("/api/optimizer/run", json={"subject_id": 1, "grade": 7, "total_hours": 10})
    assert r.status_code == 200
    run = r.json()
    path = f"/api/optimizer/runs/{run['run_id']}/decision"
    assert client.post(path, json={"decision": "reject"}).json()["status"] == "rejected"
    assert client.post(path, json={"decision": "accept"}).status_code == 409
    history = client.get("/api/optimizer/runs?subject_id=1&grade=7").json()
    assert len(history) == 1 and history[0]["run_id"] == run["run_id"]
    assert history[0]["status"] == "rejected" and history[0]["total_hours"] == 10
    assert client.get("/api/optimizer/runs?grade=8").json() == []
    assert client.get("/api/optimizer/runs?subject_id=999").json() == []
