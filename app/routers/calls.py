import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query, Response, status
from fastapi.responses import FileResponse

from ..services.call_admin_report_service import call_admin_report_service
from ..services.mongodb_service import mongodb_service, serialize_mongodb_doc
import logging
import sys
import traceback
from datetime import datetime, timezone
import os
import json
import aiohttp
import aiofiles
import re
from pathlib import Path
from bson.objectid import ObjectId
import requests
import asyncio

from ..services.transcription_service import transcribe_and_save

# Добавляем пути из настроек
from ..settings import TRANSCRIPTION_DIR, AUDIO_DIR

# Добавляем корневую директорию проекта в путь для импорта
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from app.services.amo_credentials import get_full_amo_credentials, MONGODB_URI, MONGODB_NAME
from motor.motor_asyncio import AsyncIOMotorClient

# Настройка логгера
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/calls", tags=["Звонки"])

# Функция для конвертации даты из различных форматов в объект datetime
def convert_date_string(date_str):
    if not date_str:
        return None
    
    # Пробуем разные форматы даты
    for fmt in ["%d.%m.%Y", "%Y-%m-%d"]:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    
    # Если не удалось распознать формат, логируем ошибку и возвращаем None
    logger.warning(f"Не удалось распознать формат даты: {date_str}")
    return None


# Функция для извлечения значения из custom_fields_values по field_id (прямо из test_amo.py)
def get_custom_field_value(lead, field_id):
    if not lead.get("custom_fields_values"):
        return None
    
    for field in lead["custom_fields_values"]:
        if field.get("field_id") == field_id:
            values = field.get("values", [])
            if values and len(values) > 0:
                return values[0].get("value")
    return None

# Функция для извлечения значения из custom_fields_values по field_name
def get_custom_field_value_by_name(lead, field_name):
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
    logger.info(f"Ищем поле: {field_name} по названию: {search_name}")
    
    # Логируем все доступные кастомные поля для отладки
    field_names = [field.get("field_name") for field in lead["custom_fields_values"]]
    logger.info(f"Доступные поля в сделке: {field_names}")
    
    # Приводим искомое имя к нижнему регистру для регистронезависимого сравнения
    search_name_lower = search_name.lower()
    
    for field in lead["custom_fields_values"]:
        field_name_value = field.get("field_name", "")
        # Сравниваем без учета регистра
        if field_name_value and field_name_value.lower() == search_name_lower:
            values = field.get("values", [])
            if values and len(values) > 0:
                value = values[0].get("value")
                logger.info(f"Найдено значение для {field_name_value}: {value}")
                return value
    
    logger.warning(f"Поле {search_name} не найдено в кастомных полях сделки")
    return None

