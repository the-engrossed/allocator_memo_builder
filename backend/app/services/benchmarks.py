"""Benchmark and risk-free series with explicit provenance. Nothing is ever interpolated or invented.

Benchmarks (SPY, AGG): a cache younger than 24 hours is used as-is ("cached"); otherwise live
yfinance ("live") -> any cached copy ("cached") -> committed snapshot ("fallback") -> "unavailable".
Risk-free (FRED DGS3MO, needs FRED_API_KEY): fresh cache -> live -> stale cache -> the configured
rf_fallback_annual ("fallback").

Daily adjusted closes are resampled to the last close of each calendar month, keyed by the
first of the month, and the current (partial) month is dropped.
"""

import csv
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pandas as pd

from app.config import settings
from app.domain.enums import SeriesState
from app.services.metrics import annual_rate_to_bps

BENCHMARK_TICKERS: tuple[str, ...] = ("SPY", "AGG")
DEFAULT_BENCHMARK = "SPY"
# Casefolded strategy -> benchmark ticker; every other strategy maps to DEFAULT_BENCHMARK.
BENCHMARK_BY_STRATEGY: dict[str, str] = {"credit": "AGG"}

CACHE_MAX_AGE = timedelta(hours=24)
HISTORY_START = "2015-01-01"
FRED_SERIES_ID = "DGS3MO"
FRED_URL = "https://api.stlouisfed.org/fred/series/observations"


_SECRET_QUERY_PARAM = re.compile(r"(?i)\b(api_key|apikey|access_token|token)=[^&\s'\"]*")


class MarketDataError(RuntimeError):
    """Raised with messages written in this module; they never contain request URLs."""


def redact_secrets(text: str) -> str:
    """Replace the value of any api_key/token query parameter with REDACTED."""
    return _SECRET_QUERY_PARAM.sub(lambda match: f"{match.group(1)}=REDACTED", text)


def failure_reason(exc: BaseException) -> str:
    """A short, URL-free description of a failed fetch, safe to persist and return."""
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        return "timeout"
    if isinstance(exc, MarketDataError):
        return redact_secrets(str(exc))
    return type(exc).__name__


@dataclass(frozen=True)
class SeriesProvenance:
    provider: str
    series_id: str
    state: SeriesState
    retrieved_at: datetime | None
    coverage_start: date | None
    coverage_end: date | None
    message: str

    def to_json(self) -> dict:
        return {
            "provider": self.provider,
            "series_id": self.series_id,
            "state": self.state.value,
            "retrieved_at": self.retrieved_at.isoformat() if self.retrieved_at else None,
            "coverage_start": self.coverage_start.isoformat() if self.coverage_start else None,
            "coverage_end": self.coverage_end.isoformat() if self.coverage_end else None,
            "message": redact_secrets(self.message),
        }


@dataclass(frozen=True)
class ResolvedSeries:
    """values: benchmark monthly returns, or risk-free annual rates, keyed by first of month."""

    values: pd.Series
    provenance: SeriesProvenance

    @property
    def available(self) -> bool:
        return self.provenance.state is not SeriesState.UNAVAILABLE and not self.values.empty


@dataclass(frozen=True)
class MarketData:
    benchmarks: dict[str, ResolvedSeries]
    risk_free: ResolvedSeries
    risk_free_fallback_annual: float

    def provenance_json(self) -> dict:
        data = {ticker: series.provenance.to_json() for ticker, series in self.benchmarks.items()}
        data["risk_free"] = {
            **self.risk_free.provenance.to_json(),
            "fallback_annual_bps": annual_rate_to_bps(self.risk_free_fallback_annual),
        }
        return data


def benchmark_for_strategy(strategy: str) -> str:
    return BENCHMARK_BY_STRATEGY.get(strategy.strip().casefold(), DEFAULT_BENCHMARK)


def fetch_yahoo_daily_closes(ticker: str, timeout: float) -> pd.Series:
    """Daily adjusted closes from Yahoo Finance. Raises MarketDataError when nothing comes back."""
    import yfinance as yf

    frame = yf.Ticker(ticker).history(
        start=HISTORY_START, auto_adjust=True, timeout=timeout, raise_errors=True
    )
    if frame is None or frame.empty or "Close" not in frame:
        raise MarketDataError(f"Yahoo Finance returned no prices for {ticker}.")
    closes = frame["Close"].dropna()
    index = pd.DatetimeIndex(closes.index)
    closes.index = index.tz_localize(None) if index.tz is not None else index
    return closes


