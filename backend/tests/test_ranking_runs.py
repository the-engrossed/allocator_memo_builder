import uuid
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.seed.sample_data import FUNDS, fund_returns
from app.services import benchmarks
from app.services.ranking_runs import _data_quality

SAMPLE = Path(__file__).resolve().parents[2] / "sample_data" / "sample_fund_universe.csv"

DEFAULT_MANDATE = {
    "target_return_bps": 1000,
    "max_mgmt_fee_bps": 200,
    "max_perf_fee_bps": 2000,
    "max_notice_days": 90,
    "max_lockup_months": 12,
    "min_liquidity_frequency": "quarterly",
    "max_volatility_bps": 1500,
    "max_drawdown_bps": 2000,
    "min_track_record_months": 36,
    "preferred_strategies": ["Macro", "Equity L/S", "Credit"],
    "excluded_strategies": [],
    "strategy_concentration_cap_bps": 4000,
    "max_candidates": 5,
}
ELIGIBLE = {"F001", "F002", "F003", "F004", "F006", "F007"}
EXCLUDED = {"F005", "F008", "F009", "F010"}
SELECTED = {"SELECTED_PREFERENCE_PASS", "SELECTED_RANK_PASS"}


def _sample_analysis(client: TestClient, **mandate_overrides: object) -> str:
    with SAMPLE.open("rb") as handle:
        upload = client.post("/api/analyses", files={"file": ("sample.csv", handle, "text/csv")})
    assert upload.status_code == 201, upload.text
    analysis_id = upload.json()["analysis_id"]
    saved = client.put(
        f"/api/analyses/{analysis_id}/mandate", json={**DEFAULT_MANDATE, **mandate_overrides}
    )
    assert saved.status_code == 201, saved.text
    return analysis_id


def _post_run(client: TestClient, analysis_id: str) -> dict:
    response = client.post(f"/api/analyses/{analysis_id}/ranking-runs")
    assert response.status_code == 201, response.text
    return response.json()


def _funds(body: dict) -> dict[str, dict]:
    return {fund["fund_id"]: fund for fund in body["funds"]}


def _failed(fund: dict) -> set[str]:
    return {screen["screen"] for screen in fund["screens"] if screen["result"] != "pass"}


def _generator_risk_bps(fund_id: str) -> tuple[int, int]:
    """(max drawdown, annualized vol) in bps from the generator, on the rows the CSV emits."""
    spec = next(spec for spec in FUNDS if spec.fund_id == fund_id)
    dropped = spec.skip_months | set(spec.raw_returns) | set(spec.raw_periods)
    values = np.array(
        [v for month, v in fund_returns(spec) if month.strftime("%Y-%m") not in dropped]
    )
    wealth = np.concatenate(([1.0], np.cumprod(1 + values)))
    drawdown = float(np.max(1 - wealth / np.maximum.accumulate(wealth)))
    volatility = float(np.std(values, ddof=1)) * np.sqrt(12)
    return round(drawdown * 10_000), round(volatility * 10_000)


def test_sample_upload_reports_common_window(client: TestClient) -> None:
    with SAMPLE.open("rb") as handle:
        body = client.post(
            "/api/analyses", files={"file": ("sample.csv", handle, "text/csv")}
        ).json()
    assert body["common_window"] == {
        "start": "2022-09-01",
        "end": "2026-05-01",
        "months": 45,
        "fund_count": 8,
    }
    assert not any(issue["code"] == "COMMON_WINDOW_SHORT" for issue in body["issues"])


def test_data_quality_ids_include_field_and_suffix_repeats_in_row_order() -> None:
    def issue(code: str, field: str | None, rows: list[int], severity: str = "warning"):
        return SimpleNamespace(
            code=code, field=field, row_numbers=rows, severity=severity, message=code
        )

    entries = _data_quality(
        "F001",
        [
            issue("MISSING_MONTHS", "period", [40]),
            issue("CONFLICTING_METADATA", None, [1, 2]),
            issue("MISSING_MONTHS", "period", [10]),
            issue("RETURN_UNIT_INFERRED", "net_return", [1], severity="info"),
        ],
    )
    assert [(entry["evidence_id"], entry["row_numbers"]) for entry in entries] == [
        ("DQ-F001-CONFLICTING-METADATA", [1, 2]),
        ("DQ-F001-MISSING-MONTHS-PERIOD", [10]),
        ("DQ-F001-MISSING-MONTHS-PERIOD-2", [40]),
    ]


