# IC Memo Workbench

Turns a messy fund-universe CSV and an allocator mandate into a screened, ranked shortlist and a draft Investment Committee memo in which every figure links back to its source.

**Thesis:** Python owns every number. The LLM only writes claims that point to evidence IDs, and a deterministic claim guard checks every claim before a person reads it.

## Workflow

1. **Upload & Validation.** Upload a CSV. Columns are mapped, return units are inferred per fund, and every row is validated. Issues are listed with row numbers; blocking issues remove a fund from analysis.
2. **Mandate.** Set hard screens (fees, liquidity, notice, lockup, volatility, drawdown, track record, excluded strategies) and shortlist construction (preferred strategies, concentration cap, number of candidates).
3. **Analysis & Ranking.** Benchmarks and the risk-free rate are resolved and recorded with provenance. Funds are screened, eligible funds are scored and ranked, and a shortlist is built. Each run is stored immutably.
4. **IC Memo & Audit.** The LLM drafts the memo from the stored run. Every figure renders as a chip; clicking it opens an audit drawer with the evidence record and its provenance. Guard results appear on each claim and in a banner. A template memo (no LLM) is always available.

![Analysis and ranking](docs/screenshots/analysis-ranking.png)
![Memo with claim guard](docs/screenshots/memo-audit.png)
![Audit drawer](docs/screenshots/audit-drawer.png)

## Demo walkthrough

1. `docker compose up --build`, then open <http://localhost:5173>.
2. Upload `sample_data/sample_fund_universe.csv`. Note F009 blocked (`RETURN_OUT_OF_RANGE`), F007 flagged `SMOOTH_RETURNS`, F001/F010 flagged `FUND_ID_MISMATCH`.
3. Save the default mandate.
4. Run the analysis. Check the benchmark provenance bar, F005 excluded on liquidity and lockup, F007 ranked first, F006 `CAPACITY_REACHED`.
5. Generate the memo. Click the chips for `MET-F007-SHARPE` and `SRC-F007-NOTES` in the recommendation; open the audit drawer.
6. Run `docker compose exec api python -m scripts.guard_demo --run <run_id>` (the run ID is on the Analysis page; from `backend/` with the venv, `python -m scripts.guard_demo --run <run_id>` works too) and see the four planted claims flagged. Back in the UI, click **Generate template memo (no LLM)** and switch between revisions.

## Architecture

```mermaid
flowchart LR
    UI[React + Vite UI] -->|/api| API[FastAPI routes]
    API --> ING[Ingestion]
    API --> VAL[Validation]
    API --> BMK[Benchmarks]
    API --> MET[Metrics]
    API --> RNK[Screening, ranking, shortlist]
    API --> REG[Evidence registry]
    API --> GEN[Memo generator]
    API --> GRD[Claim guard]
    ING & VAL & RNK & GEN --> DB[(PostgreSQL)]
    REG --> DB
    BMK -. SPY, AGG .-> YF[(Yahoo Finance / yfinance)]
    BMK -. DGS3MO .-> FRED[(FRED)]
    GEN -. structured output .-> OAI[(OpenAI)]
```

Routes are thin; all logic lives in `backend/app/services/`. Metrics, ranking, and the claim guard are pure functions with no I/O. Stack: React 19, TypeScript, Tailwind, Vite; Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, pandas/numpy; PostgreSQL 16; Docker Compose.

Design decisions and trade-offs: see [DECISIONS.md](DECISIONS.md).

## Data model

| Table | Holds |
| --- | --- |
| `Analysis` | One uploaded file: filename, sha256, column mapping, status. |
| `SourceRow` | Every raw CSV row as uploaded, with its row number. |
| `ValidationIssue` | Code, severity, fund, field, row numbers, details. |
| `Mandate` | One per analysis, fully replaced on save. All thresholds are integer basis points. |
| `RankingRun` | Mandate snapshot and its sha256, policy version, benchmark provenance, score weights, warnings. |
| `FundEvaluation` | Per fund per run: inputs, metrics, screen results, score components, rank, selection reason, data-quality items. |
| `MemoArtifact` | Revisioned memo per run: claims, guard results and summary, appendix, evidence snapshot, model, prompt version, token usage, fallback reason. |

Immutability: a run copies the mandate it used and stores its sha256, so editing the mandate later creates a new run and leaves the old one unchanged. Memos are numbered revisions per run and are never updated. Each memo stores the full evidence registry it was generated against (`evidence_snapshot`), so its chips resolve the same way forever.

## Ranking policy (v1)

**Screens** return `pass`, `fail`, or `unverifiable`. Only funds that pass every screen are eligible. A screen whose input is missing or invalid is `unverifiable`, which excludes the fund; no default is substituted. Screens: blocking validation, liquidity frequency, notice days, lockup months, management fee, performance fee, volatility, max drawdown, track record, excluded strategy. Thresholds are inclusive.

