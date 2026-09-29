from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field as dc_field
from datetime import date
from decimal import Decimal
from statistics import stdev

from app.domain.enums import AnalysisStatus, IssueCode, IssueSeverity, LiquidityFrequency
from app.services.ingestion import (
    AMBIGUOUS_MEDIAN_FLOOR,
    MAX_ABS_MONTHLY_RETURN,
    PERCENT_MEDIAN_THRESHOLD,
    METADATA_FIELDS,
    METADATA_INT_LIMITS,
    ParsedRow,
    ParseError,
    ReturnUnitInference,
    parse_bounded_int,
    parse_liquidity_frequency,
)


# Issues whose fund cannot be analyzed at all: no single trustworthy series exists.
BLOCKING_CODES: frozenset[IssueCode] = frozenset(
    {IssueCode.DUPLICATE_PERIOD, IssueCode.RETURN_OUT_OF_RANGE}
)

# SMOOTH_RETURNS: no negative month across at least this many observations ...
SMOOTH_MIN_OBSERVATIONS_NO_LOSS = 24
# ... or annualized volatility below this, evaluated once a fund has a year of data.
SMOOTH_MAX_ANNUALIZED_VOL = Decimal("0.01")
SMOOTH_MIN_OBSERVATIONS_VOL = 12


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
    unit_inferences: Mapping[str | None, ReturnUnitInference],
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

    for fund_id, inference in unit_inferences.items():
        issues.extend(_return_unit_issues(fund_id, inference))

    issues.extend(_parse_issues(parsed_rows))
    issues.extend(_out_of_range_issues(parsed_rows))
    issues.extend(_metadata_issues(parsed_rows))
    issues.extend(_duplicate_period_issues(parsed_rows))
    issues.extend(_conflicting_metadata_issues(parsed_rows))

    observations = select_observations(parsed_rows)
    issues.extend(_missing_month_issues(observations))
    issues.extend(_smooth_return_issues(observations))
    issues.extend(_fund_id_mismatch_issues(parsed_rows))
    issues.extend(_date_range_issues(observations))
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
    return any(issue.fund_id == fund_id and issue.code in BLOCKING_CODES for issue in issues)


def _is_valid_observation(row: ParsedRow) -> bool:
    return (
        row.fund_id is not None
        and row.period is not None
        and row.net_return is not None
        and row.period_error is None
        and row.return_error is None
    )


def _return_unit_issues(
    fund_id: str | None, inference: ReturnUnitInference
) -> list[ValidationIssue]:
    label = fund_id or "rows with no fund_id"
    details = {
        "unit": inference.unit.value,
        "median_abs_bare": inference.median_abs_bare,
        "bare_count": inference.bare_count,
        "ambiguous": inference.ambiguous,
        "percent_above_median": str(PERCENT_MEDIAN_THRESHOLD),
        "ambiguous_from_median": str(AMBIGUOUS_MEDIAN_FLOOR),
    }
    issues = [
        ValidationIssue(
            code=IssueCode.RETURN_UNIT_INFERRED,
            severity=IssueSeverity.INFO,
            fund_id=fund_id,
            field="net_return",
            message=f"{label}: {inference.message}",
            details=details,
        )
    ]
    if inference.ambiguous:
        issues.append(
            ValidationIssue(
                code=IssueCode.RETURN_UNIT_INFERRED,
                severity=IssueSeverity.WARNING,
                fund_id=fund_id,
                field="net_return",
                message=(
                    f"{label}: the median absolute bare return ({inference.median_abs_bare:.4g}) "
                    f"is between {AMBIGUOUS_MEDIAN_FLOOR} and {PERCENT_MEDIAN_THRESHOLD}, so "
                    "the unit is ambiguous. Values are read as decimals; confirm the fund's "
                    "reporting unit."
                ),
                details=details,
            )
        )
    return issues


