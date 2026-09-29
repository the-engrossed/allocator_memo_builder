from __future__ import annotations

import csv
import hashlib
import io
import re
import uuid
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from statistics import median

from sqlalchemy.orm import Session

from app.domain.enums import LiquidityFrequency, ReturnInputUnit
from app.domain.models import Analysis, ReturnObservation, SourceRow, ValidationIssue as IssueRow
from app.domain.schemas import AnalysisResponse, FundSummaryOut, ValidationIssueOut

CANONICAL_COLUMNS: tuple[str, ...] = (
    "fund_id",
    "fund_name",
    "strategy",
    "period",
    "net_return",
    "liquidity_frequency",
    "notice_days",
    "lockup_months",
    "mgmt_fee_bps",
    "perf_fee_bps",
    "notes",
)

_ALIASES: dict[str, tuple[str, ...]] = {
    "fund_id": ("fund_id", "id"),
    "fund_name": ("fund_name", "fund", "manager"),
    "period": ("period", "date", "month"),
    "net_return": ("net_return", "return", "monthly_return"),
}

_MONTH_NAMES: dict[str, int] = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

METADATA_FIELDS: tuple[str, ...] = (
    "fund_name",
    "strategy",
    "liquidity_frequency",
    "notice_days",
    "lockup_months",
    "mgmt_fee_bps",
    "perf_fee_bps",
    "notes",
)

# Inclusive upper bounds for integer metadata read by the hard screens; they mirror the mandate.
METADATA_INT_LIMITS: dict[str, int] = {
    "notice_days": 3650,
    "lockup_months": 120,
    "mgmt_fee_bps": 10_000,
    "perf_fee_bps": 10_000,
}

_LIQUIDITY_VALUES: dict[str, LiquidityFrequency] = {
    **{frequency.value: frequency for frequency in LiquidityFrequency},
    "semi-annual": LiquidityFrequency.SEMIANNUAL,
}

# A monthly net return beyond +/-50% is a data error that blocks the fund from analysis.
MAX_ABS_MONTHLY_RETURN = Decimal("0.5")

# Per-fund unit inference on the median absolute bare return (see infer_return_unit).
PERCENT_MEDIAN_THRESHOLD = Decimal("0.25")
AMBIGUOUS_MEDIAN_FLOOR = Decimal("0.10")


class ParseError(ValueError):
    pass


@dataclass(frozen=True)
class SourceRecord:
    row_number: int
    raw: dict[str, str]


@dataclass
class MappedRow:
    row_number: int
    raw: dict[str, str]
    values: dict[str, str]


@dataclass
class ParsedRow:
    row_number: int
    raw: dict[str, str]
    values: dict[str, str]
    fund_id: str | None
    period: date | None
    net_return: Decimal | None
    return_input_unit: ReturnInputUnit | None
    period_error: str | None
    return_error: str | None


@dataclass
class ReturnUnitInference:
    unit: ReturnInputUnit
    median_abs_bare: float | None
    bare_count: int
    ambiguous: bool
    message: str


def _normalize_header(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lstrip("\ufeff")).lower()


def map_columns(headers: list[str]) -> tuple[dict[str, str], list[str]]:
    """Return (canonical -> original header, missing canonical names)."""
    normalized: dict[str, str] = {}
    for original in headers:
        key = _normalize_header(original)
        if key and key not in normalized:
            normalized[key] = original.strip().lstrip("\ufeff")

    mapping: dict[str, str] = {}
    for canonical in CANONICAL_COLUMNS:
        aliases = _ALIASES.get(canonical, (canonical,))
        chosen: str | None = None
        if canonical in normalized:
            chosen = normalized[canonical]
        else:
            for alias in aliases:
                if alias != canonical and alias in normalized:
                    chosen = normalized[alias]
                    break
        if chosen is not None:
            mapping[canonical] = chosen

    missing = [name for name in CANONICAL_COLUMNS if name not in mapping]
    return mapping, missing


