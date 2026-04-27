from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Shared ────────────────────────────────────────────────────────────────
    ROOT_PATH: str = ""      # Atlas sets this to /app/cra-taxhelper
    LOG_LEVEL: str = "INFO"

    # ── LOCAL mode (docker compose up — no .env needed) ──────────────────────
    # These are the defaults that docker-compose.yml hardcodes.
    # Override by setting env vars in your shell if desired.
    AUTH_ENABLED: bool = True     # docker-compose.yml sets False → no login
    LOCAL_USER_EMAIL: str = "local@cra-helper.local"
    LOCAL_USER_NAME: str = "Local User"

    # ── PRODUCTION only (aether-data.net deployment) ─────────────────────────
    # Injected at deploy time by deploy.ps1 from Aether/.env and repo root .env.
    # Never stored in atlas-app.json or committed to git.
    SESSION_SECRET: str = ""      # HMAC key for Aether session cookies
    GATEWAY_URL: str = "https://api.aether-data.net"   # login redirect base
    ALLOWED_EMAILS: str = ""      # comma-separated allowlist; empty = any Aether user
    FIELD_ENCRYPTION_KEY: str = ""  # Fernet key; empty = plaintext (local only)

    # ── Archive (both modes, different backends) ──────────────────────────────
    # Local:      ARCHIVE_URL=http://archive:7000  → SQLite sidecar in docker-compose
    # Production: ARCHIVE_URL=http://archive:7000  → real Aether Archive service
    ARCHIVE_URL: str = "http://archive:7000"

    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def is_local(self) -> bool:
        """True when running in local (offline) mode — no Aether auth."""
        return not self.AUTH_ENABLED and not self.SESSION_SECRET

    @property
    def allowed_emails(self) -> set[str]:
        """Set of lowercase emails allowed to use this app. Empty = unrestricted."""
        if not self.ALLOWED_EMAILS:
            return set()
        return {e.strip().lower() for e in self.ALLOWED_EMAILS.split(",") if e.strip()}


settings = Settings()
