"""Claim guard: check every memo claim against the evidence registry. Pure; no I/O.

Flagged claims are reported, never deleted or rewritten.
"""

import re
from collections import Counter
from dataclasses import dataclass, field, replace

from app.services.evidence_registry import EvidenceRecord

MARKER = re.compile(r"\[\[([^\[\]]+)\]\]")
MONTH_YEAR = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{4}\b"
)
UNVERIFIED_STATUSES = {"unverifiable", "invalid", "missing"}
FUND_NEUTRAL_TYPES = {"benchmark", "run_warning"}
# Fund terms and notes: the source fields a reorder may rest on. Every MET is score-derived, SEL
# restates the baseline, and every eligible fund passes every screen, so none of those count.
REORDER_SOURCE_FIELDS = {
    "liquidity_frequency", "notice_days", "lockup_months", "mgmt_fee_bps", "perf_fee_bps", "notes",
}


@dataclass(frozen=True)
class RankingLimits:
    """Deterministic bounds on the LLM ranking, taken from the run and its mandate snapshot."""

    eligible_strategies: dict[str, str]
    max_candidates: int
    strategy_limit: int
    baseline_ranks: dict[str, int] = field(default_factory=dict)


@dataclass
class GuardContext:
    registry: dict[str, EvidenceRecord]
    shortlist: list[str]
    allowed_tokens: list[str] = field(default_factory=list)
    fund_names: dict[str, str] = field(default_factory=dict)
    ranking_limits: RankingLimits | None = None
    # Funds a recommendation may name; None means the baseline shortlist.
    recommendable: list[str] | None = None


@dataclass
class ClaimResult:
    claim_id: str
    status: str
    reasons: list[dict]

    def to_json(self) -> dict:
        return {"claim_id": self.claim_id, "status": self.status, "reasons": self.reasons}


def marker_ids(text: str) -> list[str]:
    return [match.strip() for match in MARKER.findall(text)]


def check_claim(claim: dict, context: GuardContext) -> ClaimResult:
    reasons: list[dict] = []

    def flag(code: str, message: str) -> None:
        reasons.append({"code": code, "message": message})

    text = claim["text"]
    markers = marker_ids(text)
    cited = list(claim["evidence_ids"])
    referenced = list(dict.fromkeys([*markers, *cited]))

    unknown = [evidence_id for evidence_id in referenced if evidence_id not in context.registry]
    if unknown:
        flag("UNKNOWN_EVIDENCE", "Unknown evidence id(s): " + ", ".join(unknown) + ".")

    not_cited = [m for m in dict.fromkeys(markers) if m not in cited]
    if not_cited:
        flag("MARKER_NOT_CITED", "Marker(s) missing from evidence_ids: " + ", ".join(not_cited) + ".")
    not_marked = [c for c in dict.fromkeys(cited) if c not in markers]
    if not_marked:
        flag("CITED_NOT_MARKED", "evidence_ids not used as markers: " + ", ".join(not_marked) + ".")

    if claim["claim_type"] == "quantitative" and not referenced:
        flag("QUANTITATIVE_WITHOUT_EVIDENCE", "Quantitative claim cites no evidence.")

    stray = stray_digits(text, context.allowed_tokens)
    if stray:
        flag("DIGITS_OUTSIDE_MARKERS", "Figures outside [[markers]]: " + ", ".join(stray) + ".")

    fund_id = claim.get("fund_id")
    if fund_id is not None:
        foreign = [
            evidence_id
            for evidence_id in referenced
            if (record := context.registry.get(evidence_id)) is not None
            and record.type not in FUND_NEUTRAL_TYPES
            and record.fund_id is not None
            and record.fund_id != fund_id
        ]
        if foreign:
            flag(
                "CROSS_FUND_EVIDENCE",
                f"Claim about {fund_id} cites another fund's evidence: " + ", ".join(foreign) + ".",
            )

    if fund_id is None:
        unnamed = [
            cited_fund
            for cited_fund in _cited_funds(referenced, context)
            if not _names_fund(text, cited_fund, context.fund_names.get(cited_fund))
        ]
        if unnamed:
            flag(
                "CITED_FUND_NOT_NAMED",
                "cited fund not named: " + ", ".join(unnamed)
                + ". A claim without a fund_id must name every fund whose evidence it cites.",
            )

    rationale_fund = claim.get("rationale_fund_id")
    if rationale_fund is not None and fund_id != rationale_fund:
        flag(
            "RATIONALE_FUND_MISMATCH",
            f"Claim in {rationale_fund}'s rationale has fund_id {fund_id!r}.",
        )

    recommendable = context.shortlist if context.recommendable is None else context.recommendable
    if claim["section"] == "recommendation" and fund_id is not None and fund_id not in recommendable:
        where = "on the shortlist" if context.recommendable is None else "in the LLM ranking of eligible funds"
        flag("NOT_SHORTLISTED_RECOMMENDATION", f"{fund_id} is not {where}.")

    if claim["claim_type"] == "quantitative":
        unverified = [
            evidence_id
            for evidence_id in referenced
            if (record := context.registry.get(evidence_id)) is not None
            and record.verification_status in UNVERIFIED_STATUSES
        ]
        if unverified:
            flag(
                "UNVERIFIED_EVIDENCE_AS_FACT",
                "Quantitative claim relies on unverifiable/invalid/missing evidence: "
                + ", ".join(unverified) + ".",
            )

    return ClaimResult(claim["claim_id"], "flagged" if reasons else "ok", reasons)


