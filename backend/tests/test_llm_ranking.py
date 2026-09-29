"""The LLM's proposed ranked shortlist: persisted vs the baseline and checked by the guard."""

import pytest
from fastapi.testclient import TestClient

from app.domain.schemas import MemoDraft, RankedFund
from tests.test_memos import SELECTED, _install_llm, _mock_llm_draft, _ranked, _response, _sample_run, _sel

SMOOTH_DQ = "DQ-F007-SMOOTH-RETURNS-NET-RETURN"
NOTES_SRC = "SRC-F007-NOTES"


def _baseline(run: dict) -> list[str]:
    return [f["fund_id"] for f in run["funds"] if f["selection_reason"] in SELECTED]


def _post(client: TestClient, monkeypatch: pytest.MonkeyPatch, run: dict, draft: MemoDraft) -> dict:
    _install_llm(monkeypatch, _response(draft))
    response = client.post(f"/api/ranking-runs/{run['run_id']}/memos")
    assert response.status_code == 201, response.text
    return response.json()


def _codes(memo: dict) -> set[str]:
    return {issue["code"] for issue in memo["guard_summary"]["memo_issues"]}


def _kept(run: dict, fund_id: str) -> RankedFund:
    return _ranked(fund_id, _sel(run, fund_id))


def _moved(fund_id: str) -> RankedFund:
    return _ranked(fund_id, f"MET-{fund_id}-SHARPE")


@pytest.fixture
def run(client: TestClient, live_benchmarks: None) -> dict:
    sample = _sample_run(client)
    assert _baseline(sample) == ["F007", "F004", "F001", "F003", "F002"]
    return sample


def test_cited_reorder_passes_and_is_stored_against_the_baseline(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, run: dict
) -> None:
    ranking = [
        _moved("F004"),
        _moved("F001"),
        _ranked("F007", SMOOTH_DQ, NOTES_SRC),
        _kept(run, "F003"),
        _kept(run, "F002"),
    ]
    memo = _post(client, monkeypatch, run, _mock_llm_draft(run, ranking))

    assert memo["guard_summary"]["status"] == "clean", memo["guard_summary"]
    stored = memo["llm_ranking"]
    assert stored["source"] == "llm" and stored["dropped"] == []
    rows = {row["fund_id"]: row for row in stored["entries"]}
    assert [row["fund_id"] for row in stored["entries"]] == ["F004", "F001", "F007", "F003", "F002"]
    f007 = rows["F007"]
    assert (f007["baseline_position"], f007["llm_rank"], f007["delta"], f007["move"]) == (1, 3, -2, "down")
    assert (rows["F004"]["delta"], rows["F004"]["move"]) == (1, "up")
    assert (rows["F003"]["delta"], rows["F003"]["move"]) == (0, "same")
    assert rows["F007"]["baseline_rank"] == 1
    claims = {c["claim_id"]: c for c in memo["claims"]}
    assert claims[rows["F007"]["claim_id"]]["section"] == "llm_ranking"
    assert claims[rows["F007"]["claim_id"]]["evidence_ids"] == [SMOOTH_DQ, NOTES_SRC]


def test_ineligible_fund_is_flagged(client: TestClient, monkeypatch: pytest.MonkeyPatch, run: dict) -> None:
    base = _baseline(run)
    ranking = [*(_kept(run, f) for f in base[:4]), _ranked("F005", "SRC-F005-LOCKUP-MONTHS")]
    memo = _post(client, monkeypatch, run, _mock_llm_draft(run, ranking, [_moved("F002")]))
    assert _codes(memo) == {"LLM_RANK_INELIGIBLE_FUND"}
    assert memo["llm_ranking"]["entries"][4]["eligible"] is False


def test_duplicate_fund_is_flagged(client: TestClient, monkeypatch: pytest.MonkeyPatch, run: dict) -> None:
    base = _baseline(run)
    ranking = [*(_kept(run, f) for f in base[:4]), _moved("F004")]
    memo = _post(client, monkeypatch, run, _mock_llm_draft(run, ranking, [_moved("F002")]))
    assert _codes(memo) == {"LLM_RANK_DUPLICATE"}


