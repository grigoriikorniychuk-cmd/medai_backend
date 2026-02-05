import asyncio
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Query, Response, status
import logging
import traceback
import os
from bson.objectid import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

# Импортируем сервисы и утилиты из проекта
from ..services.mongodb_service import mongodb_service
from ..utils.logging import ContextLogger

# Импортируем данные для доступа к AmoCRM
from app.services.amo_credentials import get_full_amo_credentials, MONGODB_URI, MONGODB_NAME

# Настройка логгера
logger = ContextLogger("calls_parallel")

router = APIRouter(prefix="/api/calls-parallel", tags=["Звонки Параллельно"])

# Функции-хелперы из оригинального кода
def get_custom_field_value_by_name(lead, field_name):
    """
    Извлекает значение кастомного поля из сделки по его названию
    """
    if not lead.get("custom_fields_values"):
        logger.warning(f"В сделке нет кастомных полей")
        return None
    
    field_name_mapping = {
        "administrator": "Администратор",
        "source": "Источник трафика",
        "processing_speed": "скорость обработки"
    }
    
    # Преобразуем имя поля, если есть в маппинге
    search_name = field_name_mapping.get(field_name, field_name)
    logger.debug(f"Ищем поле: {field_name} по названию: {search_name}")
    
    # Приводим искомое имя к нижнему регистру для регистронезависимого сравнения
    search_name_lower = search_name.lower()
    
    for field in lead["custom_fields_values"]:
        field_name_value = field.get("field_name", "")
        # Сравниваем без учета регистра
        if field_name_value and field_name_value.lower() == search_name_lower:
            values = field.get("values", [])
            if values and len(values) > 0:
                value = values[0].get("value")
                logger.debug(f"Найдено значение для {field_name_value}: {value}")
                return value
    
    logger.warning(f"Поле {search_name} не найдено в кастомных полях сделки")
    return None

def convert_processing_speed_to_minutes(speed_str):
    """
    Преобразует строковое значение скорости обработки в числовое значение в минутах.
    """
    processing_speed_mapping = {
        "5-10 мин": 5,
        "10-15 мин": 10,
        "15-30 мин": 15,
        "30-1 час": 30,
        "1-3 часа": 60,
        "3-6 часов": 180,
        "6-12 часов": 360,
        "12-1 день": 720,
        "1-3 дня": 1440
    }
    
    if speed_str in processing_speed_mapping:
        return processing_speed_mapping[speed_str]
    
    logger.warning(f"Неизвестное значение скорости обработки: {speed_str}")
    return None

