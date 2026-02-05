import os
import aiohttp
import logging
from typing import Dict, List, Any, Optional, Union
from bot.config.config import (
    API_URL,
    SYNC_LEADS_API_URL,
    CALLS_LIST_API_URL,
    DOWNLOAD_TRANSCRIBE_CALL_API_URL,
    ANALYZE_CALL_API_URL,
    GENERATE_REPORT_API_URL,
    DOWNLOAD_REPORT_API_URL,
    API_BASE_URL,
    GENERATE_EXCEL_REPORT_API_URL
)
import io
from aiogram.types import InputFile


def _get_headers() -> dict:
    """Возвращает заголовки с API ключом"""
    headers = {}
    api_key = os.getenv("API_KEY")
    if api_key:
        headers["X-API-Key"] = api_key
    return headers


# Функции для работы с клиниками
async def register_clinic(data: Dict[str, Any]) -> Dict:
    """Регистрация новой клиники"""
    async with aiohttp.ClientSession() as session:
        async with session.post(API_URL, json=data, headers=_get_headers()) as response:
            return await response.json()

async def refresh_token(clinic_id: str, client_secret: Optional[str] = None, redirect_url: Optional[str] = None) -> Dict:
    """Обновление токена клиники"""
    params = {}
    if client_secret:
        params["client_secret"] = client_secret
    if redirect_url:
        params["redirect_url"] = redirect_url
        
    url = f"{API_BASE_URL}/admin/clinics/{clinic_id}/refresh-token"
    async with aiohttp.ClientSession() as session:
        async with session.post(url, params=params, headers=_get_headers()) as response:
            return await response.json()

# Функции для работы со звонками
async def sync_calls_by_date(date: str, client_id: str) -> Dict:
    """
    Синхронизация звонков по дате
    
    Args:
        date: Строка даты в формате ДД.ММ.ГГГГ или ГГГГ-ММ-ДД
        client_id: ID клиента AmoCRM
        
    Returns:
        Словарь с результатом синхронизации
    """
    # Проверяем формат даты и логируем его
    date_fmt = "не определен"
    if date:
        if "." in date and len(date) == 10:
            date_fmt = "ДД.ММ.ГГГГ"
        elif "-" in date and len(date) == 10:
            date_fmt = "ГГГГ-ММ-ДД"
            
    params = {"date": date, "client_id": client_id}
    logging.info(f"Отправляем запрос на синхронизацию звонков с параметрами: {params}, формат даты: {date_fmt}, URL: {SYNC_LEADS_API_URL}")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(SYNC_LEADS_API_URL, params=params, headers=_get_headers()) as response:
                status = response.status
                logging.info(f"Получен ответ от сервера, статус: {status}")
                
                # Проверяем успешность запроса
                if status >= 400:
                    content_type = response.content_type
                    error_text = await response.text()
                    logging.error(f"Ошибка API: статус {status}, тип контента {content_type}, текст: {error_text[:200]}...")
                    return {
                        "success": False,
                        "message": f"Ошибка сервера: {status}. Проверьте формат даты и доступность сервера.",
                        "data": None
                    }
                
                # Проверяем тип контента
                if not response.content_type.startswith('application/json'):
                    content_type = response.content_type
                    error_text = await response.text()
                    logging.error(f"Ошибка: неожиданный тип контента {content_type}, текст: {error_text[:200]}...")
                    return {
                        "success": False,
                        "message": f"Получен неожиданный тип контента: {content_type}. Сервер может быть недоступен.",
                        "data": None
                    }
                
                return await response.json()
    except aiohttp.ClientError as e:
        logging.error(f"Ошибка при выполнении запроса: {str(e)}")
        return {
            "success": False,
            "message": f"Ошибка подключения к серверу: {str(e)}",
            "data": None
        }
    except Exception as e:
        logging.error(f"Неожиданная ошибка: {str(e)}")
        return {
            "success": False,
            "message": f"Неожиданная ошибка: {str(e)}",
            "data": None
        }

async def get_calls_list(
    client_id: str, 
    start_date: Optional[str] = None, 
    end_date: Optional[str] = None
) -> Dict:
    """
    Получение списка звонков
    
    Args:
        client_id: ID клиники для фильтрации звонков
        start_date: Начальная дата в формате ДД.ММ.ГГГГ или ГГГГ-ММ-ДД
        end_date: Конечная дата в формате ДД.ММ.ГГГГ или ГГГГ-ММ-ДД
        
    Returns:
        Словарь с результатами запроса
    """
    params = {}
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    if client_id:
        params["client_id"] = client_id
    
    logging.info(f"Запрос списка звонков с параметрами: {params}, URL: {CALLS_LIST_API_URL}")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(CALLS_LIST_API_URL, params=params, headers=_get_headers()) as response:
                status = response.status
                logging.info(f"Получен ответ от сервера, статус: {status}")
                
                # Проверяем успешность запроса
                if status >= 400:
                    content_type = response.content_type
                    error_text = await response.text()
                    logging.error(f"Ошибка API: статус {status}, тип контента {content_type}, текст: {error_text[:200]}...")
                    return {
                        "success": False,
                        "message": f"Ошибка сервера: {status}. Проверьте параметры запроса и доступность сервера.",
                        "data": None
                    }
                
                return await response.json()
    except aiohttp.ClientError as e:
        logging.error(f"Ошибка при выполнении запроса: {str(e)}")
        return {
            "success": False,
            "message": f"Ошибка подключения к серверу: {str(e)}",
            "data": None
        }
    except Exception as e:
        logging.error(f"Неожиданная ошибка: {str(e)}")
        return {
            "success": False,
            "message": f"Неожиданная ошибка: {str(e)}",
            "data": None
        }