def parse_period(value: str) -> date:
    raw = value.strip()
    if not raw:
        raise ParseError("Period is empty")

    match = re.fullmatch(r"(\d{4})-(\d{1,2})", raw)
    if match:
        return _month_start(int(match.group(1)), int(match.group(2)))

    match = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", raw)
    if match:
        return _month_start(int(match.group(1)), int(match.group(2)))

    match = re.fullmatch(r"(\d{1,2})/(\d{4})", raw)
    if match:
        return _month_start(int(match.group(2)), int(match.group(1)))

    match = re.fullmatch(r"([A-Za-z]{3,9})[- ](\d{4})", raw)
    if match:
        month = _MONTH_NAMES.get(match.group(1).lower())
        if month is None:
            raise ParseError(f"Unrecognized month name: {raw}")
        return _month_start(int(match.group(2)), month)

    match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", raw)
    if match:
        first = int(match.group(1))
        second = int(match.group(2))
        year = int(match.group(3))
        if first > 12:
            raise ParseError(f"Day-first dates are not accepted: {raw}")
        if second > 31:
            raise ParseError(f"Invalid day in period: {raw}")
        return _month_start(year, first)

    raise ParseError(f"Unrecognized period format: {raw}")


def parse_return(value: str, bare_unit: ReturnInputUnit) -> tuple[Decimal, ReturnInputUnit]:
    raw = value.strip()
    if not raw:
        raise ParseError("Return is empty")

    if raw.lower() in {"n/a", "na", "null", "none", "-"}:
        raise ParseError(f"Return is not numeric: {raw}")

    percent_suffix = raw.endswith("%")
    numeric_text = raw[:-1].strip() if percent_suffix else raw
    numeric_text = numeric_text.replace(",", "")
    try:
        magnitude = Decimal(numeric_text)
    except InvalidOperation as exc:
        raise ParseError(f"Return is not numeric: {raw}") from exc

    if percent_suffix:
        return magnitude / Decimal("100"), ReturnInputUnit.PERCENT
    if bare_unit is ReturnInputUnit.PERCENT:
        return magnitude / Decimal("100"), ReturnInputUnit.PERCENT
    return magnitude, ReturnInputUnit.DECIMAL


def parse_liquidity_frequency(value: str) -> LiquidityFrequency:
    raw = value.strip()
    frequency = _LIQUIDITY_VALUES.get(raw.lower())
    if frequency is None:
        allowed = ", ".join(item.value for item in LiquidityFrequency)
        raise ParseError(f"Liquidity frequency {raw!r} is not one of: {allowed}")
    return frequency


def parse_bounded_int(value: str, maximum: int) -> int:
    raw = value.strip()
    if not raw:
        raise ParseError("Value is empty")
    if not re.fullmatch(r"\d+", raw):
        raise ParseError(f"{raw!r} is not a non-negative whole number")
    number = int(raw)
    if number > maximum:
        raise ParseError(f"{number} exceeds the maximum of {maximum}")
    return number


def infer_return_unit(bare_values: list[Decimal]) -> ReturnUnitInference:
    """Classify one fund's bare returns by the median of their absolute values.

    median > 0.25        -> percentage points (a 25% median monthly decimal return is implausible)
    0.10 <= median <= 0.25 -> decimals, flagged ambiguous
    median < 0.10        -> decimals
    """
    if not bare_values:
        return ReturnUnitInference(
            unit=ReturnInputUnit.DECIMAL,
            median_abs_bare=None,
            bare_count=0,
            ambiguous=False,
            message="No bare numeric returns were found; unadorned values would read as decimals.",
        )

    abs_values = [abs(value) for value in bare_values]
    median_abs = median(abs_values)
    if median_abs > PERCENT_MEDIAN_THRESHOLD:
        unit = ReturnInputUnit.PERCENT
    else:
        unit = ReturnInputUnit.DECIMAL
    ambiguous = AMBIGUOUS_MEDIAN_FLOOR <= median_abs <= PERCENT_MEDIAN_THRESHOLD
    unit_label = "percentage points" if unit is ReturnInputUnit.PERCENT else "decimals"
    message = (
        f"Bare numeric returns read as {unit_label} "
        f"(median absolute value {median_abs:.4g} across {len(abs_values)} values)."
    )
    return ReturnUnitInference(
        unit=unit,
        median_abs_bare=float(median_abs),
        bare_count=len(abs_values),
        ambiguous=ambiguous,
        message=message,
    )


def read_csv_records(content: bytes) -> tuple[list[str], list[SourceRecord]]:
    text = _decode_csv(content)
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ValueError("CSV has no header row")
    headers = [name if name is not None else "" for name in reader.fieldnames]
    if not any(header.strip() for header in headers):
        raise ValueError("CSV has no header row")

    records: list[SourceRecord] = []
    for index, row in enumerate(reader, start=1):
        raw = {
            (key or "").lstrip("\ufeff"): "" if value is None else str(value)
            for key, value in row.items()
            if key is not None
        }
        records.append(SourceRecord(row_number=index, raw=raw))
    return headers, records


