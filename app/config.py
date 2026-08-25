from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    database_url: str = "postgresql+asyncpg://taskflow:taskflow@db:5432/taskflow"
    sync_database_url: str = "postgresql+psycopg2://taskflow:taskflow@db:5432/taskflow"

    # Redis / Celery
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/0"
    celery_result_backend: str = "redis://redis:6379/0"

    # Auth
    secret_key: str = "change-me-to-a-long-random-string-before-deploying"
    access_token_expire_minutes: int = 60

    # Cache
    cache_ttl_seconds: int = 60

    # App
    app_env: str = "development"

    from pydantic import model_validator

    @model_validator(mode="after")
    def validate_security(self) -> "Settings":
        if self.app_env.lower() in ("production", "prod") and (
            "change-me" in self.secret_key or len(self.secret_key) < 32
        ):
            raise ValueError(
                "CRITICAL SECURITY RISK: Production environment requires a secure, random SECRET_KEY "
                "(minimum 32 characters). Set the SECRET_KEY environment variable."
            )
            
        # Automatically fix standard postgresql:// URLs for asyncpg/psycopg2 drivers
        if self.database_url and self.database_url.startswith("postgresql://"):
            self.database_url = self.database_url.replace(
                "postgresql://", "postgresql+asyncpg://", 1
            )
            
        if self.sync_database_url and self.sync_database_url.startswith("postgresql://"):
            self.sync_database_url = self.sync_database_url.replace(
                "postgresql://", "postgresql+psycopg2://", 1
            )
            
        return self


settings = Settings()
