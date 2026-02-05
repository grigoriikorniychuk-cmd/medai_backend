"""
Роутер для управления графиками работы администраторов.
"""

import logging
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.schedule_service import ScheduleService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/work-schedules", tags=["work_schedules"])


# Pydantic модели для запросов/ответов
class CreateScheduleRequest(BaseModel):
    """Запрос на создание графика"""
    clinic_id: str = Field(..., description="ID клиники")
    dates: List[str] = Field(..., description="Список дат в формате YYYY-MM-DD")
    first_name: str = Field(..., description="Имя администратора")
    last_name: str = Field(..., description="Фамилия администратора")
    
    class Config:
        schema_extra = {
            "example": {
                "clinic_id": "be735efe-2f45-4262-9df1-289db57a71b5",
                "dates": ["2025-12-26", "2025-12-27", "2025-12-28"],
                "first_name": "Анна",
                "last_name": "Иванова"
            }
        }


class UpdateScheduleRequest(BaseModel):
    """Запрос на обновление графика"""
    first_name: Optional[str] = Field(None, description="Новое имя")
    last_name: Optional[str] = Field(None, description="Новая фамилия")
    date: Optional[str] = Field(None, description="Новая дата в формате YYYY-MM-DD")
    
    class Config:
        schema_extra = {
            "example": {
                "first_name": "Мария",
                "last_name": "Петрова"
            }
        }


class ScheduleResponse(BaseModel):
    """Ответ с информацией о графике"""
    id: str
    clinic_id: str
    date: str
    first_name: str
    last_name: str


# TODO: для масштабирования добавить POST /batch для массовой загрузки графиков


@router.post("", status_code=201)
async def create_schedule(request: CreateScheduleRequest):
    """
    Создать записи графика для администратора на указанные даты.
    
    Можно указать несколько дат - будет создана отдельная запись для каждой даты.
    """
    try:
        schedule_service = ScheduleService()
        
        created_ids = await schedule_service.create_schedule(
            clinic_id=request.clinic_id,
            dates=request.dates,
            first_name=request.first_name,
            last_name=request.last_name,
        )
        
        if not created_ids:
            raise HTTPException(
                status_code=400,
                detail="Не удалось создать записи графика. Проверьте входные данные."
            )
        
        return {
            "message": f"Создано {len(created_ids)} записей графика",
            "created_ids": created_ids
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при создании графика: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("")
async def get_schedules(
    clinic_id: str = Query(..., description="ID клиники"),
    date_from: Optional[str] = Query(None, description="Начальная дата (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="Конечная дата (YYYY-MM-DD)"),
):
    """
    Получить графики клиники за период.
    
    Если date_from и date_to не указаны, возвращает все графики клиники.
    """
    try:
        schedule_service = ScheduleService()
        
        schedules = await schedule_service.get_schedules_by_date_range(
            clinic_id=clinic_id,
            date_from=date_from,
            date_to=date_to,
        )
        
        return {
            "count": len(schedules),
            "schedules": schedules
        }
        
    except Exception as e:
        logger.error(f"Ошибка при получении графиков: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{schedule_id}")
async def update_schedule(schedule_id: str, request: UpdateScheduleRequest):
    """
    Обновить запись графика.
    
    Можно обновить имя, фамилию или дату работы администратора.
    """
    try:
        schedule_service = ScheduleService()
        
        # Фильтруем только не-None значения
        updates = request.dict(exclude_none=True)
        
        if not updates:
            raise HTTPException(
                status_code=400,
                detail="Нет данных для обновления"
            )
        
        success = await schedule_service.update_schedule(
            schedule_id=schedule_id,
            updates=updates
        )
        
        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"График {schedule_id} не найден"
            )
        
        return {
            "message": f"График {schedule_id} успешно обновлён",
            "updated_fields": list(updates.keys())
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при обновлении графика: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{schedule_id}")
async def delete_schedule(schedule_id: str):
    """
    Удалить запись графика.
    """
    try:
        schedule_service = ScheduleService()
        
        success = await schedule_service.delete_schedule(schedule_id)
        
        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"График {schedule_id} не найден"
            )
        
        return {
            "message": f"График {schedule_id} успешно удалён"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при удалении графика: {e}")
        raise HTTPException(status_code=500, detail=str(e))
