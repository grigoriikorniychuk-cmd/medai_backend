"""
Тестовый скрипт для сравнения производительности различных подходов к обработке данных.
Запускает все три эндпоинта синхронизации с одинаковыми входными параметрами и сравнивает результаты.
"""

import asyncio
import aiohttp
import json
import time
from datetime import datetime
import sys
import os
import tabulate

# Добавляем корневую директорию проекта в путь для импорта
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

# Настройки API
API_HOST = "http://0.0.0.0:8001"  # Замените на фактический адрес API если отличается
SEQUENTIAL_ENDPOINT = f"{API_HOST}/api/calls/sync-by-date"
PARALLEL_ENDPOINT = f"{API_HOST}/api/calls-parallel/sync-by-date"
PARALLEL_BULK_ENDPOINT = f"{API_HOST}/api/calls-parallel-bulk/sync-by-date"

# Параметры запросов
DATE_FORMAT = "%d.%m.%Y"
DEFAULT_DATE = datetime.now().strftime(DATE_FORMAT)

async def make_request(endpoint, date=None, client_id=None, concurrency=5):
    """
    Выполняет запрос к API и возвращает результат
    
    Args:
        endpoint: URL эндпоинта
        date: Дата в формате DD.MM.YYYY
        client_id: ID клиента AmoCRM
        concurrency: Количество параллельных задач (только для параллельных вариантов)
        
    Returns:
        Tuple[Dict, float]: Ответ API и время выполнения запроса
    """
    params = {}
    client_id = "906c06fb-1844-4892-9dc6-6a4e30129fdf"
    if date:
        params["date"] = date
    if client_id:
        params["client_id"] = client_id
    if "parallel" in endpoint:
        params["concurrency"] = concurrency
    
    start_time = time.time()
    
    async with aiohttp.ClientSession() as session:
        async with session.post(endpoint, params=params) as response:
            response_time = time.time() - start_time
            result = await response.json()
            return result, response_time

