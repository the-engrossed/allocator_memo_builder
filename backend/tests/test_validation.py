from datetime import date
from decimal import Decimal

from app.domain.enums import AnalysisStatus, IssueCode, IssueSeverity, ReturnInputUnit
from app.services.ingestion import (
    MappedRow,
    ParsedRow,
    ReturnUnitInference,
    parse_mapped_rows,
)
from app.services.validation import derive_status, select_observations, validate_upload


def _row(
    row_number: int,
    fund_id: str,
    period: str,
    net_return: str,
    *,
    strategy: str = "Equity",
    fund_name: str = "Alpha",
) -> MappedRow:
    values = {
        "fund_id": fund_id,
        "fund_name": fund_name,
        "strategy": strategy,
        "period": period,
        "net_return": net_return,
        "liquidity_frequency": "monthly",
        "notice_days": "30",
        "lockup_months": "0",
        "mgmt_fee_bps": "100",
        "perf_fee_bps": "200",
        "notes": "",
    }
    return MappedRow(row_number=row_number, raw=values, values=values)


def _parse(rows: list[MappedRow], unit: ReturnInputUnit = ReturnInputUnit.DECIMAL) -> list[ParsedRow]:
    return parse_mapped_rows(rows, unit)


def _info_unit() -> ReturnUnitInference:
    return ReturnUnitInference(
        unit=ReturnInputUnit.DECIMAL,
        median_abs_bare=0.01,
        bare_count=12,
        mixed_scale=False,
        message="inferred decimals",
    )


def test_missing_column_positive_and_negative() -> None:
    issues = validate_upload(
        missing_columns=["notes"], parsed_rows=[], unit_inference=None
    )
    assert issues[0].code is IssueCode.MISSING_COLUMN
    issues = validate_upload(
        missing_columns=[],
        parsed_rows=_parse([_row(1, "F001", "2023-01", "0.01")]),
        unit_inference=_info_unit(),
    )
    assert IssueCode.MISSING_COLUMN not in {issue.code for issue in issues}


def test_invalid_period_positive_and_negative() -> None:
    parsed = _parse([_row(1, "F001", "not-a-date", "0.01"), _row(2, "F001", "2023-01", "0.01")])
    issues = validate_upload(missing_columns=[], parsed_rows=parsed, unit_inference=_info_unit())
    invalid = [issue for issue in issues if issue.code is IssueCode.INVALID_PERIOD]
    assert invalid and invalid[0].row_numbers == [1]
    clean = _parse([_row(1, "F001", "2023-01", "0.01")])
    issues = validate_upload(missing_columns=[], parsed_rows=clean, unit_inference=_info_unit())
    assert IssueCode.INVALID_PERIOD not in {issue.code for issue in issues}


def test_invalid_return_positive_and_negative() -> None:
    parsed = _parse([_row(1, "F001", "2023-01", "n/a"), _row(2, "F001", "2023-02", "0.01")])
    issues = validate_upload(missing_columns=[], parsed_rows=parsed, unit_inference=_info_unit())
    invalid = [issue for issue in issues if issue.code is IssueCode.INVALID_RETURN]
    assert invalid and invalid[0].row_numbers == [1]
    clean = _parse([_row(1, "F001", "2023-01", "0.01")])
    issues = validate_upload(missing_columns=[], parsed_rows=clean, unit_inference=_info_unit())
    assert IssueCode.INVALID_RETURN not in {issue.code for issue in issues}


def test_duplicate_period_blocks_observations() -> None:
    parsed = _parse(
        [
            _row(1, "F001", "2023-01", "0.01"),
            _row(2, "F001", "2023-01", "0.02"),
            _row(3, "F001", "2023-02", "0.01"),
        ]
    )
    issues = validate_upload(missing_columns=[], parsed_rows=parsed, unit_inference=_info_unit())
    duplicate = next(issue for issue in issues if issue.code is IssueCode.DUPLICATE_PERIOD)
    assert duplicate.severity is IssueSeverity.ERROR
    assert duplicate.row_numbers == [1, 2]
    observations = select_observations(parsed)
    assert [row.period for row in observations] == [date(2023, 2, 1)]


