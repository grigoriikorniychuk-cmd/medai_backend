import asyncio
from datetime import datetime, timezone, timedelta
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

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
            resp, status = await amo_client.request("get", "api/v4/events", params=events_params)
            
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
                if page > 30:  # Больше страниц, чтобы вернуть все ~145 звонков
                    logger.warning(f"[{task_id}] Ограничение по страницам events: {page} страниц")
                    break
            else:
                break
        
        logger.info(f"[{task_id}] Получено {len(all_events)} событий звонков всего.")
        
        # Для первых элементов выводим пример структуры
        if len(all_events) > 0:
            logger.info(f"[{task_id}] Пример структуры события: {all_events[0]}")
        
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
        
        # Вывод статистики
        calls_from_leads = [call for call in calls_from_events if "lead_id" in call]
        calls_from_contacts = [call for call in calls_from_events if "contact_id" in call and "lead_id" not in call]
        
        logger.info(f"[{task_id}] Звонки из API events: из сделок {len(calls_from_leads)}, "
                   f"из контактов {len(calls_from_contacts)}, всего {len(calls_from_events)}")
        
    except Exception as e:
        logger.error(f"[{task_id}] Ошибка при получении звонков через API events: {e}")
        calls_from_events = []
    
    return calls_from_events