def test_over_capacity_is_flagged(client: TestClient, monkeypatch: pytest.MonkeyPatch, run: dict) -> None:
    ranking = [*(_kept(run, f) for f in _baseline(run)), _moved("F006")]
    memo = _post(client, monkeypatch, run, _mock_llm_draft(run, ranking))
    assert _codes(memo) == {"LLM_RANK_OVER_CAPACITY"}


def test_strategy_concentration_is_flagged(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, live_benchmarks: None
) -> None:
    run = _sample_run(client, strategy_concentration_cap_bps=2000)
    base = _baseline(run)
    skipped = next(f["fund_id"] for f in run["funds"] if f["selection_reason"] == "CONCENTRATION_SKIP")
    ranking = [*(_kept(run, f) for f in base[:-1]), _moved(skipped)]
    memo = _post(client, monkeypatch, run, _mock_llm_draft(run, ranking, [_moved(base[-1])]))
    assert _codes(memo) == {"LLM_RANK_CONCENTRATION"}


def test_uncited_move_is_flagged(client: TestClient, monkeypatch: pytest.MonkeyPatch, run: dict) -> None:
    ranking = [
        _ranked("F004", "DQ-F004-MISSING-MONTHS-PERIOD"),
        _ranked("F001", "DQ-F001-CONFLICTING-METADATA"),
        _kept(run, "F007"),
        _kept(run, "F003"),
        _kept(run, "F002"),
    ]
    memo = _post(client, monkeypatch, run, _mock_llm_draft(run, ranking))
    assert _codes(memo) == {"LLM_RANK_MOVE_UNCITED"}
    assert memo["guard_summary"]["memo_issues"][0]["message"].endswith(": F007.")


def test_pure_metric_swap_of_clean_funds_is_flagged(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, run: dict
) -> None:
    ranking = [
        *(_kept(run, f) for f in ("F007", "F004", "F001")),
        _ranked("F002", "MET-F002-SHARPE", "MET-F002-MAX-DRAWDOWN"),
        _ranked("F003", "MET-F003-ANNUALIZED-RETURN", "MET-F003-CORRELATION-SPY"),
    ]
    memo = _post(client, monkeypatch, run, _mock_llm_draft(run, ranking))
    assert _codes(memo) == {"LLM_RANK_REWEIGHTS_SCORE"}
    assert memo["guard_summary"]["memo_issues"][0]["message"].endswith(": F002 above F003.")


def test_promotion_citing_only_screen_passes_is_flagged(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, run: dict
) -> None:
    ranking = [
        _ranked("F003", "SCR-F003-NOTICE-PASS", "SCR-F003-LOCKUP-PASS"),
        *(_kept(run, f) for f in ("F007", "F004", "F001")),
        _kept(run, "F002"),
    ]
    memo = _post(client, monkeypatch, run, _mock_llm_draft(run, ranking))
    assert _codes(memo) == {"LLM_RANK_MOVE_UNCITED", "LLM_RANK_REWEIGHTS_SCORE"}
    issues = {i["code"]: i["message"] for i in memo["guard_summary"]["memo_issues"]}
    assert issues["LLM_RANK_MOVE_UNCITED"].endswith(": F003, F007, F004, F001.")
    assert "F003 above F007" in issues["LLM_RANK_REWEIGHTS_SCORE"]


def test_non_score_metric_justifies_a_swap(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, run: dict
) -> None:
    ranking = [
        *(_kept(run, f) for f in ("F007", "F004", "F001")),
        _ranked("F002", "MET-F002-SHARPE", "MET-F002-TARGET-GAP"),
        _moved("F003"),
    ]
    memo = _post(client, monkeypatch, run, _mock_llm_draft(run, ranking))
    assert _codes(memo) == set(), memo["guard_summary"]


