## Upload creates an analysis

**Choice:** Each uploaded fund-universe CSV creates an `analysis` record. Later workflow artifacts—mandate settings, calculated metrics, ranking results, evidence, and memo output—are associated with that analysis.

**Why:** An allocator's recommendation is meaningful only in the context of a specific universe, data-quality state, benchmark selection, and mandate. Using one analysis ID gives the workflow a stable audit boundary without introducing a multi-user workspace model.

**Consequence:** Re-running creates a new immutable ranking run on the same analysis, with its own mandate snapshot and sha256. A new upload creates a new analysis.

## Mandate is a one-to-one, fully replaced configuration stored in basis points

**Choice:** Each analysis has at most one mandate, keyed by `analysis_id`. `PUT /api/analyses/{analysis_id}/mandate` is a full-replacement upsert: every field is required, unknown fields are rejected, and the server applies no defaults. Rates and percentages are stored as integers in basis points. The API enforces bounds, and the database enforces them again with `CHECK` constraints. Preferred and excluded strategy lists are trimmed, rejected if an entry is blank, and deduplicated in order. Either list may be empty, a strategy may not appear in both, and neither is checked against the uploaded dataset.

**Why:** Integer basis points avoid float rounding in thresholds that later decide whether a fund is eligible. Requiring every field keeps a partial or misspelled payload from silently resetting a constraint to a default, which the memo audit trail could not explain. Replaying an identical payload is a no-op and does not advance `updated_at`.

**Consequence:** Default values live only in the frontend form. The mandate row keeps no history, but each ranking run stores the mandate snapshot and hash it used, so every decision stays reproducible.

## Mandate inputs split into hard screens, ranking, and shortlist construction

Resolves the earlier open item: AGENTS.md section 9 and the Stage 2 mandate disagreed on which inputs screen funds. The mandate is the source of truth, and AGENTS.md section 9 is updated to match. Migration `0003` adds `min_liquidity_frequency`, `max_volatility_bps`, `max_drawdown_bps`, `min_track_record_months`, and `excluded_strategies`.

**Choice:** Every mandate input has exactly one role.

1. **Hard screens decide eligibility.** Each is pass, fail, or unverifiable, and every boundary is inclusive. A fund must pass all of them to be ranked.
   - The fund has no blocking validation issue (`DUPLICATE_PERIOD` or `RETURN_OUT_OF_RANGE`).
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

**Consequence:** When a field a screen reads is missing or invalid (for example, a non-numeric fee or an unknown liquidity value), that screen's outcome is "unverifiable", which is distinct from fail. An unverifiable screen still excludes the fund, and no default value is substituted. Mandates that existed before `0003` were backfilled with values that screen nothing: annual liquidity, 10000 bps for volatility and drawdown, 0 months of track record, and no exclusions. That way the migration invents no constraint the allocator didn't set.

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

## Identity and date-range checks; the common window is the true overlap

**Choice:**
- `FUND_ID_MISMATCH` (warning, per fund) flags every fund in a group whose first-row fund names are equal after casefolding and removing non-alphanumerics. It also flags groups whose `fund_id`s are equal under the same normalization.
- **Common window:** the true overlap, from the latest start to the earliest end, across funds with at least 12 valid observations. The analysis response returns it with its length in months. When those funds share no month, start and end are null and the length is 0.
- `INCONSISTENT_DATE_RANGE` (warning, per fund) fires only when a fund's last period is earlier than the universe's latest period. A fund that simply started later is not flagged.
- `COMMON_WINDOW_SHORT` (info, universe-level, no `fund_id`) fires when the overlap is shorter than 36 months. The message is "Metrics use each fund's own history; windows differ.", and the details list each fund's start and end.

None of these block a fund, merge funds, or affect screening.

**Why:** A fund that stops reporting early may be hiding recent results, so a stale end deserves a per-fund warning. A later launch is normal and is already covered by the track-record screen. The strict overlap is the only window every qualifying fund can be compared on. Funds with fewer than 12 observations are left out of it so one new launch can't collapse it. When the overlap is short, the committee needs to know that fund-to-fund comparisons span different periods. It doesn't need a warning on every fund.

**Consequence:** In the sample, the overlap across the 8 qualifying funds is September 2022 to May 2026, which is 45 months, so `COMMON_WINDOW_SHORT` does not fire. F008 and F010 are left out of the overlap because they have fewer than 12 observations. Only F004 gets `INCONSISTENT_DATE_RANGE`, because it ends in May 2026. Metrics are still computed over each fund's own history.

