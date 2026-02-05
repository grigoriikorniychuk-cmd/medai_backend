"""
Тесты для проверки основного потока API - от получения сделок до анализа звонка.
Тестовый сценарий:
1. Получение сделок по дате
2. Получение контакта из сделки
3. Получение списка звонков по контакту
4. Скачивание и транскрибация звонка
5. Анализ звонка
"""

import asyncio
import aiohttp
import json
import os
import logging
from datetime import datetime, timedelta
import sys
from typing import Dict, Any, Optional, List

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('api_test.log')
    ]
)
logger = logging.getLogger('api_test')

# Конфигурация тестов
BASE_URL = "http://127.0.0.1:8000"
CLIENT_ID = "10d5e4d3-cd0f-406b-9dfd-cde89d81030e"  # ID клиники для тестирования
NUM_SPEAKERS = 2
TEST_DATE = "01.04.2025"  # Дата для поиска сделок


async def make_request(url: str, method: str = "GET", data: dict = None, headers: dict = None) -> Dict[str, Any]:
    """
    Выполняет HTTP-запрос к API и возвращает результат.
    
    Args:
        url: URL для запроса
        method: HTTP-метод (GET, POST, и t.д.)
        data: Данные для отправки в теле запроса
        headers: Заголовки запроса
        
    Returns:
        Словарь с результатом запроса или None в случае ошибки
    """
    try:
        logger.info(f"Выполняется {method} запрос к {url}")
        async with aiohttp.ClientSession() as session:
            if method.upper() == "GET":
                async with session.get(url, headers=headers) as response:
                    status = response.status
                    result = await response.json()
                    logger.info(f"Статус ответа: {status}")
                    return result
            elif method.upper() == "POST":
                async with session.post(url, json=data, headers=headers) as response:
                    status = response.status
                    result = await response.json()
                    logger.info(f"Статус ответа: {status}")
                    return result
            else:
                logger.error(f"Неподдерживаемый метод: {method}")
                return None
    except Exception as e:
        logger.error(f"Ошибка с выполнении запроса к {url}: {str(e)}")
        return None


async def download_file(url: str, output_path: str) -> bool:
    """
    Скачивает файл по указанному URL.
    
    Args:
        url: URL файла для скачивания
        output_path: Путь для сохранения файла
        
    Returns:
        True если скачивание успешно, else False
    """
    try:
        logger.info(f"Скачивание файла из {url} в {output_path}")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status != 200:
                    logger.error(f"Ошибка с скачивании: HTTP {response.status}")
                    return False
                
                with open(output_path, 'wb') as f:
                    f.write(await response.read())
                
                logger.info(f"Файл успешно скачан: {output_path}")
                return True
    except Exception as e:
        logger.error(f"Ошибка с скачивании файла: {str(e)}")
        return False


async def test_get_leads_by_date():
    """
    Шаг 1: Получение сделок по дате
    """
    url = f"{BASE_URL}/api/amocrm/leads/by-date"
    data = {
        "client_id": CLIENT_ID,
        "date": TEST_DATE
    }
    
    logger.info(f"Шаг 1: Получение сделок по дате {TEST_DATE}")
    result = await make_request(url, method="POST", data=data)
    
    if not result or not result.get("success", False):
        error_message = result.get("message", "Неизвестная ошибка") if result else "Нет ответа от API"
        logger.error(f"Ошибка с получении сделок: {error_message}")
        return None
    
    leads_data = result.get("data", {})
    total_leads = leads_data.get("total_leads", 0)
    leads = leads_data.get("leads", [])
    
    logger.info(f"Найдено {total_leads} сделок за {TEST_DATE}")
    
    if total_leads == 0 or not leads:
        logger.warning(f"Сделок за {TEST_DATE} не найдено")
        return None
    
    # Берем первую сделку для дальнейшего тестирования
    lead = leads[0]
    lead_id = lead.get("id")
    
    logger.info(f"Выбрана сделка для тестирования: {lead.get('name')} (ID: {lead_id})")
    return lead_id


async def test_get_contact_from_lead(lead_id: int):
    """
    Шаг 2: Получение контакта из сделки
    """
    url = f"{BASE_URL}/api/amocrm/lead/contact"
    data = {
        "client_id": CLIENT_ID,
        "lead_id": lead_id
    }
    
    logger.info(f"Шаг 2: Получение контакта из сделки {lead_id}")
    result = await make_request(url, method="POST", data=data)
    
    if not result or not result.get("success", False):
        error_message = result.get("message", "Неизвестная ошибка") if result else "Нет ответа от API"
        logger.error(f"Ошибка с получении контакта: {error_message}")
        return None
    
    contact_data = result.get("data", {})
    contact_id = contact_data.get("id")
    
    if not contact_id:
        logger.warning(f"Контакт для сделки {lead_id} не найден")
        return None
    
    logger.info(f"Получен контакт: {contact_data.get('name')} (ID: {contact_id})")
    return contact_id


async def test_get_contact_calls(contact_id: int):
    """
    Шаг 3: Получение списка звонков по контакту
    """
    url = f"{BASE_URL}/api/amocrm/contact/calls"
    data = {
        "client_id": CLIENT_ID,
        "contact_id": contact_id
    }
    
    logger.info(f"Шаг 3: Получение списка звонков для контакта {contact_id}")
    result = await make_request(url, method="POST", data=data)
    
    if not result or not result.get("success", False):
        error_message = result.get("message", "Неизвестная ошибка") if result else "Нет ответа от API"
        logger.error(f"Ошибка с получении звонков: {error_message}")
        return None
    
    calls_data = result.get("data", {})
    total_calls = calls_data.get("total_calls", 0)
    calls = calls_data.get("calls", [])
    
    logger.info(f"Найдено {total_calls} звонков для контакта {contact_id}")
    
    if total_calls == 0 or not calls:
        logger.warning(f"Звонков для контакта {contact_id} не найдено")
        return None
    
    # Берем первый звонок для дальнейшего тестирования
    call = calls[0]
    note_id = call.get("id") or call.get("note_id")
    lead_id = call.get("lead_id")
    
    logger.info(f"Выбран звонок для тестирования: ID {note_id}, связан со сделкой {lead_id}")
    return {
        "note_id": note_id,
        "lead_id": lead_id,
        "contact_id": contact_id
    }


