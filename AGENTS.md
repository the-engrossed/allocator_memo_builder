# IC Memo Workbench — Engineering Rules

This project is an allocator screening and Investment Committee memo-drafting prototype.

The objective is to turn an imperfect fund-universe CSV into a **defendable draft**
memo. It is not an autonomous investment system and does not constitute investment
advice.

## Product thesis

**Deterministic software owns data, math, screening, ranking, and every displayed
financial figure. The LLM owns constrained explanatory narrative only.**

A memo is treated as a collection of auditable claims, not an unverified block of prose.

```text
CSV → normalize → validate → benchmark → metrics → mandate screen → rank
    → evidence registry → LLM narrative → claim guard → memo and audit view
```

## Locked technology choices

- Frontend: React, TypeScript, Vite, Tailwind CSS.
- Backend: Python 3.12, FastAPI, Pydantic v2.
- Persistence: PostgreSQL, SQLAlchemy 2.0, Alembic.
- Local runtime: Docker Compose.
- Market data:
  - Yahoo Finance via `yfinance` for `SPY` and `AGG` monthly benchmark returns.
  - FRED `DGS3MO` only as an optional Treasury/risk-free reference for Sharpe.
- LLM: OpenAI only, using structured Pydantic output.
- Numerics: pandas and numpy. HTTP to FRED: httpx.
- Tests: pytest.
- Runtime data is local-first. Use local mounts/cache directories only.

Do not replace these choices without proposing the trade-off and receiving approval.

## Non-negotiable invariants

### 1. Deterministic code owns all finance decisions

Python code—not the LLM—must:
- Normalize uploaded data.
- Validate data quality.
- Retrieve and align benchmark observations.
- Compute financial metrics.
- Apply mandate constraints.
- Determine eligibility, exclusion reasons, baseline ranking, and ranking score.
- Resolve every final financial value displayed in the memo or UI.

The LLM may not calculate, screen, or decide eligibility. The LLM may propose an ordering of
eligible funds (`llm_ranking`) within deterministic limits; every move must cite evidence and is
checked by the guard. Reorders must rest on evidence the score does not already weigh.
Eligibility, scores, and the baseline shortlist remain deterministic.

### 2. No invented or model-generated financial numbers

The LLM must not emit digits or final numerical values that reach the rendered memo.

When a figure belongs in narrative, the model returns an evidence-ID marker such as:

```text
[[MET-F003-SHARPE]]
```

The frontend resolves that marker from a verified evidence record. Never render a
model-generated number directly.

### 3. Every material claim needs evidence

Each memo claim must contain:
- `text`
- `evidence_ids`
- `claim_type`: `quantitative`, `qualitative`, or `judgment`

A quantitative claim must include at least one valid evidence ID.

The claim guard (`app/services/claim_guard.py`) must visibly flag:
- Unknown evidence IDs (in markers or `evidence_ids`).
- A `[[marker]]` missing from `evidence_ids`, or an `evidence_ids` entry not used as a marker.
- Quantitative claims without evidence.
- Digits outside `[[markers]]` (fund IDs, fund names, strategies from the run, and month-year
  labels such as "May 2026" are allowed).
- Fund-specific claims that cite another fund's evidence (BMK/RUN evidence is allowed for any
  fund).
- Claims with a null `fund_id` that cite a fund's evidence without naming that fund (by fund
  ID or name) in the prose outside markers ("cited fund not named").
- Recommendation claims about a fund that is not shortlisted.
- Quantitative claims that rely on unverifiable, invalid, or missing evidence.

Memo-level issues: `shortlist_rationale` must cover each shortlisted fund once, in rank order;
if the top-ranked fund has data-quality evidence, a recommendation claim for it must cite that
DQ evidence and its verified `SRC-…-NOTES`. `guard_summary.status` is `flagged` when any claim
or memo-level issue is flagged, otherwise `clean`.

Never silently remove an invalid claim, citation, or audit warning. Flagged claims are stored
and returned verbatim.

### 4. Evidence is first-class data

Every important source field, data-quality result, computed metric, screen result, and
exclusion reason must become an evidence record.

Each evidence record requires:
- `evidence_id`
- `type`: `metric`, `source_field`, `data_quality`, `screen_result`, `selection`,
  `benchmark`, or `run_warning`
- `fund_id` nullable
- `label`
- `display_value` (pre-formatted by Python)
- `verification_status`: `verified`, `unverifiable`, `invalid`, or `missing`
- `provenance`

