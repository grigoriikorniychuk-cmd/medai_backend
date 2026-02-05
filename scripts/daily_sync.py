#!/usr/bin/env python3
"""
Скрипт для ежедневной автоматической синхронизации, транскрибации и анализа звонков.
Запускается по расписанию через cron.
"""

import os
import sys
import asyncio
import logging
from datetime import datetime, timedelta
import httpx
from typing import Dict, Any, Optional
from dotenv import load_dotenv

# Создаем директорию для логов, если её нет
log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'daily_sync.log')

# Настройка логирования
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Форматтер для логов
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Обработчик для вывода в консоль
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)

# Обработчик для записи в файл
file_handler = logging.FileHandler(log_file, encoding='utf-8')
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(formatter)

# Добавляем обработчики к логгеру
logger.addHandler(console_handler)
logger.addHandler(file_handler)

logger.info(f"Логирование инициализировано. Логи будут записаны в: {log_file}")

# Загрузка переменных окружения
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

# Конфигурация API
BASE_URL = os.getenv('BASE_URL', 'http://localhost:8001')
CLIENT_ID = os.getenv('CLIENT_ID')
CONCURRENCY = int(os.getenv('CONCURRENCY', '5'))  # Значение по умолчанию 5

if not CLIENT_ID:
    logger.error("Не установлен CLIENT_ID в переменных окружения")
    sys.exit(1)

# Заголовки для запросов
HEADERS = {
    "Content-Type": "application/json",
    "accept": "application/json",
}
_api_key = os.getenv("API_KEY")
if _api_key:
    HEADERS["X-API-Key"] = _api_key


