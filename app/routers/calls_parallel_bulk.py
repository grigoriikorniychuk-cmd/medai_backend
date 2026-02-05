import asyncio
from typing import Dict, Any, List, Optional, Tuple
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query, BackgroundTasks, Request, status
from fastapi.responses import JSONResponse
from mlab_amo_async.filters import DateRangeFilter
import logging
import traceback
import os
from bson.objectid import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.operations import UpdateOne, InsertOne

# Импортируем сервисы и утилиты из проекта
from ..services.mongodb_service import mongodb_service
from ..utils.logging import ContextLogger
from .calls import convert_date_string # Импортируем функцию для парсинга даты

# Импортируем данные для доступа к AmoCRM
from app.services.amo_credentials import get_full_amo_credentials, MONGODB_URI, MONGODB_NAME

# Настройка логгера
logger = ContextLogger("calls_parallel_bulk")

router = APIRouter(prefix="/api/calls-parallel-bulk", tags=["Звонки Параллельно Bulk"])

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
        "processing_speed": [
            "скорость обработки",
            "Скорость обработки", 
            "Скорость обработки заявки",
            "скорость обработки заявки"
        ]
    }
    
    # Преобразуем имя поля, если есть в маппинге
    search_names = field_name_mapping.get(field_name, field_name)
    
    # Преобразуем search_names в список, если это не список
    if not isinstance(search_names, list):
        search_names = [search_names]
    
    logger.debug(f"Ищем поле: {field_name} по возможным названиям: {search_names}")
    
    # Приводим все искомые имена к нижнему регистру для регистронезависимого сравнения
    search_names_lower = [name.lower() for name in search_names]
    
    for field in lead["custom_fields_values"]:
        field_name_value = field.get("field_name", "")
        field_name_lower = field_name_value.lower() if field_name_value else ""
        
        # Проверяем на совпадение с любым из возможных названий
        if field_name_lower and field_name_lower in search_names_lower:
            values = field.get("values", [])
            if values and len(values) > 0:
                value = values[0].get("value")
                logger.debug(f"Найдено значение для {field_name_value}: {value}")
                return value
    
    logger.warning(f"Поле {search_names } не найдено в кастомных полях сделки")
    return None

