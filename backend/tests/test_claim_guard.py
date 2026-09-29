import pytest

from app.services.claim_guard import GuardContext, guard_memo, stray_digits
from app.services.evidence_registry import EvidenceRecord


def _record(evidence_id: str, record_type: str, fund_id: str | None, status: str = "verified", **provenance):
    return EvidenceRecord(evidence_id, record_type, fund_id, evidence_id, "x", status, provenance)


REGISTRY = {
    r.evidence_id: r
    for r in [
        _record("MET-F007-SHARPE", "metric", "F007"),
        _record("MET-F001-SHARPE", "metric", "F001"),
        _record("SEL-F007-SELECTED-PREFERENCE-PASS", "selection", "F007"),
        _record("SEL-F001-SELECTED-PREFERENCE-PASS", "selection", "F001"),
        _record("SEL-F006-CAPACITY-REACHED", "selection", "F006"),
        _record("DQ-F007-SMOOTH-RETURNS-NET-RETURN", "data_quality", "F007"),
        _record("SRC-F007-NOTES", "source_field", "F007", field="notes"),
        _record("SRC-F009-PERF-FEE-BPS", "source_field", "F009", status="invalid", field="perf_fee_bps"),
        _record("BMK-SPY", "benchmark", None),
    ]
}
SHORTLIST = ["F007", "F001"]
TOKENS = ["F007", "F001", "F006", "F009", "Beacon Steady Income", "Fund 2 Partners"]


FUND_NAMES = {"F007": "Beacon Steady Income", "F001": "Northstar Equity Partners"}


def _context() -> GuardContext:
    return GuardContext(REGISTRY, SHORTLIST, TOKENS, FUND_NAMES)


def _claim(text: str, evidence: list[str], claim_type: str = "qualitative", fund_id: str | None = None,
           section: str = "executive_summary", rationale: str | None = None, claim_id: str = "c-1") -> dict:
    return {
        "claim_id": claim_id,
        "section": section,
        "position": 0,
        "rationale_fund_id": rationale,
        "text": text,
        "evidence_ids": evidence,
        "claim_type": claim_type,
        "fund_id": fund_id,
    }


def _clean_memo() -> list[dict]:
    return [
        _claim("F007 leads with a Sharpe of [[MET-F007-SHARPE]].", ["MET-F007-SHARPE"], "quantitative", "F007"),
        _claim(
            "Advance F007 [[SEL-F007-SELECTED-PREFERENCE-PASS]] only after verifying "
            "[[DQ-F007-SMOOTH-RETURNS-NET-RETURN]] and the disclosures in [[SRC-F007-NOTES]].",
            ["SEL-F007-SELECTED-PREFERENCE-PASS", "DQ-F007-SMOOTH-RETURNS-NET-RETURN", "SRC-F007-NOTES"],
            "judgment", "F007", section="recommendation", claim_id="r-1",
        ),
        _claim("F007 was chosen [[SEL-F007-SELECTED-PREFERENCE-PASS]].", ["SEL-F007-SELECTED-PREFERENCE-PASS"],
               fund_id="F007", section="shortlist_rationale", rationale="F007", claim_id="s-1"),
        _claim("F001 compares with [[BMK-SPY]] at [[MET-F001-SHARPE]], data through May 2026.",
               ["BMK-SPY", "MET-F001-SHARPE"], "quantitative", "F001",
               section="shortlist_rationale", rationale="F001", claim_id="s-2"),
    ]


def _codes(claim: dict) -> list[str]:
    results, _ = guard_memo([claim], _context(), SHORTLIST)
    return [reason["code"] for reason in results[0].reasons]


def test_clean_memo_passes() -> None:
    results, summary = guard_memo(_clean_memo(), _context(), SHORTLIST)
    assert [r.status for r in results] == ["ok"] * 4
    assert summary == {"total": 4, "ok": 4, "flagged": 0, "memo_issues": [], "status": "clean"}


@pytest.mark.parametrize(
    ("claim", "code"),
    [
        (_claim("Sharpe [[MET-F999-SHARPE]].", ["MET-F999-SHARPE"], "quantitative"), "UNKNOWN_EVIDENCE"),
        (_claim("Sharpe [[MET-F007-SHARPE]].", [], "quantitative", "F007"), "MARKER_NOT_CITED"),
        (_claim("Sharpe is high.", ["MET-F007-SHARPE"], "quantitative", "F007"), "CITED_NOT_MARKED"),
        (_claim("Returns are strong.", [], "quantitative"), "QUANTITATIVE_WITHOUT_EVIDENCE"),
        (_claim("Sharpe of 1.42 [[MET-F007-SHARPE]].", ["MET-F007-SHARPE"], "quantitative", "F007"),
         "DIGITS_OUTSIDE_MARKERS"),
        (_claim("F007 vs [[MET-F001-SHARPE]].", ["MET-F001-SHARPE"], "quantitative", "F007"), "CROSS_FUND_EVIDENCE"),
        (_claim("Advance F006 [[SEL-F006-CAPACITY-REACHED]].", ["SEL-F006-CAPACITY-REACHED"], "judgment", "F006",
                section="recommendation"), "NOT_SHORTLISTED_RECOMMENDATION"),
        (_claim("Fee is [[SRC-F009-PERF-FEE-BPS]].", ["SRC-F009-PERF-FEE-BPS"], "quantitative", "F009"),
         "UNVERIFIED_EVIDENCE_AS_FACT"),
        (_claim("Chosen [[SEL-F001-SELECTED-PREFERENCE-PASS]].", ["SEL-F001-SELECTED-PREFERENCE-PASS"], fund_id="F001",
                section="shortlist_rationale", rationale="F007"), "RATIONALE_FUND_MISMATCH"),
    ],
)
def test_each_planted_failure_is_flagged(claim: dict, code: str) -> None:
    assert code in _codes(claim)