## Slice 3 acceptance: app metrics reproduce the sample generator (closed)

**Issue:** F003 (drawdown about 18.6%) and F006 (about 18.4%) pass the default 20% drawdown cap narrowly. How missing months are handled could have moved these figures enough to flip a narrow pass. For example, F004 skips a month and F006 loses its unparseable November 2023 row.

**Resolution:** Metrics compound across gaps using observed months only and never fill a missing month. `tests/test_ranking_runs.py::test_sample_universe_end_to_end` uploads the sample and runs the full pipeline. For every fund that gets metrics (F001 through F008), it asserts that the app's max drawdown and annualized volatility match the generator within 5 bps. The generator's figures are computed on the rows the CSV actually emits. The test also asserts that F003 and F006 pass a 20% drawdown cap.

## Memo generation: markers only, guarded, with an immutable evidence snapshot

**Choice:**
- **One structured-output call.** The memo is drafted by a single OpenAI `responses.parse` call into `MemoDraft`, with a 120 s timeout and `max_output_tokens` of 12000. Only a connection error is retried, and only once; timeouts, HTTP errors, refusals, output-limit stops, and parse failures are not retried. The number of calls made is stored on the memo as `llm_attempts`.
- **Template fallback.** If the key is missing, or the call times out, errors, is refused, fails schema parsing, or stops at the output limit, a deterministic template memo with the same structure is used instead. The fallback reason is short and sanitized, for example `HTTP 400`, `timeout`, or `max_output_tokens`.
- **Figures only as markers.** Every figure, count, rank, and benchmark appears only as an `[[EVIDENCE-ID]]` marker, and that includes spelled-out numbers. Vague quantifiers are allowed.
- **Untrusted fund text.** Fund names, strategies, and notes are passed only inside an `<untrusted_fund_data>` block, and the model is told to treat them as data.
- **Guard on every claim.** The claim guard runs on every claim, whether it came from the LLM or the template. Flagged claims are stored verbatim, never removed or rewritten.
- **Top-fund data quality.** If the top-ranked fund has data-quality evidence, the recommendation must address it, citing its DQ and notes evidence.
- **Deterministic appendix and snapshot.** The data appendix is built from the run, not by the LLM. Each memo revision stores the evidence registry it was checked against.

**Why:** A committee reader must be able to trace every figure to one computed record, and a model that writes numbers can't be verified. The snapshot keeps an old memo's citations resolvable exactly as they were, even if registry formatting code changes later. The template keeps the demo usable, and honest about which mode produced it, when the model isn't available.

**Consequence:** Memo prose is constrained, and some sentences read like a catalogue of markers. Spelled-out numbers are banned by instruction but aren't checked by the guard in this version.

## Ranking policy v1 calculation choices

**Choice:**
- **Sharpe** is `mean(r_m − rf_m) / std(r_m) × √12`, with `rf_m = (1 + rf)^(1/12) − 1`. The annual `rf` is the mean monthly FRED DGS3MO rate over the fund's own window, or the configured fallback when FRED data isn't available. CAGR is a separate metric and is unverifiable below 12 months.
- **Score components** use a percentile rank across eligible funds rather than min-max. That way F007's outlier Sharpe (about 16 with the live FRED risk-free rate) doesn't squeeze every other fund's Sharpe score toward zero.
- **Benchmarks** come from daily adjusted closes, taking the last close of each month and dropping the current partial month. A cache under 24 hours old is used without a live call.
- **Unavailable benchmark:** if a benchmark that an eligible fund needs is unavailable, every eligible fund's correlation component is set to 0 and the run warns `BENCHMARK_UNAVAILABLE`. This keeps scores comparable within the run. A single fund with fewer than 12 overlapping months gets 0 only for itself.
- **Concentration floor:** the floor of one fund per strategy stays, and the run warns `CONCENTRATION_FLOOR_APPLIED` whenever it binds.
- **Strategy matching:** preferred and excluded strategies are compared case-insensitively.

**Why:** Each of these makes a result explainable in one sentence to a committee. Percentile ranks keep one implausible fund from reshaping everyone else's score. Zeroing correlation for the whole run keeps a data outage from rewarding the funds whose benchmark happened to load.

**Consequence:** Scores are ordinal. A fund's score says where it sits among the eligible funds in that run, not how far ahead it is. Removing or adding an eligible fund can change the other funds' component scores.

