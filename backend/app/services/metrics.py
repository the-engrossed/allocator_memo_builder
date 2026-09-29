"""Pure allocator metrics on monthly net-return series. No HTTP, database, or file access.

Inputs are pandas Series of decimal monthly returns indexed by first-of-month timestamps.
Calculations use floats; values are rounded once, when a FundMetrics is built, with to_bps
(integer basis points) or round_ratio (two decimals). Gaps in a fund's months are never
filled: every metric uses the observed months only.
"""

from dataclasses import asdict, dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from math import isfinite, sqrt

import numpy as np
import pandas as pd

MONTHS_PER_YEAR = 12
MIN_MONTHS_ANNUALIZED_RETURN = 12
MIN_OVERLAP_MONTHS_CORRELATION = 12
# Below this monthly standard deviation a series is treated as constant (float noise, not risk).
NEGLIGIBLE_DEVIATION = 1e-12


def to_bps(value: float) -> int:
    """Decimal fraction to integer basis points, rounding half away from zero."""
    return int((Decimal(str(value)) * 10_000).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_ratio(value: float) -> float:
    """Round a unitless ratio (Sharpe, correlation) to two decimals, half away from zero."""
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def annual_rate_to_bps(rate: float) -> int:
    """The single conversion used for risk-free and other annual rates."""
    return to_bps(rate)


def monthly_rate(annual_rate: float) -> float:
    return (1 + annual_rate) ** (1 / MONTHS_PER_YEAR) - 1


def months_of_history(returns: pd.Series) -> int:
    return int(returns.count())


def annualized_return(returns: pd.Series) -> float | None:
    """CAGR over observed months; unverifiable with fewer than 12 observations."""
    values = _values(returns)
    if len(values) < MIN_MONTHS_ANNUALIZED_RETURN:
        return None
    growth = float(np.prod(1 + values))
    if growth <= 0:
        return -1.0
    return growth ** (MONTHS_PER_YEAR / len(values)) - 1


def annualized_volatility(returns: pd.Series) -> float | None:
    values = _values(returns)
    if len(values) < 2:
        return None
    return float(np.std(values, ddof=1)) * sqrt(MONTHS_PER_YEAR)


def sharpe_ratio(returns: pd.Series, risk_free_annual: float) -> float | None:
    """mean(r_m - rf_m) / std(r_m) * sqrt(12), with rf_m = (1 + rf)^(1/12) - 1."""
    values = _values(returns)
    if len(values) < 2:
        return None
    deviation = float(np.std(values, ddof=1))
    if deviation < NEGLIGIBLE_DEVIATION or not isfinite(deviation):
        return None
    excess = float(np.mean(values - monthly_rate(risk_free_annual)))
    return excess / deviation * sqrt(MONTHS_PER_YEAR)


def max_drawdown(returns: pd.Series) -> float | None:
    """Largest peak-to-trough loss of the wealth index (starting at 1.0), as a positive magnitude."""
    values = _values(returns)
    if len(values) == 0:
        return None
    wealth = np.concatenate(([1.0], np.cumprod(1 + values)))
    peaks = np.maximum.accumulate(wealth)
    return float(np.max(1 - wealth / peaks))


def correlation(returns: pd.Series, benchmark: pd.Series) -> tuple[float | None, int]:
    """Pearson correlation on overlapping months, and the overlap count.

    Unverifiable (None) below 12 overlapping months or when either side has no variance.
    """
    aligned = pd.concat([returns, benchmark], axis=1, join="inner").dropna()
    overlap = len(aligned)
    if overlap < MIN_OVERLAP_MONTHS_CORRELATION:
        return None, overlap
    fund = aligned.iloc[:, 0].to_numpy(dtype=float)
    bench = aligned.iloc[:, 1].to_numpy(dtype=float)
    if np.std(fund) < NEGLIGIBLE_DEVIATION or np.std(bench) < NEGLIGIBLE_DEVIATION:
        return None, overlap
    return float(np.corrcoef(fund, bench)[0, 1]), overlap


def excess_annualized_return(
    returns: pd.Series, benchmark: pd.Series
) -> tuple[float | None, int]:
    """Fund CAGR minus benchmark CAGR over their overlapping months, and the overlap count.

    Unverifiable (None) below 12 overlapping months.
    """
    aligned = pd.concat([returns, benchmark], axis=1, join="inner").dropna()
    overlap = len(aligned)
    if overlap < MIN_OVERLAP_MONTHS_CORRELATION:
        return None, overlap
    fund = annualized_return(aligned.iloc[:, 0])
    bench = annualized_return(aligned.iloc[:, 1])
    if fund is None or bench is None:
        return None, overlap
    return fund - bench, overlap


def risk_free_for_window(
    rates: pd.Series, start: date | None, end: date | None, fallback_annual: float
) -> tuple[float, str]:
    """Mean annual risk-free rate over the fund's window, else the configured fallback."""
    if start is not None and end is not None and not rates.empty:
        window = rates[(rates.index >= pd.Timestamp(start)) & (rates.index <= pd.Timestamp(end))]
        if not window.empty:
            return float(window.mean()), "series_window_mean"
    return fallback_annual, "configured_fallback"


@dataclass(frozen=True)
class FundMetrics:
    months_of_history: int
    window_start: date | None
    window_end: date | None
    annualized_return_bps: int | None
    volatility_bps: int | None
    max_drawdown_bps: int | None
    sharpe: float | None
    correlation: float | None
    correlation_overlap_months: int
    benchmark: str
    benchmark_available: bool
    risk_free_annual_bps: int
    risk_free_source: str
    target_gap_bps: int | None
    excess_return_bps: int | None = None

    def to_json(self) -> dict:
        data = asdict(self)
        data["window_start"] = self.window_start.isoformat() if self.window_start else None
        data["window_end"] = self.window_end.isoformat() if self.window_end else None
        return data


def compute_fund_metrics(
    returns: pd.Series,
    *,
    benchmark: str,
    benchmark_returns: pd.Series | None,
    risk_free_annual: float,
    risk_free_source: str,
    target_return_bps: int,
) -> FundMetrics:
    returns = returns.sort_index()
    cagr = annualized_return(returns)
    volatility = annualized_volatility(returns)
    drawdown = max_drawdown(returns)
    sharpe = sharpe_ratio(returns, risk_free_annual)
    if benchmark_returns is None or benchmark_returns.empty:
        corr, overlap, excess = None, 0, None
    else:
        corr, overlap = correlation(returns, benchmark_returns)
        excess, _ = excess_annualized_return(returns, benchmark_returns)
    return_bps = None if cagr is None else to_bps(cagr)
    return FundMetrics(
        months_of_history=months_of_history(returns),
        window_start=returns.index.min().date() if len(returns) else None,
        window_end=returns.index.max().date() if len(returns) else None,
        annualized_return_bps=return_bps,
        volatility_bps=None if volatility is None else to_bps(volatility),
        max_drawdown_bps=None if drawdown is None else to_bps(drawdown),
        sharpe=None if sharpe is None else round_ratio(sharpe),
        correlation=None if corr is None else round_ratio(corr),
        correlation_overlap_months=overlap,
        benchmark=benchmark,
        benchmark_available=benchmark_returns is not None and not benchmark_returns.empty,
        risk_free_annual_bps=annual_rate_to_bps(risk_free_annual),
        risk_free_source=risk_free_source,
        target_gap_bps=None if return_bps is None else return_bps - target_return_bps,
        excess_return_bps=None if excess is None else to_bps(excess),
    )


def _values(returns: pd.Series) -> np.ndarray:
    return returns.dropna().to_numpy(dtype=float)
