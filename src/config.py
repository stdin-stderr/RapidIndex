from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str
    redis_url: str | None = None

    # External API keys
    tmdb_api_key: str | None = None
    tpdb_api_key: str | None = None

    # xxxclub ingester
    xxxclub_enabled: bool = False
    xxxclub_interval_seconds: int = 3600
    xxxclub_page_concurrency: int = 3
    xxxclub_start_id: int = 1
    xxxclub_request_delay_ms: int = 1000
    xxxclub_consecutive_error_limit: int = 100

    # Spotnet ingester
    spotnet_nntp_host: str | None = None
    spotnet_nntp_port: int = 563
    spotnet_nntp_ssl: bool = True
    spotnet_nntp_user: str | None = None
    spotnet_nntp_pass: str | None = None
    spotnet_newsgroups: str = "free.pt"
    spotnet_max_age_days: int = 90
    spotnet_interval_seconds: int = 3600

    # Pipeline / enrichment
    metadata_min_score: float = 0.65
    tmdb_requests_per_10s: int = 40
    tpdb_requests_per_second: int = 5
    re_enrich_failed_after_days: int | None = None
    tmdb_cast_limit: int = 20

    # API server
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_base_url: str = "http://localhost:8000"

    # Stremio
    stremio_enabled: bool = True

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