# Добавим новую функцию для преобразования строкового значения processing_speed в числовое
def convert_processing_speed_to_minutes(speed_str):
    """
    Преобразует строковое значение скорости обработки в числовое значение в минутах.
    
    Args:
        speed_str: Строковое значение скорости обработки (например, "5-10 мин")
        
    Returns:
        Числовое значение в минутах
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
    
    # Если значение есть в маппинге, возвращаем соответствующее числовое значение
    if speed_str in processing_speed_mapping:
        return processing_speed_mapping[speed_str]
    
    # Если значение не найдено, возвращаем None или значение по умолчанию
    logger.warning(f"Неизвестное значение скорости обработки: {speed_str}")
    return None

@router.post("/sync-by-date")
async def sync_calls_by_date(
    date: Optional[str] = None,
    client_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Синхронизация звонков из AmoCRM по оригинальному алгоритму из test_amo.py
    
    Args:
        date: Дата в формате DD.MM.YYYY, YYYY-MM-DD или другом распознаваемом формате
        client_id: ID клиента AmoCRM (опционально)
    """
    try:
        # Прямой вызов кода из test_amo.py с адаптацией
        from mlab_amo_async.amocrm_client import AsyncAmoCRMClient

        logger.info("Получение данных авторизации...")
        
        credentials = await get_full_amo_credentials(client_id=client_id)
        logger.info(f"Получены данные для client_id: {credentials['client_id']}, subdomain: {credentials['subdomain']}")
        
        # Подключаемся к MongoDB
        mongo_client = AsyncIOMotorClient(MONGODB_URI)
        db = mongo_client[MONGODB_NAME]
        calls_collection = db.calls
        
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
        
        logger.info(f"Всего получено {len(all_leads)} сделок за выбранную дату")
        
        # Счетчики для статистики
        total_calls_saved = 0
        leads_with_calls = 0
        
        # Обрабатываем каждую сделку
        for idx, lead in enumerate(all_leads):
            lead_id = lead.get("id")
            logger.info(f"Обработка сделки {idx+1}/{len(all_leads)}, id: {lead_id}")
            
            # Получаем детальную информацию о сделке
            lead_info = await amo.get_lead(lead_id)
            
            # Извлекаем нужные поля - именно так, как в оригинальном коде
            administrator = get_custom_field_value_by_name(lead_info, "administrator")
            source = get_custom_field_value_by_name(lead_info, "source")
            processing_speed_str = get_custom_field_value_by_name(lead_info, "processing_speed")
            
            # Устанавливаем значения по умолчанию если поля пустые
            administrator = administrator if administrator else "Неизвестный"
            source = source if source else "Неопределенный"
            processing_speed_str = processing_speed_str if processing_speed_str else "0 мин"
            
            # Преобразуем строковое значение processing_speed в числовое (в минутах)
            processing_speed_minutes = convert_processing_speed_to_minutes(processing_speed_str)
            # Если функция вернула None (неизвестное значение), устанавливаем 0
            processing_speed_minutes = 0 if processing_speed_minutes is None else processing_speed_minutes
            
            logger.info(f"Сделка {lead_id}: administrator={administrator}, source={source}, processing_speed={processing_speed_str} -> {processing_speed_minutes} мин.")
            
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
                            "processing_speed": processing_speed_minutes,  # Сохраняем числовое значение
                            "processing_speed_str": processing_speed_str,  # Сохраняем также исходную строку для справки
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
                else:
                    logger.info(f"Для контакта {contact_id} не найдено звонков")
            else:
                logger.info(f"Для сделки {lead_id} не найден контакт")
        
        logger.info("\nСтатистика:")
        logger.info(f"Всего обработано сделок: {len(all_leads)}")
        logger.info(f"Сделок с звонками: {leads_with_calls}")
        logger.info(f"Всего сохранено звонков: {total_calls_saved}")
        
        # Закрываем соединения
        await amo.close()
        mongo_client.close()
        logger.info("\nСоединения закрыты")
        
        # Формируем ответ с полной статистикой
        return {
            "success": True,
            "message": f"Синхронизация звонков из AmoCRM выполнена: обработано {len(all_leads)} сделок, сохранено {total_calls_saved} звонков",
            "data": {
                "date": now.strftime('%Y-%m-%d'),
                "client_id": client_id,
                "leads_processed": len(all_leads),
                "calls_saved": total_calls_saved,
                "leads_with_calls": leads_with_calls
            }
        }
    except Exception as e:
        logger.error(f"Ошибка при синхронизации звонков: {str(e)}")
        traceback.print_exc()
        return {
            "success": False,
            "message": f"Ошибка при синхронизации звонков: {str(e)}",
            "data": None
        }

@router.get("/report")
async def generate_call_report(
    days_ago: int = Query(30, description="За сколько дней генерировать отчет"),
    filename: Optional[str] = Query(None, description="Имя файла отчета")
) -> Dict[str, Any]:
    """
    Генерирует отчет по звонкам администраторов.
    
    Args:
        days_ago: За сколько последних дней анализировать звонки
        filename: Название для файла отчета (опционально)
        
    Returns:
        Ответ с путем к созданному файлу отчета
    """
    try:
        # Если имя файла не указано, генерируем его на основе текущей даты
        if not filename:
            current_date = datetime.now().strftime("%Y-%m-%d")
            filename = f"call_admin_report_{current_date}.pdf"
            
        # Генерируем отчет
        report_path = await call_admin_report_service.generate_report(
            days_ago=days_ago,
            output_filename=filename
        )
        
        if not report_path:
            return {
                "success": False,
                "message": "Не удалось создать отчет",
                "data": {"days_ago": days_ago}
            }
            
        return {
            "success": True,
            "message": "Отчет успешно создан",
            "data": {"report_path": report_path, "days_ago": days_ago}
        }
    except Exception as e:
        logger.error(f"Ошибка при генерации отчета: {str(e)}")
        return {
            "success": False,
            "message": f"Ошибка при генерации отчета: {str(e)}",
            "data": None
        }