def test_revision_five_shape_passes(client: TestClient, monkeypatch: pytest.MonkeyPatch, run: dict) -> None:
    """F003 promoted on metrics alone is allowed because every fund it passes cites DQ evidence."""
    ranking = [
        _ranked("F003", "MET-F003-CORRELATION-SPY", "MET-F003-ANNUALIZED-RETURN", "MET-F003-MAX-DRAWDOWN"),
        _ranked("F001", "MET-F001-ANNUALIZED-RETURN", "DQ-F001-CONFLICTING-METADATA"),
        _ranked("F004", "DQ-F004-INCONSISTENT-DATE-RANGE-PERIOD", "DQ-F004-MISSING-MONTHS-PERIOD"),
        _ranked("F002", "MET-F002-MAX-DRAWDOWN", "MET-F002-TARGET-GAP", "SRC-F002-NOTES"),
        _ranked("F007", SMOOTH_DQ, NOTES_SRC),
    ]
    memo = _post(client, monkeypatch, run, _mock_llm_draft(run, ranking))
    assert memo["guard_summary"]["status"] == "clean", memo["guard_summary"]


def test_drop_without_a_cited_entry_is_flagged(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, run: dict
) -> None:
    ranking = [_kept(run, f) for f in _baseline(run)[:4]]
    memo = _post(client, monkeypatch, run, _mock_llm_draft(run, ranking))
    assert _codes(memo) == {"LLM_RANK_MOVE_UNCITED"}
    dropped = memo["llm_ranking"]["dropped"]
    assert [(row["fund_id"], row["move"], row["claim_id"]) for row in dropped] == [("F002", "dropped", None)]


def test_recommendations_follow_the_llm_ranking(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, run: dict
) -> None:
    ranking = [*(_kept(run, f) for f in _baseline(run)[:4]), _moved("F006")]
    draft = _mock_llm_draft(run, ranking, [_moved("F002")], recommend=["F006", "F002"])
    memo = _post(client, monkeypatch, run, draft)
    flagged = {c["fund_id"]: c["guard_reasons"] for c in memo["claims"] if c["guard_status"] == "flagged"}
    assert list(flagged) == ["F002"]
    assert [r["code"] for r in flagged["F002"]] == ["NOT_SHORTLISTED_RECOMMENDATION"]
    assert _codes(memo) == set()
    assert [row["move"] for row in memo["llm_ranking"]["entries"]][-1] == "new"


def test_dropped_top_fund_addresses_its_data_quality_in_the_drop_rationale(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, run: dict
) -> None:
    ranking = [_moved("F004"), _moved("F001"), _moved("F003"), _moved("F002"), _moved("F006")]
    dropped = [_ranked("F007", SMOOTH_DQ, NOTES_SRC)]
    memo = _post(client, monkeypatch, run, _mock_llm_draft(run, ranking, dropped, recommend_top=False))
    assert memo["guard_summary"]["status"] == "clean", memo["guard_summary"]
    assert memo["llm_ranking"]["dropped"][0]["fund_id"] == "F007"


def test_invalid_drop_entry_is_flagged(client: TestClient, monkeypatch: pytest.MonkeyPatch, run: dict) -> None:
    memo = _post(client, monkeypatch, run, _mock_llm_draft(run, llm_dropped=[_moved("F006")]))
    assert _codes(memo) == {"LLM_RANK_INVALID_DROP"}
    assert memo["llm_ranking"]["dropped"][0]["move"] == "invalid_drop"


def test_template_memo_uses_the_baseline_order(client: TestClient, run: dict) -> None:
    memo = client.post(f"/api/ranking-runs/{run['run_id']}/memos", json={"mode": "template"}).json()
    stored = memo["llm_ranking"]
    assert stored["source"] == "baseline"
    assert [row["fund_id"] for row in stored["entries"]] == _baseline(run)
    assert {row["move"] for row in stored["entries"]} == {"same"} and stored["dropped"] == []
    assert memo["guard_summary"]["status"] == "clean", memo["guard_summary"]
