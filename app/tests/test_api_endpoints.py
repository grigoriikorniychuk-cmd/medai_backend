"""
Индивидуальные тесты для конкретных API-эндпоинтов.
Позволяет тестировать отдельные компоненты API независимо друг от друга.
"""

import asyncio
import aiohttp
import json
import sys
import argparse
import logging
from typing import Dict, Any, List, Optional

# Импортируем базовые функции из основного теста
from app.tests.test_api_flow import (
    make_request,
    download_file,
    BASE_URL,
    CLIENT_ID,
    logger
)

# Константы для тестирования
DEFAULT_LEAD_ID = 28504853
DEFAULT_CONTACT_ID = 34913261
DEFAULT_NOTE_ID = 146355909
DEFAULT_DATE = "01.04.2025"


async def test_leads_by_date(date: str = DEFAULT_DATE) -> Dict[str, Any]:
    """
    Тестирует API получения сделок по дате.
    
    Args:
        date: Дата для поиска сделок в формате DD.MM.YYYY
        
    Returns:
        Словарь с результатами теста
    """
    url = f"{BASE_URL}/api/amocrm/leads/by-date"
    data = {
        "client_id": CLIENT_ID,
        "date": date
    }
    
    logger.info(f"Тестирование API получения сделок по дате: {date}")
    result = await make_request(url, method="POST", data=data)
    
    if not result:
        logger.error("Нет ответа от API")
        return {"success": False, "message": "Нет ответа от API"}
    
    success = result.get("success", False)
    message = result.get("message", "Нет сообщения")
    data = result.get("data", {})
    
    total_leads = data.get("total_leads", 0) if data else 0
    
    if success:
        logger.info(f"API получения сделок работает корректно. Найдено {total_leads} сделок")
    else:
        logger.error(f"Ошибка с получении сделок: {message}")
    
    return result


async def test_lead_contact(lead_id: int = DEFAULT_LEAD_ID) -> Dict[str, Any]:
    """
    Тестирует API получения контакта из сделки.
    
    Args:
        lead_id: ID сделки
        
    Returns:
        Словарь с результатами теста
    """
    url = f"{BASE_URL}/api/amocrm/lead/contact"
    data = {
        "client_id": CLIENT_ID,
        "lead_id": lead_id
    }
    
    logger.info(f"Тестирование API получения контакта из сделки: {lead_id}")
    result = await make_request(url, method="POST", data=data)
    
    if not result:
        logger.error("Нет ответа от API")
        return {"success": False, "message": "Нет ответа от API"}
    
    success = result.get("success", False)
    message = result.get("message", "Нет сообщения")
    
    if success:
        contact_data = result.get("data", {})
        contact_id = contact_data.get("id")
        contact_name = contact_data.get("name", "Имя не указано")
        logger.info(f"API получения контакта работает корректно. Найден контакт: {contact_name} (ID: {contact_id})")
    else:
        logger.error(f"Ошибка с получении контакта: {message}")
    
    return result


async def test_contact_calls(contact_id: int = DEFAULT_CONTACT_ID) -> Dict[str, Any]:
    """
    Тестирует API получения звонков контакта.
    
    Args:
        contact_id: ID контакта
        
    Returns:
        Словарь с результатами теста
    """
    url = f"{BASE_URL}/api/amocrm/contact/calls"
    data = {
        "client_id": CLIENT_ID,
        "contact_id": contact_id
    }
    
    logger.info(f"Тестирование API получения звонков контакта: {contact_id}")
    result = await make_request(url, method="POST", data=data)
    
    if not result:
        logger.error("Нет ответа от API")
        return {"success": False, "message": "Нет ответа от API"}
    
    success = result.get("success", False)
    message = result.get("message", "Нет сообщения")
    
    if success:
        calls_data = result.get("data", {})
        total_calls = calls_data.get("total_calls", 0)
        calls = calls_data.get("calls", [])
        
        logger.info(f"API получения звонков работает корректно. Найдено {total_calls} звонков")
        
        # Выводим информацию о первых 3 звонках
        for i, call in enumerate(calls[:3]):
            note_id = call.get("id") or call.get("note_id")
            created_date = call.get("created_date", "Дата не указана")
            duration = call.get("duration_formatted", "Длительность не указана")
            direction = call.get("direction", "Направление не указано")
            
            logger.info(f"Звонок {i+1}: ID {note_id}, Дата: {created_date}, Длительность: {duration}, Направление: {direction}")
    else:
        logger.error(f"Ошибка с получении звонков: {message}")
    
    return result


