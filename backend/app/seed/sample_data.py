"""Deterministic generator for sample_data/sample_fund_universe.csv.

Run from backend/:  python -m app.seed.sample_data [output_path]

Returns are synthetic: a shared equity-like market path plus per-fund alpha, beta, seeded noise,
and scripted shock months. Nothing here is real fund or index data. The generator also plants
the demo cases the screens and validation are meant to catch:

- F003 reports bare percentage points while every other bare-numeric fund reports decimals.
- F003 and F006 pass a 20% drawdown cap narrowly (about 18.6% and 18.4%).
- F005 fails the liquidity and lockup screens (semiannual redemptions, 24-month lockup).
- F006 has one unparseable return; F004 skips a month; F001 has one conflicting notice period.
- F007 is suspiciously smooth (SMOOTH_RETURNS): no down month and near-zero volatility.
- F008 has only 11 months of history (short-history warning, fails a 36-month minimum).
- F009 breaches volatility and drawdown caps, has a non-integer performance fee, one invalid
  period, and one monthly return above the 50% sanity bound, which blocks it from analysis.
"""

import csv
import random
import sys
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date
from math import sqrt
from pathlib import Path

HEADER = (
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

FIRST_MONTH = date(2021, 9, 1)

# Synthetic monthly market path, Sep 2021 through Aug 2026 (60 months).
MARKET: tuple[float, ...] = (
    -0.047, 0.069, -0.008, 0.044,
    -0.053, -0.031, 0.036, -0.088, 0.000, -0.084, 0.091, -0.042, -0.093, 0.080, 0.054, -0.059,
    0.062, -0.026, 0.035, 0.015, 0.002, 0.065, 0.031, -0.018, -0.049, -0.022, 0.091, 0.044,
    0.016, 0.052, 0.031, -0.042, 0.048, 0.035, 0.011, 0.023, 0.020, -0.010, 0.057, -0.025,
    0.027, -0.014, -0.058, -0.008, 0.062, 0.050, 0.022, 0.019, 0.035, 0.023, 0.002, 0.001,
    -0.015, 0.012, -0.030, 0.024, 0.031, -0.022, 0.018, 0.009,
)


@dataclass(frozen=True)
class FundSpec:
    fund_id: str
    fund_name: str
    strategy: str
    liquidity_frequency: str
    notice_days: str
    lockup_months: str
    mgmt_fee_bps: str
    perf_fee_bps: str
    notes: str
    start_month: date
    alpha: float
    beta: float
    sigma: float
    seed: int
    period_format: str
    return_format: str = "decimal"
    floor: float | None = None
    cap: float = 0.45
    shocks: dict[str, float] = field(default_factory=dict)
    raw_returns: dict[str, str] = field(default_factory=dict)
    raw_periods: dict[str, str] = field(default_factory=dict)
    skip_months: frozenset[str] = frozenset()
    overrides: dict[str, dict[str, str]] = field(default_factory=dict)


FUNDS: tuple[FundSpec, ...] = (
    FundSpec(
        fund_id="F001",
        fund_name="Northstar Equity Partners",
        strategy="Equity L/S",
        liquidity_frequency="monthly",
        notice_days="30",
        lockup_months="12",
        mgmt_fee_bps="150",
        perf_fee_bps="2000",
        notes="Fundamental long/short; net exposure 30-60%.",
        start_month=date(2021, 9, 1),
        alpha=0.0050,
        beta=0.70,
        sigma=0.014,
        seed=101,
        period_format="%Y-%m",
        overrides={"2024-06": {"notice_days": "45"}},
    ),
    FundSpec(
        fund_id="F002",
        fund_name="Harbor Credit Opportunities",
        strategy="Credit",
        liquidity_frequency="quarterly",
        notice_days="60",
        lockup_months="12",
        mgmt_fee_bps="125",
        perf_fee_bps="1500",
        notes="Performing and stressed corporate credit; gates at 25% per quarter.",
        start_month=date(2022, 9, 1),
        alpha=0.0055,
        beta=0.18,
        sigma=0.008,
        seed=202,
        period_format="%b-%Y",
        return_format="percent_string",
        shocks={"2025-03": -0.030, "2025-04": -0.022},
    ),
    FundSpec(
        fund_id="F003",
        fund_name="Cedar Global Macro",
        strategy="Macro",
        liquidity_frequency="Monthly",
        notice_days="5",
        lockup_months="0",
        mgmt_fee_bps="200",
        perf_fee_bps="2000",
        notes="Discretionary rates and FX; reports returns in percentage points.",
        start_month=date(2021, 9, 1),
        alpha=0.0065,
        beta=-0.10,
        sigma=0.026,
        seed=303,
        period_format="%m/%Y",
        return_format="bare_percent",
        shocks={"2023-03": -0.025, "2023-04": -0.020, "2023-05": -0.015},
    ),
    FundSpec(
        fund_id="F004",
        fund_name="Pinnacle Multi-Strategy",
        strategy="Multi-strategy",
        liquidity_frequency="quarterly",
        notice_days="90",
        lockup_months="12",
        mgmt_fee_bps="175",
        perf_fee_bps="2000",
        notes="Pod-based platform; pass-through expenses not included in the fee.",
        start_month=date(2022, 3, 1),
        alpha=0.0060,
        beta=0.25,
        sigma=0.008,
        seed=404,
        period_format="month_end",
        skip_months=frozenset({"2024-02"}),
    ),
    FundSpec(
        fund_id="F005",
        fund_name="Summit Event Driven",
        strategy="Event-driven",
        liquidity_frequency="Semi-Annual",
        notice_days="90",
        lockup_months="24",
        mgmt_fee_bps="150",
        perf_fee_bps="2000",
        notes="Merger arbitrage and special situations; 24-month hard lockup.",
        start_month=date(2021, 9, 1),
        alpha=0.0055,
        beta=0.30,
        sigma=0.011,
        seed=505,
        period_format="%Y-%m",
        shocks={"2022-06": -0.030},
    ),
    FundSpec(
        fund_id="F006",
        fund_name="Atlas Systematic",
        strategy="Quant",
        liquidity_frequency="monthly",
        notice_days="15",
        lockup_months="0",
        mgmt_fee_bps="100",
        perf_fee_bps="1750",
        notes="Systematic multi-asset trend and carry.",
        start_month=date(2021, 9, 1),
        alpha=0.0090,
        beta=0.10,
        sigma=0.028,
        seed=606,
        period_format="%b %Y",
        shocks={"2024-07": -0.050, "2024-08": -0.040, "2024-09": -0.030},
        raw_returns={"2023-11": "n/a"},
    ),
    FundSpec(
        fund_id="F007",
        fund_name="Beacon Steady Income",
        strategy="Credit",
        liquidity_frequency="monthly",
        notice_days="30",
        lockup_months="0",
        mgmt_fee_bps="100",
        perf_fee_bps="2000",
        notes=(
            "No down month since inception. Returns calculated by the manager's affiliated "
            "administrator; auditor is a two-partner local firm."
        ),
        start_month=date(2021, 9, 1),
        alpha=0.0085,
        beta=0.0,
        sigma=0.0012,
        seed=707,
        period_format="%Y-%m",
        floor=0.0060,
    ),
    FundSpec(
        fund_id="F008",
        fund_name="Juniper Emerging Leaders",
        strategy="Equity L/S",
        liquidity_frequency="monthly",
        notice_days="30",
        lockup_months="0",
        mgmt_fee_bps="150",
        perf_fee_bps="2000",
        notes="Launched October 2025; spun out of a large long-only manager.",
        start_month=date(2025, 10, 1),
        alpha=0.0120,
        beta=0.60,
        sigma=0.020,
        seed=808,
        period_format="%Y-%m",
    ),
    FundSpec(
        fund_id="F009",
        fund_name="Vector Digital Assets",
        strategy="Crypto",
        liquidity_frequency="monthly",
        notice_days="1",
        lockup_months="0",
        mgmt_fee_bps="200",
        perf_fee_bps="20%",
        notes="Liquid tokens and basis trades; custody with a single exchange.",
        start_month=date(2022, 3, 1),
        alpha=0.010,
        beta=1.5,
        sigma=0.14,
        seed=909,
        period_format="%Y-%m",
        shocks={"2022-05": -0.30, "2022-06": -0.35, "2022-11": -0.22},
        raw_returns={"2024-03": "0.62"},
        raw_periods={"2023-09": "2023-13"},
    ),
)


def generate_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for spec in FUNDS:
        rows.extend(_fund_rows(spec))
    return rows


def write_csv(path: Path) -> list[dict[str, str]]:
    rows = generate_rows()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADER, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return rows


def fund_returns(spec: FundSpec) -> list[tuple[date, float]]:
    """The fund's clean monthly return path before formatting and planted defects."""
    rng = random.Random(spec.seed)
    series: list[tuple[date, float]] = []
    for index, market in enumerate(MARKET):
        month = _add_months(FIRST_MONTH, index)
        noise = rng.gauss(0.0, spec.sigma)
        if month < spec.start_month:
            continue
        value = spec.alpha + spec.beta * market + noise + spec.shocks.get(_key(month), 0.0)
        if spec.floor is not None:
            value = max(value, spec.floor)
        series.append((month, max(-spec.cap, min(spec.cap, round(value, 4)))))
    return series


def _fund_rows(spec: FundSpec) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for month, value in fund_returns(spec):
        key = _key(month)
        if key in spec.skip_months:
            continue
        row = {
            "fund_id": spec.fund_id,
            "fund_name": spec.fund_name,
            "strategy": spec.strategy,
            "period": spec.raw_periods.get(key, _format_period(month, spec.period_format)),
            "net_return": spec.raw_returns.get(key, _format_return(value, spec.return_format)),
            "liquidity_frequency": spec.liquidity_frequency,
            "notice_days": spec.notice_days,
            "lockup_months": spec.lockup_months,
            "mgmt_fee_bps": spec.mgmt_fee_bps,
            "perf_fee_bps": spec.perf_fee_bps,
            "notes": spec.notes,
        }
        row.update(spec.overrides.get(key, {}))
        rows.append(row)
    return rows


def _format_period(month: date, period_format: str) -> str:
    if period_format == "month_end":
        return date(month.year, month.month, monthrange(month.year, month.month)[1]).isoformat()
    return month.strftime(period_format)


def _format_return(value: float, return_format: str) -> str:
    if return_format == "percent_string":
        return f"{value * 100:.2f}%"
    if return_format == "bare_percent":
        return f"{value * 100:.2f}"
    return f"{value:.4f}"


def _add_months(start: date, months: int) -> date:
    total = start.year * 12 + start.month - 1 + months
    return date(total // 12, total % 12 + 1, 1)


def _key(month: date) -> str:
    return month.strftime("%Y-%m")


def _summary(spec: FundSpec) -> str:
    values = [value for _, value in fund_returns(spec)]
    months = len(values)
    growth = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for value in values:
        growth *= 1 + value
        peak = max(peak, growth)
        max_drawdown = max(max_drawdown, 1 - growth / peak)
    mean = sum(values) / months
    volatility = sqrt(sum((v - mean) ** 2 for v in values) / (months - 1)) * sqrt(12)
    cagr = growth ** (12 / months) - 1
    return (
        f"{spec.fund_id} {spec.strategy:<15} months={months:>2} cagr={cagr:6.1%} "
        f"vol={volatility:6.1%} max_dd={max_drawdown:6.1%}"
    )


def main(argv: list[str]) -> None:
    default = Path(__file__).resolve().parents[3] / "sample_data" / "sample_fund_universe.csv"
    output = Path(argv[1]) if len(argv) > 1 else default
    rows = write_csv(output)
    print(f"Wrote {len(rows)} rows to {output}")
    for spec in FUNDS:
        print("  " + _summary(spec))


if __name__ == "__main__":
    main(sys.argv)
