import os

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_CLOUD_RUNTIME_ENV_VARS = (
    "RAILWAY_ENVIRONMENT",
    "RAILWAY_ENVIRONMENT_NAME",
    "RAILWAY_PROJECT_ID",
    "RAILWAY_SERVICE_ID",
    "RENDER",
    "RENDER_SERVICE_ID",
)


def _is_sqlite_url(database_url: str) -> bool:
    scheme = database_url.strip().lower().split(":", 1)[0]
    return scheme.startswith("sqlite")


def _is_cloud_runtime() -> bool:
    return any(os.getenv(name) for name in _CLOUD_RUNTIME_ENV_VARS)


class Settings(BaseSettings):
    app_name: str = "AI Investment Analyst"
    app_env: str = "dev"
    database_url: str = "sqlite:///./investment_analyst.db"
    recommendation_threshold: float = 75.0
    recommendation_hysteresis_buffer: float = 4.0
    recommendation_hysteresis_minutes: int = 1440
    auto_refresh_enabled: bool = True
    auto_refresh_interval_minutes: int = 15
    # Leaderboard: penalize final_score when headline news_risk is above neutral (see news_risk.py).
    news_ranking_weight: float = 5.0
    news_risk_neutral: float = 32.0
    risk_block_min_confidence: str = "medium"
    alert_webhook_url: str = ""
    # Set AUTH_ENABLED=true (env) to require login again.
    auth_enabled: bool = False
    auth_username: str = "admin"
    auth_password: str = "GoatAnalyst99"
    auth_session_cookie: str = "aiia_session"
    # Optional: reliable quotes on cloud hosts (Yahoo often blocks datacenters).
    # Use QUOTE_API_FINNHUB or IIA_FINNHUB_TOKEN on Railway if a broken "Finnhub" build secret blocks deploy.
    finnhub_api_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "FINNHUB_API_KEY",
            "QUOTE_API_FINNHUB",
            "IIA_FINNHUB_TOKEN",
            "finnhub_api_key",
            "FinnhubApiKey",
        ),
    )
    # Optional fallback: https://www.alphavantage.co/support/#api-key
    alphavantage_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("ALPHAVANTAGE_API_KEY", "alphavantage_api_key", "ALPHA_VANTAGE_API_KEY"),
    )
    # Optional: https://twelvedata.com/ (800 calls/day free)
    twelve_data_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("TWELVE_DATA_API_KEY", "twelve_data_api_key", "TWELVEDATA_API_KEY"),
    )
    # Optional: domain-filtered headlines on GET /recommendations/{ticker} (investor_news). Falls back to Google News RSS.
    newsapi_key: str = Field(
        default="",
        validation_alias=AliasChoices("NEWSAPI_KEY", "newsapi_key", "NEWS_API_KEY"),
    )
    # Trusted-outlet substring filter for investor news (and legacy critical-event helpers in code).
    critical_news_strict_outlets: bool = Field(
        default=True,
        validation_alias=AliasChoices("CRITICAL_NEWS_STRICT_OUTLETS", "critical_news_strict_outlets"),
    )
    critical_news_allowlist: str = Field(
        default=(
            "reuters,bloomberg,wall street journal,wsj,financial times,ft.com,"
            "associated press,ap news,cnbc,bbc,the economist,new york times,nytimes,"
            "washington post,barron,barrons,nikkei,dow jones,marketwatch,fortune,"
            "investopedia,japan times,japantimes"
        ),
        validation_alias=AliasChoices("CRITICAL_NEWS_ALLOWLIST", "critical_news_allowlist"),
    )

    @model_validator(mode="after")
    def require_persistent_database_for_cloud(self) -> "Settings":
        deployed_env = str(self.app_env or "").strip().lower() in {"prod", "production", "staging"}
        database_url = str(self.database_url or "").strip()
        if (deployed_env or _is_cloud_runtime()) and (not database_url or _is_sqlite_url(database_url)):
            raise ValueError(
                "DATABASE_URL must be set to a persistent database for cloud/production deployments"
            )
        return self

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