async def test_download_transcribe(
    note_id: int = DEFAULT_NOTE_ID,
    lead_id: int = DEFAULT_LEAD_ID,
    contact_id: int = DEFAULT_CONTACT_ID
) -> Dict[str, Any]:
    """
    Тестирует API скачивания и транскрибации звонка.
    
    Args:
        note_id: ID заметки (звонка)
        lead_id: ID сделки
        contact_id: ID контакта
        
    Returns:
        Словарь с результатами теста
    """
    url = f"{BASE_URL}/api/amocrm/contact/call/{note_id}/download-and-transcribe"
    params = f"client_id={CLIENT_ID}&num_speakers=2&lead_id={lead_id}&contact_id={contact_id}"
    full_url = f"{url}?{params}"
    
    logger.info(f"Тестирование API скачивания и транскрибации звонка: {note_id}")
    result = await make_request(full_url)
    
    if not result:
        logger.error("Нет ответа от API")
        return {"success": False, "message": "Нет ответа от API"}
    
    success = result.get("success", False)
    message = result.get("message", "Нет сообщения")
    
    if success:
        transcription_data = result.get("data", {})
        transcription_id = transcription_data.get("id")
        filename = transcription_data.get("filename")
        text_length = len(transcription_data.get("transcription_text", "")) if transcription_data else 0
        
        logger.info(f"API скачивания и транскрибации работает корректно")
        logger.info(f"ID транскрипции: {transcription_id}")
        logger.info(f"Файл: {filename}")
        logger.info(f"Длина текста: {text_length} символов")
    else:
        logger.error(f"Ошибка с скачивании и транскрибации: {message}")
    
    return result


async def test_analyze_call(
    note_id: int = DEFAULT_NOTE_ID,
    lead_id: int = DEFAULT_LEAD_ID,
    contact_id: int = DEFAULT_CONTACT_ID,
    transcription_text: str = None,
    transcription_filename: str = None
) -> Dict[str, Any]:
    """
    Тестирует API анализа звонка.
    
    Args:
        note_id: ID заметки (звонка)
        lead_id: ID сделки
        contact_id: ID контакта
        transcription_text: Текст транскрипции (опционально)
        transcription_filename: Имя файла транскрипции (опционально)
        
    Returns:
        Словарь с результатами теста
    """
    # Если текст транскрипции не передан, сначала получаем его
    if not transcription_text and not transcription_filename:
        logger.info("Текст транскрипции не предоставлен, получаем через API...")
        transcription_result = await test_download_transcribe(note_id, lead_id, contact_id)
        
        if not transcription_result or not transcription_result.get("success", False):
            logger.error("Не удалось получить транскрипцию для анализа")
            return {"success": False, "message": "Не удалось получить транскрипцию для анализа"}
        
        transcription_data = transcription_result.get("data", {})
        transcription_text = transcription_data.get("transcription_text", "")
        transcription_filename = transcription_data.get("filename")
    
    url = f"{BASE_URL}/api/call/analyze"
    data = {
        "client_id": CLIENT_ID,
        "note_id": note_id,
        "lead_id": lead_id,
        "contact_id": contact_id,
        "transcription_filename": transcription_filename,
        "transcription_text": transcription_text,
        "administrator_id": "test_admin",
        "meta_info": {
            "client_source": "test",
            "administrator_name": "Тестовый администратор"
        }
    }
    
    logger.info(f"Тестирование API анализа звонка: {note_id}")
    result = await make_request(url, method="POST", data=data)
    
    if not result:
        logger.error("Нет ответа от API")
        return {"success": False, "message": "Нет ответа от API"}
    
    success = result.get("success", False)
    message = result.get("message", "Нет сообщения")
    
    if success:
        analysis_data = result.get("data", {})
        analysis_id = analysis_data.get("id")
        call_type = analysis_data.get("call_type")
        direction = analysis_data.get("direction")
        overall_score = analysis_data.get("overall_score")
        conversion = analysis_data.get("conversion")
        
        logger.info(f"API анализа звонка работает корректно")
        logger.info(f"ID анализа: {analysis_id}")
        logger.info(f"Тип звонка: {call_type}")
        logger.info(f"Направление: {direction}")
        logger.info(f"Общая оценка: {overall_score}")
        logger.info(f"Конверсия: {'Да' если conversion else 'Нет'}")
    else:
        logger.error(f"Ошибка с анализе звонка: {message}")
    
    return result