**Metrics** (rounded once at persistence: rates to integer bps, half away from zero; Sharpe and correlation to 2 decimals):

| Metric | Definition |
| --- | --- |
| Annualized return | `prod(1 + r)^(12/n) − 1`; unverifiable when n < 12 |
| Volatility | sample std (ddof = 1) × √12 |
| Sharpe | `mean(r − rf_m) / std(r) × √12`, `rf_m = (1 + rf)^(1/12) − 1`, rf = mean DGS3MO over the fund's window |
| Max drawdown | largest peak-to-trough loss of a wealth index starting at 1.0 |
| Correlation | Pearson vs mapped benchmark (Credit → AGG, else SPY); needs ≥ 12 overlapping months |
| Excess return | fund CAGR − benchmark CAGR over overlapping months; reporting only |
| Target gap | annualized return − mandate target; reporting only |

**Scoring:** each component is a percentile rank across eligible funds (ties averaged, a single fund scores 100), then weighted with locked weights: Sharpe 45, annualized return 25, drawdown resilience 20, low correlation 10. An unverifiable component scores 0 and is flagged. If a benchmark an eligible fund needs is unavailable, the correlation component is 0 for every fund and the run warns `BENCHMARK_UNAVAILABLE`.

**Tie-breakers:** total score desc, target gap desc (missing last), management fee asc, performance fee asc, fund name (case-insensitive), fund ID.

**Shortlist:** pass 1 takes funds in preferred strategies in rank order; pass 2 fills remaining slots from the rest. Each strategy is limited to `max(1, floor(max_candidates × cap / 10000))` funds; when the floor of one binds, the run warns `CONCENTRATION_FLOOR_APPLIED`. Every eligible fund gets a reason: `SELECTED_PREFERENCE_PASS`, `SELECTED_RANK_PASS`, `CONCENTRATION_SKIP`, or `CAPACITY_REACHED`.

## Evidence IDs and the claim guard

The evidence registry is built from one persisted run. Every figure the memo may show has an ID:

| Prefix | Example | Meaning |
| --- | --- | --- |
| `MET` | `MET-F007-SHARPE`, `MET-F001-CORRELATION-SPY` | Computed metric |
| `SRC` | `SRC-F005-LOCKUP-MONTHS`, `SRC-F007-NOTES` | Source field from the upload |
| `DQ` | `DQ-F007-SMOOTH-RETURNS-NET-RETURN` | Validation issue (suffixed `-2`, `-3` when repeated) |
| `SCR` | `SCR-F005-LOCKUP-FAIL` | Screen result |
| `SEL` | `SEL-F006-CAPACITY-REACHED` | Selection decision |
| `BMK` | `BMK-SPY`, `BMK-AGG`, `BMK-RF` | Benchmark or risk-free series and its provenance |
| `RUN` | `RUN-CONCENTRATION-FLOOR-APPLIED` | Run-level warning |

The LLM returns structured claims (text, `evidence_ids`, claim type, fund). Figures appear only as `[[EVIDENCE-ID]]` markers, which the UI replaces with the registry's display value. The guard flags claims; it never edits or deletes them.

| Rule | Flags |
| --- | --- |
| `UNKNOWN_EVIDENCE` | A marker or cited ID not in the registry |
| `MARKER_NOT_CITED` | A marker missing from `evidence_ids` |
| `CITED_NOT_MARKED` | A cited ID not used as a marker |
| `QUANTITATIVE_WITHOUT_EVIDENCE` | A quantitative claim with no evidence |
| `DIGITS_OUTSIDE_MARKERS` | Digits in prose outside markers (fund IDs, names, strategies, and month-year labels allowed) |
| `CROSS_FUND_EVIDENCE` | A claim about one fund citing another fund's evidence (`BMK`, `RUN` allowed) |
| `CITED_FUND_NOT_NAMED` | A multi-fund claim that cites a fund's evidence without naming that fund |
| `RATIONALE_FUND_MISMATCH` | A claim inside one fund's rationale about a different fund |
| `NOT_SHORTLISTED_RECOMMENDATION` | A recommendation for a fund not on the shortlist |
| `UNVERIFIED_EVIDENCE_AS_FACT` | A quantitative claim relying on unverifiable, invalid, or missing evidence |
| `SHORTLIST_RATIONALE_COVERAGE` (memo) | Rationale does not cover each shortlisted fund once, in rank order |
| `TOP_FUND_DATA_QUALITY_UNADDRESSED` (memo) | The recommendation does not cite the top fund's data-quality issues and notes |

