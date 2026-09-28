from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://allocator:allocator@postgres:5432/allocator"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    fred_api_key: str = ""
    rf_fallback_annual: float = 0.04
    max_upload_bytes: int = 5 * 1024 * 1024


settings = Settings()