def test_notes_input_is_missing_when_empty(client: TestClient, live_benchmarks: None) -> None:
    funds = _funds(_post_run(client, _sample_analysis(client)))
    assert all(fund["inputs"]["notes"]["status"] == "verified" for fund in funds.values())
    empty = {"raw": "", "value": "", "status": "missing"}
    header = "fund_id,fund_name,strategy,period,net_return,liquidity_frequency,notice_days,"
    header += "lockup_months,mgmt_fee_bps,perf_fee_bps,notes\n"
    rows = "".join(f"X1,Solo,Macro,2024-{m:02d},0.01,monthly,30,0,100,2000,\n" for m in range(1, 13))
    upload = client.post(
        "/api/analyses", files={"file": ("solo.csv", (header + rows).encode(), "text/csv")}
    )
    analysis_id = upload.json()["analysis_id"]
    client.put(f"/api/analyses/{analysis_id}/mandate", json=DEFAULT_MANDATE)
    solo = _funds(_post_run(client, analysis_id))["X1"]["inputs"]["notes"]
    assert {key: solo[key] for key in empty} == empty


def test_missing_analysis_is_plain_404(client: TestClient) -> None:
    missing = uuid.uuid4()
    for response in (
        client.post(f"/api/analyses/{missing}/ranking-runs"),
        client.get(f"/api/analyses/{missing}/ranking-runs/latest"),
        client.get(f"/api/ranking-runs/{missing}"),
        client.get(f"/api/analyses/{missing}/mandate"),
    ):
        assert response.status_code == 404
        assert isinstance(response.json()["detail"], str)


def test_missing_mandate_is_409_and_no_run_is_coded_404(
    client: TestClient, analysis_id: uuid.UUID
) -> None:
    latest = client.get(f"/api/analyses/{analysis_id}/ranking-runs/latest")
    assert latest.status_code == 404
    assert latest.json()["detail"] == {
        "code": "NO_RANKING_RUN",
        "message": f"Analysis {analysis_id} has no ranking runs yet.",
    }
    mandate = client.get(f"/api/analyses/{analysis_id}/mandate")
    assert mandate.status_code == 404 and mandate.json()["detail"]["code"] == "NO_MANDATE"

    response = client.post(f"/api/analyses/{analysis_id}/ranking-runs")
    assert response.status_code == 409
    assert "no saved mandate" in response.json()["detail"]