The registry (`app/services/evidence_registry.py`) is built from one persisted ranking run
only. MET/SRC/DQ/SCR records reuse the IDs the run issued; `SEL-{fund}-{REASON}`,
`BMK-SPY|AGG|RF`, and `RUN-{WARNING}` are derived one-to-one from the run. Metrics that were
not computed get no record. Each memo stores an `evidence_snapshot` of the registry it cited.

`provenance` must identify either:
- Source CSV field/row information, or
- Calculation formula, input evidence IDs, and reporting period.

Evidence IDs must be stable and readable. Examples:

```text
MET-F003-SHARPE
MET-F003-MAX-DRAWDOWN
MET-F003-CORRELATION-SPY
SRC-F003-LIQUIDITY-FREQUENCY
SRC-F003-NOTES
DQ-F003-SHORT-HISTORY-PERIOD
DQ-F001-CONFLICTING-METADATA
SCR-F003-LIQUIDITY-FAIL
SEL-F006-CAPACITY-REACHED
BMK-SPY
RUN-CONCENTRATION-FLOOR-APPLIED
```

Data-quality IDs are `DQ-{fund}-{CODE}-{FIELD}` when the issue has a field, otherwise
`DQ-{fund}-{CODE}`; a repeat within one fund gets `-2`, `-3`, … in source-row order.
Evidence IDs are unique within each fund evaluation.

### 5. Financial calculations are pure and tested

Metric functions must:
- Be pure functions with no HTTP, database, filesystem, or LLM calls.
- Have explicit type signatures.
- Handle insufficient data clearly.
- Be covered by pytest using small, hand-checkable input series.

V1 metrics only (definitions in `app/services/metrics.py`):
- CAGR / annualized return: `prod(1 + r)^(12/n) - 1`; unverifiable when n < 12.
- Annualized volatility: sample std (ddof=1) × √12.
- Sharpe ratio: `mean(r_m − rf_m) / std(r_m) × √12`, `rf_m = (1 + rf)^(1/12) − 1`.
- Maximum drawdown: largest peak-to-trough loss of the wealth index starting at 1.0.
- Correlation to the mapped benchmark (Credit → AGG, else SPY): Pearson on overlapping
  months; unverifiable below 12 overlapping months.
- Months of return history.
- `target_gap_bps = annualized_return_bps − target_return_bps` (reporting only).
- `excess_return_bps` (`MET-{fund}-EXCESS-VS-{BMK}`): fund CAGR − mapped benchmark CAGR over
  their overlapping months; unverifiable below 12 overlapping months or when the benchmark
  is unavailable. Reporting only, never scored.

Numeric policy: metrics are computed with pandas/numpy floats and rounded **once**, when
persisted and before any comparison to a mandate threshold — to integer bps (half away from
zero) for rates, or to 2 decimals for Sharpe and correlation. Mandate thresholds and any
future allocations stay integer bps. Gaps in a fund's months are never filled; metrics use
observed months only. Funds with blocking validation issues get no metrics.

Do not add Sortino, beta, alpha, tracking error, capture ratios, recovery duration,
peer heatmaps, or portfolio optimization without explicit approval.

### 6. Benchmark provenance and failure behavior are visible

Yahoo Finance is used only for `SPY` and `AGG` monthly return series: daily adjusted close
→ last close of each calendar month → month-over-month returns, with the current partial
month dropped. Calls time out after 10 seconds.

Benchmark resolution: a cache under 24 hours old is used as `cached`; otherwise live →
any cached copy (`cached`) → committed snapshot `sample_data/benchmark_fallback_{spy,agg}.csv`
(`fallback`) → `unavailable`. Never invent or hand-write benchmark numbers; snapshots are
written only by `backend/scripts/refresh_benchmark_snapshot.py`.

FRED `DGS3MO` is optional. If its key is missing or the request fails (and no cache exists):
- Use an explicit configurable 4.0% annual risk-free-rate fallback.
- Mark the source state as `fallback`.
- Surface this state in the UI and audit provenance.

Every benchmark/risk-free input must record:
- Provider.
- Ticker or series identifier.
- Retrieval timestamp.
- Date coverage.
- State: `live`, `cached`, `fallback`, or `unavailable`.

Never label cached or fallback data as live. If a benchmark needed by an eligible fund is
unavailable, the correlation component is 0 for every eligible fund in that run and the run
carries a `BENCHMARK_UNAVAILABLE` warning.

### 7. CSV scope is intentionally narrow

V1 accepts exactly one combined, long-form CSV using these canonical columns:

