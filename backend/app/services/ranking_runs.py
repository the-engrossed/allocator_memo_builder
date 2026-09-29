"""Ranking runs: resolve stored inputs, screen, score, shortlist, and persist an immutable run.

Each call creates a new run. Nothing here updates an existing run; later mandate edits do not
change what a run recorded.
"""

import hashlib
import json
import uuid
from collections import defaultdict
from datetime import date, datetime, timezone

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import AnalysisStatus, IssueSeverity, LiquidityFrequency, SelectionReason
from app.domain.models import Analysis, FundEvaluation, Mandate, RankingRun, SourceRow
from app.domain.schemas import (
    FundEvaluationOut,
    MandateResponse,
    RankingRunResponse,
    RankingRunSummary,
    RunWarningOut,
    ScreenResultOut,
)
from app.services import benchmarks
from app.services.ingestion import (
    METADATA_INT_LIMITS,
    ParseError,
    parse_bounded_int,
    parse_liquidity_frequency,
)
from app.services.mandates import AnalysisNotFoundError
from app.services.metrics import FundMetrics, compute_fund_metrics, risk_free_for_window
from app.services.ranking import (
    POLICY_VERSION,
    SCORE_WEIGHTS,
    FundInputs,
    RunWarning,
    build_shortlist,
    evaluate_screens,
    evidence_key,
    is_eligible,
    rank_order,
    score_funds,
)
from app.services.validation import BLOCKING_CODES

SELECTED = {SelectionReason.SELECTED_PREFERENCE_PASS, SelectionReason.SELECTED_RANK_PASS}


class RankingRunConflictError(ValueError):
    """The analysis cannot be ranked yet (no mandate, or the upload is invalid)."""


class RankingRunNotFoundError(LookupError):
    pass


def create_ranking_run(
    session: Session,
    analysis_id: uuid.UUID,
    *,
    today: date | None = None,
    now: datetime | None = None,
) -> RankingRun:
    now = now or datetime.now(timezone.utc)
    analysis = session.get(Analysis, analysis_id)
    if analysis is None:
        raise AnalysisNotFoundError(f"Analysis {analysis_id} not found.")
    if analysis.status == AnalysisStatus.INVALID:
        raise RankingRunConflictError(
            f"Analysis {analysis_id} is invalid; fix the upload before ranking."
        )
    mandate_row = session.get(Mandate, analysis_id)
    if mandate_row is None:
        raise RankingRunConflictError(
            f"Analysis {analysis_id} has no saved mandate; save one before ranking."
        )
    mandate = MandateResponse.model_validate(mandate_row)
    market = benchmarks.resolve_market_data(today=today, now=now)

    issues_by_fund: dict[str, list] = defaultdict(list)
    for issue in analysis.validation_issues:
        if issue.fund_id:
            issues_by_fund[issue.fund_id].append(issue)
    returns_by_fund = _returns_by_fund(analysis)

    evaluations: dict[str, dict] = {}
    for inputs, inputs_json in _resolve_fund_inputs(analysis, issues_by_fund):
        benchmark = benchmarks.benchmark_for_strategy(inputs.strategy)
        metrics = None
        if not inputs.blocked:
            metrics = _fund_metrics(
                returns_by_fund.get(inputs.fund_id, pd.Series(dtype=float)),
                benchmark,
                market,
                mandate.target_return_bps,
            )
        screens = evaluate_screens(inputs, metrics, mandate)
        evaluations[inputs.fund_id] = {
            "inputs": inputs,
            "inputs_json": inputs_json,
            "benchmark": benchmark,
            "metrics": metrics,
            "screens": screens,
            "eligible": is_eligible(screens),
            "data_quality": _data_quality(inputs.fund_id, issues_by_fund[inputs.fund_id]),
        }

    candidates = [
        (item["inputs"], item["metrics"]) for item in evaluations.values() if item["eligible"]
    ]
    needed = sorted({metrics.benchmark for _, metrics in candidates})
    unavailable = [ticker for ticker in needed if not market.benchmarks[ticker].available]
    warnings: list[RunWarning] = []
    if unavailable:
        warnings.append(
            RunWarning(
                code="BENCHMARK_UNAVAILABLE",
                message=(
                    f"No data for {', '.join(unavailable)}; the correlation component is 0 "
                    "for every eligible fund in this run."
                ),
                details={"benchmarks": unavailable},
            )
        )
    scores = score_funds(candidates, correlation_disabled=bool(unavailable))
    ranked = rank_order(candidates, scores)
    shortlist = build_shortlist(ranked, mandate)
    warnings.extend(shortlist.warnings)

    run = RankingRun(
        id=uuid.uuid4(),
        analysis_id=analysis_id,
        mandate_snapshot=_mandate_snapshot(mandate),
        mandate_sha256=mandate_sha256(mandate),
        benchmark_provenance=market.provenance_json(),
        warnings=[warning.to_json() for warning in warnings],
        policy_version=POLICY_VERSION,
        created_at=now,
    )
    rank_by_fund = {inputs.fund_id: position for position, inputs in enumerate(ranked, start=1)}
    for fund_id, item in evaluations.items():
        metrics: FundMetrics | None = item["metrics"]
        score = scores.get(fund_id)
        reason = shortlist.reasons.get(fund_id)
        run.evaluations.append(
            FundEvaluation(
                fund_id=fund_id,
                fund_name=item["inputs"].fund_name,
                strategy=item["inputs"].strategy,
                benchmark=item["benchmark"],
                eligible=item["eligible"],
                rank=rank_by_fund.get(fund_id),
                total_score=None if score is None else score.total,
                selection_reason=None if reason is None else reason.value,
                selection_detail=shortlist.details.get(fund_id),
                inputs=item["inputs_json"],
                metrics=_metrics_json(fund_id, item),
                screens=[screen.to_json() for screen in item["screens"]],
                score_components=None if score is None else score.components,
                data_quality=item["data_quality"],
                evidence_ids=_evidence_ids(fund_id, item),
            )
        )
    session.add(run)
    session.flush()
    return run


