from pydantic import AliasChoices, Field
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

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