@router.get("/list")
async def list_calls(
    start_date: Optional[str] = Query(None, description="Начальная дата (DD.MM.YYYY или YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="Конечная дата (DD.MM.YYYY или YYYY-MM-DD)"),
    client_id: Optional[str] = Query(None, description="ID клиники для фильтрации звонков")
) -> Dict[str, Any]:
    """
    Получает список звонков из MongoDB.
    
    Args:
        start_date: Начальная дата для фильтрации (формат DD.MM.YYYY или YYYY-MM-DD)
        end_date: Конечная дата для фильтрации (формат DD.MM.YYYY или YYYY-MM-DD)
        client_id: ID клиники для фильтрации звонков
        
    Returns:
        Список звонков, соответствующих критериям
    """
    try:
        # convert_date_string теперь функция уровня модуля
        
        # Создаем начальные условия фильтрации
        query_conditions = []
        
        # Добавляем фильтрацию по client_id, если указан
        if client_id:
            query_conditions.append({"client_id": client_id})
            logger.info(f"Фильтрация звонков по client_id: {client_id}")
        
        # Добавляем фильтрацию по датам, если указаны
        if start_date or end_date:
            # Конвертируем даты в объекты datetime
            start_datetime = convert_date_string(start_date)
            end_datetime = convert_date_string(end_date)
            
            if start_datetime or end_datetime:
                # Создаем фильтр по полю created_date (строковое представление)
                date_query = {}
                
                if start_datetime:
                    # Форматируем дату в строку для сравнения с created_date_for_filtering
                    start_date_str = start_datetime.strftime("%Y-%m-%d")
                    date_query["created_date_for_filtering"] = {"$gte": start_date_str}
                    logger.info(f"Фильтрация звонков с даты: {start_date_str}")
                
                if end_datetime:
                    # Форматируем дату в строку для сравнения с created_date_for_filtering
                    # Добавляем 1 день к конечной дате для включения всех событий дня
                    end_datetime = end_datetime + timedelta(days=1)
                    end_date_str = end_datetime.strftime("%Y-%m-%d")
                    
                    if "created_date_for_filtering" in date_query:
                        date_query["created_date_for_filtering"]["$lt"] = end_date_str
                    else:
                        date_query["created_date_for_filtering"] = {"$lt": end_date_str}
                    
                    logger.info(f"Фильтрация звонков до даты: {end_date_str}")
                
                # Добавляем фильтр по дате
                query_conditions.append(date_query)
                
                logger.info(f"Добавлен фильтр по дате: {date_query}")
        
        # Формируем итоговый запрос
        if len(query_conditions) > 1:
            query = {"$and": query_conditions}
        elif query_conditions:
            query = query_conditions[0]
        else:
            query = {}
            
        logger.info(f"Итоговый запрос для MongoDB: {query}")
        
        # Получаем звонки из базы
        calls = await mongodb_service.find_many("calls", query)
        
        # Формируем результат
        return {
            "success": True,
            "message": f"Получено {len(calls)} звонков",
            "data": {"calls": calls, "total": len(calls)}
        }
    except Exception as e:
        logger.error(f"Ошибка при получении списка звонков: {str(e)}")
        traceback.print_exc()  # Добавляем вывод полного стек-трейса для отладки
        return {
            "success": False,
            "message": f"Ошибка при получении списка звонков: {str(e)}",
            "data": None
        }

@router.post("/download-and-transcribe/{call_id}")
async def download_and_transcribe_call(
    call_id: str,
    background_tasks: BackgroundTasks,
    num_speakers: int = 2,
    response: Response = None
) -> Dict[str, Any]:
    """
    Скачивает запись звонка из коллекции calls и запускает её транскрибацию.
    
    Args:
        call_id: ID звонка в коллекции calls
        num_speakers: Количество говорящих для транскрибации
        
    Returns:
        Информация о процессе скачивания и транскрибации
    """
    try:
        logger.info(f"Запрос на скачивание и транскрибацию звонка: call_id={call_id}")
        
        # Проверяем, что каталоги существуют
        os.makedirs(AUDIO_DIR, exist_ok=True)
        os.makedirs(TRANSCRIPTION_DIR, exist_ok=True)
        
        # Получаем запись о звонке из MongoDB
        call_doc = await mongodb_service.find_one("calls", {"_id": ObjectId(call_id)})
        
        if not call_doc:
            logger.warning(f"Звонок с ID {call_id} не найден")
            if response:
                response.status_code = status.HTTP_404_NOT_FOUND
            return {
                "success": False,
                "message": f"Звонок с ID {call_id} не найден",
                "data": None
            }

        # Получаем ссылку на запись звонка
        call_link = call_doc.get("call_link")
        
        if not call_link:
            logger.warning(f"У звонка {call_id} нет ссылки на запись")
            if response:
                response.status_code = status.HTTP_404_NOT_FOUND
            return {
                "success": False,
                "message": f"У звонка {call_id} нет ссылки на запись",
                "data": None
            }
        
        # Формируем имя файла для аудиозаписи
        lead_id = call_doc.get("lead_id")
        note_id = call_doc.get("note_id")
        
        file_name = f"lead_{lead_id}_note_{note_id}.mp3"
        file_path = os.path.join(AUDIO_DIR, file_name)
        
        # Создаем SSL-контекст с отключенной проверкой сертификата
        import ssl
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        # Заголовки для имитации браузера
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "audio/webm,audio/ogg,audio/wav,audio/*;q=0.9,application/ogg;q=0.7,video/*;q=0.6,*/*;q=0.5",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://amocrm.mango-office.ru/",
            "Origin": "https://amocrm.mango-office.ru",
        }
        
        # Скачиваем файл
        download_success = False
        
        # Проверяем, нужно ли использовать прокси для RT и CoMagic URLs
        if "api.cloudpbx.rt.ru" in call_link or "media.comagic.ru" in call_link:
            logger.info(f"RT или CoMagic URL обнаружен, используем SOCKS5 прокси: {call_link}")
            
            # Получаем настройки прокси из переменной окружения
            proxy_string = os.getenv("PROXY_STRING")
            if proxy_string:
                parts = proxy_string.split(':')
                if len(parts) == 4:
                    ip, port, user, password = parts
                    proxy_url = f"socks5h://{user}:{password}@{ip}:{port}"
                    proxies = {"http": proxy_url, "https": proxy_url}
                    
                    try:
                        # Скачиваем через прокси в отдельном потоке
                        response = await asyncio.to_thread(
                            lambda: requests.get(call_link, headers=headers, proxies=proxies, verify=False, timeout=30)
                        )
                        
                        logger.info(f"Прокси ответ: статус {response.status_code}, размер {len(response.content)} байт")
                        
                        if response.status_code == 200 and len(response.content) > 1000 and not response.content.startswith(b"<!DOCTYPE"):
                            # Сохраняем файл
                            async with aiofiles.open(file_path, "wb") as f:
                                await f.write(response.content)
                            logger.info(f"Файл записи звонка сохранен через прокси: {file_path}")
                            download_success = True
                        else:
                            logger.error(f"Прокси: неверный ответ - статус {response.status_code}, размер {len(response.content)} байт")
                            if response.status_code != 200:
                                logger.error(f"Прокси: текст ответа: {response.text[:200]}")
                    except Exception as e:
                        logger.error(f"Ошибка скачивания через прокси: {e}")
                else:
                    logger.error("Неверный формат PROXY_STRING. Ожидается ip:port:user:password")
            else:
                logger.error("PROXY_STRING не найден в переменных окружения")
        
        # Если прокси не сработал или URL не RT, используем обычное скачивание с retry логикой
        if not download_success:
            max_retries = 3  # Уменьшено с 5 до 3 для быстрого skip проблемных файлов
            retry_delays = [1, 2, 3]  # Короткие задержки - если сервер не отвечает, нет смысла ждать долго

            for attempt in range(max_retries):
                try:
                    connector = aiohttp.TCPConnector(ssl=ssl_context)
                    timeout = aiohttp.ClientTimeout(total=30)  # Таймаут 30 секунд вместо 60

                    async with aiohttp.ClientSession(connector=connector, headers=headers, timeout=timeout) as session:
                        logger.info(f"Попытка {attempt + 1}/{max_retries}: Скачиваем файл по ссылке: {call_link}")

                        async with session.get(call_link, allow_redirects=True) as download_response:
                            status_code = download_response.status
                            logger.info(f"Статус ответа: {status_code}")
                            
                            if status_code == 200:
                                data = await download_response.read()
                                data_size = len(data)
                                
                                if data_size < 1000 or data.startswith(b"<!DOCTYPE"):
                                    logger.error(f"Получен неверный формат данных (HTML или слишком маленький размер): {data_size} байт")
                                else:
                                    # Сохраняем файл
                                    async with aiofiles.open(file_path, "wb") as f:
                                        await f.write(data)
                                        
                                    logger.info(f"Файл записи звонка сохранен: {file_path}")
                                    download_success = True
                                    break  # Успешно скачали, выходим из цикла
                            else:
                                logger.warning(f"Попытка {attempt + 1}: Неуспешный статус {status_code}")
                                # Добавляем задержку перед следующей попыткой
                                if attempt < max_retries - 1:
                                    delay = retry_delays[attempt]
                                    logger.info(f"Ожидание {delay} сек. перед следующей попыткой...")
                                    await asyncio.sleep(delay)

                except (aiohttp.ClientConnectorError, ConnectionResetError, OSError, asyncio.TimeoutError) as e:
                    logger.warning(f"Попытка {attempt + 1} не удалась: {e}")
                    if attempt < max_retries - 1:  # Если не последняя попытка
                        delay = retry_delays[attempt]
                        logger.info(f"Ожидание {delay} сек. перед следующей попыткой...")
                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"Все {max_retries} попыток скачивания не удались")
                        
                except Exception as e:
                    logger.error(f"Попытка {attempt + 1}: Неожиданная ошибка при скачивании: {e}")
                    if attempt < max_retries - 1:
                        delay = retry_delays[attempt]
                        await asyncio.sleep(delay)
                    
                if download_success:
                    break
        
        if not download_success:
            logger.error(f"Не удалось скачать запись звонка")

            # Обновляем статус звонка на failed
            await mongodb_service.update_one(
                "calls",
                {"_id": ObjectId(call_id)},
                {
                    "$set": {
                        "transcription_status": "failed",
                        "updated_at": datetime.now()
                    }
                }
            )
            logger.warning(f"Статус звонка {call_id} обновлен на 'failed' (не удалось скачать аудио)")

            if response:
                response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
            return {
                "success": False,
                "message": "Не удалось скачать запись звонка",
                "data": None
            }
        
        # Получаем данные для транскрибации
        phone = call_doc.get("phone", "")
        client_name = call_doc.get("contact_name", "")
        manager_name = call_doc.get("administrator", "")
        
        # Получаем длительность звонка из корня документа (НЕ из metrics!)
        call_duration = call_doc.get("duration", 0)
        
        # Генерируем имя файла для сохранения результата транскрибации
        current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        phone_str = ""
        
        if phone:
            # Очищаем номер телефона от лишних символов для использования в имени файла
            phone_str = re.sub(r"[^\d]", "", phone)
        
        # Формируем имя файла транскрипции
        if phone_str:
            output_filename = f"{phone_str}_{current_time}.txt"
        else:
            output_filename = f"note_{note_id}_{current_time}.txt"
            
        output_path = os.path.join(TRANSCRIPTION_DIR, output_filename)
        
        # Запускаем транскрибацию в фоновом режиме
        logger.info(f"Запускаем транскрибацию файла: {file_path}")
        
        background_tasks.add_task(
            transcribe_and_save,
            call_id=call_id,  # Передаем call_id
            audio_path=file_path,
            output_path=output_path,
            num_speakers=num_speakers,
            diarize=True,
            phone=phone,
            manager_name=manager_name,
            client_name=client_name,
            is_first_contact=False,
            note_data={
                "note_id": note_id,
                "lead_id": lead_id,
                "contact_id": call_doc.get("contact_id"),
                "client_id": call_doc.get("client_id")
            },
            call_duration=call_duration  # Передаем длительность звонка
        )
        
        # Обновляем запись в MongoDB, добавляя имена файлов
        await mongodb_service.update_one(
            "calls",
            {"_id": ObjectId(call_id)},
            {
                "$set": {
                    "filename_audio": file_name,
                    "filename_transcription": output_filename,
                    "transcription_status": "processing",
                    "updated_at": datetime.now()
                }
            }
        )
        
        return {
            "success": True,
            "message": "Звонок скачан, транскрибация запущена",
            "data": {
                "call_id": call_id,
                "note_id": note_id,
                "lead_id": lead_id, 
                "audio_file": file_name,
                "transcription_file": output_filename,
                "phone": phone,
                "client_name": client_name,
                "manager_name": manager_name,
                "status": "processing",
                "download_url": f"/api/calls/download/{call_id}",
                "transcription_url": f"/api/transcriptions/{output_filename}/download"
            }
        }
        
    except Exception as e:
        error_msg = f"Ошибка при скачивании и транскрибации звонка: {str(e)}"
        logger.error(error_msg)
        
        # Полный стек-трейс для отладки
        logger.error(f"Стек-трейс:\n{traceback.format_exc()}")
        
        if response:
            response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return {"success": False, "message": error_msg, "data": None}

