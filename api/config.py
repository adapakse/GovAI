from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://govai:govai_secret@localhost:5432/govai"
    redis_url: str = "redis://localhost:6379"
    anthropic_api_key: str = ""
    classifier_model: str = "claude-sonnet-4-6"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
