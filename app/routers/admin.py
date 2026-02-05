from fastapi import (
    APIRouter,
    HTTPException,
    status,
    Depends,
    Body,
    Query,
    BackgroundTasks,
)
from fastapi.responses import FileResponse
from typing import Optional, Dict, Any, List
import logging
import json
import os
import requests
import asyncio
import uuid
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from ..models.clinic import (
    ClinicRegistrationRequest,
    ApiResponse,
    DatalensUrlResponse,
)
from ..models.amocrm import AmoCRMAuthRequest, AmoCRMCredentials, EventsRequest, EventsStatsRequest, EventType, APIResponse
from ..services.clinic_service import ClinicService
from ..services.limits_service import LimitsService
import os
from fastapi.responses import FileResponse, JSONResponse

# from ..services.amocrm_service import AsyncAmoCRMClient
from mlab_amo_async.amocrm_client import AsyncAmoCRMClient
from mlab_amo_async.filters import DateRangeFilter
from motor.motor_asyncio import AsyncIOMotorClient
from app.settings.paths import MONGO_URI, DB_NAME

# Импортируем функции из calls.py для работы с датами
from .calls import convert_date_string
# Импортируем данные для доступа к AmoCRM
from app.services.amo_credentials import get_full_amo_credentials
from app.settings.auth import get_elevenlabs_api_key  # Импортируем функцию для получения API-ключа

# Настройка логирования
logger = logging.getLogger(__name__)


# Создаем роутер
router = APIRouter(tags=["admin"])


@router.get("/api/admin/elevenlabs-balance", summary="Получить баланс ElevenLabs")
async def get_elevenlabs_balance():
    """
    Возвращает информацию о балансе токенов и минут в ElevenLabs.
    """
    api_key = get_elevenlabs_api_key()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось получить API-ключ для ElevenLabs."
        )

    url = "https://api.elevenlabs.io/v1/user/subscription"
    headers = {
        "Accept": "application/json",
        "xi-api-key": api_key
    }

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()  # Проверка на ошибки HTTP

        data = response.json()

        # === ВАЖНО: ElevenLabs PRO тариф ===
        # Базовый лимит: 500,000 кредитов/месяц = 300 часов STT
        # API может возвращать character_limit > 500k из-за rollover (накопление до 3x)
        # Мы используем фиксированный лимит 500k для консистентности расчётов
        #
        # Если нужен реальный лимит с rollover:
        # character_limit = data.get("character_limit", 500000)
        
        TOTAL_PLAN_MINUTES = 18000   # 300 часов
        TOTAL_PLAN_TOKENS = 500000   # PRO план базовый лимит

        # Фиксируем лимит на 500k (игнорируем rollover)
        data["character_limit"] = TOTAL_PLAN_TOKENS

        used_tokens = data.get("character_count", 0)
        remaining_tokens = TOTAL_PLAN_TOKENS - used_tokens

        if TOTAL_PLAN_TOKENS > 0:
            percentage_remaining = remaining_tokens / TOTAL_PLAN_TOKENS
            minutes_remaining = TOTAL_PLAN_MINUTES * percentage_remaining
        else:
            minutes_remaining = 0

        # Добавляем расчетные поля в ответ
        data["minutes_remaining"] = round(minutes_remaining, 2)
        data["tokens_remaining"] = remaining_tokens

        return data

    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка при запросе к API ElevenLabs: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Не удалось получить данные от ElevenLabs: {e}"
        )
    except Exception as e:
        logger.error(f"Непредвиденная ошибка при получении баланса ElevenLabs: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {e}"
        )


# Зависимости для сервисов
def get_clinic_service():
    return ClinicService()


def get_limits_service():
    return LimitsService()


LOG_DIRECTORY = "/app/logs"


@router.on_event("startup")
async def startup_event_logs():
    """Создает директорию для логов при старте приложения, если она не существует."""
    if not os.path.exists(LOG_DIRECTORY):
        os.makedirs(LOG_DIRECTORY)


@router.get("/api/admin/logs", tags=["Admin Logs"], summary="Получить список лог-файлов")
async def list_logs():
    """Возвращает список доступных для скачивания лог-файлов."""
    try:
        if not os.path.isdir(LOG_DIRECTORY):
            return JSONResponse(content={"logs": []})
        files = [
            f
            for f in os.listdir(LOG_DIRECTORY)
            if os.path.isfile(os.path.join(LOG_DIRECTORY, f))
        ]
        return JSONResponse(content={"logs": sorted(files, reverse=True)})
    except FileNotFoundError:
        return JSONResponse(content={"logs": []})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/admin/logs/{filename}", tags=["Admin Logs"], summary="Скачать лог-файл")
async def download_log(filename: str):
    """Скачивает указанный лог-файл."""
    file_path = os.path.join(LOG_DIRECTORY, filename)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="Файл не найден")

    return FileResponse(path=file_path, filename=filename, media_type="text/plain")