def _cited_funds(evidence_ids: list[str], context: GuardContext) -> list[str]:
    funds: list[str] = []
    for evidence_id in evidence_ids:
        record = context.registry.get(evidence_id)
        if (
            record is not None
            and record.type not in FUND_NEUTRAL_TYPES
            and record.fund_id is not None
            and record.fund_id not in funds
        ):
            funds.append(record.fund_id)
    return funds


def _names_fund(text: str, fund_id: str, fund_name: str | None) -> bool:
    """True when the prose outside [[markers]] names the fund by ID or by name."""
    prose = MARKER.sub(" ", text)
    if re.search(rf"(?<![A-Za-z0-9]){re.escape(fund_id)}(?![A-Za-z0-9])", prose, re.IGNORECASE):
        return True
    return bool(fund_name and fund_name.strip() and fund_name.strip().casefold() in prose.casefold())


def stray_digits(text: str, allowed_tokens: list[str]) -> list[str]:
    """Digit-bearing fragments left after removing markers, allowed names/IDs, and month-year labels."""
    remainder = MARKER.sub(" ", text)
    for token in sorted(allowed_tokens, key=len, reverse=True):
        if token and any(char.isdigit() for char in token):
            remainder = remainder.replace(token, " ")
    remainder = MONTH_YEAR.sub(" ", remainder)
    return re.findall(r"\S*\d\S*", remainder)


def guard_memo(
    claims: list[dict],
    context: GuardContext,
    rationale_entries: list[str],
    llm_ranking: list[str] | None = None,
    llm_dropped: list[str] | None = None,
) -> tuple[list[ClaimResult], dict]:
    """rationale_entries: the fund_id of each shortlist_rationale entry, in draft order.

    llm_ranking / llm_dropped: fund_ids in the draft's proposed order and drop list. None (memos
    before memo-v3) skips the ranking rules and checks recommendations against the baseline.
    """
    limits = context.ranking_limits
    if llm_ranking is not None and limits is not None:
        context = replace(
            context,
            recommendable=[f for f in dict.fromkeys(llm_ranking) if f in limits.eligible_strategies],
        )
    results = [check_claim(claim, context) for claim in claims]
    memo_issues = _memo_issues(claims, context, rationale_entries)
    if llm_ranking is not None and limits is not None:
        memo_issues += llm_ranking_issues(claims, context, limits, llm_ranking, llm_dropped or [])
    flagged = sum(1 for result in results if result.status == "flagged")
    summary = {
        "total": len(results),
        "ok": len(results) - flagged,
        "flagged": flagged,
        "memo_issues": memo_issues,
        "status": "flagged" if flagged or memo_issues else "clean",
    }
    return results, summary


def _memo_issues(
    claims: list[dict], context: GuardContext, rationale_entries: list[str]
) -> list[dict]:
    issues: list[dict] = []
    if rationale_entries != context.shortlist:
        issues.append(
            {
                "code": "SHORTLIST_RATIONALE_COVERAGE",
                "message": (
                    "shortlist_rationale must cover each shortlisted fund once, in rank order "
                    f"({', '.join(context.shortlist) or 'none'}); got "
                    f"{', '.join(rationale_entries) or 'none'}."
                ),
            }
        )

    if context.shortlist:
        top = context.shortlist[0]
        concerns = [
            record.evidence_id
            for record in context.registry.values()
            if record.fund_id == top and record.type == "data_quality"
        ]
        notes_id = next(
            (
                record.evidence_id
                for record in context.registry.values()
                if record.fund_id == top
                and record.type == "source_field"
                and record.provenance.get("field") == "notes"
                and record.verification_status == "verified"
            ),
            None,
        )
        if concerns:
            # A dropped top fund addresses its concerns in its drop rationale instead.
            addressed = any(
                claim["section"] in ("recommendation", "llm_dropped")
                and claim.get("fund_id") == top
                and set(concerns) & set(claim["evidence_ids"])
                and (notes_id is None or notes_id in claim["evidence_ids"])
                for claim in claims
            )
            if not addressed:
                needed = ", ".join(sorted(concerns)) + (f" and {notes_id}" if notes_id else "")
                issues.append(
                    {
                        "code": "TOP_FUND_DATA_QUALITY_UNADDRESSED",
                        "message": (
                            f"The recommendation must address top-ranked {top}'s data-quality "
                            f"concerns, citing {needed}."
                        ),
                    }
                )
    return issues


