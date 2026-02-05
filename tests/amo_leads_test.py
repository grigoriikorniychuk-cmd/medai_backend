#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import traceback
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple
import sys
import os
from pprint import pprint
import logging
import json
import ssl
import aiohttp

# Убедитесь, что корневой каталог проекта доступен для импортов
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Импортируем необходимые модули
from amo_credentials import get_full_amo_credentials, MONGODB_URI, MONGODB_NAME, mongo_client
from motor.motor_asyncio import AsyncIOMotorClient
from aiohttp import ClientSession, BasicAuth

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("amo_leads_test")


class AmoClient:
    """Простой клиент для работы с AmoCRM API"""
    
    def __init__(self, access_token: str, subdomain: str):
        self.access_token = access_token
        self.base_url = f"https://{subdomain}.amocrm.ru/api/v4"
        self.session = None
    
    async def create_session(self):
        """Создаёт сессию для запросов к API"""
        # Создаем контекст SSL без проверки сертификата (только для тестирования)
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        # Создаем сессию с отключенной проверкой SSL
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        self.session = ClientSession(connector=connector)
        self.session.headers.update({
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        })
        return self
    
    async def close(self):
        """Закрывает сессию"""
        if self.session:
            await self.session.close()
    
    async def __aenter__(self):
        return await self.create_session()
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
    
    async def request(self, method: str, endpoint: str, params: Dict = None, data: Dict = None) -> Tuple[Dict, int]:
        """Выполняет запрос к API AmoCRM"""
        if not self.session:
            await self.create_session()
        
        url = f"{self.base_url}/{endpoint}"
        method = method.lower()
        
        try:
            if method == "get":
                async with self.session.get(url, params=params) as response:
                    status = response.status
                    if status == 204:
                        return {}, status
                    resp_data = await response.json()
                    return resp_data, status
            elif method == "post":
                async with self.session.post(url, json=data) as response:
                    status = response.status
                    if status == 204:
                        return {}, status
                    resp_data = await response.json()
                    return resp_data, status
            else:
                raise ValueError(f"Неподдерживаемый метод: {method}")
        except Exception as e:
            logger.error(f"Ошибка при выполнении запроса {method} {url}: {str(e)}")
            return {"error": str(e)}, 500
    
    async def get_contact_from_lead(self, lead_id: int) -> Optional[Dict[str, Any]]:
        """Получает контакт, связанный со сделкой"""
        try:
            # Получаем связи сделки
            links_endpoint = f"leads/{lead_id}/links"
            links_response, links_status = await self.request("get", links_endpoint)
            
            if links_status != 200:
                logger.error(f"Ошибка при получении связей сделки {lead_id}: {links_response}")
                return None
            
            # Ищем связь с контактом
            if "_embedded" in links_response and "links" in links_response["_embedded"]:
                for link in links_response["_embedded"]["links"]:
                    if link.get("to_entity_type") == "contacts":
                        contact_id = link.get("to_entity_id")
                        if contact_id:
                            # Получаем данные контакта
                            contact_response, contact_status = await self.request("get", f"contacts/{contact_id}")
                            if contact_status == 200:
                                return contact_response
            
            logger.warning(f"Контакт для сделки {lead_id} не найден")
            return None
            
        except Exception as e:
            logger.error(f"Ошибка при получении контакта для сделки {lead_id}: {str(e)}")
            return None
    
    async def get_call_links(self, contact_id: int) -> List[Dict[str, Any]]:
        """Получает информацию о звонках контакта"""
        try:
            # Получаем заметки контакта с типом 'call_in' или 'call_out'
            notes_endpoint = f"contacts/{contact_id}/notes"
            notes_params = {
                "filter[note_type]": "10,11",  # 10 - входящие, 11 - исходящие звонки
                "limit": 100  # Увеличиваем лимит для получения большего числа звонков
            }
            
            notes_response, notes_status = await self.request("get", notes_endpoint, params=notes_params)
            
            if notes_status != 200:
                logger.error(f"Ошибка при получении заметок контакта {contact_id}: {notes_response}")
                return []
            
            # Преобразуем заметки в информацию о звонках
            call_links = []
            
            if "_embedded" in notes_response and "notes" in notes_response["_embedded"]:
                for note in notes_response["_embedded"]["notes"]:
                    note_id = note.get("id")
                    if note_id:
                        call_links.append({
                            "note_id": note_id,
                            "note": note
                        })
                
                logger.info(f"Найдено {len(call_links)} звонков для контакта {contact_id}")
                return call_links
            
            logger.info(f"Звонки для контакта {contact_id} не найдены")
            return []
            
        except Exception as e:
            logger.error(f"Ошибка при получении звонков контакта {contact_id}: {str(e)}")
            return []


