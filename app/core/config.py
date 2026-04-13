from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    PROJECT_NAME: str = "AVA MJ Backend"
    API_V1_PREFIX: str = "/api/v1"
    DATABASE_URL: str = "sqlite:///./avamj.db"
    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7
    MOODLE_URL: str = "https://seu-moodle"
    MOODLE_TOKEN: str = "moodle-token"
    # Relativo ao pacote `app/` (ver app.core.media_urls.h5p_content_root).
    H5P_CONTENT_DIR: str = "templates/static/h5p"
    # URL pública dos pacotes H5P extraídos (montada em app.main com StaticFiles).
    # Em produção (Railway), defina H5P_CONTENT_DIR=/data/h5p e mantenha o prefixo /h5p.
    H5P_URL_PREFIX: str = "/h5p"
    # Avatares e outros uploads de usuário (montado em /media).
    USER_UPLOAD_DIR: str = "templates/static/uploads"
    APP_ENV: str = "development"
    APP_DEBUG: bool = False
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    COOKIE_SECURE: bool = False
    COOKIE_DOMAIN: str | None = None
    ACCESS_COOKIE_NAME: str = "access_token"
    REFRESH_COOKIE_NAME: str = "refresh_token"
    RATE_LIMIT_DEFAULT: str = "60/minute"
    ENABLE_CHAT_FALLBACK: bool = True
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.1:8b"
    CHAT_USE_LANGCHAIN: bool = True
    OLLAMA_CONTEXT_LENGTH: int = 256
    OLLAMA_NUM_PREDICT: int = 180
    OLLAMA_CONNECT_TIMEOUT_SECONDS: int = 10
    OLLAMA_READ_TIMEOUT_SECONDS: int = 45
    JITSI_BASE_URL: str = "https://meet.jit.si"
    CHAT_MAX_HISTORY_MESSAGES: int = 10
    CHAT_MAX_USER_MESSAGE_LENGTH: int = 2000
    CHAT_MEMORY_SUMMARY_EVERY: int = 8
    CHAT_RETRIEVAL_TOP_K: int = 5
    CHAT_ENABLE_SEMANTIC_SEARCH: bool = False
    CHAT_EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"
    CHAT_SYSTEM_NAME: str = "AVA MJ"
    CHAT_NLU_PROVIDER: str = "local"
    WIT_AI_TOKEN: str | None = None
    WIT_AI_BASE_URL: str = "https://api.wit.ai"
    WIT_AI_API_VERSION: str = "20230416"

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def fix_database_url(cls, v: str) -> str:
        if v and v.startswith("mysql://"):
            return v.replace("mysql://", "mysql+pymysql://", 1)
        return v

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_allowed_origins(cls, value: Any) -> list[str]:
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return []

    @property
    def is_production(self) -> bool:
        return self.APP_ENV.lower() == "production"


settings = Settings()