def test_duplicate_period_negative() -> None:
    parsed = _parse([_row(1, "F001", "2023-01", "0.01"), _row(2, "F001", "2023-02", "0.01")])
    issues = validate_upload(missing_columns=[], parsed_rows=parsed, unit_inference=_info_unit())
    assert IssueCode.DUPLICATE_PERIOD not in {issue.code for issue in issues}


def test_missing_months_positive_and_negative() -> None:
    rows: list[MappedRow] = []
    index = 1
    year, month = 2023, 1
    while (year, month) <= (2024, 1):
        if not (year == 2023 and month == 7):
            rows.append(_row(index, "F001", f"{year}-{month:02d}", "0.01"))
            index += 1
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1
    parsed = _parse(rows)
    issues = validate_upload(missing_columns=[], parsed_rows=parsed, unit_inference=_info_unit())
    missing = next(issue for issue in issues if issue.code is IssueCode.MISSING_MONTHS)
    assert missing.details["missing_months"] == ["2023-07-01"]
    assert IssueCode.SHORT_HISTORY not in {issue.code for issue in issues}

    consecutive = _parse(
        [_row(index, "F001", f"2023-{month:02d}", "0.01") for index, month in enumerate(range(1, 13), start=1)]
    )
    issues = validate_upload(missing_columns=[], parsed_rows=consecutive, unit_inference=_info_unit())
    assert IssueCode.MISSING_MONTHS not in {issue.code for issue in issues}


def test_short_history_boundary() -> None:
    eleven = _parse(
        [_row(index, "F001", f"2023-{month:02d}", "0.01") for index, month in enumerate(range(1, 12), start=1)]
    )
    issues = validate_upload(missing_columns=[], parsed_rows=eleven, unit_inference=_info_unit())
    assert IssueCode.SHORT_HISTORY in {issue.code for issue in issues}

    twelve = _parse(
        [_row(index, "F001", f"2023-{month:02d}", "0.01") for index, month in enumerate(range(1, 13), start=1)]
    )
    issues = validate_upload(missing_columns=[], parsed_rows=twelve, unit_inference=_info_unit())
    assert IssueCode.SHORT_HISTORY not in {issue.code for issue in issues}


def test_conflicting_metadata_uses_first_row() -> None:
    parsed = _parse(
        [
            _row(1, "F001", "2023-01", "0.01", strategy="Equity"),
            _row(2, "F001", "2023-02", "0.01", strategy="Credit"),
        ]
    )
    issues = validate_upload(missing_columns=[], parsed_rows=parsed, unit_inference=_info_unit())
    conflict = next(issue for issue in issues if issue.code is IssueCode.CONFLICTING_METADATA)
    assert conflict.details["chosen"]["strategy"] == "Equity"
    assert len(conflict.details["conflicts"]["strategy"]) == 2

    consistent = _parse(
        [
            _row(1, "F001", "2023-01", "0.01", strategy="Equity"),
            _row(2, "F001", "2023-02", "0.01", strategy="Equity"),
        ]
    )
    issues = validate_upload(missing_columns=[], parsed_rows=consistent, unit_inference=_info_unit())
    assert IssueCode.CONFLICTING_METADATA not in {issue.code for issue in issues}


def test_return_unit_mixed_scale_sets_needs_review() -> None:
    inference = ReturnUnitInference(
        unit=ReturnInputUnit.PERCENT,
        median_abs_bare=1.2,
        bare_count=4,
        mixed_scale=True,
        message="mixed",
    )
    parsed = _parse([_row(1, "F001", "2023-01", "1.2")], ReturnInputUnit.PERCENT)
    issues = validate_upload(missing_columns=[], parsed_rows=parsed, unit_inference=inference)
    unit_issues = [issue for issue in issues if issue.code is IssueCode.RETURN_UNIT_INFERRED]
    assert any(issue.severity is IssueSeverity.INFO for issue in unit_issues)
    assert any(issue.severity is IssueSeverity.WARNING for issue in unit_issues)
    assert derive_status(issues, 1) is AnalysisStatus.NEEDS_REVIEW


def test_status_valid_with_warnings() -> None:
    parsed = _parse(
        [_row(index, "F001", f"2023-{month:02d}", "0.01") for index, month in enumerate(range(1, 12), start=1)]
    )
    issues = validate_upload(missing_columns=[], parsed_rows=parsed, unit_inference=_info_unit())
    assert derive_status(issues, 11) is AnalysisStatus.VALID_WITH_WARNINGS