async def process_lead(amo, lead, credentials, calls_collection):
    """
    Обрабатывает отдельную сделку и сохраняет ее звонки в базу данных
    
    Args:
        amo: Клиент AmoCRM
        lead: Данные сделки
        credentials: Учетные данные AmoCRM
        calls_collection: Коллекция звонков в MongoDB
    
    Returns:
        Tuple[int, int]: Количество обработанных звонков, 1 если сделка содержит звонки или 0
    """
    try:
        lead_id = lead.get("id")
        logger.info(f"Обработка сделки id: {lead_id}")
        
        # Получаем детальную информацию о сделке
        lead_info = await amo.get_lead(lead_id)
        
        # Извлекаем нужные поля
        administrator = get_custom_field_value_by_name(lead_info, "administrator") or "Неизвестный"
        source = get_custom_field_value_by_name(lead_info, "source") or "Неопределенный"
        processing_speed_str = get_custom_field_value_by_name(lead_info, "processing_speed") or "0 мин"
        
        # Преобразуем строковое значение processing_speed в числовое (в минутах)
        processing_speed_minutes = convert_processing_speed_to_minutes(processing_speed_str) or 0
        
        # Получаем контакт, связанный со сделкой
        contact = await amo.get_contact_from_lead(lead_id)
        
        calls_saved = 0
        lead_has_calls = 0
        
        if contact:
            contact_id = contact.get("id")
            contact_name = contact.get("name", "Без имени")
            
            # Получаем звонки контакта
            call_links = await amo.get_call_links(contact_id)
            
            if call_links:
                logger.info(f"Найдено {len(call_links)} звонков для сделки #{lead_id}, контакт #{contact_id}")
                lead_has_calls = 1
                
                for call_info in call_links:
                    # ЗАЩИТА: Пропускаем API эндпоинты заметок AmoCRM
                    call_link = call_info.get("call_link", "")
                    if "/api/v4/contacts/" in call_link and "/notes/" in call_link:
                        logger.debug(f"Пропущен API эндпоинт заметки (не аудио): {call_link[:80]}")
                        continue
                    
                    note = call_info.get("note", {})
                    note_id = call_info.get("note_id")
                    params = note.get("params", {})
                    created_at = note.get("created_at")
                    
                    # Определяем тип звонка (входящий/исходящий)
                    note_type = note.get("note_type")
                    call_direction = "Неизвестно"
                    if isinstance(note_type, int):
                        call_direction = (
                            "Входящий" if note_type == 10 else
                            "Исходящий" if note_type == 11 else "Неизвестно"
                        )
                    elif isinstance(note_type, str):
                        call_direction = (
                            "Входящий" if "in" in note_type.lower() else
                            "Исходящий" if "out" in note_type.lower() else "Неизвестно"
                        )
                    
                    # Длительность звонка
                    duration = params.get("duration", 0)
                    duration_formatted = ""
                    if duration:
                        minutes = duration // 60
                        seconds = duration % 60
                        duration_formatted = f"{minutes}:{seconds:02d}"
                    
                    # Форматируем дату создания звонка
                    created_date = datetime.fromtimestamp(created_at) if created_at else datetime.now()
                    
                    # Создаем документ для сохранения в MongoDB
                    call_doc = {
                        "note_id": note_id,  # Уникальный ID заметки
                        "lead_id": lead_id,
                        "lead_name": lead_info.get("name", ""),
                        "client_id": credentials["client_id"],
                        "subdomain": credentials["subdomain"],
                        "contact_id": contact_id,
                        "contact_name": contact_name,
                        "administrator": administrator,
                        "source": source,
                        "processing_speed": processing_speed_minutes,
                        "processing_speed_str": processing_speed_str,
                        "call_direction": call_direction,
                        "duration": duration,
                        "duration_formatted": duration_formatted,
                        "phone": params.get("phone", "Неизвестно"),
                        "call_link": call_info.get("call_link", ""),
                        "created_at": created_at,
                        "created_date": created_date.strftime("%Y-%m-%d %H:%M:%S"),
                        "recorded_at": datetime.now(),
                        "amocrm_user_id": lead_info.get("responsible_user_id")
                    }
                    
                    # Проверяем, существует ли уже запись с таким note_id
                    existing_call = await calls_collection.find_one({"note_id": note_id})
                    
                    if existing_call:
                        # Обновляем существующую запись
                        await calls_collection.update_one(
                            {"note_id": note_id},
                            {"$set": call_doc}
                        )
                        logger.info(f"Обновлена запись звонка с note_id={note_id}")
                    else:
                        # Вставляем новую запись
                        await calls_collection.insert_one(call_doc)
                        logger.info(f"Сохранен новый звонок с note_id={note_id}")
                        calls_saved += 1
                
                logger.info(f"Для сделки #{lead_id} сохранено {calls_saved} звонков")
            else:
                logger.info(f"Для контакта {contact_id} не найдено звонков")
        else:
            logger.info(f"Для сделки {lead_id} не найден контакт")
        
        return calls_saved, lead_has_calls
    except Exception as e:
        logger.error(f"Ошибка при обработке сделки {lead.get('id')}: {str(e)}")
        logger.error(traceback.format_exc())
        return 0, 0

