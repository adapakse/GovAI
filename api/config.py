import json

from pydantic import Field
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

    # CORS — origins rozdzielone przecinkiem albo JSON-lista (prod: tylko domena
    # kancelarii/klienta). Trzymane jako str (nie list[str]) — pydantic-settings
    # dla pól list[str] próbuje samo zdekodować env jako JSON i wywala się
    # (SettingsError) na zwykłym CSV; parsowanie robimy sami w property niżej.
    allowed_origins_raw: str = Field(
        default="http://localhost:4000,http://localhost:3000",
        alias="ALLOWED_ORIGINS",
    )

    @property
    def allowed_origins(self) -> list[str]:
        """Akceptuje JSON-listę albo string z originami rozdzielonymi przecinkiem."""
        v = self.allowed_origins_raw.strip()
        if v.startswith("["):
            return json.loads(v)
        return [origin.strip() for origin in v.split(",") if origin.strip()]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
