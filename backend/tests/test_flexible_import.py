"""Flexible import: CSV options, two-row headers, ranges and row flags, wide/aggregate/general layouts, explicit
score and parsing rules, traceability, datasets and capability assessment. Synthetic fixtures only."""
from __future__ import annotations

import io

import openpyxl
import pytest
from sqlalchemy import text

from app.services import import_prep as prep
from app.services import import_rules as rules
from app.services.datasets import csv_safe
from tests.conftest import DEMO_CSV
from tests.test_guided_import import count, snapshot, upload_source

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def xlsx(rows: list[list], merges: tuple[str, ...] = (), title: str = "Журнал") -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = title
    for r in rows:
        ws.append(r)
    for m in merges:
        ws.merge_cells(m)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def body(src, sheet, header_row, **kw):
    return {"session_key": src["session_key"], "sheet": sheet, "header_row": header_row, **kw}


def validate(client, src, sheet, header_row, **kw):
    return client.post(f"/api/imports/{src['batch_id']}/validate", json=body(src, sheet, header_row, **kw))


def commit(client, src, v):
    return client.post(f"/api/imports/{src['batch_id']}/commit",
                       json={"session_key": src["session_key"], "config_hash": v["config_hash"]})


def inspect(client, src, sheet, header_row=None, **kw):
    return client.post(f"/api/imports/{src['batch_id']}/inspect", json=body(src, sheet, header_row, **kw))


IDENTITY = {"student_id": {"source": "column", "column": "c0"}, "class": {"source": "column", "column": "c1"},
            "grade": {"source": "value", "value": "7"}, "subject": {"source": "value", "value": "Математика"},
            "assessment_id": {"source": "value", "value": "SYN-KR1"}, "assessment_type": {"source": "value", "value": "post"},
            "assessment_date": {"source": "value", "value": "2026-05-20"}, "textbook_id": {"source": "none"}}


# --------------------------------------------------------------------------- CSV variations


def test_semicolon_csv_with_decimal_comma_and_leading_zeros(client):
    csv_text = ("Код ученика;Класс;Параллель;Предмет;Код темы;Тема;Код работы;Тип оценивания;Дата;Баллы;"
                "Максимальный балл;Код учебника\n"
                "007;7А;7;Математика;SYN-T1;Тема;SYN-A;post;20.05.2026;1,5;4;SYN-TB\n"
                "008;7А;7;Математика;SYN-T1;Тема;SYN-A;post;20.05.2026;3;4;SYN-TB\n")
    src = upload_source(client, csv_text.encode("utf-8"), "a.csv").json()
    assert src["csv_info"]["delimiter"] == ";" and src["csv_info"]["encoding"] == "utf-8"
    assert src["auto_ready"] is True
    fields = {f: {"source": "column", "column": s["column"]} for f, s in
              src["inspection"]["suggestions"]["suggested"].items()}
    v = validate(client, src, "CSV", 1, fields=fields).json()
    assert v["ok"], v["errors"]
    assert [p["student_id"] for p in v["preview"]] == ["007", "008"]  # leading zeros preserved
    assert v["preview"][0]["score"] == 1.5


def test_windows_1251_detection_and_encoding_override(client):
    content = "Код ученика;Баллы\nS1;5\nS2;4\n".encode("cp1251")
    src = upload_source(client, content, "w.csv").json()
    assert src["csv_info"]["encoding"] == "cp1251"
    assert src["inspection"]["columns"][0]["header"] == "Код ученика"
    r = inspect(client, src, "CSV", csv={"encoding": "utf-8", "delimiter": "auto"})
    assert r.status_code == 422 and "Windows-1251" in r.json()["detail"]["message"]


def test_tab_delimiter_detected_and_overridable(client):
    content = "a\tb\tc\n1\t2\t3\n4\t5\t6\n".encode()
    src = upload_source(client, content, "t.csv").json()
    assert src["csv_info"]["delimiter"] == "\t"
    forced = inspect(client, src, "CSV", 1, csv={"encoding": "auto", "delimiter": ","}).json()
    assert len(forced["inspection"]["columns"]) == 1  # the user's choice is respected, not second-guessed


