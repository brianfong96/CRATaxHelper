from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ROOT_PATH: str = ""  # Set to /app/cra-taxhelper when deployed via Atlas
    LOG_LEVEL: str = "INFO"

    # Auth — validated against the Aether platform SESSION_SECRET
    SESSION_SECRET: str = ""   # injected at deploy time from Aether .env
    AUTH_ENABLED: bool = True  # set False for local dev without Aether stack
    # URL of the Aether API gateway (used for login redirects)
    GATEWAY_URL: str = "https://api.aether-data.net"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
