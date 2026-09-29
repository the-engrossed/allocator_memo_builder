from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.domain.enums import IssueCode, IssueSeverity, ReturnInputUnit
from app.seed.sample_data import write_csv
from app.services.ingestion import (
    apply_mapping,
    infer_return_unit,
    infer_return_units,
    map_columns,
    parse_mapped_rows,
    parse_period,
    parse_return,
    read_csv_records,
)
from app.services.validation import (
    derive_status,
    is_analysis_blocked,
    select_observations,
    validate_upload,
)


def _pipeline(csv_text: str):
    headers, records = read_csv_records(csv_text.encode("utf-8"))
    mapping, missing = map_columns(headers)
    if missing:
        issues = validate_upload(missing_columns=missing, parsed_rows=[], unit_inferences={})
        return mapping, missing, [], [], issues
    mapped = apply_mapping(records, mapping)
    inferences = infer_return_units(mapped)
    parsed = parse_mapped_rows(mapped, {fund: item.unit for fund, item in inferences.items()})
    issues = validate_upload(missing_columns=[], parsed_rows=parsed, unit_inferences=inferences)
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


def test_percent_inference() -> None:
    inference = infer_return_unit([Decimal("1.2"), Decimal("1.5"), Decimal("0.8")])
    assert inference.unit is ReturnInputUnit.PERCENT
    assert inference.ambiguous is False


def test_decimal_inference() -> None:
    inference = infer_return_unit([Decimal("0.012"), Decimal("0.01"), Decimal("-0.02")])
    assert inference.unit is ReturnInputUnit.DECIMAL
    assert inference.ambiguous is False


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


def test_sample_universe_plants_expected_issues() -> None:
    sample = _sample_csv_path()
    if sample is None:
        pytest.skip("sample_fund_universe.csv is not available")
    _, missing, _, observations, issues = _pipeline(sample.read_text())
    assert missing == []

    by_code: dict[IssueCode, set[str | None]] = {}
    for issue in issues:
        if issue.severity is not IssueSeverity.INFO:
            by_code.setdefault(issue.code, set()).add(issue.fund_id)
    assert by_code == {
        IssueCode.CONFLICTING_METADATA: {"F001"},
        IssueCode.FUND_ID_MISMATCH: {"F001", "F010"},
        IssueCode.INCONSISTENT_DATE_RANGE: {"F002", "F004", "F008", "F009", "F010"},
        IssueCode.MISSING_MONTHS: {"F004", "F006", "F009"},
        IssueCode.INVALID_RETURN: {"F006"},
        IssueCode.SMOOTH_RETURNS: {"F007"},
        IssueCode.SHORT_HISTORY: {"F008", "F010"},
        IssueCode.INVALID_PERIOD: {"F009"},
        IssueCode.RETURN_OUT_OF_RANGE: {"F009"},
        IssueCode.INVALID_METADATA: {"F009"},
    }
    metadata = next(i for i in issues if i.code is IssueCode.INVALID_METADATA)
    assert metadata.field == "perf_fee_bps"
    ends_early = {
        i.fund_id for i in issues
        if i.code is IssueCode.INCONSISTENT_DATE_RANGE and i.details["ends_early"]
    }
    assert ends_early == {"F004"}

    counts: dict[str, int] = {}
    last_period: dict[str, object] = {}
    for row in observations:
        counts[row.fund_id] = counts.get(row.fund_id, 0) + 1
        last_period[row.fund_id] = max(last_period.get(row.fund_id, row.period), row.period)
    assert len(counts) == 10
    assert {fund for fund, last in last_period.items() if last != date(2026, 8, 1)} == {"F004"}
    assert counts["F008"] == 11 and counts["F010"] == 8
    assert all(36 <= count <= 60 for fund, count in counts.items() if fund not in {"F008", "F010"})

    blocked = {fund for fund in counts if is_analysis_blocked(fund, issues)}
    assert blocked == {"F009"}
    out_of_range = next(i for i in issues if i.code is IssueCode.RETURN_OUT_OF_RANGE)
    assert out_of_range.row_numbers[0] in {row.row_number for row in observations}
    assert counts["F009"] == 53


def test_sample_csv_matches_generator(tmp_path: Path) -> None:
    sample = _sample_csv_path()
    if sample is None:
        pytest.skip("sample_fund_universe.csv is not available")
    generated = tmp_path / "generated.csv"
    write_csv(generated)
    assert generated.read_text() == sample.read_text(), (
        "Regenerate with: python -m app.seed.sample_data"
    )


def test_sample_universe_infers_units_per_fund() -> None:
    sample = _sample_csv_path()
    if sample is None:
        pytest.skip("sample_fund_universe.csv is not available")
    headers, records = read_csv_records(sample.read_bytes())
    mapping, _ = map_columns(headers)
    inferences = infer_return_units(apply_mapping(records, mapping))
    assert inferences["F003"].unit is ReturnInputUnit.PERCENT
    assert "F002" not in inferences
    assert all(
        item.unit is ReturnInputUnit.DECIMAL for fund, item in inferences.items() if fund != "F003"
    )


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
