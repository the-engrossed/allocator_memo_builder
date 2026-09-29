from datetime import date
from decimal import Decimal

import pytest

from app.domain.enums import AnalysisStatus, IssueCode, IssueSeverity, ReturnInputUnit
from app.services.ingestion import (
    MappedRow,
    ParsedRow,
    ReturnUnitInference,
    infer_return_unit,
    infer_return_units,
    parse_mapped_rows,
)
from app.services.validation import (
    derive_status,
    is_analysis_blocked,
    select_observations,
    validate_upload,
)


def _row(
    row_number: int,
    fund_id: str,
    period: str,
    net_return: str,
    **metadata: str,
) -> MappedRow:
    values = {
        "fund_id": fund_id,
        "fund_name": "Alpha",
        "strategy": "Equity",
        "period": period,
        "net_return": net_return,
        "liquidity_frequency": "monthly",
        "notice_days": "30",
        "lockup_months": "0",
        "mgmt_fee_bps": "100",
        "perf_fee_bps": "200",
        "notes": "",
        **metadata,
    }
    return MappedRow(row_number=row_number, raw=values, values=values)


def _parse(rows: list[MappedRow], unit: ReturnInputUnit = ReturnInputUnit.DECIMAL) -> list[ParsedRow]:
    return parse_mapped_rows(rows, {row.values["fund_id"]: unit for row in rows})


def _validate(parsed: list[ParsedRow]):
    return validate_upload(missing_columns=[], parsed_rows=parsed, unit_inferences={})


def _codes(issues) -> set[IssueCode]:
    return {issue.code for issue in issues}


def _monthly_rows(fund_id: str, count: int, net_return: str = "0.01", start: int = 1):
    rows: list[MappedRow] = []
    year, month = 2023, 1
    for index in range(count):
        rows.append(_row(start + index, fund_id, f"{year}-{month:02d}", net_return))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return rows


def test_missing_column_positive_and_negative() -> None:
    issues = validate_upload(missing_columns=["notes"], parsed_rows=[], unit_inferences={})
    assert issues[0].code is IssueCode.MISSING_COLUMN
    issues = _validate(_parse([_row(1, "F001", "2023-01", "0.01")]))
    assert IssueCode.MISSING_COLUMN not in _codes(issues)


def test_invalid_period_positive_and_negative() -> None:
    parsed = _parse([_row(1, "F001", "not-a-date", "0.01"), _row(2, "F001", "2023-01", "0.01")])
    invalid = [issue for issue in _validate(parsed) if issue.code is IssueCode.INVALID_PERIOD]
    assert invalid and invalid[0].row_numbers == [1]
    assert IssueCode.INVALID_PERIOD not in _codes(_validate(_parse([_row(1, "F001", "2023-01", "0.01")])))


def test_invalid_return_positive_and_negative() -> None:
    parsed = _parse([_row(1, "F001", "2023-01", "n/a"), _row(2, "F001", "2023-02", "0.01")])
    invalid = [issue for issue in _validate(parsed) if issue.code is IssueCode.INVALID_RETURN]
    assert invalid and invalid[0].row_numbers == [1]
    assert IssueCode.INVALID_RETURN not in _codes(_validate(_parse([_row(1, "F001", "2023-01", "0.01")])))


def test_duplicate_period_blocks_observations() -> None:
    parsed = _parse(
        [
            _row(1, "F001", "2023-01", "0.01"),
            _row(2, "F001", "2023-01", "0.02"),
            _row(3, "F001", "2023-02", "0.01"),
        ]
    )
    duplicate = next(i for i in _validate(parsed) if i.code is IssueCode.DUPLICATE_PERIOD)
    assert duplicate.severity is IssueSeverity.ERROR
    assert duplicate.row_numbers == [1, 2]
    assert [row.period for row in select_observations(parsed)] == [date(2023, 2, 1)]


