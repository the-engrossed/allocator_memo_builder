from datetime import date

import pytest

from app.domain.enums import LiquidityFrequency, ScreenOutcome, SelectionReason
from app.domain.schemas import MandateIn
from app.services.metrics import FundMetrics
from app.services.ranking import (
    FundInputs,
    build_shortlist,
    evaluate_screens,
    is_eligible,
    percentile_ranks,
    rank_order,
    score_funds,
)

MANDATE = {
    "target_return_bps": 1000,
    "max_mgmt_fee_bps": 200,
    "max_perf_fee_bps": 2000,
    "max_notice_days": 90,
    "max_lockup_months": 12,
    "min_liquidity_frequency": "quarterly",
    "max_volatility_bps": 1500,
    "max_drawdown_bps": 2000,
    "min_track_record_months": 36,
    "preferred_strategies": ["Macro"],
    "excluded_strategies": ["Crypto"],
    "strategy_concentration_cap_bps": 4000,
    "max_candidates": 5,
}


def _mandate(**overrides: object) -> MandateIn:
    return MandateIn.model_validate({**MANDATE, **overrides})


def _inputs(fund_id: str = "F001", **overrides: object) -> FundInputs:
    values = {
        "fund_id": fund_id,
        "fund_name": f"Fund {fund_id}",
        "strategy": "Macro",
        "liquidity_frequency": LiquidityFrequency.QUARTERLY,
        "notice_days": 90,
        "lockup_months": 12,
        "mgmt_fee_bps": 200,
        "perf_fee_bps": 2000,
    }
    values.update(overrides)
    return FundInputs(**values)


def _metrics(**overrides: object) -> FundMetrics:
    values = {
        "months_of_history": 36,
        "window_start": date(2023, 1, 1),
        "window_end": date(2025, 12, 1),
        "annualized_return_bps": 1100,
        "volatility_bps": 1500,
        "max_drawdown_bps": 2000,
        "sharpe": 1.0,
        "correlation": 0.3,
        "correlation_overlap_months": 36,
        "benchmark": "SPY",
        "benchmark_available": True,
        "risk_free_annual_bps": 400,
        "risk_free_source": "configured_fallback",
        "target_gap_bps": 100,
    }
    values.update(overrides)
    return FundMetrics(**values)


def _by_screen(screens) -> dict[str, ScreenOutcome]:
    return {screen.screen: screen.result for screen in screens}


def test_every_screen_passes_at_its_inclusive_boundary() -> None:
    screens = evaluate_screens(_inputs(), _metrics(), _mandate())
    assert set(_by_screen(screens).values()) == {ScreenOutcome.PASS}
    assert is_eligible(screens)
    assert [screen.screen for screen in screens] == [
        "BLOCKING-VALIDATION", "LIQUIDITY", "NOTICE", "LOCKUP", "MGMT-FEE", "PERF-FEE",
        "VOLATILITY", "DRAWDOWN", "TRACK-RECORD", "EXCLUDED-STRATEGY",
    ]


@pytest.mark.parametrize(
    ("screen", "inputs", "metrics"),
    [
        ("LIQUIDITY", {"liquidity_frequency": LiquidityFrequency.SEMIANNUAL}, {}),
        ("NOTICE", {"notice_days": 91}, {}),
        ("LOCKUP", {"lockup_months": 13}, {}),
        ("MGMT-FEE", {"mgmt_fee_bps": 201}, {}),
        ("PERF-FEE", {"perf_fee_bps": 2001}, {}),
        ("VOLATILITY", {}, {"volatility_bps": 1501}),
        ("DRAWDOWN", {}, {"max_drawdown_bps": 2001}),
        ("TRACK-RECORD", {}, {"months_of_history": 35}),
        ("EXCLUDED-STRATEGY", {"strategy": " crypto "}, {}),
    ],
)
def test_each_screen_fails_one_step_past_its_threshold(
    screen: str, inputs: dict, metrics: dict
) -> None:
    screens = evaluate_screens(_inputs("F005", **inputs), _metrics(**metrics), _mandate())
    outcomes = _by_screen(screens)
    assert outcomes[screen] is ScreenOutcome.FAIL
    assert [s for s, outcome in outcomes.items() if outcome is not ScreenOutcome.PASS] == [screen]
    assert not is_eligible(screens)
    failed = next(s for s in screens if s.screen == screen)
    assert failed.code == f"SCR-F005-{screen}-FAIL"


