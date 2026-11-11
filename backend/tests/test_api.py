"""Integration tests: real FastAPI app + real PostgreSQL (ddc_test) + Alembic migrations."""
from tests.conftest import DEMO_CSV, make_csv

OK = "s,STU-1,7,7А,Математика,T1,Тема 1,A1,pre,2025-09-10,G1,Q1,2,4,TB-A,10"


def upload(client, content: bytes, name="data.csv"):
    return client.post("/api/imports/preview", files={"file": (name, content, "text/csv")})


def import_demo(client):
    r = upload(client, DEMO_CSV.read_bytes())
    assert r.status_code == 200 and r.json()["ok"], r.json()["errors"][:3]
    c = client.post(f"/api/imports/{r.json()['batch_id']}/commit")
    assert c.status_code == 200
    return c.json()


def test_health_and_empty_state(client):
    assert client.get("/api/health").json()["database"] is True
    ov = client.get("/api/analytics/overview").json()
    assert ov["overview"]["has_data"] is False and ov["topics"] == []
    assert client.get("/api/meta").json()["has_data"] is False
    r = client.post("/api/reports", json={"filters": {}})
    assert r.status_code == 404


def test_full_workflow(client):
    res = import_demo(client)
    assert res["inserted_rows"] == len(DEMO_CSV.read_text(encoding="utf-8").strip().splitlines()) - 1

    meta = client.get("/api/meta").json()
    assert meta["synthetic"] is True and meta["has_data"] and 7 in meta["grades"]
    subject = meta["subjects"][0]["id"]

    ov = client.get("/api/analytics/overview").json()
    assert ov["overview"]["students"] == 199
    assert any(o["type"] == "difficult_topic" for o in ov["opportunities"])

    topics = client.get(f"/api/analytics/topics?subject_id={subject}&grade=7").json()["topics"]
    fsu = next(t for t in topics if t["code"] == "T7-05")
    assert fsu["status"] == "difficult" and fsu["interpretation_code"] == "low_no_measurable_gain"
    lin = next(t for t in topics if t["code"] == "T7-01")
    assert lin["gain"]["significant"] and lin["gain"]["mean_gain"] > 30

    tb7 = client.get("/api/analytics/textbooks?grade=7").json()
    assert len(tb7["pairs"]) == 1 and tb7["pairs"][0]["adjusted"] is not None
    tb8 = client.get("/api/analytics/textbooks?grade=8").json()
    assert tb8["pairs"][0]["verdict"] == "insufficient_evidence"

    inputs = client.get(f"/api/optimizer/inputs?subject_id={subject}&grade=7").json()
    run = client.post("/api/optimizer/run", json={"subject_id": subject, "grade": 7,
                                                  "total_hours": inputs["total_hours"]}).json()
    assert run["proposed_total"] == inputs["total_hours"]
    assert all(c["ok"] for c in run["constraints"])
    ev = client.post("/api/optimizer/evaluate", json={
        "subject_id": subject, "grade": 7, "total_hours": inputs["total_hours"],
        "allocation": {str(r["topic_id"]): r["proposed_hours"] for r in run["rows"]}}).json()
    assert ev["ok"]
    assert client.post(f"/api/optimizer/runs/{run['run_id']}/decision", json={"decision": "accept"}).json()["status"] == "accepted"
    assert client.post(f"/api/optimizer/runs/{run['run_id']}/decision", json={"decision": "reject"}).status_code == 409

    ai = client.post("/api/ai/insights", json={"subject_id": subject, "grade": 7}).json()
    assert ai["mode"] == "deterministic" and ai["payload"]["findings"]

    rep = client.post("/api/reports", json={"filters": {"subject_id": subject, "grade": 7}}).json()
    assert rep["content"]["optimizer_status"] == "accepted"
    assert rep["content"]["limitations"]
    pdf = client.get(f"/api/reports/{rep['id']}/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF") and len(pdf.content) > 5000
    assert len(client.get("/api/reports").json()) == 1