def test_delimiter_uncertainty_is_reported():
    sheet, info = prep._read_csv("x;y,z\n1;2,3\n".encode(), 100)
    assert info["delimiter_confidence"] == "low" and info["delimiter_alternatives"]


# --------------------------------------------------------------------------- structure


def test_two_row_merged_header_labels():
    content = xlsx([["Код ученика", "Класс", "Контрольная 1", None, None],
                    [None, None, "Задание 1", "Задание 2", "Задание 3"],
                    ["S1", "7А", 1, 0, 2]], merges=("C1:E1", "A1:A2", "B1:B2"))
    wb = prep.read_workbook(content, "f.xlsx", max_data_rows=100, sheet_name="Журнал")
    sheet = wb.sheets[0]
    hdr = prep.suggest_header_row(sheet)
    assert hdr["row"] == 2 and hdr["header_rows"] == 2
    labels = [c.label for c in prep.header_columns(sheet, prep.Selection(2, 2))]
    assert labels == ["Код ученика", "Класс", "Контрольная 1 · Задание 1", "Контрольная 1 · Задание 2",
                      "Контрольная 1 · Задание 3"]


def test_total_and_note_rows_are_flagged_and_excluded_only_on_request(client, migrated_db):
    rows = [["Код ученика", "Класс", "Тема 1", "Тема 2"], ["S1", "7А", 3, 4], ["S2", "7А", 2, 1],
            ["Итого", None, 5, 5], ["Данные синтетические, без реальных учеников", None, None, None]]
    src = upload_source(client, xlsx(rows), "j.xlsx").json()
    ins = src["inspection"]
    assert {f["kind"] for f in ins["flags"]} == {"total", "note"}
    assert ins["layout_suggestion"]["layout"] == "wide"
    rc = [{"column": "c2", "topic_id": "SYN-T1", "topic_name": "Тема 1", "max_score": "5"},
          {"column": "c3", "topic_id": "SYN-T2", "topic_name": "Тема 2", "max_score": "5"}]
    kept = validate(client, src, "Журнал", 1, layout="wide", fields=IDENTITY, result_columns=rc,
                    confirm_shared=True).json()
    assert not kept["ok"]  # the "Итого" row is not silently dropped: it fails as a student record
    assert any(w["code"] == "FLAGGED_ROW" for w in kept["warnings"])
    v = validate(client, src, "Журнал", 1, layout="wide", fields=IDENTITY, result_columns=rc,
                 exclude=["total", "note"], confirm_shared=True).json()
    assert v["ok"], v["errors"]
    assert v["counts"]["excluded_rows"] == 2 and v["counts"]["excluded_row_numbers"] == [4, 5]
    assert v["config"]["excluded_kinds"] == ["итоговая строка", "пояснительный текст"]


def test_range_selection_limits_columns_and_rows(client):
    rows = [["Код ученика", "Класс", "Тема 1", "Комментарий"], ["S1", "7А", 3, "x"], ["S2", "7А", 2, "y"],
            [], ["Другая таблица", "a", "b", "c"]]
    src = upload_source(client, xlsx(rows), "r.xlsx").json()
    ins = inspect(client, src, "Журнал", 1, last_col=2, last_row=3).json()["inspection"]
    assert [c["letter"] for c in ins["columns"]] == ["A", "B", "C"] and ins["data_rows"] == 2
    bad = inspect(client, src, "Журнал", 1, first_col=2, last_col=1)
    assert bad.status_code == 422


# --------------------------------------------------------------------------- wide gradebooks


def gradebook() -> bytes:
    return xlsx([["Журнал 7 класса (синтетический)"],
                 ["Код ученика", "Класс", "Дроби", "Уравнения", "Проценты"],
                 ["SYN-01", "7А", 4, 3, "н"],
                 ["SYN-02", "7А", 2, None, 5],
                 ["SYN-03", "7Б", 5, 4, 1]])