def _out_of_range_issues(rows: list[ParsedRow]) -> list[ValidationIssue]:
    by_fund: dict[str | None, list[ParsedRow]] = defaultdict(list)
    for row in rows:
        if (
            row.net_return is not None
            and row.return_error is None
            and abs(row.net_return) > MAX_ABS_MONTHLY_RETURN
        ):
            by_fund[row.fund_id].append(row)

    issues: list[ValidationIssue] = []
    for fund_id, fund_rows in by_fund.items():
        label = fund_id or "rows with no fund_id"
        issues.append(
            ValidationIssue(
                code=IssueCode.RETURN_OUT_OF_RANGE,
                severity=IssueSeverity.ERROR,
                fund_id=fund_id,
                field="net_return",
                row_numbers=[row.row_number for row in fund_rows],
                message=(
                    f"{label}: {len(fund_rows)} monthly return(s) exceed "
                    f"±{MAX_ABS_MONTHLY_RETURN:.0%} after unit conversion. The fund is blocked "
                    "from analysis until the source data is corrected."
                ),
                details={
                    "limit": str(MAX_ABS_MONTHLY_RETURN),
                    "values": [
                        {"row_number": row.row_number, "net_return": str(row.net_return)}
                        for row in fund_rows
                    ],
                },
            )
        )
    return issues


