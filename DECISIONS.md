> Draft decision entries created by implementation assistants remain under
> `DRAFT — REVIEW REQUIRED` until reviewed and rewritten by the project author.

---

# DRAFT — REVIEW REQUIRED

## Upload creates an analysis

**Choice:** Each uploaded fund-universe CSV creates an `analysis` record. Later workflow artifacts—mandate settings, calculated metrics, ranking results, evidence, and memo output—are associated with that analysis.

**Why:** An allocator's recommendation is meaningful only in the context of a specific universe, data-quality state, benchmark selection, and mandate. Using one analysis ID gives the workflow a stable audit boundary without introducing a multi-user workspace model.

**Consequence:** V1 treats reruns as new analyses rather than mutating a prior run. A later version could support named scenarios that reuse one source universe with multiple mandates.

## Mandate is a one-to-one, fully replaced configuration stored in basis points

**Choice:** Each analysis has at most one mandate, keyed by `analysis_id`. `PUT /api/analyses/{analysis_id}/mandate` is a full-replacement upsert: every field is required, unknown fields are rejected, and the server applies no defaults. Rates and percentages are stored as integers in basis points. The API enforces bounds, and the database enforces them again with `CHECK` constraints. Preferred and excluded strategy lists are trimmed, rejected if an entry is blank, and deduplicated in order. Either list may be empty, a strategy may not appear in both, and neither is checked against the uploaded dataset.

**Why:** Integer basis points avoid float rounding in thresholds that later decide whether a fund is eligible. Requiring every field keeps a partial or misspelled payload from silently resetting a constraint to a default, which the memo audit trail could not explain. Replaying an identical payload is a no-op and does not advance `updated_at`.

**Consequence:** Default values live only in the frontend form. Changing a mandate overwrites the prior version, and there is no mandate history in v1.

## Mandate inputs split into hard screens, ranking, and shortlist construction

Resolves the earlier open item: AGENTS.md section 9 and the Stage 2 mandate disagreed on which inputs screen funds. The mandate is the source of truth, and AGENTS.md section 9 is updated to match. Migration `0003` adds `min_liquidity_frequency`, `max_volatility_bps`, `max_drawdown_bps`, `min_track_record_months`, and `excluded_strategies`.

**Choice:** Every mandate input has exactly one role.

1. **Hard screens decide eligibility.** Each is pass or fail, and every boundary is inclusive. A fund must pass all of them to be ranked.
   - Redemption frequency is at least as frequent as `min_liquidity_frequency`. The order is monthly, quarterly, semiannual, annual.
   - `notice_days` is at most `max_notice_days`.
   - `lockup_months` is at most `max_lockup_months`.
   - `mgmt_fee_bps` is at most `max_mgmt_fee_bps`.
   - `perf_fee_bps` is at most `max_perf_fee_bps`.
   - Annualized volatility is at most `max_volatility_bps`.
   - The maximum drawdown magnitude is at most `max_drawdown_bps`.
   - Months of valid return history is at least `min_track_record_months`.
   - The strategy is not in `excluded_strategies`.
2. **Ranking orders eligible funds only,** using the fixed weights: Sharpe 45%, annualized return 25%, drawdown resilience 20%, low benchmark correlation 10%. No mandate field changes the score or the weights.
3. **Shortlist construction runs on the ranked list** and never changes eligibility or a fund's score.
   - `max_candidates` limits the shortlist size.
   - `strategy_concentration_cap_bps` limits how many shortlisted funds can share one strategy: `max(1, floor(max_candidates × cap / 10000))`.
   - `preferred_strategies` is a preference, not a whitelist. The shortlist fills first with eligible funds in preferred strategies, in rank order and within the cap. Remaining slots are filled with other eligible funds in rank order. With an empty list, the shortlist is simply the top of the ranking.
   - `target_return_bps` is a reference point for reporting only. Each shortlisted fund records whether its annualized return meets the target. It never excludes or reorders a fund.

**Why:** A committee can defend a binary constraint or a published formula. It cannot defend a ranking quietly bent by preferences. Keeping preferences and concentration out of eligibility and scoring means every exclusion traces to one screen, and every ordering traces to the fixed weights.

**Consequence:** When a field a screen reads is missing or invalid (for example, a non-numeric fee or an unknown liquidity value), that screen fails for the fund with the reason "unverifiable". The fund is never given a default value. Mandates that existed before `0003` were backfilled with values that screen nothing: annual liquidity, 10000 bps for volatility and drawdown, 0 months of track record, and no exclusions. That way the migration invents no constraint the allocator didn't set.

## Bare-return units are inferred per fund from the median absolute value

**Choice:** For each `fund_id`, take every `net_return` that has no `%` suffix and parses as a number, and compute the median of their absolute values:
- **Above 0.25:** read as percentage points and divided by 100.
- **From 0.10 to 0.25 inclusive:** read as decimals, with a `RETURN_UNIT_INFERRED` warning that the unit is ambiguous.
- **Below 0.10:** read as decimals.

Values with a `%` suffix are always percentages. Every fund with bare values also gets an info issue recording its median, value count, and chosen unit.

**Why:** A median monthly decimal return above 25% is implausible for a hedge fund, while a median of 0.25 percentage points is a normal quiet fund. The earlier 1.0 threshold misread a fund reporting 0.8, 1.2, and −0.5 as 80%, 120%, and −50%. Between 0.10 and 0.25, both readings are possible, so the system warns instead of guessing silently. Inferring per fund stops one percentage-reporting manager from changing how every other fund is read.