def wide_columns(**extra):
    return [{"column": "c2", "topic_id": "SYN-FR", "topic_name": "Дроби", "max_score": "5", **extra},
            {"column": "c3", "topic_id": "SYN-EQ", "topic_name": "Уравнения", "max_score": "5", **extra},
            {"column": "c4", "topic_id": "SYN-PC", "topic_name": "Проценты", "max_score": "5", **extra}]


def test_wide_gradebook_normalises_with_traceability(client, migrated_db):
    src = upload_source(client, gradebook(), "g.xlsx").json()
    ins = src["inspection"]
    assert ins["header_row"] == 2 and ins["layout_suggestion"]["layout"] == "wide"
    assert [c["column"] for c in ins["wide_suggestion"]["result_columns"]] == ["c2", "c3", "c4"]
    v = validate(client, src, "Журнал", 2, layout="wide", fields=IDENTITY, result_columns=wide_columns(),
                 rules={"missing_markers": ["н"]}, confirm_shared=True).json()
    assert v["ok"], v["errors"]
    c = v["counts"]
    assert (c["source_rows"], c["records"], c["empty_result_cells"], c["missing_results"]) == (3, 7, 1, 1)
    assert "становится" in c["wide_explanation"]
    assert any(w["code"] == "MISSING_RESULTS" for w in v["warnings"])
    assert {(p["row"], p["source_column"]) for p in v["preview"]} >= {(3, "C"), (5, "E")}
    assert commit(client, src, v).status_code == 200
    with migrated_db.connect() as conn:
        rows = conn.execute(text("select r.source_row, r.source_column, r.score, t.code from assessment_results r "
                                 "join topics t on t.id = r.topic_id order by 1, 2")).all()
    assert len(rows) == 7
    assert (4, "E", 5.0, "SYN-PC") in rows  # SYN-02 «Проценты» traced to sheet row 4, column E
    assert not any(r[0] == 3 and r[1] == "E" for r in rows)  # "н" is absent, not zero


def test_wide_errors_point_to_row_and_column(client):
    rows = [["Код ученика", "Класс", "Дроби", "Уравнения"], ["SYN-01", "7А", 9, 3], ["SYN-02", "7А", "abc", 1]]
    src = upload_source(client, xlsx(rows), "g.xlsx").json()
    v = validate(client, src, "Журнал", 1, layout="wide", fields=IDENTITY, result_columns=wide_columns()[:2],
                 confirm_shared=True).json()
    errs = {(e["row"], e.get("source_column"), e["code"]) for e in v["errors"]}
    assert (2, "C", "SCORE_EXCEEDS_MAX") in errs and (3, "C", "INVALID_NUMBER") in errs
    e = next(e for e in v["errors"] if e["code"] == "INVALID_NUMBER")
    assert e["sheet"] == "Журнал" and e["value"] == "abc" and e["suggestion"]
    assert v["counts"]["invalid_records"] == 2 and v["counts"]["eligible"] == 0


def test_wide_requires_explicit_per_column_metadata(client):
    src = upload_source(client, gradebook(), "g.xlsx").json()
    r = validate(client, src, "Журнал", 2, layout="wide", fields=IDENTITY, confirm_shared=True,
                 result_columns=[{"column": "c2", "topic_name": "Дроби"}])
    codes = {(i["code"], i["field"]) for i in r.json()["detail"]["issues"]}
    assert ("MISSING_COLUMN_META", "topic_id") in codes and ("MISSING_COLUMN_META", "max_score") in codes
    r = validate(client, src, "Журнал", 2, layout="wide", fields=IDENTITY | {"score": {"source": "column",
                                                                                         "column": "c2"}},
                 result_columns=wide_columns()[1:], confirm_shared=True)
    assert "FIELD_NOT_ALLOWED" in {i["code"] for i in r.json()["detail"]["issues"]}
    r = validate(client, src, "Журнал", 2, layout="wide", fields=IDENTITY, confirm_shared=True,
                 result_columns=[{**wide_columns()[0], "assessment_id": "OTHER"}])
    assert "CONFLICTING_SOURCES" in {i["code"] for i in r.json()["detail"]["issues"]}


