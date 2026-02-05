"""
Централизованная конфигурация проекта MedAI.
Реализует паттерн Singleton для доступа к настройкам из любой части приложения.
"""

import os
from functools import lru_cache
from typing import Any, Dict, Optional
from pydantic import BaseModel, field_validator, AnyHttpUrl
from fastapi import FastAPI
from pydantic_settings import BaseSettings

# Импортируем пути из paths.py
from app.settings.paths import (
    AUDIO_DIR, 
    TRANSCRIPTION_DIR, 
    REPORTS_DIR, 
    ANALYSIS_DIR,
    MONGO_URI,
    DB_NAME
)

from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()

print("MONGODB_URI:", os.getenv("MONGODB_URI") or MONGO_URI)
print("MONGODB_NAME:", os.getenv("MONGODB_NAME") or DB_NAME)

class DatabaseSettings(BaseModel):
    """Настройки базы данных MongoDB."""

    URI: str
    NAME: str
    MIN_CONNECTIONS_COUNT: int = 10
    MAX_CONNECTIONS_COUNT: int = 100
    TIMEOUT_MS: int = 5000


class AmoCRMSettings(BaseModel):
    """Настройки интеграции с AmoCRM."""

    BASE_URL: Optional[AnyHttpUrl] = None
    CLIENT_ID: Optional[str] = None
    CLIENT_SECRET: Optional[str] = None
    REDIRECT_URI: Optional[AnyHttpUrl] = None
    ACCESS_TOKEN: Optional[str] = None
    REFRESH_TOKEN: Optional[str] = None

    @field_validator("BASE_URL", "REDIRECT_URI")
    @classmethod
    def ensure_url_has_trailing_slash(cls, v):
        if isinstance(v, str) and not v.endswith("/"):
            return f"{v}/"
        return v


class PathSettings(BaseModel):
    """Настройки путей к файлам и ресурсам."""

    AUDIO_PATH: str
    TRANSCRIPTION_PATH: str
    REPORTS_PATH: str
    ANALYSIS_PATH: str

    @field_validator(
        "AUDIO_PATH", "TRANSCRIPTION_PATH", "REPORTS_PATH", "ANALYSIS_PATH"
    )
    @classmethod
    def create_directory_if_not_exists(cls, path: str) -> str:
        """Создает директорию, если она не существует."""
        os.makedirs(path, exist_ok=True)
        return path


class APISettings(BaseModel):
    """Настройки API."""

    PREFIX: str = "/api/v1"
    DEBUG: bool = False
    TITLE: str = "MedAI API"
    DESCRIPTION: str = "API для системы анализа медицинских звонков MedAI"
    VERSION: str = "1.0.0"
    DOCS_URL: str = "/docs"
    REDOC_URL: str = "/redoc"
    OPENAPI_URL: str = "/openapi.json"
    ALLOWED_HOSTS: list[str] = ["*"]
    CORS_ORIGINS: list[str] = ["*"]


class SecuritySettings(BaseModel):
    """Настройки безопасности."""

    SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    API_KEY: Optional[str] = None


class AppSettings(BaseSettings):
    """Основные настройки приложения."""

    # Общие настройки
    APP_NAME: str = "MedAI"
    ENVIRONMENT: str

    # Компоненты настроек
    DATABASE: DatabaseSettings
    AMOCRM: AmoCRMSettings
    PATHS: PathSettings
    API: APISettings
    SECURITY: SecuritySettings

    # Настройки логирования
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    @field_validator("ENVIRONMENT")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        allowed = {"development", "staging", "production", "testing"}
        if v.lower() not in allowed:
            raise ValueError(f"Environment {v} is not valid. Must be one of {allowed}")
        return v.lower()

    model_config = {
        "env_nested_delimiter": "__",
        "case_sensitive": True,
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore"  # Игнорировать неизвестные поля
    }


@lru_cache
def get_settings() -> AppSettings:
    """
    Singleton для доступа к настройкам.
    Использует lru_cache для кэширования экземпляра настроек.

    Returns:
        AppSettings: Экземпляр настроек приложения
    """
    db_settings = DatabaseSettings(
        URI=os.getenv("MONGODB_URI", MONGO_URI), 
        NAME=os.getenv("MONGODB_NAME", DB_NAME)
    )

    amocrm_settings = AmoCRMSettings(
        BASE_URL=os.getenv("AMOCRM_BASE_URL"),
        CLIENT_ID=os.getenv("AMOCRM_CLIENT_ID"),
        CLIENT_SECRET=os.getenv("AMOCRM_CLIENT_SECRET"),
        REDIRECT_URI=os.getenv("AMOCRM_REDIRECT_URI"),
        ACCESS_TOKEN=os.getenv("AMOCRM_ACCESS_TOKEN"),
        REFRESH_TOKEN=os.getenv("AMOCRM_REFRESH_TOKEN"),
    )

    paths_settings = PathSettings(
        AUDIO_PATH=os.getenv("AUDIO_PATH", AUDIO_DIR),
        TRANSCRIPTION_PATH=os.getenv("TRANSCRIPTION_PATH", TRANSCRIPTION_DIR),
        REPORTS_PATH=os.getenv("REPORTS_PATH", REPORTS_DIR),
        ANALYSIS_PATH=os.getenv("ANALYSIS_PATH", ANALYSIS_DIR),
    )

    api_settings = APISettings(
        DEBUG=os.getenv("DEBUG", "False").lower() == "true",
        ALLOWED_HOSTS=os.getenv("ALLOWED_HOSTS", "*").split(","),
        CORS_ORIGINS=os.getenv("CORS_ORIGINS", "*").split(","),
    )

    security_settings = SecuritySettings(
        SECRET_KEY=os.getenv("SECRET_KEY", "default-secret-key-for-development-only"),
        API_KEY=os.getenv("API_KEY")
    )
    
    return AppSettings(
        ENVIRONMENT=os.getenv("ENVIRONMENT", "development"),
        DATABASE=db_settings,
        AMOCRM=amocrm_settings,
        PATHS=paths_settings,
        API=api_settings,
        SECURITY=security_settings,
        LOG_LEVEL=os.getenv("LOG_LEVEL", "INFO"),
    )