async def run_tests(date=None, client_id=None, concurrency=5):
    """
    Запускает тесты для всех трех вариантов API и сравнивает результаты
    
    Args:
        date: Дата в формате DD.MM.YYYY
        client_id: ID клиента AmoCRM
        concurrency: Количество параллельных задач
    """
    print(f"\n{'=' * 70}")
    print(f"ТЕСТИРОВАНИЕ ПРОИЗВОДИТЕЛЬНОСТИ ОБРАБОТКИ СДЕЛОК И ЗВОНКОВ")
    print(f"{'=' * 70}")
    print(f"Дата: {date or DEFAULT_DATE}")
    print(f"ID клиента: {client_id or 'не указан'}")
    print(f"Параллельные задачи: {concurrency}")
    print(f"{'-' * 70}")
    
    # Запрос к последовательному API
    print("\n1. Тестирование последовательной обработки...")
    sequential_result, sequential_time = await make_request(
        SEQUENTIAL_ENDPOINT, date, client_id
    )
    
    # Запрос к параллельному API
    print("\n2. Тестирование параллельной обработки...")
    parallel_result, parallel_time = await make_request(
        PARALLEL_ENDPOINT, date, client_id, concurrency
    )
    
    # Запрос к параллельному API с bulk операциями
    print("\n3. Тестирование параллельной обработки с bulk операциями...")
    parallel_bulk_result, parallel_bulk_time = await make_request(
        PARALLEL_BULK_ENDPOINT, date, client_id, concurrency
    )
    
    # Подготавливаем данные для анализа
    sequential_data = sequential_result.get("data", {})
    parallel_data = parallel_result.get("data", {})
    parallel_bulk_data = parallel_bulk_result.get("data", {})
    
    # Создаем таблицу для сравнения производительности
    comparison_table = [
        ["Метрика", "Последовательно", "Параллельно", "Параллельно + Bulk", "Улучшение (Bulk vs Seq.)"],
        ["Время выполнения (с)", 
         f"{sequential_data.get('execution_time', sequential_time):.2f}", 
         f"{parallel_data.get('execution_time', parallel_time):.2f}",
         f"{parallel_bulk_data.get('execution_time', parallel_bulk_time):.2f}",
         f"{(1 - parallel_bulk_data.get('execution_time', parallel_bulk_time) / max(0.001, sequential_data.get('execution_time', sequential_time))) * 100:.1f}%"],
        ["Обработано сделок", 
         sequential_data.get("leads_processed", 0), 
         parallel_data.get("leads_processed", 0),
         parallel_bulk_data.get("leads_processed", 0),
         "—"],
        ["Сохранено звонков", 
         sequential_data.get("calls_saved", 0), 
         parallel_data.get("calls_saved", 0),
         parallel_bulk_data.get("calls_saved", 0),
         "—"],
        ["Сделок со звонками", 
         sequential_data.get("leads_with_calls", 0), 
         parallel_data.get("leads_with_calls", 0),
         parallel_bulk_data.get("leads_with_calls", 0),
         "—"],
        ["Ошибок обработки", 
         sequential_data.get("errors", 0), 
         parallel_data.get("errors", 0),
         parallel_bulk_data.get("errors", 0),
         "—"],
        ["Задач параллельно", 
         "—", 
         parallel_data.get("parallel_tasks", concurrency),
         parallel_bulk_data.get("parallel_tasks", concurrency),
         "—"]
    ]
    
    # Выводим результаты
    print("\n\nРЕЗУЛЬТАТЫ ТЕСТИРОВАНИЯ:")
    print(tabulate.tabulate(comparison_table, headers="firstrow", tablefmt="grid"))
    
    # Анализ производительности
    seq_time = sequential_data.get('execution_time', sequential_time)
    par_time = parallel_data.get('execution_time', parallel_time)
    bulk_time = parallel_bulk_data.get('execution_time', parallel_bulk_time)
    
    print("\n\nАНАЛИЗ ПРОИЗВОДИТЕЛЬНОСТИ:")
    if bulk_time < seq_time:
        speedup = seq_time / bulk_time
        print(f"✅ Параллельная обработка с bulk операциями быстрее в {speedup:.2f} раз!")
        
        # Вычисляем ускорение на одну сделку
        leads_count = parallel_bulk_data.get("leads_processed", 0)
        if leads_count > 0:
            seq_per_lead = seq_time / leads_count
            bulk_per_lead = bulk_time / leads_count
            print(f"⏱️ Время на обработку одной сделки:")
            print(f"   - Последовательно: {seq_per_lead:.2f} сек")
            print(f"   - Параллельно с Bulk: {bulk_per_lead:.2f} сек")
            print(f"   - Ускорение на сделку: {(seq_per_lead - bulk_per_lead):.2f} сек ({(1 - bulk_per_lead/seq_per_lead) * 100:.1f}%)")
    else:
        print(f"⚠️ Параллельная обработка с bulk операциями не показала ускорения!")
    
    # Выводим рекомендации
    print("\nРЕКОМЕНДАЦИИ:")
    if bulk_time < par_time and bulk_time < seq_time:
        print("✅ Использовать параллельную обработку с bulk операциями для максимальной производительности")
    elif par_time < seq_time:
        print("✅ Использовать параллельную обработку для повышения производительности")
        print("❗ Рассмотреть дополнительную оптимизацию операций с базой данных")
    else:
        print("⚠️ Необходима дополнительная оптимизация - параллельная обработка не даёт ожидаемого ускорения")
        print("❗ Возможные причины:")
        print("   - Низкая производительность сети/API AmoCRM")
        print("   - Ограничения на стороне базы данных")
        print("   - Неоптимальные значения параллелизма (попробуйте другие значения concurrency)")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Тест производительности API")
    parser.add_argument("--date", type=str, help=f"Дата в формате {DATE_FORMAT}")
    parser.add_argument("--client_id", type=str, help="ID клиента AmoCRM")
    parser.add_argument("--concurrency", type=int, default=5, help="Количество параллельных задач")
    
    args = parser.parse_args()
    
    # Запускаем тесты
    asyncio.run(run_tests(args.date, args.client_id, args.concurrency)) 