def fetch_fred_monthly_rates(api_key: str, timeout: float) -> pd.Series:
    """Monthly average DGS3MO yields as annual decimal rates, keyed by first of month."""
    response = httpx.get(
        FRED_URL,
        params={
            "series_id": FRED_SERIES_ID,
            "api_key": api_key,
            "file_type": "json",
            "frequency": "m",
            "aggregation_method": "avg",
            "observation_start": HISTORY_START,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    points = {
        pd.Timestamp(item["date"]): float(item["value"]) / 100
        for item in response.json().get("observations", [])
        if item.get("value") not in (None, "", ".")
    }
    if not points:
        raise MarketDataError("FRED returned no DGS3MO observations.")
    return pd.Series(points).sort_index()


def month_end_closes(daily: pd.Series, today: date) -> pd.Series:
    """Last close of each calendar month, keyed by first of month, excluding the current month."""
    if daily.empty:
        return daily
    series = daily.sort_index()
    series.index = pd.DatetimeIndex(series.index)
    monthly = series.resample("ME").last().dropna()
    monthly.index = monthly.index.to_period("M").to_timestamp()
    return _drop_current_month(monthly, today)


def monthly_returns(closes: pd.Series) -> pd.Series:
    """Month-over-month returns; a month whose prior month is missing gets no return."""
    closes = closes.sort_index()
    months = list(closes.index)
    prices = closes.to_numpy(dtype=float)
    returns: dict[pd.Timestamp, float] = {}
    for index in range(1, len(months)):
        if months[index].to_period("M") - 1 == months[index - 1].to_period("M"):
            returns[months[index]] = prices[index] / prices[index - 1] - 1
    return pd.Series(returns, dtype=float)


def resolve_benchmark(
    ticker: str,
    *,
    today: date,
    now: datetime,
    cache_dir: Path,
    snapshot_dir: Path,
    timeout: float,
) -> ResolvedSeries:
    cached = _read_cache(cache_dir, "yfinance", ticker)
    if cached is not None and now - cached[1] < CACHE_MAX_AGE:
        return _benchmark_series(
            ticker, _drop_current_month(cached[0], today), SeriesState.CACHED, cached[1],
            "Cache is less than 24 hours old; live fetch skipped.",
        )

    try:
        closes = month_end_closes(fetch_yahoo_daily_closes(ticker, timeout), today)
        if len(closes) < 2:
            raise MarketDataError(f"Yahoo Finance returned too little history for {ticker}.")
    except Exception as exc:  # yfinance and its HTTP stack raise many exception types
        failure = f"Live fetch failed: {failure_reason(exc)}."
    else:
        _write_cache(cache_dir, "yfinance", ticker, closes, now)
        return _benchmark_series(ticker, closes, SeriesState.LIVE, now, "Fetched from Yahoo Finance.")

    if cached is not None:
        return _benchmark_series(
            ticker, _drop_current_month(cached[0], today), SeriesState.CACHED, cached[1],
            f"{failure} Using the last cached copy.",
        )
    snapshot = _read_snapshot(snapshot_dir, ticker)
    if snapshot is not None:
        return _benchmark_series(
            ticker, _drop_current_month(snapshot[0], today), SeriesState.FALLBACK, snapshot[1],
            f"{failure} Using the committed snapshot.",
        )
    return ResolvedSeries(
        values=pd.Series(dtype=float),
        provenance=SeriesProvenance(
            provider="yfinance",
            series_id=ticker,
            state=SeriesState.UNAVAILABLE,
            retrieved_at=None,
            coverage_start=None,
            coverage_end=None,
            message=f"{failure} No cache or snapshot is available.",
        ),
    )


def resolve_risk_free(
    *,
    today: date,
    now: datetime,
    cache_dir: Path,
    api_key: str,
    fallback_annual: float,
    timeout: float,
) -> ResolvedSeries:
    cached = _read_cache(cache_dir, "fred", FRED_SERIES_ID)
    if cached is not None and now - cached[1] < CACHE_MAX_AGE:
        return _rate_series(
            _drop_current_month(cached[0], today), SeriesState.CACHED, cached[1],
            "Cache is less than 24 hours old; live fetch skipped.",
        )

    failure = "FRED_API_KEY is not set."
    if api_key:
        try:
            rates = _drop_current_month(fetch_fred_monthly_rates(api_key, timeout), today)
            if rates.empty:
                raise MarketDataError("FRED returned no complete months.")
        except Exception as exc:  # httpx, JSON, and HTTP status errors
            failure = f"Live fetch failed: {failure_reason(exc)}."
        else:
            _write_cache(cache_dir, "fred", FRED_SERIES_ID, rates, now)
            return _rate_series(rates, SeriesState.LIVE, now, "Fetched from FRED.")

    if cached is not None:
        return _rate_series(
            _drop_current_month(cached[0], today), SeriesState.CACHED, cached[1],
            f"{failure} Using the last cached copy.",
        )
    return ResolvedSeries(
        values=pd.Series(dtype=float),
        provenance=SeriesProvenance(
            provider="config",
            series_id="RF_FALLBACK_ANNUAL",
            state=SeriesState.FALLBACK,
            retrieved_at=None,
            coverage_start=None,
            coverage_end=None,
            message=(
                f"{failure} Using the configured fallback of "
                f"{annual_rate_to_bps(fallback_annual)} bps."
            ),
        ),
    )


def resolve_market_data(*, today: date | None = None, now: datetime | None = None) -> MarketData:
    now = now or datetime.now(timezone.utc)
    today = today or now.date()
    benchmarks = {
        ticker: resolve_benchmark(
            ticker,
            today=today,
            now=now,
            cache_dir=settings.benchmark_cache_dir,
            snapshot_dir=settings.benchmark_snapshot_dir,
            timeout=settings.market_data_timeout_seconds,
        )
        for ticker in BENCHMARK_TICKERS
    }
    risk_free = resolve_risk_free(
        today=today,
        now=now,
        cache_dir=settings.benchmark_cache_dir,
        api_key=settings.fred_api_key,
        fallback_annual=settings.rf_fallback_annual,
        timeout=settings.market_data_timeout_seconds,
    )
    return MarketData(benchmarks, risk_free, settings.rf_fallback_annual)


def write_snapshot(snapshot_dir: Path, ticker: str, closes: pd.Series, retrieved_at: datetime) -> Path:
    """Write month-end adjusted closes as the committed fallback CSV for one ticker."""
    path = snapshot_dir / f"benchmark_fallback_{ticker.lower()}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["month", "adj_close", "retrieved_at", "provider", "ticker"])
        for month, close in closes.sort_index().items():
            writer.writerow(
                [month.date().isoformat(), f"{close:.6f}", retrieved_at.isoformat(), "yfinance", ticker]
            )
    return path


def _benchmark_series(
    ticker: str, closes: pd.Series, state: SeriesState, retrieved_at: datetime, message: str
) -> ResolvedSeries:
    returns = monthly_returns(closes)
    return ResolvedSeries(
        values=returns,
        provenance=SeriesProvenance(
            provider="yfinance",
            series_id=ticker,
            state=state if not returns.empty else SeriesState.UNAVAILABLE,
            retrieved_at=retrieved_at,
            coverage_start=returns.index.min().date() if not returns.empty else None,
            coverage_end=returns.index.max().date() if not returns.empty else None,
            message=message,
        ),
    )


def _rate_series(
    rates: pd.Series, state: SeriesState, retrieved_at: datetime, message: str
) -> ResolvedSeries:
    return ResolvedSeries(
        values=rates,
        provenance=SeriesProvenance(
            provider="fred",
            series_id=FRED_SERIES_ID,
            state=state,
            retrieved_at=retrieved_at,
            coverage_start=rates.index.min().date() if not rates.empty else None,
            coverage_end=rates.index.max().date() if not rates.empty else None,
            message=message,
        ),
    )


def _drop_current_month(series: pd.Series, today: date) -> pd.Series:
    return series[series.index < pd.Timestamp(today.year, today.month, 1)]


def _cache_path(cache_dir: Path, provider: str, series_id: str) -> Path:
    return cache_dir / f"{provider}_{series_id.lower()}.json"


def _write_cache(
    cache_dir: Path, provider: str, series_id: str, values: pd.Series, retrieved_at: datetime
) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "provider": provider,
        "series_id": series_id,
        "retrieved_at": retrieved_at.isoformat(),
        "points": [[month.date().isoformat(), float(value)] for month, value in values.items()],
    }
    _cache_path(cache_dir, provider, series_id).write_text(json.dumps(payload), encoding="utf-8")


def _read_cache(
    cache_dir: Path, provider: str, series_id: str
) -> tuple[pd.Series, datetime] | None:
    path = _cache_path(cache_dir, provider, series_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        values = pd.Series(
            {pd.Timestamp(month): float(value) for month, value in payload["points"]}
        ).sort_index()
        retrieved_at = datetime.fromisoformat(payload["retrieved_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return (values, retrieved_at) if not values.empty else None


def _read_snapshot(snapshot_dir: Path, ticker: str) -> tuple[pd.Series, datetime] | None:
    path = snapshot_dir / f"benchmark_fallback_{ticker.lower()}.csv"
    if not path.exists() or path.stat().st_size == 0:
        return None
    try:
        with path.open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        values = pd.Series(
            {pd.Timestamp(row["month"]): float(row["adj_close"]) for row in rows}
        ).sort_index()
        retrieved_at = datetime.fromisoformat(rows[0]["retrieved_at"])
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return None
    return (values, retrieved_at) if not values.empty else None