@router.get("/download/{call_id}")
async def download_call_audio(call_id: str, response: Response):
    """
    Скачивает аудиофайл звонка.
    
    Args:
        call_id: ID звонка в коллекции calls
        
    Returns:
        Аудиофайл звонка
    """
    try:
        logger.info(f"Запрос на скачивание аудиофайла звонка: call_id={call_id}")
        
        # Получаем запись о звонке из MongoDB
        call_doc = await mongodb_service.find_one("calls", {"_id": ObjectId(call_id)})
        
        if not call_doc:
            logger.warning(f"Звонок с ID {call_id} не найден")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Звонок с ID {call_id} не найден"
            )
        
        # Проверяем наличие имени файла
        filename_audio = call_doc.get("filename_audio")
        
        if not filename_audio:
            # Если имя файла не задано, формируем его из lead_id и note_id
            lead_id = call_doc.get("lead_id")
            note_id = call_doc.get("note_id")
            
            if not lead_id or not note_id:
                logger.warning(f"У звонка {call_id} нет необходимых данных для формирования имени файла")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Не удалось определить имя аудиофайла"
                )
                
            filename_audio = f"lead_{lead_id}_note_{note_id}.mp3"
        
        # Формируем полный путь к файлу
        file_path = os.path.join(AUDIO_DIR, filename_audio)
        
        # Проверяем существование файла
        if not os.path.exists(file_path):
            logger.warning(f"Файл {file_path} не найден")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Аудиофайл не найден на сервере"
            )
        
        # Создаем имя файла для скачивания
        download_filename = filename_audio
        
        # Если есть информация о контакте или звонке, создаем более понятное имя
        contact_name = call_doc.get("contact_name", "")
        phone = call_doc.get("phone", "")
        call_date = call_doc.get("created_date", "")
        
        if phone and call_date:
            # Очищаем номер телефона от лишних символов
            phone_clean = re.sub(r"[^\d]", "", phone)
            # Преобразуем дату в формат без пробелов и специальных символов
            date_clean = re.sub(r"[^\d]", "", call_date)
            download_filename = f"call_{phone_clean}_{date_clean}.mp3"
        
        # Используем FileResponse с явно указанными заголовками для загрузки
        headers = {"Content-Disposition": f'attachment; filename="{download_filename}"'}
        
        return FileResponse(
            path=file_path,
            filename=download_filename,
            media_type="audio/mpeg",
            headers=headers
        )
    
    except HTTPException:
        raise
    except Exception as e:
        error_msg = f"Ошибка при скачивании аудиофайла звонка: {str(e)}"
        logger.error(error_msg)
        logger.error(traceback.format_exc())
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=error_msg
        ) 


