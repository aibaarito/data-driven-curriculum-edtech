"""Regression tests for the audit findings (real API + isolated PostgreSQL test database)."""
import io
import json

import openpyxl
import pytest
from sqlalchemy import text

from tests.conftest import ADMIN_TOKEN, DEMO_CSV, HEADER, make_csv
from tests.test_api import import_demo, upload

H8 = HEADER + ",textbook_name,topic_min_hours,topic_max_hours"


def commit(client, preview):
    return client.post(f"/api/imports/{preview['batch_id']}/commit")


def imp(client, rows, header=HEADER):
    p = upload(client, make_csv(rows, header)).json()
    assert p["ok"], p["errors"][:3]
    r = commit(client, p)
    assert r.status_code == 200, r.text
    return p


def q(engine, sql):
    with engine.connect() as c:
        return c.execute(text(sql)).all()


# ------------------------------------------------------------------ 1. import integrity


def test_every_class_subject_pair_gets_its_textbook(client, migrated_db):
    rows = []
    for i in range(1, 4):
        rows.append(f"s,S{i},7,7A,Math,M1,Algebra,AM,post,2026-05-01,,Q1,5,10,TB-MATH,10")
        rows.append(f"s,S{i},7,7A,Physics,P1,Mechanics,AP,post,2026-05-02,,Q1,6,10,TB-PHYS,8")
    imp(client, rows)
    pairs = q(migrated_db, "select s.name, t.code from class_subjects cs join subjects s on s.id = cs.subject_id "
                           "join textbooks t on t.id = cs.textbook_id order by 1")
    assert pairs == [("Math", "TB-MATH"), ("Physics", "TB-PHYS")]
    meta = client.get("/api/meta").json()
    phys = next(x["id"] for x in meta["subjects"] if x["name"] == "Physics")
    tb_phys = next(x["id"] for x in meta["textbooks"] if x["code"] == "TB-PHYS")
    assert [t["code"] for t in client.get(f"/api/analytics/textbooks?subject_id={phys}").json()["textbooks"]] == ["TB-PHYS"]
    hours = client.get(f"/api/analytics/topics?subject_id={phys}&textbook_id={tb_phys}").json()["topics"]
    assert hours and hours[0]["hours"] == 8.0  # textbook-filtered hours work for the second subject


def test_conflicts_with_existing_records_are_rejected_or_announced(client, migrated_db):
    imp(client, ["s,S1,7,7A,Math,M1,Algebra,AM,post,2026-05-01,,Q1,5,10,TB-MATH,10,Учебник М,6,14"], H8)
    # class grade conflict
    p = upload(client, make_csv(["s,S9,8,7A,Math,M8,Geo,AM8,post,2026-05-03,,Q1,5,10,TB-MATH,10,,,"], H8)).json()
    assert not p["ok"] and any(e["code"] == "CONFLICT_WITH_DB" and e["column"] == "grade" for e in p["errors"])
    # textbook reused for another subject
    p = upload(client, make_csv(["s,S2,7,7B,Physics,P1,Mech,AP,post,2026-05-04,,Q1,5,10,TB-MATH,8,,,"], H8)).json()
    assert not p["ok"] and any(e["column"] == "textbook_id" for e in p["errors"])
    # existing topic settings / textbook name / teaching hours differ -> explicit warnings, stored values kept
    p = upload(client, make_csv(["s,S3,7,7A,Math,M1,Algebra,AM,post,2026-05-01,,Q2,5,10,TB-MATH,12,Другое имя,8,20"],
                                H8)).json()
    assert p["ok"]
    codes = p["warning_counts"]
    assert codes.get("TOPIC_SETTINGS_DIFFER") and codes.get("TEXTBOOK_NAME_DIFFERS") and codes.get("TEACHING_HOURS_REPLACED")
    commit(client, p)
    assert q(migrated_db, "select min_hours, max_hours from topics where code = 'M1'") == [(6.0, 14.0)]
    assert q(migrated_db, "select name from textbooks where code = 'TB-MATH'") == [("Учебник М",)]
    assert q(migrated_db, "select count(*) from classes") == [(1,)]