```text
fund_id
fund_name
strategy
period
net_return
liquidity_frequency
notice_days
lockup_months
mgmt_fee_bps
perf_fee_bps
notes
```

Allowed simple aliases only:

```text
fund_id: fund_id | id
fund_name: fund_name | fund | manager
period: period | date | month
net_return: net_return | return | monthly_return
```

Do not implement:
- Multiple CSV inputs.
- User-driven column mapping.
- Fuzzy fund matching.
- Natural-language fee parsing.
- Natural-language liquidity parsing.
- Automated data correction or silent imputation.

### 8. Validation reports problems; it does not hide them

V1 validation must cover:
- Missing required columns.
- Invalid periods.
- Invalid returns.
- Duplicate `(fund_id, period)` records.
- Missing months within a fund’s observed range.
- Fewer than 12 return observations.
- Conflicting metadata for a single `fund_id`.
- Monthly returns with |r| > 0.5 (error; blocks the fund from analysis, like duplicate
  periods; the row is kept, not dropped).
- `notice_days`, `lockup_months`, `mgmt_fee_bps`, and `perf_fee_bps` that are not
  non-negative integers within bounds, and `liquidity_frequency` values outside
  `monthly | quarterly | semiannual | annual` (error; hard screens read these fields).
- Implausibly smooth returns (`SMOOTH_RETURNS` warning): no negative month across ≥24
  observations, or annualized volatility < 1% with ≥12 observations.
- Possible duplicate identities (`FUND_ID_MISMATCH` warning): the same normalized fund name
  (casefolded, non-alphanumerics removed) under more than one `fund_id`, or `fund_id`s that
  differ only by case, whitespace, or punctuation.
- Stale histories (`INCONSISTENT_DATE_RANGE` warning, per fund): a fund whose last period
  is before the universe's latest period. Late starts are not flagged.
- Common window: the true overlap (latest start → earliest end) across funds with ≥12 valid
  observations, returned in the analysis response with its length in months. When it is
  shorter than 36 months, one universe-level `COMMON_WINDOW_SHORT` info issue (no
  `fund_id`) lists each fund's start and end: "Metrics use each fund's own history; windows
  differ."

Bare numeric returns (no `%` suffix) are interpreted **per fund**, never once for the whole
file: percentage points when the median |value| > 0.25, otherwise decimals, with a warning
when the median falls in 0.10–0.25. Values with a `%` suffix are always percentages.

Every issue must be structured with:
- Severity: `error`, `warning`, or `info`.
- Stable code.
- Clear human-readable message.
- `fund_id` nullable.
- Field nullable.
- Relevant source-row references when known.

Do not silently drop invalid rows. Preserve raw source inputs and report the issue.

### 9. Deterministic mandate screen and ranking