@router.post("/transcribe-by-date-range", summary="Массовая транскрибация звонков за диапазон дат")
async def transcribe_calls_by_date_range(
    background_tasks: BackgroundTasks,
    start_date_str: str = Query(..., description="Начальная дата (DD.MM.YYYY или YYYY-MM-DD)"),
    end_date_str: str = Query(..., description="Конечная дата (DD.MM.YYYY или YYYY-MM-DD)"),
    client_id: Optional[str] = Query(None, description="ID клиента для фильтрации звонков (если применимо)"),
    force_transcribe: bool = Query(False)
) -> Dict[str, Any]:
    """
    Запускает массовую транскрибацию звонков из MongoDB за указанный диапазон дат.
    Звонки отбираются по дате создания записи (`created_at`) и, опционально, по `client_id`.
    Транскрибируются только звонки, имеющие ссылку на аудиозапись (`record_link`).
    Если `force_transcribe`=False, уже транскрибированные звонки пропускаются.
    Задачи на транскрибацию добавляются в фон.
    
    ⚠️ Проверяется месячный лимит клиники на использование ElevenLabs API.
    """
    logger.info(
        f"Запрос на массовую транскрибацию: {start_date_str} - {end_date_str}, client_id: {client_id}, "
        # f"concurrency: {concurrency}, force_transcribe: {force_transcribe}"
        f"force_transcribe: {force_transcribe}"
    )

    # ПРОВЕРКА ЛИМИТА КЛИНИКИ
    if client_id:
        from app.services.clinic_limits_service import check_clinic_limit
        
        limit_check = await check_clinic_limit(client_id)
        
        if not limit_check.get("allowed", False):
            logger.warning(f"Клиника {client_id} превысила месячный лимит транскрибации")
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "Превышен месячный лимит использования транскрибации",
                    "clinic_name": limit_check.get("clinic_name", "Неизвестно"),
                    "monthly_limit": limit_check.get("monthly_limit", 0),
                    "current_usage": limit_check.get("current_usage", 0),
                    "remaining": limit_check.get("remaining", 0)
                }
            )
        
        logger.info(
            f"✅ Лимит клиники {limit_check.get('clinic_name')}: "
            f"{limit_check.get('current_usage')}/{limit_check.get('monthly_limit')} токенов использовано, "
            f"осталось {limit_check.get('remaining')} токенов"
        )

    start_time_global = datetime.now()

    start_date_obj = convert_date_string(start_date_str)
    end_date_obj = convert_date_string(end_date_str)

    if not start_date_obj or not end_date_obj:
        raise HTTPException(status_code=400, detail="Неверный формат даты. Используйте DD.MM.YYYY или YYYY-MM-DD.")

    if start_date_obj > end_date_obj:
        raise HTTPException(status_code=400, detail="Начальная дата не может быть позже конечной даты.")

    # Формируем строки для фильтрации по полю "created_date_for_filtering"
    start_date_filter_str = start_date_obj.strftime("%Y-%m-%d")
    end_date_filter_str = end_date_obj.strftime("%Y-%m-%d")
    
    mongo_query = {
        "created_date_for_filtering": {"$gte": start_date_filter_str, "$lte": end_date_filter_str},
        "call_link": {"$exists": True, "$ne": None, "$ne": ""}  # Изменено "record_link" на "call_link"
    }

    if client_id:
        mongo_query["client_id"] = client_id

    if not force_transcribe:
        # Транскрибируем звонки, которые:
        # 1. Не имеют файла транскрипции ИЛИ
        # 2. Имеют статус pending/null (еще не обработаны)
        mongo_query["$or"] = [
            {"filename_transcription": {"$exists": False}},
            {"filename_transcription": None},
            {"filename_transcription": ""},
            {"transcription_status": "pending"},
            {"transcription_status": None},
            {"transcription_status": {"$exists": False}}
        ]
        
    # TODO: Рассмотреть добавление параметра projection в mongodb_service.find_many, 
    #       если требуется запрашивать только определенные поля (например, _id) для оптимизации.
    calls_to_transcribe_list = await mongodb_service.find_many("calls", mongo_query) 

    if not calls_to_transcribe_list:
        logger.info("Не найдено звонков для транскрибации по указанным критериям.")
        return {
            "message": "Не найдено звонков для транскрибации.",
            "total_found": 0,
            "tasks_queued": 0,
            "duration_seconds": (datetime.now() - start_time_global).total_seconds()
        }

    logger.info(f"Найдено {len(calls_to_transcribe_list)} звонков для запуска транскрибации.")

    tasks_queued_count = 0
    
    for call_doc in calls_to_transcribe_list:
        call_id_str = str(call_doc["_id"])
        try:
            logger.info(f"Добавление задачи на транскрибацию для call_id: {call_id_str}")
            # Вызов существующей функции download_and_transcribe_call, 
            # она сама управляет добавлением задачи транскрибации в background_tasks.
            # num_speakers и response оставляем по умолчанию.
            background_tasks.add_task(download_and_transcribe_call, call_id=call_id_str, background_tasks=background_tasks)
            tasks_queued_count += 1
        except Exception as e:
            logger.error(f"Ошибка при постановке задачи на транскрибацию для call_id {call_id_str}: {e}")
            # Здесь можно добавить логику для сбора информации об ошибках, если необходимо

    duration = (datetime.now() - start_time_global).total_seconds()
    logger.info(f"Массовая транскрибация: {tasks_queued_count} задач добавлено в фон. Длительность постановки: {duration:.2f} сек.")

    return {
        "message": f"{tasks_queued_count} задач на транскрибацию успешно добавлено в фоновый режим.",
        "total_found": len(calls_to_transcribe_list),
        "tasks_queued": tasks_queued_count,
        "duration_seconds": duration
    }