def test_mixed_topic_total_and_item_rows_are_rejected(client):
    p = upload(client, make_csv(["s,S1,7,7A,Math,M1,Algebra,AM,post,2026-05-01,,,8,10,TB,10",
                                 "s,S1,7,7A,Math,M1,Algebra,AM,post,2026-05-01,,Q1,4,5,TB,10"])).json()
    assert not p["ok"] and "MIXED_GRANULARITY" in p["error_counts"]
    imp(client, ["s,S1,7,7A,Math,M1,Algebra,AM,post,2026-05-01,,,8,10,TB,10"])
    p = upload(client, make_csv(["s,S1,7,7A,Math,M1,Algebra,AM,post,2026-05-01,,Q1,4,5,TB,10"])).json()
    assert not p["ok"] and "MIXED_GRANULARITY" in p["error_counts"]
    # legitimate item-level re-import of identical rows is still skipped as duplicate
    imp(client, ["s,S2,7,7A,Math,M1,Algebra,AM,post,2026-05-01,,Q1,4,5,TB,10"])
    p = upload(client, make_csv(["s,S2,7,7A,Math,M1,Algebra,AM,post,2026-05-01,,Q1,4,5,TB,10"])).json()
    assert p["ok"] and p["warning_counts"].get("ALREADY_IMPORTED")


@pytest.mark.parametrize("value,code", [("1,000", "AMBIGUOUS_NUMBER"), ("2.500", "AMBIGUOUS_NUMBER"),
                                        ("1.000,5", "AMBIGUOUS_NUMBER"), ("1e3", "INVALID_NUMBER")])
def test_ambiguous_numbers_rejected_not_guessed(client, value, code):
    p = upload(client, make_csv([f's,S1,7,7A,Math,M1,Alg,AM,post,2026-05-01,,Q1,5,"{value}",TB,10'])).json()
    assert not p["ok"] and code in p["error_counts"]


def test_supported_localized_numbers_and_native_excel_numbers(client):
    header = HEADER.replace(",", ";")
    p = upload(client, make_csv(['s;S1;7;7A;Math;M1;Alg;AM;post;2026-05-01;;Q1;7,5;1 000;TB;0,125'], header)).json()
    assert p["ok"], p["errors"]
    row = p["preview"][0]
    assert (row["score"], row["max_score"], row["teaching_hours"]) == (7.5, 1000.0, 0.125)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(HEADER.split(","))
    ws.append(["s", "S2", 7, "7A", "Math", "M1", "Alg", "AM", "post", "2026-05-01", "", "Q1", 1.125, 2, "TB", 10])
    buf = io.BytesIO()
    wb.save(buf)
    p = client.post("/api/imports/preview", files={"file": ("x.xlsx", buf.getvalue(), "application/octet-stream")}).json()
    assert p["ok"] and p["preview"][0]["score"] == 1.125  # a real Excel number is not "ambiguous"


# ------------------------------------------------------------------ 6. identifiers


def test_names_are_not_echoed_or_stored(client, migrated_db):
    p = upload(client, make_csv(["s,Иван Петров,7,7A,Math,M1,Alg,AM,post,2026-05-01,,Q1,abc,10,TB,10"])).json()
    blob = json.dumps(p, ensure_ascii=False)
    assert "Иван" not in blob and "abc" not in blob
    assert {"INVALID_IDENTIFIER", "POSSIBLE_PERSONAL_DATA"} <= set(p["error_counts"])
    assert q(migrated_db, f"select position('Иван' in validation::text) from import_batches where id = {p['batch_id']}") == [(0,)]


# ------------------------------------------------------------------ 7. report scope


