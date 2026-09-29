"""The demo path end to end through the API: upload, mandate, run, memos, immutability.

Yahoo Finance, FRED, and OpenAI are all stubbed; nothing here touches the network.
"""

import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.domain.models import MemoArtifact
from app.services import benchmarks
from tests.test_memos import _install_llm, _mock_llm_draft, _ranked, _response, _sel
from tests.test_ranking_runs import DEFAULT_MANDATE, SAMPLE

SMOOTH_DQ = "DQ-F007-SMOOTH-RETURNS-NET-RETURN"
NOTES_SRC = "SRC-F007-NOTES"


@pytest.fixture
def live_fred(monkeypatch: pytest.MonkeyPatch) -> None:
    rates = pd.Series(0.04, index=pd.date_range("2015-01-01", "2026-08-01", freq="MS"))
    monkeypatch.setattr(settings, "fred_api_key", "fake-fred-key")
    monkeypatch.setattr(benchmarks, "fetch_fred_monthly_rates", lambda key, timeout: rates)


def _issue_funds(issues: list[dict], code: str) -> set[str]:
    return {issue["fund_id"] for issue in issues if issue["code"] == code}


def _snapshot_bytes(db_session: Session, memo_id: str) -> str:
    db_session.expire_all()
    memo = db_session.scalars(select(MemoArtifact).where(MemoArtifact.id == memo_id)).one()
    return json.dumps(memo.evidence_snapshot, sort_keys=True)


def test_demo_flow_end_to_end(
    client: TestClient,
    db_session: Session,
    live_benchmarks: None,
    live_fred: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with SAMPLE.open("rb") as handle:
        upload = client.post("/api/analyses", files={"file": ("sample.csv", handle, "text/csv")})
    assert upload.status_code == 201, upload.text
    analysis = upload.json()
    issues = analysis["issues"]
    assert _issue_funds(issues, "SMOOTH_RETURNS") == {"F007"}
    assert _issue_funds(issues, "RETURN_OUT_OF_RANGE") == {"F009"}
    assert _issue_funds(issues, "FUND_ID_MISMATCH") == {"F001", "F010"}
    assert _issue_funds(issues, "INCONSISTENT_DATE_RANGE") == {"F004"}
    analysis_id = analysis["analysis_id"]

    saved = client.put(f"/api/analyses/{analysis_id}/mandate", json=DEFAULT_MANDATE)
    assert saved.status_code == 201, saved.text
    created = client.post(f"/api/analyses/{analysis_id}/ranking-runs")
    assert created.status_code == 201, created.text
    run = created.json()
    run_id = run["run_id"]

    assert {name: entry["state"] for name, entry in run["benchmark_provenance"].items()} == {
        "SPY": "live", "AGG": "live", "risk_free": "live",
    }
    funds = {fund["fund_id"]: fund for fund in run["funds"]}
    assert {f for f, fund in funds.items() if fund["eligible"]} == {
        "F001", "F002", "F003", "F004", "F006", "F007",
    }
    assert run["summary"]["shortlisted"] == 5
    assert funds["F006"]["selection_reason"] == "CAPACITY_REACHED"

    demoted = [
        _ranked("F004", "MET-F004-SHARPE"),
        _ranked("F001", "MET-F001-SHARPE"),
        _ranked("F007", SMOOTH_DQ, NOTES_SRC),
        _ranked("F003", _sel(run, "F003")),
        _ranked("F002", _sel(run, "F002")),
    ]
    fake = _install_llm(monkeypatch, _response(_mock_llm_draft(run, demoted)))
    llm_post = client.post(f"/api/ranking-runs/{run_id}/memos")
    assert llm_post.status_code == 201, llm_post.text
    llm_memo = llm_post.json()
    assert len(fake.calls) == 1
    assert llm_memo["revision"] == 1 and llm_memo["generation_mode"] == "llm"
    assert llm_memo["guard_summary"]["status"] == "clean", llm_memo["guard_summary"]
    f007 = next(row for row in llm_memo["llm_ranking"]["entries"] if row["fund_id"] == "F007")
    assert (f007["baseline_rank"], f007["llm_rank"], f007["move"]) == (1, 3, "down")
    f007_rationale = next(c for c in llm_memo["claims"] if c["claim_id"] == f007["claim_id"])
    assert SMOOTH_DQ in f007_rationale["evidence_ids"] and f007_rationale["guard_status"] == "ok"
    recommendation = [c for c in llm_memo["claims"] if c["section"] == "recommendation"]
    assert recommendation and all(c["guard_status"] == "ok" for c in recommendation)
    cited = {evidence_id for claim in recommendation for evidence_id in claim["evidence_ids"]}
    assert {SMOOTH_DQ, NOTES_SRC} <= cited

    template_post = client.post(f"/api/ranking-runs/{run_id}/memos", json={"mode": "template"})
    assert template_post.status_code == 201, template_post.text
    template_memo = template_post.json()
    assert template_memo["revision"] == 2
    assert template_memo["generation_mode"] == "template"
    assert template_memo["fallback_reason"] == "template requested"
    assert template_memo["llm_ranking"]["source"] == "baseline"
    assert len(fake.calls) == 1

    # Production requests each get a fresh session; read back from Postgres the same way.
    db_session.expire_all()
    before = {
        "run": client.get(f"/api/ranking-runs/{run_id}").content,
        "evidence": client.get(f"/api/ranking-runs/{run_id}/evidence").content,
        "llm": client.get(f"/api/memos/{llm_memo['memo_id']}").content,
        "template": client.get(f"/api/memos/{template_memo['memo_id']}").content,
    }
    snapshots = {m["memo_id"]: _snapshot_bytes(db_session, m["memo_id"]) for m in (llm_memo, template_memo)}

    changed = client.put(
        f"/api/analyses/{analysis_id}/mandate",
        json={**DEFAULT_MANDATE, "max_candidates": 3, "strategy_concentration_cap_bps": 2000},
    )
    assert changed.status_code == 200, changed.text
    new_run = client.post(f"/api/analyses/{analysis_id}/ranking-runs")
    assert new_run.status_code == 201, new_run.text
    assert new_run.json()["run_id"] != run_id
    assert new_run.json()["mandate_sha256"] != run["mandate_sha256"]
    assert new_run.json()["summary"]["shortlisted"] == 3

    db_session.expire_all()
    after = {
        "run": client.get(f"/api/ranking-runs/{run_id}").content,
        "evidence": client.get(f"/api/ranking-runs/{run_id}/evidence").content,
        "llm": client.get(f"/api/memos/{llm_memo['memo_id']}").content,
        "template": client.get(f"/api/memos/{template_memo['memo_id']}").content,
    }
    assert after == before
    for memo_id, snapshot in snapshots.items():
        assert _snapshot_bytes(db_session, memo_id) == snapshot
