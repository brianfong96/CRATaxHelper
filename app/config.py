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
    # SESSION_SECRET is only used for legacy X-Aether-Internal calls.
    SESSION_SECRET: str = ""
    # Mandatory audience-scoped keys for the previous/current/next three-day UTC
    # periods. The hosted service never derives keys or falls back to a static
    # secret; deployments must provide all six values.
    AETHER_AUTH_PREVIOUS_KEY_ID: str = ""
    AETHER_AUTH_PREVIOUS_SECRET_HEX: str = ""
    AETHER_AUTH_KEY_ID: str = ""
    AETHER_AUTH_SECRET_HEX: str = ""
    AETHER_AUTH_NEXT_KEY_ID: str = ""
    AETHER_AUTH_NEXT_SECRET_HEX: str = ""
    # Archive-only local/test compatibility. User-session verification never
    # consults this flag and never falls back to SESSION_SECRET.
    AETHER_ALLOW_MASTER_KEY_FALLBACK: bool = False
    GATEWAY_URL: str = "https://api.aether-data.net"
    ALLOWED_EMAILS: str = ""
    FIELD_ENCRYPTION_KEY: str = ""

    # ── Archive ───────────────────────────────────────────────────────────────
    # Local:      ARCHIVE_URL=http://archive:7000  → SQLite sidecar
    # Production: ARCHIVE_URL=http://archive:7000  → real Aether Archive
    # Desktop:    ARCHIVE_URL=""                   → localStorage only
    ARCHIVE_URL: str = "http://archive:7000"
    # Dedicated internal secret for outbound X-Aether-Internal Archive admin calls
    # (project/table/RLS provisioning, role grants). Purpose-separated from the
    # platform master SESSION_SECRET so hosted CRA never receives the master.
    # Production must set this; a SESSION_SECRET fallback is available only for
    # local/tests when AETHER_ALLOW_MASTER_KEY_FALLBACK is enabled.
    ARCHIVE_INTERNAL_SECRET: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def archive_internal_secret(self) -> str:
        """Resolved secret sent as X-Aether-Internal on Archive admin calls.

        Uses the dedicated ARCHIVE_INTERNAL_SECRET so the platform master
        SESSION_SECRET never leaves this service. Falls back to SESSION_SECRET
        only when AETHER_ALLOW_MASTER_KEY_FALLBACK is enabled (local/tests);
        production fails closed (returns "") when the dedicated secret is missing.
        """
        if self.ARCHIVE_INTERNAL_SECRET:
            return self.ARCHIVE_INTERNAL_SECRET
        if self.AETHER_ALLOW_MASTER_KEY_FALLBACK and self.SESSION_SECRET:
            return self.SESSION_SECRET
        return ""

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