@router.get("/transcribe-by-date-range-status")
async def get_transcription_status_by_date_range(
    start_date_str: str = Query(..., description="Начальная дата (DD.MM.YYYY или YYYY-MM-DD)"),
    end_date_str: str = Query(..., description="Конечная дата (DD.MM.YYYY или YYYY-MM-DD)"),
    client_id: str = Query(..., description="ID клиента")
) -> Dict[str, Any]:
    """
    Получить статус транскрибации звонков за указанный период для проверки завершения процесса.
    """
    try:
        # Преобразуем строки дат в datetime объекты используя существующую функцию
        start_datetime = convert_date_string(start_date_str)
        end_datetime = convert_date_string(end_date_str)
        
        if not start_datetime or not end_datetime:
            raise HTTPException(status_code=400, detail="Неверный формат даты. Используйте DD.MM.YYYY или YYYY-MM-DD.")
        
        end_datetime = end_datetime + timedelta(days=1) - timedelta(microseconds=1)

        # Формируем строки для фильтрации по полю "created_date_for_filtering" (как в основном эндпоинте)
        start_date_filter_str = start_datetime.strftime("%Y-%m-%d")
        end_date_filter_str = end_datetime.strftime("%Y-%m-%d")
        
        # Формируем запрос для поиска звонков в указанном диапазоне
        query = {
            "client_id": client_id,
            "created_date_for_filtering": {
                "$gte": start_date_filter_str,
                "$lte": end_date_filter_str
            }
        }

        # Получаем звонки за период
        calls = await mongodb_service.find_many("calls", query)
        
        # Подсчитываем статистику по статусам транскрибации
        total_calls = len(calls)
        processing_count = 0
        success_count = 0
        failed_count = 0
        pending_count = 0

        for call in calls:
            transcription_status = call.get("transcription_status", "pending")
            if transcription_status == "processing":
                processing_count += 1
            elif transcription_status == "success":
                success_count += 1
            elif transcription_status == "failed":
                failed_count += 1
            else:
                pending_count += 1

        # Завершенные = success + failed (транскрибация была выполнена, успешно или нет)
        completed_count = success_count + failed_count
        
        # Определяем общий статус процесса
        if processing_count > 0:
            overall_status = "processing"
        elif pending_count > 0:
            overall_status = "pending"
        elif completed_count == total_calls:
            # Все звонки обработаны (успешно или с ошибкой)
            overall_status = "completed"
        else:
            overall_status = "partial"

        result = {
            "overall_status": overall_status,
            "total_calls": total_calls,
            "status_breakdown": {
                "pending": pending_count,
                "processing": processing_count,
                "success": success_count,
                "failed": failed_count
            },
            # Прогресс = (success + failed) / total, т.к. failed тоже обработаны
            "progress_percentage": round((completed_count / total_calls * 100), 2) if total_calls > 0 else 0
        }
        
        # Логируем результат для отладки
        logger.info(f"📊 Статус транскрибации для {client_id} ({start_date_str} - {end_date_str}): {result}")
        
        return result

    except ValueError as ve:
        logger.error(f"Ошибка формата даты: {ve}")
        raise HTTPException(status_code=400, detail=f"Неверный формат даты: {ve}")
    except Exception as e:
        logger.error(f"Ошибка при получении статуса транскрибации: {e}")
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка сервера: {str(e)}")