def test_sample_universe_end_to_end(client: TestClient, live_benchmarks: None) -> None:
    analysis_id = _sample_analysis(client)
    body = _post_run(client, analysis_id)
    funds = _funds(body)

    assert {f for f, fund in funds.items() if fund["eligible"]} == ELIGIBLE
    assert {f for f, fund in funds.items() if not fund["eligible"]} == EXCLUDED
    assert _failed(funds["F005"]) == {"LIQUIDITY", "LOCKUP"}
    assert _failed(funds["F008"]) == {"TRACK-RECORD"}
    assert _failed(funds["F010"]) == {"TRACK-RECORD"}
    assert "BLOCKING-VALIDATION" in _failed(funds["F009"])
    assert "SCR-F005-LOCKUP-FAIL" in funds["F005"]["evidence_ids"]

    blocked = funds["F009"]["metrics"]
    assert blocked["sharpe"] is None and blocked["metric_evidence"] == {}
    assert set(blocked["unverifiable_reasons"].values()) == {
        "Fund blocked by validation: RETURN_OUT_OF_RANGE"
    }
    assert "months_of_history" in blocked["unverifiable_reasons"]
    short = funds["F008"]["metrics"]
    assert short["unverifiable_reasons"] == {
        "annualized_return_bps": "11 months of history; 12 required",
        "target_gap_bps": "Annualized return unverifiable: 11 months of history; 12 required",
        "correlation": "11 overlapping months with SPY; 12 required",
        "excess_return_bps": "11 overlapping months with SPY; 12 required",
    }
    assert funds["F001"]["metrics"]["unverifiable_reasons"] == {}
    assert funds["F001"]["metrics"]["metric_evidence"]["sharpe"] == "MET-F001-SHARPE"
    assert funds["F002"]["metrics"]["metric_evidence"]["correlation"] == "MET-F002-CORRELATION-AGG"
    for fund_id, fund in funds.items():
        metrics = fund["metrics"]
        assert set(metrics["metric_evidence"].values()) <= set(fund["evidence_ids"]), fund_id
        for name, value in metrics.items():
            if name in metrics["metric_evidence"]:
                assert value is not None, (fund_id, name)
        for name in metrics["unverifiable_reasons"]:
            assert metrics[name] is None, (fund_id, name)
            assert name not in metrics["metric_evidence"], (fund_id, name)

    assert [d["code"] for d in funds["F007"]["data_quality"]] == ["SMOOTH_RETURNS"]
    assert "DQ-F007-SMOOTH-RETURNS-NET-RETURN" in funds["F007"]["evidence_ids"]
    assert "DQ-F001-FUND-ID-MISMATCH-FUND-ID" in funds["F001"]["evidence_ids"]
    assert "DQ-F001-CONFLICTING-METADATA" in funds["F001"]["evidence_ids"]
    assert "DQ-F004-INCONSISTENT-DATE-RANGE-PERIOD" in funds["F004"]["evidence_ids"]
    for fund_id, fund in funds.items():
        ids = fund["evidence_ids"]
        assert len(ids) == len(set(ids)), f"{fund_id} has duplicate evidence ids"

    notes = funds["F007"]["inputs"]["notes"]
    assert notes["evidence_id"] == "SRC-F007-NOTES" and notes["status"] == "verified"
    assert notes["value"] == notes["raw"] and "No down month" in notes["raw"]
    assert notes["source_row"] == funds["F007"]["inputs"]["fund_name"]["source_row"]
    assert "SRC-F007-NOTES" in funds["F007"]["evidence_ids"]
    assert not any("NOTES" in screen["code"] for screen in funds["F007"]["screens"])
    assert not any(
        d["code"] == "SMOOTH_RETURNS" for f, fund in funds.items() if f != "F007"
        for d in fund["data_quality"]
    )

    for fund_id in ("F001", "F002", "F003", "F004", "F005", "F006", "F007", "F008"):
        metrics = funds[fund_id]["metrics"]
        expected_drawdown, expected_volatility = _generator_risk_bps(fund_id)
        assert abs(metrics["max_drawdown_bps"] - expected_drawdown) <= 5, fund_id
        assert abs(metrics["volatility_bps"] - expected_volatility) <= 5, fund_id
    for fund_id in ("F003", "F006"):
        assert funds[fund_id]["metrics"]["max_drawdown_bps"] <= DEFAULT_MANDATE["max_drawdown_bps"]

    provenance = body["benchmark_provenance"]
    assert provenance["SPY"]["state"] == provenance["AGG"]["state"] == "live"
    assert provenance["SPY"]["coverage_end"] == "2026-08-01"
    assert provenance["risk_free"]["state"] == "fallback"
    assert funds["F002"]["benchmark"] == "AGG" and funds["F001"]["benchmark"] == "SPY"
    assert funds["F001"]["metrics"]["correlation"] is not None
    assert funds["F001"]["metrics"]["excess_return_bps"] is not None
    assert "MET-F001-EXCESS-VS-SPY" in funds["F001"]["evidence_ids"]
    assert "MET-F002-EXCESS-VS-AGG" in funds["F002"]["evidence_ids"]
    assert funds["F010"]["metrics"]["excess_return_bps"] is None
    assert not any("EXCESS" in name for name in funds["F001"]["score_components"])

    ranks = sorted(fund["rank"] for fund in funds.values() if fund["eligible"])
    assert ranks == list(range(1, 7))
    assert body["summary"] == {"evaluated": 10, "eligible": 6, "excluded": 4, "shortlisted": 5}
    assert body["warnings"] == []
    reasons = [fund["selection_reason"] for fund in body["funds"] if fund["eligible"]]
    assert reasons.count("CAPACITY_REACHED") == 1
    assert body["score_weights"] == {
        "sharpe": 45, "annualized_return": 25, "drawdown_resilience": 20, "low_correlation": 10,
    }

    assert client.get(f"/api/analyses/{analysis_id}/ranking-runs/latest").json() == body
    assert client.get(f"/api/ranking-runs/{body['run_id']}").json() == body