@router.post("/sync-by-date")
async def sync_calls_by_date_parallel(
    date: Optional[str] = None,
    client_id: Optional[str] = None,
    concurrency: int = Query(5, description="Количество параллельных задач")
) -> Dict[str, Any]:
    """
    Синхронизация звонков из AmoCRM с параллельной обработкой сделок
    
    Args:
        date: Дата в формате DD.MM.YYYY, YYYY-MM-DD или другом распознаваемом формате
        client_id: ID клиента AmoCRM (опционально)
        concurrency: Максимальное количество параллельных задач (default: 5)
        
    Returns:
        Результаты синхронизации
    """
    amo = None
    mongo_client = None
    
    try:
        logger.info("Получение данных авторизации...")
        
        credentials = await get_full_amo_credentials(client_id=client_id)
        logger.info(f"Получены данные для client_id: {credentials['client_id']}, subdomain: {credentials['subdomain']}")
        
        # Подключаемся к MongoDB
        mongo_client = AsyncIOMotorClient(MONGODB_URI)
        db = mongo_client[MONGODB_NAME]
        calls_collection = db.calls
        
        # Создаем экземпляр API amoCRM
        from mlab_amo_async.amocrm_client import AsyncAmoCRMClient
        amo = AsyncAmoCRMClient(
            client_id=credentials["client_id"],
            client_secret=credentials["client_secret"],
            subdomain=credentials["subdomain"],
            redirect_url=credentials["redirect_url"],
            mongo_uri=MONGODB_URI,
            db_name=MONGODB_NAME
        )
        logger.info("Клиент amoCRM успешно создан")
        
        # Определение временного диапазона для запроса
        now = None
        if date:
            try:
                # Пробуем несколько форматов
                for fmt in ["%d.%m.%Y", "%Y-%m-%d", "%Y.%m.%d", "%d-%m-%Y"]:
                    try:
                        now = datetime.strptime(date, fmt)
                        logger.info(f"Успешно распознан формат даты {fmt} для {date}")
                        break
                    except ValueError:
                        continue
                
                if not now:
                    now = datetime.now()
                    logger.warning(f"Не удалось распознать формат даты: {date}, используется текущая дата")
            except Exception as e:
                now = datetime.now()
                logger.warning(f"Ошибка при обработке даты: {e}, используется текущая дата")
        else:
            now = datetime.now()
        
        # Расчет временных меток
        today_start = int(datetime(now.year, now.month, now.day, 0, 0, 0, tzinfo=timezone.utc).timestamp())
        today_end = int(datetime(now.year, now.month, now.day, 23, 59, 59, tzinfo=timezone.utc).timestamp())
        
        logger.info(f"Получение сделок за день: {now.strftime('%d.%m.%Y')}")
        logger.info(f"Временной диапазон: {today_start} - {today_end}")
        logger.info(f"from: {datetime.fromtimestamp(today_start)}, to: {datetime.fromtimestamp(today_end)}")
        
        # Получаем сделки
        all_leads = []
        page = 1
        
        while True:
            # Параметры фильтрации для сделок за текущий день
            filter_params = {
                "filter[created_at][from]": today_start,
                "filter[created_at][to]": today_end,
                "page": page,
                "limit": 50
            }
            
            logger.info(f"Запрос сделок со следующими параметрами: {filter_params}")
            leads_response, leads_status = await amo.leads.request(
                "get", "leads", params=filter_params
            )
            
            if leads_status != 200:
                logger.error(f"Ошибка при получении сделок, статус: {leads_status}, response: {leads_response}")
                break
            
            # Извлекаем сделки из ответа
            if "_embedded" in leads_response and "leads" in leads_response["_embedded"]:
                leads = leads_response["_embedded"]["leads"]
                if not leads:
                    logger.info(f"Нет сделок на странице {page}")
                    break
                
                all_leads.extend(leads)
                logger.info(f"Получено {len(leads)} сделок на странице {page}")
                
                # Проверяем, есть ли следующая страница
                if "_links" in leads_response and "next" in leads_response["_links"]:
                    page += 1
                else:
                    break
            else:
                logger.warning(f"Неожиданный формат ответа: {leads_response}")
                break
        
        total_leads = len(all_leads)
        logger.info(f"Всего получено {total_leads} сделок за выбранную дату")
        
        # Если сделок нет, возвращаем пустой результат
        if not all_leads:
            return {
                "success": True,
                "message": "Сделки не найдены за указанную дату",
                "data": {
                    "date": now.strftime('%Y-%m-%d'),
                    "client_id": client_id,
                    "leads_processed": 0,
                    "calls_saved": 0,
                    "leads_with_calls": 0,
                    "execution_time": 0,
                    "parallel_tasks": concurrency
                }
            }
        
        # Засекаем время исполнения
        start_time = datetime.now()
        
        # Обрабатываем сделки параллельно
        semaphore = asyncio.Semaphore(concurrency)
        
        async def process_lead_with_semaphore(amo, lead, credentials, calls_collection):
            async with semaphore:
                return await process_lead(amo, lead, credentials, calls_collection)
        
        # Запускаем задачи обработки сделок параллельно с ограничением через semaphore
        tasks = [
            process_lead_with_semaphore(amo, lead, credentials, calls_collection)
            for lead in all_leads
        ]
        
        # Ожидаем выполнения всех задач
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Подсчитываем общие результаты
        total_calls_saved = 0
        leads_with_calls = 0
        errors = 0
        
        for result in results:
            if isinstance(result, Exception):
                errors += 1
                logger.error(f"Ошибка при обработке сделки: {result}")
                continue
            
            calls_saved, has_calls = result
            total_calls_saved += calls_saved
            leads_with_calls += has_calls
        
        # Рассчитываем затраченное время
        end_time = datetime.now()
        execution_time = (end_time - start_time).total_seconds()
        
        logger.info("\nСтатистика:")
        logger.info(f"Всего обработано сделок: {total_leads}")
        logger.info(f"Сделок с звонками: {leads_with_calls}")
        logger.info(f"Всего сохранено звонков: {total_calls_saved}")
        logger.info(f"Ошибок при обработке: {errors}")
        logger.info(f"Время исполнения: {execution_time:.2f} сек")
        
        # Закрываем соединения
        await amo.close()
        mongo_client.close()
        logger.info("\nСоединения закрыты")
        
        # Формируем ответ с полной статистикой
        return {
            "success": True,
            "message": f"Синхронизация звонков из AmoCRM выполнена: обработано {total_leads} сделок, сохранено {total_calls_saved} звонков",
            "data": {
                "date": now.strftime('%Y-%m-%d'),
                "client_id": client_id,
                "leads_processed": total_leads,
                "calls_saved": total_calls_saved,
                "leads_with_calls": leads_with_calls,
                "errors": errors,
                "execution_time": round(execution_time, 2),
                "parallel_tasks": concurrency
            }
        }
    except Exception as e:
        logger.error(f"Ошибка при синхронизации звонков: {str(e)}")
        logger.error(traceback.format_exc())
        return {
            "success": False,
            "message": f"Ошибка при синхронизации звонков: {str(e)}",
            "data": None
        }
    finally:
        # Закрываем соединения, если они были созданы
        if amo:
            try:
                await amo.close()
            except Exception as e:
                logger.error(f"Ошибка при закрытии соединения с AmoCRM: {str(e)}")
        
        if mongo_client:
            try:
                mongo_client.close()
            except Exception as e:
                logger.error(f"Ошибка при закрытии соединения с MongoDB: {str(e)}") 