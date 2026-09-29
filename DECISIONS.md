> Draft decision entries created by implementation assistants remain under
> `DRAFT — REVIEW REQUIRED` until reviewed and rewritten by the project author.

---

# DRAFT — REVIEW REQUIRED

## Upload creates an analysis

**Choice:** Each uploaded fund-universe CSV creates an `analysis` record. Later workflow artifacts—mandate settings, calculated metrics, ranking results, evidence, and memo output—are associated with that analysis.

**Why:** An allocator's recommendation is meaningful only in the context of a specific universe, data-quality state, benchmark selection, and mandate. Using one analysis ID gives the workflow a stable audit boundary without introducing a multi-user workspace model.

**Consequence:** V1 treats reruns as new analyses rather than mutating a prior run. A later version could support named scenarios that reuse one source universe with multiple mandates.

## Mandate is a one-to-one, fully replaced configuration stored in basis points

**Choice:** Each analysis has at most one mandate, keyed by `analysis_id`. `PUT /api/analyses/{analysis_id}/mandate` is a full-replacement upsert: every field is required, unknown fields are rejected, and the server applies no defaults. Rates and percentages are stored as integers in basis points. The API enforces bounds, and the database enforces them again with `CHECK` constraints. Preferred strategies are trimmed, rejected if blank, and deduplicated in order. They are not checked against the uploaded dataset.

**Why:** Integer basis points avoid float rounding in thresholds that later decide whether a fund is eligible. Requiring every field keeps a partial or misspelled payload from silently resetting a constraint to a default, which the memo audit trail could not explain. Replaying an identical payload is a no-op and does not advance `updated_at`.

**Consequence:** Default values live only in the frontend form. Changing a mandate overwrites the prior version, and there is no mandate history in v1.

## OPEN — Stage 3 screening policy does not match AGENTS.md section 9

**Issue:** AGENTS.md section 9 lists the hard screens as required liquidity, maximum annualized volatility, maximum drawdown, minimum track-record months, and excluded strategies. The Stage 2 mandate instead stores target return, maximum management and performance fees, maximum notice days, maximum lockup months, preferred strategies, a strategy concentration cap, and a maximum candidate count. Section 9's screens have no matching mandate fields, and the Stage 2 fields have no defined screening or ranking role.

**Needs decision before Stage 3:** which constraints are hard screens and which are ranking inputs or portfolio-construction limits; whether the missing section 9 fields get added to the mandate; how preferred strategies and the concentration cap should work (preference versus exclusion); and which version, AGENTS.md or the mandate, is the source of truth. Neither AGENTS.md nor the ranking logic changes until this is resolved.
