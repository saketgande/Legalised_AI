"""Application configuration.

The database URL defaults to the local Postgres brought up by docker-compose
(or the dev cluster the README describes). Nothing here is secret in dev; a
production deploy overrides via environment variables.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg2://frontdoor:frontdoor@localhost:5432/frontdoor"

    # Optional: when set, contract generation asks Claude to polish the
    # deterministically-assembled draft. Absent -> deterministic assembly only,
    # so the whole product runs end-to-end with no API key (demo stays green).
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-4-8"

    # Front-end origins allowed through CORS in dev (localhost + loopback).
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

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