@router.post("/api/admin/clinics", response_model=ApiResponse)
async def register_clinic(
    request: ClinicRegistrationRequest,
    clinic_service: ClinicService = Depends(get_clinic_service),
):
    try:
        # Регистрируем клинику и создаем администраторов
        # (инициализация токена происходит внутри сервиса)
        result = await clinic_service.register_clinic(request.dict())

        return ApiResponse(
            success=True,
            message=f"Клиника {request.name} успешно зарегистрирована с авторизацией в AmoCRM",
            data=result,
        )
    except Exception as e:
        logger.error(f"Ошибка при регистрации клиники: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))



@router.post("/api/admin/clinics/{clinic_id}/refresh-token", response_model=ApiResponse)
async def refresh_amocrm_token(
    clinic_id: str,
    client_secret: Optional[str] = None,
    redirect_url: Optional[str] = None,
    clinic_service: ClinicService = Depends(get_clinic_service),
):
    """
    Обновляет токен для конкретной клиники.
    Адаптация существующего эндпоинта /api/amocrm/refresh-token.
    """
    try:
        logger.info(
            f"Запрос на диагностику/обновление токена для клиники ID={clinic_id}"
        )

        # Получаем информацию о клинике
        clinic = await clinic_service.get_clinic_by_id(clinic_id)

        if not clinic:
            return ApiResponse(
                success=False, message=f"Клиника с ID {clinic_id} не найдена", data=None
            )

        # Получаем token_data из MongoDB
        mongo_client = AsyncIOMotorClient(MONGO_URI)
        db = mongo_client[DB_NAME]
        collection = db["tokens"]

        token_data = await collection.find_one({"client_id": clinic["client_id"]})

        if not token_data:
            return ApiResponse(
                success=False,
                message=f"Токен для клиники ID={clinic_id} (client_id={clinic['client_id']}) не найден в базе данных",
                data={
                    "suggestion": "Необходимо выполнить первичную авторизацию через /api/admin/clinics"
                },
            )

        # Выводим информацию о токене для диагностики
        token_info = {
            "client_id": clinic["client_id"],
            "has_access_token": "access_token" in token_data,
            "has_refresh_token": "refresh_token" in token_data,
            "has_subdomain": "subdomain" in token_data,
            "updated_at": token_data.get("updated_at", "Неизвестно"),
        }

        # Создаем экземпляр клиента AmoCRM
        client = AsyncAmoCRMClient(
            client_id=clinic["client_id"],
            client_secret=client_secret or clinic["client_secret"],
            subdomain=clinic["amocrm_subdomain"],
            redirect_url=redirect_url or clinic["redirect_url"],
            mongo_uri=MONGO_URI,
            db_name=DB_NAME,
        )

        # Проверяем правильность хранимого токена
        try:
            # Пытаемся получить токен (это вызовет обновление, если он истек)
            access_token = await client.token_manager.get_access_token()

            # Если мы дошли сюда, то токен либо действителен, либо успешно обновлен
            return ApiResponse(
                success=True,
                message="Токен действителен или успешно обновлен",
                data={
                    "token_info": token_info,
                    "access_token_preview": (
                        access_token[:10] + "..." if access_token else None
                    ),
                    "clinic_id": clinic_id,
                },
            )
        except Exception as token_error:
            # Если возникла ошибка, попробуем принудительно обновить токен
            logger.error(f"Ошибка при проверке токена: {token_error}")

            try:
                # Явно указываем нужные параметры
                client.token_manager.subdomain = clinic["amocrm_subdomain"]

                # Принудительно пытаемся обновить токен
                refresh_token = await client.token_manager._storage.get_refresh_token(
                    clinic["client_id"]
                )

                if not refresh_token:
                    return ApiResponse(
                        success=False,
                        message="Refresh token отсутствует в базе данных",
                        data={
                            "token_info": token_info,
                            "error": str(token_error),
                            "suggestion": "Необходимо выполнить первичную авторизацию через /api/admin/clinics",
                        },
                    )

                # Формируем запрос на обновление токена
                body = {
                    "client_id": clinic["client_id"],
                    "client_secret": client_secret or clinic["client_secret"],
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "redirect_uri": redirect_url or clinic["redirect_url"],
                }

                logger.info(
                    f"Попытка принудительно обновить токен: {json.dumps(body, default=str)}"
                )

                response = requests.post(
                    f"https://{clinic['amocrm_subdomain']}.amocrm.ru/oauth2/access_token",
                    json=body,
                )

                if response.status_code == 200:
                    data = response.json()

                    # Сохраняем новые токены
                    await client.token_manager._storage.save_tokens(
                        clinic["client_id"],
                        data["access_token"],
                        data["refresh_token"],
                        clinic["amocrm_subdomain"],
                    )

                    return ApiResponse(
                        success=True,
                        message="Токен успешно обновлен принудительно",
                        data={
                            "old_token_info": token_info,
                            "access_token_preview": data["access_token"][:10] + "...",
                            "clinic_id": clinic_id,
                        },
                    )
                else:
                    return ApiResponse(
                        success=False,
                        message=f"Ошибка при принудительном обновлении токена: HTTP {response.status_code}",
                        data={
                            "token_info": token_info,
                            "response": response.text,
                            "suggestion": "Возможно, интеграция была отключена или удалена в AmoCRM",
                        },
                    )

            except Exception as forced_refresh_error:
                return ApiResponse(
                    success=False,
                    message=f"Ошибка при принудительном обновлении токена: {str(forced_refresh_error)}",
                    data={
                        "token_info": token_info,
                        "original_error": str(token_error),
                        "clinic_id": clinic_id,
                    },
                )
    except Exception as e:
        error_msg = f"Ошибка при диагностике/обновлении токена: {str(e)}"
        logger.error(error_msg)

        return ApiResponse(success=False, message=error_msg, data=None)


async def get_calls_via_events(amo_client, task_id: str, start_date_obj, end_date_obj, credentials):
    """Получение звонков через API /api/v4/events (по рекомендации с форума AmoCRM)"""
    logger.info(f"[{task_id}] Получение звонков через API events...")
    calls_from_events = []
    
    try:
        start_dt_utc = datetime(start_date_obj.year, start_date_obj.month, start_date_obj.day, tzinfo=timezone.utc)
        end_dt_utc = datetime(end_date_obj.year, end_date_obj.month, end_date_obj.day, 23, 59, 59, tzinfo=timezone.utc)
        
        all_events = []
        page = 1
        
        while True:
            events_params = {
                "limit": 250,
                "page": page,
                "filter[created_at][from]": int(start_dt_utc.timestamp()),
                "filter[created_at][to]": int(end_dt_utc.timestamp()),
                "filter[type]": "outgoing_call,incoming_call"
            }
            
            try:
                # Пробуем использовать прямой HTTP запрос через aiohttp
                import aiohttp
                
                # Получаем базовый URL и токен из клиента
                base_url = f"https://{credentials['subdomain']}.amocrm.ru"
                
                # Получаем токен доступа
                token_info = await amo_client.get_token()
                access_token = token_info.get('access_token')
                
                if not access_token:
                    logger.error(f"[{task_id}] Не удалось получить токен доступа")
                    break
                
                headers = {
                    'Authorization': f'Bearer {access_token}',
                    'Content-Type': 'application/json'
                }
                
                # Формируем URL для API events
                events_url = f"{base_url}/api/v4/events"
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(events_url, params=events_params, headers=headers) as response:
                        status = response.status
                        if status == 200:
                            resp = await response.json()
                        else:
                            resp = await response.text()
                            
            except Exception as e:
                logger.error(f"[{task_id}] Ошибка API events запроса: {e}")
                break
                
            if status != 200:
                logger.warning(f"[{task_id}] API events вернул статус {status}: {resp}")
                break
                
            if "_embedded" in resp and "events" in resp["_embedded"]:
                events = resp["_embedded"]["events"]
                all_events.extend(events)
                logger.info(f"[{task_id}] Страница {page}: получено {len(events)} событий звонков")
                
                if "_links" not in resp or "next" not in resp["_links"]:
                    break
                page += 1
                
                if page > 50:
                    logger.warning(f"[{task_id}] Ограничение по страницам events: {page} страниц")
                    break
            else:
                break
        
        logger.info(f"[{task_id}] Получено {len(all_events)} событий звонков всего.")
        
        if len(all_events) > 0:
            logger.info(f"[{task_id}] Пример структуры события: {all_events[0]}")
        
        for event in all_events:
            event_type = event.get("type")
            entity_type = event.get("entity_type")
            entity_id = event.get("entity_id")
            
            call = {
                "id": event.get("id"),
                "created_at": event.get("created_at"),
                "updated_at": event.get("created_at"),
                "type": event_type,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "params": event.get("value_after", {})
            }
            
            if entity_type == "lead":
                call["lead_id"] = entity_id
            elif entity_type == "contact":
                call["contact_id"] = entity_id
            
            calls_from_events.append(call)
        
    except Exception as e:
        logger.error(f"[{task_id}] Ошибка при получении звонков через API events: {e}")
        calls_from_events = []
    
    return calls_from_events


async def _perform_amocrm_check_task(
    task_id: str,
    client_id: str,
    start_date_str: str,
    end_date_str: str
):
    """Фоновая задача для проверки данных AmoCRM с использованием API /api/v4/events"""
    start_time = datetime.now()
    try:
        start_date_obj = convert_date_string(start_date_str)
        end_date_obj = convert_date_string(end_date_str)
        logger.info(f"[{task_id}] Анализ AmoCRM для {client_id} за {start_date_obj.strftime('%Y-%m-%d')} - {end_date_obj.strftime('%Y-%m-%d')}")

        credentials = await get_full_amo_credentials(client_id=client_id)
        amo_client = AsyncAmoCRMClient(
            client_id=credentials["client_id"], client_secret=credentials["client_secret"],
            subdomain=credentials["subdomain"], redirect_url=credentials["redirect_url"],
            mongo_uri=MONGO_URI, db_name=DB_NAME
        )
        
        from ..models.amocrm import LeadsByDateRequest
        from ..routers.amocrm import get_leads_by_date
        all_leads_by_date, total_leads, all_leads_for_period = [], 0, []
        current_date_obj = start_date_obj
        while current_date_obj <= end_date_obj:
            date_str = current_date_obj.strftime('%d.%m.%Y')
            request = LeadsByDateRequest(client_id=credentials['client_id'], date=date_str)
            response = await get_leads_by_date(request)
            day_leads = 0
            if response.success and response.data:
                day_leads = response.data.get("total_leads", 0)
                total_leads += day_leads
                if response.data.get("leads"):
                    all_leads_for_period.extend(response.data["leads"])
            all_leads_by_date.append({"date": date_str, "total": day_leads})
            current_date_obj += timedelta(days=1)
            await asyncio.sleep(0.1)
        logger.info(f"[{task_id}] Найдено сделок: {total_leads}")

        # Получение звонков через API /api/v4/events (по рекомендации с форума AmoCRM)
        events_calls = await get_calls_via_events(amo_client, task_id, start_date_obj, end_date_obj, credentials)
        
        # Разделяем звонки из событий на сделки и контакты для совместимости с существующим кодом
        calls_from_leads = [call for call in events_calls if "lead_id" in call]
        calls_from_contacts = [call for call in events_calls if "contact_id" in call and "lead_id" not in call]
        
        calls_from_leads_count = len(calls_from_leads)
        calls_from_contacts_count = len(calls_from_contacts)
        
        logger.info(f"[{task_id}] Получено звонков через API events: из сделок {calls_from_leads_count}, из контактов {calls_from_contacts_count}, всего {len(events_calls)}")
        
        # Используем все звонки из API events
        all_calls = events_calls
        
        # Анализ звонков для отчета
        total_calls = len(all_calls)
        logger.info(f"[{task_id}] Всего найдено уникальных звонков: {total_calls}")

        zero_duration_calls, duplicates_by_duration_contact, advanced_dupes = 0, {}, {}
        for call in all_calls:
            params = call.get('params', {})
            duration = params.get('duration', 0)
            contact_id = call.get('contact_id', 0)
            created_at = call.get('created_at', 0)
            if duration == 0: zero_duration_calls += 1
            advanced_key = (duration, contact_id, created_at)
            if advanced_key not in advanced_dupes: advanced_dupes[advanced_key] = []
            advanced_dupes[advanced_key].append(call)
            duplicate_key = (duration, contact_id)
            if duplicate_key not in duplicates_by_duration_contact: duplicates_by_duration_contact[duplicate_key] = []
            duplicates_by_duration_contact[duplicate_key].append(call)

        duplicates_count = sum(len(calls) - 1 for calls in duplicates_by_duration_contact.values() if len(calls) > 1)
        unique_calls = len(advanced_dupes)

        leads_by_date_str = "\n  ".join([f"{d['date']}: {d['total']} сделок" for d in all_leads_by_date])
        zero_p = f"{zero_duration_calls/total_calls*100:.1f}%" if total_calls > 0 else "0%"
        dupes_p = f"{duplicates_count/total_calls*100:.1f}%" if total_calls > 0 else "0%"
        stats_report = f"""СТАТИСТИКА AMO\n---\nПериод: {start_date_obj.strftime("%d.%m.%Y")} - {end_date_obj.strftime("%d.%m.%Y")}\nВсего сделок: {total_leads}\nЗвонков из сделок: {calls_from_leads_count}\nЗвонков из контактов: {calls_from_contacts_count}\nВсего звонков (уникальных ID): {total_calls}\n---\nСделки по дням:\n  {leads_by_date_str}\n---\nАнализ звонков:\nНулевых: {zero_duration_calls} ({zero_p})\nДублей (duration+contact): {duplicates_count} ({dupes_p})\nУникальных (duration+contact+created): {unique_calls}\n---"""
        logger.info(stats_report)

        result = {
            "success": True, "task_id": task_id, "statistics": {
                "total_leads": total_leads,
                "calls_from_leads": calls_from_leads_count,
                "calls_from_contacts": calls_from_contacts_count,
                "total_calls": total_calls,
                "zero_duration_calls": zero_duration_calls,
                "duplicates_found": duplicates_count,
                "unique_calls": unique_calls,
                "leads_by_date": all_leads_by_date,
                "formatted_report": stats_report
            }
        }
        result_file = f"/tmp/amocrm_checks/{task_id}.json"
        os.makedirs(os.path.dirname(result_file), exist_ok=True)
        with open(result_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        logger.info(f"[{task_id}] Результат сохранен в {result_file}")

    except Exception as e:
        error_msg = f"Ошибка при проверке данных AmoCRM: {str(e)}"
        logger.error(f"[{task_id}] {error_msg}")
        error_result = {"success": False, "task_id": task_id, "error": error_msg}
        result_file = f"/tmp/amocrm_checks/{task_id}.json"
        os.makedirs(os.path.dirname(result_file), exist_ok=True)
        with open(result_file, 'w', encoding='utf-8') as f:
            json.dump(error_result, f, ensure_ascii=False, indent=2)


@router.post("/api/admin/check-amocrm-calls")
async def check_amocrm_calls(
    background_tasks: BackgroundTasks,
    client_id: str = Query(..., description="ID клиента AmoCRM"),
    start_date_str: str = Query(..., description="Начальная дата (DD.MM.YYYY или YYYY-MM-DD)"),
    end_date_str: str = Query(..., description="Конечная дата (DD.MM.YYYY или YYYY-MM-DD)")
) -> Dict[str, Any]:
    """
    Запускает проверку данных AmoCRM за период в фоновом режиме.
    Возвращает ID задачи для получения результата.
    """
    try:
        # Парсинг дат для валидации
        start_date_obj = convert_date_string(start_date_str)
        end_date_obj = convert_date_string(end_date_str)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Ошибка парсинга даты: {str(e)}")

    if not start_date_obj or not end_date_obj:
        raise HTTPException(status_code=400, detail="Некорректный формат даты. Используйте DD.MM.YYYY или YYYY-MM-DD.")

    if start_date_obj > end_date_obj:
        raise HTTPException(status_code=400, detail="Начальная дата не может быть позже конечной даты.")

    # Генерация уникального ID задачи
    task_id = f"amocrm_check_{uuid.uuid4().hex[:12]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    # Запуск фоновой задачи
    background_tasks.add_task(
        _perform_amocrm_check_task,
        task_id,
        client_id,
        start_date_str,
        end_date_str
    )
    
    logger.info(f"Запущена фоновая задача анализа AmoCRM: {task_id}")
    
    return {
        "success": True,
        "message": "Задача анализа AmoCRM запущена в фоновом режиме",
        "task_id": task_id,
        "client_id": client_id,
        "period": {
            "start_date": start_date_obj.strftime('%Y-%m-%d'),
            "end_date": end_date_obj.strftime('%Y-%m-%d')
        },
        "download_url": f"/api/admin/check-amocrm-calls/{task_id}/download"
    }


@router.get("/api/admin/check-amocrm-calls/{task_id}/download")
async def download_amocrm_check_result(task_id: str):
    """
    Скачивает результат анализа AmoCRM по ID задачи
    """
    result_dir = "/tmp/amocrm_checks"
    result_file = os.path.join(result_dir, f"{task_id}.json")
    
    if not os.path.exists(result_file):
        raise HTTPException(
            status_code=404, 
            detail=f"Результат анализа с ID {task_id} не найден. Возможно, задача еще выполняется или ID неверный."
        )
    
    return FileResponse(
        path=result_file, 
        filename=f"amocrm_check_{task_id}.json",
        media_type="application/json"
    )


@router.post("/api/admin/amocrm/events/stats", response_model=APIResponse)
async def get_amocrm_events_stats(request: EventsStatsRequest) -> APIResponse:
    """
    Получение статистики по событиям из AmoCRM, с агрегацией по типам.
    Использует пагинацию для получения полной статистики по всем событиям за период.
    """
    client = None
    try:
        # Начало измерения времени
        start_time = datetime.now()
        
        logger.info(f"Запрос статистики по событиям AmoCRM: client_id={request.client_id}")
        
        # Находим клинику по client_id
        clinic_service = ClinicService()
        clinic = await clinic_service.find_clinic_by_client_id(request.client_id)
        
        if not clinic:
            return APIResponse(
                success=False,
                message=f"Клиника с client_id={request.client_id} не найдена",
                data=None
            )

        # Подготовка временного диапазона, если указаны даты
        start_timestamp = None
        end_timestamp = None
        
        if request.start_date:
            try:
                # Получаем дату начала как объект datetime
                date_obj = convert_date_string(request.start_date)
                if not date_obj:
                    return APIResponse(success=False, message=f"Ошибка в формате начальной даты", data=None)
                
                # Преобразуем в timestamp начала дня (00:00:00)
                start_timestamp = int(datetime.combine(date_obj.date(), datetime.min.time()).timestamp())
                logger.info(f"Начальная дата: {date_obj.strftime('%d.%m.%Y')}, timestamp: {start_timestamp}")
            except Exception as e:
                return APIResponse(success=False, message=f"Ошибка в формате начальной даты: {str(e)}", data=None)
        
        if request.end_date:
            try:
                # Получаем дату окончания как объект datetime
                date_obj = convert_date_string(request.end_date)
                if not date_obj:
                    return APIResponse(success=False, message=f"Ошибка в формате конечной даты", data=None)
                
                # Преобразуем в timestamp конца дня (23:59:59)
                end_timestamp = int(datetime.combine(date_obj.date(), datetime.max.time()).timestamp())
                logger.info(f"Конечная дата: {date_obj.strftime('%d.%m.%Y')}, timestamp: {end_timestamp}")
            except Exception as e:
                return APIResponse(success=False, message=f"Ошибка в формате конечной даты: {str(e)}", data=None)
        
        # Создаем клиент AmoCRM
        client = AsyncAmoCRMClient(
            client_id=clinic["client_id"],
            client_secret=clinic["client_secret"],
            subdomain=clinic["amocrm_subdomain"],
            redirect_url=clinic["redirect_url"],
            mongo_uri=MONGO_URI,
            db_name=DB_NAME
        )
        
        # Статистика по типам событий
        event_stats = defaultdict(int)
        
        # Множества для хранения уникальных ID сделок и контактов
        unique_leads = set()  # Уникальные сделки
        unique_contacts = set()  # Уникальные контакты
        
        # Статистика по звонкам
        call_stats = {
            "outgoing_call": 0,
            "incoming_call": 0,
            "total_calls": 0,
            "total_duration": 0,
            "avg_duration": 0,
            "calls_with_recording": 0,
            "zero_duration_calls": 0,  # Звонки с нулевой продолжительностью
            "duplicate_calls": 0  # Дубликаты звонков
        }
        
        # Статистика по сообщениям чата
        chat_stats = {
            "incoming_chat_message": 0,
            "outgoing_chat_message": 0,
            "total_messages": 0
        }
        
        # Словарь для отслеживания дублей звонков
        # Ключ: (entity_id, дата, duration), Значение: счетчик
        call_fingerprints = defaultdict(int)
        
        # Параметры для пагинации
        page = 1
        page_limit = 250  # Максимальное количество событий на страницу
        total_events = 0
        has_more = True
        next_page_url = None
        detailed_events = []
        
        # Пути API для попыток запросов
        api_paths = ["api/v4/events", "api/v2/events", "events"]
        api_path = None
        
        # Проверка какой из путей API работает
        for path in api_paths:
            try:
                logger.info(f"Проверка пути API: {path}")
                params = {
                    "page": 1,
                    "limit": 1
                }
                response, status = await client.contacts.request("get", path, params=params)
                if status == 200:
                    logger.info(f"Успешный путь API: {path}")
                    api_path = path
                    break
            except Exception as e:
                logger.warning(f"Ошибка при проверке пути {path}: {str(e)}")
                continue
        
        # Если не найден работающий путь API
        if not api_path:
            return APIResponse(
                success=False,
                message="Не удалось найти работающий эндпоинт событий AmoCRM",
                data={
                    "tried_paths": api_paths,
                    "hint": "Возможно, в вашем тарифе AmoCRM нет доступа к API событий"
                }
            )
            
        # Запрашиваем события с пагинацией
        while has_more and page <= request.max_pages:
            params = {
                "page": page,
                "limit": page_limit
            }
            
            # Добавляем фильтр по дате, если указана
            if start_timestamp:
                params["filter[created_at][from]"] = start_timestamp
            if end_timestamp:
                params["filter[created_at][to]"] = end_timestamp
            
            logger.info(f"Запрос событий, страница {page} из {request.max_pages}")
            
            try:
                response_data, status_code = await client.contacts.request("get", api_path, params=params)
                
                if status_code != 200:
                    logger.error(f"Ошибка при запросе событий на странице {page}: HTTP {status_code}")
                    break
                
                # Обрабатываем события на текущей странице
                if "_embedded" in response_data and "events" in response_data["_embedded"]:
                    events = response_data["_embedded"]["events"]
                    page_events_count = len(events)
                    total_events += page_events_count
                    logger.info(f"Получено {page_events_count} событий на странице {page}")
                    
                    # Анализируем каждое событие
                    for event in events:
                        event_type = event.get("type")
                        event_stats[event_type] += 1
                        
                        # Собираем уникальные сделки и контакты
                        entity_id = event.get("entity_id")
                        entity_type = event.get("entity_type")
                        
                        if entity_type == "lead" and entity_id:
                            unique_leads.add(str(entity_id))
                        elif entity_type == "contact" and entity_id:
                            unique_contacts.add(str(entity_id))
                        
                        # Статистика по звонкам
                        if event_type in ["outgoing_call", "incoming_call"]:
                            call_stats[event_type] += 1
                            call_stats["total_calls"] += 1
                            
                            # Дополнительная информация о звонке
                            entity_id_str = str(entity_id) if entity_id else ""
                            created_date = datetime.fromtimestamp(event.get("created_at", 0)).strftime("%Y-%m-%d") if event.get("created_at") else ""
                            created_timestamp = event.get("created_at", 0)
                            
                            # Проверка наличия данных о звонке
                            # В API событий информация о звонке часто отсутствует
                            duration = 0
                            phone = ""
                            has_link = False
                            
                            # Пытаемся получить информацию из value_after, если она есть
                            if "value_after" in event and isinstance(event["value_after"], dict):
                                value = event["value_after"]
                                duration = value.get("duration", 0)
                                phone = value.get("phone", "")
                                has_link = bool(value.get("link"))
                                
                                # Подсчитываем звонки с записью
                                if has_link:
                                    call_stats["calls_with_recording"] += 1
                            
                            # Если нет value_after, считаем звонок нулевым (поскольку отсутствует информация)
                            if duration == 0:
                                call_stats["zero_duration_calls"] += 1
                            else:
                                call_stats["total_duration"] += duration
                            
                            # Создаем отпечаток звонка для поиска дублей
                            # Даже если нет полных данных, мы можем использовать сочетание entity_id, даты и временной метки
                            if entity_id_str and created_timestamp > 0:
                                call_fingerprint = (entity_id_str, str(created_timestamp))
                                call_fingerprints[call_fingerprint] += 1
                                
                            # Если есть телефон, создаем более точный отпечаток
                            if entity_id_str and phone and created_date:
                                precise_fingerprint = (entity_id_str, created_date, phone, duration)
                                call_fingerprints[precise_fingerprint] += 1
                            
                            # Сохраняем детали звонка, если нужно
                            if request.include_details:
                                event_data = {
                                    "id": event.get("id"),
                                    "type": event_type,
                                    "entity_id": event.get("entity_id"),
                                    "entity_type": event.get("entity_type"),
                                    "created_at": event.get("created_at"),
                                    "created_date": datetime.fromtimestamp(event.get("created_at", 0)).strftime("%d.%m.%Y %H:%M:%S") if event.get("created_at") else None,
                                }
                                
                                if "value_after" in event and isinstance(event["value_after"], dict):
                                    value = event["value_after"]
                                    event_data["call_info"] = {
                                        "duration": value.get("duration"),
                                        "duration_formatted": f"{value.get('duration', 0) // 60}:{value.get('duration', 0) % 60:02d}" if value.get("duration") else "0:00",
                                        "phone": value.get("phone"),
                                        "link": value.get("link"),
                                        "status": value.get("status"),
                                        "call_result": value.get("call_result"),
                                        "call_status": value.get("call_status")
                                    }
                                
                                detailed_events.append(event_data)
                        
                        # Статистика по сообщениям чата
                        elif event_type in ["incoming_chat_message", "outgoing_chat_message"]:
                            chat_stats[event_type] += 1
                            chat_stats["total_messages"] += 1
                            
                            # Сохраняем детали сообщения, если нужно
                            if request.include_details and "value_after" in event:
                                value = event["value_after"]
                                event_data = {
                                    "id": event.get("id"),
                                    "type": event_type,
                                    "entity_id": event.get("entity_id"),
                                    "entity_type": event.get("entity_type"),
                                    "created_at": event.get("created_at"),
                                    "created_date": datetime.fromtimestamp(event.get("created_at", 0)).strftime("%d.%m.%Y %H:%M:%S") if event.get("created_at") else None,
                                    "message_info": {
                                        "message": value.get("message") if isinstance(value, dict) else None,
                                        "sender": value.get("sender") if isinstance(value, dict) else None
                                    }
                                }
                                detailed_events.append(event_data)
                    
                    # Проверяем наличие следующей страницы
                    if "_links" in response_data and "next" in response_data["_links"]:
                        next_page_url = response_data["_links"]["next"].get("href")
                        page += 1
                    else:
                        has_more = False
                        logger.info(f"Достигнут конец списка событий (всего получено: {total_events})")
                else:
                    has_more = False
                    logger.info("Нет событий в ответе")
                
                # Небольшая пауза между запросами
                await asyncio.sleep(0.5)
                
            except Exception as e:
                logger.error(f"Ошибка при запросе событий на странице {page}: {str(e)}")
                break
        
        # Дополнительная статистика
        execution_time = (datetime.now() - start_time).total_seconds()
        
        # Подсчет дублей звонков
        duplicate_count = 0
        for fingerprint, count in call_fingerprints.items():
            if count > 1:
                # Если звонок с таким отпечатком встречается больше одного раза - это дубль
                duplicate_count += (count - 1)  # Вычитаем оригинальный звонок
        
        call_stats["duplicate_calls"] = duplicate_count
        
        # Рассчитываем среднюю продолжительность звонка
        if call_stats["total_calls"] > 0:
            call_stats["avg_duration"] = call_stats["total_duration"] / call_stats["total_calls"]
            # Форматированная средняя продолжительность
            avg_mins = int(call_stats["avg_duration"]) // 60
            avg_secs = int(call_stats["avg_duration"]) % 60
            call_stats["avg_duration_formatted"] = f"{avg_mins}:{avg_secs:02d}"
        
        # Формируем ответ
        result = {
            "total_events": total_events,
            "entity_stats": {
                "total_leads": len(unique_leads),
                "total_contacts": len(unique_contacts)
            },
            "event_types": dict(event_stats),
            "call_stats": call_stats,
            "chat_stats": chat_stats,
            "period": {
                "start_date": datetime.fromtimestamp(start_timestamp).strftime("%d.%m.%Y") if start_timestamp else "No limit",
                "end_date": datetime.fromtimestamp(end_timestamp).strftime("%d.%m.%Y") if end_timestamp else "No limit"
            },
            "execution_info": {
                "pages_processed": page,
                "max_pages": request.max_pages,
                "has_more": has_more,
                "execution_time_seconds": execution_time
            }
        }
        
        # Добавляем детали, если запрошены
        if request.include_details:
            result["detailed_events"] = detailed_events
        
        return APIResponse(
            success=True,
            message=f"Получена статистика по {total_events} событиям, сделки: {len(unique_leads)}, звонки: {call_stats['total_calls']} (нулевых: {call_stats['zero_duration_calls']}, дублей: {call_stats['duplicate_calls']})",
            data=result
        )
    except Exception as e:
        error_msg = f"Ошибка при получении статистики событий AmoCRM: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return APIResponse(success=False, message=error_msg, data=None)
    finally:
        if client:
            await client.close()


@router.get("/api/admin/check-amocrm-calls/{task_id}/status")
async def get_amocrm_check_status(task_id: str) -> Dict[str, Any]:
    """
    Проверяет статус выполнения задачи анализа AmoCRM
    """
    result_dir = "/tmp/amocrm_checks"
    result_file = os.path.join(result_dir, f"{task_id}.json")
    
    if not os.path.exists(result_file):
        return {
            "success": True,
            "task_id": task_id,
            "status": "running",
            "message": "Задача выполняется"
        }
    
    try:
        with open(result_file, 'r', encoding='utf-8') as f:
            result = json.load(f)
        
        return {
            "success": True,
            "task_id": task_id,
            "status": "completed" if result.get("success") else "failed",
            "message": "Задача завершена" if result.get("success") else f"Ошибка: {result.get('error', 'Неизвестная ошибка')}",
            "completed_at": result.get("completed_at"),
            "result_available": True,
            "download_url": f"/api/admin/check-amocrm-calls/{task_id}/download"
        }
    except Exception as e:
        return {
            "success": False,
            "task_id": task_id,
            "status": "error",
            "message": f"Ошибка при чтении результата: {str(e)}"
        }


@router.post("/api/admin/amocrm/events", response_model=APIResponse)
async def get_amocrm_events(request: EventsRequest) -> APIResponse:
    """
    Получение событий из AmoCRM, включая звонки (outgoing_call) и сообщения чата (incoming_chat_message).
    
    Использует API v4 events для получения событий.
    """
    client = None
    try:
        logger.info(f"Запрос событий AmoCRM: client_id={request.client_id}, тип={request.event_type.value}")
        
        # Находим клинику по client_id
        clinic_service = ClinicService()
        clinic = await clinic_service.find_clinic_by_client_id(request.client_id)
        
        if not clinic:
            return APIResponse(
                success=False,
                message=f"Клиника с client_id={request.client_id} не найдена",
                data=None
            )
        
        # Подготовка временного диапазона, если указаны даты
        start_timestamp = None
        end_timestamp = None
        
        if request.start_date:
            try:
                # Получаем дату начала как объект datetime
                date_obj = convert_date_string(request.start_date)
                if not date_obj:
                    return APIResponse(success=False, message=f"Ошибка в формате начальной даты", data=None)
                
                # Преобразуем в timestamp начала дня (00:00:00)
                start_timestamp = int(datetime.combine(date_obj.date(), datetime.min.time()).timestamp())
                logger.info(f"Начальная дата: {date_obj.strftime('%d.%m.%Y')}, timestamp: {start_timestamp}")
            except Exception as e:
                return APIResponse(success=False, message=f"Ошибка в формате начальной даты: {str(e)}", data=None)
        
        if request.end_date:
            try:
                # Получаем дату окончания как объект datetime
                date_obj = convert_date_string(request.end_date)
                if not date_obj:
                    return APIResponse(success=False, message=f"Ошибка в формате конечной даты", data=None)
                
                # Преобразуем в timestamp конца дня (23:59:59)
                end_timestamp = int(datetime.combine(date_obj.date(), datetime.max.time()).timestamp())
                logger.info(f"Конечная дата: {date_obj.strftime('%d.%m.%Y')}, timestamp: {end_timestamp}")
            except Exception as e:
                return APIResponse(success=False, message=f"Ошибка в формате конечной даты: {str(e)}", data=None)
        
        # Создаем клиент AmoCRM
        client = AsyncAmoCRMClient(
            client_id=clinic["client_id"],
            client_secret=clinic["client_secret"],
            subdomain=clinic["amocrm_subdomain"],
            redirect_url=clinic["redirect_url"],
            mongo_uri=MONGO_URI,
            db_name=DB_NAME
        )
        
        # Формируем параметры запроса
        params = {
            "limit": request.limit
        }
        
        # Добавляем фильтр по временному диапазону
        if start_timestamp:
            params["filter[created_at][from]"] = start_timestamp
        if end_timestamp:
            params["filter[created_at][to]"] = end_timestamp
        
        # Добавляем фильтр по типу события, если запрошен конкретный тип
        if request.event_type != EventType.ALL:
            params["filter[type]"] = request.event_type.value
        
        # Отправляем запрос к API
        logger.info(f"Отправка запроса к events API с параметрами: {params}")
        
        # Пробуем несколько вариантов путей к API событий
        api_paths = ["api/v4/events", "api/v2/events", "events"]
        response_data = None
        status_code = 404
        exception = None
        
        for path in api_paths:
            try:
                logger.info(f"Попытка запроса к пути: {path}")
                response_data, status_code = await client.contacts.request("get", path, params=params)
                if status_code == 200:
                    logger.info(f"Успешный запрос к пути: {path}")
                    break
            except Exception as e:
                logger.warning(f"Ошибка при запросе к пути {path}: {str(e)}")
                exception = e
                continue
        
        if status_code != 200:
            error_msg = f"Ошибка при запросе событий: HTTP {status_code}"
            if exception:
                error_msg += f". Последняя ошибка: {str(exception)}"
            
            logger.error(error_msg)
            
            # Проверим, возможно, эндпоинт не поддерживается или у пользователя нет прав
            # Попробуем запросить сведения о текущем аккаунте для проверки авторизации
            try:
                logger.info(f"Проверка доступа к API AmoCRM...")
                account_info, account_status = await client.contacts.request("get", "api/v4/account", params={})
                
                if account_status == 200:
                    logger.info(f"Доступ к аккаунту AmoCRM есть, но эндпоинт событий недоступен")
                    return APIResponse(
                        success=False,
                        message=f"Эндпоинт событий недоступен для данного аккаунта AmoCRM или недостаточно прав для доступа",
                        data={
                            "error": error_msg,
                            "account_info": {
                                "name": account_info.get("name", "Неизвестно"),
                                "subdomain": account_info.get("subdomain", "Неизвестно")
                            }
                        }
                    )
                
            except Exception as acc_error:
                logger.error(f"Ошибка при проверке доступа к аккаунту: {str(acc_error)}")
            
            # Возвращаем ошибку с деталями
            return APIResponse(
                success=False,
                message=error_msg,
                data={
                    "response": response_data,
                    "tried_paths": api_paths,
                    "status_code": status_code,
                    "hint": "Возможно, в вашем тарифе AmoCRM нет доступа к API событий или требуется другой способ авторизации"
                }
            )
        
        # Обрабатываем ответ
        events = []
        if "_embedded" in response_data and "events" in response_data["_embedded"]:
            raw_events = response_data["_embedded"]["events"]
            logger.info(f"Получено {len(raw_events)} событий")
            
            # Обрабатываем каждое событие
            for event in raw_events:
                # Добавляем базовую информацию о событии
                event_data = {
                    "id": event.get("id"),
                    "type": event.get("type"),
                    "entity_id": event.get("entity_id"),
                    "entity_type": event.get("entity_type"),
                    "created_at": event.get("created_at"),
                    "created_date": datetime.fromtimestamp(event.get("created_at", 0)).strftime("%d.%m.%Y %H:%M:%S") if event.get("created_at") else None,
                    "value_after": event.get("value_after"),
                    "value_before": event.get("value_before")
                }
                
                # Добавляем дополнительную информацию для звонков
                if event.get("type") == EventType.OUTGOING_CALL.value or event.get("type") == EventType.INCOMING_CALL.value:
                    # Получаем дополнительную информацию о звонке из значения
                    if event.get("value_after") and isinstance(event.get("value_after"), dict):
                        value = event.get("value_after")
                        event_data["call_info"] = {
                            "duration": value.get("duration"),
                            "duration_formatted": f"{value.get('duration', 0) // 60}:{value.get('duration', 0) % 60:02d}" if value.get("duration") else "0:00",
                            "phone": value.get("phone"),
                            "link": value.get("link"),  # Ссылка на запись разговора, если доступна
                            "status": value.get("status"),
                            "call_result": value.get("call_result"),
                            "call_status": value.get("call_status")
                        }
                
                # Добавляем дополнительную информацию для сообщений чата
                elif event.get("type") == EventType.INCOMING_CHAT_MESSAGE.value:
                    if event.get("value_after") and isinstance(event.get("value_after"), dict):
                        value = event.get("value_after")
                        event_data["message_info"] = {
                            "message": value.get("message"),
                            "sender": value.get("sender"),
                            "receiver": value.get("receiver")
                        }
                
                events.append(event_data)
            
            # Сортируем события по дате (сначала новые)
            events.sort(key=lambda e: e.get("created_at", 0), reverse=True)
        
        # Формируем ответ
        return APIResponse(
            success=True,
            message=f"Получено {len(events)} событий" + (f" типа {request.event_type.value}" if request.event_type != EventType.ALL else ""),
            data={
                "total": len(events),
                "events": events,
                "_links": response_data.get("_links", {}),
                "_page": response_data.get("_page", {})
            }
        )
    except Exception as e:
        error_msg = f"Ошибка при получении событий AmoCRM: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return APIResponse(success=False, message=error_msg, data=None)
    finally:
        if client:
            await client.close()


@router.post("/api/admin/amocrm/all-calls", response_model=APIResponse)  
async def get_all_amocrm_calls(request: EventsStatsRequest) -> APIResponse:
    """
    Получает ВСЕ события входящих и исходящих звонков из AmoCRM за указанный период.
    Возвращает СЫРЫЕ данные как есть от API.
    """
    client = None
    try:
        logger.info(f"Запрос СЫРЫХ данных по звонкам: client_id={request.client_id}")

        # Находим клинику
        clinic_service = ClinicService()
        clinic = await clinic_service.find_clinic_by_client_id(request.client_id)
        if not clinic:
            return APIResponse(success=False, message=f"Клиника не найдена", data=None)

        # Парсим даты
        start_timestamp = None
        end_timestamp = None
        if request.start_date:
            date_obj = convert_date_string(request.start_date)
            start_timestamp = int(datetime.combine(date_obj.date(), datetime.min.time()).timestamp())
        if request.end_date:
            date_obj = convert_date_string(request.end_date)
            end_timestamp = int(datetime.combine(date_obj.date(), datetime.max.time()).timestamp())

        # Создаем клиент
        client = AsyncAmoCRMClient(
            client_id=clinic["client_id"],
            client_secret=clinic["client_secret"],
            subdomain=clinic["amocrm_subdomain"],
            redirect_url=clinic["redirect_url"],
            mongo_uri=MONGO_URI,
            db_name=DB_NAME
        )

        # Проверяем путь API
        api_paths = ["api/v4/events", "api/v2/events", "events"]
        api_path = None
        for path in api_paths:
            try:
                params = {"page": 1, "limit": 1}
                response, status = await client.contacts.request("get", path, params=params)
                if status == 200:
                    api_path = path
                    break
            except:
                continue
        
        if not api_path:
            return APIResponse(success=False, message="API путь не найден", data=None)

        # Собираем ВСЕ события
        all_events = []
        page = 1
        
        while page <= request.max_pages:
            params = {"page": page, "limit": 250}
            if start_timestamp:
                params["filter[created_at][from]"] = start_timestamp
            if end_timestamp:
                params["filter[created_at][to]"] = end_timestamp
            
            logger.info(f"Страница {page}")
            response_data, status_code = await client.contacts.request("get", api_path, params=params)
            
            if status_code != 200:
                break
            
            if "_embedded" in response_data and "events" in response_data["_embedded"]:
                events = response_data["_embedded"]["events"]
                all_events.extend(events)
                logger.info(f"Страница {page}: получено {len(events)} событий")
                
                if "_links" not in response_data or "next" not in response_data["_links"]:
                    break
                page += 1
            else:
                break

        logger.info(f"Всего событий: {len(all_events)}")

        # ОБОГАЩЕНИЕ: Создаём мапу contact_id → lead_id
        logger.info("Создаём мапу contact→lead для обогащения...")
        
        # Получаем все сделки за период через get_all() с фильтром
        from mlab_amo_async.filters import DateRangeFilter
        
        all_leads = []
        if start_timestamp and end_timestamp:
            # Создаём datetime объекты из timestamp
            start_dt = datetime.fromtimestamp(start_timestamp)
            end_dt = datetime.fromtimestamp(end_timestamp)
            
            # Создаём фильтр по дате создания
            date_filter = DateRangeFilter("created_at")
            date_filter(start_dt, end_dt)
            
            # Получаем все сделки с фильтром
            logger.info(f"Получаем сделки за период {start_dt} - {end_dt}...")
            async for lead in client.leads.get_all(filters=[date_filter]):
                all_leads.append(lead)
                if len(all_leads) % 100 == 0:
                    logger.info(f"Получено сделок: {len(all_leads)}...")
                # Ограничение для безопасности
                if len(all_leads) >= 5000:
                    logger.warning("Достигнут лимит в 5000 сделок!")
                    break
        
        logger.info(f"Найдено сделок для маппинга: {len(all_leads)}")
        
        # Создаём мапу contact→lead через получение связей
        contact_to_lead_map = {}
        for lead in all_leads:
            try:
                # Получаем сделку со связанными контактами
                lead_with_contacts = await client.leads.get(lead['id'], include=["contacts"])
                
                if "_embedded" in lead_with_contacts and "contacts" in lead_with_contacts["_embedded"]:
                    contacts = lead_with_contacts["_embedded"]["contacts"]
                    for contact in contacts:
                        contact_id = contact["id"]
                        if contact_id not in contact_to_lead_map:
                            contact_to_lead_map[contact_id] = {"lead_id": lead['id'], "lead_name": lead['name']}
            except:
                continue
        
        logger.info(f"Создана мапа для {len(contact_to_lead_map)} контактов")
        
        # Обогащаем события
        enriched_events = []
        enriched_count = 0
        
        for event in all_events:
            contact_id = event.get("entity_id") if event.get("entity_type") == "contact" else None
            
            enriched_event = {
                **event,
                "lead_id": None,
                "lead_name": None,
                "has_lead": False  # Флаг для фронтенда
            }
            
            # Обогащаем если контакт есть в мапе
            if contact_id and contact_id in contact_to_lead_map:
                lead_info = contact_to_lead_map[contact_id]
                enriched_event["lead_id"] = lead_info["lead_id"]
                enriched_event["lead_name"] = lead_info["lead_name"]
                enriched_event["has_lead"] = True
                enriched_count += 1
            # Если entity_type = "lead" - берём напрямую
            elif event.get("entity_type") == "lead":
                enriched_event["lead_id"] = event.get("entity_id")
                enriched_event["has_lead"] = True
                enriched_count += 1
            
            enriched_events.append(enriched_event)
        
        # Статистика
        event_types = {}
        for e in enriched_events:
            t = e.get("type")
            event_types[t] = event_types.get(t, 0) + 1
        
        logger.info(f"ИТОГО: {len(enriched_events)} событий, обогащено: {enriched_count}")

        return APIResponse(
            success=True,
            message=f"Найдено {len(enriched_events)} событий, обогащено {enriched_count}",
            data={
                "total": len(enriched_events),
                "enriched": enriched_count,
                "not_enriched": len(enriched_events) - enriched_count,
                "event_types": event_types,
                "events": enriched_events  # События с lead_id и флагом has_lead!
            }
        )

    except Exception as e:
        logger.error(f"Ошибка: {e}", exc_info=True)
        return APIResponse(success=False, message=str(e), data=None)
    finally:
        if client:
            await client.close()