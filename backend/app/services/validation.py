from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from dataclasses import field as dc_field
from datetime import date

from app.domain.enums import AnalysisStatus, IssueCode, IssueSeverity, ReturnInputUnit
from app.services.ingestion import (
    METADATA_FIELDS,
    ParsedRow,
    ReturnUnitInference,
)


@dataclass
class ValidationIssue:
    code: IssueCode
    severity: IssueSeverity
    message: str
    fund_id: str | None = None
    field: str | None = None
    row_numbers: list[int] = dc_field(default_factory=list)
    details: dict = dc_field(default_factory=dict)


def validate_upload(
    *,
    missing_columns: list[str],
    parsed_rows: list[ParsedRow],
    unit_inference: ReturnUnitInference | None,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if missing_columns:
        issues.append(
            ValidationIssue(
                code=IssueCode.MISSING_COLUMN,
                severity=IssueSeverity.ERROR,
                field=None,
                message="Required columns are missing: " + ", ".join(missing_columns) + ".",
                details={"missing_columns": missing_columns},
            )
        )
        return issues

    if unit_inference is not None:
        issues.extend(_return_unit_issues(unit_inference))

    issues.extend(_parse_issues(parsed_rows))
    issues.extend(_duplicate_period_issues(parsed_rows))
    issues.extend(_conflicting_metadata_issues(parsed_rows))

    duplicate_keys = _duplicate_keys(parsed_rows)
    observations = [
        row
        for row in parsed_rows
        if _is_valid_observation(row) and (row.fund_id, row.period) not in duplicate_keys
    ]
    issues.extend(_missing_month_issues(observations))
    issues.extend(_short_history_issues(observations))
    return issues


def select_observations(parsed_rows: list[ParsedRow]) -> list[ParsedRow]:
    duplicate_keys = _duplicate_keys(parsed_rows)
    return [
        row
        for row in parsed_rows
        if _is_valid_observation(row) and (row.fund_id, row.period) not in duplicate_keys
    ]


def derive_status(issues: list[ValidationIssue], observation_count: int) -> AnalysisStatus:
    if observation_count == 0:
        return AnalysisStatus.INVALID
    codes = {issue.code for issue in issues}
    if IssueCode.MISSING_COLUMN in codes:
        return AnalysisStatus.INVALID
    has_error = any(issue.severity is IssueSeverity.ERROR for issue in issues)
    unit_warning = any(
        issue.code is IssueCode.RETURN_UNIT_INFERRED and issue.severity is IssueSeverity.WARNING
        for issue in issues
    )
    if has_error or unit_warning:
        return AnalysisStatus.NEEDS_REVIEW
    has_warning = any(issue.severity is IssueSeverity.WARNING for issue in issues)
    if has_warning:
        return AnalysisStatus.VALID_WITH_WARNINGS
    return AnalysisStatus.VALID


def is_analysis_blocked(fund_id: str, issues: list[ValidationIssue]) -> bool:
    return any(
        issue.fund_id == fund_id and issue.code is IssueCode.DUPLICATE_PERIOD for issue in issues
    )


def _is_valid_observation(row: ParsedRow) -> bool:
    return (
        row.fund_id is not None
        and row.period is not None
        and row.net_return is not None
        and row.period_error is None
        and row.return_error is None
    )


def _return_unit_issues(inference: ReturnUnitInference) -> list[ValidationIssue]:
    issues = [
        ValidationIssue(
            code=IssueCode.RETURN_UNIT_INFERRED,
            severity=IssueSeverity.INFO,
            message=inference.message,
            details={
                "unit": inference.unit.value,
                "median_abs_bare": inference.median_abs_bare,
                "bare_count": inference.bare_count,
                "mixed_scale": inference.mixed_scale,
            },
        )
    ]
    if inference.mixed_scale:
        issues.append(
            ValidationIssue(
                code=IssueCode.RETURN_UNIT_INFERRED,
                severity=IssueSeverity.WARNING,
                message=(
                    "Bare numeric returns mix values at or below 1.0 with values above 1.0. "
                    f"The file-level rule treats unadorned numbers as "
                    f"{'percentage points' if inference.unit is ReturnInputUnit.PERCENT else 'decimals'}, "
                    "which can make cross-fund comparisons unreliable."
                ),
                details={
                    "unit": inference.unit.value,
                    "median_abs_bare": inference.median_abs_bare,
                    "bare_count": inference.bare_count,
                    "mixed_scale": True,
                },
            )
        )
    return issues


def _parse_issues(rows: list[ParsedRow]) -> list[ValidationIssue]:
    period_rows: dict[str | None, list[int]] = defaultdict(list)
    period_messages: dict[str | None, str] = {}
    return_rows: dict[str | None, list[int]] = defaultdict(list)
    return_messages: dict[str | None, str] = {}

    for row in rows:
        if row.period_error:
            period_rows[row.fund_id].append(row.row_number)
            period_messages[row.fund_id] = row.period_error
        if row.return_error:
            return_rows[row.fund_id].append(row.row_number)
            return_messages[row.fund_id] = row.return_error

    issues: list[ValidationIssue] = []
    for fund_id, row_numbers in period_rows.items():
        label = fund_id or "rows with no fund_id"
        issues.append(
            ValidationIssue(
                code=IssueCode.INVALID_PERIOD,
                severity=IssueSeverity.ERROR,
                fund_id=fund_id,
                field="period",
                row_numbers=row_numbers,
                message=f"{label}: {len(row_numbers)} period value(s) could not be parsed.",
                details={"example": period_messages[fund_id]},
            )
        )
    for fund_id, row_numbers in return_rows.items():
        label = fund_id or "rows with no fund_id"
        issues.append(
            ValidationIssue(
                code=IssueCode.INVALID_RETURN,
                severity=IssueSeverity.ERROR,
                fund_id=fund_id,
                field="net_return",
                row_numbers=row_numbers,
                message=f"{label}: {len(row_numbers)} return value(s) could not be parsed.",
                details={"example": return_messages[fund_id]},
            )
        )
    return issues


def _duplicate_keys(rows: list[ParsedRow]) -> set[tuple[str, date]]:
    counts: dict[tuple[str, date], int] = defaultdict(int)
    for row in rows:
        if row.fund_id and row.period and row.period_error is None:
            counts[(row.fund_id, row.period)] += 1
    return {key for key, count in counts.items() if count > 1}


def _duplicate_period_issues(rows: list[ParsedRow]) -> list[ValidationIssue]:
    grouped: dict[tuple[str, date], list[int]] = defaultdict(list)
    for row in rows:
        if row.fund_id and row.period and row.period_error is None:
            grouped[(row.fund_id, row.period)].append(row.row_number)

    by_fund: dict[str, list[tuple[str, list[int]]]] = defaultdict(list)
    for (fund_id, period), row_numbers in grouped.items():
        if len(row_numbers) > 1:
            by_fund[fund_id].append((period.isoformat(), row_numbers))

    issues: list[ValidationIssue] = []
    for fund_id, duplicates in by_fund.items():
        row_numbers = sorted({row for _, rows_for_period in duplicates for row in rows_for_period})
        issues.append(
            ValidationIssue(
                code=IssueCode.DUPLICATE_PERIOD,
                severity=IssueSeverity.ERROR,
                fund_id=fund_id,
                field="period",
                row_numbers=row_numbers,
                message=(
                    f"{fund_id}: duplicate fund_id+period rows were found. "
                    "The fund is blocked from analysis because a value cannot be chosen."
                ),
                details={"duplicates": [{"period": period, "rows": rows} for period, rows in duplicates]},
            )
        )
    return issues


def _conflicting_metadata_issues(rows: list[ParsedRow]) -> list[ValidationIssue]:
    by_fund: dict[str, list[ParsedRow]] = defaultdict(list)
    for row in rows:
        if row.fund_id:
            by_fund[row.fund_id].append(row)

    issues: list[ValidationIssue] = []
    for fund_id, fund_rows in by_fund.items():
        conflicts: dict[str, list[dict[str, object]]] = {}
        for field_name in METADATA_FIELDS:
            seen: dict[str, list[int]] = defaultdict(list)
            for row in fund_rows:
                seen[row.values.get(field_name, "")].append(row.row_number)
            if len(seen) > 1:
                conflicts[field_name] = [
                    {"value": value, "row_numbers": numbers} for value, numbers in seen.items()
                ]
        if not conflicts:
            continue
        first_row = min(fund_rows, key=lambda item: item.row_number)
        chosen = {field_name: first_row.values.get(field_name, "") for field_name in conflicts}
        issues.append(
            ValidationIssue(
                code=IssueCode.CONFLICTING_METADATA,
                severity=IssueSeverity.WARNING,
                fund_id=fund_id,
                row_numbers=sorted(row.row_number for row in fund_rows),
                message=(
                    f"{fund_id}: metadata fields disagree across rows "
                    f"({', '.join(conflicts)}). The first row's values are shown."
                ),
                details={"conflicts": conflicts, "chosen": chosen},
            )
        )
    return issues


def _missing_month_issues(observations: list[ParsedRow]) -> list[ValidationIssue]:
    by_fund: dict[str, list[date]] = defaultdict(list)
    by_fund_rows: dict[str, list[int]] = defaultdict(list)
    for row in observations:
        assert row.fund_id is not None and row.period is not None
        by_fund[row.fund_id].append(row.period)
        by_fund_rows[row.fund_id].append(row.row_number)

    issues: list[ValidationIssue] = []
    for fund_id, periods in by_fund.items():
        missing = _missing_months(periods)
        if not missing:
            continue
        issues.append(
            ValidationIssue(
                code=IssueCode.MISSING_MONTHS,
                severity=IssueSeverity.WARNING,
                fund_id=fund_id,
                field="period",
                row_numbers=sorted(by_fund_rows[fund_id]),
                message=(
                    f"{fund_id}: {len(missing)} month(s) are missing between "
                    f"{min(periods).isoformat()} and {max(periods).isoformat()}."
                ),
                details={"missing_months": [month.isoformat() for month in missing]},
            )
        )
    return issues


def _short_history_issues(observations: list[ParsedRow]) -> list[ValidationIssue]:
    by_fund: dict[str, list[ParsedRow]] = defaultdict(list)
    for row in observations:
        assert row.fund_id is not None
        by_fund[row.fund_id].append(row)

    issues: list[ValidationIssue] = []
    for fund_id, fund_rows in by_fund.items():
        if len(fund_rows) >= 12:
            continue
        issues.append(
            ValidationIssue(
                code=IssueCode.SHORT_HISTORY,
                severity=IssueSeverity.WARNING,
                fund_id=fund_id,
                field="period",
                row_numbers=sorted(row.row_number for row in fund_rows),
                message=(
                    f"{fund_id}: {len(fund_rows)} monthly observation(s) found; "
                    "fewer than 12 months is a short track record."
                ),
                details={"observations": len(fund_rows)},
            )
        )
    return issues


def _missing_months(periods: list[date]) -> list[date]:
    unique = sorted(set(periods))
    if len(unique) < 2:
        return []
    missing: list[date] = []
    year, month = unique[0].year, unique[0].month
    end = unique[-1]
    present = set(unique)
    while (year, month) <= (end.year, end.month):
        current = date(year, month, 1)
        if current not in present:
            missing.append(current)
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1
    return missing
