from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Shared ────────────────────────────────────────────────────────────────
    ROOT_PATH: str = ""      # Atlas sets this to /app/cra-taxhelper
    LOG_LEVEL: str = "INFO"

    # ── LOCAL / DESKTOP mode ─────────────────────────────────────────────────
    # docker-compose.yml sets AUTH_ENABLED=false for local mode.
    # desktop.py sets AUTH_ENABLED=false and DESKTOP_MODE=true.
    AUTH_ENABLED: bool = True
    DESKTOP_MODE: bool = False    # True when running as packaged desktop app
    LOCAL_USER_EMAIL: str = "local@cra-helper.local"
    LOCAL_USER_NAME: str = "Local User"

    # ── PRODUCTION only (aether-data.net deployment) ─────────────────────────
    SESSION_SECRET: str = ""
    GATEWAY_URL: str = "https://api.aether-data.net"
    ALLOWED_EMAILS: str = ""
    FIELD_ENCRYPTION_KEY: str = ""

    # ── Archive ───────────────────────────────────────────────────────────────
    # Local:      ARCHIVE_URL=http://archive:7000  → SQLite sidecar
    # Production: ARCHIVE_URL=http://archive:7000  → real Aether Archive
    # Desktop:    ARCHIVE_URL=""                   → localStorage only
    ARCHIVE_URL: str = "http://archive:7000"

    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def is_local(self) -> bool:
        """True when running in local (offline) mode — no Aether auth."""
        return not self.AUTH_ENABLED and not self.SESSION_SECRET

    @property
    def is_desktop(self) -> bool:
        """True when running as a packaged Electron desktop application."""
        return self.DESKTOP_MODE

    @property
    def allowed_emails(self) -> set[str]:
        """Set of lowercase emails allowed to use this app. Empty = unrestricted."""
        if not self.ALLOWED_EMAILS:
            return set()
        return {e.strip().lower() for e in self.ALLOWED_EMAILS.split(",") if e.strip()}


settings = Settings()
