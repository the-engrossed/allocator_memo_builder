from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py locally; /app/app/config.py in the API container, where the
# repository's sample_data/ directory is mounted at /sample_data.
_APP_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://allocator:allocator@postgres:5432/allocator"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    fred_api_key: str = ""
    rf_fallback_annual: float = 0.04
    max_upload_bytes: int = 5 * 1024 * 1024
    benchmark_cache_dir: Path = _APP_DIR.parent / ".cache" / "benchmarks"
    benchmark_snapshot_dir: Path = _APP_DIR.parents[1] / "sample_data"
    market_data_timeout_seconds: float = 10.0


settings = Settings()
