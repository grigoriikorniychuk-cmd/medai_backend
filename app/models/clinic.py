from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List
from datetime import datetime


class ClinicRegistrationRequest(BaseModel):
    name: str = Field(..., description="Название клиники")
    amocrm_subdomain: str = Field(
        ..., description="Поддомен AmoCRM (example в example.amocrm.ru)"
    )
    client_id: str = Field(..., description="Client ID из интеграции AmoCRM")
    client_secret: str = Field(..., description="Client Secret из интеграции AmoCRM")
    redirect_url: str = Field(
        ..., description="URL перенаправления из настроек интеграции"
    )
    auth_code: str = Field(..., description="Код авторизации AmoCRM")
    amocrm_pipeline_id: Optional[int] = Field(None, description="ID воронки в AmoCRM")
    monthly_limit: int = Field(100, description="Месячный лимит звонков для клиники")


class AdministratorResponse(BaseModel):
    id: str
    name: str
    email: Optional[str] = None
    amocrm_user_id: str
    monthly_limit: Optional[int] = None
    current_month_usage: int = 0


class ClinicResponse(BaseModel):
    id: str
    name: str
    client_id: str
    amocrm_subdomain: str
    amocrm_pipeline_id: Optional[int] = None
    monthly_limit: int
    current_month_usage: int
    last_reset_date: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    datalens_dashboard_url: Optional[str] = None
    administrators: List[AdministratorResponse] = []


class DatalensUrlUpdate(BaseModel):
    datalens_dashboard_url: str = Field(..., description="Новый URL дашборда в DataLens")


class ProcessDataRequest(BaseModel):
    start_date: str = Field(..., description="Начальная дата в формате DD.MM.YYYY или YYYY-MM-DD")
    end_date: str = Field(..., description="Конечная дата в формате DD.MM.YYYY или YYYY-MM-DD")


class DatalensUrlResponse(BaseModel):
    datalens_dashboard_url: Optional[str]


class ApiResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