def test_totals_mixed_with_items_are_rejected(client):
    rows = [["Код ученика", "Класс", "Задание 1", "Задание 2", "Итого"], ["SYN-01", "7А", 1, 1, 2]]
    src = upload_source(client, xlsx(rows), "g.xlsx").json()
    assert [c["column"] for c in src["inspection"]["wide_suggestion"]["total_columns"]] == ["c4"]
    rc = [{"column": "c2", "topic_id": "SYN-T", "topic_name": "Т", "item_id": "Q1", "max_score": "1"},
          {"column": "c3", "topic_id": "SYN-T", "topic_name": "Т", "item_id": "Q2", "max_score": "1"},
          {"column": "c4", "topic_id": "SYN-T", "topic_name": "Т", "max_score": "2"}]
    v = validate(client, src, "Журнал", 1, layout="wide", fields=IDENTITY, result_columns=rc, confirm_shared=True).json()
    assert "MIXED_GRANULARITY" in v["error_counts"] and not v["ok"]


def test_wide_expansion_is_bounded(client, monkeypatch):
    from app.config import get_settings

    src = upload_source(client, gradebook(), "g.xlsx").json()
    monkeypatch.setattr(get_settings(), "max_upload_rows", 5)
    r = validate(client, src, "Журнал", 2, layout="wide", fields=IDENTITY, result_columns=wide_columns(),
                 confirm_shared=True)
    assert r.status_code == 413 and r.json()["detail"]["code"] == "TOO_MANY_RECORDS"


def test_wide_reimport_is_skipped_as_already_imported(client):
    for expected in (7, 0):
        src = upload_source(client, gradebook(), "g.xlsx").json()
        v = validate(client, src, "Журнал", 2, layout="wide", fields=IDENTITY, result_columns=wide_columns(),
                     rules={"missing_markers": ["н"]}, confirm_shared=True).json()
        assert v["ok"]
        assert commit(client, src, v).json()["inserted_rows"] == expected
    assert v["counts"]["existing_duplicates"] == 7 and v["counts"]["eligible"] == 0


# --------------------------------------------------------------------------- score & parsing rules


def long_rows(scores: list, header_score="Оценка", date="20.05.2026"):
    head = ["Код ученика", "Класс", "Код темы", "Тема", header_score, "Дата", "Максимальный балл"]
    return xlsx([head] + [[f"SYN-{i}", "7А", "SYN-T1", "Тема", s, date, 5] for i, s in enumerate(scores)])


WITH_MAX = {"max_score": {"source": "column", "column": "c6"}}


LONG = {"student_id": {"source": "column", "column": "c0"}, "class": {"source": "column", "column": "c1"},
        "topic_id": {"source": "column", "column": "c2"}, "topic_name": {"source": "column", "column": "c3"},
        "score": {"source": "column", "column": "c4"}, "assessment_date": {"source": "column", "column": "c5"},
        "grade": {"source": "value", "value": "7"}, "subject": {"source": "value", "value": "Математика"},
        "assessment_id": {"source": "value", "value": "SYN-A"}, "assessment_type": {"source": "value", "value": "post"},
        "textbook_id": {"source": "none"}}


def test_grade_scale_requires_explicit_table(client):
    src = upload_source(client, long_rows([5, 4, 3, 2]), "s.xlsx").json()
    assert "score" in src["inspection"]["suggestions"]["ambiguous"]  # «Оценка» is never preselected
    # Points need a maximum: it is never taken from the largest observed value.
    r = validate(client, src, "Журнал", 1, fields=LONG, confirm_shared=True)
    assert any(i["field"] == "max_score" for i in r.json()["detail"]["issues"])
    partial = {"score_mode": "scale", "scale": {"5": 100, "4": 75, "3": 50}}
    v = validate(client, src, "Журнал", 1, fields=LONG, rules=partial, confirm_shared=True).json()
    assert "SCALE_VALUE_UNDEFINED" in v["error_counts"] and not v["ok"]
    full = {"score_mode": "scale", "scale": {"5": 100, "4": 75, "3": 50, "2": 25}}
    v = validate(client, src, "Журнал", 1, fields=LONG, rules=full, confirm_shared=True).json()
    assert v["ok"], v["errors"]
    assert [(p["score"], p["max_score"]) for p in v["preview"]] == [(100, 100), (75, 100), (50, 100), (25, 100)]
    assert any("Шкала" in line for line in v["config"]["rules"])
    bad = validate(client, src, "Журнал", 1, fields=LONG, rules={"score_mode": "scale", "scale": {"5": 120}},
                   confirm_shared=True)
    assert bad.status_code == 422 and bad.json()["detail"]["issues"][0]["code"] == "INVALID_RULES"


