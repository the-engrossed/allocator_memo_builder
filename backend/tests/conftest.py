# pytest configuration lives in pyproject.toml
#
# Postgres-backed tests run only against an explicit TEST_DATABASE_URL whose database name
# ends in "_test". DATABASE_URL is overridden before any app module is imported so the
# application engine can never point at the development database during tests.
import os

_TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")
if _TEST_DATABASE_URL:
    os.environ["DATABASE_URL"] = _TEST_DATABASE_URL

import uuid  # noqa: E402
from collections.abc import Generator, Iterator  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import Engine, create_engine, make_url, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

_BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline_market_data(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No test may reach Yahoo Finance or FRED; caches and snapshots live in tmp_path."""
    from app.config import settings
    from app.services import benchmarks

    def _offline(*_args: object, **_kwargs: object) -> None:
        raise benchmarks.MarketDataError("Network access is disabled in tests.")

    monkeypatch.setattr(benchmarks, "fetch_yahoo_daily_closes", _offline)
    monkeypatch.setattr(benchmarks, "fetch_fred_monthly_rates", _offline)
    monkeypatch.setattr(settings, "benchmark_cache_dir", tmp_path / "benchmark_cache")
    monkeypatch.setattr(settings, "benchmark_snapshot_dir", tmp_path / "benchmark_snapshot")
    monkeypatch.setattr(settings, "fred_api_key", "")
    monkeypatch.setattr(settings, "rf_fallback_annual", 0.04)


@pytest.fixture(autouse=True)
def offline_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test may reach OpenAI: no key, and constructing a client fails loudly."""
    from app.config import settings
    from app.services import memo_generator

    def _no_client() -> None:
        raise AssertionError("Tests must not construct a real OpenAI client.")

    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(memo_generator, "make_openai_client", _no_client)


@pytest.fixture
def live_benchmarks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Synthetic month-end closes standing in for Yahoo Finance; no real market data in tests."""
    import numpy as np
    import pandas as pd

    from app.seed.sample_data import MARKET
    from app.services import benchmarks

    month_ends = pd.date_range("2021-08-31", periods=len(MARKET) + 1, freq="ME")
    spy = pd.Series(100 * np.cumprod([1.0, *(1 + r for r in MARKET)]), index=month_ends)
    agg_returns = [0.002 + 0.1 * r for r in MARKET]
    agg = pd.Series(100 * np.cumprod([1.0, *(1 + r for r in agg_returns)]), index=month_ends)
    partial = pd.Timestamp("2026-09-15")
    closes = {
        "SPY": pd.concat([spy, pd.Series([999.0], index=[partial])]),
        "AGG": pd.concat([agg, pd.Series([999.0], index=[partial])]),
    }
    monkeypatch.setattr(benchmarks, "fetch_yahoo_daily_closes", lambda ticker, timeout: closes[ticker])


@pytest.fixture(scope="session")
def pg_engine() -> Iterator[Engine]:
    if not _TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is not set; skipping Postgres-backed tests.")
    url = make_url(_TEST_DATABASE_URL)
    if not (url.database or "").endswith("_test"):
        raise pytest.UsageError(
            f"TEST_DATABASE_URL must name a database ending in '_test'; got {url.database!r}."
        )

    from app.config import settings

    if settings.database_url != _TEST_DATABASE_URL:
        raise pytest.UsageError("App settings were loaded before the test database override.")

    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        exists = connection.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": url.database}
        )
        if not exists:
            connection.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()

    alembic_config = Config(str(_BACKEND_DIR / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    command.upgrade(alembic_config, "head")

    engine = create_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(pg_engine: Engine) -> Iterator[Session]:
    connection = pg_engine.connect()
    transaction = connection.begin()
    session = Session(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    from app.database import get_db
    from app.main import app

    def _override_get_db() -> Generator[Session, None, None]:
        try:
            yield db_session
            db_session.commit()
        except Exception:
            db_session.rollback()
            raise

    app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def analysis_id(db_session: Session) -> uuid.UUID:
    from app.domain.models import Analysis

    analysis = Analysis(
        id=uuid.uuid4(),
        filename="fixture.csv",
        sha256="0" * 64,
        uploaded_at=datetime.now(timezone.utc),
        row_count=0,
        fund_count=0,
        status="valid",
        column_mapping={},
    )
    db_session.add(analysis)
    # Commit releases the savepoint so a failed request's rollback cannot discard the fixture;
    # the outer test transaction still rolls everything back at teardown.
    db_session.commit()
    return analysis.id
