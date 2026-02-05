import os
import json
import logging
import asyncio
import traceback
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Query, HTTPException, BackgroundTasks

from ..models.amocrm import CallsExportRequest, APIResponse
from mlab_amo_async.amocrm_client import AsyncAmoCRMClient
from ..services.clinic_service import ClinicService
from ..settings.paths import MONGO_URI, DB_NAME
from .calls import convert_date_string
from collections import defaultdict
from motor.motor_asyncio import AsyncIOMotorClient


# Функции-хелперы для работы с кастомными полями
def get_custom_field_value_by_name(lead, field_name):
    """
    Извлекает значение кастомного поля из сделки по его названию
    """
    if not lead.get("custom_fields_values"):
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
                return value
    
    return None


def convert_processing_speed_to_minutes(speed_str):
    """
    Преобразует строковое значение скорости обработки в числовое значение в минутах.
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
    
    return 0


# === ФУНКЦИИ АВТОДЕТЕКЦИИ И ПРОВЕРКИ КОНВЕРСИЙ ===

async def detect_conversion_config(client, clinic_service, client_id):
    """
    Автоматически определяет конфигурацию конверсий для клиники.
    Сохраняет в БД ТОЛЬКО если конфигурации нет.
    Уже существующая конфигурация НЕ перезаписывается (чтобы сохранить ручные правки).
    """
    logger.info(f"Получение конфигурации конверсий для {client_id}")
    
    # Получаем клинику из БД
    clinic = await clinic_service.find_clinic_by_client_id(client_id)
    if not clinic:
        logger.error(f"Клиника {client_id} не найдена")
        return None
    
    config = clinic.get("conversion_config")
    
    # Автодетекция запускается ТОЛЬКО если конфигурации нет вообще
    # Существующая конфигурация никогда не перезаписывается автоматически
    should_detect = False
    if not config:
        should_detect = True
        logger.info("Конфигурация отсутствует, запускаем автодетекцию")
    else:
        logger.info(f"Конфигурация уже существует, используем её без изменений")
    
    if should_detect:
        # Детектим конфигурацию
        config = {
            "primary": {"pipeline_id": None, "pipeline_name": None, "status_id": None, "status_name": None},
            "secondary": {"pipeline_id": None, "pipeline_name": None, "status_id": None, "status_name": None},
            "confirmation_field": {"field_id": None, "field_name": None, "enum_id": None, "enum_name": None}
        }
        
        try:
            # Детектим воронки
            pipelines_resp, status = await client.leads.request("get", "leads/pipelines")
            if status == 200:
                pipelines = pipelines_resp.get("_embedded", {}).get("pipelines", [])
                
                for pipeline in pipelines:
                    name = pipeline.get("name", "").lower()
                    
                    if "первичн" in name and not config["primary"]["pipeline_id"]:
                        config["primary"]["pipeline_id"] = pipeline["id"]
                        config["primary"]["pipeline_name"] = pipeline.get("name")
                        
                        statuses = pipeline.get("_embedded", {}).get("statuses", [])
                        for st in statuses:
                            st_name = st.get("name", "").lower()
                            # Ищем статус "Записались" (не "думают о записи")
                            if "записал" in st_name or "записан" in st_name:
                                config["primary"]["status_id"] = st["id"]
                                config["primary"]["status_name"] = st.get("name")
                                break
                    
                    elif ("вторичн" in name or "повторн" in name) and not config["secondary"]["pipeline_id"]:
                        config["secondary"]["pipeline_id"] = pipeline["id"]
                        config["secondary"]["pipeline_name"] = pipeline.get("name")
                        
                        statuses = pipeline.get("_embedded", {}).get("statuses", [])
                        for st in statuses:
                            st_name = st.get("name", "").lower()
                            # Ищем статус "Записались" (не "думают о записи")
                            if "записал" in st_name or "записан" in st_name:
                                config["secondary"]["status_id"] = st["id"]
                                config["secondary"]["status_name"] = st.get("name")
                                break
            
            # Детектим кастомное поле "Подтверждение"
            page = 1
            while page <= 5:  # Максимум 5 страниц
                params = {"page": page, "limit": 250}
                resp, status = await client.leads.request("get", "leads/custom_fields", params=params)
                
                if status != 200:
                    break
                
                fields = resp.get("_embedded", {}).get("custom_fields", [])
                if not fields:
                    break
                
                for field in fields:
                    name = field.get("name", "").lower()
                    if ("подтвержд" in name or "подтверж" in name) and not config["confirmation_field"]["field_id"]:
                        config["confirmation_field"]["field_id"] = field["id"]
                        config["confirmation_field"]["field_name"] = field.get("name")
                        
                        for enum in field.get("enums", []):
                            enum_value = enum.get("value", "").lower()
                            if "подтвержд" in enum_value and "не" not in enum_value:
                                config["confirmation_field"]["enum_id"] = enum["id"]
                                config["confirmation_field"]["enum_name"] = enum.get("value")
                                break
                        break
                
                if config["confirmation_field"]["field_id"]:
                    break
                
                if "next" not in resp.get("_links", {}):
                    break
                
                page += 1
            
            # Сохраняем конфигурацию в БД ТОЛЬКО если её не было
            config["auto_detected"] = True
            config["detected_at"] = datetime.now().isoformat()
            config["manually_overridden"] = False
            
            # Используем прямой доступ к БД через clinic_service
            await clinic_service.db.clinics.update_one(
                {"client_id": client_id},
                {"$set": {"conversion_config": config}}
            )
            logger.info(f"✅ Конфигурация автодетектирована и сохранена для {client_id}")
            
        except Exception as e:
            logger.error(f"Ошибка при автодетекции конфигурации: {e}", exc_info=True)
            return None
    else:
        # Если конфигурация уже существует, возвращаем её БЕЗ изменений
        logger.info(f"✅ Используем существующую конфигурацию (не перезаписываем)")
    
    # Проверяем полноту конфигурации
    # ВАЖНО: confirmation_field необязателен! Достаточно primary или secondary
    is_complete = (
        (config.get("primary", {}).get("pipeline_id") and config.get("primary", {}).get("status_id")) or
        (config.get("secondary", {}).get("pipeline_id") and config.get("secondary", {}).get("status_id"))
    )

    if not is_complete:
        logger.warning(f"Неполная конфигурация конверсий для {client_id}: нет ни primary, ни secondary воронок")
        return None

    return config


async def check_conversion_for_lead(client, lead_id, call_date, conversion_config):
    """
    Проверяет наличие конверсии для сделки.
    Возвращает (has_conversion: bool, conversion_type: str | None)
    """
    try:
        # Получаем метку времени дня звонка
        day_start = int(datetime.combine(call_date.date(), datetime.min.time()).timestamp())
        day_end = int(datetime.combine(call_date.date(), datetime.max.time()).timestamp())
        
        # 1. Используем эндпоинт events (единственный реально работающий в AmoCRM)
        # Проверено тестом test_events_api_endpoints.py: api/v4/events и api/v2/events не существуют
        api_path = "events"
        
        # 3. Разделяем события как в тестовой версии
        async def fetch_events(event_type=None):
            """Загружает все страницы событий за день звонка. Если event_type указан, добавляет фильтр по типу."""
            result = []
            page = 1
            while True:
                params = {
                    "filter[entity]": "lead",
                    "filter[entity_id]": lead_id,
                    "filter[created_at][from]": day_start,
                    "filter[created_at][to]": day_end,
                    "page": page,
                    "limit": 250,
                }
                if event_type:
                    params["filter[type]"] = event_type
                try:
                    resp, st = await client.contacts.request("get", api_path, params=params)
                except Exception:
                    break
                if st != 200:
                    break
                batch = resp.get("_embedded", {}).get("events", [])
                if not batch:
                    break
                result.extend(batch)
                if "next" in resp.get("_links", {}):
                    page += 1
                else:
                    break
            return result

        status_events = await fetch_events("lead_status_changed")
        all_events_for_day = await fetch_events()
        cf_events = [
            ev for ev in all_events_for_day
            if isinstance(ev.get("type"), str)
            and ev["type"].startswith("custom_field_")
            and ev["type"].endswith("_value_changed")
        ]
        
        # Извлекаем конфигурацию
        primary_pipeline = conversion_config.get("primary", {}).get("pipeline_id")
        primary_status = conversion_config.get("primary", {}).get("status_id")
        secondary_pipeline = conversion_config.get("secondary", {}).get("pipeline_id")
        secondary_status = conversion_config.get("secondary", {}).get("status_id")
        confirmation_field = conversion_config.get("confirmation_field", {}).get("field_id")
        confirmation_enum = conversion_config.get("confirmation_field", {}).get("enum_id")
        
        # 4. Проверяем кастомное поле Подтверждение (только если поле задано)
        # ВАЖНО: Пропускаем всю проверку если confirmation_field = None
        if confirmation_field is not None:
            for ev in cf_events:
                value_after = ev.get("value_after")
                if isinstance(value_after, dict):
                    items = [value_after]
                else:
                    items = value_after or []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    # Вариант 1: структура с обёрткой custom_field_values
                    if "custom_field_values" in item:
                        cfv = item.get("custom_field_values", {})
                        if cfv.get("field_id") == confirmation_field:
                            for enum_val in cfv.get("enum_values", []):
                                if enum_val.get("enum_id") == confirmation_enum:
                                    return True, "Подтверждение -> Подтвержден"
                    # Вариант 1.1: вложенный объект custom_field_value
                    if "custom_field_value" in item and isinstance(item.get("custom_field_value"), dict):
                        cfv = item.get("custom_field_value", {})
                        if cfv.get("field_id") == confirmation_field:
                            enum_ok = cfv.get("enum_id") == confirmation_enum
                            text = (cfv.get("text") or "").lower()
                            text_ok = ("подтвержд" in text) and ("не" not in text)
                            if enum_ok or text_ok:
                                return True, "Подтверждение -> Подтвержден"
                    # Вариант 2: плоская структура field_id / enum_id
                    if item.get("field_id") == confirmation_field:
                        enum_id = item.get("enum_id") or item.get("value")
                        if enum_id == confirmation_enum:
                            return True, "Подтверждение -> Подтвержден"

        # 4.1. Резерв: по состоянию сделки, если нет событий (только если поле задано)
        # ВАЖНО: Пропускаем эту проверку если confirmation_field = None
        if confirmation_field is not None:
            try:
                lead_snapshot = await client.get_lead(lead_id)
            except Exception:
                lead_snapshot = None
            if lead_snapshot:
                lu = lead_snapshot.get("updated_at") or 0
                if day_start <= lu <= day_end:
                    for cf in (lead_snapshot.get("custom_fields_values") or []):
                        fid = cf.get("field_id")
                        if fid == confirmation_field:
                            for v in cf.get("values", []):
                                enum_id = v.get("enum_id")
                                text = (v.get("value") or "").lower()
                                if enum_id == confirmation_enum or ("подтвержд" in text and "не" not in text):
                                    return True, "Подтверждение -> Подтвержден"
        
        # 5. Проверяем смену статуса на "Записались" в нужных воронках (как в тестовой версии)
        for ev in status_events:
            for item in ev.get("value_after", []):
                ls = item.get("lead_status", {})
                pid = ls.get("pipeline_id")
                sid = ls.get("id")
                if pid == primary_pipeline and sid == primary_status:
                    return True, "Первичные -> Записались"
                if pid == secondary_pipeline and sid == secondary_status:
                    return True, "Вторичные -> Записались"
        
        return False, None
        
    except Exception as e:
        logger.error(f"Ошибка при проверке конверсии для сделки {lead_id}: {e}")
        return False, None


async def enrich_calls_with_conversion(calls_events, client, call_date, conversion_config, clinic_service, client_id):
    """
    Обогащает звонки данными о конверсии.
    Проверяет каждую уникальную сделку на наличие конверсии.
    """
    logger.info(f"Начало обогащения {len(calls_events)} звонков конверсией")
    
    if not conversion_config:
        logger.warning("Конфигурация конверсий отсутствует, пропускаем обогащение")
        return calls_events
    
    # Собираем уникальные lead_id
    unique_leads = {}
    for event in calls_events:
        lead_id = event.get("lead_id")
        if lead_id and lead_id not in unique_leads:
            unique_leads[lead_id] = event
    
    logger.info(f"Найдено {len(unique_leads)} уникальных сделок для проверки")
    
    # Проверяем конверсии
    converted_leads = {}
    conversion_types = {}
    
    for idx, lead_id in enumerate(unique_leads.keys(), 1):
        has_conversion, conv_type = await check_conversion_for_lead(
            client, lead_id, call_date, conversion_config
        )
        
        if has_conversion:
            converted_leads[lead_id] = True
            conversion_types[lead_id] = conv_type
            logger.info(f"✅ [Conversion Found] lead_id={lead_id}, type={conv_type}")
        
        if idx % 50 == 0:
            logger.info(f"Проверено конверсий: {idx}/{len(unique_leads)}")
    
    # ЛОГИРУЕМ итоги проверки
    logger.info(f"🎯 [Conversion Check Complete] Найдено {len(converted_leads)} конверсий из {len(unique_leads)} уникальных сделок")
    
    logger.info(f"Найдено конверсий: {len(converted_leads)} из {len(unique_leads)} сделок")
    
    # Обогащаем события звонков
    enriched_count = 0
    for event in calls_events:
        lead_id = event.get("lead_id")
        if lead_id and lead_id in converted_leads:
            event["conversion"] = True
            event["conversion_type"] = conversion_types.get(lead_id)
            enriched_count += 1
    
    logger.info(f"Обогащено звонков: {enriched_count}")
    
    return calls_events


router = APIRouter(prefix="/api/calls-events", tags=["Звонки через API событий"])

# Настройка логирования
logger = logging.getLogger(__name__)


# Глобальные счетчики для статистики
export_stats = {
    "total_processed": 0,
    "saved_to_db": 0,
    "filtered_zero_duration": 0,
    "filtered_short_calls": 0,
    "filtered_duplicates": 0,
    "processing_errors": 0
}

async def process_single_call_event(event, client_id, subdomain, administrator, source, detailed=True, conversion_config=None, call_date=None):
    """
    Обрабатывает одно событие звонка в фоновом режиме.
    Обновляет глобальные счетчики статистики.
    """
    event_id = event.get('id', 'unknown')
    logger.info(f"Начало обработки события {event_id} в фоновом режиме (detailed={detailed})")
    
    try:
        # Создаем клиент AmoCRM для этой задачи
        clinic_service = ClinicService()
        clinic = await clinic_service.find_clinic_by_client_id(client_id)
        
        if not clinic:
            logger.error(f"Клиника с client_id={client_id} не найдена в фоновой задаче")
            return
            
        client = AsyncAmoCRMClient(
            client_id=clinic["client_id"],
            client_secret=clinic["client_secret"],
            subdomain=clinic["amocrm_subdomain"],
            redirect_url=clinic["redirect_url"],
            mongo_uri=MONGO_URI,
            db_name=DB_NAME
        )
        
        try:
            # Обрабатываем событие
            if detailed:
                # Получаем детальную информацию
                call_record = await get_call_details(event, client, administrator, source, client_id, subdomain)
            else:
                # Создаем базовую запись
                call_record = await create_basic_call_record(event, client_id, subdomain, administrator, source)
            
            # Обновляем счетчики
            export_stats["total_processed"] += 1
            
            if call_record:
                # Обогащаем конверсиями ПОСЛЕ создания call_record с реальными данными
                if conversion_config and call_date:
                    try:
                        lead_id = call_record.get("lead_id")
                        if lead_id:
                            # Проверяем конверсию для этого lead_id
                            has_conversion, conv_type = await check_conversion_for_lead(
                                client, lead_id, call_date, conversion_config
                            )
                            
                            # Добавляем данные о конверсии в call_record
                            if "metrics" not in call_record:
                                call_record["metrics"] = {}
                            call_record["metrics"]["conversion"] = has_conversion
                            if conv_type:
                                call_record["conversion_type"] = conv_type
                                
                            logger.info(f"🎯 [Conversion] Lead {lead_id}: {has_conversion}, {conv_type}")
                    except Exception as e:
                        logger.error(f"Ошибка при обогащении конверсией для lead {call_record.get('lead_id')}: {e}")
                
                # Пытаемся сохранить (может быть отфильтровано)
                save_result = await save_call_record_to_db(call_record, client_id)
                
                if save_result == "saved":
                    export_stats["saved_to_db"] += 1
                    logger.info(f"Событие {event_id} обработано и сохранено")
                elif save_result == "zero_duration":
                    export_stats["filtered_zero_duration"] += 1
                elif save_result == "short_call":
                    export_stats["filtered_short_calls"] += 1
                elif save_result == "duplicate":
                    export_stats["filtered_duplicates"] += 1
                elif save_result == "error":
                    export_stats["processing_errors"] += 1
            else:
                export_stats["processing_errors"] += 1
                logger.warning(f"Не удалось обработать событие {event_id}")
                
        finally:
            await client.close()
            
    except Exception as e:
        export_stats["processing_errors"] += 1
        logger.error(f"Ошибка при обработке события {event_id}: {e}", exc_info=True)


async def save_call_record_to_db(call_record, client_id):
    """
    Сохраняет запись о звонке в MongoDB коллекцию calls.
    Применяет фильтры: не сохраняет нулевые, дубли и звонки <6 сек.
    """
    try:
        # ЗАЩИТА: Пропускаем API эндпоинты заметок AmoCRM
        call_link = call_record.get("call_link", "")
        if "/api/v4/contacts/" in call_link and "/notes/" in call_link:
            logger.debug(f"Пропущен API эндпоинт заметки (не аудио): {call_link[:80]}")
            return "filtered_api_endpoint"
        
        # Проверяем фильтры перед сохранением
        duration = call_record.get("duration", 0)
        
        # Отсекаем нулевые звонки
        if duration == 0:
            logger.debug(f"Пропущен нулевой звонок note_id={call_record.get('note_id')}")
            return "zero_duration"
            
        # Отсекаем звонки меньше 6 секунд
        if duration < 6:
            logger.debug(f"Пропущен короткий звонок ({duration} сек) note_id={call_record.get('note_id')}")
            return "short_call"
        
        # Создаем асинхронное соединение к MongoDB
        mongo_client = AsyncIOMotorClient(MONGO_URI)
        db = mongo_client[DB_NAME]
        calls_collection = db.calls
        
        # Используем дату звонка для created_date_for_filtering
        created_at = call_record.get("created_at")
        if created_at:
            # Преобразуем timestamp в дату звонка
            call_date = datetime.fromtimestamp(created_at).strftime('%Y-%m-%d')
        else:
            call_date = datetime.now().strftime('%Y-%m-%d')
        
        # Добавляем метаданные как в оригинальном коде
        call_record_final = {
            **call_record,
            "recorded_at": datetime.now(),
            "created_date_for_filtering": call_date  # Дата звонка, не текущая!
        }
        
        # ЛОГИРУЕМ что сохраняем в БД
        logger.info(f"💾 [Save to DB] note_id={call_record.get('note_id')}, lead_id={call_record.get('lead_id')}, metrics.conversion={call_record.get('metrics', {}).get('conversion')}, conversion_type={call_record.get('conversion_type')}")
        
        # Проверяем на дубли по note_id
        note_id = call_record.get("note_id")
        if note_id:
            existing_record = await calls_collection.find_one({"note_id": note_id})
            if existing_record:
                # Отсекаем дубли - не сохраняем
                logger.debug(f"Пропущен дубль note_id={note_id}")
                mongo_client.close()
                return "duplicate"
            else:
                # Сохраняем новую запись
                result = await calls_collection.insert_one(call_record_final)
                logger.info(f"Сохранен звонок note_id={note_id}, duration={duration} сек, дата: {call_date} (inserted_id: {result.inserted_id})")
                mongo_client.close()
                return "saved"
        else:
            # Если note_id нет, сохраняем (но это не должно происходить)
            result = await calls_collection.insert_one(call_record_final)
            logger.warning(f"Сохранен звонок без note_id дата: {call_date} (inserted_id: {result.inserted_id})")
            mongo_client.close()
            return "saved"
        
    except Exception as e:
        logger.error(f"Ошибка при сохранении записи о звонке: {e}", exc_info=True)
        return "error"


async def create_basic_call_record(event, client_id, subdomain, administrator, source):
    """Создает базовую запись о звонке из события без детализации."""
    entity_id = event.get("entity_id")
    entity_type = event.get("entity_type")
    event_type = event.get("type")
    created_at = event.get("created_at")
    event_id = event.get("id")
    
    # Определяем тип звонка
    call_direction = "Входящий" if event_type == "incoming_call" else "Исходящий"
    
    # ЛОГИРУЕМ входящие данные конверсии
    event_conversion = event.get("conversion")
    event_conversion_type = event.get("conversion_type")
    logger.info(f"📝 [Basic Record] event_id={event_id}, lead_id={entity_id if entity_type == 'lead' else None}, event.conversion={event_conversion}, event.conversion_type={event_conversion_type}")
    
    record = {
        "note_id": event_id,  # Используем ID события как ID заметки
        "event_id": event_id,
        "lead_id": entity_id if entity_type == "lead" else None,
        "lead_name": "",
        "contact_id": entity_id if entity_type == "contact" else None,
        "contact_name": "Неизвестный контакт",
        "client_id": client_id,
        "subdomain": subdomain,
        "call_direction": call_direction,
        "duration": 0,  # Нет данных о длительности
        "duration_formatted": "0:00",
        "phone": "Неизвестно",  # Нет данных о телефоне
        "call_link": "",  # Нет данных о ссылке
        "created_at": created_at,
        "created_date": datetime.fromtimestamp(created_at).strftime("%Y-%m-%d %H:%M:%S") if created_at else None,
        "administrator": administrator,
        "source": source,
        "processing_speed": 0,
        "processing_speed_str": "0 мин",
        "transcription_status": "pending",  # Инициализируем статус транскрибации
        "metrics": {
            "conversion": event.get("conversion", False)  # Поле конверсии из обогащения
        }
    }
    
    # Добавляем тип конверсии если есть
    if event.get("conversion_type"):
        record["conversion_type"] = event.get("conversion_type")
        logger.info(f"✅ [Basic Record] Добавлен conversion_type: {event.get('conversion_type')}")
    
    logger.info(f"📤 [Basic Record] Итоговый record.metrics.conversion={record['metrics']['conversion']}")
    
    return record


@router.post("/export")
async def export_calls_from_events(
    request: CallsExportRequest,
    background_tasks: BackgroundTasks
) -> Dict[str, Any]:
    """
    Запускает экспорт звонков через API событий AmoCRM в фоновом режиме.
    Немедленно возвращает ответ о количестве поставленных в очередь задач.
    """
    client = None
    try:
        start_time = datetime.now()
        logger.info(f"Запрос экспорта звонков: client_id={request.client_id}")
        
        # Находим клинику по client_id
        clinic_service = ClinicService()
        clinic = await clinic_service.find_clinic_by_client_id(request.client_id)
        
        if not clinic:
            return {
                "success": False,
                "message": f"Клиника с client_id={request.client_id} не найдена"
            }

        # Создаем клиент AmoCRM для получения событий
        client = AsyncAmoCRMClient(
            client_id=clinic["client_id"],
            client_secret=clinic["client_secret"],
            subdomain=clinic["amocrm_subdomain"],
            redirect_url=clinic["redirect_url"],
            mongo_uri=MONGO_URI,
            db_name=DB_NAME
        )

        # --- Гарантированное обновление токена при смене клиники ---
        logger.info(f"Принудительная проверка и обновление токена для client_id={request.client_id}")
        try:
            # Шаг 1: Обновляем токен через существующий клиент
            await client.token_manager.get_access_token()
            logger.info(f"Токен для client_id={request.client_id} успешно проверен и/или обновлен.")
            
            # Шаг 2: Даем достаточно времени на запись в базу данных и стабилизацию состояния
            logger.info("Ожидание 3 секунды для полной стабилизации...")
            await asyncio.sleep(3)
            
            # Шаг 3: КРИТИЧЕСКИ ВАЖНО - пересоздаем клиент с чистым состоянием
            # НЕ закрываем старый клиент явно, чтобы не повредить глобальное состояние
            client = AsyncAmoCRMClient(
                client_id=clinic["client_id"],
                client_secret=clinic["client_secret"],
                subdomain=clinic["amocrm_subdomain"],
                redirect_url=clinic["redirect_url"],
                mongo_uri=MONGO_URI,
                db_name=DB_NAME
            )
            logger.info("Клиент AmoCRM был пересоздан с обновленным токеном из базы данных.")
            
            # Шаг 4: Делаем тестовый запрос с повторной попыткой
            max_retries = 2
            last_error = None
            for attempt in range(max_retries):
                try:
                    account_info, status = await client.contacts.request("get", "account")
                    if status == 200:
                        logger.info(f"Тестовый запрос успешен (попытка {attempt + 1}). Клиент работает с {account_info.get('subdomain', 'неизвестный субдомен')}")
                        break
                    else:
                        last_error = f"Статус {status}"
                        if attempt < max_retries - 1:
                            logger.warning(f"Тестовый запрос вернул статус {status}, повторная попытка через 2 секунды...")
                            await asyncio.sleep(2)
                except Exception as e:
                    last_error = str(e)
                    if attempt < max_retries - 1:
                        logger.warning(f"Тестовый запрос провалился ({e}), повторная попытка через 2 секунды...")
                        await asyncio.sleep(2)
                    else:
                        raise Exception(f"Все попытки тестового запроса провалились. Последняя ошибка: {last_error}")
            
        except Exception as e:
            logger.error(f"Критическая ошибка при обновлении токена и пересоздании клиента: {e}", exc_info=True)
            raise
        # -----------------------------------------------------------------

        # Подготовка временного диапазона, если указаны даты
        start_timestamp = None
        end_timestamp = None
        
        # Подготовка временного диапазона, если указаны даты
        if request.start_date:
            try:
                # Получаем дату начала как объект datetime
                date_obj = convert_date_string(request.start_date)
                if not date_obj:
                    return {"success": False, "message": "Ошибка в формате начальной даты"}
                
                # Преобразуем в timestamp начала дня (00:00:00)
                start_timestamp = int(datetime.combine(date_obj.date(), datetime.min.time()).timestamp())
                logger.info(f"Начальная дата: {date_obj.strftime('%d.%m.%Y')}, timestamp: {start_timestamp}")
            except Exception as e:
                return {"success": False, "message": f"Ошибка в формате начальной даты: {str(e)}"}
        
        if request.end_date:
            try:
                # Получаем дату окончания как объект datetime
                date_obj = convert_date_string(request.end_date)
                if not date_obj:
                    return {"success": False, "message": "Ошибка в формате конечной даты"}
                
                # Преобразуем в timestamp конца дня (23:59:59)
                end_timestamp = int(datetime.combine(date_obj.date(), datetime.max.time()).timestamp())
                logger.info(f"Конечная дата: {date_obj.strftime('%d.%m.%Y')}, timestamp: {end_timestamp}")
            except Exception as e:
                return {"success": False, "message": f"Ошибка в формате конечной даты: {str(e)}"}
        
        
        # Получаем данные об администраторе и источнике для звонков
        administrator = clinic.get("administrator", "Неизвестный")
        source = clinic.get("source", "Неопределенный")
        
        # Получаем список звонков из API событий
        calls_events = await get_calls_from_events(
            client=client,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            max_pages=request.max_pages
        )
        
        logger.info(f"Найдено {len(calls_events)} событий звонков через API событий")
        
        if not calls_events:
            return {
                "success": True,
                "message": "Не найдено событий звонков для обработки",
                "total_found": 0,
                "tasks_queued": 0,
                "duration_seconds": (datetime.now() - start_time).total_seconds()
            }
        
        # НЕ обогащаем здесь - будем обогащать в process_single_call_event
        # после создания call_record с реальными данными о звонке
        logger.info(f"Пропускаем обогащение на уровне событий, будем обогащать в process_single_call_event")
        
        # Получаем конфигурацию конверсий для передачи в фоновые задачи
        conversion_config = None
        call_date = convert_date_string(request.start_date) if request.start_date else datetime.now()
        try:
            conversion_config = await detect_conversion_config(client, clinic_service, request.client_id)
            if conversion_config:
                logger.info(f"✅ Конфигурация конверсий получена для обогащения в process_single_call_event")
        except Exception as e:
            logger.error(f"Ошибка при получении конфигурации конверсий: {e}", exc_info=True)
        
        # Ограничиваем количество обрабатываемых звонков
        max_calls_to_process = min(len(calls_events), request.max_calls)
        calls_to_process = calls_events[:max_calls_to_process]
        
        logger.info(f"Запуск обработки {len(calls_to_process)} событий звонков в фоновом режиме (detailed={request.detailed})")
        logger.info(f"Пример события: {calls_to_process[0] if calls_to_process else 'None'}")
        
        tasks_queued_count = 0
        
        # Добавляем каждое событие звонка как отдельную фоновую задачу
        for event in calls_to_process:
            try:
                background_tasks.add_task(
                    process_single_call_event,
                    event=event,
                    client_id=request.client_id,
                    subdomain=clinic["amocrm_subdomain"],
                    administrator=administrator,
                    source=source,
                    detailed=request.detailed,
                    # Передаем данные для обогащения конверсиями
                    conversion_config=conversion_config,
                    call_date=call_date
                )
                tasks_queued_count += 1
            except Exception as e:
                logger.error(f"Ошибка при добавлении фоновой задачи для события {event.get('id', 'unknown')}: {e}")
        
        duration = (datetime.now() - start_time).total_seconds()
        logger.info(f"Экспорт звонков: {tasks_queued_count} задач добавлено в фон. Длительность постановки: {duration:.2f} сек.")
        
        # Сбрасываем счетчики перед новым экспортом
        global export_stats
        export_stats = {
            "total_processed": 0,
            "saved_to_db": 0,
            "filtered_zero_duration": 0,
            "filtered_short_calls": 0,
            "filtered_duplicates": 0,
            "processing_errors": 0
        }
        
        # Добавляем фоновую задачу для вывода и сохранения итоговой статистики
        background_tasks.add_task(
            print_final_stats, 
            request.client_id, 
            len(calls_to_process), 
            30, 
            request.start_date, 
            request.end_date
        )
        
        return {
            "success": True,
            "message": f"{tasks_queued_count} задач на обработку звонков добавлено в фон. Итоговая статистика будет выведена в логи через 30 сек.",
            "total_found": len(calls_events),
            "tasks_queued": tasks_queued_count,
            "duration_seconds": duration,
            "detailed_mode": request.detailed,
            "max_calls_limit": request.max_calls,
            "note": "Просмотрите логи сервера через 30 сек для итоговой статистики"
        }
    except Exception as e:
        error_msg = f"Ошибка при экспорте звонков: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {"success": False, "message": error_msg}
    finally:
        if client:
            await client.close()


async def print_final_stats(client_id, total_events, delay_seconds, start_date: str, end_date: str):
    """
    Выводит итоговую статистику экспорта в логи и сохраняет её в MongoDB.
    Ждёт пока ВСЕ задачи обработаются, а не фиксированное время.
    """
    import asyncio
    
    # Ждём пока все события будут обработаны (с таймаутом 30 минут)
    max_wait_seconds = 1800  # 30 минут максимум
    poll_interval = 5  # проверяем каждые 5 секунд
    waited = 0
    
    logger.info(f"⏳ Ожидание обработки {total_events} событий...")
    
    while waited < max_wait_seconds:
        processed = export_stats.get("total_processed", 0)
        if processed >= total_events:
            logger.info(f"✅ Все {total_events} событий обработаны за {waited} сек")
            break
        
        # Логируем прогресс каждые 30 секунд
        if waited > 0 and waited % 30 == 0:
            logger.info(f"   Обработано {processed}/{total_events} ({processed*100//total_events}%)")
        
        await asyncio.sleep(poll_interval)
        waited += poll_interval
    
    if waited >= max_wait_seconds:
        logger.warning(f"⚠️ Таймаут ожидания! Обработано {export_stats.get('total_processed', 0)}/{total_events}")
    
    logger.info("\n" + "="*80)
    logger.info("📊 ИТОГОВАЯ СТАТИСТИКА ЭКСПОРТА ЗВОНКОВ")
    logger.info("="*80)
    logger.info(f"🏢 Client ID: {client_id}")
    logger.info(f"📅 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"📚 Общие данные:")
    logger.info(f"   • Событий найдено: {total_events}")
    logger.info(f"   • Обработано: {export_stats['total_processed']}")
    logger.info(f"")
    logger.info(f"✅ УСПЕШНО СОХРАНЕНО В БАЗУ: {export_stats['saved_to_db']}")
    logger.info(f"")
    logger.info(f"❌ ОТФИЛЬТРОВАНО:")
    logger.info(f"   • Нулевых звонков (0 сек): {export_stats['filtered_zero_duration']}")
    logger.info(f"   • Коротких звонков (<6 сек): {export_stats['filtered_short_calls']}")
    logger.info(f"   • Дублей: {export_stats['filtered_duplicates']}")
    logger.info(f"")
    logger.info(f"⚠️ Ошибок обработки: {export_stats['processing_errors']}")
    logger.info(f"")
    
    # Подсчитываем проценты
    if export_stats['total_processed'] > 0:
        save_rate = (export_stats['saved_to_db'] / export_stats['total_processed']) * 100
        filter_rate = ((export_stats['filtered_zero_duration'] + export_stats['filtered_short_calls'] + export_stats['filtered_duplicates']) / export_stats['total_processed']) * 100
        logger.info(f"📊 ПРОЦЕНТЫ:")
        logger.info(f"   • Сохранено: {save_rate:.1f}%")
        logger.info(f"   • Отфильтровано: {filter_rate:.1f}%")
    
    # --- СОХРАНЕНИЕ ИТОГОВОЙ СТАТИСТИКИ В MONGODB ---
    mongo_client = None
    try:
        mongo_client = AsyncIOMotorClient(MONGO_URI)
        db = mongo_client[DB_NAME]
        status_collection = db.call_status

        status_doc = {
            "client_id": client_id,
            "start_date": start_date,
            "end_date": end_date,
            "total_found": total_events,
            "total_processed": export_stats['total_processed'],
            "saved_to_db": export_stats['saved_to_db'],
            "filtered_zero_duration": export_stats['filtered_zero_duration'],
            "filtered_short_calls": export_stats['filtered_short_calls'],
            "filtered_duplicates": export_stats['filtered_duplicates'],
            "processing_errors": export_stats['processing_errors'],
            "created_at": datetime.now()
        }

        # Обновляем или создаем запись
        await status_collection.update_one(
            {
                "client_id": client_id,
                "start_date": start_date,
                "end_date": end_date
            },
            {"$set": status_doc},
            upsert=True
        )
        logger.info(f"Итоговая статистика для диапазона {start_date}-{end_date} сохранена в call_status.")

    except Exception as e:
        logger.error(f"Ошибка при сохранении итоговой статистики в call_status: {e}", exc_info=True)
    finally:
        if mongo_client:
            mongo_client.close()
    # --------------------------------------------------

    logger.info("="*80)
    logger.info("🚀 ЭКСПОРТ ЗАВЕРШЕН!")
    logger.info("="*80 + "\n")


@router.get("/export-status")
async def get_export_status(
    client_id: str = Query(..., description="ID клиента"),
    date: str = Query(..., description="Дата в формате DD.MM.YYYY")
) -> Dict[str, Any]:
    """
    Получить статистику экспорта звонков за конкретную дату.
    """
    mongo_client = None
    try:
        mongo_client = AsyncIOMotorClient(MONGO_URI)
        db = mongo_client[DB_NAME]
        collection = db.calls  # Используем коллекцию calls
        
        # Преобразуем дату в правильный формат
        from .calls import convert_date_string
        date_obj = convert_date_string(date)
        if not date_obj:
            return {"success": False, "message": f"Неверный формат даты. Используйте DD.MM.YYYY"}
        
        date_filter_str = date_obj.strftime('%Y-%m-%d')
        
        query = {
            "client_id": client_id,
            "created_date_for_filtering": date_filter_str
        }
        
        # Подсчитываем статистику
        total_exported = await collection.count_documents(query)
        
        # Получаем последние записи
        recent_records_cursor = collection.find(query).sort("recorded_at", -1).limit(10)
        recent_records = await recent_records_cursor.to_list(length=10)
        
        # Подсчитываем полную статистику
        short_calls_count = 0  # <6 сек
        normal_calls_count = 0  # >=6 сек
        
        for record in recent_records:
            duration = record.get("duration", 0)
            if 0 < duration < 6:
                short_calls_count += 1
            elif duration >= 6:
                normal_calls_count += 1
        
        return {
            "success": True,
            "message": f"Статистика звонков за {date}",
            "client_id": client_id,
            "date": date,
            "date_filter": date_filter_str,
            "statistics": {
                "total_calls_found": total_exported,
                "normal_calls": normal_calls_count,
                "short_calls": short_calls_count,
                "sample_size": len(recent_records)
            },
            "recent_calls_sample": [
                {
                    "event_id": record.get("event_id"),
                    "phone": record.get("phone", "Неизвестно"),
                    "duration": record.get("duration", 0),
                    "call_direction": record.get("call_direction"),
                    "recorded_at": record.get("recorded_at").isoformat() if record.get("recorded_at") else None,
                    "has_call_link": bool(record.get("call_link"))
                }
                for record in recent_records[:5]  # Показываем только 5 последних
            ],
            "note": "FastAPI BackgroundTasks не поддерживает отслеживание статуса. Данная статистика основана на сохраненных записях."
        }
    except Exception as e:
        logger.error(f"Ошибка при получении статуса экспорта: {e}")
        return {"success": False, "message": f"Ошибка: {str(e)}"}
    finally:
        if mongo_client:
            mongo_client.close()


@router.get("/export-results")
async def get_export_results(
    client_id: str = Query(..., description="ID клиента"),
    start_date: str = Query(..., description="Начальная дата в формате DD.MM.YYYY"),
    end_date: str = Query(..., description="Конечная дата в формате DD.MM.YYYY"),
) -> Dict[str, Any]:
    """
    Получает итоговую статистику экспорта из коллекции call_status.
    """
    mongo_client = None
    try:
        mongo_client = AsyncIOMotorClient(MONGO_URI)
        db = mongo_client[DB_NAME]
        status_collection = db.call_status

        # Ищем последнюю запись статистики для данного диапазона
        status_doc = await status_collection.find_one(
            {
                "client_id": client_id,
                "start_date": start_date,
                "end_date": end_date
            },
            sort=[("created_at", -1)]
        )

        if not status_doc:
            raise HTTPException(
                status_code=404, 
                detail=f"Статистика для диапазона {start_date} - {end_date} не найдена. Запустите экспорт."
            )

        # Убираем служебное поле _id
        status_doc.pop("_id", None)
        if 'created_at' in status_doc:
            status_doc['created_at'] = status_doc['created_at'].isoformat()

        total_found = status_doc.get("total_found", 0)
        saved_to_db = status_doc.get("saved_to_db", 0)
        filtered_total = total_found - saved_to_db if total_found >= saved_to_db else 0

        return {
            "success": True,
            "message": f"Статистика экспорта за {start_date} - {end_date}: Найдено {total_found}, Сохранено {saved_to_db}, Отфильтровано {filtered_total}",
            "statistics": status_doc
        }

    except HTTPException as http_exc:
        # Перехватываем и пробрасываем HTTPException, чтобы FastAPI вернул правильный статус
        raise http_exc
    except Exception as e:
        logger.error(f"Ошибка при получении результатов экспорта из call_status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Внутренняя ошибка сервера")
    finally:
        if mongo_client:
            mongo_client.close()


@router.delete("/export-results")
async def clear_export_results(
    client_id: str = Query(..., description="ID клиента для очистки результатов")
) -> Dict[str, Any]:
    """
    Очистить сохраненные результаты экспорта звонков для клиента.
    """
    mongo_client = None
    try:
        mongo_client = AsyncIOMotorClient(MONGO_URI)
        db = mongo_client[DB_NAME]
        collection = db.calls  # Используем коллекцию calls
        
        query = {"client_id": client_id}  # Используем client_id
        
        # Подсчитываем количество до удаления
        count_before = await collection.count_documents(query)
        
        # Удаляем записи
        result = await collection.delete_many(query)
        
        return {
            "success": True,
            "message": f"Удалено {result.deleted_count} записей о звонках для client_id={client_id}",
            "deleted_count": result.deleted_count,
            "count_before": count_before
        }
    except Exception as e:
        logger.error(f"Ошибка при очистке результатов экспорта: {e}")
        return {"success": False, "message": f"Ошибка: {str(e)}"}
    finally:
        if mongo_client:
            mongo_client.close()


async def get_calls_from_events(client, start_timestamp=None, end_timestamp=None, max_pages=10):
    """
    Получает список событий звонков из API AmoCRM
    """
    calls_events = []
    page = 1
    has_more = True

    # Используем эндпоинт events (единственный реально работающий в AmoCRM)
    # Проверено тестом test_events_api_endpoints.py
    api_path = "events"
    
    # Запрашиваем события с пагинацией
    while has_more and page <= max_pages:
        params = {
            "page": page,
            "limit": 250,  # Максимальное количество на страницу
            "filter[type][]": ["incoming_call", "outgoing_call"]  # Фильтр только по звонкам (массив)
        }
        
        # Добавляем фильтр по дате
        if start_timestamp:
            params["filter[created_at][from]"] = start_timestamp
        if end_timestamp:
            params["filter[created_at][to]"] = end_timestamp
            
        logger.info(f"Запрос событий звонков, страница {page} из {max_pages}")
        
        try:
            response_data, status_code = await client.contacts.request("get", api_path, params=params)
            
            if status_code != 200:
                logger.error(f"Ошибка при запросе событий на странице {page}: HTTP {status_code}")
                break
            
            # Обрабатываем события на текущей странице
            if "_embedded" in response_data and "events" in response_data["_embedded"]:
                events = response_data["_embedded"]["events"]
                calls_events.extend(events)
                logger.info(f"Получено {len(events)} событий звонков на странице {page}")
                
                # Проверяем наличие следующей страницы
                if "_links" in response_data and "next" in response_data["_links"]:
                    page += 1
                else:
                    has_more = False
            else:
                has_more = False
            
            # Небольшая пауза между запросами
            await asyncio.sleep(0.2)
            
        except Exception as e:
            logger.error(f"Ошибка при запросе событий на странице {page}: {str(e)}")
            break
    
    return calls_events


async def get_call_details(event, client, administrator, source, client_id_str="", subdomain_str=""):
    """
    Получает детальную информацию о звонке из AmoCRM.
    
    Используем методы get_call_links и get_call_links_from_lead для получения деталей звонков.
    В случае неудачи возвращаем базовые данные из события.
    """
    event_id = event.get("id", "")
    logger.debug(f"Получение деталей звонка для события ID={event_id}")
    
    try:
        entity_id = event.get("entity_id")
        entity_type = event.get("entity_type")
        event_type = event.get("type")
        created_at = event.get("created_at")
        event_id = event.get("id")
        
        logger.info(f"🔍 ОТЛАДКА: id={event_id}, entity_type='{entity_type}', entity_id={entity_id}, event_type={event_type}")
        logger.debug(f"Обработка события: id={event_id}, type={event_type}, entity={entity_type}:{entity_id}, created_at={created_at}")
        
        # Получаем client_id и subdomain из параметров или объекта client
        client_id = client_id_str or getattr(client, "_client_id", "") or ""
        subdomain = subdomain_str or getattr(client, "_subdomain", "") or ""
        
        # Определяем тип звонка
        call_direction = "Входящий" if event_type == "incoming_call" else "Исходящий"
        
        # Создаем базовую запись о звонке
        call_record = {
            "note_id": event_id,  # По умолчанию используем ID события
            "event_id": event_id,
            "lead_id": entity_id if entity_type == "lead" else None,
            "lead_name": "",
            "contact_id": entity_id if entity_type == "contact" else None,
            "contact_name": "Неизвестный контакт",
            "client_id": client_id,
            "subdomain": subdomain,
            "administrator": administrator,
            "source": source,
            "processing_speed": 0,          # Скорость обработки в минутах
            "processing_speed_str": "0 мин", # Скорость обработки строкой
            "call_direction": call_direction,
            "duration": 0,  # По умолчанию нулевая длительность
            "duration_formatted": "0:00",
            "phone": "Неизвестно",
            "call_link": "",
            "created_at": created_at,
            "created_date": datetime.fromtimestamp(created_at).strftime("%Y-%m-%d %H:%M:%S") if created_at else None,
            "transcription_status": "pending",  # Инициализируем статус транскрибации
            "metrics": {
                "conversion": event.get("conversion", False)  # Поле конверсии из обогащения
            }
        }
        
        # Добавляем тип конверсии если есть
        if event.get("conversion_type"):
            call_record["conversion_type"] = event.get("conversion_type")
        
        logger.info(f"📝 Базовая запись создана: lead_id={call_record['lead_id']}, entity_type='{entity_type}', entity_id={entity_id}")
        
        # Для контактов получаем детали с помощью get_call_links
        details_found = False
        
        # Вариант 1: Если это контакт, получаем звонки через get_call_links
        if entity_type == "contact" and entity_id and isinstance(entity_id, int):
            try:
                # Получаем детали звонков для контакта
                logger.debug(f"Запрос звонков для контакта {entity_id}")
                call_links = await client.get_call_links(entity_id)
                
                # Если нашли звонки, ищем соответствующий данному событию
                if call_links:
                    logger.debug(f"Найдено {len(call_links)} звонков для контакта {entity_id}")
                    
                    # Фильтруем звонки по времени (+-10 минут от времени события)
                    time_window = 600  # 10 минут
                    matching_calls = []
                    
                    for call_link in call_links:
                        call_created_at = call_link.get("note", {}).get("created_at", 0)
                        
                        # Проверяем, что звонок примерно совпадает по времени с событием
                        if abs(call_created_at - created_at) <= time_window:
                            matching_calls.append(call_link)
                    
                    # Используем первый найденный подходящий звонок
                    if matching_calls:
                        # Берем первый совпадающий звонок
                        matching_call = matching_calls[0]
                        note = matching_call.get("note", {})
                        params = note.get("params", {})
                        
                        # Заполняем детальную информацию о звонке
                        call_record["note_id"] = matching_call.get("note_id") or event_id
                        call_record["call_link"] = matching_call.get("call_link", "")
                        
                        # Длительность звонка
                        if "duration" in params:
                            duration = params.get("duration", 0)
                            call_record["duration"] = duration
                            
                            # Форматируем длительность
                            minutes = duration // 60
                            seconds = duration % 60
                            call_record["duration_formatted"] = f"{minutes}:{seconds:02d}"
                        
                        # Телефон
                        if "phone" in params:
                            call_record["phone"] = params.get("phone", "Неизвестно")

                        # --- НАЧАЛО БЛОКА ОБОГАЩЕНИЯ ---
                        # Извлекаем lead_id из заметки (если звонок привязан к сделке)
                        embedded = note.get("_embedded", {})
                        leads = embedded.get("leads", [])
                        if leads and len(leads) > 0:
                            lead_id_from_note = leads[0].get("id")
                            if lead_id_from_note:
                                call_record["lead_id"] = lead_id_from_note
                                logger.info(f"✅ Извлечен lead_id={lead_id_from_note} из заметки контакта")
                        
                        try:
                            # Получаем имя контакта напрямую
                            contact_info = await client.get_contact(entity_id)
                            if contact_info:
                                call_record["contact_name"] = contact_info.get("name", call_record["contact_name"])
                                logger.debug(f"[Enrichment] Имя контакта обновлено: {call_record['contact_name']}")
                                
                                # ДОПОЛНИТЕЛЬНОЕ ОБОГАЩЕНИЕ: Если lead_id еще не найден, ищем активные сделки контакта
                                if not call_record.get("lead_id"):
                                    embedded = contact_info.get("_embedded", {})
                                    leads_from_contact = embedded.get("leads", [])
                                    if leads_from_contact and len(leads_from_contact) > 0:
                                        # Берем первую активную сделку контакта
                                        first_lead = leads_from_contact[0]
                                        lead_id_from_contact = first_lead.get("id")
                                        if lead_id_from_contact:
                                            call_record["lead_id"] = lead_id_from_contact
                                            logger.info(f"✅ [Enrichment] lead_id={lead_id_from_contact} найден через активные сделки контакта")
                        except Exception as contact_exc:
                            logger.error(f"[Enrichment] Ошибка при получении имени контакта {entity_id}: {contact_exc}")
                        # --- КОНЕЦ БЛОКА ОБОГАЩЕНИЯ ---

                        details_found = True
                        logger.debug(f"Найдены детали звонка: duration={call_record['duration']}, phone={call_record['phone']}")
            except Exception as e:
                logger.error(f"Ошибка при получении деталей звонка для контакта {entity_id}: {str(e)}")
                
        # Вариант 2: Если это сделка, получаем звонки через get_call_links_from_lead
        elif entity_type == "lead" and entity_id and isinstance(entity_id, int) and not details_found:
            try:
                # Получаем детали звонков для сделки
                logger.debug(f"Запрос звонков для сделки {entity_id}")
                call_links = await client.get_call_links_from_lead(entity_id)
                
                # Если нашли звонки, ищем соответствующий данному событию
                if call_links:
                    logger.debug(f"Найдено {len(call_links)} звонков для сделки {entity_id}")
                    
                    # Фильтруем звонки по времени (+-10 минут от времени события)
                    time_window = 600  # 10 минут
                    matching_calls = []
                    
                    for call_link in call_links:
                        call_created_at = call_link.get("note", {}).get("created_at", 0)
                        
                        # Проверяем, что звонок примерно совпадает по времени с событием
                        if abs(call_created_at - created_at) <= time_window:
                            matching_calls.append(call_link)
                    
                    # Используем первый найденный подходящий звонок
                    if matching_calls:
                        # Берем первый совпадающий звонок
                        matching_call = matching_calls[0]
                        note = matching_call.get("note", {})
                        params = note.get("params", {})
                        
                        # Заполняем детальную информацию о звонке
                        call_record["note_id"] = matching_call.get("note_id") or event_id
                        call_record["call_link"] = matching_call.get("call_link", "")
                        
                        # Длительность звонка
                        if "duration" in params:
                            duration = params.get("duration", 0)
                            call_record["duration"] = duration
                            minutes = duration // 60
                            seconds = duration % 60
                            call_record["duration_formatted"] = f"{minutes}:{seconds:02d}"

                        # Получаем ID сделки из заметки
                        lead_from_note = note.get("lead", {})
                        lead_id_from_note = lead_from_note.get("id")

                        # Если у нас есть ID сделки, получаем полную информацию о ней
                        if lead_id_from_note:
                            try:
                                # Запрашиваем полную информацию о сделке
                                logger.info(f"🔍 Запрос полной информации для сделки ID={lead_id_from_note}")
                                lead_info = await client.get_lead(lead_id_from_note)
                                
                                logger.info(f"🔍 client.get_lead вернул: type={type(lead_info)}, value={lead_info}")
                                
                                if lead_info:
                                    logger.info(f"✅ Полная информация для сделки ID={lead_id_from_note} получена.")
                                    # НЕ перезаписываем lead_id если новое значение None
                                    new_lead_id = lead_info.get("id")
                                    logger.info(f"🔍 lead_info.get('id') вернул: {new_lead_id}, текущий lead_id в call_record: {call_record.get('lead_id')}")
                                    
                                    if new_lead_id:
                                        call_record["lead_id"] = new_lead_id
                                        logger.info(f"✅ lead_id обновлен на: {new_lead_id}")
                                    else:
                                        logger.warning(f"⚠️ lead_info.get('id') вернул None, оставляем текущий lead_id={call_record.get('lead_id')}")
                                    call_record["lead_name"] = lead_info.get("name", "")

                                    # Извлекаем кастомные поля
                                    administrator = get_custom_field_value_by_name(lead_info, "administrator")
                                    source = get_custom_field_value_by_name(lead_info, "source")
                                    processing_speed_str = get_custom_field_value_by_name(lead_info, "processing_speed")

                                    if administrator:
                                        call_record["administrator"] = administrator
                                    if source:
                                        call_record["source"] = source
                                    if processing_speed_str:
                                        call_record["processing_speed_str"] = processing_speed_str
                                        call_record["processing_speed"] = convert_processing_speed_to_minutes(processing_speed_str)

                                    # Получаем контакт, связанный со сделкой, для актуализации имени
                                    try:
                                        contact_from_lead = await client.get_contact_from_lead(lead_id_from_note)
                                        if contact_from_lead:
                                            call_record["contact_name"] = contact_from_lead.get("name", call_record["contact_name"])
                                            logger.debug(f"Имя контакта обновлено на '{call_record['contact_name']}' из сделки.")
                                    except Exception as contact_exc:
                                        logger.warning(f"Не удалось получить контакт из сделки {lead_id_from_note}: {contact_exc}")

                                else:
                                     logger.warning(f"⚠️ Не удалось получить полную информацию для сделки ID={lead_id_from_note}")

                            except Exception as lead_exc:
                                logger.error(f"Ошибка при запросе полной информации о сделке {lead_id_from_note}: {lead_exc}")
                        else:
                            logger.warning("В заметке о звонке нет информации о связанной сделке.")
                        
                        # Телефон
                        if "phone" in params:
                            call_record["phone"] = params.get("phone", "Неизвестно")
                        
                        # ГАРАНТИРУЕМ: если это событие сделки, lead_id всегда = entity_id
                        if not call_record.get("lead_id"):
                            call_record["lead_id"] = entity_id
                            logger.debug(f"lead_id установлен напрямую из entity_id сделки: {entity_id}")
                        
                        details_found = True
                        logger.debug(f"Найдены детали звонка через сделку: duration={call_record['duration']}, phone={call_record['phone']}, lead_id={call_record['lead_id']}")
            except Exception as e:
                logger.error(f"Ошибка при получении деталей звонка для сделки {entity_id}: {str(e)}")
                # Даже при ошибке гарантируем lead_id для событий сделок
                if entity_type == "lead" and not call_record.get("lead_id"):
                    call_record["lead_id"] = entity_id
                    logger.debug(f"lead_id установлен при ошибке для сделки: {entity_id}")
        
        # Если детали не найдены, но мы можем попытаться получить информацию напрямую из заметки события
        if not details_found and event_type in ["incoming_call", "outgoing_call"]:
            try:
                # Если у нас есть сведения о value_after, используем их
                if "value_after" in event and isinstance(event["value_after"], dict):
                    value = event["value_after"]
                    
                    # Длительность звонка
                    if "duration" in value:
                        duration = value.get("duration", 0)
                        call_record["duration"] = duration
                        
                        # Форматируем длительность
                        minutes = duration // 60
                        seconds = duration % 60
                        call_record["duration_formatted"] = f"{minutes}:{seconds:02d}"
                    
                    # Телефон
                    if "phone" in value:
                        call_record["phone"] = value.get("phone", "Неизвестно")
                        
                    # Ссылка на запись
                    if "link" in value:
                        call_record["call_link"] = value.get("link", "")
                        
                    details_found = True
                    logger.debug(f"Найдены детали звонка из value_after: duration={call_record['duration']}, phone={call_record['phone']}")
            except Exception as e:
                logger.error(f"Ошибка при извлечении данных из value_after: {str(e)}")
        
        # ФИНАЛЬНАЯ ПРОВЕРКА №1: если это была сделка, гарантируем lead_id
        if entity_type == "lead" and not call_record.get("lead_id"):
            call_record["lead_id"] = entity_id
            logger.warning(f"⚠️ lead_id не был установлен ранее, установлен в конце для сделки: {entity_id}")
        
        # ФИНАЛЬНАЯ ПРОВЕРКА №2: если это контакт без lead_id, делаем последнюю попытку найти сделку
        if entity_type == "contact" and not call_record.get("lead_id") and entity_id:
            try:
                logger.info(f"🔍 [Final Fallback] Попытка найти lead_id для контакта {entity_id}")
                # ИСПРАВЛЕНО: используем правильный метод с параметром with=leads
                contact_data, status = await client.contacts.request(
                    "get", f"contacts/{entity_id}", params={"with": "leads"}
                )
                if status == 200 and isinstance(contact_data, dict):
                    embedded = contact_data.get("_embedded", {})
                    leads_from_contact = embedded.get("leads", [])
                    if leads_from_contact and len(leads_from_contact) > 0:
                        # Сортируем сделки по дате обновления (самая свежая первая)
                        def lead_timestamp(x):
                            return x.get("updated_at") or x.get("created_at") or 0
                        leads_sorted = sorted(leads_from_contact, key=lead_timestamp, reverse=True)
                        first_lead = leads_sorted[0]
                        lead_id_from_contact = first_lead.get("id")
                        if lead_id_from_contact:
                            call_record["lead_id"] = lead_id_from_contact
                            call_record["lead_name"] = first_lead.get("name", "")
                            logger.info(f"✅ [Final Fallback] lead_id={lead_id_from_contact} найден для контакта {entity_id}")
                            
                            # ОБОГАЩЕНИЕ: Получаем кастомные поля из найденной сделки
                            try:
                                logger.info(f"🔍 [Final Fallback] Обогащаем кастомными полями из сделки {lead_id_from_contact}")
                                lead_info = await client.get_lead(lead_id_from_contact)
                                if lead_info and isinstance(lead_info, dict):
                                    administrator = get_custom_field_value_by_name(lead_info, "administrator")
                                    source = get_custom_field_value_by_name(lead_info, "source")
                                    processing_speed_str = get_custom_field_value_by_name(lead_info, "processing_speed")
                                    
                                    if administrator:
                                        call_record["administrator"] = administrator
                                        logger.debug(f"   ✅ administrator: {administrator}")
                                    if source:
                                        call_record["source"] = source
                                        logger.debug(f"   ✅ source: {source}")
                                    if processing_speed_str:
                                        call_record["processing_speed_str"] = processing_speed_str
                                        call_record["processing_speed"] = convert_processing_speed_to_minutes(processing_speed_str)
                                        logger.debug(f"   ✅ processing_speed: {processing_speed_str}")
                            except Exception as enrich_exc:
                                logger.warning(f"⚠️ [Final Fallback] Не удалось обогатить кастомными полями: {enrich_exc}")
                    else:
                        logger.warning(f"⚠️ [Final Fallback] У контакта {entity_id} нет активных сделок")
                else:
                    logger.warning(f"⚠️ [Final Fallback] Не удалось получить данные контакта {entity_id}, status={status}")
            except Exception as fallback_exc:
                logger.error(f"❌ [Final Fallback] Ошибка при поиске сделки для контакта {entity_id}: {fallback_exc}")
        
        # УНИВЕРСАЛЬНОЕ ОБОГАЩЕНИЕ: Если есть lead_id, но нет кастомных полей - обогащаем
        lead_id = call_record.get("lead_id")
        if lead_id:
            # Проверяем, нужно ли обогащение
            needs_enrichment = (
                not call_record.get("administrator") or call_record.get("administrator") == "Неизвестный" or
                not call_record.get("source") or call_record.get("source") == "Неопределенный" or
                "processing_speed" not in call_record or "processing_speed_str" not in call_record
            )
            
            if needs_enrichment:
                try:
                    logger.info(f"🔍 [Universal Enrichment] Обогащаем кастомными полями для lead_id={lead_id}")
                    lead_info = await client.get_lead(int(lead_id))
                    if lead_info and isinstance(lead_info, dict):
                        administrator = get_custom_field_value_by_name(lead_info, "administrator")
                        source = get_custom_field_value_by_name(lead_info, "source")
                        processing_speed_str = get_custom_field_value_by_name(lead_info, "processing_speed")
                        
                        if administrator:
                            call_record["administrator"] = administrator
                        if source:
                            call_record["source"] = source
                        if processing_speed_str:
                            call_record["processing_speed_str"] = processing_speed_str
                            call_record["processing_speed"] = convert_processing_speed_to_minutes(processing_speed_str)
                        
                        logger.debug(f"✅ [Universal Enrichment] Обогащено: admin={administrator}, source={source}, speed={processing_speed_str}")
                except Exception as enrich_exc:
                    logger.warning(f"⚠️ [Universal Enrichment] Не удалось обогатить для lead_id={lead_id}: {enrich_exc}")
        
        # КОПИРУЕМ КОНВЕРСИЮ ИЗ EVENT: Если event был обогащён конверсией - переносим в call_record
        if event.get("conversion") is not None:
            # Создаём структуру metrics если её нет
            if "metrics" not in call_record:
                call_record["metrics"] = {}
            call_record["metrics"]["conversion"] = event.get("conversion")
            if event.get("conversion_type"):
                call_record["conversion_type"] = event.get("conversion_type")
            logger.info(f"✅ [Conversion Copy] event_id={event.get('id')}, lead_id={event.get('lead_id')}, conversion={event.get('conversion')}, type={event.get('conversion_type')}")
        else:
            logger.debug(f"⚠️ [Conversion Copy] event_id={event.get('id')} НЕ имеет поля conversion - пропускаем")
                
        return call_record
    except Exception as e:
        logger.error(f"Общая ошибка при получении деталей звонка: {str(e)}")
        return None
