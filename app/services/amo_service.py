import asyncio
import traceback
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List, Tuple
import logging

# Добавляем путь к корню проекта для импорта
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from app.services.amo_credentials import get_full_amo_credentials, MONGODB_URI, MONGODB_NAME

from motor.motor_asyncio import AsyncIOMotorClient

from .mongodb_service import mongodb_service

# Настройка логгера
logger = logging.getLogger(__name__)

from mlab_amo_async.amocrm_client import AsyncAmoCRMClient

async def get_custom_field_value(lead: Dict[str, Any], field_id: int) -> Optional[str]:
    """
    Извлекает значение кастомного поля из сделки по идентификатору поля.
    
    Args:
        lead: Сделка из AmoCRM
        field_id: ID кастомного поля
    
    Returns:
        Значение поля или None, если поле не найдено
    """
    if not lead.get("custom_fields_values"):
        return None
    
    for field in lead["custom_fields_values"]:
        if field.get("field_id") == field_id:
            values = field.get("values", [])
            if values and len(values) > 0:
                return values[0].get("value")
    return None

async def get_today_leads_and_save_calls(client_id: Optional[str] = None) -> Tuple[int, int]:
    """
    Получает сделки за текущий день из AmoCRM и сохраняет звонки в MongoDB.
    
    Args:
        client_id: ID клиента AmoCRM (опционально)
    
    Returns:
        Кортеж (количество обработанных сделок, количество сохраненных звонков)
    """
    try:
        logger.info("Получение данных авторизации...")
        
        # Импортируем здесь, чтобы избежать циклических импортов
        from mlab_amo_async.amocrm_client import AsyncAmoCRMClient
        
        credentials = await get_full_amo_credentials(client_id=client_id)
        logger.info(f"Получены данные для client_id: {credentials['client_id']}, subdomain: {credentials['subdomain']}")
        
        # Используем существующее подключение к MongoDB из сервиса
        calls_collection = mongodb_service.db["calls"]
        
        # Создаем экземпляр API amoCRM
        amo = AsyncAmoCRMClient(
            client_id=credentials["client_id"],
            client_secret=credentials["client_secret"],
            subdomain=credentials["subdomain"],
            redirect_url=credentials["redirect_url"],
            mongo_uri=MONGODB_URI,
            db_name=MONGODB_NAME
        )
        logger.info("Клиент amoCRM успешно создан")
        
        # Расчет временных меток для текущего дня
        now = datetime.now()
        today_start = int(datetime(now.year, now.month, now.day, 0, 0, 0, tzinfo=timezone.utc).timestamp())
        today_end = int(datetime(now.year, now.month, now.day, 23, 59, 59, tzinfo=timezone.utc).timestamp())
        
        logger.info(f"Получение сделок за текущий день ({now.strftime('%d.%m.%Y')})")
        logger.info(f"Временной диапазон: {today_start} - {today_end}")
        
        # Получаем сделки за текущий день
        all_leads = []
        page = 1
        
        while True:
            # Параметры фильтрации для сделок за текущий день
            filter_params = {
                "filter[created_at][from]": today_start,
                "filter[created_at][to]": today_end,
                "page": page,
                "limit": 50  # Увеличиваем лимит для снижения количества запросов
            }
            
            leads_response, leads_status = await amo.leads.request(
                "get", "leads", params=filter_params
            )
            
            if leads_status != 200:
                logger.error(f"Ошибка при получении сделок, статус: {leads_status}")
                break
            
            # Извлекаем сделки из ответа
            if "_embedded" in leads_response and "leads" in leads_response["_embedded"]:
                leads = leads_response["_embedded"]["leads"]
                if not leads:
                    break
                
                all_leads.extend(leads)
                logger.info(f"Получено {len(leads)} сделок на странице {page}")
                
                # Проверяем, есть ли следующая страница
                if "_links" in leads_response and "next" in leads_response["_links"]:
                    page += 1
                else:
                    break
            else:
                break
        
        logger.info(f"Всего получено {len(all_leads)} сделок за текущий день")
        
        # Счетчики для статистики
        total_calls_saved = 0
        leads_with_calls = 0
        
        # Обрабатываем каждую сделку
        for lead in all_leads:
            lead_id = lead.get("id")
            
            # Получаем детальную информацию о сделке
            lead_info = await amo.get_lead(lead_id)
            
            # Извлекаем нужные поля
            administrator = await get_custom_field_value(lead_info, 908101)
            source = await get_custom_field_value(lead_info, 908783)
            processing_speed = await get_custom_field_value(lead_info, 908013)
            
            # Получаем контакт, связанный со сделкой
            contact = await amo.get_contact_from_lead(lead_id)
            
            if contact:
                contact_id = contact.get("id")
                contact_name = contact.get("name", "Без имени")
                
                # Получаем звонки контакта
                call_links = await amo.get_call_links(contact_id)
                
                if call_links:
                    logger.info(f"Найдено {len(call_links)} звонков для сделки #{lead_id}, контакт #{contact_id}")
                    leads_with_calls += 1
                    calls_saved_for_lead = 0
                    
                    for call_info in call_links:
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
                            "administrator": administrator or "Не указан",
                            "source": source or "Не указан",
                            "processing_speed": processing_speed,
                            "call_direction": call_direction,
                            "duration": duration,
                            "duration_formatted": duration_formatted,
                            "phone": params.get("phone", "Неизвестно"),
                            "call_link": call_info.get("call_link", ""),
                            "created_at": created_at,
                            "created_date": created_date.strftime("%Y-%m-%d %H:%M:%S"),
                            "recorded_at": datetime.now(),
                            "amocrm_user_id": lead_info.get("responsible_user_id"),
                            "responsible_user_id": lead_info.get("responsible_user_id"),
                            "created_by_user_id": lead_info.get("created_by") or 0
                        }
                        
                        # Проверяем, существует ли уже запись с таким note_id
                        existing_call = await calls_collection.find_one({"note_id": note_id})
                        
                        if existing_call:
                            # Обновляем существующую запись
                            update_result = await calls_collection.update_one(
                                {"note_id": note_id},
                                {"$set": call_doc}
                            )
                            logger.info(f"Обновлена запись звонка с note_id={note_id}")
                        else:
                            # Вставляем новую запись
                            insert_result = await calls_collection.insert_one(call_doc)
                            logger.info(f"Сохранен новый звонок с note_id={note_id}")
                            calls_saved_for_lead += 1
                            total_calls_saved += 1
                    
                    logger.info(f"Для сделки #{lead_id} сохранено {calls_saved_for_lead} звонков")
        
        logger.info("\nСтатистика:")
        logger.info(f"Всего обработано сделок: {len(all_leads)}")
        logger.info(f"Сделок с звонками: {leads_with_calls}")
        logger.info(f"Всего сохранено звонков: {total_calls_saved}")
        
        # Закрываем соединение
        await amo.close()
        logger.info("\nСоединения закрыты")
        
        return len(all_leads), total_calls_saved
        
    except Exception as e:
        logger.error(f"Ошибка: {str(e)}")
        logger.error(traceback.format_exc())
        return 0, 0

