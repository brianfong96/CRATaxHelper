from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ROOT_PATH: str = ""  # Set to /app/cra-taxhelper when deployed via Atlas
    LOG_LEVEL: str = "INFO"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
