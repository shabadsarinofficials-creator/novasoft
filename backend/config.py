from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "BizSuite"
    APP_ENV: str = "development"
    DATABASE_URL: str = "postgresql://bizsuite:password@localhost:5432/bizsuite"
    LEGACY_DATABASE_URL: str | None = None
    SECRET_KEY: str = "dev-secret-change-me-in-production-32chars"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    ADMIN_NAME: str = "Administrator"
    ADMIN_EMAIL: str = "admin@novasoft.local"
    ADMIN_PASSWORD: str = "ChangeMeImmediately123!"
    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_MB: int = 20
    # "*" = same-origin friendly for single-service deploy (API + UI together)
    CORS_ORIGINS: str = "*"

    @property
    def cors_origins_list(self) -> List[str]:
        raw = [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]
        if raw == ["*"]:
            return ["*"]
        return raw

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_MB * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
