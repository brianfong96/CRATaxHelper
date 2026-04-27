from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ROOT_PATH: str = ""  # Set to /app/cra-taxhelper when deployed via Atlas
    LOG_LEVEL: str = "INFO"

    # Auth — validated against the Aether platform SESSION_SECRET
    SESSION_SECRET: str = ""   # injected at deploy time from Aether .env
    AUTH_ENABLED: bool = True  # set False for local dev without Aether stack
    # URL of the Aether API gateway (used for login redirects)
    GATEWAY_URL: str = "https://api.aether-data.net"

    # Per-app RBAC: comma-separated list of allowed email addresses.
    # Empty string (default) = any whitelisted Aether user may access this app.
    ALLOWED_EMAILS: str = ""

    # Aether Archive service URL for server-side per-user data persistence.
    ARCHIVE_URL: str = "http://archive:7000"

    # Fernet key for encrypting form data at rest in Archive.
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # If empty, data is stored as plaintext (local dev fallback only).
    FIELD_ENCRYPTION_KEY: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def allowed_emails(self) -> set[str]:
        """Set of lowercase emails allowed to use this app. Empty = unrestricted."""
        if not self.ALLOWED_EMAILS:
            return set()
        return {e.strip().lower() for e in self.ALLOWED_EMAILS.split(",") if e.strip()}


settings = Settings()