def get_ranking_run(session: Session, run_id: uuid.UUID) -> RankingRun:
    run = session.get(RankingRun, run_id)
    if run is None:
        raise RankingRunNotFoundError(f"Ranking run {run_id} not found.")
    return run


def get_latest_ranking_run(session: Session, analysis_id: uuid.UUID) -> RankingRun:
    if session.get(Analysis, analysis_id) is None:
        raise AnalysisNotFoundError(f"Analysis {analysis_id} not found.")
    run = session.scalar(
        select(RankingRun)
        .where(RankingRun.analysis_id == analysis_id)
        .order_by(RankingRun.created_at.desc(), RankingRun.id.desc())
        .limit(1)
    )
    if run is None:
        raise RankingRunNotFoundError(f"Analysis {analysis_id} has no ranking runs yet.")
    return run


def run_to_response(run: RankingRun) -> RankingRunResponse:
    ordered = sorted(
        run.evaluations,
        key=lambda item: (item.rank is None, item.rank or 0, item.fund_id),
    )
    eligible = sum(1 for item in ordered if item.eligible)
    shortlisted = sum(1 for item in ordered if item.selection_reason in SELECTED)
    return RankingRunResponse(
        run_id=run.id,
        analysis_id=run.analysis_id,
        created_at=run.created_at,
        policy_version=run.policy_version,
        mandate_sha256=run.mandate_sha256,
        mandate_snapshot=run.mandate_snapshot,
        benchmark_provenance=run.benchmark_provenance,
        score_weights=SCORE_WEIGHTS,
        warnings=[RunWarningOut(**warning) for warning in run.warnings],
        summary=RankingRunSummary(
            evaluated=len(ordered),
            eligible=eligible,
            excluded=len(ordered) - eligible,
            shortlisted=shortlisted,
        ),
        funds=[
            FundEvaluationOut(
                fund_id=item.fund_id,
                fund_name=item.fund_name,
                strategy=item.strategy,
                benchmark=item.benchmark,
                eligible=item.eligible,
                rank=item.rank,
                total_score=None if item.total_score is None else float(item.total_score),
                selection_reason=item.selection_reason,
                selection_detail=item.selection_detail,
                inputs=item.inputs,
                metrics=item.metrics,
                screens=[ScreenResultOut(**screen) for screen in item.screens],
                score_components=item.score_components,
                data_quality=item.data_quality,
                evidence_ids=item.evidence_ids,
            )
            for item in ordered
        ],
    )


