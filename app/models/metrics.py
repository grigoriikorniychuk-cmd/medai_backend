# from pydantic import BaseModel, Field
# from typing import Dict, Any, Optional, List
# from datetime import datetime

# class CallMetrics(BaseModel):
#     """Модель для хранения метрик звонка и оценок администратора"""
#     greeting: float = Field(..., description="Оценка приветствия (0-10)")
#     needs_identification: float = Field(..., description="Оценка выявления потребностей (0-10)")
#     solution_proposal: float = Field(..., description="Оценка предложения решения (0-10)")
#     objection_handling: float = Field(..., description="Оценка работы с возражениями (0-10)")
#     call_closing: float = Field(..., description="Оценка завершения разговора (0-10)")
#     tone: str = Field(..., description="Тональность разговора (positive/neutral/negative)")
#     customer_satisfaction: str = Field(..., description="Удовлетворенность клиента (high/medium/low)")
#     overall_score: float = Field(..., description="Общая оценка (0-10)")

# class CallMetricsRecord(BaseModel):
#     """Модель для записи метрик звонка в базу данных"""
#     administrator_id: str = Field(..., description="ID администратора")
#     administrator_name: str = Field(..., description="Имя администратора")
#     clinic_id: str = Field(..., description="ID клиники")
#     date: str = Field(..., description="Дата звонка в формате YYYY-MM-DD")
#     call_id: Optional[str] = Field(None, description="Идентификатор звонка")
#     note_id: Optional[int] = Field(None, description="ID заметки AmoCRM")
#     contact_id: Optional[int] = Field(None, description="ID контакта AmoCRM")
#     lead_id: Optional[int] = Field(None, description="ID сделки AmoCRM")
#     metrics: CallMetrics = Field(..., description="Метрики звонка")
#     comments: Optional[str] = Field(None, description="Комментарии к оценке")
#     recommendations: Optional[List[str]] = Field(None, description="Рекомендации по улучшению")
#     call_classification: int = Field(..., description="Классификация звонка (1-8)")
#     created_at: str = Field(default_factory=lambda: datetime.now().isoformat(), description="Дата создания записи")

# class MetricsQueryParams(BaseModel):
#     """Параметры запроса для фильтрации метрик звонков"""
#     start_date: str = Field(..., description="Начальная дата (YYYY-MM-DD)")
#     end_date: str = Field(..., description="Конечная дата (YYYY-MM-DD)")
#     clinic_id: Optional[str] = Field(None, description="ID клиники для фильтрации")
#     administrator_ids: Optional[List[str]] = Field(None, description="Список ID администраторов")
#     call_classification: Optional[int] = Field(None, description="Тип звонка (1-8)")

# class MetricsResponse(BaseModel):
#     """Ответ API с метриками звонков"""
#     success: bool
#     message: str
#     data: Optional[Dict[str, Any]] = None


from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List
from datetime import datetime


class CallSubcriteria(BaseModel):
    """Подкритерии оценки звонка по категориям"""

    greeting: Optional[str] = Field(None, description="Оценка приветствия (✅, !, ±)")
    patient_name: Optional[str] = Field(
        None, description="Выяснение имени пациента (✅, !, ±)"
    )
    need_identification: Optional[str] = Field(
        None, description="Выявление потребностей (✅, !, ±)"
    )
    clinic_presentation: Optional[str] = Field(
        None, description="Презентация клиники (✅, !, ±)"
    )
    service_presentation: Optional[str] = Field(
        None, description="Презентация услуг (✅, !, ±)"
    )
    doctor_presentation: Optional[str] = Field(
        None, description="Презентация врачей (✅, !, ±)"
    )
    appointment: Optional[str] = Field(None, description="Запись на приём (✅, !, ±)")
    price: Optional[str] = Field(None, description="Обсуждение цены (✅, !, ±)")
    address: Optional[str] = Field(None, description="Предоставление адреса (✅, !, ±)")
    passport: Optional[str] = Field(
        None, description="Напоминание о паспорте (✅, !, ±)"
    )
    objection_handling: Optional[str] = Field(
        None, description="Работа с возражениями (✅, !, ±)"
    )
    next_step: Optional[str] = Field(
        None, description="Обсуждение следующего шага (✅, !, ±)"
    )
    speech_quality: Optional[str] = Field(None, description="Качество речи (✅, !, ±)")
    initiative: Optional[str] = Field(
        None, description="Проявление инициативы (✅, !, ±)"
    )
    recall_appeal: Optional[str] = Field(
        None, description="Апелляция к предыдущему звонку (✅, !, ±)"
    )
    clarification: Optional[str] = Field(
        None, description="Уточнение вопроса (✅, !, ±)"
    )