def test_percent_and_binary_modes(client):
    src = upload_source(client, long_rows(["85%", "40", "0,5%"], header_score="Процент"), "p.xlsx").json()
    v = validate(client, src, "Журнал", 1, fields=LONG, rules={"score_mode": "percent"}, confirm_shared=True).json()
    assert v["ok"], v["errors"]
    assert [p["score"] for p in v["preview"]] == [85, 40, 0.5]
    src = upload_source(client, long_rows(["верно", "неверно", "?"], header_score="Ответ"), "b.xlsx").json()
    v = validate(client, src, "Журнал", 1, fields=LONG, confirm_shared=True,
                 rules={"score_mode": "binary", "true_tokens": ["верно"], "false_tokens": ["неверно"]}).json()
    assert v["error_counts"] == {"BINARY_VALUE_UNDEFINED": 1}
    e = v["errors"][0]
    assert (e["row"], e["source_column"], e["value"]) == (4, "E", "?")
    r = validate(client, src, "Журнал", 1, fields=LONG | WITH_MAX, rules={"score_mode": "percent"},
                 confirm_shared=True)
    assert "MAX_NOT_USED" in {i["code"] for i in r.json()["detail"]["issues"]}


def test_ambiguous_dates_need_a_format(client):
    src = upload_source(client, long_rows(["3"], header_score="Баллы", date="03/04/2026"), "d.xlsx").json()
    fields = LONG | WITH_MAX
    v = validate(client, src, "Журнал", 1, fields=fields, confirm_shared=True).json()
    assert v["error_counts"] == {"DATE_FORMAT_REQUIRED": 1}
    assert "формат даты" in v["errors"][0]["suggestion"]
    v = validate(client, src, "Журнал", 1, fields=fields, rules={"date_format": "DD/MM/YYYY"}, confirm_shared=True).json()
    assert v["ok"] and v["preview"][0]["assessment_date"] == "2026-04-03"
    v = validate(client, src, "Журнал", 1, fields=fields, rules={"date_format": "MM/DD/YYYY"}, confirm_shared=True).json()
    assert v["preview"][0]["assessment_date"] == "2026-03-04"


def test_decimal_rules():
    assert rules.parse_num("1,000", "comma") == (1.0, None)
    assert rules.parse_num("1,000", "dot") == (1000.0, None)
    assert rules.parse_num("1.000,5", "comma") == (1000.5, None)
    assert rules.parse_num("1,000", "auto")[1] == "AMBIGUOUS_NUMBER"
    assert rules.parse_num("12%", "comma")[1] == "INVALID_NUMBER"


def test_missing_marker_is_not_zero(client):
    src = upload_source(client, long_rows([3, "н/я"], header_score="Баллы"), "m.xlsx").json()
    fields = LONG | {"max_score": {"source": "value", "value": "5"}}
    r = validate(client, src, "Журнал", 1, fields=fields, confirm_shared=True)
    assert r.status_code == 422  # max_score cannot be a shared value: it is never assumed
    fields = LONG | WITH_MAX
    v = validate(client, src, "Журнал", 1, fields=fields, confirm_shared=True).json()
    assert "MISSING_VALUE" not in v["error_counts"] and "INVALID_NUMBER" in v["error_counts"]
    v = validate(client, src, "Журнал", 1, fields=fields, rules={"missing_markers": ["н/я"]}, confirm_shared=True).json()
    assert v["ok"] and v["counts"]["missing_results"] == 1 and len(v["preview"]) == 1


# --------------------------------------------------------------------------- aggregate and general datasets


