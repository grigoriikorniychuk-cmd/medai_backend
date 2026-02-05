from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List, Union
from datetime import datetime
from enum import Enum


class EventType(str, Enum):
    """Типы событий AmoCRM"""
    OUTGOING_CALL = "outgoing_call"
    INCOMING_CALL = "incoming_call"
    INCOMING_CHAT_MESSAGE = "incoming_chat_message"
    ALL = "all"


class AmoCRMCredentials(BaseModel):
    client_id: str = Field(..., description="Client ID из интеграции AmoCRM")
    client_secret: str = Field(..., description="Client Secret из интеграции AmoCRM")
    subdomain: str = Field(
        ..., description="Поддомен вашей AmoCRM (example в example.amocrm.ru)"
    )
    redirect_url: str = Field(
        ..., description="URL перенаправления из настроек интеграции"
    )


class AmoCRMAuthRequest(AmoCRMCredentials):
    auth_code: str = Field(
        ..., description="Код авторизации, полученный после редиректа"
    )


class LeadRequest(BaseModel):
    client_id: str = Field(..., description="Client ID из интеграции AmoCRM")
    lead_id: int = Field(..., description="ID сделки в AmoCRM")


class ContactRequest(BaseModel):
    client_id: str = Field(..., description="Client ID из интеграции AmoCRM")
    contact_id: int = Field(..., description="ID контакта в AmoCRM")


class LeadsByDateRequest(BaseModel):
    client_id: str = Field(..., description="Client ID из интеграции AmoCRM")
    date: str = Field(
        ..., description="Дата в формате ДД.ММ.ГГГГ (например, 13.03.2025)"
    )


class APIResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


class ContactResponse(BaseModel):
    id: int
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None


class CallResponse(BaseModel):
    contact_id: int
    call_link: Optional[str] = None
    download_url: Optional[str] = None
    local_path: Optional[str] = None


class EventsRequest(BaseModel):
    client_id: str = Field(..., description="Client ID из интеграции AmoCRM")
    event_type: EventType = Field(EventType.ALL, description="Тип события для фильтрации")
    start_date: Optional[str] = Field(None, description="Дата начала в формате ДД.ММ.ГГГГ или ГГГГ-ММ-ДД")
    end_date: Optional[str] = Field(None, description="Дата окончания в формате ДД.ММ.ГГГГ или ГГГГ-ММ-ДД")
    limit: Optional[int] = Field(50, description="Количество событий для получения", ge=1, le=250)


class EventsStatsRequest(BaseModel):
    client_id: str = Field(..., description="Client ID из интеграции AmoCRM")
    start_date: Optional[str] = Field(None, description="Дата начала в формате ДД.ММ.ГГГГ или ГГГГ-ММ-ДД")
    end_date: Optional[str] = Field(None, description="Дата окончания в формате ДД.ММ.ГГГГ или ГГГГ-ММ-ДД")
    include_details: Optional[bool] = Field(False, description="Включить детальную информацию по звонкам и сообщениям")
    max_pages: Optional[int] = Field(10, description="Максимальное количество страниц для запроса (для ограничения времени выполнения)", ge=1, le=50)


class CallsExportRequest(BaseModel):
    client_id: str = Field(..., description="Client ID из интеграции AmoCRM")
    start_date: Optional[str] = Field(None, description="Дата начала в формате ДД.ММ.ГГГГ или ГГГГ-ММ-ДД")
    end_date: Optional[str] = Field(None, description="Дата окончания в формате ДД.ММ.ГГГГ или ГГГГ-ММ-ДД")
    max_pages: Optional[int] = Field(50, description="Максимальное количество страниц для запроса событий", ge=1, le=100)
    detailed: Optional[bool] = Field(True, description="Получать детальную информацию о звонках через API заметок")
    max_calls: Optional[int] = Field(5000, description="Максимальное количество звонков для обработки", ge=1, le=10000)
    concurrency: Optional[int] = Field(5, description="Количество параллельных запросов для получения деталей", ge=1, le=20)
    filter_zero_duration: Optional[bool] = Field(True, description="Фильтровать звонки с нулевой длительностью")
