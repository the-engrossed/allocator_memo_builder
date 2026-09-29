import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.models import MemoArtifact
from scripts import guard_demo
from tests.test_memos import _sample_run

EXPECTED = {
    "planted-1-stray-digit": {"DIGITS_OUTSIDE_MARKERS", "QUANTITATIVE_WITHOUT_EVIDENCE"},
    "planted-2-unknown-evidence": {"UNKNOWN_EVIDENCE"},
    "planted-3-cross-fund": {"CROSS_FUND_EVIDENCE"},
    "planted-4-not-shortlisted": {"NOT_SHORTLISTED_RECOMMENDATION"},
}


def _stored(db_session: Session) -> tuple[int, str]:
    db_session.expire_all()
    memos = db_session.scalars(select(MemoArtifact).order_by(MemoArtifact.id)).all()
    state = [(m.claims, m.guard_results, m.guard_summary, m.evidence_snapshot) for m in memos]
    return db_session.scalar(select(func.count()).select_from(MemoArtifact)), json.dumps(state, sort_keys=True)


def test_guard_demo_flags_every_planted_claim_and_writes_nothing(
    client: TestClient,
    db_session: Session,
    live_benchmarks: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run = _sample_run(client)
    memo = client.post(f"/api/ranking-runs/{run['run_id']}/memos", json={"mode": "template"})
    assert memo.status_code == 201, memo.text
    assert memo.json()["guard_summary"]["status"] == "clean"
    before = _stored(db_session)

    result = guard_demo.run_guard_demo(db_session, uuid.UUID(run["run_id"]))
    assert {claim["claim_id"]: {r["code"] for r in res.reasons} for claim, res in result.planted} == EXPECTED
    assert result.original_summary["status"] == "clean"
    assert result.summary["status"] == "flagged"
    assert result.summary["flagged"] == len(EXPECTED)
    assert result.summary["total"] == result.original_summary["total"] + len(EXPECTED)
    assert not db_session.new and not db_session.dirty
    assert _stored(db_session) == before

    monkeypatch.setattr(guard_demo, "SessionLocal", lambda: db_session)
    assert guard_demo.main(["--run", run["run_id"]]) == 0
    output = capsys.readouterr().out
    assert "Planted claims flagged: 4 of 4" in output
    assert "Read-only: nothing was written." in output
    assert _stored(db_session) == before


def test_guard_demo_reports_a_run_without_memos(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = _sample_run(client)
    monkeypatch.setattr(guard_demo, "SessionLocal", lambda: db_session)
    assert guard_demo.main(["--run", run["run_id"]]) == 1
    assert "has no memo" in capsys.readouterr().err