def apply_mapping(records: list[SourceRecord], mapping: dict[str, str]) -> list[MappedRow]:
    mapped: list[MappedRow] = []
    for record in records:
        values = {
            canonical: record.raw.get(original, "").strip()
            for canonical, original in mapping.items()
        }
        mapped.append(MappedRow(row_number=record.row_number, raw=record.raw, values=values))
    return mapped


def collect_bare_returns_by_fund(rows: list[MappedRow]) -> dict[str | None, list[Decimal]]:
    """Bare numeric returns (no % suffix) grouped by fund_id; None collects unassigned rows."""
    collected: dict[str | None, list[Decimal]] = defaultdict(list)
    for row in rows:
        raw = row.values.get("net_return", "").strip()
        if not raw or raw.endswith("%"):
            continue
        try:
            value = Decimal(raw.replace(",", ""))
        except InvalidOperation:
            continue
        collected[_fund_key(row)].append(value)
    return dict(collected)


def infer_return_units(rows: list[MappedRow]) -> dict[str | None, ReturnUnitInference]:
    """Infer decimal vs percentage-point units separately for each fund's bare returns."""
    return {
        fund_id: infer_return_unit(values)
        for fund_id, values in collect_bare_returns_by_fund(rows).items()
    }


def parse_mapped_rows(
    rows: list[MappedRow], unit_by_fund: Mapping[str | None, ReturnInputUnit]
) -> list[ParsedRow]:
    """Parse rows, reading each bare return with its own fund's unit (decimal if unknown)."""
    parsed: list[ParsedRow] = []
    for row in rows:
        fund_id = _fund_key(row)
        bare_unit = unit_by_fund.get(fund_id, ReturnInputUnit.DECIMAL)
        period: date | None = None
        period_error: str | None = None
        net_return: Decimal | None = None
        unit: ReturnInputUnit | None = None
        return_error: str | None = None

        period_raw = row.values.get("period", "")
        try:
            period = parse_period(period_raw)
        except ParseError as exc:
            period_error = str(exc)

        return_raw = row.values.get("net_return", "")
        try:
            net_return, unit = parse_return(return_raw, bare_unit)
        except ParseError as exc:
            return_error = str(exc)

        parsed.append(
            ParsedRow(
                row_number=row.row_number,
                raw=row.raw,
                values=row.values,
                fund_id=fund_id,
                period=period,
                net_return=net_return,
                return_input_unit=unit,
                period_error=period_error,
                return_error=return_error,
            )
        )
    return parsed


def _fund_key(row: MappedRow) -> str | None:
    return row.values.get("fund_id", "").strip() or None


def _month_start(year: int, month: int) -> date:
    if month < 1 or month > 12:
        raise ParseError(f"Invalid month: {month}")
    return date(year, month, 1)


def _decode_csv(content: bytes) -> str:
    if not content:
        raise ValueError("CSV file is empty")
    if content.startswith(b"\xef\xbb\xbf"):
        content = content[3:]
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("CSV must be UTF-8 encoded") from exc


def create_analysis(db: Session, *, filename: str, content: bytes) -> Analysis:
    from app.services.validation import derive_status, select_observations, validate_upload

    headers, records = read_csv_records(content)
    mapping, missing = map_columns(headers)
    mapped_rows = apply_mapping(records, mapping) if not missing else []
    unit_inferences: dict[str | None, ReturnUnitInference] = {}
    parsed_rows: list[ParsedRow] = []
    if not missing:
        unit_inferences = infer_return_units(mapped_rows)
        parsed_rows = parse_mapped_rows(
            mapped_rows, {fund_id: item.unit for fund_id, item in unit_inferences.items()}
        )

    issues = validate_upload(
        missing_columns=missing,
        parsed_rows=parsed_rows,
        unit_inferences=unit_inferences,
    )
    observations = [] if missing else select_observations(parsed_rows)
    status = derive_status(issues, len(observations))

    fund_ids = _collect_fund_ids(parsed_rows, records, mapping)
    analysis = Analysis(
        id=uuid.uuid4(),
        filename=filename,
        sha256=hashlib.sha256(content).hexdigest(),
        uploaded_at=datetime.now(timezone.utc),
        row_count=len(records),
        fund_count=len(fund_ids),
        status=status.value,
        column_mapping=mapping,
        source_rows=[
            SourceRow(row_number=record.row_number, raw=record.raw) for record in records
        ],
        return_observations=[
            ReturnObservation(
                source_row_number=row.row_number,
                fund_id=row.fund_id or "",
                period=row.period,
                net_return=row.net_return,
                return_input_unit=(row.return_input_unit or ReturnInputUnit.DECIMAL).value,
            )
            for row in observations
        ],
        validation_issues=[
            IssueRow(
                code=issue.code.value,
                severity=issue.severity.value,
                fund_id=issue.fund_id,
                field=issue.field,
                row_numbers=issue.row_numbers,
                message=issue.message,
                details=issue.details,
            )
            for issue in issues
        ],
    )
    db.add(analysis)
    db.flush()
    return analysis