def _metadata_issues(rows: list[ParsedRow]) -> list[ValidationIssue]:
    """Flag screen-critical metadata that is not a bounded integer or an allowed liquidity value."""
    invalid: dict[tuple[str, str], list[tuple[int, str, str]]] = defaultdict(list)
    for row in rows:
        if row.fund_id is None:
            continue
        value = row.values.get("liquidity_frequency", "")
        try:
            parse_liquidity_frequency(value)
        except ParseError as exc:
            invalid[(row.fund_id, "liquidity_frequency")].append((row.row_number, value, str(exc)))
        for field_name, maximum in METADATA_INT_LIMITS.items():
            value = row.values.get(field_name, "")
            try:
                parse_bounded_int(value, maximum)
            except ParseError as exc:
                invalid[(row.fund_id, field_name)].append((row.row_number, value, str(exc)))

    issues: list[ValidationIssue] = []
    for (fund_id, field_name), failures in invalid.items():
        if field_name == "liquidity_frequency":
            expected: object = [item.value for item in LiquidityFrequency]
        else:
            expected = {"min": 0, "max": METADATA_INT_LIMITS[field_name]}
        issues.append(
            ValidationIssue(
                code=IssueCode.INVALID_METADATA,
                severity=IssueSeverity.ERROR,
                fund_id=fund_id,
                field=field_name,
                row_numbers=[row_number for row_number, _, _ in failures],
                message=(
                    f"{fund_id}: {len(failures)} row(s) have an invalid {field_name} "
                    f"({failures[0][2]}). Hard screens that read {field_name} cannot verify "
                    "this fund."
                ),
                details={
                    "expected": expected,
                    "values": sorted({value for _, value, _ in failures}),
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


@dataclass(frozen=True)
class CommonWindow:
    """The universe's reference window: from the median fund start to the latest period."""

    start: date
    end: date
    fund_count: int
    funds_covering: int


def common_window(periods_by_fund: Mapping[str, list[date]]) -> CommonWindow | None:
    spans = [(min(periods), max(periods)) for periods in periods_by_fund.values() if periods]
    if not spans:
        return None
    starts = sorted(start for start, _ in spans)
    start = starts[(len(starts) - 1) // 2]
    end = max(end for _, end in spans)
    covering = sum(1 for first, last in spans if first <= start and last >= end)
    return CommonWindow(start=start, end=end, fund_count=len(spans), funds_covering=covering)


def _normalize_identifier(value: str) -> str:
    return re.sub(r"[^0-9a-z]", "", value.casefold())


def _fund_id_mismatch_issues(rows: list[ParsedRow]) -> list[ValidationIssue]:
    """Warn when distinct fund_ids look like one fund: same normalized name, or ids that differ
    only by case, whitespace, or punctuation."""
    first_rows: dict[str, ParsedRow] = {}
    for row in sorted(rows, key=lambda item: item.row_number):
        if row.fund_id and row.fund_id not in first_rows:
            first_rows[row.fund_id] = row

    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for fund_id, row in first_rows.items():
        name_key = _normalize_identifier(row.values.get("fund_name", ""))
        if name_key:
            groups[("same_fund_name", name_key)].append(fund_id)
        id_key = _normalize_identifier(fund_id)
        if id_key:
            groups[("similar_fund_id", id_key)].append(fund_id)

    matches: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for (reason, _), fund_ids in groups.items():
        if len(fund_ids) < 2:
            continue
        for fund_id in fund_ids:
            matches[fund_id][reason].update(other for other in fund_ids if other != fund_id)

    issues: list[ValidationIssue] = []
    for fund_id in sorted(matches):
        reasons = matches[fund_id]
        related = sorted(set().union(*reasons.values()))
        described = {
            "same_fund_name": "the same fund name",
            "similar_fund_id": "a fund_id that differs only by case, spacing, or punctuation",
        }
        issues.append(
            ValidationIssue(
                code=IssueCode.FUND_ID_MISMATCH,
                severity=IssueSeverity.WARNING,
                fund_id=fund_id,
                field="fund_id",
                row_numbers=[first_rows[fund_id].row_number],
                message=(
                    f"{fund_id}: shares {' and '.join(described[r] for r in sorted(reasons))} "
                    f"with {', '.join(related)}. Confirm these are different funds before "
                    "comparing them."
                ),
                details={
                    "related_fund_ids": related,
                    "reasons": sorted(reasons),
                    "fund_name": first_rows[fund_id].values.get("fund_name", ""),
                },
            )
        )
    return issues


def _date_range_issues(observations: list[ParsedRow]) -> list[ValidationIssue]:
    periods: dict[str, list[date]] = defaultdict(list)
    rows: dict[str, list[int]] = defaultdict(list)
    for row in observations:
        assert row.fund_id is not None and row.period is not None
        periods[row.fund_id].append(row.period)
        rows[row.fund_id].append(row.row_number)
    window = common_window(periods)
    if window is None:
        return []

    issues: list[ValidationIssue] = []
    for fund_id in sorted(periods):
        first, last = min(periods[fund_id]), max(periods[fund_id])
        reasons = []
        if last < window.end:
            reasons.append(f"ends {last.isoformat()}, before the universe's latest period")
        if first > window.start:
            reasons.append(f"starts {first.isoformat()}, after the common window start")
        if not reasons:
            continue
        issues.append(
            ValidationIssue(
                code=IssueCode.INCONSISTENT_DATE_RANGE,
                severity=IssueSeverity.WARNING,
                fund_id=fund_id,
                field="period",
                row_numbers=sorted(rows[fund_id]),
                message=(
                    f"{fund_id}: {'; '.join(reasons)} ({window.start.isoformat()} to "
                    f"{window.end.isoformat()}). Its metrics cover a different period than "
                    "most of the universe."
                ),
                details={
                    "first_period": first.isoformat(),
                    "last_period": last.isoformat(),
                    "common_window_start": window.start.isoformat(),
                    "common_window_end": window.end.isoformat(),
                    "ends_early": last < window.end,
                    "starts_late": first > window.start,
                },
            )
        )
    return issues


def _smooth_return_issues(observations: list[ParsedRow]) -> list[ValidationIssue]:
    """Warn on return streams too smooth to be plausible for a hedge fund."""
    by_fund: dict[str, list[ParsedRow]] = defaultdict(list)
    for row in observations:
        assert row.fund_id is not None and row.net_return is not None
        by_fund[row.fund_id].append(row)

    issues: list[ValidationIssue] = []
    for fund_id, fund_rows in by_fund.items():
        returns = [row.net_return for row in fund_rows if row.net_return is not None]
        count = len(returns)
        no_losses = count >= SMOOTH_MIN_OBSERVATIONS_NO_LOSS and min(returns) >= 0
        volatility = (
            stdev(returns) * Decimal(12).sqrt() if count >= SMOOTH_MIN_OBSERVATIONS_VOL else None
        )
        low_volatility = volatility is not None and volatility < SMOOTH_MAX_ANNUALIZED_VOL
        if not (no_losses or low_volatility):
            continue
        reasons = []
        if no_losses:
            reasons.append(f"no negative month across {count} observations")
        if low_volatility:
            reasons.append(f"annualized volatility {volatility:.2%}")
        issues.append(
            ValidationIssue(
                code=IssueCode.SMOOTH_RETURNS,
                severity=IssueSeverity.WARNING,
                fund_id=fund_id,
                field="net_return",
                row_numbers=sorted(row.row_number for row in fund_rows),
                message=(
                    f"{fund_id}: returns are unusually smooth ({'; '.join(reasons)}). "
                    "Verify pricing, administration, and audit before relying on its "
                    "risk-adjusted metrics."
                ),
                details={
                    "observations": count,
                    "negative_months": sum(1 for value in returns if value < 0),
                    "annualized_volatility": None if volatility is None else str(volatility),
                    "no_loss_min_observations": SMOOTH_MIN_OBSERVATIONS_NO_LOSS,
                    "volatility_threshold": str(SMOOTH_MAX_ANNUALIZED_VOL),
                },
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
