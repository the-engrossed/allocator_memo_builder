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

## Tests

```bash
make test
```

or:

```bash
docker compose run --rm api pytest -q
```

Tests do not call OpenAI, Yahoo Finance, or FRED.