def test_reimport_same_file_skips_duplicates(client):
    import_demo(client)
    r = upload(client, DEMO_CSV.read_bytes()).json()
    assert r["ok"] and r["warning_counts"].get("ALREADY_IMPORTED")
    c = client.post(f"/api/imports/{r['batch_id']}/commit").json()
    assert c["inserted_rows"] == 0


def test_conflicting_reimport_rejected(client):
    r = upload(client, make_csv([OK])).json()
    client.post(f"/api/imports/{r['batch_id']}/commit")
    changed = upload(client, make_csv([OK.replace(",2,4,", ",3,4,")])).json()
    assert not changed["ok"] and "CONFLICT_WITH_DB" in changed["error_counts"]
    assert client.post(f"/api/imports/{changed['batch_id']}/commit").status_code == 422


def test_file_with_errors_cannot_be_committed(client):
    r = upload(client, make_csv([OK.replace(",2,4,", ",9,4,")])).json()
    assert r["ok"] is False and r["errors"][0]["code"] == "SCORE_EXCEEDS_MAX"
    assert client.post(f"/api/imports/{r['batch_id']}/commit").status_code == 422
    assert client.get("/api/meta").json()["has_data"] is False


def test_bad_uploads(client, monkeypatch):
    assert upload(client, b"", "a.csv").status_code == 422
    assert upload(client, b"x", "a.txt").status_code == 422
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "max_upload_mb", 0.0001)
    assert upload(client, make_csv([OK] * 50)).status_code == 413


def test_discard_and_double_commit(client):
    r = upload(client, make_csv([OK])).json()
    assert client.post(f"/api/imports/{r['batch_id']}/discard").status_code == 200
    assert client.post(f"/api/imports/{r['batch_id']}/commit").status_code == 409
    assert client.post("/api/imports/9999/commit").status_code == 404


def test_infeasible_optimizer_returns_explanation(client):
    import_demo(client)
    r = client.post("/api/optimizer/run", json={"subject_id": 1, "grade": 7, "total_hours": 10})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "INFEASIBLE"
    assert client.post("/api/optimizer/run", json={"subject_id": 1, "grade": 7, "total_hours": 80,
                                                   "topics": [{"topic_id": 999}]}).status_code == 422


def test_settings_validation_and_topic_update(client):
    s = client.get("/api/settings").json()
    assert s["llm"]["enabled"] is False and "api_key" not in str(s).lower()
    bad = {**s["analysis"], "difficult_threshold": 90, "watch_threshold": 50}
    assert client.put("/api/settings", json=bad).status_code == 422
    good = {**s["analysis"], "difficult_threshold": 45}
    assert client.put("/api/settings", json=good).json()["analysis"]["difficult_threshold"] == 45
    import_demo(client)
    assert client.put("/api/topics/1", json={"min_hours": 9, "max_hours": 3, "priority": 2}).status_code == 422
    assert client.put("/api/topics/1", json={"min_hours": 3, "max_hours": 9, "priority": 3}).status_code == 200


def test_filters_validation(client):
    assert client.get("/api/analytics/overview?grade=99").status_code == 422
    assert client.get("/api/analytics/overview?date_from=2026-01-01&date_to=2025-01-01").status_code == 422


def test_reset_requires_admin_token_and_confirmation(client):
    from tests.conftest import ADMIN_TOKEN
    import_demo(client)
    assert client.post("/api/admin/reset", json={"confirm": "УДАЛИТЬ"}).status_code == 403  # no admin token
    assert client.post("/api/admin/reset", json={"confirm": "УДАЛИТЬ"},
                       headers={"X-Admin-Token": "wrong-token-wrong-token"}).status_code == 403
    assert client.post("/api/admin/reset", json={"confirm": "yes"},
                       headers={"X-Admin-Token": ADMIN_TOKEN}).status_code == 422
    assert client.get("/api/meta").json()["has_data"] is True
    assert client.post("/api/admin/reset", json={"confirm": "УДАЛИТЬ"},
                       headers={"X-Admin-Token": ADMIN_TOKEN}).status_code == 200
    assert client.get("/api/meta").json()["has_data"] is False


def test_errors_do_not_leak_internals(client):
    r = client.get("/api/reports/abc")
    assert r.status_code == 422 and "Traceback" not in r.text