class CallMetrics(BaseModel):
    """Модель для хранения метрик звонка и оценок администратора"""

    greeting: float = Field(..., description="Оценка приветствия (0-10)")
    needs_identification: float = Field(
        ..., description="Оценка выявления потребностей (0-10)"
    )
    solution_proposal: float = Field(
        ..., description="Оценка предложения решения (0-10)"
    )
    objection_handling: float = Field(
        ..., description="Оценка работы с возражениями (0-10)"
    )
    call_closing: float = Field(..., description="Оценка завершения разговора (0-10)")
    tone: str = Field(
        ..., description="Тональность разговора (positive/neutral/negative)"
    )
    customer_satisfaction: str = Field(
        ..., description="Удовлетворенность клиента (high/medium/low)"
    )
    overall_score: float = Field(..., description="Общая оценка (0-10)")
    fg_percent: Optional[float] = Field(
        None, description="Процент выполнения критериев (FG%)"
    )
    subcriteria: Optional[CallSubcriteria] = Field(
        None, description="Детальные оценки по подкритериям"
    )


class CallMetricsRecord(BaseModel):
    """Модель для записи метрик звонка в базу данных"""

    administrator_id: str = Field(..., description="ID администратора")
    administrator_name: str = Field(..., description="Имя администратора")
    clinic_id: str = Field(..., description="ID клиники")
    date: str = Field(..., description="Дата звонка в формате YYYY-MM-DD")
    time: Optional[str] = Field(None, description="Время звонка в формате HH:MM:SS")
    call_id: Optional[str] = Field(None, description="Идентификатор звонка")
    note_id: Optional[int] = Field(None, description="ID заметки AmoCRM")
    contact_id: Optional[int] = Field(None, description="ID контакта AmoCRM")
    lead_id: Optional[int] = Field(None, description="ID сделки AmoCRM")
    call_type: Optional[str] = Field(
        None, description="Тип звонка (входящий/исходящий)"
    )
    call_category: Optional[str] = Field(
        None,
        description="Категория звонка (первичка_1/первичка_перезвон/подтверждение/вторичка)",
    )
    traffic_source: Optional[str] = Field(None, description="Источник трафика")
    client_request: Optional[str] = Field(
        None, description="Запрос клиента (краткое описание)"
    )
    conversion: Optional[bool] = Field(
        None, description="Конверсия (True - да, False - нет)"
    )
    metrics: CallMetrics = Field(..., description="Метрики звонка")
    comments: Optional[str] = Field(None, description="Комментарии к оценке")
    recommendations: Optional[List[str]] = Field(
        None, description="Рекомендации по улучшению"
    )
    call_classification: int = Field(..., description="Классификация звонка (1-8)")
    crm_link: Optional[str] = Field(None, description="Ссылка на карточку в CRM")
    transcription_link: Optional[str] = Field(
        None, description="Ссылка на транскрибацию"
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now().isoformat(),
        description="Дата создания записи",
    )


class MetricsQueryParams(BaseModel):
    """Параметры запроса для фильтрации метрик звонков"""

    start_date: str = Field(..., description="Начальная дата (YYYY-MM-DD)")
    end_date: str = Field(..., description="Конечная дата (YYYY-MM-DD)")
    clinic_id: Optional[str] = Field(None, description="ID клиники для фильтрации")
    administrator_ids: Optional[List[str]] = Field(
        None, description="Список ID администраторов"
    )
    call_classification: Optional[int] = Field(None, description="Тип звонка (1-8)")
    call_type: Optional[str] = Field(
        None, description="Тип звонка (входящий/исходящий)"
    )
    call_category: Optional[str] = Field(
        None,
        description="Категория звонка (первичка_1/первичка_перезвон/подтверждение/вторичка)",
    )
    traffic_source: Optional[str] = Field(None, description="Источник трафика")
    conversion: Optional[bool] = Field(None, description="Конверсия (True/False)")


class MetricsResponse(BaseModel):
    """Ответ API с метриками звонков"""

    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
