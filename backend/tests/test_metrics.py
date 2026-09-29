from datetime import date

import pandas as pd
import pytest

from app.services.metrics import (
    annual_rate_to_bps,
    annualized_return,
    annualized_volatility,
    compute_fund_metrics,
    correlation,
    excess_annualized_return,
    max_drawdown,
    risk_free_for_window,
    round_ratio,
    sharpe_ratio,
    to_bps,
)


def _series(values: list[float], start: str = "2023-01-01") -> pd.Series:
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="MS"))


def test_rounding_is_half_away_from_zero_once() -> None:
    assert to_bps(0.00125) == 13
    assert to_bps(-0.00125) == -13
    assert to_bps(0.1) == 1000
    assert annual_rate_to_bps(0.0425) == 425
    assert round_ratio(1.005) == 1.01
    assert round_ratio(-0.125) == -0.13


def test_annualized_return_is_cagr_and_needs_twelve_months() -> None:
    assert annualized_return(_series([0.01] * 12)) == pytest.approx(1.01**12 - 1)
    assert to_bps(annualized_return(_series([0.01] * 12))) == 1268
    assert annualized_return(_series([0.05] * 11)) is None


def test_volatility_is_sample_std_times_root_twelve() -> None:
    assert annualized_volatility(_series([0.02, 0.0, 0.02, 0.0])) == pytest.approx(0.04)
    assert annualized_volatility(_series([0.02])) is None


def test_sharpe_uses_monthly_excess_over_monthly_std() -> None:
    returns = _series([0.02, 0.0, 0.02, 0.0])
    assert sharpe_ratio(returns, 0.0) == pytest.approx(3.0)
    rf_with_half_percent_monthly = 1.005**12 - 1
    assert sharpe_ratio(returns, rf_with_half_percent_monthly) == pytest.approx(1.5)
    assert sharpe_ratio(_series([0.01] * 6), 0.0) is None


def test_max_drawdown_from_wealth_index() -> None:
    assert max_drawdown(_series([0.10, -0.20, 0.05])) == pytest.approx(0.20)
    assert max_drawdown(_series([-0.10, 0.05])) == pytest.approx(0.10)
    assert max_drawdown(_series([0.01, 0.02, 0.03])) == 0.0


def test_gaps_are_not_filled() -> None:
    months = pd.to_datetime([f"2023-{m:02d}-01" for m in range(1, 13)] + ["2024-02-01"])
    returns = pd.Series([0.01] * 13, index=months)
    assert annualized_return(returns) == pytest.approx((1.01**13) ** (12 / 13) - 1)
    assert max_drawdown(pd.Series([0.10, -0.20], index=months[[0, 12]])) == pytest.approx(0.20)


def test_correlation_needs_twelve_overlapping_months() -> None:
    fund = _series([0.01 * (i % 5) for i in range(14)])
    benchmark = _series([0.02 * (i % 5) + 0.001 for i in range(14)])
    value, overlap = correlation(fund, benchmark)
    assert value == pytest.approx(1.0) and overlap == 14

    late = _series([0.02 * (i % 5) for i in range(14)], start="2023-04-01")
    value, overlap = correlation(fund, late)
    assert value is None and overlap == 11


def test_excess_return_over_overlapping_months() -> None:
    fund = _series([0.02] * 14, start="2023-01-01")
    benchmark = _series([0.01] * 12, start="2023-03-01")
    excess, overlap = excess_annualized_return(fund, benchmark)
    assert overlap == 12
    assert excess == pytest.approx((1.02**12 - 1) - (1.01**12 - 1))
    assert to_bps(excess) == 1414

    short, overlap = excess_annualized_return(fund, _series([0.01] * 11, start="2023-01-01"))
    assert short is None and overlap == 11


def test_excess_return_is_unverifiable_without_benchmark() -> None:
    base = {
        "benchmark": "SPY",
        "risk_free_annual": 0.04,
        "risk_free_source": "configured_fallback",
        "target_return_bps": 1000,
    }
    fund = _series([0.02] * 12)
    assert compute_fund_metrics(fund, benchmark_returns=None, **base).excess_return_bps is None
    with_benchmark = compute_fund_metrics(fund, benchmark_returns=_series([0.01] * 12), **base)
    assert with_benchmark.excess_return_bps == 1414


def test_risk_free_uses_window_mean_else_fallback() -> None:
    rates = _series([0.04, 0.05, 0.06], start="2023-01-01")
    assert risk_free_for_window(rates, date(2023, 2, 1), date(2023, 3, 1), 0.01) == (
        pytest.approx(0.055),
        "series_window_mean",
    )
    assert risk_free_for_window(rates, date(2025, 1, 1), date(2025, 6, 1), 0.01) == (
        0.01,
        "configured_fallback",
    )


def test_compute_fund_metrics_rounds_and_reports_target_gap() -> None:
    metrics = compute_fund_metrics(
        _series([0.01] * 12),
        benchmark="SPY",
        benchmark_returns=None,
        risk_free_annual=0.04,
        risk_free_source="configured_fallback",
        target_return_bps=1000,
    )
    assert metrics.months_of_history == 12
    assert metrics.annualized_return_bps == 1268
    assert metrics.target_gap_bps == 268
    assert metrics.sharpe is None
    assert metrics.correlation is None and metrics.benchmark_available is False
    assert metrics.risk_free_annual_bps == 400
    assert metrics.window_start == date(2023, 1, 1) and metrics.window_end == date(2023, 12, 1)

    short = compute_fund_metrics(
        _series([0.01, 0.02] * 5),
        benchmark="SPY",
        benchmark_returns=None,
        risk_free_annual=0.04,
        risk_free_source="configured_fallback",
        target_return_bps=1000,
    )
    assert short.annualized_return_bps is None and short.target_gap_bps is None
    assert short.volatility_bps is not None
