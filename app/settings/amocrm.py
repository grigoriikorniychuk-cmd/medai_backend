"""
Модуль с настройками для интеграции с AmoCRM.
Предоставляет централизованный доступ к конфигурации AmoCRM.
"""

import os
from typing import Dict, Any, Optional, Union
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Базовые настройки для подключения к AmoCRM с правильными переменными
# ВАЖНО: redirect_url обычно берется из базы данных (коллекция clinics),
# это значение используется только как fallback
AMOCRM_DEFAULT_CONFIG = {
    "mongo_uri": os.getenv("MONGODB_URI", "mongodb://localhost:27017"),
    "db_name": os.getenv("MONGODB_NAME", "medai"),
    "redirect_url": os.getenv("AMOCRM_REDIRECT_URL", "https://medai.mlab-electronics.ru"),
}

# Время жизни токена в секундах (6 часов)
AMOCRM_TOKEN_LIFETIME = 6 * 60 * 60

# Экспортируем константы для совместимости со старым кодом
MONGODB_URI = AMOCRM_DEFAULT_CONFIG["mongo_uri"]
MONGODB_NAME = AMOCRM_DEFAULT_CONFIG["db_name"]


def get_amocrm_config(
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    subdomain: Optional[str] = None,
    redirect_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Возвращает конфигурацию для подключения к AmoCRM.
    Если параметры не указаны, используются значения по умолчанию.

    Args:
        client_id: ID интеграции AmoCRM
        client_secret: Секретный ключ интеграции AmoCRM
        subdomain: Поддомен AmoCRM (например, test для test.amocrm.ru)
        redirect_url: URL для перенаправления после авторизации
    
    Returns:
        Словарь с конфигурацией AmoCRM
    """
    config = AMOCRM_DEFAULT_CONFIG.copy()

    if client_id:
        config["client_id"] = client_id
    if client_secret:
        config["client_secret"] = client_secret
    if subdomain:
        config["subdomain"] = subdomain
    if redirect_url:
        config["redirect_url"] = redirect_url

    return config


def get_amocrm_config_from_clinic(clinic: Dict[str, Any]) -> Dict[str, Any]:
    """
    Создает конфигурацию AmoCRM на основе данных клиники

    Args:
        clinic: Словарь с данными клиники
    
    Returns:
        Словарь с конфигурацией AmoCRM
    """
    return get_amocrm_config(
        client_id=clinic.get("client_id"),
        client_secret=clinic.get("client_secret"),
        subdomain=clinic.get("amocrm_subdomain"),
        redirect_url=clinic.get("redirect_url"),
    )
