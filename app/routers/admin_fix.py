import asyncio
from datetime import datetime, timezone, timedelta
import logging
from typing import List, Dict, Any, Optional
import os
import json
import uuid

# Настройка логирования
logger = logging.getLogger(__name__)

async def _perform_amocrm_check_task(
    task_id: str,
    client_id: str,
    start_date_str: str,
    end_date_str: str
):
    """Фоновая задача для проверки данных AmoCRM с использованием API /api/v4/events"""
    start_time = datetime.now()
    try:
        # Импорт сервисов и моделей здесь для избежания циклических импортов
        from ..models.amocrm import LeadsByDateRequest
        from ..routers.amocrm import get_leads_by_date
        from ..services.amocrm.client import AsyncAmoCRMClient
        from ..services.amocrm.client import get_full_amo_credentials
        from ..utils.dates import convert_date_string
        from ..utils.mongo import get_mongo_client

        # База данных MongoDB
        MONGO_URI = os.getenv("MONGO_URI")
        DB_NAME = os.getenv("DB_NAME")

        # Преобразуем строковые даты в объекты даты
        start_date_obj = convert_date_string(start_date_str)
        end_date_obj = convert_date_string(end_date_str)
        logger.info(f"[{task_id}] Анализ AmoCRM для {client_id} за {start_date_obj.strftime('%Y-%m-%d')} - {end_date_obj.strftime('%Y-%m-%d')}")

        # Инициализируем клиент AmoCRM
        credentials = await get_full_amo_credentials(client_id=client_id)
        amo_client = AsyncAmoCRMClient(
            client_id=credentials["client_id"], client_secret=credentials["client_secret"],
            subdomain=credentials["subdomain"], redirect_url=credentials["redirect_url"],
            mongo_uri=MONGO_URI, db_name=DB_NAME
        )
        
        # Получаем сделки по дням для отображения в отчете
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
        calls_from_events = await get_calls_via_events(amo_client, task_id, start_date_obj, end_date_obj)
        
        # Разделяем звонки из событий на сделки и контакты
        calls_from_leads = [call for call in calls_from_events if "lead_id" in call]
        calls_from_contacts = [call for call in calls_from_events if "contact_id" in call and "lead_id" not in call]
        
        calls_from_leads_count = len(calls_from_leads)
        calls_from_contacts_count = len(calls_from_contacts)
        
        logger.info(f"[{task_id}] Получено звонков через API events: из сделок {calls_from_leads_count}, из контактов {calls_from_contacts_count}, всего {len(calls_from_events)}")
        
        # Используем все звонки из API events
        all_calls = calls_from_events
        
        # Анализ звонков для отчета
        total_calls = len(all_calls)
        logger.info(f"[{task_id}] Всего найдено уникальных звонков: {total_calls}")

        # Подсчет статистики по звонкам
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

        # Подсчет дубликатов
        duplicates_count = sum(len(calls) - 1 for calls in duplicates_by_duration_contact.values() if len(calls) > 1)
        unique_calls = len(advanced_dupes)

        # Формируем отчет
        leads_by_date_str = "\n  ".join([f"{d['date']}: {d['total']} сделок" for d in all_leads_by_date])
        zero_p = f"{zero_duration_calls/total_calls*100:.1f}%" if total_calls > 0 else "0%"
        dupes_p = f"{duplicates_count/total_calls*100:.1f}%" if total_calls > 0 else "0%"
        stats_report = f"""СТАТИСТИКА AMO
---
Период: {start_date_obj.strftime("%d.%m.%Y")} - {end_date_obj.strftime("%d.%m.%Y")}
Всего сделок: {total_leads}
Звонков из сделок: {calls_from_leads_count}
Звонков из контактов: {calls_from_contacts_count}
Всего звонков (уникальных ID): {total_calls}
---
Сделки по дням:
  {leads_by_date_str}
---
Анализ звонков:
Нулевых: {zero_duration_calls} ({zero_p})
Дублей (duration+contact): {duplicates_count} ({dupes_p})
Уникальных (duration+contact+created): {unique_calls}
---"""
        logger.info(stats_report)

        # Сохраняем результат
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

    execution_time = (datetime.now() - start_time).total_seconds()
    logger.info(f"[{task_id}] Задача выполнена за {execution_time:.2f} сек.")