def test_invalid_metadata_and_blocked_funds_are_unverifiable() -> None:
    screens = evaluate_screens(_inputs(notice_days=None, liquidity_frequency=None), _metrics(), _mandate())
    outcomes = _by_screen(screens)
    assert outcomes["NOTICE"] is ScreenOutcome.UNVERIFIABLE
    assert outcomes["LIQUIDITY"] is ScreenOutcome.UNVERIFIABLE
    assert not is_eligible(screens)

    blocked = evaluate_screens(_inputs(blocking_codes=("RETURN_OUT_OF_RANGE",)), None, _mandate())
    outcomes = _by_screen(blocked)
    assert outcomes["BLOCKING-VALIDATION"] is ScreenOutcome.FAIL
    for screen in ("VOLATILITY", "DRAWDOWN", "TRACK-RECORD"):
        assert outcomes[screen] is ScreenOutcome.UNVERIFIABLE
    assert "SCR-F001-VOLATILITY-UNVERIFIABLE" in {screen.code for screen in blocked}


def test_preferred_strategy_is_not_a_screen() -> None:
    screens = evaluate_screens(_inputs(strategy="Quant"), _metrics(), _mandate())
    assert is_eligible(screens)


@pytest.mark.parametrize(
    ("values", "higher", "expected"),
    [
        ({"a": 1.0, "b": 2.0, "c": 3.0}, True, {"a": 0.0, "b": 50.0, "c": 100.0}),
        ({"a": 1.0, "b": 1.0, "c": 3.0}, True, {"a": 25.0, "b": 25.0, "c": 100.0}),
        ({"a": 1.0, "b": 2.0, "c": 3.0}, False, {"a": 100.0, "b": 50.0, "c": 0.0}),
        ({"a": 5.0, "b": 5.0}, True, {"a": 50.0, "b": 50.0}),
        ({"a": 7.0}, True, {"a": 100.0}),
    ],
)
def test_percentile_ranks(values: dict, higher: bool, expected: dict) -> None:
    assert percentile_ranks(values, higher_is_better=higher) == expected


def test_outlier_does_not_compress_other_funds() -> None:
    candidates = [
        (_inputs("A"), _metrics(sharpe=15.0)),
        (_inputs("B"), _metrics(sharpe=1.2)),
        (_inputs("C"), _metrics(sharpe=1.1)),
    ]
    scores = score_funds(candidates, correlation_disabled=False)
    assert scores["B"].components["sharpe"]["percentile"] == 50.0
    assert scores["C"].components["sharpe"]["percentile"] == 0.0


def test_unverifiable_and_disabled_correlation_score_zero() -> None:
    candidates = [
        (_inputs("A"), _metrics(correlation=None)),
        (_inputs("B"), _metrics(correlation=0.9)),
    ]
    scores = score_funds(candidates, correlation_disabled=False)
    assert scores["A"].components["low_correlation"] == {
        "value": None, "percentile": 0.0, "weight": 10, "points": 0.0, "flag": "unverifiable",
    }
    assert scores["B"].components["low_correlation"]["percentile"] == 100.0

    disabled = score_funds(candidates, correlation_disabled=True)
    for fund_id in ("A", "B"):
        component = disabled[fund_id].components["low_correlation"]
        assert component["points"] == 0.0 and component["flag"] == "benchmark_unavailable"


def test_total_uses_locked_weights_and_one_decimal() -> None:
    candidates = [
        (_inputs("A"), _metrics(sharpe=2.0, annualized_return_bps=900, max_drawdown_bps=500, correlation=0.1)),
        (_inputs("B"), _metrics(sharpe=1.0, annualized_return_bps=1200, max_drawdown_bps=900, correlation=0.5)),
    ]
    scores = score_funds(candidates, correlation_disabled=False)
    assert scores["A"].total == 75.0
    assert scores["B"].total == 25.0


