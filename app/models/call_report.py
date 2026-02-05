from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum


class ReportType(str, Enum):
    """Типы отчетов для генерации"""
    SUMMARY = "summary"
    INDIVIDUAL = "individual"
    FULL = "full"
    ANALYTICS = "analytics"


class VisualizationType(str, Enum):
    """Типы визуализаций для аналитических отчетов"""
    CATEGORY_DISTRIBUTION = "category_distribution"
    CALL_DURATION = "call_duration"
    TIME_DISTRIBUTION = "time_distribution"
    SUCCESS_RATE = "success_rate"


class CallReportRequest(BaseModel):
    """Запрос на генерацию отчета по звонкам"""
    start_date: str = Field(..., description="Начальная дата в формате DD.MM.YYYY")
    end_date: str = Field(..., description="Конечная дата в формате DD.MM.YYYY")
    report_type: ReportType = Field(..., description="Тип отчета")
    clinic_id: Optional[str] = Field(None, description="ID клиники (по умолчанию - все клиники)")
    administrator_ids: Optional[List[str]] = Field(None, description="Список ID администраторов (по умолчанию - все администраторы)")
    email_recipients: Optional[List[str]] = Field(None, description="Список адресов электронной почты для отправки отчета")
    send_email: bool = Field(False, description="Отправить отчет по электронной почте")


class AnalyticsReportRequest(BaseModel):
    """Запрос на генерацию аналитического отчета на основе коллекции calls"""
    start_date: str = Field(..., description="Начальная дата в формате DD.MM.YYYY")
    end_date: str = Field(..., description="Конечная дата в формате DD.MM.YYYY")
    clinic_id: Optional[str] = Field(None, description="ID клиники (по умолчанию - все клиники)")
    administrator_ids: Optional[List[str]] = Field(None, description="Список ID администраторов (по умолчанию - все)")
    visualization_type: Optional[VisualizationType] = Field(None, description="Тип визуализации для отчета")
    format: str = Field("png", description="Формат изображений (png, jpg, svg)")
    include_raw_data: bool = Field(False, description="Включить сырые данные в ответ")


class AdministratorStats(BaseModel):
    """Статистика по администратору"""

    id: str = Field(..., description="ID администратора")
    name: str = Field(..., description="Имя администратора")
    total_calls: int = Field(..., description="Общее количество звонков")
    incoming_calls: int = Field(..., description="Количество входящих звонков")
    outgoing_calls: int = Field(..., description="Количество исходящих звонков")
    incoming_conversion: float = Field(
        ..., description="Конверсия входящих звонков (%)"
    )
    outgoing_conversion: float = Field(
        ..., description="Конверсия исходящих звонков (%)"
    )
    overall_conversion: float = Field(..., description="Общая конверсия (%)")
    avg_score: float = Field(..., description="Средний FG% (0-10)")
    avg_greeting: float = Field(0.0, description="Средняя оценка приветствия (0-10)")
    avg_needs_identification: float = Field(0.0, description="Средняя оценка выявления потребностей (0-10)")
    avg_solution_proposal: float = Field(0.0, description="Средняя оценка предложения решения (0-10)")
    avg_objection_handling: float = Field(0.0, description="Средняя оценка работы с возражениями (0-10)")
    avg_call_closing: float = Field(0.0, description="Средняя оценка завершения звонка (0-10)")


class DetailedCall(BaseModel):
    """Детальная информация о звонке для отчета"""

    id: str = Field(..., description="ID звонка в MongoDB")
    date: str = Field(..., description="Дата звонка")
    time: str = Field(..., description="Время звонка")
    administrator_name: str = Field(..., description="Имя администратора")
    call_type: str = Field(..., description="Тип звонка (входящий/исходящий)")
    call_category: str = Field(..., description="Категория звонка")
    source: str = Field(..., description="Источник трафика")
    fg_percent: float = Field(..., description="FG% (0-100)")
    criteria: str = Field(..., description="Критерии оценки (✅, !, ±)")
    conversion: bool = Field(..., description="Конверсия (да/нет)")
    comment: Optional[str] = Field(None, description="Комментарий")
    crm_link: Optional[str] = Field(None, description="Ссылка на CRM")
    transcription_link: Optional[str] = Field(
        None, description="Ссылка на транскрипцию"
    )
    duration: Optional[int] = Field(None, description="Длительность звонка в секундах")
    customer_satisfaction: Optional[str] = Field(None, description="Удовлетворенность клиента")
    tone: Optional[str] = Field(None, description="Тон разговора")


