# app/routers/clinics.py

from fastapi import APIRouter, Depends, HTTPException, status, Body, Request, Query
from typing import List, Dict, Any
import logging
import httpx
import asyncio

from ..services.clinic_service import ClinicService
from ..models.clinic import ClinicResponse, DatalensUrlUpdate

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Admin Clinics"])

def get_clinic_service():
    return ClinicService()

@router.get("/api/admin/clinics", response_model=List[ClinicResponse])
async def get_all_clinics(
    clinic_service: ClinicService = Depends(get_clinic_service),
):
    """
    Получает список всех зарегистрированных клиник.
    """
    try:
        clinics = await clinic_service.get_all_clinics()
        return clinics
    except Exception as e:
        logger.error(f"Ошибка при получении списка клиник: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Внутренняя ошибка сервера при получении списка клиник"
        )

@router.put("/api/admin/clinics/{client_id}/datalens-url")
async def update_datalens_url(
    client_id: str,
    payload: DatalensUrlUpdate,
    clinic_service: ClinicService = Depends(get_clinic_service),
):
    """
    Добавляет или обновляет URL дашборда DataLens для клиники.
    """
    try:
        updated_clinic = await clinic_service.update_datalens_url(
            client_id, payload.datalens_dashboard_url
        )
        if not updated_clinic:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Клиника с client_id {client_id} не найдена"
            )
        return {"message": "URL для DataLens успешно обновлен", "client_id": client_id, "new_url": payload.datalens_dashboard_url}
    except Exception as e:
        logger.error(f"Ошибка при обновлении URL DataLens для client_id {client_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@router.post("/admin/clinics/{client_id}/process-data")
async def process_clinic_data(
    request: Request,
    client_id: str,
    start_date_str: str = Query(...),
    end_date_str: str = Query(...),
) -> Dict[str, Any]:
    """
    Оркестрирует последовательную обработку данных для клиники за указанный период.
    1. Синхронизирует звонки.
    2. Транскрибирует звонки.
    3. Анализирует звонки.
    4. Анализирует рекомендации.
    """
    # Заменяем http на https, чтобы избежать редиректа, который меняет POST на GET
    base_url = str(request.base_url).replace("http://", "https://")
    results = {}

    async with httpx.AsyncClient(timeout=None, follow_redirects=True) as client:
        try:
            # 1. Синхронизация звонков
            logger.info(f"Шаг 1: Синхронизация звонков для {client_id}...")
            sync_url = f"{base_url}api/calls-parallel-bulk/sync-by-date-range"
            sync_params = {
                "start_date_str": start_date_str,
                "end_date_str": end_date_str,
                "client_id": client_id
            }
            sync_response = await client.post(sync_url, params=sync_params)
            sync_response.raise_for_status()
            results['sync'] = sync_response.json()
            logger.info(f"Шаг 1: Синхронизация звонков для {client_id} завершена.")

            # 2. Транскрибация звонков
            logger.info(f"Шаг 2: Транскрибация звонков для {client_id}...")
            transcribe_url = f"{base_url}api/calls/transcribe-by-date-range"
            transcribe_params = {
                "start_date_str": start_date_str,
                "end_date_str": end_date_str,
                "client_id": client_id
            }
            transcribe_response = await client.post(transcribe_url, params=transcribe_params)
            transcribe_response.raise_for_status()
            results['transcription'] = transcribe_response.json()
            logger.info(f"Шаг 2: Транскрибация звонков для {client_id} завершена.")

            # 3. Анализ звонков
            logger.info(f"Шаг 3: Анализ звонков для {client_id}...")
            analyze_calls_url = f"{base_url}analyze-by-date-range"
            analyze_calls_params = {
                "start_date_str": start_date_str,
                "end_date_str": end_date_str,
                "client_id": client_id,
                "force_analyze": False
            }
            analyze_calls_response = await client.post(analyze_calls_url, params=analyze_calls_params)
            analyze_calls_response.raise_for_status()
            results['analysis'] = analyze_calls_response.json()
            logger.info(f"Шаг 3: Анализ звонков для {client_id} завершен.")

            # 4. Анализ рекомендаций
            logger.info(f"Шаг 4: Анализ рекомендаций для {client_id}...")
            analyze_recs_url = f"{base_url}api/recommendations/analyze-by-date-range"
            analyze_recs_params = {
                "start_date_str": start_date_str,
                "end_date_str": end_date_str,
                "client_id": client_id
            }
            analyze_recs_response = await client.post(analyze_recs_url, params=analyze_recs_params)
            analyze_recs_response.raise_for_status()
            results['recommendations'] = analyze_recs_response.json()
            logger.info(f"Шаг 4: Анализ рекомендаций для {client_id} завершен.")

            return {"message": "Обработка данных клиники успешно завершена", "results": results}

        except httpx.HTTPStatusError as e:
            logger.error(f"Ошибка при вызове внутреннего сервиса: {e.response.status_code} - {e.response.text}")
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"Ошибка на шаге '{list(results.keys())[-1] if results else 'sync'}': {e.response.text}"
            )
        except Exception as e:
            logger.error(f"Непредвиденная ошибка в процессе оркестрации для {client_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Внутренняя ошибка сервера в процессе оркестрации: {str(e)}"
            )


