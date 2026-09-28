"""Analysis lifecycle: persist an upload and read it back as a validation summary.

Each upload creates a new, append-only analysis. The fund summary is derived from source
rows, valid observations, and issues; there is no canonical fund table in this slice.
"""

import hashlib
import uuid
from collections import defaultdict
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.domain.enums import IssueCode, IssueSeverity
from app.domain.models import Analysis, ReturnObservation, SourceRow, ValidationIssue
from app.domain.schemas import (
    AnalysisResponse,
    FundSummaryOut,
    IssueCounts,
    ValidationIssueOut,
)
from app.services.ingestion import parse_upload
from app.services.validation import validate_upload


class AnalysisNotFoundError(LookupError):
    pass


def create_analysis(session: Session, filename: str, content: bytes) -> AnalysisResponse:
    """Parse, validate, and persist an upload. Raises UploadRejectedError for unreadable files."""
    parsed = parse_upload(content)
    result = validate_upload(parsed)

    analysis = Analysis(
        filename=filename,
        file_sha256=hashlib.sha256(content).hexdigest(),
        status=result.status,
        row_count=len(parsed.source_records),
        column_mapping=parsed.column_mapping,
        bare_return_unit=parsed.unit_inference.unit,
    )
    session.add(analysis)
    session.flush()

    source_rows = {
        record.row_number: SourceRow(
            analysis_id=analysis.id, row_number=record.row_number, raw=record.raw
        )
        for record in parsed.source_records
    }
    session.add_all(source_rows.values())
    session.flush()

    session.add_all(
        ReturnObservation(
            analysis_id=analysis.id,
            source_row_id=source_rows[row.row_number].id,
            fund_id=row.fund_id,
            period=row.period,
            net_return=row.net_return,
            input_format=row.return_format,
        )
        for row in result.accepted_rows
    )
    session.add_all(
        ValidationIssue(
            analysis_id=analysis.id,
            code=issue.code,
            severity=issue.severity,
            fund_id=issue.fund_id,
            field=issue.field,
            row_numbers=list(issue.row_numbers),
            message=issue.message,
            details=issue.details,
        )
        for issue in result.issues
    )
    session.commit()
    return get_analysis(session, analysis.id)


def get_analysis(session: Session, analysis_id: uuid.UUID) -> AnalysisResponse:
    analysis = session.scalar(
        select(Analysis)
        .where(Analysis.id == analysis_id)
        .options(
            selectinload(Analysis.source_rows),
            selectinload(Analysis.observations),
            selectinload(Analysis.issues),
        )
    )
    if analysis is None:
        raise AnalysisNotFoundError(f"Analysis {analysis_id} not found.")

    fund_id_column = analysis.column_mapping.get("fund_id")
    unassigned = (
        [r.row_number for r in analysis.source_rows if not r.raw[fund_id_column].strip()]
        if fund_id_column
        else []
    )

    return AnalysisResponse(
        analysis_id=analysis.id,
        filename=analysis.filename,
        file_sha256=analysis.file_sha256,
        uploaded_at=analysis.uploaded_at,
        status=analysis.status,
        row_count=analysis.row_count,
        observation_count=len(analysis.observations),
        column_mapping=analysis.column_mapping,
        bare_return_unit=analysis.bare_return_unit,
        unassigned_row_numbers=unassigned,
        issue_counts=_count_issues(analysis.issues),
        issues=[_issue_out(issue) for issue in analysis.issues],
        funds=_fund_summaries(analysis),
    )


def _issue_out(issue: ValidationIssue) -> ValidationIssueOut:
    return ValidationIssueOut(
        code=issue.code,
        severity=issue.severity,
        fund_id=issue.fund_id,
        field=issue.field,
        row_numbers=issue.row_numbers,
        message=issue.message,
        details=issue.details,
    )


def _count_issues(issues: Sequence[ValidationIssue]) -> IssueCounts:
    counts = IssueCounts()
    for issue in issues:
        match issue.severity:
            case IssueSeverity.ERROR:
                counts.error += 1
            case IssueSeverity.WARNING:
                counts.warning += 1
            case IssueSeverity.INFO:
                counts.info += 1
    return counts


def _fund_summaries(analysis: Analysis) -> list[FundSummaryOut]:
    mapping = analysis.column_mapping
    if any(column not in mapping for column in ("fund_id", "fund_name", "strategy")):
        return []

    first_row: dict[str, SourceRow] = {}
    for row in analysis.source_rows:
        fund_id = row.raw[mapping["fund_id"]].strip()
        if fund_id and fund_id not in first_row:
            first_row[fund_id] = row

    observations: dict[str, list[ReturnObservation]] = defaultdict(list)
    for observation in analysis.observations:
        observations[observation.fund_id].append(observation)

    issues: dict[str, list[ValidationIssue]] = defaultdict(list)
    for issue in analysis.issues:
        if issue.fund_id is not None:
            issues[issue.fund_id].append(issue)

    summaries = []
    for fund_id in sorted(first_row):
        periods = [o.period for o in observations[fund_id]]
        fund_issues = issues[fund_id]
        source = first_row[fund_id].raw
        summaries.append(
            FundSummaryOut(
                fund_id=fund_id,
                fund_name=source[mapping["fund_name"]].strip(),
                strategy=source[mapping["strategy"]].strip(),
                observation_count=len(periods),
                first_period=min(periods) if periods else None,
                last_period=max(periods) if periods else None,
                analysis_blocked=any(i.code is IssueCode.DUPLICATE_PERIOD for i in fund_issues),
                issue_counts=_count_issues(fund_issues),
                issue_codes=sorted({i.code for i in fund_issues}, key=list(IssueCode).index),
            )
        )
    return summaries