async def get_calls_for_lead(amo: AmoClient, lead: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Получает все звонки, связанные с одной сделкой
    
    Args:
        amo: Экземпляр клиента AMO CRM
        lead: Сделка из AMO CRM
    
    Returns:
        Список звонков, связанных с этой сделкой
    """
    try:
        lead_id = lead.get("id")
        if not lead_id:
            logger.warning("У сделки отсутствует ID")
            return []
        
        # Получаем кастомные поля сделки (для дополнительной информации)
        custom_fields = {}
        if lead.get("custom_fields_values"):
            for field in lead["custom_fields_values"]:
                field_name = field.get("field_name", f"Поле {field.get('field_id')}")
                values = field.get("values", [])
                if values:
                    field_value = values[0].get("value")
                    custom_fields[field_name] = field_value
        
        # Получаем контакт, связанный со сделкой
        contact = await amo.get_contact_from_lead(lead_id)
        
        if not contact:
            logger.info(f"Для сделки #{lead_id} не найден связанный контакт")
            return []
        
        contact_id = contact.get("id")
        if not contact_id:
            logger.warning(f"У контакта отсутствует ID")
            return []
        
        contact_name = contact.get("name", "Без имени")
        
        # Получаем звонки контакта
        call_links = await amo.get_call_links(contact_id)
        
        if not call_links:
            logger.info(f"Для контакта #{contact_id} не найдено звонков")
            return []
        
        # Обрабатываем и форматируем информацию о звонках
        calls = []
        
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
            created_date = datetime.fromtimestamp(created_at, tz=timezone.utc) if created_at else datetime.now(tz=timezone.utc)
            created_date_str = created_date.strftime("%Y-%m-%d %H:%M:%S")
            
            # Создаем документ с информацией о звонке
            call_doc = {
                "note_id": note_id,  # Уникальный ID заметки
                "lead_id": lead_id,
                "lead_name": lead.get("name", ""),
                "contact_id": contact_id,
                "contact_name": contact_name,
                "call_direction": call_direction,
                "duration": duration,
                "duration_formatted": duration_formatted,
                "phone": params.get("phone", "Неизвестно"),
                "call_link": params.get("link", ""),
                "call_status": params.get("call_status", ""),
                "created_at": created_at,
                "created_date": created_date_str,
                "custom_fields": custom_fields
            }
            
            calls.append(call_doc)
        
        logger.info(f"Для сделки #{lead_id} (контакт #{contact_id}) обработано {len(calls)} звонков")
        return calls
    
    except Exception as e:
        logger.error(f"Ошибка при обработке звонков для сделки: {str(e)}")
        logger.error(traceback.format_exc())
        return []


async def get_leads_by_date(target_date: str, client_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Получает все сделки из AMO CRM за указанную дату
    
    Args:
        target_date: Дата в формате DD.MM.YYYY
        client_id: ID клиента AmoCRM (опционально)
    
    Returns:
        Список всех полученных сделок
    """
    try:
        logger.info(f"Получение сделок за дату: {target_date}")
        
        # Получаем учетные данные для AMO CRM
        logger.info("Получение данных авторизации...")
        credentials = await get_full_amo_credentials(client_id=client_id)
        logger.info(f"Получены данные для client_id: {credentials['client_id']}, subdomain: {credentials['subdomain']}")
        
        # Создаем экземпляр API amoCRM
        amo = AmoClient(
            access_token=credentials["access_token"],
            subdomain=credentials["subdomain"]
        )
        logger.info("Клиент amoCRM успешно создан")
        
        # Разбираем дату и создаем временные метки начала и конца дня
        try:
            date_parts = target_date.split('.')
            day, month, year = map(int, date_parts)
            date_start = int(datetime(year, month, day, 0, 0, 0, tzinfo=timezone.utc).timestamp())
            date_end = int(datetime(year, month, day, 23, 59, 59, tzinfo=timezone.utc).timestamp())
        except (ValueError, IndexError, AttributeError) as e:
            logger.error(f"Ошибка при парсинге даты {target_date}: {e}")
            raise ValueError(f"Некорректный формат даты. Используйте DD.MM.YYYY")
        
        logger.info(f"Временной диапазон: {date_start} - {date_end} ({target_date})")
        logger.info(f"от: {datetime.fromtimestamp(date_start)}, до: {datetime.fromtimestamp(date_end)}")
        
        # Получаем сделки за указанный день
        all_leads = []
        page = 1
        
        while True:
            # Параметры фильтрации для сделок за указанный день
            filter_params = {
                "filter[created_at][from]": date_start,
                "filter[created_at][to]": date_end,
                "page": page,
                "limit": 50  # Увеличиваем лимит для снижения количества запросов
            }
            
            logger.info(f"Запрос сделок (страница {page})...")
            leads_response, leads_status = await amo.request("get", "leads", params=filter_params)
            
            if leads_status != 200:
                logger.error(f"Ошибка при получении сделок, статус: {leads_status}, response: {leads_response}")
                break
            
            # Извлекаем сделки из ответа
            if "_embedded" in leads_response and "leads" in leads_response["_embedded"]:
                leads = leads_response["_embedded"]["leads"]
                if not leads:
                    logger.info(f"Нет сделок на странице {page}")
                    break
                
                logger.info(f"Получено {len(leads)} сделок на странице {page}")
            
                # Добавляем сделки в общий список
                all_leads.extend(leads)
                
                # Проверяем, есть ли следующая страница
                if "_links" in leads_response and "next" in leads_response["_links"]:
                    page += 1
                else:
                    break
            else:
                logger.warning(f"Неожиданный формат ответа: {leads_response}")
                break
        
        logger.info(f"Всего получено {len(all_leads)} сделок за {target_date}")
        
        # Закрываем соединение с AMO CRM
        await amo.close()
        
        return all_leads
    
    except Exception as e:
        logger.error(f"Ошибка при получении сделок: {str(e)}")
        logger.error(traceback.format_exc())
        return []


async def get_calls_from_leads(amo: AmoClient, leads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Получает все звонки из списка сделок
    
    Args:
        amo: Экземпляр клиента AMO CRM
        leads: Список сделок
    
    Returns:
        Список всех звонков из указанных сделок
    """
    all_calls = []
    leads_with_calls = 0
    total_leads = len(leads)
    
    logger.info(f"Начинаем обработку звонков из {total_leads} сделок")
    
    for i, lead in enumerate(leads, 1):
        lead_id = lead.get("id")
        lead_name = lead.get("name", "Без названия")
        
        logger.info(f"[{i}/{total_leads}] Обрабатываем сделку #{lead_id} - {lead_name}")
        
        # Получаем звонки для текущей сделки
        lead_calls = await get_calls_for_lead(amo, lead)
        
        if lead_calls:
            all_calls.extend(lead_calls)
            leads_with_calls += 1
    
    logger.info(f"Обработка завершена. Из {total_leads} сделок найдено {leads_with_calls} с звонками. Всего звонков: {len(all_calls)}")
    return all_calls


async def print_calls_info(calls: List[Dict[str, Any]]):
    """
    Выводит информацию о звонках в удобочитаемом формате
    
    Args:
        calls: Список звонков из AMO CRM
    """
    if not calls:
        logger.info("Звонки не найдены")
        return
    
    logger.info(f"Вывод информации о {len(calls)} звонках:")
    print("\n" + "=" * 80)
    
    for i, call in enumerate(calls, 1):
        note_id = call.get("note_id")
        lead_id = call.get("lead_id")
        lead_name = call.get("lead_name", "Без названия")
        contact_name = call.get("contact_name", "Неизвестно")
        call_direction = call.get("call_direction", "Неизвестно")
        duration_formatted = call.get("duration_formatted", "0:00")
        phone = call.get("phone", "Неизвестно")
        created_date = call.get("created_date", "Неизвестно")
        
        # Получаем кастомные поля сделки (если есть)
        custom_fields = call.get("custom_fields", {})
        
        print(f"Звонок #{i}: ID {note_id}")
        print(f"Сделка: {lead_name} (ID: {lead_id})")
        print(f"Контакт: {contact_name}")
        print(f"Направление: {call_direction}")
        print(f"Длительность: {duration_formatted}")
        print(f"Телефон: {phone}")
        print(f"Дата звонка: {created_date}")
        
        if custom_fields:
            print("Дополнительная информация о сделке:")
            for name, value in custom_fields.items():
                print(f"  - {name}: {value}")
        
        print("=" * 80)


async def print_leads_info(leads: List[Dict[str, Any]]):
    """
    Выводит информацию о сделках в удобочитаемом формате
    
    Args:
        leads: Список сделок из AMO CRM
    """
    if not leads:
        logger.info("Сделки не найдены")
        return
    
    logger.info(f"Вывод информации о {len(leads)} сделках:")
    print("\n" + "-" * 50)
    
    for i, lead in enumerate(leads, 1):
        lead_id = lead.get("id")
        name = lead.get("name", "Без названия")
        price = lead.get("price", 0)
        status_id = lead.get("status_id")
        pipeline_id = lead.get("pipeline_id")
        responsible_user_id = lead.get("responsible_user_id")
        created_at_timestamp = lead.get("created_at")
        
        # Преобразуем timestamp в читаемую дату
        created_at = datetime.fromtimestamp(created_at_timestamp).strftime("%d.%m.%Y %H:%M:%S") if created_at_timestamp else "Неизвестно"
        
        # Получаем значения кастомных полей (если есть)
        custom_fields = {}
        if lead.get("custom_fields_values"):
            for field in lead["custom_fields_values"]:
                field_name = field.get("field_name", f"Поле {field.get('field_id')}")
                values = field.get("values", [])
                if values:
                    field_value = values[0].get("value")
                    custom_fields[field_name] = field_value
        
        # Форматированный вывод для каждой сделки
        print(f"Сделка #{i}: ID {lead_id}")
        print(f"Название: {name}")
        print(f"Сумма: {price} руб.")
        print(f"ID статуса: {status_id}, ID воронки: {pipeline_id}")
        print(f"ID ответственного: {responsible_user_id}")
        print(f"Создана: {created_at}")
        
        if custom_fields:
            print("Кастомные поля:")
            for name, value in custom_fields.items():
                print(f"  - {name}: {value}")
        
        print("-" * 50)


async def main():
    """
    Основная функция для запуска получения и вывода сделок
    """
    try:
        # Установка даты и ID клиента
        target_date = "13.05.2025"  # Дата в формате DD.MM.YYYY
        client_id = None  # Можно указать конкретный client_id или None для использования последнего токена
        
        # Получаем сделки
        leads = await get_leads_by_date(target_date, client_id)
        
        # Сохраняем сделки в JSON файл для отладки
        with open('leads_13_05_2025.json', 'w', encoding='utf-8') as f:
            json.dump(leads, f, ensure_ascii=False, indent=2)
            logger.info(f"Сохранены данные о сделках в файл leads_13_05_2025.json")
        
        # Выводим информацию о сделках
        await print_leads_info(leads)
        
        # Получаем и сохраняем звонки
        calls = await get_calls_from_leads(amo, leads)
        
        # Сохраняем звонки в JSON файл
        with open('calls_13_05_2025.json', 'w', encoding='utf-8') as f:
            json.dump(calls, f, ensure_ascii=False, indent=2)
            logger.info(f"Сохранены данные о звонках в файл calls_13_05_2025.json")
        
        # Выводим информацию о звонках
        await print_calls_info(calls)
        
        logger.info(f"Всего найдено {len(leads)} сделок и {len(calls)} звонков за {target_date}")
    
    except Exception as e:
        logger.error(f"Ошибка при выполнении: {str(e)}")
        logger.error(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    # Если передан аргумент командной строки, используем его как client_id
    if len(sys.argv) > 1:
        client_id_arg = sys.argv[1]
        logger.info(f"Запуск с указанным client_id: {client_id_arg}")
        
        # Модифицируем main чтобы использовать переданный client_id
        original_main = main
        async def main_with_client_id():
            try:
                # Установка даты и ID клиента из аргумента
                target_date = "13.05.2025"  # Дата в формате DD.MM.YYYY
                client_id = client_id_arg
                
                # Получаем сделки
                leads = await get_leads_by_date(target_date, client_id)
                
                # Сохраняем сделки в JSON файл для отладки
                with open('leads_13_05_2025.json', 'w', encoding='utf-8') as f:
                    json.dump(leads, f, ensure_ascii=False, indent=2)
                    logger.info(f"Сохранены данные о сделках в файл leads_13_05_2025.json")
                
                # Выводим информацию о сделках
                await print_leads_info(leads)
                
                # Получаем и сохраняем звонки
                calls = await get_calls_from_leads(amo, leads)
                
                # Сохраняем звонки в JSON файл
                with open('calls_13_05_2025.json', 'w', encoding='utf-8') as f:
                    json.dump(calls, f, ensure_ascii=False, indent=2)
                    logger.info(f"Сохранены данные о звонках в файл calls_13_05_2025.json")
                
                # Выводим информацию о звонках
                await print_calls_info(calls)
                
                logger.info(f"Всего найдено {len(leads)} сделок и {len(calls)} звонков за {target_date}")
            
            except Exception as e:
                logger.error(f"Ошибка при выполнении: {str(e)}")
                logger.error(traceback.format_exc())
                sys.exit(1)
        
        # Заменяем main на версию с client_id из аргумента
        main = main_with_client_id
    
    # Запуск асинхронной функции main
    asyncio.run(main())
