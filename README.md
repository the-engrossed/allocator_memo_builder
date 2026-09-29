# IC Memo Workbench

Local prototype that turns a fund-universe CSV into a defendable Investment Committee memo draft. Python owns data, math, screening, ranking, and every displayed number. The LLM owns explanatory narrative only.

This slice covers **CSV upload, normalization, validation, persistence, and the Upload & Validation UI**.

## Setup

1. Copy `.env.example` to `.env`.
2. From the repository root:

```bash
docker compose up --build
```

3. Open [http://localhost:5173](http://localhost:5173).
4. Upload `sample_data/sample_fund_universe.csv`.

The sample universe is synthetic and generated deterministically. Its planted demo cases are
documented in `backend/app/seed/sample_data.py`. To regenerate it, run from `backend/`:

```bash
python -m app.seed.sample_data
```

The API is at [http://localhost:8000](http://localhost:8000) (`GET /api/health`).

After pulling dependency changes, rebuild the API image with `docker compose build api`.

## Benchmarks and ranking

`POST /api/analyses/{id}/ranking-runs` screens, scores, and shortlists the funds against the saved mandate, and stores an immutable run. `GET /api/analyses/{id}/ranking-runs/latest` and `GET /api/ranking-runs/{run_id}` read runs back.

SPY and AGG come live from Yahoo Finance. When the live call fails, the app falls back to a local cache, then to the committed snapshots in `sample_data/benchmark_fallback_{spy,agg}.csv`. The risk-free rate comes from FRED DGS3MO when `FRED_API_KEY` is set, and otherwise from `RF_FALLBACK_ANNUAL`. Every run records which source it used.

To refresh the snapshots from Yahoo Finance, run from `backend/`:

```bash
python -m scripts.refresh_benchmark_snapshot
```

## Tests

```bash
make test
```

or:

```bash
docker compose run --rm api pytest -q
```

Tests do not call OpenAI, Yahoo Finance, or FRED.