def llm_ranking_issues(
    claims: list[dict],
    context: GuardContext,
    limits: RankingLimits,
    ranking: list[str],
    dropped: list[str],
) -> list[dict]:
    """Deterministic checks on the LLM's proposed order against eligibility and the mandate."""
    issues: list[dict] = []

    def issue(code: str, message: str) -> None:
        issues.append({"code": code, "message": message})

    eligible = limits.eligible_strategies
    ineligible = [f for f in dict.fromkeys(ranking) if f not in eligible]
    if ineligible:
        issue(
            "LLM_RANK_INELIGIBLE_FUND",
            "Only funds that passed every hard screen may be ranked; not eligible: "
            + ", ".join(ineligible) + ".",
        )

    duplicates = [f for f, count in Counter([*ranking, *dropped]).items() if count > 1]
    if duplicates:
        issue(
            "LLM_RANK_DUPLICATE",
            "Each fund may appear once across the ranking and drop list: " + ", ".join(duplicates) + ".",
        )

    if len(ranking) > limits.max_candidates:
        issue(
            "LLM_RANK_OVER_CAPACITY",
            f"The LLM ranking lists {len(ranking)} funds; the mandate allows {limits.max_candidates}.",
        )

    names: dict[str, str] = {}
    counts: Counter[str] = Counter()
    for fund_id in dict.fromkeys(ranking):
        if fund_id in eligible:
            key = eligible[fund_id].strip().casefold()
            names.setdefault(key, eligible[fund_id].strip())
            counts[key] += 1
    crowded = [names[key] for key, count in counts.items() if count > limits.strategy_limit]
    if crowded:
        issue(
            "LLM_RANK_CONCENTRATION",
            f"More than {limits.strategy_limit} ranked fund(s) per strategy in: " + ", ".join(crowded) + ".",
        )

    baseline = {fund_id: position for position, fund_id in enumerate(context.shortlist, start=1)}
    invalid_drops = [f for f in dict.fromkeys(dropped) if f not in baseline or f in ranking]
    if invalid_drops:
        issue(
            "LLM_RANK_INVALID_DROP",
            "Only baseline-shortlisted funds left out of the LLM ranking can be dropped: "
            + ", ".join(invalid_drops) + ".",
        )

    positions: dict[str, int] = {}
    for position, fund_id in enumerate(ranking, start=1):
        positions.setdefault(fund_id, position)
    moved = [
        fund_id
        for fund_id in dict.fromkeys([*ranking, *baseline])
        if fund_id in eligible and positions.get(fund_id) != baseline.get(fund_id)
    ]
    uncited = [
        fund_id
        for fund_id in moved
        if not _reorder_evidence(
            claims, context, fund_id, "llm_ranking" if fund_id in positions else "llm_dropped"
        )
    ]
    if uncited:
        issue(
            "LLM_RANK_MOVE_UNCITED",
            "A fund whose position differs from the deterministic baseline must cite its own "
            "warning- or error-level DQ, SRC terms or notes, or a failing or unverifiable SCR "
            "(metrics never count): " + ", ".join(uncited) + ".",
        )

    ranks = limits.baseline_ranks
    ordered = [f for f in positions if f in ranks]
    kinds = {fund_id: _reorder_evidence(claims, context, fund_id, "llm_ranking") for fund_id in ordered}
    reweighted = [
        f"{above} above {below}"
        for i, above in enumerate(ordered)
        for below in ordered[i + 1:]
        if ranks[above] > ranks[below]
        and not (kinds[below] & {"dq", "src"})
        and "src" not in kinds[above]
    ]
    if reweighted:
        issue(
            "LLM_RANK_REWEIGHTS_SCORE",
            "A fund placed above a better-ranked baseline fund needs the demoted fund's own DQ or "
            "SRC, or the promoted fund's own SRC terms or notes; a fund's own DQ never promotes it: "
            + ", ".join(reweighted) + ".",
        )
    return issues


def _reorder_evidence(claims: list[dict], context: GuardContext, fund_id: str, section: str) -> set[str]:
    """Kinds of reorder evidence the fund's own rationale cites: "dq", "src", or "scr"."""
    kinds: set[str] = set()
    for claim in claims:
        if claim["section"] != section or claim.get("rationale_fund_id") != fund_id:
            continue
        for evidence_id in claim["evidence_ids"]:
            record = context.registry.get(evidence_id)
            if record is None or record.fund_id != fund_id:
                continue
            if record.type == "data_quality" and record.provenance.get("severity") in ("warning", "error"):
                kinds.add("dq")
            elif (
                record.type == "source_field"
                and record.provenance.get("field") in REORDER_SOURCE_FIELDS
                and record.verification_status == "verified"
            ):
                kinds.add("src")
            elif record.type == "screen_result" and record.provenance.get("result") in ("fail", "unverifiable"):
                kinds.add("scr")
    return kinds
