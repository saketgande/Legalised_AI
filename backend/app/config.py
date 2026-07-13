"""Application configuration.

The database URL defaults to the local Postgres brought up by docker-compose
(or the dev cluster the README describes). Nothing here is secret in dev; a
production deploy overrides via environment variables.
"""
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg2://frontdoor:frontdoor@localhost:5432/frontdoor"

    # Optional: when set, contract generation asks Claude to polish the
    # deterministically-assembled draft. Absent -> deterministic assembly only,
    # so the whole product runs end-to-end with no API key (demo stays green).
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-4-8"

    # Seed the reference data (playbook, reviewers) on startup if the DB is empty.
    # Handy for one-click deploys where there's no separate seed step.
    seed_on_start: bool = False

    # Auth. Override AUTH_SECRET in production. AUTH_DEMO_PASSWORD is the password
    # the seed sets on every seeded user so the deployed demo is loginnable.
    auth_secret: str = "dev-insecure-change-me"
    auth_token_ttl_hours: int = 12
    auth_demo_password: str = "demo1234"

    # Comma-separated list of allowed front-end origins. In production set
    # CORS_ORIGINS to the deployed web URL, e.g. "https://legalised-web.onrender.com".
    cors_origins_raw: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000",
        validation_alias="CORS_ORIGINS",
    )

    @field_validator("database_url")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        # Managed hosts (Render/Heroku/Neon) hand out postgres:// or postgresql://
        # URLs; pin the psycopg2 driver so SQLAlchemy 2.0 accepts them.
        if v.startswith("postgres://"):
            v = "postgresql+psycopg2://" + v[len("postgres://"):]
        elif v.startswith("postgresql://"):
            v = "postgresql+psycopg2://" + v[len("postgresql://"):]
        return v

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins_raw.split(",") if o.strip()]

    # Triage policy for the outbound golden path (the auto-send gate).
    auto_max_term_months: int = 24
    auto_allowed_purposes: list[str] = [
        "sales_evaluation",
        "vendor_evaluation",
        "hiring",
        "partnership_exploration",
    ]
    auto_allowed_jurisdictions: list[str] = ["US", "US-CA", "US-NY", "US-DE"]


settings = Settings()