def test_aggregate_topic_table_is_kept_as_aggregate(client, migrated_db):
    rows = [["Класс", "Тема", "Средний %", "Количество учеников"], ["7А", "Дроби", 62.5, 24],
            ["7Б", "Дроби", 70, 20], ["7А", "Уравнения", 81, 24]]
    src = upload_source(client, xlsx(rows, title="Сводка"), "agg.xlsx").json()
    ins = src["inspection"]
    assert ins["layout_suggestion"]["layout"] == "aggregate"
    roles = ins["aggregate_suggestion"]
    assert sorted(roles.values()) == ["class", "count", "topic_name", "value"]
    before = snapshot(migrated_db)
    r = validate(client, src, "Сводка", 1, layout="aggregate", roles=roles, metric={})
    assert "MISSING_METRIC" in {i["code"] for i in r.json()["detail"]["issues"]}
    v = validate(client, src, "Сводка", 1, layout="aggregate", roles=roles, metric={"kind": "percent"},
                 dataset_name="Сводка по темам").json()
    assert v["ok"] and v["counts"]["eligible"] == 3 and "AGGREGATE_DATA" in v["warning_counts"]
    caps = {c["key"]: c for c in v["capabilities"]}
    assert caps["aggregate"]["available"] and not caps["gains"]["available"] and not caps["textbooks"]["available"]
    res = commit(client, src, v).json()
    assert res["kind"] == "aggregate" and res["inserted_rows"] == 3
    assert snapshot(migrated_db) == before  # never converted into student records
    ds = client.get(f"/api/datasets/{res['dataset_id']}").json()
    fr = next(g for g in ds["aggregate"]["by_topic"] if g["group"] == "Дроби")
    assert fr["mean_of_groups_pct"] == 66.2 and fr["weighted_pct"] == round((62.5 * 24 + 70 * 20) / 44, 1)


def test_aggregate_mean_points_requires_a_maximum(client):
    rows = [["Класс", "Средний балл"], ["7А", 3.4]]
    src = upload_source(client, xlsx(rows, title="С"), "a.xlsx").json()
    roles = {"c0": "class", "c1": "value"}
    r = validate(client, src, "С", 1, layout="aggregate", roles=roles, metric={"kind": "mean_points"})
    assert "MISSING_MAX" in {i["code"] for i in r.json()["detail"]["issues"]}
    v = validate(client, src, "С", 1, layout="aggregate", roles=roles,
                 metric={"kind": "mean_points", "max_value": "5"}).json()
    assert v["ok"] and v["preview"][0]["pct"] == 68.0


def test_general_table_exploration_search_sort_filter_and_safe_export(client, migrated_db):
    rows = [["Код", "Город", "Дата поставки", "Количество", "Комментарий"]] + [
        [f"{i:03d}", ["Алматы", "Астана"][i % 2], f"2026-0{1 + i % 3}-15", i * 1.5, "@SUM(A1)" if i == 2
         else "ok"] for i in range(1, 7)]
    src = upload_source(client, xlsx(rows, title="Склад"), "stock.xlsx").json()
    ins = src["inspection"]
    assert ins["layout_suggestion"]["layout"] == "general"
    types = ins["type_suggestion"]
    assert types["c0"] == "identifier" and types["c1"] == "category" and types["c2"] == "date" \
        and types["c3"] == "number"
    before = snapshot(migrated_db)
    v = validate(client, src, "Склад", 1, layout="general", types=types).json()
    assert v["ok"] and {c["key"] for c in v["capabilities"] if c["available"]} == {"explore"}
    res = commit(client, src, v).json()
    assert snapshot(migrated_db) == before
    ds = client.get(f"/api/datasets/{res['dataset_id']}").json()
    prof = {c["letter"]: c for c in ds["profile"]["column_profiles"]}
    assert "numeric" not in prof["A"]  # identifiers are not summarised as numbers
    assert prof["D"]["numeric"]["max"] == 9.0 and prof["C"]["date_range"] == {"from": "2026-01-15", "to": "2026-03-15"}
    assert {f["value"] for f in prof["B"]["frequencies"]} == {"Алматы", "Астана"}
    q = client.get(f"/api/datasets/{res['dataset_id']}/rows", params={"q": "астана", "sort": "c3",
                                                                      "direction": "desc"}).json()
    assert q["total"] == 3 and [r["values"][0] for r in q["rows"]] == ["005", "003", "001"]
    f = client.get(f"/api/datasets/{res['dataset_id']}/rows", params={"filter_col": "c1", "filter_value": "Алматы"})
    assert f.json()["total"] == 3
    exp = client.get(f"/api/datasets/{res['dataset_id']}/export.csv").content.decode("utf-8-sig")
    assert "'@SUM(A1)" in exp and "\n2;001;" in exp.replace("\r\n", "\n")
    with migrated_db.connect() as conn:
        stored = conn.execute(text("select values->>4 from dataset_rows where source_row = 3")).scalar_one()
    assert stored == "@SUM(A1)"  # the original value is preserved; only the export is neutralised
    upd = client.put(f"/api/datasets/{res['dataset_id']}/columns", json={"types": {"c3": "text"}}).json()
    assert "numeric" not in {c["letter"]: c for c in upd["profile"]["column_profiles"]}["D"]


