"""
Модуль настроек приложения.
Предоставляет централизованный доступ ко всем настройкам.
"""

# Импортируем все переменные и функции из paths и auth для удобного доступа
from .paths import (
    APP_DIR,
    ROOT_DIR,
    DATA_DIR,
    AUDIO_DIR,
    TRANSCRIPTION_DIR,
    ANALYSIS_DIR,
    REPORTS_DIR,
    # EXTERNAL_AUDIO_DIR,
    MONGO_URI,
    DB_NAME,
    print_paths,
)

from .auth import evenlabs, get_langchain_token, get_mongodb, get_db_collection

from .amocrm import (
    AMOCRM_DEFAULT_CONFIG,
    AMOCRM_TOKEN_LIFETIME,
    get_amocrm_config,
    get_amocrm_config_from_clinic,
)

# Версия приложения
VERSION = "1.0.1"

# Настройки по умолчанию для API
DEFAULT_API_SETTINGS = {
    "title": "MedAI API",
    "description": "API для обработки и анализа звонков клиник",
    "version": VERSION,
}

# Настройки для логирования
LOGGING_CONFIG = {
    "level": "INFO",
    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
}


# Функция-помощник для получения полных настройки API
def get_api_settings():
    """Возвращает словарь с настройками API"""
    return DEFAULT_API_SETTINGS