async def get_leads_and_save_calls_by_date(target_date: Optional[str] = None, client_id: Optional[str] = None) -> Tuple[int, int]:
    """
    Получает сделки за указанную дату из AmoCRM и сохраняет звонки в MongoDB.
    
    Args:
        target_date: Дата в формате YYYY-MM-DD (опционально, по умолчанию - текущая дата)
        client_id: ID клиента AmoCRM (опционально)
    
    Returns:
        Кортеж (количество обработанных сделок, количество сохраненных звонков)
    """
    try:
        logger.info("Получение данных авторизации...")
        
        # Импортируем здесь, чтобы избежать циклических импортов
        from mlab_amo_async.amocrm_client import AsyncAmoCRMClient
        
        # Определяем дату
        if target_date:
            # Пробуем разные форматы даты
            date_formats = ["%Y-%m-%d", "%Y.%m.%d", "%d.%m.%Y", "%d-%m-%Y"]
            date_obj = None
            
            logger.info(f"Пытаемся распарсить дату: {target_date}")
            
            for date_format in date_formats:
                try:
                    date_obj = datetime.strptime(target_date, date_format)
                    logger.info(f"Успешно распарсили дату с форматом {date_format}: {date_obj}")
                    break
                except ValueError:
                    continue
            
            if not date_obj:
                logger.error(f"Не удалось распарсить дату: {target_date}, используется текущая дата")
                date_obj = datetime.now()
        else:
            logger.info("Дата не указана, используется текущая дата")
            date_obj = datetime.now()
        
        logger.info(f"Используемая дата: {date_obj.strftime('%Y-%m-%d')}")
        
        # Получаем учетные данные AmoCRM
        credentials = await get_full_amo_credentials(client_id=client_id)
        logger.info(f"Получены данные для client_id: {credentials['client_id']}, subdomain: {credentials['subdomain']}")
        
        # Используем существующее подключение к MongoDB из сервиса
        calls_collection = mongodb_service.db["calls"]
        
        # Создаем экземпляр API amoCRM
        amo = AsyncAmoCRMClient(
            client_id=credentials["client_id"],
            client_secret=credentials["client_secret"],
            subdomain=credentials["subdomain"],
            redirect_url=credentials["redirect_url"],
            mongo_uri=MONGODB_URI,
            db_name=MONGODB_NAME
        )
        logger.info("Клиент amoCRM успешно создан")
        
        # Расчет временных меток для указанной даты
        date_start = int(datetime(date_obj.year, date_obj.month, date_obj.day, 0, 0, 0, tzinfo=timezone.utc).timestamp())
        date_end = int(datetime(date_obj.year, date_obj.month, date_obj.day, 23, 59, 59, tzinfo=timezone.utc).timestamp())
        
        logger.info(f"Получение сделок за дату: {date_obj.strftime('%d.%m.%Y')}")
        logger.info(f"Временной диапазон: {date_start} ({datetime.fromtimestamp(date_start)}) - {date_end} ({datetime.fromtimestamp(date_end)})")
        
        # Получаем сделки за указанную дату
        all_leads = []
        page = 1
        
        while True:
            # Параметры фильтрации для сделок за указанную дату
            filter_params = {
                "filter[created_at][from]": date_start,
                "filter[created_at][to]": date_end,
                "page": page,
                "limit": 50  # Увеличиваем лимит для снижения количества запросов
            }
            
            logger.info(f"Запрос сделок: page={page}, params={filter_params}")
            leads_response, leads_status = await amo.leads.request(
                "get", "leads", params=filter_params
            )
            
            if leads_status != 200:
                logger.error(f"Ошибка при получении сделок, статус: {leads_status}, ответ: {leads_response}")
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
        
        logger.info(f"Всего получено {len(all_leads)} сделок за выбранную дату")
        
        # Счетчики для статистики
        total_calls_saved = 0
        leads_with_calls = 0
        
        # Обрабатываем каждую сделку
        for lead_index, lead in enumerate(all_leads):
            lead_id = lead.get("id")
            logger.info(f"Обрабатываем сделку #{lead_index+1}/{len(all_leads)}, id={lead_id}")
            
            # Получаем детальную информацию о сделке
            lead_info = await amo.get_lead(lead_id)
            
            # Извлекаем нужные поля
            administrator = None
            source = None
            processing_speed = None
            
            if lead_info.get("custom_fields_values"):
                for field in lead_info.get("custom_fields_values", []):
                    field_id = field.get("field_id")
                    values = field.get("values", [])
                    
                    if values and len(values) > 0:
                        if field_id == 908101:  # Администратор
                            administrator = values[0].get("value")
                        elif field_id == 908783:  # Источник
                            source = values[0].get("value")
                        elif field_id == 908013:  # Скорость обработки
                            processing_speed = values[0].get("value")
            
            logger.info(f"Информация о сделке: administrator={administrator}, source={source}")
            
            # Получаем контакт, связанный со сделкой
            contact = await amo.get_contact_from_lead(lead_id)
            
            if contact:
                contact_id = contact.get("id")
                contact_name = contact.get("name", "Без имени")
                logger.info(f"Найден контакт: id={contact_id}, name={contact_name}")
                
                # Получаем звонки контакта
                call_links = await amo.get_call_links(contact_id)
                
                if call_links:
                    logger.info(f"Найдено {len(call_links)} звонков для сделки #{lead_id}, контакт #{contact_id}")
                    leads_with_calls += 1
                    calls_saved_for_lead = 0
                    
                    for call_info in call_links:
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
                            "administrator": administrator or "Не указан",
                            "source": source or "Не указан",
                            "processing_speed": processing_speed,
                            "call_direction": call_direction,
                            "duration": duration,
                            "duration_formatted": duration_formatted,
                            "phone": params.get("phone", "Неизвестно"),
                            "call_link": call_info.get("call_link", ""),
                            "created_at": created_at,
                            "created_date": created_date.strftime("%Y-%m-%d %H:%M:%S"),
                            "recorded_at": datetime.now(),
                            "amocrm_user_id": lead_info.get("responsible_user_id"),
                            "responsible_user_id": lead_info.get("responsible_user_id"),
                            "created_by_user_id": lead_info.get("created_by") or 0
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
                            calls_saved_for_lead += 1
                            total_calls_saved += 1
                    
                    logger.info(f"Для сделки #{lead_id} сохранено {calls_saved_for_lead} звонков")
                else:
                    logger.info(f"Для контакта #{contact_id} не найдено звонков")
            else:
                logger.info(f"Для сделки #{lead_id} не найден связанный контакт")
        
        logger.info("\nСтатистика:")
        logger.info(f"Всего обработано сделок: {len(all_leads)}")
        logger.info(f"Сделок с звонками: {leads_with_calls}")
        logger.info(f"Всего сохранено звонков: {total_calls_saved}")
        
        # Закрываем соединение
        await amo.close()
        logger.info("\nСоединения закрыты")
        
        return len(all_leads), total_calls_saved
        
    except Exception as e:
        logger.error(f"Ошибка: {str(e)}")
        logger.error(traceback.format_exc())
        return 0, 0




# Для ручного запуска через python -m
async def manual_run():
    """Ручной запуск синхронизации звонков с AmoCRM"""
    import sys
    client_id = sys.argv[1] if len(sys.argv) > 1 else None
    logger.info(f"Используемый client_id: {client_id or 'не указан (будет использован последний токен)'}")
    
    await get_today_leads_and_save_calls(client_id)

if __name__ == "__main__":
    asyncio.run(manual_run()) 