async def call_api(endpoint: str, method: str = 'post', params: Optional[Dict] = None, json_data: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Универсальная функция для вызова API
    """
    url = f"{BASE_URL.rstrip('/')}/{endpoint.lstrip('/')}"
    
    # Логируем базовую информацию о запросе
    logger.info(f"Вызываем {method.upper()} {url}")
    logger.debug(f"Параметры: {params}")
    if json_data:
        logger.debug(f"Тело запроса: {json_data}")
    
    # Параметры для повторных попыток
    max_retries = 3
    retry_delay = 5  # секунды
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        for attempt in range(max_retries):
            try:
                if method.lower() == 'get':
                    response = await client.get(url, params=params, headers=HEADERS)
                elif method.lower() == 'post':
                    response = await client.post(url, json=json_data, params=params, headers=HEADERS)
                else:
                    raise ValueError(f"Неподдерживаемый метод: {method}")
                
                response.raise_for_status()
                return response.json()
                
            except httpx.HTTPStatusError as e:
                error_msg = f"Ошибка API ({e.response.status_code}): {e.response.text}"
                logger.error(f"Попытка {attempt + 1}/{max_retries} - {error_msg}")
                if attempt == max_retries - 1:  # Последняя попытка
                    raise Exception(error_msg)
                    
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                error_msg = f"Ошибка подключения к {url}: {str(e)}"
                logger.error(f"Попытка {attempt + 1}/{max_retries} - {error_msg}")
                if attempt == max_retries - 1:  # Последняя попытка
                    # Проверяем, доступен ли сервер
                    try:
                        ping_url = f"{BASE_URL.rstrip('/')}/docs"  # или другой эндпоинт для проверки доступности
                        ping = await client.get(ping_url, timeout=5.0)
                        logger.error(f"Сервер доступен, но эндпоинт не отвечает. Статус проверки: {ping.status_code}")
                    except Exception as ping_error:
                        logger.error(f"Сервер недоступен: {str(ping_error)}")
                    
                    raise Exception(f"Не удалось подключиться к API. Проверьте, запущен ли сервер и доступен ли он по адресу {BASE_URL}")
                
                # Ждем перед повторной попыткой
                await asyncio.sleep(retry_delay * (attempt + 1))
                
            except Exception as e:
                error_msg = f"Неожиданная ошибка при вызове {url}: {str(e)}"
                logger.error(f"Попытка {attempt + 1}/{max_retries} - {error_msg}")
                if attempt == max_retries - 1:  # Последняя попытка
                    raise Exception(error_msg)
                
                await asyncio.sleep(retry_delay * (attempt + 1))


async def sync_calls_by_date_range(start_date: str, end_date: str) -> Dict[str, Any]:
    """
    Синхронизация звонков за указанный диапазон дат
    """
    logger.info(f"Запуск синхронизации звонков с {start_date} по {end_date} для клиента {CLIENT_ID}")
    
    # Формируем query-параметры
    # Даты уже должны быть в формате DD.MM.YYYY
    params = {
        "start_date_str": start_date,
        "end_date_str": end_date,
        "client_id": CLIENT_ID,
        "concurrency": str(CONCURRENCY),
        "force_sync": "false"  # Строка, а не булево значение
    }
    
    logger.debug(f"Параметры запроса: {params}")
    
    # Используем POST с пустым телом, как в curl-примере
    response = await call_api(
        '/api/calls-parallel-bulk/sync-by-date-range',
        'post',
        params=params,
        json_data={}  # Пустое тело, как в curl-примере
    )
    
    logger.info(f"Синхронизация завершена: {response}")
    return response


async def transcribe_by_date_range(start_date: str, end_date: str) -> Dict[str, Any]:
    """
    Запуск транскрибации звонков за указанный диапазон дат
    """
    logger.info(f"Запуск транскрибации звонков с {start_date} по {end_date} для клиента {CLIENT_ID}")
    
    # Формируем query-параметры
    params = {
        "start_date_str": start_date,
        "end_date_str": end_date,
        "client_id": CLIENT_ID
    }
    
    logger.debug(f"Параметры запроса транскрибации: {params}")
    
    response = await call_api(
        '/api/calls/transcribe-by-date-range',
        'post',
        params=params,
        json_data={}
    )
    
    return response


async def analyze_by_date_range(start_date: str, end_date: str) -> Dict[str, Any]:
    """
    Запуск анализа звонков за указанный диапазон дат
    """
    logger.info(f"Запуск анализа звонков с {start_date} по {end_date} для клиента {CLIENT_ID}")
    
    # Формируем query-параметры
    params = {
        "start_date_str": start_date,
        "end_date_str": end_date,
        "client_id": CLIENT_ID,
        "skip_processed": "true",  # Строка, а не булево значение
        "background": "true"  # Строка, а не булево значение
    }
    
    logger.debug(f"Параметры запроса анализа: {params}")
    
    response = await call_api(
        '/api/analyze-by-date-range',
        'post',
        params=params,
        json_data={}
    )
    
    return response


async def wait_for_task_completion(task_id: str, task_type: str, check_interval: int = 30) -> None:
    """
    Ожидание завершения фоновой задачи
    """
    logger.info(f"Ожидание завершения задачи {task_type} (ID: {task_id})")
    
    while True:
        try:
            # Здесь должна быть логика проверки статуса задачи
            # В зависимости от API, это может быть отдельный эндпоинт
            # Например: /api/tasks/{task_id}/status
            
            # Временная заглушка - просто ждем 30 секунд
            await asyncio.sleep(check_interval)
            logger.info(f"Задача {task_type} (ID: {task_id}) все еще выполняется...")
            
            # TODO: Добавить реальную проверку статуса задачи
            # Если задача завершена, выходим из цикла
            # if task_is_completed:
            #     logger.info(f"Задача {task_type} (ID: {task_id}) завершена")
            #     break
            
        except Exception as e:
            logger.error(f"Ошибка при проверке статуса задачи: {str(e)}")
            await asyncio.sleep(60)  # Ждем перед повторной попыткой


async def main():
    """
    Основная функция для выполнения всех операций
    """
    # Получаем дату вчерашнего дня (по умолчанию обрабатываем вчерашний день)
    yesterday = datetime.now() - timedelta(days=1)
    date_str = yesterday.strftime('%d.%m.%Y')  # Формат DD.MM.YYYY
    
    logger.info(f"Запуск ежедневной синхронизации за {date_str}")
    logger.info(f"Базовый URL API: {BASE_URL}")
    
    try:
        logger.info("=== НАЧАЛО СИНХРОНИЗАЦИИ ЗВОНКОВ ===")
        sync_result = await sync_calls_by_date_range(date_str, date_str)
        logger.info(f"Результат синхронизации: {sync_result}")
        
        logger.info("=== НАЧАЛО ТРАНСКРИБАЦИИ ===")
        transcribe_result = await transcribe_by_date_range(date_str, date_str)
        logger.info(f"Результат запуска транскрибации: {transcribe_result}")
        
        # Ожидаем завершения транскрибации (если есть ID задачи)
        if transcribe_result and 'task_id' in transcribe_result:
            logger.info(f"Ожидаем завершения транскрибации (ID задачи: {transcribe_result['task_id']})")
            try:
                await wait_for_task_completion(transcribe_result['task_id'], 'transcribe')
                logger.info("Транскрибация успешно завершена")
            except Exception as e:
                logger.error(f"Ошибка при ожидании завершения транскрибации: {str(e)}", exc_info=True)
                # Продолжаем выполнение, даже если транскрибация не удалась
        
        logger.info("=== НАЧАЛО АНАЛИЗА ===")
        analyze_result = await analyze_by_date_range(date_str, date_str)
        logger.info(f"Результат запуска анализа: {analyze_result}")
        
        # Ожидаем завершения анализа (если есть ID задачи)
        if analyze_result and 'task_id' in analyze_result:
            logger.info(f"Ожидаем завершения анализа (ID задачи: {analyze_result['task_id']})")
            try:
                await wait_for_task_completion(analyze_result['task_id'], 'analyze')
                logger.info("Анализ успешно завершен")
            except Exception as e:
                logger.error(f"Ошибка при ожидании завершения анализа: {str(e)}", exc_info=True)
                # Продолжаем выполнение, даже если анализ не удался
        
        logger.info("=== ВСЕ ОПЕРАЦИИ УСПЕШНО ЗАВЕРШЕНЫ ===")
        return 0
        
    except Exception as e:
        logger.critical(f"КРИТИЧЕСКАЯ ОШИБКА: {str(e)}", exc_info=True)
        return 1
    finally:
        # Закрываем все асинхронные ресурсы
        logger.info("Завершение работы скрипта")


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        logger.info(f"Скрипт завершен с кодом {exit_code}")
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("Скрипт остановлен пользователем")
        sys.exit(130)  # Код выхода для SIGINT
    except Exception as e:
        logger.critical(f"НЕОБРАБОТАННОЕ ИСКЛЮЧЕНИЕ: {str(e)}", exc_info=True)
        sys.exit(1)
