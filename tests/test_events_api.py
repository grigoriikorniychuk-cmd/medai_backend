import asyncio
import os
from datetime import datetime, timedelta, timezone
import logging
from dotenv import load_dotenv
from app.services.amocrm.client import AsyncAmoCRMClient

# Настройка логирования
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def test_events_api():
    """Тестирование API Events для получения звонков"""
    
    # Загрузка переменных окружения
    load_dotenv()
    
    # Получаем клиент AmoCRM
    client = AsyncAmoCRMClient(
        client_id=os.getenv("AMO_CLIENT_ID"),
        client_secret=os.getenv("AMO_CLIENT_SECRET"), 
        subdomain=os.getenv("AMO_SUBDOMAIN"),
        redirect_url=os.getenv("AMO_REDIRECT_URL"),
        mongo_uri=os.getenv("MONGO_URI"),
        db_name=os.getenv("DB_NAME")
    )
    
    # Определяем период запроса (вчера и сегодня)
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=1)
    
    # Параметры запроса к API events
    events_params = {
        "limit": 50,
        "page": 1,
        "filter[created_at][from]": int(start_date.timestamp()),
        "filter[created_at][to]": int(end_date.timestamp()),
        "filter[type]": "outgoing_call,incoming_call"  # Типы событий звонков
    }
    
    # Выполняем запрос к API events
    logger.info(f"Запрос к API /api/v4/events с параметрами: {events_params}")
    resp, status = await client.request("get", "api/v4/events", params=events_params)
    
    # Проверяем ответ
    if status != 200:
        logger.error(f"API events вернул статус {status}: {resp}")
        return
    
    # Обрабатываем ответ
    if "_embedded" in resp and "events" in resp["_embedded"]:
        events = resp["_embedded"]["events"]
        logger.info(f"Получено {len(events)} событий звонков")
        
        # Выводим пример структуры события для анализа
        if len(events) > 0:
            logger.info(f"Пример структуры события: {events[0]}")
            
            # Анализируем все типы событий
            event_types = {}
            for event in events:
                event_type = event.get("type")
                if event_type not in event_types:
                    event_types[event_type] = 0
                event_types[event_type] += 1
            
            logger.info(f"Найденные типы событий: {event_types}")
    else:
        logger.warning("Не найдено событий звонков в ответе API")

if __name__ == "__main__":
    asyncio.run(test_events_api())