The memo's guard status is `clean` only when no claim is flagged and there are no memo-level issues. `scripts/guard_demo.py` appends four planted bad claims to a stored memo and runs the same guard read-only.

## Benchmarks and fallbacks

| Input | Order |
| --- | --- |
| SPY, AGG (yfinance) | cache under 24 h → live → cache of any age → committed snapshot (`sample_data/benchmark_fallback_{spy,agg}.csv`) → unavailable |
| Risk-free (FRED DGS3MO) | cache under 24 h → live if `FRED_API_KEY` is set → cache of any age → `RF_FALLBACK_ANNUAL` (4%) |
| Memo (OpenAI) | one structured-output call (one retry on connection errors) → deterministic template memo on any failure |

Daily closes are resampled to month-end and the current partial month is dropped. Market data calls time out after 10 s, OpenAI after 120 s. Every run records the state (`live`, `cached`, `fallback`, `unavailable`) and source of each series, and every template memo records why it was used (for example `OPENAI_API_KEY is not set`, `timeout`, `schema_parse_failure`, or `template requested`). The template memo goes through the same guard.

## Security

- Keys live only in `.env`, which is excluded by `.gitignore`, `.dockerignore`, and `.cursorignore`. Every key is optional.
- API keys are never logged, persisted, or returned. Provider error messages pass through `redact_secrets` before they are stored as a failure reason.
- Fund names and notes are untrusted. In the prompt they sit inside an `<untrusted_fund_data>` block, JSON-encoded with `<` and `>` escaped, and the system prompt tells the model to treat them as data. The UI renders them as plain text.

## Setup from a clean clone

Requires Docker Desktop.

```bash
cp .env.example .env    # optional; add OPENAI_API_KEY and FRED_API_KEY if you have them
docker compose up --build
```

Open <http://localhost:5173>. The API is at <http://localhost:8000/api/health>. Migrations run on API start. Without `.env` the app still runs: memos use the template, the risk-free rate uses 4%, and benchmarks fall back to the committed snapshots if Yahoo Finance is unreachable.

| Command | Does |
| --- | --- |
| `make up` | `docker compose up --build` |
| `make down` | stop containers (add `-v` to `docker compose down` to wipe the database) |
| `make test` | backend tests inside the API container against `allocator_test` |
| `make logs` | follow API and web logs |

On macOS, if `docker compose up` fails with `mkdir /host_mnt/...: operation not permitted`, Docker Desktop cannot read the folder the repo is in (common under `~/Documents`, `~/Desktop`, or `~/Downloads`). Grant Docker Desktop Full Disk Access (System Settings → Privacy & Security), then restart Docker. If that doesn't help, move the repo outside `~/Documents` (for example to `~/code`).

## Tests

278 backend tests, all against PostgreSQL. None call OpenAI, Yahoo Finance, or FRED: fixtures stub those clients, and a test that tries to build a real OpenAI client fails.

| Layer | Files | Tests |
| --- | --- | --- |
| Pure functions | `test_metrics.py`, `test_ranking.py`, `test_claim_guard.py` | 60 |
| Ingestion, validation, benchmark resolution | `test_ingestion.py`, `test_validation.py`, `test_benchmarks.py` | 92 |
| API and services on Postgres | `test_mandates.py`, `test_ranking_runs.py`, `test_memos.py` | 123 |
| End-to-end demo path and guard demo script | `test_e2e_demo.py`, `test_guard_demo.py` | 3 |

In a container:

```bash
make test
```

On the host, with the compose Postgres running:

```bash
cd backend
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
TEST_DATABASE_URL=postgresql+psycopg://allocator:allocator@localhost:5432/allocator_test .venv/bin/pytest -q
```

`TEST_DATABASE_URL` must name a database ending in `_test`; it is created and migrated automatically. The frontend has no test suite; `npm run build` in `frontend/` runs the TypeScript strict check.

## Limitations

- The guard checks citations, not meaning. A claim can cite the right ID and still characterize it wrongly. The audit drawer is the human check.
- Scores are percentiles within the uploaded universe, so adding or removing a fund can change other funds' scores.
- Fund terms (fees, liquidity, notice, lockup, notes) come from each fund's first source row; conflicting later values are reported, not merged.
- Memo generation is a synchronous request of roughly 40–50 seconds.
- The sample universe is synthetic, generated by `backend/app/seed/sample_data.py`.
- There is no authentication.
- The LLM explains the deterministic shortlist; it cannot change it.

## What I'd do next

- Let the LLM propose ranking adjustments, each with a cited justification, as a separate reviewable layer on top of the deterministic ranking.
- Add a semantic check that a claim's wording matches what its cited evidence says.
- Build an evaluation set of runs and expected guard outcomes, tracked by `prompt_version`.
- Move memo generation to a background job with progress reporting.
- Add authentication and per-user analyses.