async def download_call(call_id: str) -> str:
    """Получение URL для скачивания звонка"""
    return f"{API_BASE_URL}/calls/download/{call_id}"

async def download_and_transcribe_call(call_id: str, num_speakers: int = 2) -> Dict:
    """Скачивание и транскрибация звонка"""
    url = f"{DOWNLOAD_TRANSCRIBE_CALL_API_URL}/{call_id}"
    params = {"num_speakers": num_speakers}
    
    # Используем увеличенный таймаут для ожидания завершения операции
    timeout = aiohttp.ClientTimeout(total=300)  # 5 минут
    
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, params=params, headers=_get_headers()) as response:
            return await response.json()

async def download_transcription(url_or_path: str) -> str:
    """Получение URL для скачивания транскрибации
    
    Может принимать как относительный путь, так и полный URL.
    Также обрабатывает пути вида `/api/transcriptions/filename.txt/download`
    
    Args:
        url_or_path: Относительный путь, полный URL или имя файла
    
    Returns:
        Полный URL для скачивания
    """
    # Если это полный URL, возвращаем как есть
    if url_or_path.startswith("http"):
        return url_or_path
    
    # Проверяем на формат "/api/transcriptions/filename.txt/download"
    if url_or_path.startswith("/api/transcriptions") and "/download" in url_or_path:
        # Это путь, полученный от API сервера непосредственно
        # Получаем имя файла между "/api/transcriptions/" и "/download"
        parts = url_or_path.split("/")
        if len(parts) >= 4:
            filename = parts[-2]  # Получаем имя файла из пути
            return f"{API_BASE_URL}/transcriptions/{filename}/download"
    
    # Если переданный параметр не содержит слеш, считаем что это просто имя файла
    if "/" not in url_or_path:
        return f"{API_BASE_URL}/transcriptions/{url_or_path}/download"
    
    # Если это относительный путь, начинающийся с /api, убираем /api, так как API_BASE_URL уже содержит его
    if url_or_path.startswith("/api"):
        url_or_path = url_or_path[4:]  # Убираем '/api' из пути
    
    # Если путь начинается с /, убираем его
    if url_or_path.startswith("/"):
        url_or_path = url_or_path[1:]
        
    # Формируем полный URL
    return f"{API_BASE_URL}/{url_or_path}"

async def analyze_call(call_id: str) -> Dict:
    """Анализ звонка через LLM"""
    url = f"{ANALYZE_CALL_API_URL}/{call_id}"
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=_get_headers()) as response:
            return await response.json()

# Функции для работы с отчетами
async def generate_report(report_data: Dict[str, Any]) -> Dict:
    """Генерация отчета"""
    async with aiohttp.ClientSession() as session:
        async with session.post(GENERATE_REPORT_API_URL, json=report_data, headers=_get_headers()) as response:
            return await response.json()

async def download_report(url_or_path: str) -> str:
    """Получение URL для скачивания отчета
    
    Может принимать как относительный путь, так и полный URL.
    Также обрабатывает пути вида `/api/call/reports/filename.pdf/download`
    или `/api/app/data/reports/filename.pdf`
    
    Args:
        url_or_path: Относительный путь, полный URL или имя файла
    
    Returns:
        Полный URL для скачивания
    """
    # Если это полный URL, возвращаем как есть
    if url_or_path.startswith("http"):
        return url_or_path
    
    # Проверяем на формат "/api/call/reports/filename.pdf/download"
    if url_or_path.startswith("/api/call/reports") and "/download" in url_or_path:
        # Это путь, полученный от API сервера непосредственно
        # Получаем имя файла между "/api/call/reports/" и "/download"
        parts = url_or_path.split("/")
        if len(parts) >= 4:
            filename = parts[-2]  # Получаем имя файла из пути
            return f"{API_BASE_URL}/call/reports/{filename}/download"
    
    # Проверяем на формат "/api/app/data/reports/filename.pdf"
    if (url_or_path.startswith("/api/app/data/reports") or 
        url_or_path.startswith("api/app/data/reports")):
        # Получаем имя файла из пути
        parts = url_or_path.split("/")
        if len(parts) >= 4:
            filename = parts[-1]  # Получаем имя файла из пути
            return f"{API_BASE_URL}/call/reports/{filename}/download"
    
    # Если переданный параметр не содержит слеш, считаем что это просто имя файла
    if "/" not in url_or_path:
        return f"{API_BASE_URL}/call/reports/{url_or_path}/download"
    
    # Если это относительный путь, начинающийся с /api, убираем /api, так как API_BASE_URL уже содержит его
    if url_or_path.startswith("/api"):
        url_or_path = url_or_path[4:]  # Убираем '/api' из пути
    
    # Если путь начинается с /, убираем его
    if url_or_path.startswith("/"):
        url_or_path = url_or_path[1:]
    
    # Проверяем, является ли путь путем к отчету, но без /download в конце
    if "reports" in url_or_path and not url_or_path.endswith("/download"):
        # Получаем имя файла из пути
        parts = url_or_path.split("/")
        filename = parts[-1]
        return f"{API_BASE_URL}/call/reports/{filename}/download"
        
    # Формируем полный URL
    return f"{API_BASE_URL}/{url_or_path}" 

async def generate_excel_report(report_data: Dict[str, Any]) -> Optional[str]:
    """
    Генерация Excel-отчета, возвращает имя файла
    """
    async with aiohttp.ClientSession() as session:
        async with session.get(GENERATE_EXCEL_REPORT_API_URL, params=report_data, headers=_get_headers()) as response:
            if response.status == 200:
                result = await response.json()
                return result.get("filename")
            else:
                logging.error(f"Ошибка генерации Excel-отчета: {response.status}")
                return None