def mandate_sha256(mandate: MandateResponse) -> str:
    fields = mandate.model_dump(mode="json", exclude={"analysis_id", "created_at", "updated_at"})
    canonical = json.dumps(fields, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _mandate_snapshot(mandate: MandateResponse) -> dict:
    snapshot = mandate.model_dump(mode="json", exclude={"analysis_id", "created_at"})
    snapshot["mandate_updated_at"] = snapshot.pop("updated_at")
    return snapshot


def _fund_metrics(
    returns: pd.Series, benchmark: str, market: benchmarks.MarketData, target_return_bps: int
) -> FundMetrics:
    start = returns.index.min().date() if len(returns) else None
    end = returns.index.max().date() if len(returns) else None
    rf_annual, rf_source = risk_free_for_window(
        market.risk_free.values, start, end, market.risk_free_fallback_annual
    )
    series = market.benchmarks[benchmark]
    return compute_fund_metrics(
        returns,
        benchmark=benchmark,
        benchmark_returns=series.values if series.available else None,
        risk_free_annual=rf_annual,
        risk_free_source=rf_source,
        target_return_bps=target_return_bps,
    )


def _returns_by_fund(analysis: Analysis) -> dict[str, pd.Series]:
    points: dict[str, dict[pd.Timestamp, float]] = defaultdict(dict)
    for observation in analysis.return_observations:
        points[observation.fund_id][pd.Timestamp(observation.period)] = float(
            observation.net_return
        )
    return {fund_id: pd.Series(values).sort_index() for fund_id, values in points.items()}


def _resolve_fund_inputs(
    analysis: Analysis, issues_by_fund: dict[str, list]
) -> list[tuple[FundInputs, dict]]:
    """Screen inputs from each fund's first source row; a field with an INVALID_METADATA issue
    (on any of the fund's rows) resolves to None, which makes its screen unverifiable."""
    mapping = analysis.column_mapping
    first_rows: dict[str, SourceRow] = {}
    for row in sorted(analysis.source_rows, key=lambda item: item.row_number):
        fund_id = row.raw.get(mapping.get("fund_id", ""), "").strip()
        if fund_id and fund_id not in first_rows:
            first_rows[fund_id] = row

    resolved: list[tuple[FundInputs, dict]] = []
    for fund_id in sorted(first_rows):
        row = first_rows[fund_id]
        issues = issues_by_fund.get(fund_id, [])
        invalid_fields = {issue.field for issue in issues if issue.code == "INVALID_METADATA"}
        raw = {field: row.raw.get(mapping.get(field, ""), "").strip() for field in mapping}

        liquidity: LiquidityFrequency | None = None
        if "liquidity_frequency" not in invalid_fields:
            try:
                liquidity = parse_liquidity_frequency(raw.get("liquidity_frequency", ""))
            except ParseError:
                liquidity = None
        terms: dict[str, int | None] = {}
        for field, maximum in METADATA_INT_LIMITS.items():
            terms[field] = None
            if field not in invalid_fields:
                try:
                    terms[field] = parse_bounded_int(raw.get(field, ""), maximum)
                except ParseError:
                    terms[field] = None

        resolved_values: dict[str, object] = {
            "liquidity_frequency": liquidity.value if liquidity else None,
            **terms,
            "fund_name": raw.get("fund_name", ""),
            "strategy": raw.get("strategy", ""),
        }
        inputs_json = {
            field: {
                "raw": raw.get(field, ""),
                "value": value,
                "status": "verified" if value is not None else "invalid",
                "source_row": row.row_number,
                "evidence_id": _source_evidence_id(fund_id, field),
            }
            for field, value in resolved_values.items()
        }
        notes = raw.get("notes", "")
        inputs_json["notes"] = {
            "raw": notes,
            "value": notes,
            "status": "verified" if notes else "missing",
            "source_row": row.row_number,
            "evidence_id": _source_evidence_id(fund_id, "notes"),
        }
        blocking = tuple(sorted({issue.code for issue in issues if issue.code in BLOCKING_CODES}))
        resolved.append(
            (
                FundInputs(
                    fund_id=fund_id,
                    fund_name=raw.get("fund_name", ""),
                    strategy=raw.get("strategy", ""),
                    liquidity_frequency=liquidity,
                    notice_days=terms["notice_days"],
                    lockup_months=terms["lockup_months"],
                    mgmt_fee_bps=terms["mgmt_fee_bps"],
                    perf_fee_bps=terms["perf_fee_bps"],
                    blocking_codes=blocking,
                ),
                inputs_json,
            )
        )
    return resolved


def _source_evidence_id(fund_id: str, field: str) -> str:
    return f"SRC-{evidence_key(fund_id)}-{_id_part(field)}"


def _id_part(name: str) -> str:
    return name.upper().replace("_", "-")


def _data_quality(fund_id: str, issues: list) -> list[dict]:
    """Non-info issues for the fund with unique evidence ids: DQ-{fund}-{CODE}[-{FIELD}],
    suffixed -2, -3, ... in source-row order if the same id would repeat."""
    key = evidence_key(fund_id)
    relevant = [issue for issue in issues if issue.severity != IssueSeverity.INFO]
    relevant.sort(key=lambda issue: (min(issue.row_numbers or [10**9]), issue.code))
    seen: dict[str, int] = defaultdict(int)
    entries: list[dict] = []
    for issue in relevant:
        base = f"DQ-{key}-{_id_part(issue.code)}"
        if issue.field:
            base = f"{base}-{_id_part(issue.field)}"
        seen[base] += 1
        evidence_id = base if seen[base] == 1 else f"{base}-{seen[base]}"
        entries.append(
            {
                "code": issue.code,
                "severity": issue.severity,
                "field": issue.field,
                "message": issue.message,
                "row_numbers": list(issue.row_numbers or []),
                "evidence_id": evidence_id,
            }
        )
    return entries


_METRIC_EVIDENCE = {
    "months_of_history": "MONTHS",
    "annualized_return_bps": "ANNUALIZED-RETURN",
    "volatility_bps": "VOLATILITY",
    "sharpe": "SHARPE",
    "max_drawdown_bps": "MAX-DRAWDOWN",
    "target_gap_bps": "TARGET-GAP",
}
_REPORTED_METRICS = (
    *_METRIC_EVIDENCE,
    "correlation",
    "excess_return_bps",
)


def _metric_evidence(fund_id: str, metrics: FundMetrics | None) -> dict[str, str]:
    """Evidence id for every metric that has a value; unverifiable metrics get none."""
    if metrics is None:
        return {}
    key = evidence_key(fund_id)
    values = metrics.to_json()
    evidence = {
        field: f"MET-{key}-{name}"
        for field, name in _METRIC_EVIDENCE.items()
        if values[field] is not None
    }
    if metrics.correlation is not None:
        evidence["correlation"] = f"MET-{key}-CORRELATION-{metrics.benchmark}"
    if metrics.excess_return_bps is not None:
        evidence["excess_return_bps"] = f"MET-{key}-EXCESS-VS-{metrics.benchmark}"
    return evidence


def _metrics_json(fund_id: str, item: dict) -> dict:
    metrics: FundMetrics | None = item["metrics"]
    if metrics is not None:
        data = metrics.to_json()
    else:
        reason = "Fund blocked by validation: " + ", ".join(item["inputs"].blocking_codes)
        data = {name: None for name in _REPORTED_METRICS}
        data.update(
            window_start=None,
            window_end=None,
            correlation_overlap_months=0,
            benchmark=item["benchmark"],
            benchmark_available=None,
            risk_free_annual_bps=None,
            risk_free_source=None,
            unverifiable_reasons={name: reason for name in _REPORTED_METRICS},
        )
    data["metric_evidence"] = _metric_evidence(fund_id, metrics)
    return data


def _evidence_ids(fund_id: str, item: dict) -> list[str]:
    ids = [field["evidence_id"] for field in item["inputs_json"].values()]
    ids.extend(_metric_evidence(fund_id, item["metrics"]).values())
    ids.extend(screen.code for screen in item["screens"])
    ids.extend(issue["evidence_id"] for issue in item["data_quality"])
    return ids
