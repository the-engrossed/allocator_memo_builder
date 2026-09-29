"""Evidence registry: every citable fact of one persisted ranking run, keyed by evidence ID.

Built deterministically from the run's stored JSON. Nothing is recomputed: MET, SRC, DQ, and
SCR records reuse the IDs the run issued. SEL, BMK, and RUN records are derived one-to-one from
the run's selection reasons, benchmark provenance, and run warnings.
"""

from dataclasses import asdict, dataclass, field

from app.domain.models import FundEvaluation, RankingRun
from app.services.ranking import evidence_key

EVIDENCE_TYPES = (
    "metric",
    "source_field",
    "data_quality",
    "screen_result",
    "selection",
    "benchmark",
    "run_warning",
)
UNTRUSTED_SOURCE_FIELDS = ("fund_name", "strategy", "notes")

_METRIC_LABELS = {
    "months_of_history": "Months of return history",
    "annualized_return_bps": "Annualized return (CAGR)",
    "volatility_bps": "Annualized volatility",
    "sharpe": "Sharpe ratio",
    "max_drawdown_bps": "Maximum drawdown",
    "target_gap_bps": "Gap to target return",
    "correlation": "Correlation to {benchmark}",
    "excess_return_bps": "Excess annualized return vs {benchmark}",
}
_METRIC_FORMULAS = {
    "months_of_history": "count of valid monthly observations",
    "annualized_return_bps": "prod(1 + r)^(12/n) - 1",
    "volatility_bps": "stdev(r, ddof=1) * sqrt(12)",
    "sharpe": "mean(r_m - rf_m) / stdev(r_m) * sqrt(12), rf_m = (1 + rf)^(1/12) - 1",
    "max_drawdown_bps": "max(1 - wealth / running peak), wealth index starting at 1.0",
    "target_gap_bps": "annualized_return_bps - mandate target_return_bps",
    "correlation": "Pearson correlation on overlapping months",
    "excess_return_bps": "fund CAGR - benchmark CAGR over overlapping months",
}
_SOURCE_LABELS = {
    "fund_name": "Fund name",
    "strategy": "Strategy",
    "liquidity_frequency": "Redemption frequency",
    "notice_days": "Notice period",
    "lockup_months": "Lockup",
    "mgmt_fee_bps": "Management fee",
    "perf_fee_bps": "Performance fee",
    "notes": "Manager notes",
}
_SELECTION_LABELS = {
    "SELECTED_PREFERENCE_PASS": "Selected in the preferred-strategy pass",
    "SELECTED_RANK_PASS": "Selected in the rank-order pass",
    "CONCENTRATION_SKIP": "Skipped by the strategy concentration cap",
    "CAPACITY_REACHED": "Not selected: shortlist full",
}
_SELECTION_SHORT = {
    "CONCENTRATION_SKIP": "Skipped · concentration cap",
    "CAPACITY_REACHED": "Not selected · shortlist full",
}
# Chip text for data-quality evidence; the full issue message is in the label and provenance.
_DATA_QUALITY_SHORT = {
    "SMOOTH_RETURNS": "Smooth returns",
    "MISSING_MONTHS": "Missing months",
    "INCONSISTENT_DATE_RANGE": "Stale data",
    "FUND_ID_MISMATCH": "Possible duplicate fund",
    "CONFLICTING_METADATA": "Conflicting terms",
    "INVALID_METADATA": "Invalid term",
}
_BENCHMARKS = (("SPY", "BMK-SPY"), ("AGG", "BMK-AGG"), ("risk_free", "BMK-RF"))
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


class DuplicateEvidenceError(ValueError):
    pass


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    type: str
    fund_id: str | None
    label: str
    display_value: str
    verification_status: str
    provenance: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return asdict(self)


def build_registry(run: RankingRun) -> dict[str, EvidenceRecord]:
    records: list[EvidenceRecord] = []
    for evaluation in sorted(run.evaluations, key=lambda item: item.fund_id):
        records.extend(_metric_records(run, evaluation))
        records.extend(_source_records(evaluation))
        records.extend(_data_quality_records(evaluation))
        records.extend(_screen_records(evaluation))
        records.extend(_selection_records(evaluation))
    records.extend(_benchmark_records(run))
    records.extend(_warning_records(run))

    registry: dict[str, EvidenceRecord] = {}
    for record in records:
        if record.evidence_id in registry:
            raise DuplicateEvidenceError(f"Duplicate evidence id {record.evidence_id}.")
        registry[record.evidence_id] = record
    return registry