class CallTypeStats(BaseModel):
    """Статистика по типам звонков"""

    type_id: int = Field(..., description="ID типа звонка")
    name: str = Field(..., description="Название типа звонка")
    count: int = Field(..., description="Количество звонков")
    percentage: float = Field(..., description="Процент от общего количества")
    conversion_rate: float = Field(..., description="Конверсия (%)")
    avg_duration: Optional[float] = Field(None, description="Средняя длительность звонка (сек)")


class SourceStats(BaseModel):
    """Статистика по источникам трафика"""

    source: str = Field(..., description="Источник трафика")
    count: int = Field(..., description="Количество звонков")
    percentage: float = Field(..., description="Процент от общего количества")
    conversion_rate: float = Field(..., description="Конверсия (%)")
    avg_score: Optional[float] = Field(None, description="Средний FG% для источника (0-100)")


class WeekdayStats(BaseModel):
    """Статистика по дням недели"""
    
    day: str = Field(..., description="День недели")
    count: int = Field(..., description="Количество звонков")
    conversion_rate: float = Field(..., description="Конверсия (%)")
    avg_score: float = Field(..., description="Средний FG% (0-100)")


class DailyStats(BaseModel):
    """Статистика по дням"""
    
    date: str = Field(..., description="Дата")
    total_calls: int = Field(..., description="Общее количество звонков")
    incoming_calls: int = Field(..., description="Входящие звонки")
    outgoing_calls: int = Field(..., description="Исходящие звонки")
    conversion_rate: float = Field(..., description="Конверсия (%)")


class CallReportData(BaseModel):
    """Данные отчета по звонкам"""

    report_id: str = Field(..., description="ID отчета")
    report_type: ReportType = Field(..., description="Тип отчета")
    clinic_id: Optional[str] = Field(None, description="ID клиники")
    clinic_name: Optional[str] = Field(None, description="Название клиники")
    start_date: str = Field(..., description="Начальная дата")
    end_date: str = Field(..., description="Конечная дата")
    generated_at: str = Field(..., description="Дата и время генерации отчета")

    # Общая статистика
    total_calls: int = Field(..., description="Общее количество звонков")
    incoming_calls: int = Field(..., description="Количество входящих звонков")
    outgoing_calls: int = Field(..., description="Количество исходящих звонков")
    conversion_rate: float = Field(..., description="Общая конверсия (%)")
    avg_score: float = Field(..., description="Средний FG% (0-100)")
    avg_duration: Optional[float] = Field(None, description="Средняя длительность звонка (сек)")

    # Статистика по администраторам
    administrators: List[AdministratorStats] = Field(
        ..., description="Статистика по администраторам"
    )

    # Детальная информация о звонках
    calls: Optional[List[DetailedCall]] = Field(
        None, description="Детальная информация о звонках"
    )

    # Статистика по типам звонков
    call_types: List[CallTypeStats] = Field(
        ..., description="Статистика по типам звонков"
    )

    # Статистика по источникам трафика
    sources: List[SourceStats] = Field(
        ..., description="Статистика по источникам трафика"
    )
    
    # Статистика по дням недели
    weekday_stats: Optional[List[WeekdayStats]] = Field(
        None, description="Статистика по дням недели"
    )
    
    # Статистика по дням
    daily_stats: Optional[List[DailyStats]] = Field(
        None, description="Статистика по дням"
    )

    # Ссылки на файлы отчета
    pdf_link: Optional[str] = Field(None, description="Ссылка на PDF отчет")
    excel_link: Optional[str] = Field(None, description="Ссылка на Excel отчет")


class CallReportResponse(BaseModel):
    """Ответ на запрос генерации отчета по звонкам"""
    success: bool = Field(..., description="Флаг успешного выполнения запроса")
    message: str = Field(..., description="Сообщение о результате запроса")
    data: Optional[dict] = Field(None, description="Данные отчета")


class ReportFormat(str, Enum):
    PDF = "pdf"
    PNG = "png"
    JPEG = "jpeg"
    SVG = "svg"
