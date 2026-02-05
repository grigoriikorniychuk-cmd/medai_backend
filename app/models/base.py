"""
Базовые модели данных для всего проекта.
Предоставляет основные абстракции для моделей.
"""

from datetime import datetime
from typing import Any, Dict, Generic, List, Optional, TypeVar, Union, Annotated
from uuid import UUID, uuid4
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator, BeforeValidator
from bson import ObjectId


# Создаем кастомный тип для ObjectId MongoDB
class PyObjectId(str):
    """Кастомный тип для корректной сериализации ObjectId MongoDB."""
    
    @classmethod
    def validate(cls, v):
        if isinstance(v, ObjectId):
            return str(v)
        if not isinstance(v, str):
            raise TypeError("ObjectId required")
        if ObjectId.is_valid(v):
            return str(v)
        raise ValueError("Invalid ObjectId")


# Создаем тип для использования с аннотациями Pydantic v2
PydanticObjectId = Annotated[str, BeforeValidator(PyObjectId.validate)]


# Базовая модель для всех моделей
class BaseModelMedAI(BaseModel):
    """Базовая модель для всех моделей MedAI с общими настройками."""

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
        json_encoders={ObjectId: str, datetime: lambda dt: dt.isoformat()},
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="ignore",
    )


# Базовая модель с идентификатором
class IdentifiableModel(BaseModelMedAI):
    """Базовая модель с идентификатором."""

    id: Optional[PydanticObjectId] = Field(
        None, alias="_id", description="Уникальный идентификатор"
    )


# Базовая аудит модель для отслеживания изменений
class AuditModel(IdentifiableModel):
    """Базовая модель с полями аудита."""

    created_at: Optional[datetime] = Field(None, description="Дата создания")
    updated_at: Optional[datetime] = Field(None, description="Дата обновления")
    created_by: Optional[str] = Field(None, description="Создатель")
    updated_by: Optional[str] = Field(None, description="Обновивший")

    @model_validator(mode="before")
    @classmethod
    def set_datetimes(cls, values):
        """Устанавливает даты создания и обновления при необходимости."""
        if isinstance(values, dict):
            # Если запись новая (без id), устанавливаем дату создания
            if values.get("_id") is None and values.get("id") is None:
                values["created_at"] = datetime.now()

            # При любом сохранении устанавливаем дату обновления
            values["updated_at"] = datetime.now()
        return values


# Модель для результатов пагинации
class PageModel(BaseModelMedAI, Generic[TypeVar("T")]):
    """Модель для результатов пагинации."""

    items: List[TypeVar("T")] = Field(..., description="Элементы страницы")
    total: int = Field(..., description="Общее количество элементов")
    page: int = Field(1, description="Текущая страница")
    page_size: int = Field(10, description="Размер страницы")
    pages: int = Field(1, description="Общее количество страниц")

    @model_validator(mode="after")
    def calculate_pages(self):
        """Вычисляет общее количество страниц."""
        if self.page_size > 0:
            self.pages = (self.total + self.page_size - 1) // self.page_size
        else:
            self.pages = 1
        return self


# Модель для ответа API
class ApiResponse(BaseModelMedAI, Generic[TypeVar("T")]):
    """Стандартная модель ответа API."""

    success: bool = Field(True, description="Успешность операции")
    data: Optional[TypeVar("T")] = Field(None, description="Данные ответа")
    error: Optional[str] = Field(None, description="Сообщение об ошибке")
    timestamp: datetime = Field(
        default_factory=datetime.now, description="Временная метка"
    )

    @staticmethod
    def success_response(data: Any = None) -> "ApiResponse":
        """Создает успешный ответ."""
        return ApiResponse(success=True, data=data)

    @staticmethod
    def error_response(error: str) -> "ApiResponse":
        """Создает ответ с ошибкой."""
        return ApiResponse(success=False, error=error)


# Модель фильтрации по датам для отчетов
class DateRangeFilter(BaseModelMedAI):
    """Модель для фильтрации по диапазону дат."""

    start_date: str = Field(..., description="Начальная дата в формате YYYY-MM-DD")
    end_date: str = Field(..., description="Конечная дата в формате YYYY-MM-DD")

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_date_format(cls, v):
        """Валидирует формат даты."""
        try:
            datetime.strptime(v, "%Y-%m-%d")
            return v
        except ValueError:
            raise ValueError("Дата должна быть в формате YYYY-MM-DD")


# Настройки пагинации
class PaginationParams(BaseModelMedAI):
    """Параметры пагинации для запросов."""

    page: int = Field(1, ge=1, description="Номер страницы")
    page_size: int = Field(10, ge=1, le=100, description="Размер страницы")

    def get_skip(self) -> int:
        """Возвращает количество пропускаемых элементов."""
        return (self.page - 1) * self.page_size
