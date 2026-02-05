from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime


class ReportRequest(BaseModel):
    start_date: str = Field(..., description="Начальная дата отчета (DD.MM.YYYY)")
    end_date: str = Field(..., description="Конечная дата отчета (DD.MM.YYYY)")
    administrator_ids: Optional[List[str]] = Field(
        None, description="Список ID администраторов (если пусто, то все)"
    )
    clinic_id: Optional[str] = Field(
        None, description="ID клиники (если нужен отчет по одной клинике)"
    )
    report_type: str = Field(
        "full", description="Тип отчета: full, summary, individual"
    )


class ReportResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