def test_duplicate_period_negative() -> None:
    parsed = _parse([_row(1, "F001", "2023-01", "0.01"), _row(2, "F001", "2023-02", "0.01")])
    assert IssueCode.DUPLICATE_PERIOD not in _codes(_validate(parsed))


def test_missing_months_positive_and_negative() -> None:
    rows = [row for row in _monthly_rows("F001", 13) if row.values["period"] != "2023-07"]
    issues = _validate(_parse(rows))
    missing = next(issue for issue in issues if issue.code is IssueCode.MISSING_MONTHS)
    assert missing.details["missing_months"] == ["2023-07-01"]
    assert IssueCode.SHORT_HISTORY not in _codes(issues)

    assert IssueCode.MISSING_MONTHS not in _codes(_validate(_parse(_monthly_rows("F001", 12))))


def test_short_history_boundary() -> None:
    assert IssueCode.SHORT_HISTORY in _codes(_validate(_parse(_monthly_rows("F001", 11))))
    assert IssueCode.SHORT_HISTORY not in _codes(_validate(_parse(_monthly_rows("F001", 12))))


def test_conflicting_metadata_uses_first_row() -> None:
    parsed = _parse(
        [
            _row(1, "F001", "2023-01", "0.01", strategy="Equity"),
            _row(2, "F001", "2023-02", "0.01", strategy="Credit"),
        ]
    )
    conflict = next(i for i in _validate(parsed) if i.code is IssueCode.CONFLICTING_METADATA)
    assert conflict.details["chosen"]["strategy"] == "Equity"
    assert len(conflict.details["conflicts"]["strategy"]) == 2

    consistent = _parse(
        [
            _row(1, "F001", "2023-01", "0.01", strategy="Equity"),
            _row(2, "F001", "2023-02", "0.01", strategy="Equity"),
        ]
    )
    assert IssueCode.CONFLICTING_METADATA not in _codes(_validate(consistent))


def test_ambiguous_return_unit_warns_and_sets_needs_review() -> None:
    inference = ReturnUnitInference(
        unit=ReturnInputUnit.DECIMAL,
        median_abs_bare=0.15,
        bare_count=4,
        ambiguous=True,
        message="ambiguous",
    )
    parsed = _parse([_row(1, "F001", "2023-01", "0.15")])
    issues = validate_upload(
        missing_columns=[], parsed_rows=parsed, unit_inferences={"F001": inference}
    )
    unit_issues = [issue for issue in issues if issue.code is IssueCode.RETURN_UNIT_INFERRED]
    assert {issue.severity for issue in unit_issues} == {IssueSeverity.INFO, IssueSeverity.WARNING}
    assert all(issue.fund_id == "F001" for issue in unit_issues)
    assert derive_status(issues, 1) is AnalysisStatus.NEEDS_REVIEW


@pytest.mark.parametrize(
    ("values", "unit", "ambiguous"),
    [
        (["0.8", "1.2", "-0.5"], ReturnInputUnit.PERCENT, False),
        (["0.26", "-0.30", "0.27"], ReturnInputUnit.PERCENT, False),
        (["0.25", "-0.25", "0.20"], ReturnInputUnit.DECIMAL, True),
        (["0.10", "-0.12", "0.05"], ReturnInputUnit.DECIMAL, True),
        (["0.099", "-0.02", "0.12"], ReturnInputUnit.DECIMAL, False),
        (["0.012", "-0.004", "0.009"], ReturnInputUnit.DECIMAL, False),
    ],
)
def test_unit_inference_thresholds(
    values: list[str], unit: ReturnInputUnit, ambiguous: bool
) -> None:
    inference = infer_return_unit([Decimal(value) for value in values])
    assert inference.unit is unit
    assert inference.ambiguous is ambiguous


