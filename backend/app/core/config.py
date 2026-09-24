from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "onboarding-assistant-api"
    version: str = "0.1.0"
    log_level: str = "INFO"

    database_url: str = ""
    redis_url: str = ""

    otel_exporter_otlp_endpoint: str = ""

    mistral_api_key: str = ""

    llm_provider: str = "mistral"
    ollama_base_url: str = "http://localhost:11434"

    mock_oidc: int = 1
    dev_principal_sub: str = "dev-user"
    dev_principal_email: str = "dev@example.com"
    dev_principal_dept: str = "Engineering"
    dev_principal_role: str = "employee"

    session_secret: str = "dev-only-insecure-secret"

    sql_readonly_role: str = "app_readonly"
    sql_statement_timeout_ms: int = 5000
    sql_max_rows: int = 100


@lru_cache
def get_settings() -> Settings:
    return Settings()