def selection_evidence_id(fund_id: str, reason: str) -> str:
    return f"SEL-{_key(fund_id)}-{reason.replace('_', '-')}"


def format_bps(bps: int, *, signed: bool = False) -> str:
    sign = "-" if bps < 0 else ("+" if signed and bps > 0 else "")
    magnitude = abs(bps)
    return f"{sign}{magnitude // 100}.{magnitude % 100:02d}%"


def format_month(iso: str | None) -> str:
    if not iso:
        return "n/a"
    year, month = iso.split("-")[:2]
    return f"{_MONTHS[int(month) - 1]} {year}"


def _metric_records(run: RankingRun, evaluation: FundEvaluation) -> list[EvidenceRecord]:
    metrics = evaluation.metrics or {}
    benchmark = metrics.get("benchmark") or evaluation.benchmark
    records = []
    # Sorted so registry order never depends on JSONB key order.
    for name, evidence_id in sorted((metrics.get("metric_evidence") or {}).items()):
        value = metrics.get(name)
        provenance = {
            "formula": _METRIC_FORMULAS.get(name, ""),
            "window_start": metrics.get("window_start"),
            "window_end": metrics.get("window_end"),
            "observations": metrics.get("months_of_history"),
            "risk_free_annual_bps": metrics.get("risk_free_annual_bps"),
            "risk_free_source": metrics.get("risk_free_source"),
            "benchmark": benchmark,
            "ranking_run_id": str(run.id),
        }
        if name in ("correlation", "excess_return_bps"):
            provenance["overlap_months"] = metrics.get("correlation_overlap_months")
        if name == "target_gap_bps":
            provenance["target_return_bps"] = run.mandate_snapshot.get("target_return_bps")
        records.append(
            EvidenceRecord(
                evidence_id=evidence_id,
                type="metric",
                fund_id=evaluation.fund_id,
                label=f"{evaluation.fund_id} {_METRIC_LABELS[name].format(benchmark=benchmark)}",
                display_value=_metric_display(name, value),
                verification_status="verified" if value is not None else "unverifiable",
                provenance=provenance,
            )
        )
    return records


def _metric_display(name: str, value: object) -> str:
    if value is None:
        return "unverifiable"
    if name == "months_of_history":
        return f"{value} months"
    if name in ("sharpe", "correlation"):
        return f"{float(value):.2f}"
    signed = name in ("target_gap_bps", "excess_return_bps")
    return format_bps(int(value), signed=signed)


def _source_records(evaluation: FundEvaluation) -> list[EvidenceRecord]:
    records = []
    for name, entry in evaluation.inputs.items():
        status = entry.get("status", "verified")
        if status not in ("verified", "invalid", "missing"):
            status = "invalid"
        records.append(
            EvidenceRecord(
                evidence_id=entry["evidence_id"],
                type="source_field",
                fund_id=evaluation.fund_id,
                label=f"{evaluation.fund_id} {_SOURCE_LABELS.get(name, name)}",
                display_value=_source_display(name, entry, status),
                verification_status=status,
                provenance={
                    "field": name,
                    "source_row": entry.get("source_row"),
                    "raw_value": entry.get("raw"),
                    "untrusted_text": name in UNTRUSTED_SOURCE_FIELDS,
                },
            )
        )
    return records


def _source_display(name: str, entry: dict, status: str) -> str:
    raw = entry.get("raw", "")
    value = entry.get("value")
    if status == "missing":
        return "(empty)"
    if status == "invalid" or value is None:
        return f"invalid: {raw!r}" if raw else "invalid: (empty)"
    if name == "liquidity_frequency":
        return str(value).capitalize()
    if name == "notice_days":
        return f"{value} days"
    if name == "lockup_months":
        return f"{value} months"
    if name in ("mgmt_fee_bps", "perf_fee_bps"):
        return f"{value} bps ({format_bps(int(value))})"
    if name == "notes":
        return "Manager notes"
    return str(value)


