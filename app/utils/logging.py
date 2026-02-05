"""
Модуль логирования для приложения MedAI.
Предоставляет настраиваемое логирование для различных компонентов системы.
"""

import logging
import sys
import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Dict, Any, Optional, Union

from app.settings.config import get_settings

settings = get_settings()

# Формат логирования для консоли
CONSOLE_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"

# Расширенный формат для файлов
FILE_FORMAT = (
    "%(asctime)s | %(levelname)s | %(name)s | %(filename)s:%(lineno)d | %(message)s"
)

# Корректное получение уровня логирования из настроек
log_level_name = settings.LOG_LEVEL
# Получаем числовое значение уровня логирования
LOG_LEVEL = getattr(logging, log_level_name) if hasattr(logging, log_level_name) else logging.INFO


class JsonFormatter(logging.Formatter):
    """
    Форматтер для логов в JSON формате для улучшенной обработки логов системами ELK, Graylog и t.д.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_record = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Добавляем информацию об исключении, если она есть
        if record.exc_info:
            log_record["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
            }

        # Добавляем дополнительные атрибуты, если они были переданы через extra
        if hasattr(record, "extra") and record.extra:
            log_record["extra"] = record.extra

        return json.dumps(log_record)


@lru_cache
def get_logger(
    name: str, log_to_file: bool = False, log_file: Optional[Union[str, Path]] = None
) -> logging.Logger:
    """
    Получает настроенный логгер по имени.

    Args:
        name: Имя логгера (обычно имя модуля).
        log_to_file: Флаг, указывающий нужно ли логировать в файл.
        log_file: Путь к файлу лога (если None, используется имя логгера).

    Returns:
        Настроенный логгер.
    """
    logger = logging.getLogger(name)
    logger.setLevel(LOG_LEVEL)

    # Удаляем существующие обработчики, если они есть
    if logger.handlers:
        logger.handlers.clear()

    # Добавляем обработчик для вывода в консоль
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(LOG_LEVEL)
    console_formatter = logging.Formatter(CONSOLE_FORMAT)
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # Добавляем обработчик для записи в файл, если требуется
    if log_to_file:
        if not log_file:
            log_file = f"logs/{name.replace('.', '_')}.log"

        # Создаем директорию для логов, если её нет
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(LOG_LEVEL)

        # Для файлов используем JSON формат для лучшей обработки
        file_handler.setFormatter(JsonFormatter())
        logger.addHandler(file_handler)

    # Отключаем распространение логов к родительским логгерам
    logger.propagate = False

    return logger


class ContextLogger:
    """
    Класс для логирования с контекстом.
    Сохраняет контекст между вызовами и добавляет его к каждому сообщению лога.
    """

    def __init__(self, name: str, context: Optional[Dict[str, Any]] = None):
        self.logger = get_logger(name)
        self.context = context or {}

    def add_context(self, **kwargs) -> None:
        """Добавляет контекст к логгеру."""
        self.context.update(kwargs)

    def clear_context(self) -> None:
        """Очищает контекст логгера."""
        self.context.clear()

    def _format_message(self, message: str) -> str:
        """Форматирует сообщение с контекстом."""
        if not self.context:
            return message

        context_str = " | ".join(f"{k}={v}" for k, v in self.context.items())
        return f"{message} [Context: {context_str}]"

    def debug(self, message: str, **kwargs) -> None:
        """Логирует сообщение с уровнем DEBUG."""
        temp_context = {**self.context, **kwargs}
        self.logger.debug(self._format_message(message), extra={"extra": temp_context})

    def info(self, message: str, **kwargs) -> None:
        """Логирует сообщение с уровнем INFO."""
        temp_context = {**self.context, **kwargs}
        self.logger.info(self._format_message(message), extra={"extra": temp_context})

    def warning(self, message: str, **kwargs) -> None:
        """Логирует сообщение с уровнем WARNING."""
        temp_context = {**self.context, **kwargs}
        self.logger.warning(
            self._format_message(message), extra={"extra": temp_context}
        )

    def error(self, message: str, exc_info: bool = False, **kwargs) -> None:
        """Логирует сообщение с уровнем ERROR."""
        temp_context = {**self.context, **kwargs}
        self.logger.error(
            self._format_message(message),
            exc_info=exc_info,
            extra={"extra": temp_context},
        )

    def critical(self, message: str, exc_info: bool = True, **kwargs) -> None:
        """Логирует сообщение с уровнем CRITICAL."""
        temp_context = {**self.context, **kwargs}
        self.logger.critical(
            self._format_message(message),
            exc_info=exc_info,
            extra={"extra": temp_context},
        )

    def exception(self, message: str, **kwargs) -> None:
        """Логирует исключение."""
        temp_context = {**self.context, **kwargs}
        self.logger.exception(
            self._format_message(message), extra={"extra": temp_context}
        )


# Создаем логгер приложения
app_logger = get_logger("medai")
