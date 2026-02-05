from fastapi import APIRouter, HTTPException, Query, BackgroundTasks, status
from fastapi.responses import FileResponse
from datetime import datetime
import os
import re
from typing import Optional
from pydantic import BaseModel, Field

from app.settings.paths import MONGO_URI, DB_NAME
from app.services.generate_report import CallReportService
import logging

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/reports",
    tags=["reports"],
    responses={404: {"description": "Not found"}},
)

class ReportRequest(BaseModel):
    """Модель запроса на генерацию отчета"""
    start_date: str = Field(..., description="Дата начала периода в формате ДД.ММ.ГГГГ")
    end_date: str = Field(..., description="Дата конца периода в формате ДД.ММ.ГГГГ")
    clinic_id: Optional[str] = Field(None, description="ID клиники")

    class Config:
        schema_extra = {
            "example": {
                "start_date": "01.04.2025",
                "end_date": "30.04.2025",
                "clinic_id": "1234567890"
            }
        }

def validate_date_format(date_str: str) -> bool:
    """
    Проверка формата даты ДД.ММ.ГГГГ
    
    Args:
        date_str (str): Строка с датой
        
    Returns:
        bool: True, если дата соответствует формату, иначе False
    """
    pattern = r'^(0[1-9]|[12][0-9]|3[01])\.(0[1-9]|1[0-2])\.\d{4}$'
    return bool(re.match(pattern, date_str))

@router.post("/generate_call_report")
async def generate_call_report(report_request: ReportRequest, background_tasks: BackgroundTasks):
    """
    Генерация отчета по звонкам
    
    Args:
        report_request (ReportRequest): Параметры запроса
        background_tasks (BackgroundTasks): Фоновые задачи
        
    Returns:
        dict: Информация о статусе генерации отчета
    """
    # Проверка формата дат
    if not validate_date_format(report_request.start_date):
        raise HTTPException(status_code=400, detail="Некорректный формат даты начала периода. Используйте формат ДД.ММ.ГГГГ")
    
    if not validate_date_format(report_request.end_date):
        raise HTTPException(status_code=400, detail="Некорректный формат даты конца периода. Используйте формат ДД.ММ.ГГГГ")
    
    # Проверка правильности периода
    try:
        start_date = datetime.strptime(report_request.start_date, "%d.%m.%Y")
        end_date = datetime.strptime(report_request.end_date, "%d.%m.%Y")
        
        if start_date > end_date:
            raise HTTPException(status_code=400, detail="Дата начала периода не может быть позже даты конца периода")
    except ValueError:
        raise HTTPException(status_code=400, detail="Ошибка при преобразовании дат")
    
    # Создание сервиса для генерации отчета
    report_service = CallReportService(
        mongodb_uri=MONGO_URI,
        mongodb_name=DB_NAME,
        # reports_dir=REPORTS_DIR
    )
    
    # try:
        # Генерация отчета
    report_filename = await report_service.generate_report(
        start_date_str=report_request.start_date,
        end_date_str=report_request.end_date,
        clinic_id=report_request.clinic_id
    )
    
    if not report_filename:
        raise HTTPException(status_code=404, detail="Не удалось сгенерировать отчет. Проверьте параметры запроса.")
    
    # Проверка существования файла отчета
    if not os.path.exists(report_filename):
        raise HTTPException(status_code=404, detail=f"Файл отчета не найден: {report_filename}")
    
    return {"status": "success", "message": "Отчет успешно сгенерирован", "filename": report_filename}
        
    # except Exception as e:
    #     logger.error(f"Ошибка при генерации отчета: {str(e)}")
    #     raise HTTPException(status_code=500, detail=f"Ошибка при генерации отчета: {str(e)}")

@router.get("/download_call_report/{filename}")
async def download_call_report(filename: str):
    """
    Скачивание сгенерированного отчета
    
    Args:
        filename (str): Имя файла отчета
        
    Returns:
        FileResponse: Файл отчета
    """
    # Проверка безопасности пути файла
    if '..' in filename or '/' in filename:
        raise HTTPException(status_code=400, detail="Некорректное имя файла")
    
    # Формируем полный путь к файлу
    file_path = os.path.join(os.path.dirname(filename), filename)
    
    # Проверка существования файла
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Файл не найден: {file_path}")
    
    # Возвращаем файл для скачивания
    return FileResponse(
        path=file_path,
        filename=os.path.basename(file_path),
        media_type="application/pdf"
    )


@router.get("/generate-excel")
async def generate_excel_report(
    start_date: str = Query(..., description="Начальная дата в формате DD.MM.YYYY"),
    end_date: str = Query(..., description="Конечная дата в формате DD.MM.YYYY"), 
    clinic_id: Optional[str] = Query(None, description="ID клиники (опционально)")):
    """
    Генерирует Excel-отчет и возвращает имя файла
    """
    report_service = CallReportService()
    try:
        datetime.strptime(start_date, "%d.%m.%Y")
        datetime.strptime(end_date, "%d.%m.%Y")
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неверный формат даты. Используйте формат DD.MM.YYYY"
        )
    report_path = await report_service.generate_excel_report(start_date, end_date, clinic_id)
    if report_path is None or not os.path.exists(report_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Не удалось создать отчет. Возможно, нет данных за указанный период."
        )
    filename = os.path.basename(report_path)
    return {"status": "success", "filename": filename}