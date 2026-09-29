import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pandas as pd
import pytest

from app.domain.enums import SeriesState
from app.services import benchmarks
from app.services.benchmarks import (
    FRED_URL,
    benchmark_for_strategy,
    failure_reason,
    month_end_closes,
    monthly_returns,
    redact_secrets,
    resolve_benchmark,
    resolve_risk_free,
    write_snapshot,
)

# Captured at import, before the autouse offline fixture replaces it.
REAL_FETCH_FRED = benchmarks.fetch_fred_monthly_rates

TODAY = date(2026, 9, 28)
NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)


def _daily(prices: dict[str, float]) -> pd.Series:
    return pd.Series(list(prices.values()), index=pd.to_datetime(list(prices)), dtype=float)


DAILY = _daily(
    {
        "2026-06-15": 90.0,
        "2026-06-30": 100.0,
        "2026-07-31": 110.0,
        "2026-08-14": 120.0,
        "2026-08-31": 99.0,
        "2026-09-25": 150.0,
    }
)


def _resolve(tmp_path: Path, **overrides: object):
    kwargs = {
        "today": TODAY,
        "now": NOW,
        "cache_dir": tmp_path / "cache",
        "snapshot_dir": tmp_path / "snapshot",
        "timeout": 10.0,
    }
    kwargs.update(overrides)
    return resolve_benchmark("SPY", **kwargs)


def test_month_end_resample_drops_the_current_partial_month() -> None:
    closes = month_end_closes(DAILY, TODAY)
    assert list(closes.index) == list(pd.to_datetime(["2026-06-01", "2026-07-01", "2026-08-01"]))
    assert list(closes) == [100.0, 110.0, 99.0]
    returns = monthly_returns(closes)
    assert returns.round(4).tolist() == [0.1, -0.1]
    assert returns.index[0] == pd.Timestamp("2026-07-01")


def test_monthly_returns_skip_months_without_a_prior_close() -> None:
    closes = pd.Series([100.0, 110.0, 121.0], index=pd.to_datetime(["2026-01-01", "2026-02-01", "2026-04-01"]))
    assert list(monthly_returns(closes).index) == [pd.Timestamp("2026-02-01")]