async def get_calls_via_events(amo_client, task_id: str, start_date_obj, end_date_obj) -> List[Dict[str, Any]]:
    """
    Получение звонков через API /api/v4/events (по рекомендации с форума AmoCRM)
    """
    logger.info(f"[{task_id}] Получение звонков через API events...")
    calls_from_events = []
    
    try:
        # Используем уже существующие переменные даты
        start_dt_utc = datetime(start_date_obj.year, start_date_obj.month, start_date_obj.day, tzinfo=timezone.utc)
        end_dt_utc = datetime(end_date_obj.year, end_date_obj.month, end_date_obj.day, 23, 59, 59, tzinfo=timezone.utc)
        
        # Получаем все события звонков с пагинацией через API /api/v4/events
        all_events = []
        page = 1
        
        # Запрашиваем звонки за период
        while True:
            # Параметры запроса к API events
            events_params = {
                "limit": 250,
                "page": page,
                "filter[created_at][from]": int(start_dt_utc.timestamp()),
                "filter[created_at][to]": int(end_dt_utc.timestamp()),
                "filter[type]": "outgoing_call,incoming_call"  # Типы событий звонков
            }
            
            # Выполняем запрос к API events
            try:
                resp, status = await amo_client.request("get", "api/v4/events", params=events_params)
            except Exception as e:
                logger.error(f"[{task_id}] Ошибка API events запроса: {e}")
                break
                
            if status != 200:
                logger.warning(f"[{task_id}] API events вернул статус {status}: {resp}")
                break
                
            # Обрабатываем ответ
            if "_embedded" in resp and "events" in resp["_embedded"]:
                events = resp["_embedded"]["events"]
                all_events.extend(events)
                logger.info(f"[{task_id}] Страница {page}: получено {len(events)} событий звонков")
                
                if "_links" not in resp or "next" not in resp["_links"]:
                    break
                page += 1
                
                # Ограничение по страницам
                if page > 50:  # Больше страниц, чтобы вернуть все ~145 звонков
                    logger.warning(f"[{task_id}] Ограничение по страницам events: {page} страниц")
                    break
            else:
                break
        
        logger.info(f"[{task_id}] Получено {len(all_events)} событий звонков всего.")
        
        # Для первых элементов выводим пример структуры
        if len(all_events) > 0:
            logger.info(f"[{task_id}] Пример структуры события: {all_events[0]}")
        
        # Анализируем все типы событий
        event_types = {}
        entity_types = {}
        for event in all_events:
            event_type = event.get("type")
            if event_type not in event_types:
                event_types[event_type] = 0
            event_types[event_type] += 1
            
            entity_type = event.get("entity_type")
            if entity_type not in entity_types:
                entity_types[entity_type] = 0
            entity_types[entity_type] += 1
        
        logger.info(f"[{task_id}] Типы событий: {event_types}")
        logger.info(f"[{task_id}] Типы сущностей: {entity_types}")
        
        # Обрабатываем каждое событие и преобразуем в формат звонка
        for event in all_events:
            event_type = event.get("type")
            # Получаем связанную сделку или контакт
            entity_type = event.get("entity_type")
            entity_id = event.get("entity_id")
            
            # Создаем формат звонка, совместимый с предыдущим кодом
            call = {
                "id": event.get("id"),
                "created_at": event.get("created_at"),
                "updated_at": event.get("created_at"),
                "type": event_type,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "params": event.get("value_after", {})  # Вероятно здесь хранятся параметры звонка
            }
            
            # Добавляем идентификаторы сделки/контакта
            if entity_type == "lead":
                call["lead_id"] = entity_id
            elif entity_type == "contact":
                call["contact_id"] = entity_id
            
            calls_from_events.append(call)
        
    except Exception as e:
        logger.error(f"[{task_id}] Ошибка при получении звонков через API events: {e}")
        calls_from_events = []
    
    return calls_from_events