def test_fund_reporting_small_percentages_is_read_as_percent() -> None:
    rows = [
        _row(1, "PCT", "2023-01", "0.8"),
        _row(2, "PCT", "2023-02", "1.2"),
        _row(3, "PCT", "2023-03", "-0.5"),
    ]
    inferences = infer_return_units(rows)
    assert inferences["PCT"].unit is ReturnInputUnit.PERCENT

    parsed = parse_mapped_rows(rows, {fund: item.unit for fund, item in inferences.items()})
    assert [row.net_return for row in parsed] == [
        Decimal("0.008"),
        Decimal("0.012"),
        Decimal("-0.005"),
    ]
    issues = validate_upload(missing_columns=[], parsed_rows=parsed, unit_inferences=inferences)
    assert not any(
        issue.code is IssueCode.RETURN_UNIT_INFERRED and issue.severity is IssueSeverity.WARNING
        for issue in issues
    )


def test_return_units_are_inferred_per_fund() -> None:
    rows = [
        *_monthly_rows("DEC", 6, net_return="0.012"),
        *_monthly_rows("PCT", 6, net_return="1.2", start=7),
    ]
    inferences = infer_return_units(rows)
    assert inferences["DEC"].unit is ReturnInputUnit.DECIMAL
    assert inferences["PCT"].unit is ReturnInputUnit.PERCENT

    parsed = parse_mapped_rows(rows, {fund: item.unit for fund, item in inferences.items()})
    returns = {(row.fund_id, str(row.net_return)) for row in parsed}
    assert returns == {("DEC", "0.012"), ("PCT", "0.012")}


def test_percent_suffix_is_independent_of_fund_unit() -> None:
    rows = [_row(1, "F001", "2023-01", "1.5%"), _row(2, "F001", "2023-02", "0.015")]
    inferences = infer_return_units(rows)
    parsed = parse_mapped_rows(rows, {fund: item.unit for fund, item in inferences.items()})
    assert [str(row.net_return) for row in parsed] == ["0.015", "0.015"]


@pytest.mark.parametrize("value", ["0.51", "-0.5001", "75%"])
def test_return_beyond_half_blocks_the_fund(value: str) -> None:
    parsed = _parse([_row(1, "F001", "2023-01", value), _row(2, "F001", "2023-02", "0.01")])
    issues = _validate(parsed)
    issue = next(i for i in issues if i.code is IssueCode.RETURN_OUT_OF_RANGE)
    assert issue.severity is IssueSeverity.ERROR
    assert issue.row_numbers == [1]
    assert is_analysis_blocked("F001", issues)
    assert [row.row_number for row in select_observations(parsed)] == [1, 2]


def test_out_of_range_return_blocks_only_its_fund() -> None:
    parsed = _parse([_row(1, "F001", "2023-01", "0.9"), _row(2, "F002", "2023-01", "0.01")])
    issues = _validate(parsed)
    assert is_analysis_blocked("F001", issues)
    assert not is_analysis_blocked("F002", issues)


@pytest.mark.parametrize("value", ["0.5", "-0.5", "50%", "0.4999"])
def test_return_at_half_is_accepted(value: str) -> None:
    parsed = _parse([_row(1, "F001", "2023-01", value)])
    issues = _validate(parsed)
    assert IssueCode.RETURN_OUT_OF_RANGE not in _codes(issues)
    assert not is_analysis_blocked("F001", issues)


def test_no_negative_month_across_24_observations_is_smooth() -> None:
    returns = ["0.004", "0.012"] * 12
    rows = [_row(i + 1, "F001", f"{2023 + i // 12}-{i % 12 + 1:02d}", r) for i, r in enumerate(returns)]
    issue = next(i for i in _validate(_parse(rows)) if i.code is IssueCode.SMOOTH_RETURNS)
    assert issue.severity is IssueSeverity.WARNING
    assert issue.details["negative_months"] == 0
    assert issue.details["observations"] == 24


