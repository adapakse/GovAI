from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://govai:govai_secret@localhost:5432/govai"
    redis_url: str = "redis://localhost:6379"
    anthropic_api_key: str = ""
    log_level: str = "INFO"

    # Progi Presidio — minimalny poziom pewności wykrycia PII
    pii_confidence_threshold: float = 0.7

    # TTL zadania w kolejce nadzoru (sekundy)
    oversight_ttl_seconds: int = 3600

    # Minimalna liczba sekund przeglądu — poniżej: alert o pozornym nadzorze
    min_review_seconds: int = 10

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
