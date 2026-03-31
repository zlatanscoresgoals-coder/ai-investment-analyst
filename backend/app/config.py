from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AI Investment Analyst"
    app_env: str = "dev"
    database_url: str = "sqlite:///./investment_analyst.db"
    recommendation_threshold: float = 75.0
    recommendation_hysteresis_buffer: float = 4.0
    recommendation_hysteresis_minutes: int = 1440
    auto_refresh_enabled: bool = True
    auto_refresh_interval_minutes: int = 15
    risk_block_min_confidence: str = "medium"
    alert_webhook_url: str = ""
    auth_enabled: bool = True
    auth_username: str = "admin"
    auth_password: str = "GoatAnalyst99"
    auth_session_cookie: str = "aiia_session"
    # Optional: reliable quotes on cloud hosts (Yahoo often blocks datacenters).
    finnhub_api_key: str = Field(default="", validation_alias="FINNHUB_API_KEY")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
