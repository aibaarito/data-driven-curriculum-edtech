"""Guided import: worksheet/header selection, mapping, shared values, configuration-bound validation and commit.

All fixtures are synthetic and built in memory. Integration tests run against the dedicated *_test database.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import openpyxl
import pytest
from sqlalchemy import text

from app.services import import_prep as prep
from app.services.importer import FileFormatError
from tests.conftest import DEMO_CSV, HEADER, make_csv

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "app" / "assets" / "data" / "example_guided_import.xlsx"
TEMPLATE = ROOT / "app" / "assets" / "data" / "template.csv"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

RU_HEADER = ["Код ученика", "Параллель", "Класс", "Код темы", "Тема", "Код работы", "Дата", "Баллы",
             "Максимальный балл", "Учебник", "Примечание"]


def ru_row(sid="SYN-1", topic="SYN-T1", score=3, mx=4, cls="7А", tb="SYN-TB-A"):
    return [sid, 7, cls, topic, "Тема " + topic, "SYN-PRE", "15.09.2026", score, mx, tb, ""]


def workbook(sheets: dict[str, list[list]], hidden: tuple[str, ...] = ()) -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(r)
        if name in hidden:
            ws.sheet_state = "hidden"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def multi_sheet_ru(rows: list[list] | None = None) -> bytes:
    data = [["Результаты диагностики (синтетические)"], [], RU_HEADER, *(rows or [ru_row(), ru_row(topic="SYN-T2")])]
    return workbook({"Пояснение": [["Это синтетический пример"]], "Результаты": data,
                     "Скрытый": [["x", "y"]]}, hidden=("Скрытый",))


def ru_fields(**override) -> dict:
    f = {"student_id": "c0", "grade": "c1", "class": "c2", "topic_id": "c3", "topic_name": "c4",
         "assessment_id": "c5", "assessment_date": "c6", "score": "c7", "max_score": "c8", "textbook_id": "c9"}
    out = {k: {"source": "column", "column": v} for k, v in f.items()}
    out["subject"] = {"source": "value", "value": "Математика"}
    out["assessment_type"] = {"source": "value", "value": "pre"}
    out.update(override)
    return out


def upload_source(client, content: bytes, name: str):
    mime = XLSX if name.endswith(".xlsx") else "text/csv"
    return client.post("/api/imports/sources", files={"file": (name, content, mime)})


def validate(client, src: dict, sheet: str, header_row: int, fields: dict, confirm=True):
    return client.post(f"/api/imports/{src['batch_id']}/validate",
                       json={"session_key": src["session_key"], "sheet": sheet, "header_row": header_row,
                             "fields": fields, "confirm_shared": confirm})


def commit(client, src: dict, config_hash: str | None):
    return client.post(f"/api/imports/{src['batch_id']}/commit",
                       json={"session_key": src["session_key"], "config_hash": config_hash})


def auto_fields(inspection: dict) -> dict:
    return {f: {"source": "column", "column": s["column"]} for f, s in inspection["suggestions"]["suggested"].items()}


def count(db, table: str) -> int:
    with db.connect() as c:
        return c.execute(text(f"select count(*) from {table}")).scalar_one()


ANALYTICAL = ("schools", "subjects", "textbooks", "classes", "students", "topics", "assessments",
              "assessment_results", "class_subjects", "class_topic_hours", "topic_prerequisites")


def snapshot(db) -> dict[str, int]:
    return {t: count(db, t) for t in ANALYTICAL}


# --------------------------------------------------------------------------- unit: reading & suggestions


def test_csv_single_pseudo_sheet_and_bom():
    wb = prep.read_workbook(b"\xef\xbb\xbf" + make_csv(["s,STU-1,7,7А,М,T1,Т,A1,pre,2025-09-10,G1,Q1,2,4,TB,10"]),
                            "f.csv", max_data_rows=100)
    assert [s.name for s in wb.sheets] == ["CSV"]
    cols = prep.header_columns(wb.sheets[0], 1)
    assert cols[0].header == "school"  # BOM removed
    assert set(prep.suggest_mapping(cols)["suggested"]) >= set(prep.REQUIRED_COLUMNS)


def test_title_rows_merged_title_and_header_suggestion():
    content = multi_sheet_ru()
    wb = prep.read_workbook(content, "f.xlsx", max_data_rows=100)
    sheet = wb.get("Результаты")
    assert prep.suggest_header_row(sheet) == {"row": 3, "confidence": "high",
                                              "reason": "В строке 3 найдено 10 знакомых названий столбцов."}
    assert prep.suggest_sheet(wb.sheets)["name"] == "Результаты"
    summaries = {s["name"]: s for s in map(prep.sheet_summary, wb.sheets)}
    assert summaries["Скрытый"]["hidden"] is True


def test_hidden_sheet_never_auto_selected():
    content = workbook({"Видимый": [["Заметки"]], "Данные": [RU_HEADER, ru_row()]}, hidden=("Данные",))
    wb = prep.read_workbook(content, "f.xlsx", max_data_rows=100)
    assert prep.suggest_sheet(wb.sheets)["name"] == "Видимый"  # the only visible non-empty sheet
    content2 = workbook({"Пусто": [], "Данные": [RU_HEADER, ru_row()]}, hidden=("Данные",))
    assert prep.suggest_sheet(prep.read_workbook(content2, "f.xlsx", max_data_rows=100).sheets)["name"] is None


def test_two_equal_candidate_sheets_require_a_choice():
    content = workbook({"2025": [RU_HEADER, ru_row()], "2026": [RU_HEADER, ru_row()]})
    assert prep.suggest_sheet(prep.read_workbook(content, "f.xlsx", max_data_rows=100).sheets)["name"] is None


def test_russian_and_english_aliases_and_normalisation():
    cols = [prep.Column(f"c{i}", i, prep.col_letter(i), h, h) for i, h in enumerate(
        ["  ID ученика ", "SUBJECT", "Topic name", "Набранный балл", "Max score", "Дата оценивания", "Код  темы"])]
    s = prep.suggest_mapping(cols)["suggested"]
    assert {f: v["column"] for f, v in s.items()} == {
        "student_id": "c0", "subject": "c1", "topic_name": "c2", "score": "c3", "max_score": "c4",
        "assessment_date": "c5", "topic_id": "c6"}


@pytest.mark.parametrize("header,fields", [("Оценка", ["score"]), ("Учебник", ["textbook_id", "textbook_name"]),
                                           ("ФИО", ["student_id"]), ("%", ["score"])])
def test_ambiguous_aliases_are_not_preselected(header, fields):
    res = prep.suggest_mapping([prep.Column("c0", 0, "A", header, header)])
    assert res["suggested"] == {}
    assert set(res["ambiguous"]) == set(fields)


def test_duplicate_and_blank_headers_keep_distinct_column_ids():
    content = workbook({"Лист": [["Баллы", "баллы ", None, "Код ученика"], [1, 2, 3, "S1"]]})
    sheet = prep.read_workbook(content, "f.xlsx", max_data_rows=100).sheets[0]
    ins = prep.inspect_sheet(sheet, 1)
    assert [c["id"] for c in ins["columns"]] == ["c0", "c1", "c2", "c3"]
    assert ins["columns"][2]["label"] == "Столбец C (без заголовка)"
    assert ins["duplicate_headers"] == [{"header": "Баллы", "letters": ["A", "B"]}]
    assert "score" not in ins["suggestions"]["suggested"]  # two candidates -> user must choose
    assert {a["column"] for a in ins["suggestions"]["ambiguous"]["score"]} == {"c0", "c1"}


def test_wide_layout_is_flagged():
    rows = [["Код ученика", "Класс", "Дроби", "Уравнения", "Проценты"], ["S1", "7А", 3, 4, 5], ["S2", "7А", 1, 2, 2]]
    sheet = prep.read_workbook(workbook({"Л": rows}), "f.xlsx", max_data_rows=100).sheets[0]
    codes = {n["code"] for n in prep.inspect_sheet(sheet, 1)["notices"]}
    assert "WIDE_LAYOUT_SUSPECTED" in codes


def test_repeated_header_inside_data_is_reported():
    rows = [RU_HEADER, ru_row(), [], RU_HEADER, ru_row(sid="S9")]
    sheet = prep.read_workbook(workbook({"Л": rows}), "f.xlsx", max_data_rows=100).sheets[0]
    notices = prep.inspect_sheet(sheet, 1)["notices"]
    assert notices[0]["code"] == "REPEATED_HEADER" and notices[0]["rows"] == [4]


def test_merged_cells_are_not_forward_filled():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(RU_HEADER)
    ws.append(ru_row())
    ws.append(ru_row(topic="SYN-T2"))
    ws.merge_cells("C2:C3")  # class written once for two rows
    buf = io.BytesIO()
    wb.save(buf)
    sheet = prep.read_workbook(buf.getvalue(), "f.xlsx", max_data_rows=100).sheets[0]
    assert sheet.rows[2][1][2] is None or sheet.rows[2][1][2] == ""


def test_formula_without_cached_value_is_detected_not_evaluated():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(RU_HEADER)
    r = ru_row()
    r[7] = "=2+1"  # openpyxl writes no cached value
    ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    wbk = prep.read_workbook(buf.getvalue(), "f.xlsx", max_data_rows=100, sheet_name="Sheet", detect_formulas=True)
    assert wbk.sheets[0].formula_cells == {(2, 7)}
    assert wbk.sheets[0].rows[1][1][7] is None  # never computed to 3


def test_too_many_columns_and_cells_are_bounded(monkeypatch):
    wide = workbook({"Л": [[f"h{i}" for i in range(prep.MAX_COLUMNS + 5)]]})
    sheet = prep.read_workbook(wide, "f.xlsx", max_data_rows=100).sheets[0]
    assert sheet.problem and "столбцов" in sheet.problem
    monkeypatch.setattr(prep, "MAX_CELLS", 50)
    big = workbook({"Л": [RU_HEADER] + [ru_row(sid=f"S{i}") for i in range(20)]})
    with pytest.raises(FileFormatError, match="лимит ячеек"):
        prep.read_workbook(big, "f.xlsx", max_data_rows=100)


def test_row_limit_and_zip_bomb_guard(monkeypatch):
    big = workbook({"Л": [RU_HEADER] + [ru_row(sid=f"S{i}") for i in range(60)]})
    sheet = prep.read_workbook(big, "f.xlsx", max_data_rows=5).sheets[0]
    assert sheet.problem and "лимит" in sheet.problem
    monkeypatch.setattr(prep, "MAX_XLSX_UNCOMPRESSED_BYTES", 100)
    with pytest.raises(FileFormatError, match="слишком велика"):
        prep.read_workbook(big, "f.xlsx", max_data_rows=100)


def test_shared_value_rules():
    assert prep.validate_shared_value("grade", "7") is None
    assert prep.validate_shared_value("grade", "7А")
    assert prep.validate_shared_value("assessment_date", "09/15/2026")
    assert prep.validate_shared_value("assessment_type", "входная")
    assert prep.validate_shared_value("assessment_id", "Иван Петров")
    assert "score" not in prep.SHARED_ELIGIBLE and "student_id" not in prep.SHARED_ELIGIBLE
    assert "max_score" not in prep.SHARED_ELIGIBLE and "textbook_id" not in prep.SHARED_ELIGIBLE


# --------------------------------------------------------------------------- integration: endpoints


def test_template_is_auto_ready_and_imports(client, migrated_db):
    src = upload_source(client, TEMPLATE.read_bytes(), "template.csv").json()
    assert src["kind"] == "csv" and src["auto_ready"] is True
    ins = src["inspection"]
    assert ins["header_row"] == 1 and ins["header_suggestion"]["confidence"] == "high"
    v = validate(client, src, "CSV", 1, auto_fields(ins), confirm=False).json()
    assert v["ok"], v["errors"][:3]
    assert v["config"]["shared"] == [] and v["config"]["ignored_columns"] == []
    assert commit(client, src, v["config_hash"]).status_code == 200
    assert count(migrated_db, "assessment_results") == v["valid_rows"]


def test_guided_result_equals_one_step_preview(client):
    """The guided path reuses the same validator: identical normalized rows for the standard template."""
    one = client.post("/api/imports/preview", files={"file": ("d.csv", DEMO_CSV.read_bytes(), "text/csv")}).json()
    src = upload_source(client, DEMO_CSV.read_bytes(), "d.csv").json()
    v = validate(client, src, "CSV", 1, auto_fields(src["inspection"])).json()
    assert v["ok"] and one["ok"]
    for k in ("total_rows", "valid_rows", "summary", "warning_counts", "preview"):
        assert v[k] == one[k], k


def test_multi_sheet_russian_workbook_full_flow(client, migrated_db):
    src = upload_source(client, multi_sheet_ru(), "школа.xlsx").json()
    assert [s["name"] for s in src["sheets"]] == ["Пояснение", "Результаты", "Скрытый"]
    assert src["sheet_suggestion"]["name"] == "Результаты"
    assert src["auto_ready"] is False  # subject/type are not in the file, textbook column is ambiguous
    ins = src["inspection"]
    assert ins["header_row"] == 3 and [p["row"] for p in ins["preview"]][:3] == [1, 3, 4]
    before = snapshot(migrated_db)
    v = validate(client, src, "Результаты", 3, ru_fields()).json()
    assert v["ok"], v["errors"]
    assert snapshot(migrated_db) == before  # validation never touches analytical data
    assert v["config"]["shared"] == [{"field": "subject", "label": "Предмет", "value": "Математика"},
                                     {"field": "assessment_type", "label": "Тип оценивания", "value": "pre"}]
    assert v["config"]["ignored_columns"] == ["Примечание"]
    assert v["preview"][0]["row"] == 4 and v["preview"][0]["subject"] == "Математика"
    r = commit(client, src, v["config_hash"])
    assert r.status_code == 200 and r.json()["inserted_rows"] == 2
    with migrated_db.connect() as c:
        assert c.execute(text("select source_file is null, status from import_batches where id=:i"),
                         {"i": src["batch_id"]}).one() == (True, "committed")


def test_original_row_numbers_in_errors(client):
    rows = [ru_row(), ru_row(topic="SYN-T2", score=9, mx=4)]
    src = upload_source(client, multi_sheet_ru(rows), "f.xlsx").json()
    v = validate(client, src, "Результаты", 3, ru_fields()).json()
    assert not v["ok"]
    assert [(e["row"], e["code"]) for e in v["errors"]] == [(5, "SCORE_EXCEEDS_MAX")]
    assert v["total_rows"] == 2 and v["rows_with_errors"] == 1 and v["records_validated"] is True
    assert commit(client, src, v["config_hash"]).status_code == 422


def test_explicit_header_row_selection_and_blank_rows(client):
    content = workbook({"Л": [["Отчёт"], [], ["Заметка", "без", "смысла"], RU_HEADER, ru_row(), [], ru_row(
        topic="SYN-T2")]})
    src = upload_source(client, content, "f.xlsx").json()
    assert src["inspection"]["header_row"] == 4
    other = client.post(f"/api/imports/{src['batch_id']}/inspect",
                        json={"session_key": src["session_key"], "sheet": "Л", "header_row": 3}).json()
    assert other["inspection"]["header_row"] == 3 and other["auto_ready"] is False
    bad = client.post(f"/api/imports/{src['batch_id']}/inspect",
                      json={"session_key": src["session_key"], "sheet": "Л", "header_row": 2})
    assert bad.status_code == 422  # empty row cannot be a header
    v = validate(client, src, "Л", 4, ru_fields()).json()
    assert v["ok"] and v["total_rows"] == 2 and v["warning_counts"].get("BLANK_ROWS") == 1
    assert [p["row"] for p in v["preview"]] == [5, 7]


@pytest.mark.parametrize("fields,code", [
    (lambda f: f | {"score": {"source": "column", "column": "c0"}}, "COLUMN_REUSED"),
    (lambda f: f | {"score": {"source": "column", "column": "c99"}}, "UNKNOWN_COLUMN"),
    (lambda f: f | {"hacked": {"source": "column", "column": "c10"}}, "UNKNOWN_FIELD"),
    (lambda f: {k: v for k, v in f.items() if k != "student_id"}, "MISSING_MAPPING"),
    (lambda f: f | {"student_id": {"source": "none"}}, "MISSING_MAPPING"),
    (lambda f: f | {"max_score": {"source": "value", "value": "100"}}, "SHARED_NOT_ALLOWED"),
    (lambda f: f | {"subject": {"source": "value", "value": "  "}}, "INVALID_SHARED_VALUE"),
    (lambda f: f | {"assessment_type": {"source": "value", "value": "входная"}}, "INVALID_SHARED_VALUE"),
    (lambda f: f | {"score": {"source": "formula"}}, "INVALID_MAPPING"),
])
def test_invalid_or_tampered_configuration_is_rejected(client, fields, code):
    src = upload_source(client, multi_sheet_ru(), "f.xlsx").json()
    r = validate(client, src, "Результаты", 3, fields(ru_fields()))
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["code"] == "INVALID_CONFIGURATION"
    assert code in {i["code"] for i in detail["issues"]}


def test_shared_values_require_confirmation(client):
    src = upload_source(client, multi_sheet_ru(), "f.xlsx").json()
    r = validate(client, src, "Результаты", 3, ru_fields(), confirm=False)
    assert r.status_code == 422 and r.json()["detail"]["issues"][0]["code"] == "SHARED_NOT_CONFIRMED"


def test_unknown_sheet_and_header_row_rejected(client):
    src = upload_source(client, multi_sheet_ru(), "f.xlsx").json()
    assert validate(client, src, "Нет такого", 3, ru_fields()).status_code == 422
    r = validate(client, src, "Результаты", 2, ru_fields())
    assert r.status_code == 422 and r.json()["detail"]["issues"][0]["code"] == "INVALID_HEADER_ROW"


def test_textbook_explicitly_absent_is_allowed_with_warning(client):
    src = upload_source(client, multi_sheet_ru(), "f.xlsx").json()
    v = validate(client, src, "Результаты", 3, ru_fields(textbook_id={"source": "none"})).json()
    assert v["ok"] and "MISSING_TEXTBOOK" in v["warning_counts"]
    assert v["config"]["not_in_file"] == [{"field": "textbook_id", "label": "Идентификатор учебника"}]


def test_existing_numeric_date_and_cross_record_rules_still_apply(client):
    rows = [ru_row(score="1,000"), ru_row(topic="SYN-T2"), ru_row(topic="SYN-T2"), ru_row(sid="SYN-2", cls="7Б")]
    rows[3][6] = "09/15/2026"
    src = upload_source(client, multi_sheet_ru(rows), "f.xlsx").json()
    v = validate(client, src, "Результаты", 3, ru_fields()).json()
    codes = {(e["row"], e["code"]) for e in v["errors"]}
    assert (4, "AMBIGUOUS_NUMBER") in codes and (6, "DUPLICATE_ROW") in codes and (7, "INVALID_DATE") in codes


def test_formula_cells_without_value_block_validation(client):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Л"
    ws.append(RU_HEADER)
    r = ru_row()
    r[7] = "=1+1"
    ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    src = upload_source(client, buf.getvalue(), "f.xlsx").json()
    v = validate(client, src, "Л", 1, ru_fields()).json()
    assert not v["ok"] and "FORMULA_WITHOUT_VALUE" in v["error_counts"]


def test_configuration_change_invalidates_previous_validation(client, migrated_db):
    src = upload_source(client, multi_sheet_ru(), "f.xlsx").json()
    good = validate(client, src, "Результаты", 3, ru_fields()).json()
    assert good["ok"]
    # A different (still valid) mapping produces a new hash; the earlier hash can no longer be committed.
    changed = validate(client, src, "Результаты", 3, ru_fields(textbook_id={"source": "none"})).json()
    assert changed["ok"] and changed["config_hash"] != good["config_hash"]
    r = commit(client, src, good["config_hash"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "STALE_PREVIEW"
    # An invalid configuration also invalidates the last successful result.
    assert validate(client, src, "Результаты", 3, {}).status_code == 422
    assert commit(client, src, changed["config_hash"]).status_code == 409
    assert count(migrated_db, "assessment_results") == 0


def test_commit_requires_session_key_and_hash(client):
    src = upload_source(client, multi_sheet_ru(), "f.xlsx").json()
    v = validate(client, src, "Результаты", 3, ru_fields()).json()
    assert client.post(f"/api/imports/{src['batch_id']}/commit").status_code == 403
    r = client.post(f"/api/imports/{src['batch_id']}/commit", json={"session_key": "wrong", "config_hash": v["config_hash"]})
    assert r.status_code == 403
    other = upload_source(client, multi_sheet_ru(), "f.xlsx").json()  # a key from another upload does not work
    r = client.post(f"/api/imports/{src['batch_id']}/commit",
                    json={"session_key": other["session_key"], "config_hash": v["config_hash"]})
    assert r.status_code == 403
    assert client.post(f"/api/imports/{src['batch_id']}/inspect",
                       json={"session_key": other["session_key"], "sheet": "Результаты"}).status_code == 403
    assert commit(client, src, None).status_code == 409
    assert commit(client, src, v["config_hash"]).status_code == 200
    assert commit(client, src, v["config_hash"]).status_code == 409  # duplicate submission


def test_expired_guided_preview(client, migrated_db):
    src = upload_source(client, multi_sheet_ru(), "f.xlsx").json()
    v = validate(client, src, "Результаты", 3, ru_fields()).json()
    with migrated_db.begin() as c:
        c.execute(text("update import_batches set expires_at = now() - interval '1 minute' where id=:i"),
                  {"i": src["batch_id"]})
    r = validate(client, src, "Результаты", 3, ru_fields())
    assert r.status_code == 410 and r.json()["detail"]["code"] == "PREVIEW_EXPIRED"
    assert commit(client, src, v["config_hash"]).status_code == 410
    with migrated_db.connect() as c:
        row = c.execute(text("select status, source_file is null, staged_rows is null from import_batches "
                             "where id=:i"), {"i": src["batch_id"]}).one()
    assert row == ("expired", True, True)


def test_purge_drops_stored_files(client, migrated_db):
    src = upload_source(client, multi_sheet_ru(), "f.xlsx").json()
    with migrated_db.begin() as c:
        c.execute(text("update import_batches set expires_at = now() - interval '1 minute' where id=:i"),
                  {"i": src["batch_id"]})
    upload_source(client, multi_sheet_ru(), "g.xlsx")  # any upload purges expired previews
    with migrated_db.connect() as c:
        assert c.execute(text("select source_file is null from import_batches where id=:i"),
                         {"i": src["batch_id"]}).scalar_one() is True


def test_discard_keeps_data_and_drops_file(client, migrated_db):
    src = upload_source(client, TEMPLATE.read_bytes(), "t.csv").json()
    v = validate(client, src, "CSV", 1, auto_fields(src["inspection"])).json()
    assert commit(client, src, v["config_hash"]).status_code == 200
    before = snapshot(migrated_db)
    src2 = upload_source(client, multi_sheet_ru(), "f.xlsx").json()
    v2 = validate(client, src2, "Результаты", 3, ru_fields()).json()
    assert v2["ok"]
    assert client.post(f"/api/imports/{src2['batch_id']}/discard").status_code == 403
    assert client.post(f"/api/imports/{src2['batch_id']}/discard",
                       json={"session_key": src2["session_key"]}).status_code == 200
    assert snapshot(migrated_db) == before
    assert commit(client, src2, v2["config_hash"]).status_code == 409


def test_reimport_and_conflicts_with_stored_data(client, migrated_db):
    src = upload_source(client, multi_sheet_ru(), "f.xlsx").json()
    v = validate(client, src, "Результаты", 3, ru_fields()).json()
    assert commit(client, src, v["config_hash"]).status_code == 200
    again = upload_source(client, multi_sheet_ru(), "f.xlsx").json()
    v2 = validate(client, again, "Результаты", 3, ru_fields()).json()
    assert v2["ok"] and "ALREADY_IMPORTED" in v2["warning_counts"]
    assert commit(client, again, v2["config_hash"]).json()["inserted_rows"] == 0
    changed = upload_source(client, multi_sheet_ru([ru_row(score=1)]), "f.xlsx").json()
    v3 = validate(client, changed, "Результаты", 3, ru_fields()).json()
    assert not v3["ok"] and "CONFLICT_WITH_DB" in v3["error_counts"]


def test_atomic_commit_on_conflict_under_lock(client, migrated_db):
    """Data changed between validation and commit: the whole import is refused, nothing is written."""
    src = upload_source(client, multi_sheet_ru([ru_row(), ru_row(topic="SYN-T2")]), "f.xlsx").json()
    v = validate(client, src, "Результаты", 3, ru_fields()).json()
    other = upload_source(client, multi_sheet_ru([ru_row(score=0)]), "g.xlsx").json()
    ov = validate(client, other, "Результаты", 3, ru_fields()).json()
    assert commit(client, other, ov["config_hash"]).status_code == 200
    before = snapshot(migrated_db)
    assert commit(client, src, v["config_hash"]).status_code == 409
    assert snapshot(migrated_db) == before


def test_upload_limits(client, monkeypatch):
    from app.config import get_settings

    r = upload_source(client, b"x" * (int(get_settings().max_upload_bytes) + 10), "big.csv")
    assert r.status_code == 413
    assert upload_source(client, b"PK\x03\x04junk", "f.xlsx").status_code == 422
    assert upload_source(client, b"hello", "f.pdf").status_code == 422
    bomb = io.BytesIO()
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("xl/big.bin", b"\0" * (101 * 1024 * 1024))
    r = upload_source(client, bomb.getvalue(), "bomb.xlsx")
    assert r.status_code == 422 and "слишком велика" in r.json()["detail"]["message"]


def test_example_workbook_is_synthetic_and_imports(client):
    src = upload_source(client, EXAMPLE.read_bytes(), "example.xlsx").json()
    assert src["sheet_suggestion"]["name"] == "Результаты"
    assert any(s["hidden"] for s in src["sheets"])
    ins = src["inspection"]
    assert ins["header_row"] == 3
    v = validate(client, src, "Результаты", 3, ru_fields()).json()
    assert v["ok"], v["errors"][:3]
    assert v["total_rows"] == 36 and all(r["student_id"].startswith("SYN-") for r in v["preview"])


def test_legacy_header_csv_still_uses_one_step_preview(client):
    r = client.post("/api/imports/preview", files={"file": ("x.csv", make_csv([]), "text/csv")}).json()
    assert r["error_counts"] == {"EMPTY_FILE": 1}
    r = client.post("/api/imports/preview", files={"file": ("x.csv", b"student_id,grade\nS1,7\n", "text/csv")}).json()
    assert r["error_counts"] == {"MISSING_COLUMN": 1} and r["records_validated"] is False
    assert HEADER  # keep the shared fixture import meaningful


def test_row_limit_is_enforced_at_validation(client, monkeypatch):
    from app.config import get_settings

    src = upload_source(client, multi_sheet_ru([ru_row(topic=f"SYN-T{i}") for i in range(6)]), "f.xlsx").json()
    monkeypatch.setattr(get_settings(), "max_upload_rows", 5)
    r = validate(client, src, "Результаты", 3, ru_fields())
    assert r.status_code == 413 and r.json()["detail"]["code"] == "TOO_MANY_ROWS"
