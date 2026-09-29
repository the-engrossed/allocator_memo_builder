"""Deterministic screens, score, and shortlist (AGENTS.md section 9, policy v1). Pure; no I/O.

Screens compare persisted integer bps (and whole-number terms) to integer mandate thresholds,
with inclusive boundaries. Preferred strategies and SMOOTH_RETURNS are never screens.
"""

import operator
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from app.domain.enums import LiquidityFrequency, ScreenOutcome, SelectionReason
from app.domain.schemas import MandateFields
from app.services.metrics import FundMetrics

POLICY_VERSION = "v1"

# AGENTS.md section 9: locked weights, in percent. No mandate field may change them.
SCORE_WEIGHTS: dict[str, int] = {
    "sharpe": 45,
    "annualized_return": 25,
    "drawdown_resilience": 20,
    "low_correlation": 10,
}

LIQUIDITY_ORDER: tuple[LiquidityFrequency, ...] = tuple(LiquidityFrequency)


@dataclass(frozen=True)
class FundInputs:
    """Screen inputs resolved from the fund's first source row; None means missing or invalid."""

    fund_id: str
    fund_name: str
    strategy: str
    liquidity_frequency: LiquidityFrequency | None
    notice_days: int | None
    lockup_months: int | None
    mgmt_fee_bps: int | None
    perf_fee_bps: int | None
    blocking_codes: tuple[str, ...] = ()

    @property
    def blocked(self) -> bool:
        return bool(self.blocking_codes)


