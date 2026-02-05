from fastapi import (
    APIRouter,
    HTTPException,
    status,
    BackgroundTasks,
    Response,
    Request,
    Query,
)
from fastapi.responses import FileResponse, JSONResponse
import logging
import os
from datetime import datetime, timedelta
from typing import List, Optional

from ..models.call_report import CallReportRequest, CallReportResponse, ReportType, AnalyticsReportRequest
from ..services.call_report_service import call_report_service
from ..services.call_admin_report_service import call_admin_report_service

# Настройка логирования
logger = logging.getLogger(__name__)

# Создаем роутер для работы с отчетами по звонкам
router = APIRouter(tags=["call_reports"])


@router.get("/api/call/reports/{filename}/download")
async def download_report(filename: str):
    """
    Скачивание файла отчета (PDF или Excel).
    """
    try:
        # Определяем тип файла
        file_path = os.path.join(call_report_service.reports_dir, filename)

        if not os.path.exists(file_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Файл {filename} не найден",
            )

        # Определяем MIME-тип на основе расширения файла
        media_type = (
            "application/pdf"
            if filename.endswith(".pdf")
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

        return FileResponse(path=file_path, filename=filename, media_type=media_type)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при скачивании отчета: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка при скачивании отчета: {str(e)}",
        )