def test_dataset_reimport_is_announced(client):
    content = xlsx([["Город", "Число"], ["А", 1]], title="Т")  # the same bytes both times
    for i in range(2):
        src = upload_source(client, content, "t.xlsx").json()
        v = validate(client, src, "Т", 1, layout="general").json()
        if i == 0:
            commit(client, src, v)
    assert "DATASET_ALREADY_IMPORTED" in v["warning_counts"]


def test_csv_safe():
    assert csv_safe("=1+1") == "'=1+1" and csv_safe("@SUM(A1)") == "'@SUM(A1)" and csv_safe("-5") == "-5"
    assert csv_safe("+7 701") == "'+7 701" and csv_safe("plain") == "plain"


# --------------------------------------------------------------------------- capabilities


def test_capabilities_explain_missing_metadata(client):
    src = upload_source(client, gradebook(), "g.xlsx").json()
    v = validate(client, src, "Журнал", 2, layout="wide", fields=IDENTITY, result_columns=wide_columns(),
                 rules={"missing_markers": ["н"]}, confirm_shared=True).json()
    caps = {c["key"]: c for c in v["capabilities"]}
    assert caps["overview"]["available"] and caps["topics"]["available"] and caps["topics"]["partial"]
    assert caps["textbooks"]["missing"] == ["Для сравнения учебников укажите столбец с учебником."]
    assert not caps["gains"]["available"] and "входная" in caps["gains"]["missing"][0]
    assert not caps["optimizer"]["available"]


def test_capabilities_for_the_full_demo_dataset(client):
    r = client.post("/api/imports/preview", files={"file": ("d.csv", DEMO_CSV.read_bytes(), "text/csv")}).json()
    client.post(f"/api/imports/{r['batch_id']}/commit")
    caps = {c["key"]: c for c in client.get("/api/analytics/capabilities").json()["capabilities"]}
    assert all(caps[k]["available"] for k in ("overview", "topics", "gains", "trends", "textbooks", "optimizer"))
    empty = {c["key"]: c for c in client.get("/api/analytics/capabilities?grade=11").json()["capabilities"]}
    assert not empty["overview"]["available"]


def test_traceability_for_long_imports(client, migrated_db):
    r = client.post("/api/imports/preview", files={"file": ("d.csv", DEMO_CSV.read_bytes(), "text/csv")}).json()
    client.post(f"/api/imports/{r['batch_id']}/commit")
    assert count(migrated_db, "assessment_results where source_row is null") == 0
    with migrated_db.connect() as conn:
        assert conn.execute(text("select min(source_row) from assessment_results")).scalar_one() == 2


@pytest.mark.parametrize("raw,msg", [({"decimal": "x"}, "десятичного"), ({"score_mode": "binary"}, "верно"),
                                     ({"date_format": "YYYY/DD"}, "формат даты")])
def test_invalid_rules_are_rejected(raw, msg):
    with pytest.raises(rules.RuleError, match=msg):
        rules.parse_rules(raw)
