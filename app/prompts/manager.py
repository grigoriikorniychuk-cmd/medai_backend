"""
Менеджер промптов для системы MedAI.
Обеспечивает загрузку, управление и форматирование промптов для использования в системе.
"""

import os
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List, Union, Type, TypeVar
from pathlib import Path

from app.prompts.templates import (
    PromptTemplate,
    PromptType,
    DEFAULT_PROMPT_TEMPLATES,
    CLASSIFICATION_PROMPT,
    METRICS_PROMPT,
    ANALYSIS_PROMPT,
    SUMMARY_PROMPT,
)
from app.exceptions.base_exceptions import ConfigurationError, FileNotFoundError
from app.utils.logging import ContextLogger

# Создаем логгер
logger = ContextLogger("prompt_manager")

# Создаем типизированную переменную для промптов
T = TypeVar("T", bound=PromptTemplate)


class PromptManager:
    """
    Менеджер промптов для системы MedAI.
    Обеспечивает загрузку, управление и форматирование промптов для использования в системе.
    """

    def __init__(
        self, prompts_dir: Optional[str] = None, prompts_file: Optional[str] = None
    ):
        """
        Инициализирует менеджер промптов.

        Args:
            prompts_dir: Директория для хранения промптов (если None, используется директория по умолчанию)
            prompts_file: Файл с промптами (если None, используется файл по умолчанию)
        """
        # Устанавливаем пути к файлам
        self.prompts_dir = prompts_dir or os.path.join(
            os.path.dirname(__file__), "..", "data"
        )
        self.prompts_file = prompts_file or os.path.join(
            self.prompts_dir, "prompts.txt"
        )
        self.json_prompts_file = os.path.join(self.prompts_dir, "prompts.json")

        # Создаем кеш для хранения промптов
        self._prompt_cache: Dict[str, PromptTemplate] = {}
        self._legacy_prompts: Dict[str, str] = {}

        # Загружаем промпты
        self._load_prompts()

    def _load_prompts(self) -> None:
        """
        Загружает промпты из файлов.
        Пытается загрузить промпты из JSON файла, если он существует.
        В противном случае загружает из текстового файла и конвертирует в JSON.
        """
        # Сначала загружаем дефолтные промпты
        for prompt_type, prompt_template in DEFAULT_PROMPT_TEMPLATES.items():
            self._prompt_cache[prompt_type.value] = prompt_template

        # Проверяем существование JSON файла с промптами
        if os.path.exists(self.json_prompts_file):
            try:
                logger.info(
                    f"Загрузка промптов из JSON файла: {self.json_prompts_file}"
                )
                with open(self.json_prompts_file, "r", encoding="utf-8") as f:
                    prompts_data = json.load(f)

                # Загружаем промпты из JSON
                for prompt_key, prompt_data in prompts_data.items():
                    if isinstance(prompt_data, dict):
                        try:
                            prompt_template = PromptTemplate(**prompt_data)
                            self._prompt_cache[prompt_key] = prompt_template
                        except Exception as e:
                            logger.error(
                                f"Ошибка загрузки промпта {prompt_key}: {str(e)}"
                            )

                logger.info(
                    f"Загружено {len(self._prompt_cache)} промптов из JSON файла"
                )
            except Exception as e:
                logger.error(f"Ошибка с загрузке промптов из JSON файла: {str(e)}")
                # Если не удалось загрузить JSON, пробуем старый формат
                self._load_legacy_prompts()
        else:
            # Если JSON файла нет, загружаем из текстового файла
            logger.info(
                f"JSON файл промптов не найден, загрузка из текстового файла: {self.prompts_file}"
            )
            self._load_legacy_prompts()

    def _load_legacy_prompts(self) -> None:
        """
        Загружает промпты из текстового файла старого формата.
        Преобразует в новый формат и сохраняет в JSON.
        """
        try:
            if not os.path.exists(self.prompts_file):
                logger.warning(f"Файл промптов не найден: {self.prompts_file}")
                return

            with open(self.prompts_file, "r", encoding="utf-8") as f:
                content = f.read()

            # Парсим разделы промптов
            prompts = {}
            sections = content.split("[")
            for section in sections:
                if "]" in section:
                    key, text = section.split("]", 1)
                    prompts[key.strip()] = text.strip()

            # Сохраняем промпты в кеше
            self._legacy_prompts = prompts

            # Конвертируем старые промпты в новый формат
            for key, text in prompts.items():
                # Определяем тип промпта
                prompt_type = None
                if key.lower() == "classification":
                    prompt_type = PromptType.CLASSIFICATION
                elif key.lower() == "metrics":
                    prompt_type = PromptType.METRICS
                elif key.lower() == "analysis":
                    prompt_type = PromptType.ANALYSIS
                elif key.lower() == "summary":
                    prompt_type = PromptType.SUMMARY

                if prompt_type:
                    # Создаем шаблон промпта на основе старого текста
                    prompt_template = PromptTemplate(
                        name=f"legacy_{key.lower()}",
                        type=prompt_type,
                        template=text,
                        description=f"Промпт для {key}, конвертированный из старого формата",
                        variables=[
                            "dialogue"
                        ],  # Предполагаем, что все промпты используют dialogue
                        created_at=datetime.now().isoformat(),
                        author="system",
                    )

                    # Сохраняем в кеше
                    self._prompt_cache[key.lower()] = prompt_template

            # Сохраняем конвертированные промпты в JSON
            self._save_prompts_to_json()

            logger.info(
                f"Загружено {len(self._legacy_prompts)} промптов из текстового файла"
            )
        except Exception as e:
            logger.error(f"Ошибка с загрузке промптов из текстового файла: {str(e)}")

    def _save_prompts_to_json(self) -> None:
        """
        Сохраняет промпты в JSON файл.
        """
        try:
            # Создаем директорию, если она не существует
            os.makedirs(os.path.dirname(self.json_prompts_file), exist_ok=True)

            # Подготавливаем данные для JSON
            prompts_data = {}
            for key, prompt in self._prompt_cache.items():
                prompts_data[key] = prompt.dict()

            # Сохраняем в JSON
            with open(self.json_prompts_file, "w", encoding="utf-8") as f:
                json.dump(prompts_data, f, ensure_ascii=False, indent=2)

            logger.info(f"Промпты сохранены в JSON файл: {self.json_prompts_file}")
        except Exception as e:
            logger.error(f"Ошибка с сохранении промптов в JSON файл: {str(e)}")

    def get_prompt_template(
        self, prompt_type: Union[str, PromptType]
    ) -> PromptTemplate:
        """
        Получает шаблон промпта по типу.

        Args:
            prompt_type: Тип промпта или его строковое представление

        Returns:
            Шаблон промпта

        Raises:
            ConfigurationError: Если промпт не найден
        """
        # Преобразуем тип промпта в строку, если он передан как PromptType
        prompt_key = (
            prompt_type.value if isinstance(prompt_type, PromptType) else prompt_type
        )

        # Проверяем, есть ли промпт в кеше
        if prompt_key in self._prompt_cache:
            return self._prompt_cache[prompt_key]

        # Проверяем, есть ли промпт в старом формате
        if prompt_key in self._legacy_prompts:
            logger.warning(f"Промпт {prompt_key} найден только в старом формате")
            # Используем промпт по умолчанию с текстом из старого формата
            default_prompt = DEFAULT_PROMPT_TEMPLATES.get(
                PromptType(prompt_key),
                DEFAULT_PROMPT_TEMPLATES[PromptType.CLASSIFICATION],
            )
            custom_prompt = PromptTemplate(
                **default_prompt.dict(exclude={"template"}),
                template=self._legacy_prompts[prompt_key],
            )
            return custom_prompt

        # Если промпт не найден, возвращаем ошибку
        logger.error(f"Промпт {prompt_key} не найден")
        raise ConfigurationError(f"Промпт {prompt_key} не найден")

    def get_formatted_prompt(
        self, prompt_type: Union[str, PromptType], **kwargs
    ) -> str:
        """
        Получает отформатированный промпт с подставленными переменными.

        Args:
            prompt_type: Тип промпта или его строковое представление
            **kwargs: Переменные для подстановки в шаблон

        Returns:
            Отформатированный текст промпта

        Raises:
            ConfigurationError: Если промпт не найден или ошибка форматирования
        """
        try:
            # Получаем шаблон промпта
            prompt_template = self.get_prompt_template(prompt_type)

            # Форматируем шаблон с переданными переменными
            formatted_prompt = prompt_template.template.format(**kwargs)

            return formatted_prompt
        except KeyError as e:
            logger.error(f"Отсутствует переменная {e} для промпта {prompt_type}")
            raise ConfigurationError(
                f"Отсутствует переменная {e} для промпта {prompt_type}"
            )
        except Exception as e:
            logger.error(f"Ошибка форматирования промпта {prompt_type}: {str(e)}")
            raise ConfigurationError(
                f"Ошибка форматирования промпта {prompt_type}: {str(e)}"
            )

    def add_prompt_template(self, prompt_template: PromptTemplate) -> None:
        """
        Добавляет новый шаблон промпта в систему.

        Args:
            prompt_template: Шаблон промпта
        """
        # Добавляем промпт в кеш
        self._prompt_cache[prompt_template.type.value] = prompt_template

        # Сохраняем обновленные промпты в JSON
        self._save_prompts_to_json()

        logger.info(f"Добавлен новый шаблон промпта: {prompt_template.name}")

    def update_prompt_template(
        self, prompt_type: Union[str, PromptType], **updates
    ) -> PromptTemplate:
        """
        Обновляет существующий шаблон промпта.

        Args:
            prompt_type: Тип промпта или его строковое представление
            **updates: Обновления для шаблона промпта

        Returns:
            Обновленный шаблон промпта

        Raises:
            ConfigurationError: Если промпт не найден
        """
        # Получаем ключ промпта
        prompt_key = (
            prompt_type.value if isinstance(prompt_type, PromptType) else prompt_type
        )

        # Проверяем, есть ли промпт в кеше
        if prompt_key not in self._prompt_cache:
            logger.error(f"Промпт {prompt_key} не найден")
            raise ConfigurationError(f"Промпт {prompt_key} не найден")

        # Получаем текущий шаблон промпта
        current_prompt = self._prompt_cache[prompt_key]

        # Обновляем версию
        if "version" not in updates:
            # Инкрементируем версию (например, 1.0.0 -> 1.0.1)
            version_parts = current_prompt.version.split(".")
            if len(version_parts) >= 3:
                version_parts[-1] = str(int(version_parts[-1]) + 1)
                updates["version"] = ".".join(version_parts)

        # Добавляем дату обновления
        updates["updated_at"] = datetime.now().isoformat()

        # Создаем обновленный шаблон
        updated_data = current_prompt.dict()
        updated_data.update(updates)
        updated_prompt = PromptTemplate(**updated_data)

        # Обновляем кеш
        self._prompt_cache[prompt_key] = updated_prompt

        # Сохраняем обновленные промпты в JSON
        self._save_prompts_to_json()

        logger.info(
            f"Обновлен шаблон промпта: {updated_prompt.name}, версия: {updated_prompt.version}"
        )

        return updated_prompt

    def delete_prompt_template(self, prompt_type: Union[str, PromptType]) -> bool:
        """
        Удаляет шаблон промпта из системы.

        Args:
            prompt_type: Тип промпта или его строковое представление

        Returns:
            True если промпт удален, False если промпт не найден
        """
        # Получаем ключ промпта
        prompt_key = (
            prompt_type.value if isinstance(prompt_type, PromptType) else prompt_type
        )

        # Проверяем, есть ли промпт в кеше
        if prompt_key not in self._prompt_cache:
            logger.warning(f"Промпт {prompt_key} не найден")
            return False

        # Удаляем промпт из кеша
        del self._prompt_cache[prompt_key]

        # Сохраняем обновленные промпты в JSON
        self._save_prompts_to_json()

        logger.info(f"Удален шаблон промпта: {prompt_key}")

        return True

    def get_all_prompt_templates(self) -> Dict[str, PromptTemplate]:
        """
        Получает все доступные шаблоны промптов.

        Returns:
            Словарь с шаблонами промптов
        """
        return self._prompt_cache

    def reset_to_defaults(self) -> None:
        """
        Сбрасывает все промпты к значениям по умолчанию.
        """
        # Очищаем кеш
        self._prompt_cache.clear()

        # Загружаем дефолтные промпты
        for prompt_type, prompt_template in DEFAULT_PROMPT_TEMPLATES.items():
            self._prompt_cache[prompt_type.value] = prompt_template

        # Сохраняем обновленные промпты в JSON
        self._save_prompts_to_json()

        logger.info("Промпты сброшены к значениям по умолчанию")

    def export_prompt_templates(self, file_path: str) -> None:
        """
        Экспортирует все шаблоны промптов в JSON файл.

        Args:
            file_path: Путь к файлу для экспорта
        """
        try:
            # Создаем директорию, если она не существует
            os.makedirs(os.path.dirname(file_path), exist_ok=True)

            # Подготавливаем данные для JSON
            prompts_data = {}
            for key, prompt in self._prompt_cache.items():
                prompts_data[key] = prompt.dict()

            # Сохраняем в JSON
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(prompts_data, f, ensure_ascii=False, indent=2)

            logger.info(f"Промпты экспортированы в файл: {file_path}")
        except Exception as e:
            logger.error(f"Ошибка с экспорте промптов: {str(e)}")
            raise ConfigurationError(f"Ошибка с экспорте промптов: {str(e)}")

    def import_prompt_templates(self, file_path: str) -> None:
        """
        Импортирует шаблоны промптов из JSON файла.

        Args:
            file_path: Путь к файлу для импорта

        Raises:
            FileNotFoundError: Если файл не найден
            ConfigurationError: Если ошибка импорта
        """
        try:
            # Проверяем существование файла
            if not os.path.exists(file_path):
                logger.error(f"Файл {file_path} не найден")
                raise FileNotFoundError(f"Файл {file_path} не найден")

            # Загружаем данные из JSON
            with open(file_path, "r", encoding="utf-8") as f:
                prompts_data = json.load(f)

            # Обновляем кеш промптов
            for key, prompt_data in prompts_data.items():
                try:
                    prompt_template = PromptTemplate(**prompt_data)
                    self._prompt_cache[key] = prompt_template
                except Exception as e:
                    logger.error(f"Ошибка импорта промпта {key}: {str(e)}")

            # Сохраняем обновленные промпты в JSON
            self._save_prompts_to_json()

            logger.info(
                f"Импортировано {len(prompts_data)} промптов из файла {file_path}"
            )
        except Exception as e:
            logger.error(f"Ошибка с импорте промптов: {str(e)}")
            raise ConfigurationError(f"Ошибка с импорте промптов: {str(e)}")


# Создаем экземпляр менеджера промптов для использования в приложении
prompt_manager = PromptManager()