def analysis_to_response(analysis: Analysis) -> AnalysisResponse:
    from app.domain.enums import IssueCode, IssueSeverity
    from app.services.validation import ValidationIssue, is_analysis_blocked

    typed_issues = [
        ValidationIssue(
            code=IssueCode(issue.code),
            severity=IssueSeverity(issue.severity),
            message=issue.message,
            fund_id=issue.fund_id,
            field=issue.field,
            row_numbers=list(issue.row_numbers or []),
            details=issue.details or {},
        )
        for issue in analysis.validation_issues
    ]
    funds = _build_fund_summaries(analysis, typed_issues, is_analysis_blocked)
    strategies = sorted({fund.strategy for fund in funds if fund.strategy})
    return AnalysisResponse(
        analysis_id=analysis.id,
        filename=analysis.filename,
        status=analysis.status,  # type: ignore[arg-type]
        uploaded_at=analysis.uploaded_at,
        row_count=analysis.row_count,
        fund_count=analysis.fund_count,
        column_mapping=analysis.column_mapping,
        strategies=strategies,
        issues=[
            ValidationIssueOut(
                code=issue.code,
                severity=issue.severity,
                fund_id=issue.fund_id,
                field=issue.field,
                row_numbers=list(issue.row_numbers or []),
                message=issue.message,
                details=issue.details or {},
            )
            for issue in analysis.validation_issues
        ],
        funds=funds,
    )


def _collect_fund_ids(
    parsed_rows: list[ParsedRow],
    records: list[SourceRecord],
    mapping: dict[str, str],
) -> set[str]:
    fund_ids = {row.fund_id for row in parsed_rows if row.fund_id}
    fund_header = mapping.get("fund_id")
    if fund_header:
        for record in records:
            value = record.raw.get(fund_header, "").strip()
            if value:
                fund_ids.add(value)
    return fund_ids


def _build_fund_summaries(analysis: Analysis, issues, is_blocked) -> list[FundSummaryOut]:
    observations_by_fund: dict[str, list[ReturnObservation]] = defaultdict(list)
    for observation in analysis.return_observations:
        observations_by_fund[observation.fund_id].append(observation)

    metadata_by_fund: dict[str, dict[str, str]] = {}
    fund_header = analysis.column_mapping.get("fund_id")
    if fund_header:
        ordered_rows = sorted(analysis.source_rows, key=lambda item: item.row_number)
        for source in ordered_rows:
            fund_id = str(source.raw.get(fund_header, "")).strip()
            if fund_id and fund_id not in metadata_by_fund:
                metadata_by_fund[fund_id] = {
                    canonical: str(source.raw.get(original, "")).strip()
                    for canonical, original in analysis.column_mapping.items()
                }

    fund_ids = sorted(
        set(observations_by_fund)
        | set(metadata_by_fund)
        | {issue.fund_id for issue in issues if issue.fund_id}
    )
    summaries: list[FundSummaryOut] = []
    for fund_id in fund_ids:
        fund_obs = sorted(observations_by_fund.get(fund_id, []), key=lambda item: item.period)
        meta = metadata_by_fund.get(fund_id, {})
        fund_issues = [issue for issue in issues if issue.fund_id == fund_id]
        counts = {"error": 0, "warning": 0, "info": 0}
        for issue in fund_issues:
            counts[issue.severity.value] = counts.get(issue.severity.value, 0) + 1
        summaries.append(
            FundSummaryOut(
                fund_id=fund_id,
                fund_name=meta.get("fund_name", ""),
                strategy=meta.get("strategy", ""),
                liquidity_frequency=meta.get("liquidity_frequency", ""),
                first_period=fund_obs[0].period if fund_obs else None,
                last_period=fund_obs[-1].period if fund_obs else None,
                observations=len(fund_obs),
                analysis_blocked=is_blocked(fund_id, issues),
                issue_counts=counts,
            )
        )
    return summaries