async def run_selected_test(test_name: str, **kwargs):
    """
    Запускает указанный тест с переданными параметрами.
    
    Args:
        test_name: Имя теста для запуска
        **kwargs: Дополнительные параметры для теста
    """
    tests = {
        "leads_by_date": test_leads_by_date,
        "lead_contact": test_lead_contact,
        "contact_calls": test_contact_calls,
        "download_transcribe": test_download_transcribe,
        "analyze_call": test_analyze_call,
    }
    
    if test_name not in tests:
        logger.error(f"Неизвестный тест: {test_name}")
        print(f"Доступные тесты: {', '.join(tests.keys())}")
        return
    
    logger.info(f"Запуск теста: {test_name}")
    result = await tests[test_name](**kwargs)
    
    # Вывод результата в форматированном виде
    print(f"\nРезультат теста '{test_name}':")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def parse_args():
    """
    Разбирает аргументы командной строки.
    
    Returns:
        Объект с распарсенными аргументами
    """
    parser = argparse.ArgumentParser(description="Утилита для тестирования API")
    parser.add_argument(
        "test", 
        choices=["leads_by_date", "lead_contact", "contact_calls", "download_transcribe", "analyze_call", "all"],
        help="Тест для запуска"
    )
    parser.add_argument("--date", help="Дата для поиска сделок (формат DD.MM.YYYY)")
    parser.add_argument("--lead-id", type=int, help="ID сделки")
    parser.add_argument("--contact-id", type=int, help="ID контакта")
    parser.add_argument("--note-id", type=int, help="ID заметки (звонка)")
    
    return parser.parse_args()


async def run_all_tests():
    """
    Запускает все тесты последовательно.
    """
    logger.info("=== ЗАПУСК ВСЕХ ТЕСТОВ ===")
    
    # 1. Получение сделок по дате
    leads_result = await test_leads_by_date()
    print(json.dumps(leads_result, ensure_ascii=False, indent=2))
    
    # 2. Получение контакта из сделки
    lead_id = DEFAULT_LEAD_ID
    contact_result = await test_lead_contact(lead_id)
    print(json.dumps(contact_result, ensure_ascii=False, indent=2))
    
    # 3. Получение звонков контакта
    contact_id = DEFAULT_CONTACT_ID
    calls_result = await test_contact_calls(contact_id)
    print(json.dumps(calls_result, ensure_ascii=False, indent=2))
    
    # 4. Скачивание и транскрибация звонка
    note_id = DEFAULT_NOTE_ID
    transcribe_result = await test_download_transcribe(note_id, lead_id, contact_id)
    print(json.dumps(transcribe_result, ensure_ascii=False, indent=2))
    
    # 5. Анализ звонка
    if transcribe_result and transcribe_result.get("success", False):
        transcription_data = transcribe_result.get("data", {})
        transcription_text = transcription_data.get("transcription_text", "")
        transcription_filename = transcription_data.get("filename")
        
        analyze_result = await test_analyze_call(
            note_id, lead_id, contact_id, 
            transcription_text=transcription_text,
            transcription_filename=transcription_filename
        )
        print(json.dumps(analyze_result, ensure_ascii=False, indent=2))
    else:
        logger.error("Не удалось выполнить анализ звонка, так как транскрипция не получена")
    
    logger.info("=== ТЕСТЫ ЗАВЕРШЕНЫ ===")


def main():
    """
    Основная функция для запуска тестов.
    """
    args = parse_args()
    
    try:
        if args.test == "all":
            asyncio.run(run_all_tests())
        else:
            # Собираем параметры для выбранного теста
            kwargs = {}
            if args.date and args.test == "leads_by_date":
                kwargs["date"] = args.date
            if args.lead_id and args.test in ["lead_contact", "download_transcribe", "analyze_call"]:
                kwargs["lead_id"] = args.lead_id
            if args.contact_id and args.test in ["contact_calls", "download_transcribe", "analyze_call"]:
                kwargs["contact_id"] = args.contact_id
            if args.note_id and args.test in ["download_transcribe", "analyze_call"]:
                kwargs["note_id"] = args.note_id
            
            asyncio.run(run_selected_test(args.test, **kwargs))
    except Exception as e:
        logger.error(f"Ошибка с выполнении тестов: {str(e)}")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())