**Consequence:** A low-volatility fund reporting in percentage points with a median below 0.25 (for example, 0.2 meaning 0.2%) is read as decimals, which is 20%. Such a fund would almost always also trigger `RETURN_OUT_OF_RANGE` or an extreme volatility figure, and the ambiguity warning covers the 0.10–0.25 band. Allocators should use `%` suffixes when a fund's returns are that small.

## Out-of-range monthly returns block the fund

**Choice:** A monthly return with |r| > 0.5 after unit conversion raises a `RETURN_OUT_OF_RANGE` error and blocks the whole fund from analysis, the same as `DUPLICATE_PERIOD`. The row stays in the stored observations.

**Why:** Dropping a single implausible month would quietly remove what may be the fund's worst loss, and flatter its drawdown and volatility. A 60% month is either a unit error or a real event, and neither should be averaged away.

## SMOOTH_RETURNS warns on implausibly smooth return streams

**Choice:** A fund gets a `SMOOTH_RETURNS` warning when its valid observations show either of these:
- No negative month across at least 24 observations.
- Annualized volatility (sample standard deviation × √12) below 1%, evaluated only once the fund has at least 12 observations.

This is a warning. It does not block the fund or affect the screens and ranking.

**Why:** The deterministic ranking rewards low volatility, so a fabricated or stale-priced return stream would rank first on Sharpe. The warning puts that risk in front of the committee as cited data-quality evidence, without letting a heuristic silently exclude a real low-volatility fund. The 12-observation minimum on the volatility test exists because a standard deviation from a few months means little, and short histories already get `SHORT_HISTORY`.

**Consequence:** In the sample universe only F007 triggers it, with 60 months, no losses, and about 0.4% volatility. F007 will still rank highly until a human acts on the warning, and the memo should cite the warning next to its metrics.

## Identity and date-range checks are warnings; the common window starts at the median fund start

**Choice:**
- `FUND_ID_MISMATCH` warns every fund in a group whose first-row fund names are equal after casefolding and removing non-alphanumerics. It also warns groups whose `fund_id`s are equal under the same normalization.
- `INCONSISTENT_DATE_RANGE` warns a fund that ends before the universe's latest period, or starts after the common window start.
- The common window runs from the **median** fund start (the lower median) to the latest period in the universe. It is returned in the analysis response, along with how many funds fully cover it.

Both checks are warnings only. They never block a fund or merge funds, and they don't affect screening.

**Why:** A strict intersection of all funds' ranges can't be used for "starts after the common window start", because by definition no fund starts after the latest start. It would also collapse to one fund's history as soon as a single recent launch joined the universe. The median start describes where most of the universe begins, and one late fund can't move it. Merging look-alike funds automatically would be silent remediation; flagging them leaves the decision to the allocator.

**Consequence:** In the sample, five funds warn on start date (F002, F004, F008, F009, F010), and F004 also warns for ending in May 2026. These are informational. Funds are still measured over their own windows, as the policy requires.

## Slice 3 acceptance: app metrics reproduce the sample generator (closed)

**Issue:** F003 (drawdown about 18.6%) and F006 (about 18.4%) pass the default 20% drawdown cap narrowly. How missing months are handled could have moved these figures enough to flip a narrow pass. For example, F004 skips a month and F006 loses its unparseable November 2023 row.

**Resolution:** Metrics compound across gaps using observed months only and never fill a missing month. `tests/test_ranking_runs.py::test_sample_universe_end_to_end` uploads the sample and runs the full pipeline. For every fund that gets metrics (F001 through F008), it asserts that the app's max drawdown and annualized volatility match the generator within 5 bps. The generator's figures are computed on the rows the CSV actually emits. The test also asserts that F003 and F006 pass a 20% drawdown cap.

## Ranking policy v1 calculation choices

**Choice:**
- **Sharpe** is `mean(r_m − rf_m) / std(r_m) × √12`, with `rf_m = (1 + rf)^(1/12) − 1`. The annual `rf` is the mean monthly FRED DGS3MO rate over the fund's own window, or the configured fallback when FRED data isn't available. CAGR is a separate metric and is unverifiable below 12 months.
- **Score components** use a percentile rank across eligible funds rather than min-max. That way F007's outlier Sharpe (about 15) doesn't squeeze every other fund's Sharpe score toward zero.
- **Benchmarks** come from daily adjusted closes, taking the last close of each month and dropping the current partial month. A cache under 24 hours old is used without a live call.
- **Unavailable benchmark:** if a benchmark that an eligible fund needs is unavailable, every eligible fund's correlation component is set to 0 and the run warns `BENCHMARK_UNAVAILABLE`. This keeps scores comparable within the run. A single fund with fewer than 12 overlapping months gets 0 only for itself.
- **Concentration floor:** the floor of one fund per strategy stays, and the run warns `CONCENTRATION_FLOOR_APPLIED` whenever it binds.
- **Strategy matching:** preferred and excluded strategies are compared case-insensitively.

**Why:** Each of these makes a result explainable in one sentence to a committee. Percentile ranks keep one implausible fund from reshaping everyone else's score. Zeroing correlation for the whole run keeps a data outage from rewarding the funds whose benchmark happened to load.

**Consequence:** Scores are ordinal. A fund's score says where it sits among the eligible funds in that run, not how far ahead it is. Removing or adding an eligible fund can change the other funds' component scores.
