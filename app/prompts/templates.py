"""
Шаблоны промптов для системы анализа звонков MedAI.
Содержит типизированные шаблоны для разных типов промптов.
"""

from enum import Enum
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field


class PromptType(str, Enum):
    """Типы промптов, используемых в системе."""

    CLASSIFICATION = "classification"  # Классификация звонка
    METRICS = "metrics"  # Анализ метрик звонка
    ANALYSIS = "analysis"  # Полный анализ звонка
    SUMMARY = "summary"  # Краткое резюме звонка
    OBJECTIONS = "objections"  # Анализ возражений
    CONVERSION = "conversion"  # Анализ конверсии
    ADMIN_NAME_EXTRACTION = "admin_name_extraction"  # Извлечение имени администратора


class LLMProvider(str, Enum):
    """Поставщики LLM моделей."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    LOCAL = "local"
    YANDEX = "yandex"


class PromptTemplate(BaseModel):
    """
    Шаблон промпта для языковой модели.
    Позволяет def структуру промпта с переменными.
    """

    name: str = Field(..., description="Название шаблона")
    version: str = Field("1.0.0", description="Версия шаблона")
    type: PromptType = Field(..., description="Тип промпта")
    provider: LLMProvider = Field(LLMProvider.OPENAI, description="Поставщик LLM")
    template: str = Field(
        ..., description="Текст шаблона с переменными в формате {variable}"
    )
    description: Optional[str] = Field(None, description="Описание шаблона")
    parameters: Dict[str, Any] = Field(
        default_factory=dict, description="Параметры для LLM"
    )
    variables: List[str] = Field(
        default_factory=list, description="Список переменных в шаблоне"
    )
    created_at: Optional[str] = Field(None, description="Дата создания шаблона")
    updated_at: Optional[str] = Field(None, description="Дата обновления шаблона")
    author: Optional[str] = Field(None, description="Автор шаблона")
    tags: List[str] = Field(
        default_factory=list, description="Теги для категоризации шаблона"
    )
    examples: List[Dict[str, Any]] = Field(
        default_factory=list, description="Примеры использования шаблона"
    )

    class Config:
        arbitrary_types_allowed = True
        schema_extra = {
            "example": {
                "name": "call_classification",
                "version": "1.0.0",
                "type": "classification",
                "provider": "openai",
                "template": "Проанализируй следующий диалог между администратором медицинского центра и клиентом:\n\n{dialogue}\n\nОпредели тип звонка",
                "description": "Шаблон для классификации звонков",
                "parameters": {"temperature": 0.1, "max_tokens": 500},
                "variables": ["dialogue"],
                "created_at": "2025-04-10",
                "author": "Ivan Petrov",
                "tags": ["call", "classification", "analysis"],
            }
        }


# Базовые шаблоны промптов
CLASSIFICATION_PROMPT = PromptTemplate(
    name="call_classification",
    type=PromptType.CLASSIFICATION,
    template="""
Ты - опытный аналитик медицинских звонков. Проанализируй диалог между администратором медицинского центра и клиентом:

{dialogue}

Определи тип звонка из следующих категорий:
1. Первичное обращение (новый клиент)
2. Запись на приём
3. Запрос информации (цены, услуги и t.д.)
4. Проблема или жалоба
5. Изменение или отмена встречи
6. Повторная консультация
7. Запрос результатов анализов
8. Другое

Также определи направление звонка (входящий или исходящий).

Ответь в следующем формате: "Категория: [номер категории]. [название категории]. Направление: [входящий/исходящий]"
""",
    description="Шаблон для классификации типа звонка",
    parameters={"temperature": 0.1, "max_tokens": 100},
    variables=["dialogue"],
    tags=["classification", "call_type"],
)

METRICS_PROMPT = PromptTemplate(
    name="call_metrics",
    type=PromptType.METRICS,
    template="""
Ты - опытный аналитик качества обслуживания в медицинском центре. Проанализируй диалог между администратором медицинского центра и клиентом:

{dialogue}

Оцени качество работы администратора по следующим параметрам по шкале от 0 до 10:
1. greeting - Приветствие клиента (0-10)
2. needs_identification - Выявление потребностей клиента (0-10)
3. solution_proposal - Предложение решения (0-10)
4. objection_handling - Работа с возражениями (0-10)
5. call_closing - Завершение звонка (0-10)

Также оцени:
- tone - Общую тональность диалога (positive, neutral, negative)
- customer_satisfaction - Уровень удовлетворенности клиента (high, medium, low)
- overall_score - Общая оценка звонка от 0 до 10

Ответь в следующем формате:
greeting: [оценка]
needs_identification: [оценка]
solution_proposal: [оценка]
objection_handling: [оценка]
call_closing: [оценка]
tone: [тональность]
customer_satisfaction: [уровень]
overall_score: [общая оценка]
""",
    description="Шаблон для оценки метрик качества звонка",
    parameters={"temperature": 0.2, "max_tokens": 300},
    variables=["dialogue"],
    tags=["metrics", "quality", "evaluation"],
)

ANALYSIS_PROMPT = PromptTemplate(
    name="call_analysis",
    type=PromptType.ANALYSIS,
    template="""
