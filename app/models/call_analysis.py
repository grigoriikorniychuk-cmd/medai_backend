"""
Модели данных для анализа звонков.
"""

from enum import Enum
from typing import Dict, Any, Optional, List
from datetime import datetime
from pydantic import BaseModel, Field

from app.models.base import BaseModelMedAI, AuditModel, IdentifiableModel


class CallDirectionEnum(str, Enum):
    """Направление звонка (входящий/исходящий)."""

    INCOMING = "incoming"
    OUTGOING = "outgoing"


class CallCategoryEnum(int, Enum):
    """Категории звонков."""

    NEW_CLIENT = 1  # Первичное обращение (новый клиент)
    APPOINTMENT = 2  # Запись на приём
    INFO_REQUEST = 3  # Запрос информации (цены, услуги и т.д.)
    PROBLEM_COMPLAINT = 4  # Проблема или жалоба
    CHANGE_CANCEL = 5  # Изменение или отмена встречи
    FOLLOW_UP = 6  # Повторная консультация
    RESULTS_REQUEST = 7  # Запрос результатов анализов
    OTHER = 8  # Другое


class ToneEnum(str, Enum):
    """Тональность звонка."""

    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class SatisfactionEnum(str, Enum):
    """Уровень удовлетворенности клиента."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class CallMetrics(BaseModel):
    """
    Метрики оценки звонка
    """
    greeting: int = Field(0, description="Приветствие", ge=0, le=10)
    patient_name: int = Field(0, description="Имя пациента", ge=0, le=10)
    needs_identification: int = Field(0, description="Выявление потребностей", ge=0, le=10)
    objection_handling: int = Field(0, description="Работа с возражениями", ge=0, le=10)
    service_presentation: int = Field(0, description="Презентация услуги", ge=0, le=10)
    clinic_presentation: int = Field(0, description="Презентация клиники", ge=0, le=10)
    doctor_presentation: int = Field(0, description="Презентация врача", ge=0, le=10)
    patient_booking: int = Field(0, description="Запись пациента", ge=0, le=10)
    clinic_address: int = Field(0, description="Адрес клиники", ge=0, le=10)
    passport: int = Field(0, description="Паспорт", ge=0, le=10)
    price: int = Field(0, description="Цена \"от\"", ge=0, le=10)
    expertise: int = Field(0, description="Экспертность", ge=0, le=10)
    next_step: int = Field(0, description="Следующий шаг", ge=0, le=10)
    appointment: int = Field(0, description="Запись на прием", ge=0, le=10)
    emotional_tone: int = Field(0, description="Эмоциональный окрас", ge=0, le=10)
    speech: int = Field(0, description="Речь", ge=0, le=10)
    initiative: int = Field(0, description="Инициатива", ge=0, le=10)
    solution_proposal: int = Field(0, description="Предложение решения", ge=0, le=10)
    call_closing: int = Field(0, description="Завершение звонка", ge=0, le=10)
    overall_score: Optional[float] = Field(None, description="Общая оценка", ge=0, le=10)
    tone: Optional[ToneEnum] = Field(None, description="Тон разговора")
    customer_satisfaction: Optional[SatisfactionEnum] = Field(None, description="Удовлетворенность клиента")
    conversion: bool = Field(False, description="Конверсия (была ли запись на прием)")
    recommendations: Optional[List[str]] = Field(None, description="Список рекомендаций для улучшения")
    
    def average_score(self) -> float:
        """
        Рассчитывает среднюю оценку по всем числовым метрикам
        
        Returns:
            Средняя оценка звонка по всем метрикам
        """
        # Получаем все числовые метрики, пропуская поля, которые не являются оценками
        numeric_fields = {
            field: value for field, value in self.dict().items() 
            if isinstance(value, int) and field not in ['overall_score']
        }
        
        # Рассчитываем среднюю оценку из ненулевых значений
        non_zero_values = [v for v in numeric_fields.values() if v > 0]
        return sum(non_zero_values) / len(non_zero_values) if non_zero_values else 0


class CallTypeInfo(BaseModelMedAI):
    """Информация о типе звонка."""

    direction: CallDirectionEnum = CallDirectionEnum.INCOMING
    category: CallCategoryEnum = CallCategoryEnum.OTHER
    category_name: str = "Другое"
    duration: Optional[int] = None
    duration_formatted: Optional[str] = None


class ClientInfo(BaseModelMedAI):
    """Информация о клиенте."""

    phone: Optional[str] = None
    source: str = "Unknown"
    name: Optional[str] = None
    email: Optional[str] = None


class FileLinks(BaseModelMedAI):
    """Ссылки на файлы, связанные со звонком."""

    transcription: Optional[str] = None
    analysis: Optional[str] = None
    audio: Optional[str] = None


class ApiLinks(BaseModelMedAI):
    """API-ссылки для доступа к файлам."""

    transcription: Optional[str] = None
    audio: Optional[str] = None
    report: Optional[str] = None


class CallAnalysisRequest(BaseModelMedAI):
    """Запрос на анализ звонка."""

    transcription_filename: Optional[str] = None
    transcription_text: Optional[str] = None
    note_id: Optional[int] = None
    contact_id: Optional[int] = None
    lead_id: Optional[int] = None
    administrator_id: Optional[str] = None
    clinic_id: Optional[str] = None
    call_id: Optional[str] = None
    meta_info: Optional[Dict[str, Any]] = None

    class Config:
        json_schema_extra = {
            "example": {
                "transcription_filename": "79155366257_20250326_095836.txt",
                "note_id": 123456,
                "contact_id": 789012,
                "lead_id": 345678,
                "administrator_id": "admin_ivan_petrov",
                "clinic_id": "818579a1-fc67-4a0f-a543-56f6eb828606",
                "meta_info": {
                    "client_name": "Иванов Иван",
                    "client_email": "ivanov@example.com",
                },
            }
        }


class CallAnalysisResponse(BaseModelMedAI):
    """Ответ на запрос анализа звонка."""

    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


class CallAnalysisModel(AuditModel):
    """Модель данных анализа звонка."""

    # Идентификаторы AmoCRM
    note_id: Optional[int] = None
    contact_id: Optional[int] = None
    lead_id: Optional[int] = None
    client_id: Optional[str] = None

    # Метаданные звонка
    clinic_id: str
    administrator_id: str
    administrator_name: str
    timestamp: datetime
    date: str

    # Информация о звонке
    call_type: CallTypeInfo
    client: ClientInfo
    metrics: CallMetrics

    # Файлы и ссылки
    files: Optional[FileLinks] = None
    links: Optional[ApiLinks] = None

    # Результаты анализа
    analysis_text: Optional[str] = None
    transcription_text: Optional[str] = None
    classification: Optional[str] = None
    recommendations: Optional[List[str]] = None


class CallAnalysisSummary(BaseModelMedAI):
    """Сводка результатов анализа для отображения в списке."""

    id: str
    date: str
    timestamp: datetime
    administrator_name: str
    client_phone: Optional[str] = None
    call_category: str
    call_direction: CallDirectionEnum
    overall_score: float
    conversion: bool
    satisfaction: SatisfactionEnum
    recommendations: Optional[List[str]] = None


class CallMetricsAggregate(BaseModelMedAI):
    """Агрегированные метрики по звонкам."""

    total_calls: int = 0
    incoming_calls: int = 0
    outgoing_calls: int = 0
    conversion_count: int = 0
    conversion_rate: float = 0.0
    avg_score: float = 0.0
    administrators: List[Dict[str, Any]] = []
    call_types: Dict[int, Dict[str, Any]] = {}
    traffic_sources: Dict[str, Dict[str, Any]] = {}


class MetricsFilter(BaseModelMedAI):
    """Фильтр для получения метрик."""

    start_date: str
    end_date: str
    clinic_id: Optional[str] = None
    administrator_ids: Optional[List[str]] = None


class CriterionScore(BaseModel):
    """Оценка одного критерия."""

    name: str = Field(..., description="Название критерия")
    score: int = Field(..., description="Оценка от 0 до 10", ge=0, le=10)
    comment: Optional[str] = Field(None, description="Комментарий к оценке")

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Приветствие",
                "score": 8,
                "comment": "Администратор назвала клинику и своё имя"
            }
        }


class CallScoresResponse(BaseModelMedAI):
    """Ответ с оценками по звонку."""

    note_id: int = Field(..., description="ID заметки в AmoCRM")
    client_id: str = Field(..., description="ID клиники")
    call_type: str = Field(..., description="Тип звонка (первичка/вторичка/перезвон)")
    call_type_id: Optional[int] = Field(None, description="ID типа звонка")
    administrator: Optional[str] = Field(None, description="Имя администратора")
    created_date: Optional[str] = Field(None, description="Дата создания звонка")
    overall_score: Optional[float] = Field(None, description="Общая оценка", ge=0, le=10)
    conversion: Optional[bool] = Field(None, description="Конверсия (запись на прием)")
    scores: Dict[str, CriterionScore] = Field(..., description="Оценки по критериям")
    recommendations: Optional[List[str]] = Field(None, description="Рекомендации")
    transcription_url: Optional[str] = Field(None, description="Ссылка на скачивание транскрибации")

    class Config:
        json_schema_extra = {
            "example": {
                "note_id": 123456,
                "client_id": "818579a1-fc67-4a0f-a543-56f6eb828606",
                "call_type": "Первичка",
                "call_type_id": 1,
                "administrator": "Иванова Мария",
                "created_date": "2025-11-28",
                "overall_score": 7.5,
                "conversion": True,
                "scores": {
                    "greeting": {
                        "name": "Приветствие",
                        "score": 8,
                        "comment": "Назвала клинику и своё имя"
                    },
                    "patient_name": {
                        "name": "Имя пациента",
                        "score": 10,
                        "comment": "Узнала имя в начале и использовала 4+ раз"
                    }
                },
                "recommendations": [
                    "Улучшить выявление потребностей клиента",
                    "Презентовать клинику более детально"
                ],
                "transcription_url": "/api/transcriptions/79123456789_20251128_123456.txt/download"
            }
        }
