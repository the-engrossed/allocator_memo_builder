from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.domain.enums import IssueCode, ReturnInputUnit
from app.services.ingestion import (
    apply_mapping,
    collect_bare_return_decimals,
    infer_return_unit,
    map_columns,
    parse_mapped_rows,
    parse_period,
    parse_return,
    read_csv_records,
)
from app.services.validation import derive_status, select_observations, validate_upload


def _pipeline(csv_text: str):
    headers, records = read_csv_records(csv_text.encode("utf-8"))
    mapping, missing = map_columns(headers)
    if missing:
        issues = validate_upload(missing_columns=missing, parsed_rows=[], unit_inference=None)
        return mapping, missing, [], [], issues
    mapped = apply_mapping(records, mapping)
    inference = infer_return_unit(collect_bare_return_decimals(mapped))
    parsed = parse_mapped_rows(mapped, inference.unit)
    issues = validate_upload(missing_columns=[], parsed_rows=parsed, unit_inference=inference)
    observations = select_observations(parsed)
    return mapping, missing, parsed, observations, issues


def test_period_formats() -> None:
    assert parse_period("2023-01") == date(2023, 1, 1)
    assert parse_period("2023-01-31") == date(2023, 1, 1)
    assert parse_period("Jan-2023") == date(2023, 1, 1)
    assert parse_period("Jan 2023") == date(2023, 1, 1)
    assert parse_period("01/2023") == date(2023, 1, 1)
    assert parse_period("1/15/2023") == date(2023, 1, 1)


def test_period_rejects_garbage_and_day_first() -> None:
    for value in ("", "n/a", "not-a-date", "31/01/2023", "13/2023"):
        try:
            parse_period(value)
            raise AssertionError(f"expected failure for {value}")
        except ValueError:
            pass


def test_return_decimal() -> None:
    value, unit = parse_return("0.012", ReturnInputUnit.DECIMAL)
    assert value == Decimal("0.012")
    assert unit is ReturnInputUnit.DECIMAL
    value, unit = parse_return(" 0.012 ", ReturnInputUnit.DECIMAL)
    assert value == Decimal("0.012")


def test_return_percent_string() -> None:
    value, unit = parse_return("1.2%", ReturnInputUnit.DECIMAL)
    assert value == Decimal("0.012")
    assert unit is ReturnInputUnit.PERCENT
    value, _ = parse_return("-0.5 %", ReturnInputUnit.DECIMAL)
    assert value == Decimal("-0.005")


def test_return_numeric_percent_uses_file_unit() -> None:
    value, unit = parse_return("1.2", ReturnInputUnit.PERCENT)
    assert value == Decimal("0.012")
    assert unit is ReturnInputUnit.PERCENT


def test_return_rejects_non_numeric() -> None:
    for value in ("n/a", "", "abc"):
        try:
            parse_return(value, ReturnInputUnit.DECIMAL)
            raise AssertionError(f"expected failure for {value}")
        except ValueError:
            pass


def test_column_aliases() -> None:
    mapping, missing = map_columns(
        [
            "id",
            "manager",
            "strategy",
            "date",
            "return",
            "liquidity_frequency",
            "notice_days",
            "lockup_months",
            "mgmt_fee_bps",
            "perf_fee_bps",
            "notes",
        ]
    )
    assert missing == []
    assert mapping["fund_id"] == "id"
    assert mapping["fund_name"] == "manager"
    assert mapping["period"] == "date"
    assert mapping["net_return"] == "return"


def test_whitespace_insensitive_headers() -> None:
    mapping, missing = map_columns(
        [
            " ID ",
            "fund_name",
            "strategy",
            " month ",
            "monthly_return",
            "liquidity_frequency",
            "notice_days",
            "lockup_months",
            "mgmt_fee_bps",
            "perf_fee_bps",
            "notes",
        ]
    )
    assert missing == []
    assert mapping["fund_id"] == "ID"
    assert mapping["period"] == "month"


def test_file_level_percent_inference() -> None:
    inference = infer_return_unit([Decimal("1.2"), Decimal("1.5"), Decimal("0.8")])
    assert inference.unit is ReturnInputUnit.PERCENT
    assert inference.mixed_scale is True


def test_file_level_decimal_inference() -> None:
    inference = infer_return_unit([Decimal("0.012"), Decimal("0.01"), Decimal("-0.02")])
    assert inference.unit is ReturnInputUnit.DECIMAL
    assert inference.mixed_scale is False


def test_invalid_rows_never_become_observations() -> None:
    csv_text = _header() + "\n".join(
        [
            _row("F001", "2023-01", "0.01"),
            _row("F001", "bad-date", "0.01"),
            _row("F001", "2023-03", "n/a"),
            _row("F001", "2023-03", "0.02"),
            _row("F001", "2023-03", "0.03"),
        ]
    )
    _, _, parsed, observations, issues = _pipeline(csv_text)
    assert len(parsed) == 5
    assert [row.period for row in observations] == [date(2023, 1, 1)]
    codes = {issue.code for issue in issues}
    assert IssueCode.INVALID_PERIOD in codes
    assert IssueCode.INVALID_RETURN in codes
    assert IssueCode.DUPLICATE_PERIOD in codes


def test_missing_column_short_circuits() -> None:
    csv_text = "fund_id,fund_name,strategy,period,net_return\nF001,Alpha,Equity,2023-01,0.01\n"
    _, missing, _, observations, issues = _pipeline(csv_text)
    assert "liquidity_frequency" in missing
    assert observations == []
    assert issues[0].code is IssueCode.MISSING_COLUMN
    assert derive_status(issues, 0).value == "invalid"


def test_sample_universe_emits_expected_issue_codes() -> None:
    sample = _sample_csv_path()
    if sample is None:
        pytest.skip("sample_fund_universe.csv is not available")
    _, _, _, _, issues = _pipeline(sample.read_text())
    codes = {issue.code for issue in issues}
    assert IssueCode.RETURN_UNIT_INFERRED in codes
    assert IssueCode.INVALID_PERIOD in codes
    assert IssueCode.INVALID_RETURN in codes
    assert IssueCode.DUPLICATE_PERIOD in codes
    assert IssueCode.MISSING_MONTHS in codes
    assert IssueCode.SHORT_HISTORY in codes
    assert IssueCode.CONFLICTING_METADATA in codes
    assert IssueCode.MISSING_COLUMN not in codes


def _sample_csv_path() -> Path | None:
    candidates = [
        Path("/sample_data/sample_fund_universe.csv"),
        Path(__file__).resolve().parents[2] / "sample_data" / "sample_fund_universe.csv",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def _header() -> str:
    return (
        "fund_id,fund_name,strategy,period,net_return,liquidity_frequency,"
        "notice_days,lockup_months,mgmt_fee_bps,perf_fee_bps,notes\n"
    )


def _row(fund_id: str, period: str, net_return: str) -> str:
    return (
        f"{fund_id},Alpha,Equity,{period},{net_return},monthly,30,0,100,200,note\n"
    )
