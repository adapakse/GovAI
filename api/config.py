from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://govai:govai_secret@localhost:5432/govai"
    redis_url: str = "redis://localhost:6379"
    anthropic_api_key: str = ""
    classifier_model: str = "claude-sonnet-4-6"
    gateway_url: str = "http://gateway:8001"

    # JWT — wygeneruj własny sekret: python -c "import secrets; print(secrets.token_hex(32))"
    jwt_secret: str = "ZMIEN_MNIE_NA_LOSOWY_32_BAJTOWY_KLUCZ_HEX"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 7

    # CORS — lista dozwolonych origins (prod: tylko domena kancelarii)
    allowed_origins: list[str] = ["http://localhost:4000", "http://localhost:3000"]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