# ============== ENDPOINTS ДЛЯ УПРАВЛЕНИЯ ЛИМИТАМИ ==============

# NOTE: Endpoint для получения баланса ElevenLabs уже есть: GET /api/admin/elevenlabs-balance (в admin.py)

@router.post("/api/admin/elevenlabs/sync")
async def sync_elevenlabs_usage() -> Dict[str, Any]:
    """
    Синхронизирует данные использования с ElevenLabs API.
    Сохраняет результаты в базу данных для истории.
    Рекомендуется вызывать раз в день или по необходимости.
    """
    from app.services.clinic_limits_service import sync_with_elevenlabs
    
    try:
        result = await sync_with_elevenlabs()
        if not result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result.get("error", "Не удалось синхронизировать данные")
            )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при синхронизации с ElevenLabs: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/api/admin/clinics/{client_id}/limits")
async def get_clinic_limits(client_id: str) -> Dict[str, Any]:
    """
    Получает информацию о лимитах использования для конкретной клиники.
    """
    from app.services.clinic_limits_service import check_and_reset_monthly_limit
    
    try:
        limits = await check_and_reset_monthly_limit(client_id)
        if not limits:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Клиника с client_id {client_id} не найдена"
            )
        return limits
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при получении лимитов клиники {client_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/api/clinics/limits/all")
async def get_all_clinics_limits() -> Dict[str, Any]:
    """
    Получает информацию о лимитах для ВСЕХ клиник.
    Используется на фронте для отображения баланса каждой клиники.
    
    Returns:
        {
            "clinics": [
                {
                    "client_id": "xxx",
                    "name": "Название",
                    "monthly_limit_minutes": 3000,
                    "current_month_minutes": 150.5,
                    "remaining_minutes": 2849.5,
                    "usage_percent": 5.0
                },
                ...
            ],
            "total_limit_minutes": 18000,
            "total_used_minutes": 500.5,
            "total_remaining_minutes": 17499.5
        }
    """
    from app.services.mongodb_service import mongodb_service
    from app.services.clinic_limits_service import DEFAULT_CLINIC_LIMIT_MINUTES
    
    try:
        clinics = await mongodb_service.find_many("clinics", {})
        
        result = []
        total_limit = 0
        total_used = 0
        
        for clinic in clinics:
            monthly_limit = clinic.get("monthly_limit_minutes", DEFAULT_CLINIC_LIMIT_MINUTES)
            current_usage = clinic.get("current_month_minutes", 0)
            remaining = monthly_limit - current_usage
            usage_percent = round((current_usage / monthly_limit * 100), 1) if monthly_limit > 0 else 0
            
            result.append({
                "client_id": clinic.get("client_id"),
                "name": clinic.get("name", "Неизвестно"),
                "monthly_limit_minutes": monthly_limit,
                "current_month_minutes": round(current_usage, 2),
                "remaining_minutes": round(remaining, 2),
                "usage_percent": usage_percent
            })
            
            total_limit += monthly_limit
            total_used += current_usage
        
        return {
            "clinics": result,
            "total_limit_minutes": total_limit,
            "total_used_minutes": round(total_used, 2),
            "total_remaining_minutes": round(total_limit - total_used, 2)
        }
        
    except Exception as e:
        logger.error(f"Ошибка при получении лимитов всех клиник: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/api/admin/clinics/{client_id}/limits/reset")
async def reset_clinic_usage(client_id: str) -> Dict[str, Any]:
    """
    Сбрасывает счётчик использования клиники на 0.
    Используется для ручного сброса в начале месяца.
    """
    from app.services.mongodb_service import mongodb_service
    from datetime import datetime
    
    try:
        result = await mongodb_service.update_one(
            "clinics",
            {"client_id": client_id},
            {
                "$set": {
                    "current_month_minutes": 0,
                    "last_reset_date": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat()
                }
            }
        )
        
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Клиника с client_id {client_id} не найдена"
            )
        
        logger.info(f"✅ Счётчик использования клиники {client_id} сброшен на 0")
        return {
            "success": True,
            "message": f"Счётчик использования клиники {client_id} сброшен на 0 минут",
            "reset_date": datetime.now().isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при сбросе счётчика клиники {client_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.put("/api/admin/clinics/{client_id}/limits")
async def update_clinic_limits(
    client_id: str,
    monthly_limit_minutes: float = Query(..., description="Новый месячный лимит в минутах"),
    current_usage_minutes: float = Query(None, description="Новое значение текущего использования в минутах (опционально)")
) -> Dict[str, Any]:
    """
    Обновляет лимиты клиники (в минутах).
    Позволяет установить новый месячный лимит и опционально скорректировать текущее использование.
    """
    from app.services.mongodb_service import mongodb_service
    from datetime import datetime
    
    try:
        update_data = {
            "monthly_limit_minutes": monthly_limit_minutes,
            "updated_at": datetime.now().isoformat()
        }
        
        if current_usage_minutes is not None:
            update_data["current_month_minutes"] = current_usage_minutes
        
        result = await mongodb_service.update_one(
            "clinics",
            {"client_id": client_id},
            {"$set": update_data}
        )
        
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Клиника с client_id {client_id} не найдена"
            )
        
        logger.info(f"✅ Лимиты клиники {client_id} обновлены: monthly_limit={monthly_limit_minutes} минут")
        return {
            "success": True,
            "message": f"Лимиты клиники {client_id} обновлены",
            "monthly_limit_minutes": monthly_limit_minutes,
            "current_usage_minutes": current_usage_minutes
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при обновлении лимитов клиники {client_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/api/clinics/{clinic_id}/settings")
async def get_clinic_settings(
    clinic_id: str,
    clinic_service: ClinicService = Depends(get_clinic_service),
):
    """
    Получить настройки клиники.
    
    Возвращает:
    - admin_detection_method: "amocrm" или "ai_schedule"
    """
    try:
        clinic = await clinic_service.get_clinic_by_id(clinic_id)
        
        if not clinic:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Клиника {clinic_id} не найдена"
            )
        
        # Получаем метод определения администратора (по умолчанию amocrm)
        admin_detection_method = clinic.get("admin_detection_method", "amocrm")
        
        return {
            "success": True,
            "data": {
                "admin_detection_method": admin_detection_method
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при получении настроек клиники {clinic_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.patch("/api/clinics/{clinic_id}/settings")
async def update_clinic_settings(
    clinic_id: str,
    settings: Dict[str, Any] = Body(...),
    clinic_service: ClinicService = Depends(get_clinic_service),
):
    """
    Обновить настройки клиники.
    
    Поддерживаемые настройки:
    - admin_detection_method: "amocrm" или "ai_schedule"
    """
    try:
        success = await clinic_service.update_clinic_settings(clinic_id, settings)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Клиника {clinic_id} не найдена или настройки не изменились"
            )
        
        return {
            "success": True,
            "message": f"Настройки клиники {clinic_id} обновлены",
            "updated_settings": settings
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при обновлении настроек клиники {clinic_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