def test_live_fetch_writes_cache_with_retrieved_at(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(benchmarks, "fetch_yahoo_daily_closes", lambda ticker, timeout: DAILY)
    series = _resolve(tmp_path)
    assert series.provenance.state is SeriesState.LIVE
    assert series.provenance.coverage_end == date(2026, 8, 1)
    cache = json.loads((tmp_path / "cache" / "yfinance_spy.json").read_text())
    assert cache["retrieved_at"] == NOW.isoformat()
    assert cache["series_id"] == "SPY"


def test_fresh_cache_skips_live_and_stale_cache_prefers_live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(benchmarks, "fetch_yahoo_daily_closes", lambda ticker, timeout: DAILY)
    _resolve(tmp_path)

    def _must_not_be_called(*_args: object) -> pd.Series:
        raise AssertionError("fresh cache should skip the live fetch")

    monkeypatch.setattr(benchmarks, "fetch_yahoo_daily_closes", _must_not_be_called)
    fresh = _resolve(tmp_path, now=NOW + timedelta(hours=23))
    assert fresh.provenance.state is SeriesState.CACHED
    assert fresh.provenance.retrieved_at == NOW

    monkeypatch.setattr(benchmarks, "fetch_yahoo_daily_closes", lambda ticker, timeout: DAILY)
    stale_now = NOW + timedelta(hours=25)
    refreshed = _resolve(tmp_path, now=stale_now)
    assert refreshed.provenance.state is SeriesState.LIVE
    assert refreshed.provenance.retrieved_at == stale_now


def test_stale_cache_is_used_when_live_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(benchmarks, "fetch_yahoo_daily_closes", lambda ticker, timeout: DAILY)
    _resolve(tmp_path)
    monkeypatch.setattr(
        benchmarks,
        "fetch_yahoo_daily_closes",
        lambda ticker, timeout: (_ for _ in ()).throw(TimeoutError("timed out")),
    )
    series = _resolve(tmp_path, now=NOW + timedelta(days=3))
    assert series.provenance.state is SeriesState.CACHED
    assert series.provenance.message.startswith("Live fetch failed: timeout.")
    assert series.values.round(4).tolist() == [0.1, -0.1]


def test_snapshot_then_unavailable_when_live_and_cache_fail(tmp_path: Path) -> None:
    unavailable = _resolve(tmp_path)
    assert unavailable.provenance.state is SeriesState.UNAVAILABLE
    assert unavailable.values.empty and not unavailable.available

    (tmp_path / "snapshot").mkdir()
    (tmp_path / "snapshot" / "benchmark_fallback_spy.csv").write_text("")
    assert _resolve(tmp_path).provenance.state is SeriesState.UNAVAILABLE

    write_snapshot(tmp_path / "snapshot", "SPY", month_end_closes(DAILY, TODAY), NOW)
    fallback = _resolve(tmp_path)
    assert fallback.provenance.state is SeriesState.FALLBACK
    assert fallback.provenance.retrieved_at == NOW
    assert fallback.values.round(4).tolist() == [0.1, -0.1]


def test_risk_free_resolution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    common = {"today": TODAY, "now": NOW, "cache_dir": tmp_path, "fallback_annual": 0.04, "timeout": 10.0}
    no_key = resolve_risk_free(api_key="", **common)
    assert no_key.provenance.state is SeriesState.FALLBACK
    assert no_key.provenance.provider == "config" and "400 bps" in no_key.provenance.message

    failing = resolve_risk_free(api_key="key", **common)
    assert failing.provenance.state is SeriesState.FALLBACK
    assert "Live fetch failed" in failing.provenance.message

    rates = pd.Series([0.05, 0.051, 0.049], index=pd.to_datetime(["2026-07-01", "2026-08-01", "2026-09-01"]))
    monkeypatch.setattr(benchmarks, "fetch_fred_monthly_rates", lambda key, timeout: rates)
    live = resolve_risk_free(api_key="key", **common)
    assert live.provenance.state is SeriesState.LIVE
    assert live.values.index.max() == pd.Timestamp("2026-08-01")


def _leaky_fred_error(*_args: object, **_kwargs: object) -> None:
    request = httpx.Request("GET", f"{FRED_URL}?series_id=DGS3MO&api_key=SECRET123&file_type=json")
    response = httpx.Response(400, request=request)
    raise httpx.HTTPStatusError(
        f"Client error '400 Bad Request' for url '{request.url}'", request=request, response=response
    )


def test_fred_failure_never_exposes_the_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(benchmarks, "fetch_fred_monthly_rates", REAL_FETCH_FRED)
    monkeypatch.setattr(benchmarks.httpx, "get", _leaky_fred_error)
    resolved = resolve_risk_free(
        today=TODAY, now=NOW, cache_dir=tmp_path, api_key="SECRET123",
        fallback_annual=0.04, timeout=10.0,
    )
    assert resolved.provenance.state is SeriesState.FALLBACK
    assert resolved.provenance.message.startswith("Live fetch failed: HTTP 400.")
    assert "SECRET123" not in json.dumps(resolved.provenance.to_json())


@pytest.mark.parametrize(
    ("exc", "reason"),
    [
        (httpx.ReadTimeout("read timed out for https://x?api_key=SECRET123"), "timeout"),
        (TimeoutError("slow"), "timeout"),
        (ValueError("bad json from https://x?api_key=SECRET123"), "ValueError"),
        (benchmarks.MarketDataError("no rows"), "no rows"),
    ],
)
def test_failure_reason_is_url_free(exc: BaseException, reason: str) -> None:
    assert failure_reason(exc) == reason


def test_redact_secrets() -> None:
    text = "GET https://h/p?series_id=X&api_key=SECRET123&token=abc Api_Key=zzz"
    redacted = redact_secrets(text)
    assert "SECRET123" not in redacted and "abc" not in redacted and "zzz" not in redacted
    assert "api_key=REDACTED" in redacted and "series_id=X" in redacted


@pytest.mark.parametrize(
    ("strategy", "ticker"),
    [("Credit", "AGG"), (" credit ", "AGG"), ("Macro", "SPY"), ("Equity L/S", "SPY"), ("", "SPY")],
)
def test_strategy_benchmark_mapping(strategy: str, ticker: str) -> None:
    assert benchmark_for_strategy(strategy) == ticker