Ты - опытный аналитик медицинских звонков. Проанализируй диалог между администратором медицинского центра и клиентом:

{dialogue}

Проведи детальный анализ звонка по следующим направлениям:
1. Краткое резюме диалога
2. Сильные стороны работы администратора
3. Области для улучшения
4. Ключевые потребности клиента
5. Эффективность решения проблемы клиента
6. Конверсия (была ли достигнута цель диалога)
7. Рекомендации по улучшению

Твой анализ должен быть подробным, но структурированным. Используй конкретные примеры из диалога.
""",
    description="Шаблон для полного анализа звонка",
    parameters={"temperature": 0.3, "max_tokens": 1500},
    variables=["dialogue"],
    tags=["analysis", "detailed", "recommendations"],
)

SUMMARY_PROMPT = PromptTemplate(
    name="call_summary",
    type=PromptType.SUMMARY,
    template="""
Ты - опытный специалист по анализу диалогов. Создай краткое и информативное резюме диалога между администратором медицинского центра и клиентом:

{dialogue}

Резюме должно быть объемом 2-3 предложения и включать:
- Цель обращения клиента
- Главные обсуждаемые вопросы
- Результат диалога
""",
    description="Шаблон для создания краткого резюме звонка",
    parameters={"temperature": 0.2, "max_tokens": 200},
    variables=["dialogue"],
    tags=["summary", "brief"],
)

ADMIN_NAME_EXTRACTION_PROMPT = PromptTemplate(
    name="admin_name_extraction",
    type=PromptType.ADMIN_NAME_EXTRACTION,
    template="""
Ты - специалист по анализу транскрипций звонков. Проанализируй следующую транскрипцию звонка между сотрудником медицинской клиники и клиентом:

{transcription}

Список администраторов, работавших в этот день согласно графику:
{administrators_list}

Твоя задача - определить, КТО ИМЕННО из перечисленных администраторов вёл этот разговор.

КРИТИЧЕСКИ ВАЖНО:
1. Администратор ДОЛЖЕН ЯВНО представиться в транскрипции (назвать своё имя)
2. Если в транскрипции НЕТ явного упоминания имени сотрудника - верни null
3. НЕ УГАДЫВАЙ! Если имя не произносится - это null
4. Возвращай имя СТРОГО КАК НАПИСАНО В СПИСКЕ! Люди часто представляются уменьшительными именами, но ты ОБЯЗАН вернуть ПОЛНОЕ имя из списка.

ОБЯЗАТЕЛЬНО сопоставляй уменьшительные/разговорные формы с полными именами из списка:
- Юля, Юлечка → Юлия
- Настя, Настенька → Анастасия
- Лена → Елена
- Лиза → Елизавета
- Катя → Екатерина
- Саша, Шура → Александра/Александр
- Женя → Евгения/Евгений
- Валя → Валентина
- Лера → Валерия
- Маша → Мария
- Даша → Дарья
- Наташа → Наталья
- Алёна → Алёна/Елена
- Люба → Любовь
- Надя → Надежда
- Аня → Анна
- Таня → Татьяна
- Юра → Юрий
- Миша → Михаил
И другие стандартные русские сокращения имён.

Примеры когда ЕСТЬ имя (возвращай ПОЛНОЕ имя из списка):
- "администратор Настя" → Анастасия (если в списке есть Анастасия)
- "Меня зовут Юля" → Юлия (если в списке есть Юлия)
- "Клиника Перфетто, Лиза, слушаю" → Елизавета (если в списке есть Елизавета)

Примеры когда НЕТ имени (возвращай null):
- "Клиника, здравствуйте" → null (нет имени)
- "Алло, вы дозвонились" → null (нет имени)
- "Стоматология, добрый день" → null (нет имени)
- Любые гудки, автоответчики → null

НЕ путай имя администратора с именем клиента!
Оцени уверенность от 0.0 до 1.0

Верни результат СТРОГО в формате JSON без дополнительного текста:
{{
    "first_name": "Имя ТОЛЬКО если явно произнесено в транскрипции",
    "last_name": "Фамилия из списка",
    "confidence": 0.95
}}

Если имя администратора НЕ упоминается в транскрипции, ОБЯЗАТЕЛЬНО верни:
{{
    "first_name": null,
    "last_name": null,
    "confidence": 0.0
}}
""",
    description="Шаблон для определения администратора из списка работающих по графику",
    parameters={"temperature": 0.1, "max_tokens": 150},
    variables=["transcription", "administrators_list"],
    tags=["extraction", "admin", "name", "schedule"],
)

# Словарь всех шаблонов промптов
DEFAULT_PROMPT_TEMPLATES = {
    PromptType.CLASSIFICATION: CLASSIFICATION_PROMPT,
    PromptType.METRICS: METRICS_PROMPT,
    PromptType.ANALYSIS: ANALYSIS_PROMPT,
    PromptType.SUMMARY: SUMMARY_PROMPT,
    PromptType.ADMIN_NAME_EXTRACTION: ADMIN_NAME_EXTRACTION_PROMPT,
}