def test_tie_breakers_in_order() -> None:
    same = {"sharpe": 1.0, "annualized_return_bps": 1100, "max_drawdown_bps": 1000, "correlation": 0.2}
    candidates = [
        (_inputs("F9", fund_name="zeta"), _metrics(**same, target_gap_bps=100)),
        (_inputs("F8", fund_name="Alpha"), _metrics(**same, target_gap_bps=100)),
        (_inputs("F7", fund_name="alpha"), _metrics(**same, target_gap_bps=100)),
        (_inputs("F6"), _metrics(**same, target_gap_bps=100, )),
        (_inputs("F5", perf_fee_bps=1500), _metrics(**same, target_gap_bps=100)),
        (_inputs("F4", mgmt_fee_bps=100), _metrics(**same, target_gap_bps=100)),
        (_inputs("F3"), _metrics(**same, target_gap_bps=300)),
        (_inputs("F2"), _metrics(**same, target_gap_bps=None)),
    ]
    scores = score_funds(candidates, correlation_disabled=False)
    assert len({score.total for score in scores.values()}) == 1
    order = [inputs.fund_id for inputs in rank_order(candidates, scores)]
    assert order == ["F3", "F4", "F5", "F7", "F8", "F6", "F9", "F2"]


def test_shortlist_preference_pass_then_rank_pass_then_capacity() -> None:
    ranked = [
        _inputs("R1", strategy="Quant"),
        _inputs("P1", strategy="Macro"),
        _inputs("R2", strategy="Credit"),
        _inputs("P2", strategy="macro"),
    ]
    result = build_shortlist(ranked, _mandate(max_candidates=3, strategy_concentration_cap_bps=10_000))
    assert result.reasons == {
        "P1": SelectionReason.SELECTED_PREFERENCE_PASS,
        "P2": SelectionReason.SELECTED_PREFERENCE_PASS,
        "R1": SelectionReason.SELECTED_RANK_PASS,
        "R2": SelectionReason.CAPACITY_REACHED,
    }
    assert result.warnings == []


def test_concentration_skip_records_reason() -> None:
    ranked = [_inputs("A", strategy="Credit"), _inputs("B", strategy="Credit"), _inputs("C", strategy="Quant")]
    result = build_shortlist(ranked, _mandate(max_candidates=5, strategy_concentration_cap_bps=2000))
    assert result.per_strategy_limit == 1
    assert result.reasons["B"] is SelectionReason.CONCENTRATION_SKIP
    assert "Credit already holds 1 of 1" in result.details["B"]
    assert result.reasons["C"] is SelectionReason.SELECTED_RANK_PASS
    assert result.warnings == []


def test_concentration_floor_warning_when_it_binds() -> None:
    ranked = [_inputs("A", strategy="Credit"), _inputs("B", strategy="Credit")]
    result = build_shortlist(ranked, _mandate(max_candidates=5, strategy_concentration_cap_bps=1000))
    assert result.per_strategy_limit == 1
    assert [warning.code for warning in result.warnings] == ["CONCENTRATION_FLOOR_APPLIED"]
    assert result.reasons["B"] is SelectionReason.CONCENTRATION_SKIP


def test_empty_preferences_mean_pure_rank_order() -> None:
    ranked = [_inputs(f"F{i}", strategy=f"S{i}") for i in range(4)]
    result = build_shortlist(
        ranked, _mandate(preferred_strategies=[], max_candidates=3, strategy_concentration_cap_bps=10_000)
    )
    assert [result.reasons[f"F{i}"] for i in range(4)] == [
        SelectionReason.SELECTED_RANK_PASS,
        SelectionReason.SELECTED_RANK_PASS,
        SelectionReason.SELECTED_RANK_PASS,
        SelectionReason.CAPACITY_REACHED,
    ]
