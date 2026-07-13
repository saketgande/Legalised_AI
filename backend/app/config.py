"""Application configuration.

The database URL defaults to the local Postgres brought up by docker-compose
(or the dev cluster the README describes). Nothing here is secret in dev; a
production deploy overrides via environment variables.
"""
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEV_AUTH_SECRET = "dev-insecure-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # "development" | "production" — production turns on fail-loud secret guards.
    environment: str = "development"

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

    # Optional shared secret for the inbound email webhook (X-Intake-Secret header).
    # Empty -> webhook is open (dev). Set in production. Also authorises the
    # external-scheduler poll endpoint (POST /api/intake/email/poll-cron).
    intake_webhook_secret: str = ""

    # Email-inbox polling. A background loop polls every configured, active mailbox
    # on this cadence and funnels each new message through the intake pipeline.
    # Disable the in-process loop and drive polls from an external cron instead by
    # setting EMAIL_POLLING_ENABLED=false (Render free tier sleeps idle web services).
    email_polling_enabled: bool = True
    email_poll_interval_seconds: int = 120

    # E-signature (DocuSign). When all three are set, the DocuSign client is used;
    # otherwise the stub client keeps the demo working. HMAC key secures the webhook.
    docusign_base_uri: str = ""        # e.g. https://demo.docusign.net/restapi
    docusign_account_id: str = ""
    docusign_access_token: str = ""    # OAuth token (dev). JWT grant is the prod path.
    docusign_connect_hmac: str = ""    # verifies DocuSign Connect webhook signatures
    esign_signer_email: str = ""       # demo override; defaults to the requester's email

    @property
    def docusign_configured(self) -> bool:
        return bool(self.docusign_base_uri and self.docusign_account_id and self.docusign_access_token)

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

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


settings = Settings()


def assert_production_secrets() -> None:
    """Fail loud at startup if a production deploy is missing hardened secrets —
    better a clear boot failure than silently shipping the dev signing key."""
    if not settings.is_production:
        return
    problems: list[str] = []
    if settings.auth_secret == DEV_AUTH_SECRET or len(settings.auth_secret) < 16:
        problems.append("AUTH_SECRET must be a strong random value (>=16 chars)")
    if not settings.intake_webhook_secret:
        problems.append("INTAKE_WEBHOOK_SECRET must be set so the email webhook isn't open")
    if problems:
        raise RuntimeError(
            "Refusing to start in production — insecure config:\n  - " + "\n  - ".join(problems)
        )
