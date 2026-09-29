"""Claim guard: check every memo claim against the evidence registry. Pure; no I/O.

Flagged claims are reported, never deleted or rewritten.
"""

import re
from dataclasses import dataclass, field

from app.services.evidence_registry import EvidenceRecord

MARKER = re.compile(r"\[\[([^\[\]]+)\]\]")
MONTH_YEAR = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{4}\b"
)
UNVERIFIED_STATUSES = {"unverifiable", "invalid", "missing"}
FUND_NEUTRAL_TYPES = {"benchmark", "run_warning"}


@dataclass
class GuardContext:
    registry: dict[str, EvidenceRecord]
    shortlist: list[str]
    allowed_tokens: list[str] = field(default_factory=list)
    fund_names: dict[str, str] = field(default_factory=dict)


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

    if claim["section"] == "recommendation" and fund_id is not None and fund_id not in context.shortlist:
        flag("NOT_SHORTLISTED_RECOMMENDATION", f"{fund_id} is not on the shortlist.")

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
    claims: list[dict], context: GuardContext, rationale_entries: list[str]
) -> tuple[list[ClaimResult], dict]:
    """rationale_entries: the fund_id of each shortlist_rationale entry, in draft order."""
    results = [check_claim(claim, context) for claim in claims]
    memo_issues = _memo_issues(claims, context, rationale_entries)
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
            addressed = any(
                claim["section"] == "recommendation"
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