def test_no_negative_month_below_24_observations_is_not_smooth() -> None:
    returns = ["0.004", "0.030"] * 11 + ["0.004"]
    rows = [_row(i + 1, "F001", f"{2023 + i // 12}-{i % 12 + 1:02d}", r) for i, r in enumerate(returns)]
    assert IssueCode.SMOOTH_RETURNS not in _codes(_validate(_parse(rows)))


def test_one_loss_month_is_not_smooth_when_volatility_is_normal() -> None:
    returns = ["0.004", "0.030"] * 12
    returns[5] = "-0.001"
    rows = [_row(i + 1, "F001", f"{2023 + i // 12}-{i % 12 + 1:02d}", r) for i, r in enumerate(returns)]
    assert IssueCode.SMOOTH_RETURNS not in _codes(_validate(_parse(rows)))


def test_low_volatility_with_losses_is_smooth() -> None:
    returns = ["0.003", "-0.001", "0.004", "0.002"] * 3
    rows = [_row(i + 1, "F001", f"2023-{i + 1:02d}", r) for i, r in enumerate(returns)]
    issue = next(i for i in _validate(_parse(rows)) if i.code is IssueCode.SMOOTH_RETURNS)
    assert Decimal(issue.details["annualized_volatility"]) < Decimal("0.01")
    assert issue.details["negative_months"] == 3


def test_low_volatility_needs_twelve_observations() -> None:
    returns = ["0.003", "-0.001", "0.004", "0.002"] * 2 + ["0.003", "-0.001", "0.004"]
    rows = [_row(i + 1, "F001", f"2023-{i + 1:02d}", r) for i, r in enumerate(returns)]
    assert IssueCode.SMOOTH_RETURNS not in _codes(_validate(_parse(rows)))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("notice_days", "30.5"),
        ("notice_days", "-1"),
        ("notice_days", ""),
        ("lockup_months", "121"),
        ("lockup_months", "twelve"),
        ("mgmt_fee_bps", "1.5%"),
        ("perf_fee_bps", "10001"),
        ("liquidity_frequency", "weekly"),
        ("liquidity_frequency", "quarterly-ish"),
        ("liquidity_frequency", ""),
    ],
)
def test_invalid_metadata_is_an_error(field: str, value: str) -> None:
    parsed = _parse([_row(1, "F001", "2023-01", "0.01", **{field: value})])
    issue = next(i for i in _validate(parsed) if i.code is IssueCode.INVALID_METADATA)
    assert issue.severity is IssueSeverity.ERROR
    assert issue.field == field
    assert issue.row_numbers == [1]
    assert issue.details["values"] == [value]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("notice_days", "0"),
        ("notice_days", " 3650 "),
        ("lockup_months", "120"),
        ("perf_fee_bps", "10000"),
        ("liquidity_frequency", "Quarterly"),
        ("liquidity_frequency", "semi-annual"),
        ("liquidity_frequency", "SEMIANNUAL"),
        ("liquidity_frequency", "annual"),
    ],
)
def test_valid_metadata_is_accepted(field: str, value: str) -> None:
    parsed = _parse([_row(1, "F001", "2023-01", "0.01", **{field: value})])
    assert IssueCode.INVALID_METADATA not in _codes(_validate(parsed))


def test_invalid_metadata_groups_rows_per_fund_and_field() -> None:
    parsed = _parse(
        [
            _row(1, "F001", "2023-01", "0.01", mgmt_fee_bps="2%"),
            _row(2, "F001", "2023-02", "0.01", mgmt_fee_bps="2%"),
            _row(3, "F002", "2023-01", "0.01", mgmt_fee_bps="2%"),
        ]
    )
    issues = [i for i in _validate(parsed) if i.code is IssueCode.INVALID_METADATA]
    assert sorted((i.fund_id, i.row_numbers) for i in issues) == [("F001", [1, 2]), ("F002", [3])]


def test_status_valid_with_warnings() -> None:
    issues = _validate(_parse(_monthly_rows("F001", 11)))
    assert derive_status(issues, 11) is AnalysisStatus.VALID_WITH_WARNINGS