def convert_processing_speed_to_minutes(speed_str):
    """
    Преобразует строковое значение скорости обработки в числовое значение в минутах.
    Поддерживает строки как с пробелами вокруг дефиса, так и без них.
    """
    if not speed_str:
        return 0
    
    # Нормализация строки - удаляем пробелы вокруг дефиса
    normalized_str = speed_str.replace(" - ", "-").replace(" -", "-").replace("- ", "-")
    
    # Базовое маппинг для известных значений
    processing_speed_mapping = {
        "0 мин": 0,
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
    
    # Проверяем на наличие в маппинге
    if normalized_str in processing_speed_mapping:
        return processing_speed_mapping[normalized_str]
    
    # Проверяем простые числовые значения с "мин"
    try:
        # Пробуем извлечь число из строки с "мин"
        if "мин" in normalized_str:
            # Удаляем "мин" и пробелы, пытаемся получить число
            num_part = normalized_str.replace("мин", "").strip()
            
            # Если есть диапазон, берем нижнюю границу
            if "-" in num_part:
                num_part = num_part.split("-")[0].strip()
            
            # Преобразуем в число
            return int(num_part)
    except (ValueError, TypeError) as e:
        logger.warning(f"Ошибка при парсинге числа из '{speed_str}': {e}")
    
    logger.warning(f"Неизвестное значение скорости обработки: {speed_str}")
    return 0  # По умолчанию возвращаем 0, а не None

async def process_lead(amo, lead, credentials, calls_collection, user_date=None, timeout=60):
    """
    Обрабатывает отдельную сделку и сохраняет ее звонки в базу данных,
    используя bulk операции для оптимизации
    
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
        logger.info(f"[LEAD-{lead_id}] Начало обработки.")
        
        # Получаем детальную информацию о сделке
        logger.debug(f"[LEAD-{lead_id}] Запрос детальной информации о сделке...")
        lead_info = await asyncio.wait_for(amo.get_lead(lead_id), timeout=timeout)
        logger.debug(f"[LEAD-{lead_id}] Детальная информация о сделке получена.")
        
        # Извлекаем нужные поля
        administrator = get_custom_field_value_by_name(lead_info, "administrator") or "Неизвестный"
        source = get_custom_field_value_by_name(lead_info, "source") or "Неопределенный"
        processing_speed_str = get_custom_field_value_by_name(lead_info, "processing_speed") or "0 мин"
        
        # Преобразуем строковое значение processing_speed в числовое (в минутах)
        processing_speed_minutes = convert_processing_speed_to_minutes(processing_speed_str) or 0
        
        # Получаем контакт, связанный со сделкой
        logger.debug(f"[LEAD-{lead_id}] Запрос контакта...")
        contact = await asyncio.wait_for(amo.get_contact_from_lead(lead_id), timeout=timeout)
        logger.debug(f"[LEAD-{lead_id}] Контакт получен.")
        
        calls_saved = 0
        lead_has_calls = 0
        
        # Создаем список операций для MongoDB
        bulk_operations = []
        note_ids_to_check = []
        call_docs = []
        
        if contact:
            contact_id = contact.get("id")
            contact_name = contact.get("name", "Без имени")
            
            # Получаем звонки контакта
            logger.debug(f"[LEAD-{lead_id}] Запрос ссылок на звонки для контакта {contact_id}...")
            call_links = await asyncio.wait_for(amo.get_call_links(contact_id), timeout=timeout)
            logger.debug(f"[LEAD-{lead_id}] Ссылки на звонки получены.")
            
            if call_links:
                logger.info(f"Найдено {len(call_links)} звонков для сделки #{lead_id}, контакт #{contact_id}")
                lead_has_calls = 1
                
                # Подготавливаем документы и собираем note_ids для проверки
                for call_info in call_links:
                    # ЗАЩИТА: Пропускаем API эндпоинты заметок AmoCRM
                    call_link = call_info.get("call_link", "")
                    if "/api/v4/contacts/" in call_link and "/notes/" in call_link:
                        logger.debug(f"[LEAD-{lead_id}] Пропущен API эндпоинт заметки (не аудио): {call_link[:80]}")
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

                    # Пропускаем звонки с нулевой длительностью
                    if not duration or duration == 0:
                        logger.debug(f"[LEAD-{lead_id}] Пропущен звонок с note_id={note_id} из-за нулевой длительности.")
                        continue

                    # Пропускаем звонки со ссылкой на uiscom
                    link = params.get("link")
                    if link and link.startswith("https://media.uiscom.ru/"):
                        logger.debug(f"[LEAD-{lead_id}] Пропущен звонок с note_id={note_id} из-за ссылки на uiscom: {link}")
                        continue

                    duration_formatted = ""
                    if duration:
                        minutes = duration // 60
                        seconds = duration % 60
                        duration_formatted = f"{minutes}:{seconds:02d}"
                    
                    # Форматируем дату создания звонка с учетом часового пояса UTC
                    created_date = datetime.fromtimestamp(created_at, tz=timezone.utc) if created_at else datetime.now(timezone.utc)
                    
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
                        "created_date_iso": created_date.isoformat(),
                        "created_date_for_filtering": user_date or datetime.now().strftime('%Y-%m-%d'),
                        "recorded_at": datetime.now(),
                        "amocrm_user_id": lead_info.get("responsible_user_id")
                    }
                    
                    note_ids_to_check.append(note_id)
                    call_docs.append(call_doc)
                
                # Проверяем существующие записи одной операцией
                if note_ids_to_check:
                    # Получаем все существующие заметки одним запросом
                    existing_notes = await calls_collection.find(
                        {"note_id": {"$in": note_ids_to_check}},
                        {"note_id": 1}
                    ).to_list(length=len(note_ids_to_check))
                    
                    # Создаем множество для быстрой проверки
                    existing_note_ids = {note.get("note_id") for note in existing_notes}
                    
                    # Формируем операции для MongoDB
                    for call_doc in call_docs:
                        note_id = call_doc["note_id"]
                        
                        if note_id in existing_note_ids:
                            # Обновляем существующую запись
                            bulk_operations.append(
                                UpdateOne({"note_id": note_id}, {"$set": call_doc})
                            )
                            logger.debug(f"Добавлена операция обновления для звонка с note_id={note_id}")
                        else:
                            # Вставляем новую запись
                            bulk_operations.append(
                                InsertOne(call_doc)
                            )
                            calls_saved += 1
                            logger.debug(f"Добавлена операция вставки для нового звонка с note_id={note_id}")
                
                # Выполняем все операции одним запросом
                if bulk_operations:
                    logger.debug(f"[LEAD-{lead_id}] Выполнение bulk_write с {len(bulk_operations)} операциями...")
                    result = await asyncio.wait_for(calls_collection.bulk_write(bulk_operations), timeout=timeout)
                    logger.debug(f"[LEAD-{lead_id}] bulk_write выполнен.")
                    logger.info(f"Выполнено bulk_write с {len(bulk_operations)} операциями")
                    logger.info(f"Результат: inserted={result.inserted_count}, modified={result.modified_count}")
                
                logger.info(f"[LEAD-{lead_id}] Сохранено {calls_saved} новых звонков. Обработка завершена.")
            else:
                logger.info(f"Для контакта {contact_id} не найдено звонков")
        else:
            logger.info(f"Для сделки {lead_id} не найден контакт")
        
        return calls_saved, lead_has_calls
    except asyncio.TimeoutError:
        logger.error(f"[LEAD-{lead.get('id')}] Таймаут при обработке сделки (превышен лимит {timeout} сек).")
        logger.error(traceback.format_exc())
        return 0, 0
    except Exception as e:
        logger.error(f"[LEAD-{lead.get('id')}] Непредвиденная ошибка при обработке: {str(e)}")
        logger.error(traceback.format_exc())
        return 0, 0

@router.post("/sync-by-date")
async def sync_calls_by_date_parallel_bulk(
    date: Optional[str] = None,
    client_id: Optional[str] = None,
    concurrency: int = Query(5, description="Количество параллельных задач")
) -> Dict[str, Any]:
    """
    Синхронизация звонков из AmoCRM с параллельной обработкой сделок
    и использованием bulk операций для MongoDB
    
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

        start_time = datetime.now()

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
                    logger.warning(f"Не удалось распознать формат даты: {date}, используется текущая дата")
                    # Выбрасываем ошибку, если дата передана, но не распознана
                    raise HTTPException(status_code=400, detail=f"Не удалось распознать формат даты: {date}. Используйте DD.MM.YYYY или YYYY-MM-DD.")

            except Exception as e:
                logger.warning(f"Ошибка при обработке даты: {e}, используется текущая дата")
                now = datetime.now()
        else:
            now = datetime.now()

        formatted_date_for_filter = now.strftime('%Y-%m-%d')
        logger.info(f"Дата для фильтрации (created_date_for_filtering): {formatted_date_for_filter}")

        # Проверка, была ли уже синхронизация за этот день для данного клиента
        existing_sync_record = await calls_collection.find_one({
            "client_id": credentials["client_id"],
            "created_date_for_filtering": formatted_date_for_filter
        })

        if existing_sync_record:
            logger.info(f"Синхронизация для клиента {credentials['client_id']} по дате {formatted_date_for_filter} уже проводилась. Пропуск основной логики.")
            # total_execution_time_seconds считается от start_time, который теперь определен ранее
            total_execution_time = (datetime.now() - start_time).total_seconds()
            return {
                "message": f"Синхронизация для даты {formatted_date_for_filter} уже была выполнена ранее. Новые данные не запрашивались.",
                "total_calls_saved": 0,
                "total_leads_with_calls": 0,
                "total_leads_processed": 0,
                "total_execution_time_seconds": round(total_execution_time, 2)
            }

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
        
        # Сохраняем все сделки в JSON файл для анализа
        try:
            # Подготавливаем список сделок с дополнительной информацией
            leads_for_json = []
            for lead in all_leads:
                lead_info = {
                    "id": lead.get("id"),
                    "name": lead.get("name"),
                    "created_at": lead.get("created_at"),
                    "created_at_formatted": datetime.fromtimestamp(lead.get("created_at")).strftime("%Y-%m-%d %H:%M:%S") if lead.get("created_at") else None,
                    "responsible_user_id": lead.get("responsible_user_id"),
                    "status_id": lead.get("status_id"),
                    "pipeline_id": lead.get("pipeline_id"),
                    "source_date": date,
                    "synced_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                leads_for_json.append(lead_info)
            
            # Создаем имя файла с текущей датой и временем
            json_filename = f"leads_{now.strftime('%Y%m%d')}_{datetime.now().strftime('%H%M%S')}.json"
            base_dir = Path(__file__).resolve().parent.parent.parent  # Путь к корневой директории проекта
            json_path = base_dir / json_filename
            
            # Записываем данные в JSON
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(leads_for_json, f, ensure_ascii=False, indent=2)
            
            logger.info(f"Сохранено {len(leads_for_json)} сделок в файл {json_path}")
        except Exception as e:
            logger.error(f"Ошибка при сохранении сделок в JSON: {str(e)}")
            logger.error(traceback.format_exc())
        
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
        
        # Адаптивно выбираем уровень параллелизма в зависимости от количества сделок
        adaptive_concurrency = min(concurrency, max(1, min(total_leads // 5, 10)))
        logger.info(f"Адаптивно выбран уровень параллелизма: {adaptive_concurrency}")
        
        # Засекаем время исполнения
        start_time = datetime.now()
        
        # Обрабатываем сделки параллельно
        semaphore = asyncio.Semaphore(adaptive_concurrency)
        
        async def process_lead_with_semaphore(amo, lead, credentials, calls_collection):
            async with semaphore:
                # Устанавливаем таймаут для каждой задачи в 90 секунд
                return await process_lead(amo, lead, credentials, calls_collection, user_date=now.strftime('%Y-%m-%d'), timeout=90)
        
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
        
        # Анализируем результаты
        for i, result in enumerate(results):
            lead_id_for_log = all_leads[i].get('id', 'UNKNOWN')
            if isinstance(result, Exception):
                errors += 1
                # Логируем ошибку с указанием ID сделки
                logger.error(f"[LEAD-{lead_id_for_log}] Задача завершилась с ошибкой: {result}")
                # Дополнительно можно логировать traceback, если нужно
                # logger.error(traceback.format_exc())
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
                "parallel_tasks": adaptive_concurrency
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


@router.post("/sync-by-date-range")
async def sync_calls_by_date_range_parallel_bulk(
    start_date_str: str = Query(..., description="Начальная дата диапазона (DD.MM.YYYY или YYYY-MM-DD)"),
    end_date_str: str = Query(..., description="Конечная дата диапазона (DD.MM.YYYY или YYYY-MM-DD)"),
    client_id: Optional[str] = Query(None, description="ID клиента AmoCRM"),
    concurrency: int = Query(5, description="Количество параллельных задач")
) -> Dict[str, Any]:
    """
    Синхронизация звонков из AmoCRM за диапазон дат с параллельной обработкой сделок
    и использованием bulk операций для MongoDB.
    """
    overall_start_time_global = datetime.now() # Общее время начала всего процесса
    daily_results = []
    overall_total_calls_saved = 0
    overall_total_leads_with_calls = 0
    overall_total_leads_processed = 0
    overall_total_errors_daily = 0 # Ошибки на уровне обработки дня, не критичные для всего процесса

    try:
        start_date_obj = convert_date_string(start_date_str)
        end_date_obj = convert_date_string(end_date_str)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not start_date_obj or not end_date_obj:
        logger.error(f"Некорректный формат начальной ({start_date_str}) или конечной ({end_date_str}) даты.")
        raise HTTPException(status_code=400, detail="Некорректный формат даты. Используйте DD.MM.YYYY или YYYY-MM-DD.")

    if start_date_obj > end_date_obj:
        logger.error(f"Начальная дата диапазона ({start_date_obj.strftime('%Y-%m-%d')}) не может быть позже конечной даты ({end_date_obj.strftime('%Y-%m-%d')}).")
        raise HTTPException(status_code=400, detail="Начальная дата диапазона не может быть позже конечной даты.")

    logger.info(f"Запрос на синхронизацию для клиента {client_id} за диапазон дат: с {start_date_obj.strftime('%Y-%m-%d')} по {end_date_obj.strftime('%Y-%m-%d')}")

    amo_global = None
    mongo_client_global = None # Для глобального подключения

    try:
        logger.info("Получение данных авторизации для диапазонной синхронизации...")
        credentials = await get_full_amo_credentials(client_id=client_id)
        effective_client_id = credentials['client_id'] 
        logger.info(f"Получены данные для client_id: {effective_client_id}, subdomain: {credentials['subdomain']} (диапазон)")

        logger.info("Подключение к MongoDB (глобальное для диапазона)...")
        mongo_client_global = AsyncIOMotorClient(MONGODB_URI)
        db_global = mongo_client_global[MONGODB_NAME]
        calls_collection_global = db_global.calls # Используем глобальную коллекцию
        logger.info("Успешное подключение к MongoDB (глобальное для диапазона)")

        logger.info("Создание экземпляра API amoCRM (глобальное для диапазона)...")
        from mlab_amo_async.amocrm_client import AsyncAmoCRMClient # Локальный импорт для ясности
        amo_global = AsyncAmoCRMClient(
            client_id=credentials["client_id"],
            client_secret=credentials["client_secret"],
            subdomain=credentials["subdomain"],
            redirect_url=credentials["redirect_url"],
            mongo_uri=MONGODB_URI, 
            db_name=MONGODB_NAME   
        )
        logger.info("Клиент amoCRM (глобальный для диапазона) успешно создан")

        current_date_iter = start_date_obj
        while current_date_iter <= end_date_obj:
            date_str_for_loop = current_date_iter.strftime('%Y-%m-%d')
            logger.info(f"Начало обработки даты: {date_str_for_loop} в рамках диапазона.")
            day_start_time = datetime.now()
            
            day_calls_saved = 0
            day_leads_processed = 0
            day_leads_with_calls = 0
            day_errors = 0
            day_status = "pending"

            try:
                # Проверка, была ли уже синхронизация за этот день для данного клиента
                existing_sync_record = await calls_collection_global.find_one({
                    "client_id": effective_client_id,
                    "created_date_for_filtering": date_str_for_loop
                })

                if existing_sync_record:
                    logger.info(f"Синхронизация для клиента {effective_client_id} по дате {date_str_for_loop} уже проводилась. Пропуск.")
                    day_status = "skipped"
                    # Остальные счетчики дня остаются 0
                else:
                    logger.info(f"Начало синхронизации для {date_str_for_loop}...")
                    # Определение временного диапазона для запроса (для текущего дня в цикле)
                    day_start_dt = datetime(current_date_iter.year, current_date_iter.month, current_date_iter.day, 0, 0, 0, tzinfo=timezone.utc)
                    day_end_dt = datetime(current_date_iter.year, current_date_iter.month, current_date_iter.day, 23, 59, 59, tzinfo=timezone.utc)
                    day_start_timestamp = int(day_start_dt.timestamp())
                    day_end_timestamp = int(day_end_dt.timestamp())

                    logger.info(f"Получение сделок из AmoCRM для даты {date_str_for_loop} (от {day_start_dt.strftime('%Y-%m-%d %H:%M:%S')} до {day_end_dt.strftime('%Y-%m-%d %H:%M:%S')})...")
                    
                    created_at_filter = DateRangeFilter("created_at")
                    created_at_filter(day_start_dt, day_end_dt) # DateRangeFilter ожидает datetime объекты

                    all_leads_for_day = []
                    # Метод get_all является асинхронным генератором
                    # Параметр include=["contacts"] добавлен для получения связанных контактов, что часто требуется.
                    # Если контакты не нужны на этом этапе, его можно убрать для оптимизации.
                    async for lead_page_item in amo_global.leads.get_all(filters=[created_at_filter], include=["contacts"]):
                        all_leads_for_day.append(lead_page_item)
                    
                    total_leads_for_day = len(all_leads_for_day)
                    logger.info(f"Для даты {date_str_for_loop} (диапазон {day_start_dt.strftime('%Y-%m-%d %H:%M:%S')} - {day_end_dt.strftime('%Y-%m-%d %H:%M:%S')}) получено {total_leads_for_day} сделок.")

                    # Этот блок теперь корректно вложен в 'else' для 'if existing_sync_record:'
                    if total_leads_for_day == 0:
                        logger.info(f"Для даты {date_str_for_loop} нет сделок для обработки.")
                        day_status = "completed_no_leads"
                        # Счетчики дня остаются 0
                        pass # Добавлено для линтера
                    else:
                        # Адаптивный уровень параллелизма для текущего дня
                        adaptive_concurrency_for_day = min(concurrency, max(1, total_leads_for_day // 10 if total_leads_for_day > 10 else 1))
                        if total_leads_for_day <= 5: # Для очень малого количества задач нет смысла в большом параллелизме
                            adaptive_concurrency_for_day = min(concurrency, total_leads_for_day) 
                            logger.info(f"Для даты {date_str_for_loop} адаптивно выбран уровень параллелизма: {adaptive_concurrency_for_day} (запрошено {concurrency})")
                        
                        day_semaphore = asyncio.Semaphore(adaptive_concurrency_for_day)
                        
                        # Вложенная функция для обработки одной сделки с семафором для текущего дня
                        async def _process_lead_with_semaphore_for_day_range(amo_client, lead_item, creds, calls_coll, user_date_str):
                            async with day_semaphore:
                                # process_lead уже обрабатывает исключения внутри и возвращает Tuple или вызывает ошибку, которую поймает gather
                                return await process_lead(amo_client, lead_item, creds, calls_coll, user_date=user_date_str)

                        tasks_for_day = [
                            _process_lead_with_semaphore_for_day_range(
                                amo_global, # Используем глобальный клиент Amo
                                lead_summary_item, 
                                credentials, # Используем глобальные credentials
                                calls_collection_global, # Используем глобальную коллекцию
                                date_str_for_loop # Дата текущей итерации цикла
                            )
                            for lead_summary_item in all_leads_for_day
                        ]
                        
                        logger.info(f"Для даты {date_str_for_loop} запускается {len(tasks_for_day)} задач параллельной обработки сделок...")
                        results_for_day = await asyncio.gather(*tasks_for_day, return_exceptions=True)
                        
                        # Подсчитываем результаты для текущего дня
                        processed_task_count_for_day = 0
                        for result_item in results_for_day:
                            if isinstance(result_item, Exception):
                                day_errors += 1
                                logger.error(f"Ошибка при обработке сделки для даты {date_str_for_loop}: {result_item}")
                                # Можно добавить traceback.format_exc() если нужно больше деталей в логе
                            else:
                                calls_s, has_c = result_item
                                day_calls_saved += calls_s
                                day_leads_with_calls += has_c
                                processed_task_count_for_day +=1 # Считаем успешно завершенные задачи
                        
                        day_leads_processed = processed_task_count_for_day # Количество успешно обработанных сделок
                        
                        if day_errors > 0:
                            day_status = "completed_with_errors"
                        else:
                            day_status = "completed"
                        
                        logger.info(f"Статистика для даты {date_str_for_loop}:")
                        logger.info(f"  Обработано сделок (успешно запущено задач): {total_leads_for_day}")
                        logger.info(f"  Из них успешно завершено обработку: {day_leads_processed}")
                        logger.info(f"  Сделок с звонками: {day_leads_with_calls}")
                        logger.info(f"  Всего сохранено звонков: {day_calls_saved}")
                        logger.info(f"  Ошибок при обработке отдельных сделок: {day_errors}")

            except Exception as e_day:
                logger.error(f"Ошибка при обработке даты {date_str_for_loop}: {str(e_day)}")
                logger.error(traceback.format_exc())
                day_errors +=1 # Считаем как одну ошибку на уровне дня
                day_status = "failed_day_processing"
            
            day_execution_time = (datetime.now() - day_start_time).total_seconds()
            
            daily_results.append({
                "date": date_str_for_loop,
                "status": day_status, 
                "leads_processed": day_leads_processed,
                "calls_saved": day_calls_saved,
                "leads_with_calls": day_leads_with_calls,
                "errors": day_errors,
                "execution_time_seconds": round(day_execution_time, 2)
            })
            
            overall_total_calls_saved += day_calls_saved
            overall_total_leads_processed += day_leads_processed
            overall_total_leads_with_calls += day_leads_with_calls
            overall_total_errors_daily += day_errors

            current_date_iter += timedelta(days=1)
        
        overall_execution_time_global = (datetime.now() - overall_start_time_global).total_seconds()
        logger.info(f"Завершена обработка всех дат в диапазоне. Общее время: {overall_execution_time_global:.2f} сек.")

        # Закрываем соединения здесь, так как основной цикл завершен успешно (или пустой диапазон)
        if amo_global:
            await amo_global.close()
            logger.info("Глобальное соединение с AmoCRM успешно закрыто после цикла.")
            amo_global = None 
        if mongo_client_global:
            mongo_client_global.close()
            logger.info("Глобальное соединение с MongoDB успешно закрыто после цикла.")
            mongo_client_global = None 

        return {
            "success": True,
            "message": "Синхронизация за диапазон дат завершена.",
            "client_id": effective_client_id,
            "date_range": {
                "start_date": start_date_obj.strftime('%Y-%m-%d'),
                "end_date": end_date_obj.strftime('%Y-%m-%d')
            },
            "overall_summary": {
                "total_days_processed_or_skipped": len(daily_results),
                "total_calls_saved": overall_total_calls_saved,
                "total_leads_processed": overall_total_leads_processed,
                "total_leads_with_calls": overall_total_leads_with_calls,
                "total_errors_in_days": overall_total_errors_daily,
                "total_execution_time_seconds": round(overall_execution_time_global, 2)
            },
            "daily_breakdown": daily_results
        }

    except HTTPException as http_exc: 
        logger.warning(f"Перехвачено HTTPException: {http_exc.detail}")
        raise http_exc
    except Exception as e:
        error_message = f"Критическая ошибка во время синхронизации за диапазон дат: {str(e)}"
        logger.error(error_message)
        logger.error(traceback.format_exc())
        # Не нужно здесь закрывать соединения, это сделает finally
        raise HTTPException(status_code=500, detail=error_message)
    finally:
        if amo_global:
            try:
                logger.info("Закрытие глобального соединения AmoCRM в блоке finally...")
                await amo_global.close()
                logger.info("Глобальное соединение с AmoCRM закрыто в блоке finally.")
            except Exception as e_close:
                logger.error(f"Ошибка при закрытии глобального соединения с AmoCRM в finally: {str(e_close)}")
        if mongo_client_global:
            try:
                logger.info("Закрытие глобального соединения MongoDB в блоке finally...")
                mongo_client_global.close()
                logger.info("Глобальное соединение с MongoDB закрыто в блоке finally.")
            except Exception as e_close:
                logger.error(f"Ошибка при закрытии глобального соединения с MongoDB в finally: {str(e_close)}")


async def run_sync_job(
    start_date_str: str,
    end_date_str: str,
    client_id: Optional[str],
    concurrency: int
):
    """
    Эта функция выполняет реальную работу по синхронизации в фоновом режиме.
    """
    logger.info(f"[BG Task] Запущена синхронизация за диапазон дат: {start_date_str} - {end_date_str} с concurrency={concurrency}")
    overall_start_time_global = datetime.now()
    amo_global = None
    mongo_client_global = None

    try:
        start_date_obj = convert_date_string(start_date_str)
        end_date_obj = convert_date_string(end_date_str)

        creds = await get_full_amo_credentials(client_id)
        if not creds:
            logger.error(f"[BG Task] Учетные данные для клиента {client_id} не найдены.")
            return
        effective_client_id = creds.get("client_id")

        amo_global = Amo(credentials=creds, storage_type='mongodb')
        await amo_global.init()
        logger.info(f"[BG Task] Глобальное соединение с AmoCRM для клиента {effective_client_id} установлено.")

        mongo_client_global = AsyncIOMotorClient(MONGODB_URI)
        db = mongo_client_global[MONGODB_NAME]
        calls_collection = db.calls
        logger.info("[BG Task] Глобальное соединение с MongoDB установлено.")

        async def _process_lead_with_semaphore_for_day_range(amo_client, lead_item, creds, calls_coll, user_date_str):
            semaphore = asyncio.Semaphore(concurrency)
            async with semaphore:
                return await process_lead(amo_client, lead_item, creds, calls_coll, user_date=user_date_str)

        current_date_iter = start_date_obj
        while current_date_iter <= end_date_obj:
            day_start_time = datetime.now()
            current_date_str = current_date_iter.strftime('%d.%m.%Y')
            logger.info(f"[BG Task] Начинаем обработку даты: {current_date_str}")

            try:
                date_filter = DateRangeFilter(from_date=current_date_iter, to_date=current_date_iter)
                leads_for_day = await amo_global.get_leads(filters=date_filter, includes=["contacts"])
                logger.info(f"[BG Task] Найдено {len(leads_for_day)} сделок для {current_date_str}")

                if leads_for_day:
                    tasks = [
                        _process_lead_with_semaphore_for_day_range(amo_global, lead, creds, calls_collection, current_date_str)
                        for lead in leads_for_day
                    ]
                    await asyncio.gather(*tasks, return_exceptions=True)

            except Exception as e:
                logger.error(f"[BG Task] Ошибка при получении или обработке сделок за {current_date_str}: {e}")
                logger.error(traceback.format_exc())

            day_execution_time = (datetime.now() - day_start_time).total_seconds()
            logger.info(f"[BG Task] Обработка даты {current_date_str} завершена за {day_execution_time:.2f} сек.")
            current_date_iter += timedelta(days=1)
        
        overall_execution_time_global = (datetime.now() - overall_start_time_global).total_seconds()
        logger.info(f"[BG Task] Завершена обработка всех дат в диапазоне. Общее время: {overall_execution_time_global:.2f} сек.")

    except Exception as e:
        error_message = f"[BG Task] Критическая ошибка во время фоновой синхронизации: {str(e)}"
        logger.error(error_message)
        logger.error(traceback.format_exc())
    finally:
        if amo_global:
            try:
                await amo_global.close()
                logger.info("[BG Task] Глобальное соединение с AmoCRM закрыто.")
            except Exception as e_close:
                logger.error(f"[BG Task] Ошибка при закрытии соединения AmoCRM: {str(e_close)}")
        if mongo_client_global:
            try:
                mongo_client_global.close()
                logger.info("[BG Task] Глобальное соединение с MongoDB закрыто.")
            except Exception as e_close:
                logger.error(f"[BG Task] Ошибка при закрытии соединения MongoDB: {str(e_close)}")


@router.post("/sync-by-date-range", summary="Синхронизация звонков за диапазон дат (Bulk)", status_code=status.HTTP_202_ACCEPTED)
async def sync_calls_by_date_range_parallel_bulk(
    background_tasks: BackgroundTasks,
    start_date_str: str = Query(..., description="Начальная дата в формате DD.MM.YYYY или YYYY-MM-DD"),
    end_date_str: str = Query(..., description="Конечная дата в формате DD.MM.YYYY или YYYY-MM-DD"),
    client_id: Optional[str] = Query(None, description="ID клиента AmoCRM"),
    concurrency: int = Query(5, description="Количество параллельных задач")
):
    """
    Запускает фоновую задачу для синхронизации звонков из AmoCRM за диапазон дат.
    """
    try:
        start_date_obj = convert_date_string(start_date_str)
        end_date_obj = convert_date_string(end_date_str)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    if start_date_obj > end_date_obj:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Начальная дата не может быть позже конечной даты.")

    background_tasks.add_task(
        run_sync_job,
        start_date_str=start_date_str,
        end_date_str=end_date_str,
        client_id=client_id,
        concurrency=concurrency
    )

    return JSONResponse(
        content={
            "status": "accepted",
            "message": "Процесс синхронизации запущен в фоновом режиме.",
            "details": {
                "client_id": client_id,
                "start_date": start_date_str,
                "end_date": end_date_str,
                "concurrency": concurrency
            }
        },
        status_code=status.HTTP_202_ACCEPTED
    )