## Evidence display values are short labels

**Choice:** Data-quality, selection, and notes chips show short labels, such as "Smooth returns", "Rank 1 · score 81.0", and "Manager notes". The full issue message, selection decision, and raw notes text are kept in the record's label and provenance, which the audit drawer shows.

**Why:** Long messages inside chips made memo sentences hard to read. The chip only needs to say what kind of evidence it is; the audit drawer is where a reader checks the detail.

**Consequence:** Existing memos keep their stored evidence snapshot, so older revisions still show the long values they were generated with.

## Prompt memo-v2 after a real guard catch

**Choice:** The system prompt now requires that a claim with a null `fund_id` name every fund whose evidence it cites, by fund ID, in the prose. The prompt version is `memo-v2`.

**Why:** In testing, gpt-6-sol twice wrote multi-fund claims that cited F007 and F004 evidence without naming either fund. The guard flagged both as `CITED_FUND_NOT_NAMED`. The guard caught the problem; the prompt change makes it less likely to recur.

**Consequence:** Revision 3 (memo-v1, flagged) is kept unchanged as the record of the catch. Memos store their `prompt_version`, so v1 and v2 output can be compared.

## The LLM proposes a ranked shortlist within deterministic limits (memo-v3 to memo-v6)

**Choice:** Screens, eligibility, scores, and the baseline shortlist stay deterministic. The memo draft adds `llm_ranking` (an ordered list of eligible funds, each with a rationale claim) and `llm_dropped` (baseline-shortlisted funds left out, each with a rationale claim). The LLM may reorder the baseline, add an eligible fund, or drop a shortlisted one. Deterministic memo-level rules flag a ranked fund that isn't eligible, a fund listed twice, more funds than `max_candidates`, more funds per strategy than the concentration limit, an invalid drop entry, and any fund whose position differs from its baseline shortlist position without citing its own reorder evidence (`LLM_RANK_MOVE_UNCITED`). `LLM_RANK_REWEIGHTS_SCORE` flags a fund A placed above a fund B that ranks above it in the baseline, unless B cites its own DQ or SRC or A cites its own SRC terms or notes. Reorder evidence is only a warning- or error-level DQ, verified SRC terms or notes, or a failing or unverifiable SCR; no MET counts. The prompt (`memo-v6`) says: reorder only on data-quality flags or fund terms and notes, never on metrics, which the score already weighs. Recommendations must name funds in the LLM ranking. Each memo stores the ranking with baseline rank, LLM rank, and delta per fund; the template memo stores the baseline order with source `baseline`.

**Why:** The brief asks for an LLM-produced ranked shortlist. Letting the model reorder only inside the eligible set, under the mandate's capacity and concentration limits, keeps every hard constraint deterministic while letting it act on evidence the score ignores, such as F007's smooth returns and manager notes. Requiring a citation for every move makes each change traceable. In `memo-v3`, the model promoted F003 from fourth to first on correlation, return, and drawdown alone, which re-weighs the formula rather than adding information; `memo-v4` closes that. In `memo-v4` revision 6, the model then promoted F003 to first citing only its notice and lockup screen passes. Every eligible fund passes every screen, so a pass separates nothing: `SCR-*-PASS` records of eligible funds no longer count as evidence for `LLM_RANK_MOVE_UNCITED` or `LLM_RANK_REWEIGHTS_SCORE`. Re-running the guard read-only on revision 6 now flags `LLM_RANK_MOVE_UNCITED` for F003; the stored memo and its clean guard result are kept unchanged. Two further gaps were found in external review and closed in `memo-v6`. C1: the `memo-v4` rule still accepted score-derived metrics such as target gap, excess return, volatility, and months as reasons to reorder; now no MET counts. C2: the pair rule accepted either fund's evidence in either direction, so a fund's own data-quality flag could justify promoting it; the rule is now directional, and a promoted fund can only rest on its own terms or notes. Re-run read-only under the `memo-v6` rules, revisions 5 and 6 are flagged `LLM_RANK_MOVE_UNCITED` for F003 (metrics only and screen passes only), and revision 7 stays clean.

**Consequence:** The guard checks that a move cites the right kind of evidence, not that the evidence justifies the move; the baseline rank shown next to every fund is the reader's check. Memos before `memo-v3` have no stored ranking and keep checking recommendations against the baseline shortlist. AGENTS.md section 1 is amended to match.
