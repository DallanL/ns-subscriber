from pydantic_settings import BaseSettings, SettingsConfigDict  # type: ignore
from pydantic import Field


class Settings(BaseSettings):
    # App Settings
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    # Security
    ENCRYPTION_KEY: str = Field(..., min_length=1)

    # Netsapiens OAuth - Used for background maintenance
    NS_CLIENT_ID: str = "client_id"
    NS_CLIENT_SECRET: str = "client_secret"
    NS_API_URL: str = Field(..., min_length=1)
    ALLOWED_ORIGINS: str = Field(..., min_length=1)

    # Database
    DATABASE_URL: str = (
        "postgresql+asyncpg://ns_user:ns_password@localhost/ns_subscriber"
    )

    # Subscription Settings
    SUBSCRIPTION_DURATION_DAYS: int = 7
    SUBSCRIPTION_RENEWAL_WINDOW_HOURS: int = 24

    # API Throttling
    NS_API_MAX_REQUESTS_PER_SECOND: float = 5.0

    # Public URL for the API (used in JS injection)
    PUBLIC_API_URL: str = "http://localhost:8000/api/debug"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()  # type: ignore
