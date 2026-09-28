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

    # Attempts per model call, and the pause before the first retry. A key with a
    # real per-minute ceiling needs to wait it out; one locked out of a model does
    # not, and is handled by moving to a stand-in instead.
    llm_max_attempts: int = 4
    llm_retry_base_delay_s: float = 2.0
    llm_retry_max_delay_s: float = 30.0

    mock_oidc: int = 1
    dev_principal_sub: str = "dev-user"
    dev_principal_email: str = "dev@example.com"
    dev_principal_dept: str = "Engineering"
    dev_principal_role: str = "employee"

    # OIDC (production auth path). Setting an issuer and client id enables the
    # authorization-code flow; MOCK_OIDC stays for local dev and the demo.
    # The issuer must match the token's `iss` claim exactly.
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_audience: str = ""
    oidc_scope: str = "openid profile email"
    oidc_authorize_url: str = ""
    oidc_token_url: str = ""
    oidc_jwks_url: str = ""
    oidc_dept_claim: str = "dept"
    oidc_role_claim: str = "role"
    oidc_email_claim: str = "email"
    # Comma-separated allowlists. An empty department list accepts any
    # non-empty department claim; a role outside the list degrades to the
    # least-privileged role and is reported as claim drift.
    oidc_allowed_departments: str = ""
    oidc_allowed_roles: str = "employee,admin"

    session_secret: str = "dev-only-insecure-secret"

    # Per-user daily token budget (tokens in + out, summed across models). The
    # request that would reach the cap is rejected; 0 disables the cap. The
    # spend threshold only raises a runaway alert, it never blocks.
    daily_token_budget: int = 200_000
    daily_cost_alert_usd: float = 1.0

    # Moderation screen over user input and ingested content. It never blocks;
    # it flags abuse/personal data for the redaction layer and observability.
    moderation_enabled: bool = True

    # Retention window for query audit logs and eval-run records.
    retention_days: int = 90

    # Incoming-webhook URL for the nightly eval alert. Empty disables posting.
    slack_eval_webhook_url: str = ""

    # Base URL of the trace backend (Tempo HTTP API) for the admin span viewer.
    tempo_url: str = ""

    sql_readonly_role: str = "app_readonly"
    sql_statement_timeout_ms: int = 5000
    sql_max_rows: int = 100


@lru_cache
def get_settings() -> Settings:
    return Settings()