def test_flagged_claims_are_kept_verbatim() -> None:
    bad = _claim("Sharpe of 1.42.", [], "quantitative", "F007")
    claims = [*_clean_memo(), bad]
    results, summary = guard_memo(claims, _context(), SHORTLIST)
    assert claims[-1]["text"] == "Sharpe of 1.42."
    assert results[-1].status == "flagged"
    assert summary["flagged"] == 1 and summary["status"] == "flagged"


@pytest.mark.parametrize(
    "text",
    [
        "F007 and F001 differ: [[MET-F007-SHARPE]] versus [[MET-F001-SHARPE]].",
        "Beacon Steady Income leads northstar equity partners: [[MET-F007-SHARPE]] vs [[MET-F001-SHARPE]].",
        "f007 and F001 compared: [[MET-F007-SHARPE]], [[MET-F001-SHARPE]].",
    ],
)
def test_fund_neutral_claim_naming_every_cited_fund_passes(text: str) -> None:
    claim = _claim(text, ["MET-F007-SHARPE", "MET-F001-SHARPE"], "quantitative")
    assert "CITED_FUND_NOT_NAMED" not in _codes(claim)


@pytest.mark.parametrize(
    ("text", "unnamed"),
    [
        ("The leader posts [[MET-F007-SHARPE]] against F001's [[MET-F001-SHARPE]].", "F007"),
        ("Two funds compare at [[MET-F007-SHARPE]] and [[MET-F001-SHARPE]].", "F007, F001"),
        ("F0070 is not F007's ID; see [[MET-F001-SHARPE]] only for F007.", "F001"),
    ],
)
def test_fund_neutral_claim_with_unnamed_cited_fund_is_flagged(text: str, unnamed: str) -> None:
    claim = _claim(text, ["MET-F007-SHARPE", "MET-F001-SHARPE"] if "F007-SHARPE" in text else ["MET-F001-SHARPE"],
                   "quantitative")
    results, _ = guard_memo([claim], _context(), SHORTLIST)
    reason = next(r for r in results[0].reasons if r["code"] == "CITED_FUND_NOT_NAMED")
    assert reason["message"].startswith(f"cited fund not named: {unnamed}.")


def test_fund_scoped_and_benchmark_only_claims_skip_the_naming_rule() -> None:
    assert "CITED_FUND_NOT_NAMED" not in _codes(
        _claim("Its Sharpe is [[MET-F007-SHARPE]].", ["MET-F007-SHARPE"], "quantitative", "F007")
    )
    assert "CITED_FUND_NOT_NAMED" not in _codes(_claim("Benchmark: [[BMK-SPY]].", ["BMK-SPY"]))


def test_benchmark_evidence_is_allowed_for_any_fund_and_qualitative_may_cite_unverified() -> None:
    assert _codes(_claim("F007 vs [[BMK-SPY]].", ["BMK-SPY"], fund_id="F007")) == []
    assert _codes(_claim("F009's fee [[SRC-F009-PERF-FEE-BPS]] could not be verified.",
                         ["SRC-F009-PERF-FEE-BPS"], "qualitative", "F009")) == []


@pytest.mark.parametrize(
    ("text", "stray"),
    [
        ("F007 and Fund 2 Partners reported through May 2026 and Sept 2025.", []),
        ("Sharpe [[MET-F007-SHARPE]] beats 1.2 and 15%.", ["1.2", "15%."]),
        ("Top 3 funds.", ["3"]),
    ],
)
def test_digit_rule(text: str, stray: list[str]) -> None:
    assert stray_digits(text, TOKENS) == stray


def test_rationale_coverage_and_top_fund_concerns_are_memo_issues() -> None:
    memo = [claim for claim in _clean_memo() if claim["section"] != "recommendation"]
    _, summary = guard_memo(memo, _context(), ["F001", "F007"])
    codes = [issue["code"] for issue in summary["memo_issues"]]
    assert codes == ["SHORTLIST_RATIONALE_COVERAGE", "TOP_FUND_DATA_QUALITY_UNADDRESSED"]
    assert summary["flagged"] == 0 and summary["status"] == "flagged"

    without_notes = _clean_memo()
    without_notes[1] = _claim(
        "Advance F007 [[SEL-F007-SELECTED-PREFERENCE-PASS]] after [[DQ-F007-SMOOTH-RETURNS-NET-RETURN]].",
        ["SEL-F007-SELECTED-PREFERENCE-PASS", "DQ-F007-SMOOTH-RETURNS-NET-RETURN"],
        "judgment", "F007", section="recommendation", claim_id="r-1",
    )
    _, summary = guard_memo(without_notes, _context(), SHORTLIST)
    assert [issue["code"] for issue in summary["memo_issues"]] == ["TOP_FUND_DATA_QUALITY_UNADDRESSED"]