def _data_quality_records(evaluation: FundEvaluation) -> list[EvidenceRecord]:
    return [
        EvidenceRecord(
            evidence_id=issue["evidence_id"],
            type="data_quality",
            fund_id=evaluation.fund_id,
            label=f"{evaluation.fund_id} {issue['code']} ({issue['severity']}): {issue['message']}",
            display_value=_DATA_QUALITY_SHORT.get(issue["code"], issue["code"].replace("_", " ").capitalize()),
            verification_status="verified",
            provenance={
                "code": issue["code"],
                "severity": issue["severity"],
                "message": issue["message"],
                "field": issue.get("field"),
                "source_rows": issue.get("row_numbers", []),
            },
        )
        for issue in evaluation.data_quality
    ]


def _screen_records(evaluation: FundEvaluation) -> list[EvidenceRecord]:
    records = []
    for screen in evaluation.screens:
        result = screen["result"]
        observed, threshold = screen.get("observed"), screen.get("threshold")
        detail = ""
        if observed not in (None, [], "") and threshold not in (None, [], ""):
            detail = f" ({_plain(observed)} vs {_plain(threshold)})"
        records.append(
            EvidenceRecord(
                evidence_id=screen["code"],
                type="screen_result",
                fund_id=evaluation.fund_id,
                label=f"{evaluation.fund_id} {screen['screen']} screen",
                display_value=f"{result.capitalize()}{detail}",
                verification_status="unverifiable" if result == "unverifiable" else "verified",
                provenance={
                    "screen": screen["screen"],
                    "result": result,
                    "observed": observed,
                    "threshold": threshold,
                    "reason": screen.get("reason"),
                },
            )
        )
    return records


def _selection_records(evaluation: FundEvaluation) -> list[EvidenceRecord]:
    reason = evaluation.selection_reason
    if not reason:
        return []
    score = None if evaluation.total_score is None else float(evaluation.total_score)
    decision = _SELECTION_LABELS.get(reason, reason)
    if reason in _SELECTION_SHORT:
        display = _SELECTION_SHORT[reason]
    elif evaluation.rank is not None and score is not None:
        display = f"Rank {evaluation.rank} · score {score:.1f}"
    else:
        display = decision
    return [
        EvidenceRecord(
            evidence_id=selection_evidence_id(evaluation.fund_id, reason),
            type="selection",
            fund_id=evaluation.fund_id,
            label=f"{evaluation.fund_id} shortlist decision: {decision}",
            display_value=display,
            verification_status="verified",
            provenance={
                "selection_reason": reason,
                "selection": decision,
                "selection_detail": evaluation.selection_detail,
                "rank": evaluation.rank,
                "total_score": score,
                "score_components": evaluation.score_components,
            },
        )
    ]


def _benchmark_records(run: RankingRun) -> list[EvidenceRecord]:
    records = []
    for key, evidence_id in _BENCHMARKS:
        series = run.benchmark_provenance.get(key)
        if not series:
            continue
        state = series.get("state", "unavailable")
        coverage = (
            f"{format_month(series.get('coverage_start'))} to {format_month(series.get('coverage_end'))}"
            if series.get("coverage_start")
            else "no coverage"
        )
        if key == "risk_free" and state == "fallback":
            display = f"Configured fallback {format_bps(series.get('fallback_annual_bps', 0))} (fallback)"
        else:
            display = f"{series.get('provider')} {series.get('series_id')}, {state}, {coverage}"
        records.append(
            EvidenceRecord(
                evidence_id=evidence_id,
                type="benchmark",
                fund_id=None,
                label="Risk-free rate" if key == "risk_free" else f"{key} benchmark",
                display_value=display,
                verification_status="unverifiable" if state == "unavailable" else "verified",
                provenance={k: series.get(k) for k in (
                    "provider", "series_id", "state", "retrieved_at",
                    "coverage_start", "coverage_end", "message", "fallback_annual_bps",
                )},
            )
        )
    return records


def _warning_records(run: RankingRun) -> list[EvidenceRecord]:
    return [
        EvidenceRecord(
            evidence_id=f"RUN-{warning['code'].replace('_', '-')}",
            type="run_warning",
            fund_id=None,
            label=f"Run warning {warning['code']}",
            display_value=warning["message"],
            verification_status="verified",
            provenance={"code": warning["code"], "details": warning.get("details", {})},
        )
        for warning in run.warnings
    ]


def _plain(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) or "none"
    return str(value)


def _key(fund_id: str) -> str:
    return evidence_key(fund_id)