Every mandate input has exactly one role. See `DECISIONS.md` ("Mandate inputs split into
hard screens, ranking, and shortlist construction").

Hard screens (pass/fail, inclusive boundaries; a fund must pass all to be ranked):
- Redemption frequency at least as frequent as `min_liquidity_frequency`
  (monthly < quarterly < semiannual < annual).
- `notice_days` ≤ `max_notice_days`.
- `lockup_months` ≤ `max_lockup_months`.
- `mgmt_fee_bps` ≤ `max_mgmt_fee_bps`.
- `perf_fee_bps` ≤ `max_perf_fee_bps`.
- Annualized volatility ≤ `max_volatility_bps`.
- Maximum drawdown magnitude ≤ `max_drawdown_bps`.
- Months of valid return history ≥ `min_track_record_months`.
- Strategy not in `excluded_strategies`.

A screen whose input field is missing or invalid fails as "unverifiable"; never substitute
a default for fund data.

Only eligible funds can be ranked. V1 score weights must be explicit and centralized, and no
mandate field may change them:

```text
Sharpe: 45%
Annualized return: 25%
Drawdown resilience: 20%
Low benchmark correlation: 10%
```

Each component is a percentile rank across eligible funds (`position / (n − 1) × 100`, best
= 100, ties share the average position, a single fund = 100). A component without a
verifiable value scores 0 and is flagged. The total is rounded to 1 decimal. Ties break on:
total desc, target gap desc, management fee asc, performance fee asc, fund name (casefold)
asc, fund_id asc.

Shortlist construction runs on the ranked list and never changes eligibility or score:
- `max_candidates` caps the shortlist size.
- `strategy_concentration_cap_bps` caps funds per strategy at
  `max(1, floor(max_candidates × cap / 10000))`; the run warns
  `CONCENTRATION_FLOOR_APPLIED` when the floor of one binds.
- Every eligible fund gets exactly one of `SELECTED_PREFERENCE_PASS`, `SELECTED_RANK_PASS`,
  `CONCENTRATION_SKIP`, or `CAPACITY_REACHED`. No allocation weights in v1.
- Strategy names match case-insensitively (casefold) for preferences and exclusions.

Every ranking run is immutable: it stores the mandate snapshot and its SHA-256, benchmark
provenance, and policy version. Mandate edits never change a past run; a new POST creates a
new run.
- `preferred_strategies` is a preference, not a whitelist: fill first with eligible funds in
  preferred strategies (rank order, within the cap), then with the remaining eligible funds in
  rank order. An empty list means pure rank order.
- `target_return_bps` is a reporting reference only: record whether each shortlisted fund's
  annualized return meets it.

The UI must show the score, components, weights, exclusion reasons, and why each shortlisted
fund was included.

### 10. Thin routes; business logic lives in services

FastAPI route modules may:
- Parse and validate transport inputs.
- Call one or more application services.
- Convert known domain failures into HTTP responses.
- Return Pydantic response schemas.

Route modules may not:
- Contain pandas logic.
- Compute metrics.
- Make ranking decisions.
- Construct audit evidence.
- Call the LLM directly.
- Contain business-rule conditionals beyond request validation.

Business behavior belongs in clearly named service modules.

### 11. Keep the application a modular monolith

Do not add:
- Microservices.
- Background queues, Celery, Redis, or worker infrastructure.
- Authentication or user accounts.
- Cloud deployment infrastructure.
- CI/CD pipelines.
- Vector databases, embeddings, RAG, LangChain, or LangGraph.
- Generic repository patterns, Unit of Work abstractions, or base repository classes.
- PDF export.
- Unrequested new metrics or product features.

This is a local, single-user prototype. Complete and clear beats broad and incomplete.

### 12. Fallbacks must be explicit

The application must remain demoable when optional external services fail:
- Market-data failure: use bundled/cache fallback and show it.
- OpenAI unavailable or key missing: use a deterministic template-based memo and show it.
- Invalid data: show structured failures and prevent dependent calculations when necessary.

Never pretend a fallback result is live, model-generated, or fully validated when it is not.

## Code quality

- Python: full type hints on public functions and Pydantic models at transport boundaries.
- Use Pydantic v2 for API and LLM response contracts.
- Use SQLAlchemy 2.0 typed ORM models.
- TypeScript: avoid `any`; use API types from `frontend/src/types/api.ts`.
- Keep modules focused. Split modules before they become difficult to explain.
- Prefer explicit code over clever abstraction.
- No large `utils.py`, `helpers.py`, or generic `common.py` dumping grounds.
- Preserve user-facing error context; do not catch broad exceptions and return generic success.
- Maintain formatting and linting supported by the repository configuration.

## Testing requirements

Tests must exist for:
- Return normalization: decimal, numeric-percent, and percentage-string inputs.
- CSV validation: duplicates, missing months, short history, conflicting metadata.
- Each financial metric function.
- Mandate pass/fail logic and deterministic ranking.
- Claim guard behavior, including invalid evidence references and cross-fund evidence.

Tests must not require:
- A live OpenAI API key.
- Live Yahoo Finance or FRED calls.
- A frontend browser.

External clients must be replaceable by fakes/fixtures in tests.

## Decision-log discipline

`DECISIONS.md` records meaningful trade-offs, not a development diary.

A decision entry is required for a change affecting:
- Architecture or module boundaries.
- Data integrity or validation behavior.
- Financial calculation policy.
- LLM safety or claim verification.
- External data reliability or fallback behavior.
- Meaningful product scope.

Before implementing a meaningful decision that is not already locked here:

1. State the decision and alternatives in the Cursor conversation.
2. Draft the entry under `DRAFT — REVIEW REQUIRED` in `DECISIONS.md`.
3. Wait for my approval before treating it as final.

Do not add entries for routine file placement, variable names, imports, or basic UI work.

## Working protocol

For each vertical slice:

1. Read this file and `DECISIONS.md`.
2. State a concise plan.
3. List every file to be created or modified.
4. Wait for approval before editing.
5. Implement one concern at a time.
6. Run the relevant tests.
7. Report:
   - Files changed.
   - Tests run and result.
   - Manual verification performed.
   - Assumptions or unresolved questions.
8. Stop after the approved slice. Do not autonomously begin the next feature.