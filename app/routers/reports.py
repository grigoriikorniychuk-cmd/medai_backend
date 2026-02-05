from typing import List, Optional
from fastapi import APIRouter, HTTPException, status, BackgroundTasks, Response, Request
from fastapi.responses import FileResponse, JSONResponse
import logging
import os
from datetime import datetime

from ..models.report import ReportRequest, ReportResponse
from ..services.report_service import ReportService

# Настройка логирования
logger = logging.getLogger(__name__)

# Создаем роутер для работы с отчетами
router = APIRouter(tags=["reports"])


@router.post("/api/reports/generate", response_class=FileResponse)
async def generate_report(request: ReportRequest, background_tasks: BackgroundTasks):
    """
    Генерирует PDF отчет по оценке администраторов клиники.
    """
    try:
        # Создаем сервис отчетов
        report_service = ReportService()

        # Получаем метрики звонков из базы данных
        metrics_data = await report_service.get_call_metrics(
            request.start_date,
            request.end_date,
            request.administrator_ids,
            request.clinic_id,
        )

        # Если данных нет, возвращаем ошибку
        if not metrics_data:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "message": "Данные для отчета не найдены",
                    "data": None,
                },
            )

        # Генерируем графики
        charts, grouped_data = report_service.generate_charts(metrics_data)

        # Генерируем PDF-отчет
        pdf_path = report_service.generate_pdf_report(
            metrics_data, charts, grouped_data, request.report_type
        )

        # Планируем удаление временных файлов
        background_tasks.add_task(report_service.cleanup)

        # Формируем имя файла для скачивания
        filename = f"call_report_{request.start_date}_{request.end_date}.pdf"

        # Возвращаем файл PDF
        return FileResponse(
            path=pdf_path, filename=filename, media_type="application/pdf"
        )
    except Exception as e:
        logger.error(f"Ошибка при генерации отчета: {str(e)}")
        import traceback

        logger.error(f"Стек-трейс: {traceback.format_exc()}")

        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": f"Ошибка при генерации отчета: {str(e)}",
                "data": None,
            },
        )


@router.post("/api/reports/generate-test-data", response_model=ReportResponse)
async def generate_test_data(
    start_date: str = "01.03.2025",
    end_date: str = "26.03.2025",
    admin_ids: Optional[List[str]] = None,
    clinic_id: Optional[str] = None,
    num_administrators: int = 3,
    calls_per_admin: int = 10,
):
    """
    Генерирует тестовые данные для отчетов.
    """
    try:
        report_service = ReportService()
        result = await report_service.generate_test_data(
            start_date=start_date,
            end_date=end_date,
            administrator_ids=admin_ids,
            clinic_id=clinic_id,
            num_administrators=num_administrators,
            calls_per_admin=calls_per_admin,
        )
        return result
    except Exception as e:
        logger.error(f"Ошибка при генерации тестовых данных: {str(e)}")
        return ReportResponse(
            success=False,
            message=f"Ошибка при генерации тестовых данных: {str(e)}",
            data=None,
        )
