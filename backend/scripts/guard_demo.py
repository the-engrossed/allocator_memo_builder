"""Plant four bad claims in the latest memo for a run and show the claim guard catching them.

Run from backend/:  python -m scripts.guard_demo --run <ranking_run_id>

Read-only: the memo's own claims and evidence_snapshot are loaded, the planted claims are
appended in memory, and guard_memo runs exactly as it does during generation. Nothing is
written; the session is rolled back.
"""

import argparse
import sys
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.domain.models import MemoArtifact
from app.services.claim_guard import ClaimResult, GuardContext, guard_memo
from app.services.evidence_registry import EvidenceRecord
from app.services.memo_generator import build_context
from app.services.ranking_runs import get_ranking_run

PLANTED = [
    {
        "claim_id": "planted-1-stray-digit",
        "section": "shortlist_rationale",
        "text": "F007 has a Sharpe of 15.6",
        "evidence_ids": [],
        "claim_type": "quantitative",
        "fund_id": "F007",
    },
    {
        "claim_id": "planted-2-unknown-evidence",
        "section": "shortlist_rationale",
        "text": "F007 generates alpha of [[MET-F007-ALPHA]].",
        "evidence_ids": ["MET-F007-ALPHA"],
        "claim_type": "quantitative",
        "fund_id": "F007",
    },
    {
        "claim_id": "planted-3-cross-fund",
        "section": "shortlist_rationale",
        "text": "F001 posts a Sharpe of [[MET-F007-SHARPE]].",
        "evidence_ids": ["MET-F007-SHARPE"],
        "claim_type": "quantitative",
        "fund_id": "F001",
    },
    {
        "claim_id": "planted-4-not-shortlisted",
        "section": "recommendation",
        "text": "Recommend F005 for allocation; its lockup is [[SRC-F005-LOCKUP-MONTHS]].",
        "evidence_ids": ["SRC-F005-LOCKUP-MONTHS"],
        "claim_type": "judgment",
        "fund_id": "F005",
    },
]


class NoMemoError(LookupError):
    pass


@dataclass
class DemoResult:
    memo: MemoArtifact
    planted: list[tuple[dict, ClaimResult]]
    original_summary: dict
    summary: dict


def run_guard_demo(session: Session, run_id: uuid.UUID) -> DemoResult:
    run = get_ranking_run(session, run_id)
    memo = session.scalar(
        select(MemoArtifact)
        .where(MemoArtifact.ranking_run_id == run_id)
        .order_by(MemoArtifact.revision.desc())
        .limit(1)
    )
    if memo is None:
        raise NoMemoError(f"Ranking run {run_id} has no memo; generate one first.")

    registry = {record["evidence_id"]: EvidenceRecord(**record) for record in memo.evidence_snapshot}
    context = build_context(run, registry)
    planted = [
        {**claim, "position": index, "rationale_fund_id": None}
        for index, claim in enumerate(PLANTED)
    ]
    claims = [*(dict(claim) for claim in memo.claims), *planted]
    def section_funds(section: str) -> list[str]:
        return [c["rationale_fund_id"] for c in memo.claims if c["section"] == section]

    has_ranking = memo.llm_ranking is not None
    results, summary = guard_memo(
        claims,
        GuardContext(
            registry,
            context.shortlist_ids,
            context.allowed_tokens(),
            {fund.fund_id: fund.fund_name for fund in run.evaluations},
            context.ranking_limits(),
        ),
        list(dict.fromkeys(section_funds("shortlist_rationale"))),
        section_funds("llm_ranking") if has_ranking else None,
        section_funds("llm_dropped") if has_ranking else None,
    )
    by_id = {result.claim_id: result for result in results}
    return DemoResult(
        memo=memo,
        planted=[(claim, by_id[claim["claim_id"]]) for claim in planted],
        original_summary=dict(memo.guard_summary),
        summary=summary,
    )


def format_report(result: DemoResult) -> str:
    memo = result.memo
    lines = [
        f"Memo {memo.id} · revision {memo.revision} · {memo.generation_mode}"
        + (f" ({memo.model})" if memo.model else ""),
        f"Stored guard summary: {_summary_line(result.original_summary)}",
        "",
        f"{'planted claim':<28} {'fund':<5} {'status':<8} reasons",
        "-" * 100,
    ]
    for claim, claim_result in result.planted:
        lines.append(f"{claim['claim_id']:<28} {claim['fund_id']:<5} {claim_result.status:<8} {claim['text']}")
        for reason in claim_result.reasons:
            lines.append(f"{'':<43} {reason['code']}: {reason['message']}")
    caught = sum(1 for _, claim_result in result.planted if claim_result.status == "flagged")
    lines += [
        "-" * 100,
        f"Planted claims flagged: {caught} of {len(result.planted)}",
        f"Guard summary with planted claims: {_summary_line(result.summary)}",
        "Read-only: nothing was written.",
    ]
    return "\n".join(lines)


def _summary_line(summary: dict) -> str:
    issues = ", ".join(issue["code"] for issue in summary.get("memo_issues", [])) or "none"
    return (
        f"{summary['status']} · {summary['total']} claims · {summary['ok']} ok · "
        f"{summary['flagged']} flagged · memo issues: {issues}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", required=True, type=uuid.UUID, help="ranking run id")
    args = parser.parse_args(argv)
    session = SessionLocal()
    try:
        print(format_report(run_guard_demo(session, args.run)))
    except (LookupError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        session.rollback()
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