async def test_download_and_transcribe_call(call_info: Dict[str, Any]):
    """
    Шаг 4: Скачивание и транскрибация звонка
    """
    note_id = call_info.get("note_id")
    lead_id = call_info.get("lead_id")
    contact_id = call_info.get("contact_id")
    
    url = f"{BASE_URL}/api/amocrm/contact/call/{note_id}/download-and-transcribe"
    params = f"client_id={CLIENT_ID}&num_speakers={NUM_SPEAKERS}&lead_id={lead_id}&contact_id={contact_id}"
    full_url = f"{url}?{params}"
    
    logger.info(f"Шаг 4: Скачивание и транскрибация звонка {note_id}")
    result = await make_request(full_url)
    
    if not result or not result.get("success", False):
        error_message = result.get("message", "Неизвестная ошибка") if result else "Нет ответа от API"
        logger.error(f"Ошибка с скачивании и транскрибации: {error_message}")
        return None
    
    transcription_data = result.get("data", {})
    transcription_text = transcription_data.get("transcription_text")
    transcription_id = transcription_data.get("id")
    filename = transcription_data.get("filename")
    
    if not transcription_text or not transcription_id:
        logger.warning(f"Транскрипция для звонка {note_id} не получена")
        return None
    
    logger.info(f"Получена транскрипция: ID {transcription_id}, длина текста: {len(transcription_text)} символов")
    
    # Возвращаем информацию для анализа звонка
    return {
        "transcription_id": transcription_id,
        "note_id": note_id,
        "lead_id": lead_id,
        "contact_id": contact_id,
        "transcription_filename": filename,
        "transcription_text": transcription_text
    }


async def test_analyze_call(transcription_info: Dict[str, Any]):
    """
    Шаг 5: Анализ звонка
    """
    url = f"{BASE_URL}/api/call/analyze"
    data = {
        "client_id": CLIENT_ID,
        "note_id": transcription_info.get("note_id"),
        "lead_id": transcription_info.get("lead_id"),
        "contact_id": transcription_info.get("contact_id"),
        "transcription_filename": transcription_info.get("transcription_filename"),
        "transcription_text": transcription_info.get("transcription_text"),
        "administrator_id": "test_admin",
        "meta_info": {
            "client_source": "test",
            "administrator_name": "Тестовый администратор"
        }
    }
    
    logger.info(f"Шаг 5: Анализ звонка (note_id: {transcription_info.get('note_id')})")
    result = await make_request(url, method="POST", data=data)
    
    if not result or not result.get("success", False):
        error_message = result.get("message", "Неизвестная ошибка") if result else "Нет ответа от API"
        logger.error(f"Ошибка с анализе звонка: {error_message}")
        return None
    
    analysis_data = result.get("data", {})
    analysis_id = analysis_data.get("id")
    
    if not analysis_id:
        logger.warning("ID анализа не получен")
        return None
    
    logger.info(f"Анализ звонка успешно создан: ID {analysis_id}")
    logger.info(f"Тип звонка: {analysis_data.get('call_type')}")
    logger.info(f"Направление: {analysis_data.get('direction')}")
    logger.info(f"Общая оценка: {analysis_data.get('overall_score')}")
    logger.info(f"Конверсия: {'Да' если analysis_data.get('conversion') else 'Нет'}")
    
    return analysis_data


async def run_full_test():
    """
    Запускает полный тестовый сценарий от получения сделок до анализа звонка
    """
    logger.info("=== ЗАПУСК ПОЛНОГО ТЕСТОВОГО СЦЕНАРИЯ ===")
    
    # Шаг 1: Получение сделок по дате
    lead_id = await test_get_leads_by_date()
    if not lead_id:
        logger.error("Тест завершен с ошибкой на шаге 1")
        return False
    
    # Шаг 2: Получение контакта из сделки
    contact_id = await test_get_contact_from_lead(lead_id)
    if not contact_id:
        logger.error("Тест завершен с ошибкой на шаге 2")
        return False
    
    # Шаг 3: Получение списка звонков по контакту
    call_info = await test_get_contact_calls(contact_id)
    if not call_info:
        logger.error("Тест завершен с ошибкой на шаге 3")
        return False
    
    # Шаг 4: Скачивание и транскрибация звонка
    transcription_info = await test_download_and_transcribe_call(call_info)
    if not transcription_info:
        logger.error("Тест завершен с ошибкой на шаге 4")
        return False
    
    # Шаг 5: Анализ звонка
    analysis_result = await test_analyze_call(transcription_info)
    if not analysis_result:
        logger.error("Тест завершен с ошибкой на шаге 5")
        return False
    
    logger.info("=== ТЕСТОВЫЙ СЦЕНАРИЙ УСПЕШНО ЗАВЕРШЕН ===")
    return True


# Функция для запуска тестов в асинхронном режиме
def main():
    logger.info("Запуск тестов API")
    
    try:
        result = asyncio.run(run_full_test())
        if result:
            logger.info("Все тесты успешно пройдены!")
            return 0
        else:
            logger.error("Тесты завершены с ошибками")
            return 1
    except Exception as e:
        logger.error(f"Ошибка с выполнении тестов: {str(e)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())