def test_tight_concentration_cap_skips_one_credit_fund(
    client: TestClient, live_benchmarks: None
) -> None:
    analysis_id = _sample_analysis(client, strategy_concentration_cap_bps=2000, max_candidates=5)
    funds = _funds(_post_run(client, analysis_id))
    credit_reasons = sorted(funds[f]["selection_reason"] for f in ("F002", "F007"))
    assert credit_reasons[0] == "CONCENTRATION_SKIP"
    assert credit_reasons[1] in SELECTED
    assert "Credit already holds 1 of 1" in next(
        funds[f]["selection_detail"] for f in ("F002", "F007")
        if funds[f]["selection_reason"] == "CONCENTRATION_SKIP"
    )
    shortlisted = {f for f, fund in funds.items() if fund["selection_reason"] in SELECTED}
    assert len(shortlisted) == 5


def test_run_is_immutable_after_mandate_put(client: TestClient, live_benchmarks: None) -> None:
    analysis_id = _sample_analysis(client)
    first = _post_run(client, analysis_id)

    changed = client.put(
        f"/api/analyses/{analysis_id}/mandate", json={**DEFAULT_MANDATE, "max_lockup_months": 24}
    )
    assert changed.status_code == 200
    assert client.get(f"/api/ranking-runs/{first['run_id']}").json() == first

    second = _post_run(client, analysis_id)
    assert second["run_id"] != first["run_id"]
    assert second["mandate_sha256"] != first["mandate_sha256"]
    assert second["mandate_snapshot"]["max_lockup_months"] == 24
    assert first["mandate_snapshot"]["max_lockup_months"] == 12
    assert "LOCKUP" not in _failed(_funds(second)["F005"])
    assert client.get(f"/api/analyses/{analysis_id}/ranking-runs/latest").json()["run_id"] == (
        second["run_id"]
    )


def test_fred_api_key_never_reaches_the_ranking_run_response(
    client: TestClient, live_benchmarks: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import settings
    from tests.test_benchmarks import REAL_FETCH_FRED, _leaky_fred_error

    monkeypatch.setattr(settings, "fred_api_key", "SECRET123")
    monkeypatch.setattr(benchmarks, "fetch_fred_monthly_rates", REAL_FETCH_FRED)
    monkeypatch.setattr(benchmarks.httpx, "get", _leaky_fred_error)

    analysis_id = _sample_analysis(client)
    response = client.post(f"/api/analyses/{analysis_id}/ranking-runs")
    assert response.status_code == 201
    assert response.json()["benchmark_provenance"]["risk_free"]["message"].startswith(
        "Live fetch failed: HTTP 400."
    )
    assert "SECRET123" not in response.text
    assert "SECRET123" not in client.get(f"/api/analyses/{analysis_id}/ranking-runs/latest").text


def test_health_reports_only_booleans(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "fred_api_key", "SECRET123")
    monkeypatch.setattr(settings, "openai_api_key", "sk-SECRET456")
    response = client.get("/api/health")
    assert response.json() == {
        "status": "ok", "db": True, "openai_configured": True, "fred_configured": True,
    }
    assert "SECRET" not in response.text


def test_unavailable_benchmarks_zero_correlation_for_all(client: TestClient) -> None:
    analysis_id = _sample_analysis(client)
    body = _post_run(client, analysis_id)
    assert body["benchmark_provenance"]["SPY"]["state"] == "unavailable"
    assert [warning["code"] for warning in body["warnings"]] == ["BENCHMARK_UNAVAILABLE"]
    for fund in body["funds"]:
        if fund["eligible"]:
            component = fund["score_components"]["low_correlation"]
            assert component["points"] == 0 and component["flag"] == "benchmark_unavailable"
            benchmark = fund["benchmark"]
            assert fund["metrics"]["unverifiable_reasons"]["correlation"] == (
                f"Benchmark {benchmark} unavailable for this run"
            )
