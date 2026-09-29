"""Memo artifacts: draft (LLM or template), guard, appendix, and immutable persistence.

Each call creates a new revision for the ranking run; nothing is updated afterwards.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.domain.models import MemoArtifact
from app.domain.schemas import (
    EvidenceRecordOut,
    EvidenceRegistryResponse,
    MemoClaimOut,
    MemoDraft,
    MemoResponse,
    MemoSummaryOut,
)
from app.services.claim_guard import GuardContext, guard_memo
from app.services.evidence_registry import EvidenceRecord, build_registry, selection_evidence_id
from app.services.memo_generator import (
    PROMPT_VERSION,
    DraftFailure,
    MemoContext,
    build_context,
    generate_llm_draft,
    generate_template_draft,
)
from app.services.ranking_runs import get_ranking_run

SECTIONS = ("executive_summary", "recommendation", "shortlist_rationale", "key_risks")
APPENDIX_METRICS = (
    "months_of_history",
    "annualized_return_bps",
    "volatility_bps",
    "sharpe",
    "max_drawdown_bps",
    "correlation",
    "excess_return_bps",
    "target_gap_bps",
)


TEMPLATE_REQUESTED = "template requested"


class MemoNotFoundError(LookupError):
    pass


class MemoInProgressError(RuntimeError):
    """Another request took this revision number first."""


def create_memo(
    session: Session, run_id: uuid.UUID, *, force_template: bool = False
) -> MemoArtifact:
    run = get_ranking_run(session, run_id)
    registry = build_registry(run)
    context = build_context(run, registry)

    token_usage: dict | None = None
    fallback_reason: str | None = None
    if force_template:
        draft = generate_template_draft(context)
        mode, model, fallback_reason, attempts = "template", None, TEMPLATE_REQUESTED, 0
    else:
        try:
            draft, token_usage, attempts = generate_llm_draft(context)
            mode, model = "llm", settings.openai_model
        except DraftFailure as failure:
            draft = generate_template_draft(context)
            mode, model, fallback_reason = "template", None, failure.reason
            attempts = failure.attempts

    claims = flatten_draft(draft)
    results, summary = guard_memo(
        claims,
        GuardContext(
            registry,
            context.shortlist_ids,
            context.allowed_tokens(),
            {fund.fund_id: fund.fund_name for fund in run.evaluations},
        ),
        [entry.fund_id for entry in draft.shortlist_rationale],
    )
    memo = MemoArtifact(
        id=uuid.uuid4(),
        ranking_run_id=run.id,
        revision=_next_revision(session, run.id),
        generation_mode=mode,
        model=model,
        prompt_version=PROMPT_VERSION,
        fallback_reason=fallback_reason,
        llm_attempts=attempts,
        claims=claims,
        guard_results=[result.to_json() for result in results],
        guard_summary=summary,
        appendix=build_appendix(context),
        evidence_snapshot=[record.to_json() for record in registry.values()],
        token_usage=token_usage,
        created_at=datetime.now(timezone.utc),
    )
    session.add(memo)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise MemoInProgressError(
            f"Another memo for ranking run {run_id} took revision {memo.revision}; "
            "generation is already in progress."
        ) from exc
    return memo


def list_memos(session: Session, run_id: uuid.UUID) -> list[MemoArtifact]:
    get_ranking_run(session, run_id)
    return list(
        session.scalars(
            select(MemoArtifact)
            .where(MemoArtifact.ranking_run_id == run_id)
            .order_by(MemoArtifact.revision)
        )
    )


def memo_summary(memo: MemoArtifact) -> MemoSummaryOut:
    return MemoSummaryOut(
        memo_id=memo.id,
        revision=memo.revision,
        generation_mode=memo.generation_mode,
        model=memo.model,
        fallback_reason=memo.fallback_reason,
        created_at=memo.created_at,
        guard_status=memo.guard_summary.get("status", "flagged"),
    )


def get_memo(session: Session, memo_id: uuid.UUID) -> MemoArtifact:
    memo = session.get(MemoArtifact, memo_id)
    if memo is None:
        raise MemoNotFoundError(f"Memo {memo_id} not found.")
    return memo


def get_latest_memo(session: Session, run_id: uuid.UUID) -> MemoArtifact | None:
    get_ranking_run(session, run_id)
    return session.scalar(
        select(MemoArtifact)
        .where(MemoArtifact.ranking_run_id == run_id)
        .order_by(MemoArtifact.revision.desc())
        .limit(1)
    )


def evidence_for_run(session: Session, run_id: uuid.UUID) -> EvidenceRegistryResponse:
    run = get_ranking_run(session, run_id)
    return EvidenceRegistryResponse(
        ranking_run_id=run.id,
        records=[EvidenceRecordOut(**record.to_json()) for record in build_registry(run).values()],
    )


def memo_to_response(memo: MemoArtifact) -> MemoResponse:
    guard_by_claim = {result["claim_id"]: result for result in memo.guard_results}
    return MemoResponse(
        memo_id=memo.id,
        ranking_run_id=memo.ranking_run_id,
        analysis_id=memo.ranking_run.analysis_id,
        revision=memo.revision,
        generation_mode=memo.generation_mode,
        model=memo.model,
        prompt_version=memo.prompt_version,
        fallback_reason=memo.fallback_reason,
        llm_attempts=memo.llm_attempts,
        created_at=memo.created_at,
        claims=[
            MemoClaimOut(
                **claim,
                guard_status=guard_by_claim[claim["claim_id"]]["status"],
                guard_reasons=guard_by_claim[claim["claim_id"]]["reasons"],
            )
            for claim in memo.claims
        ],
        guard_summary=memo.guard_summary,
        appendix=memo.appendix,
        evidence_snapshot=[EvidenceRecordOut(**record) for record in memo.evidence_snapshot],
        token_usage=memo.token_usage,
    )


def flatten_draft(draft: MemoDraft) -> list[dict]:
    """Stable, section-ordered claim list with unique claim_ids."""
    claims: list[dict] = []

    def add(section: str, index: int, claim, rationale_fund_id: str | None, claim_id: str) -> None:
        claims.append(
            {
                "claim_id": claim_id,
                "section": section,
                "position": index,
                "rationale_fund_id": rationale_fund_id,
                "text": claim.text,
                "evidence_ids": list(claim.evidence_ids),
                "claim_type": claim.claim_type,
                "fund_id": claim.fund_id,
            }
        )

    for section in SECTIONS:
        if section == "shortlist_rationale":
            for entry_index, entry in enumerate(draft.shortlist_rationale, start=1):
                for index, claim in enumerate(entry.claims):
                    add(section, index, claim, entry.fund_id, f"{section}-{entry_index}-{index + 1}")
        else:
            for index, claim in enumerate(getattr(draft, section)):
                add(section, index, claim, None, f"{section}-{index + 1}")
    return claims


def build_appendix(context: MemoContext) -> dict:
    """Deterministic data appendix; never written by the LLM."""
    registry = context.registry
    run = context.run
    ordered = [*context.shortlist, *context.not_selected, *context.excluded]

    def record_json(evidence_id: str | None) -> dict | None:
        record: EvidenceRecord | None = registry.get(evidence_id) if evidence_id else None
        return None if record is None else {
            "evidence_id": record.evidence_id,
            "display_value": record.display_value,
            "verification_status": record.verification_status,
        }

    metrics_rows = []
    for fund in ordered:
        metrics = fund.metrics or {}
        evidence = metrics.get("metric_evidence") or {}
        reasons = metrics.get("unverifiable_reasons") or {}
        metrics_rows.append(
            {
                "fund_id": fund.fund_id,
                "eligible": fund.eligible,
                "rank": fund.rank,
                "benchmark": fund.benchmark,
                "window_start": metrics.get("window_start"),
                "window_end": metrics.get("window_end"),
                "metrics": {
                    name: record_json(evidence.get(name)) or {
                        "evidence_id": None,
                        "display_value": "unverifiable",
                        "verification_status": "unverifiable",
                        "reason": reasons.get(name),
                    }
                    for name in APPENDIX_METRICS
                },
            }
        )
    return {
        "generated_from": {
            "ranking_run_id": str(run.id),
            "policy_version": run.policy_version,
            "mandate_sha256": run.mandate_sha256,
        },
        "mandate": run.mandate_snapshot,
        "metrics": metrics_rows,
        "screens": [
            {
                "fund_id": fund.fund_id,
                "eligible": fund.eligible,
                "screens": [record_json(screen["code"]) | {"screen": screen["screen"]} for screen in fund.screens],
            }
            for fund in ordered
        ],
        "selection": [
            {
                "fund_id": fund.fund_id,
                "rank": fund.rank,
                **(record_json(selection_evidence_id(fund.fund_id, fund.selection_reason)) or {}),
            }
            for fund in [*context.shortlist, *context.not_selected]
        ],
        "benchmarks": [record.to_json() for record in registry.values() if record.type == "benchmark"],
        "run_warnings": [record.to_json() for record in registry.values() if record.type == "run_warning"],
    }


def _next_revision(session: Session, run_id: uuid.UUID) -> int:
    current = session.scalar(
        select(func.max(MemoArtifact.revision)).where(MemoArtifact.ranking_run_id == run_id)
    )
    return (current or 0) + 1
