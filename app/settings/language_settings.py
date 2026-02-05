#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Настройки языка для проекта.
Этот файл определяет правила использования языков в проекте:
- Интерфейс на английском
- Комментарии и документация на русском
"""

# Настройки языка для IDE и инструментов разработки
INTERFACE_LANGUAGE = "en"  # Интерфейс на английском
COMMENTS_LANGUAGE = "ru"   # Комментарии на русском
DOCUMENTATION_LANGUAGE = "ru"  # Документация на русском

# Список каталогов, где разрешены русские комментарии
RUSSIAN_COMMENTS_ALLOWED_DIRS = [
    "app/",
    "tests/",
    "scripts/",
]

# Функция для проверки, разрешены ли русские комментарии в файле
def is_russian_comments_allowed(file_path: str) -> bool:
    """
    Проверяет, разрешены ли русские комментарии в указанном файле.
    
    Args:
        file_path: Путь к файлу для проверки
        
    Returns:
        True, если русские комментарии разрешены, else False
    """
    return any(file_path.startswith(dir) for dir in RUSSIAN_COMMENTS_ALLOWED_DIRS)

# Инструкции для разработчиков
DEVELOPER_INSTRUCTIONS = """
Правила использования языков в проекте:

1. Весь код (имена переменных, функций, классов) должен быть на английском языке
2. Комментарии и строки документации должны быть на русском языке
3. Сообщения для пользователей (логи, интерфейс) должны быть на русском языке
4. Интерфейс IDE и инструментов разработки должен быть установлен на английский
   для избежания проблем с подменой символов в коде.

При использовании инструментов автогенерации кода (Copilot и др.) следует указать,
что интерфейс должен быть на английском, a комментарии и документация на русском.
"""

# Для интеграции в IDE и инструменты
def get_language_settings():
    """
    Возвращает настройки языка для интеграции с IDE и инструментами.
    
    Returns:
        Словарь с настройками языка
    """
    return {
        "interface_language": INTERFACE_LANGUAGE,
        "comments_language": COMMENTS_LANGUAGE,
        "documentation_language": DOCUMENTATION_LANGUAGE,
        "developer_instructions": DEVELOPER_INSTRUCTIONS
    }

if __name__ == "__main__":
    print(DEVELOPER_INSTRUCTIONS)