def test_report_never_borrows_a_plan_from_another_grade(client):
    import_demo(client)
    meta = client.get("/api/meta").json()
    subj = meta["subjects"][0]["id"]
    inp = client.get(f"/api/optimizer/inputs?subject_id={subj}&grade=7").json()
    run = client.post("/api/optimizer/run", json={"subject_id": subj, "grade": 7, "total_hours": inp["total_hours"]}).json()
    client.post(f"/api/optimizer/runs/{run['run_id']}/decision", json={"decision": "accept"})
    c8 = next(c for c in meta["classes"] if c["grade"] == 8)
    rep = client.post("/api/reports", json={"filters": {"class_id": c8["id"]}, "include_ai": False}).json()
    assert rep["content"]["optimizer"] is None and "8" in rep["content"]["optimizer_scope_note"]
    c7 = next(c for c in meta["classes"] if c["grade"] == 7)
    rep7 = client.post("/api/reports", json={"filters": {"class_id": c7["id"]}, "include_ai": False}).json()
    assert rep7["content"]["optimizer"] is not None
    assert "к плану не применяются" in rep7["content"]["optimizer_scope_note"]
    rep_all = client.post("/api/reports", json={"filters": {}, "include_ai": False}).json()
    assert rep_all["content"]["optimizer"] is None  # two grades in scope -> no single plan applies
    pdf = client.get(f"/api/reports/{rep['id']}/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_stale_plan_is_flagged_after_new_import(client):
    import_demo(client)
    subj = client.get("/api/meta").json()["subjects"][0]["id"]
    inp = client.get(f"/api/optimizer/inputs?subject_id={subj}&grade=7").json()
    client.post("/api/optimizer/run", json={"subject_id": subj, "grade": 7, "total_hours": inp["total_hours"]})
    imp(client, ["SYNTH-DEMO,S7X-001,7,7А,Математика,T7-01,Линейные уравнения,A7-EXTRA,current,2026-05-20,,Q1,1,2,TB-A7,12"])
    rep = client.post("/api/reports", json={"filters": {"grade": 7}, "include_ai": False}).json()
    assert "до последнего импорта" in rep["content"]["optimizer_scope_note"]


# ------------------------------------------------------------------ 8. uploads & previews


def test_oversized_uploads_rejected_without_trusting_content_length(client, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "max_upload_mb", 0.5)
    big = b"x" * (2 * 1024 * 1024)
    r = client.post("/api/imports/preview", files={"file": ("a.csv", big, "text/csv")})
    assert r.status_code == 413

    def chunks():  # chunked transfer: no Content-Length header at all
        yield b"--b\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.csv\"\r\n\r\n"
        for _ in range(40):
            yield b"y" * 65536
        yield b"\r\n--b--\r\n"
    r = client.post("/api/imports/preview", content=chunks(),
                    headers={"Content-Type": "multipart/form-data; boundary=b"})
    assert r.status_code == 413 and "МБ" in r.json()["detail"]


def test_expired_previews_cannot_be_committed_and_are_purged(client, migrated_db):
    p = upload(client, make_csv(["s,S1,7,7A,Math,M1,Alg,AM,post,2026-05-01,,Q1,5,10,TB,10"])).json()
    with migrated_db.begin() as c:
        c.execute(text(f"update import_batches set expires_at = now() - interval '1 minute' where id = {p['batch_id']}"))
    assert commit(client, p).status_code == 410
    assert q(migrated_db, f"select status, staged_rows is null from import_batches where id = {p['batch_id']}") == [("expired", True)]
    p2 = upload(client, make_csv(["s,S2,7,7A,Math,M1,Alg,AM,post,2026-05-01,,Q1,5,10,TB,10"])).json()
    with migrated_db.begin() as c:
        c.execute(text(f"update import_batches set expires_at = now() - interval '1 minute' where id = {p2['batch_id']}"))
    upload(client, make_csv(["s,S3,7,7A,Math,M1,Alg,AM,post,2026-05-01,,Q1,5,10,TB,10"]))  # triggers purge
    assert q(migrated_db, f"select status from import_batches where id = {p2['batch_id']}") == [("expired",)]
    bad = upload(client, make_csv(["s,S4,7,7A,Math,M1,Alg,AM,post,2026-05-01,,Q1,50,10,TB,10"])).json()
    assert q(migrated_db, f"select staged_rows is null from import_batches where id = {bad['batch_id']}") == [(True,)]


# ------------------------------------------------------------------ 9. access control


def test_api_requires_token_except_health(client):
    from app.main import app
    from fastapi.testclient import TestClient
    anon = TestClient(app)
    assert anon.get("/api/health").status_code == 200
    assert anon.get("/api/meta").status_code == 401
    assert anon.get("/api/meta", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert anon.post("/api/imports/preview", files={"file": ("a.csv", b"x", "text/csv")}).status_code == 401
    assert anon.get("/api/reports/1/pdf").status_code == 401


def test_local_only_mode_rejects_remote_clients(client, monkeypatch):
    from app.config import get_settings
    from app.main import app
    from fastapi.testclient import TestClient
    monkeypatch.setattr(get_settings(), "api_token", "")
    remote = TestClient(app, client=("203.0.113.9", 5555))
    assert remote.get("/api/meta").status_code == 403
    local = TestClient(app, client=("127.0.0.1", 5555))
    assert local.get("/api/meta").status_code == 200


def test_reset_disabled_unless_explicitly_enabled(client, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "enable_data_reset", False)
    r = client.post("/api/admin/reset", json={"confirm": "УДАЛИТЬ"}, headers={"X-Admin-Token": ADMIN_TOKEN})
    assert r.status_code == 403 and "отключено" in r.json()["detail"]
    assert client.get("/api/settings").json()["access"]["reset_enabled"] is False


# ------------------------------------------------------------------ existing data, settings, migrations


def test_integrity_check_finds_and_repairs_legacy_data(client, migrated_db):
    imp(client, ["s,S1,7,7A,Math,M1,Alg,AM,post,2026-05-01,,,8,10,TB,10"])
    with migrated_db.begin() as c:  # simulate data written by the old importer
        c.execute(text("delete from class_subjects"))
        c.execute(text("insert into assessment_results (student_id, assessment_id, topic_id, item_id, score, max_score) "
                       "select student_id, assessment_id, topic_id, 'Q1', 4, 5 from assessment_results limit 1"))
        c.execute(text("""insert into import_batches (filename, status, total_rows, valid_rows, inserted_rows, validation)
                          values ('old.csv', 'discarded', 1, 0, 0, '{"errors": [{"row": 2, "column": "student_id",
                          "code": "INVALID_IDENTIFIER", "message": "Недопустимый идентификатор «Иван Петров»"}]}')"""))
    report = client.get("/api/admin/integrity").json()
    assert not report["ok"]
    assert report["counts"]["missing_textbook_assignment"] == 1
    assert report["counts"]["mixed_granularity_results"] == 1
    assert report["counts"]["validation_with_echoed_values"] == 1
    from app.db import get_db
    from app.services.integrity import repair, run_integrity_checks
    db = next(get_db())
    done = repair(db, add_missing_assignments=True, redact_validation=True, purge_previews=True)
    assert done["assignments_added"] == 1 and done["validations_redacted"] == 1
    after = run_integrity_checks(db)["counts"]
    assert after["missing_textbook_assignment"] == 0 and after["validation_with_echoed_values"] == 0
    assert after["mixed_granularity_results"] == 1  # reported only: a human must decide which rows are right
    assert q(migrated_db, "select textbook_id from class_subjects") == [(None,)]  # nothing fabricated
    assert q(migrated_db, "select position('Иван' in validation::text) from import_batches where filename='old.csv'") == [(0,)]
    db.close()


def test_persisted_unsafe_class_minimum_is_raised_and_reported(client, migrated_db):
    with migrated_db.begin() as c:
        c.execute(text("""insert into app_settings (key, value) values ('analysis', '{"min_classes_textbook": 2}')"""))
    s = client.get("/api/settings").json()
    assert s["analysis"]["min_classes_textbook"] == 3 and s["notices"]
    assert client.put("/api/settings", json={**s["analysis"], "min_classes_textbook": 2}).status_code == 422


def test_migrations_are_reversible_on_disposable_database(migrated_db):
    from alembic import command
    from alembic.config import Config
    from tests.conftest import ROOT
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    command.downgrade(cfg, "6129d2b374e8")  # decision-intelligence migration removed
    assert q(migrated_db, "select count(*) from information_schema.tables where table_name in "
                          "('interventions','audit_events')") == [(0,)]
    assert q(migrated_db, "select count(*) from information_schema.columns where table_name='topic_prerequisites' "
                          "and column_name='review_status'") == [(0,)]
    command.downgrade(cfg, "-1")
    assert q(migrated_db, "select count(*) from information_schema.columns where table_name='import_batches' "
                          "and column_name='expires_at'") == [(0,)]
    command.upgrade(cfg, "head")
    assert q(migrated_db, "select count(*) from information_schema.tables where table_name in "
                          "('interventions','audit_events')") == [(2,)]
    assert q(migrated_db, "select count(*) from information_schema.columns where table_name='import_batches' "
                          "and column_name='expires_at'") == [(1,)]


def test_demo_dataset_full_path_still_valid(client):
    res = import_demo(client)
    assert res["inserted_rows"] == len(DEMO_CSV.read_text(encoding="utf-8").strip().splitlines()) - 1
    assert client.get("/api/admin/integrity").json()["ok"] is True