@dataclass(frozen=True)
class ScreenResult:
    code: str
    screen: str
    result: ScreenOutcome
    observed: object
    threshold: object
    reason: str

    def to_json(self) -> dict:
        return {
            "code": self.code,
            "screen": self.screen,
            "result": self.result.value,
            "observed": self.observed,
            "threshold": self.threshold,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RunWarning:
    code: str
    message: str
    details: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return {"code": self.code, "message": self.message, "details": self.details}


@dataclass(frozen=True)
class ScoreBreakdown:
    components: dict[str, dict]
    total: float


@dataclass(frozen=True)
class ShortlistResult:
    reasons: dict[str, SelectionReason]
    details: dict[str, str]
    per_strategy_limit: int
    warnings: list[RunWarning]


def evidence_key(fund_id: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "-", fund_id.upper()).strip("-")


def evaluate_screens(
    inputs: FundInputs, metrics: FundMetrics | None, mandate: MandateFields
) -> list[ScreenResult]:
    key = evidence_key(inputs.fund_id)

    def result(
        screen: str, outcome: ScreenOutcome, observed: object, threshold: object, reason: str
    ) -> ScreenResult:
        code = f"SCR-{key}-{screen}-{outcome.value.upper()}"
        return ScreenResult(code, screen, outcome, observed, threshold, reason)

    def bounded(
        screen: str,
        observed: int | None,
        threshold: int,
        passes: Callable[[int, int], bool],
        label: str,
        missing: str,
    ) -> ScreenResult:
        if observed is None:
            return result(screen, ScreenOutcome.UNVERIFIABLE, None, threshold, missing)
        outcome = ScreenOutcome.PASS if passes(observed, threshold) else ScreenOutcome.FAIL
        return result(screen, outcome, observed, threshold, f"{label} {observed} vs {threshold}.")

    at_most, at_least = operator.le, operator.ge
    invalid_field = "The source field is missing or invalid."
    no_metrics = (
        "Metrics were not computed because the fund is blocked."
        if inputs.blocked
        else "Not enough observations to compute this metric."
    )

    screens = [
        result(
            "BLOCKING-VALIDATION",
            ScreenOutcome.FAIL if inputs.blocked else ScreenOutcome.PASS,
            list(inputs.blocking_codes),
            [],
            (
                "Blocking validation issues: " + ", ".join(inputs.blocking_codes) + "."
                if inputs.blocked
                else "No blocking validation issues."
            ),
        ),
        _liquidity_screen(inputs, mandate, result),
        bounded("NOTICE", inputs.notice_days, mandate.max_notice_days, at_most,
                "Notice days", invalid_field),
        bounded("LOCKUP", inputs.lockup_months, mandate.max_lockup_months, at_most,
                "Lockup months", invalid_field),
        bounded("MGMT-FEE", inputs.mgmt_fee_bps, mandate.max_mgmt_fee_bps, at_most,
                "Management fee bps", invalid_field),
        bounded("PERF-FEE", inputs.perf_fee_bps, mandate.max_perf_fee_bps, at_most,
                "Performance fee bps", invalid_field),
        bounded("VOLATILITY", metrics.volatility_bps if metrics else None,
                mandate.max_volatility_bps, at_most, "Annualized volatility bps", no_metrics),
        bounded("DRAWDOWN", metrics.max_drawdown_bps if metrics else None,
                mandate.max_drawdown_bps, at_most, "Max drawdown bps", no_metrics),
        bounded("TRACK-RECORD", metrics.months_of_history if metrics else None,
                mandate.min_track_record_months, at_least, "Months of history", no_metrics),
    ]
    excluded = {name.casefold() for name in mandate.excluded_strategies}
    is_excluded = inputs.strategy.strip().casefold() in excluded
    screens.append(
        result(
            "EXCLUDED-STRATEGY",
            ScreenOutcome.FAIL if is_excluded else ScreenOutcome.PASS,
            inputs.strategy,
            list(mandate.excluded_strategies),
            f"Strategy {inputs.strategy!r} is {'excluded' if is_excluded else 'not excluded'}.",
        )
    )
    return screens


def is_eligible(screens: list[ScreenResult]) -> bool:
    return all(screen.result is ScreenOutcome.PASS for screen in screens)


def percentile_ranks(values: dict[str, float], *, higher_is_better: bool) -> dict[str, float]:
    """position / (n - 1) * 100 with the best value at 100; ties share their average position."""
    if not values:
        return {}
    if len(values) == 1:
        return {fund_id: 100.0 for fund_id in values}
    ordered = sorted(values, key=lambda fund_id: values[fund_id] * (1 if higher_is_better else -1))
    positions: dict[str, float] = {}
    index = 0
    while index < len(ordered):
        end = index
        while end + 1 < len(ordered) and values[ordered[end + 1]] == values[ordered[index]]:
            end += 1
        average = (index + end) / 2
        for fund_id in ordered[index : end + 1]:
            positions[fund_id] = average
        index = end + 1
    return {fund_id: position / (len(values) - 1) * 100 for fund_id, position in positions.items()}


def score_funds(
    candidates: list[tuple[FundInputs, FundMetrics]], *, correlation_disabled: bool
) -> dict[str, ScoreBreakdown]:
    """Percentile-rank each component across eligible funds and apply the locked weights.

    A component with no verifiable value scores 0 and is flagged; when correlation is disabled
    for the run (a needed benchmark is unavailable), every fund's correlation component is 0.
    """
    components = {
        "sharpe": (lambda m: m.sharpe, True),
        "annualized_return": (lambda m: m.annualized_return_bps, True),
        "drawdown_resilience": (lambda m: m.max_drawdown_bps, False),
        "low_correlation": (lambda m: m.correlation, False),
    }
    breakdown: dict[str, dict[str, dict]] = {inputs.fund_id: {} for inputs, _ in candidates}
    raw_totals: dict[str, float] = {inputs.fund_id: 0.0 for inputs, _ in candidates}
    for name, (getter, higher_is_better) in components.items():
        disabled = name == "low_correlation" and correlation_disabled
        values = {
            inputs.fund_id: getter(metrics)
            for inputs, metrics in candidates
            if not disabled and getter(metrics) is not None
        }
        ranks = percentile_ranks(values, higher_is_better=higher_is_better)
        for inputs, metrics in candidates:
            percentile = ranks.get(inputs.fund_id)
            flag = None
            if disabled:
                flag = "benchmark_unavailable"
            elif percentile is None:
                flag = "unverifiable"
            weight = SCORE_WEIGHTS[name]
            points = weight * (percentile or 0.0) / 100
            raw_totals[inputs.fund_id] += points
            breakdown[inputs.fund_id][name] = {
                "value": getter(metrics),
                "percentile": round(percentile or 0.0, 2),
                "weight": weight,
                "points": round(points, 2),
                "flag": flag,
            }
    return {
        fund_id: ScoreBreakdown(components=parts, total=_round_score(raw_totals[fund_id]))
        for fund_id, parts in breakdown.items()
    }


def rank_order(
    candidates: list[tuple[FundInputs, FundMetrics]], scores: dict[str, ScoreBreakdown]
) -> list[FundInputs]:
    """Total desc, target gap desc (unverifiable last), fees asc, name, then fund_id."""

    def key(candidate: tuple[FundInputs, FundMetrics]) -> tuple:
        inputs, metrics = candidate
        gap = metrics.target_gap_bps
        return (
            -scores[inputs.fund_id].total,
            gap is None,
            -(gap or 0),
            inputs.mgmt_fee_bps if inputs.mgmt_fee_bps is not None else 10**9,
            inputs.perf_fee_bps if inputs.perf_fee_bps is not None else 10**9,
            inputs.fund_name.casefold(),
            inputs.fund_id,
        )

    return [inputs for inputs, _ in sorted(candidates, key=key)]


def build_shortlist(ranked: list[FundInputs], mandate: MandateFields) -> ShortlistResult:
    """Pass 1: preferred-strategy funds in rank order. Pass 2: the rest in rank order."""
    raw_limit = mandate.max_candidates * mandate.strategy_concentration_cap_bps // 10_000
    limit = max(1, raw_limit)
    warnings: list[RunWarning] = []
    if raw_limit < 1:
        warnings.append(
            RunWarning(
                code="CONCENTRATION_FLOOR_APPLIED",
                message=(
                    f"A {mandate.strategy_concentration_cap_bps} bps cap on "
                    f"{mandate.max_candidates} candidates allows less than one fund per "
                    "strategy; the floor of one fund per strategy was applied."
                ),
                details={
                    "max_candidates": mandate.max_candidates,
                    "strategy_concentration_cap_bps": mandate.strategy_concentration_cap_bps,
                    "per_strategy_limit": limit,
                },
            )
        )

    preferred = {name.casefold() for name in mandate.preferred_strategies}
    first_pass = [f for f in ranked if f.strategy.strip().casefold() in preferred]
    second_pass = [f for f in ranked if f.strategy.strip().casefold() not in preferred]

    reasons: dict[str, SelectionReason] = {}
    details: dict[str, str] = {}
    counts: dict[str, int] = {}
    selected = 0
    for funds, reason in (
        (first_pass, SelectionReason.SELECTED_PREFERENCE_PASS),
        (second_pass, SelectionReason.SELECTED_RANK_PASS),
    ):
        for fund in funds:
            strategy = fund.strategy.strip().casefold()
            if selected >= mandate.max_candidates:
                reasons[fund.fund_id] = SelectionReason.CAPACITY_REACHED
                details[fund.fund_id] = f"Shortlist is full at {mandate.max_candidates} funds."
            elif counts.get(strategy, 0) >= limit:
                reasons[fund.fund_id] = SelectionReason.CONCENTRATION_SKIP
                details[fund.fund_id] = (
                    f"{fund.strategy} already holds {limit} of {limit} allowed shortlist slots."
                )
            else:
                reasons[fund.fund_id] = reason
                counts[strategy] = counts.get(strategy, 0) + 1
                selected += 1
                details[fund.fund_id] = (
                    "Selected in the preferred-strategy pass."
                    if reason is SelectionReason.SELECTED_PREFERENCE_PASS
                    else "Selected in the rank-order pass."
                )
    return ShortlistResult(reasons, details, limit, warnings)


def _liquidity_screen(
    inputs: FundInputs,
    mandate: MandateFields,
    result: Callable[[str, ScreenOutcome, object, object, str], ScreenResult],
) -> ScreenResult:
    threshold = mandate.min_liquidity_frequency.value
    if inputs.liquidity_frequency is None:
        return result(
            "LIQUIDITY", ScreenOutcome.UNVERIFIABLE, None, threshold,
            "The source field is missing or invalid.",
        )
    observed = inputs.liquidity_frequency
    passes = LIQUIDITY_ORDER.index(observed) <= LIQUIDITY_ORDER.index(
        mandate.min_liquidity_frequency
    )
    return result(
        "LIQUIDITY",
        ScreenOutcome.PASS if passes else ScreenOutcome.FAIL,
        observed.value,
        threshold,
        f"Redeems {observed.value}; the mandate requires {threshold} or more often.",
    )


def _round_score(total: float) -> float:
    return float(Decimal(str(total)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
