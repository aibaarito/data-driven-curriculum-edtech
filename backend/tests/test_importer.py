import io

import openpyxl
import pytest

from app.services.importer import FileFormatError, read_table, validate_dataframe
from tests.conftest import HEADER, make_csv

OK = "s,STU-1,7,7А,Математика,T1,Тема 1,A1,pre,2025-09-10,G1,Q1,2,4,TB-A,10"


def validate(content: bytes, name: str = "f.csv"):
    return validate_dataframe(read_table(content, name))


def codes(res):
    return {e.code for e in res.errors}


def test_valid_csv_parses():
    res = validate(make_csv([OK, OK.replace("Q1", "Q2")]))
    assert res.ok and res.total_rows == 2 and len(res.rows) == 2
    assert res.rows[0]["score"] == 2.0 and res.rows[0]["max_score"] == 4.0
    assert res.summary["students"] == 1 and res.summary["item_level"] is True


def test_supported_csv_encodings_preserve_values():
    source = make_csv([OK]).decode("utf-8")
    for encoding in ("utf-8-sig", "cp1251"):
        result = validate(source.encode(encoding))
        assert result.ok and result.rows[0]["score"] == 2
        assert result.rows[0]["subject"] == "Математика"


def test_nonfinite_score_tokens_are_rejected_without_echoing_them():
    for token in ("NaN", "Infinity", "-Infinity"):
        result = validate(make_csv([OK.replace(",2,4,", f",{token},4,")]))
        assert not result.ok and "INVALID_NUMBER" in codes(result)
        assert all(token not in error.message for error in result.errors)


def test_xlsx_parses():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(HEADER.split(","))
    ws.append(OK.split(","))
    buf = io.BytesIO()
    wb.save(buf)
    res = validate(buf.getvalue(), "data.xlsx")
    assert res.ok and res.rows[0]["student_id"] == "STU-1"


def test_semicolon_csv_with_decimal_comma():
    header = HEADER.replace(",", ";")
    row = OK.replace(",", ";").replace(";2;4;", ";1,5;4;")
    res = validate(make_csv([row], header))
    assert res.ok and res.rows[0]["score"] == 1.5


@pytest.mark.parametrize("content,name,msg", [
    (b"", "a.csv", "пустой"),
    (b"hello", "a.pdf", "Неподдерживаемый"),
    (b"PK\x03\x04garbage", "a.xlsx", "Excel"),
    (b"not a zip", "a.xlsx", "не является"),
    (b"PK\x03\x04", "a.csv", "двоичные"),
])
def test_invalid_files(content, name, msg):
    with pytest.raises(FileFormatError, match=msg):
        read_table(content, name)


def test_header_only_is_empty_file():
    res = validate(make_csv([]))
    assert not res.ok and "EMPTY_FILE" in codes(res)


def test_missing_columns():
    res = validate(b"student_id,grade\nS1,7\n")
    assert not res.ok and codes(res) == {"MISSING_COLUMN"}


@pytest.mark.parametrize("row,code", [
    (OK.replace(",2,4,", ",,4,"), "MISSING_VALUE"),
    (OK.replace(",2,4,", ",abc,4,"), "INVALID_NUMBER"),
    (OK.replace(",2,4,", ",5,4,"), "SCORE_EXCEEDS_MAX"),
    (OK.replace(",2,4,", ",0,0,"), "NON_POSITIVE_MAX"),
    (OK.replace(",2,4,", ",-1,4,"), "NEGATIVE_SCORE"),
    (OK.replace("2025-09-10", "10/09/2025"), "INVALID_DATE"),
    (OK.replace(",pre,", ",exam,"), "INVALID_ASSESSMENT_TYPE"),
    (OK.replace(",7,7А,", ",13,7А,"), "INVALID_GRADE"),
    (OK.replace("STU-1", "Иван Петров"), "POSSIBLE_PERSONAL_DATA"),
    (OK.replace(",10", ",-3"), "INVALID_HOURS"),
    (OK.replace(",2,4,", ",inf,4,"), "INVALID_NUMBER"),
])
def test_row_errors_are_reported_not_fixed(row, code):
    res = validate(make_csv([row]))
    assert not res.ok
    assert code in codes(res)
    assert res.errors[0].row == 2  # spreadsheet row number


def test_duplicate_rows_detected():
    res = validate(make_csv([OK, OK]))
    assert "DUPLICATE_ROW" in codes(res)
    assert [e.row for e in res.errors if e.code == "DUPLICATE_ROW"] == [3]


def test_conflicting_assessment_metadata():
    other = OK.replace("Q1", "Q2").replace("2025-09-10", "2025-09-11")
    res = validate(make_csv([OK, other]))
    assert "CONFLICT" in codes(res)


def test_student_in_two_classes_conflict():
    other = OK.replace("Q1", "Q2").replace("7А", "7Б")
    res = validate(make_csv([OK, other]))
    assert "CONFLICT" in codes(res)


def test_missing_textbook_is_warning_not_error():
    row = OK.replace(",TB-A,", ",,")
    res = validate(make_csv([row]))
    assert res.ok
    assert any(w.code == "MISSING_TEXTBOOK" for w in res.warnings)


def test_missing_hours_and_group_warnings():
    row = OK.replace(",G1,", ",,").rsplit(",", 1)[0] + ","
    res = validate(make_csv([row]))
    assert res.ok
    assert {"MISSING_HOURS", "MISSING_COMPARISON_GROUP"} <= {w.code for w in res.warnings}


def test_one_student_one_row_ok():
    res = validate(make_csv([OK]))
    assert res.ok and res.summary["students"] == 1


def test_unknown_prerequisite_rejected():
    header = HEADER + ",topic_prerequisites"
    res = validate(make_csv([OK + ",T99"], header))
    assert "UNKNOWN_PREREQUISITE" in codes(res)


def test_blank_rows_are_counted():
    content = make_csv([OK]) + b",,,,,,,,,,,,,,,\n"
    res = validate(content)
    assert res.ok and any(w.code == "BLANK_ROWS" for w in res.warnings)


def test_demo_dataset_is_valid():
    from tests.conftest import DEMO_CSV
    res = validate(DEMO_CSV.read_bytes())
    assert res.ok, res.as_dict()["errors"][:3]
    assert res.summary["students"] >= 150
