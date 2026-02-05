import os

# ПРИНУДИТЕЛЬНАЯ УСТАНОВКА ЛОКАЛЬНОГО URI ДЛЯ MONGO
# Это необходимо, т.к. скрипт запускается локально, а в .env файле, скорее всего,
# указан URI для Docker-контейнера ('mongodb:27017').
# Эта строка переопределяет переменную окружения ДО того, как ее прочтет amo_credentials.py
os.environ['MONGODB_URI'] = 'mongodb://92.113.151.220:27018/'

import asyncio
import logging
from datetime import datetime
from pathlib import Path

# Используем существующие в проекте модули для конфигурации и работы с AmoCRM
from amo_credentials import get_full_amo_credentials, MONGODB_URI, MONGODB_NAME
from mlab_amo_async.amocrm_client import AsyncAmoCRMClient, AsyncNotesInteraction

# --- НАСТРОЙКИ --- #
CLIENT_ID_TO_TEST = "906c06fb-1844-4892-9dc6-6a4e30129fdf"
LEAD_ID_TO_UPDATE = 45917555  # ID сделки, который вы указали

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

async def main():
    """
    Основная функция для тестирования записи транскрипции в AmoCRM.
    """
    # --- Чтение реальной транскрипции из файла ---
    TRANSCRIPTION_FILENAME = "73432178406_20250502_140143.txt"
    TRANSCRIPTION_PATH = Path("app/data/transcription") / TRANSCRIPTION_FILENAME

    try:
        transcription_text = TRANSCRIPTION_PATH.read_text(encoding='utf-8')
        if not transcription_text.strip():
            logging.error(f"Файл транскрипции '{TRANSCRIPTION_PATH}' пуст.")
            return
        logging.info(f"Успешно прочитан файл транскрипции: {TRANSCRIPTION_PATH}")
    except FileNotFoundError:
        logging.error(f"Файл транскрипции не найден по пути: {TRANSCRIPTION_PATH}")
        return
    except Exception as e:
        logging.error(f"Ошибка при чтении файла транскрипции: {e}")
        return
    # ---

    amo_client = None
    try:
        # 1. Получаем учетные данные через существующую функцию
        logging.info(f"Получение учетных данных для client_id: {CLIENT_ID_TO_TEST} через get_full_amo_credentials")
        credentials = await get_full_amo_credentials(client_id=CLIENT_ID_TO_TEST)
        logging.info(f"Учетные данные для субдомена '{credentials['subdomain']}' успешно получены.")

        # 2. Инициализируем асинхронный клиент
        amo_client = AsyncAmoCRMClient(
            client_id=credentials["client_id"],
            client_secret=credentials["client_secret"],
            subdomain=credentials["subdomain"],
            redirect_url=credentials["redirect_url"],
            mongo_uri=MONGODB_URI,
            db_name=MONGODB_NAME,
        )
        logging.info("Клиент amoCRM успешно инициализирован.")

        # 3. Инициализируем класс для работы с заметками для конкретной сделки
        logging.info(f"Инициализация обработчика заметок для сделки ID: {LEAD_ID_TO_UPDATE}")
        notes_interaction = AsyncNotesInteraction(
            token_manager=amo_client.token_manager,
            entity_type="leads",
            entity_id=LEAD_ID_TO_UPDATE
        )

        # 4. Подготавливаем данные для создания заметки (без entity_id, т.к. он уже в пути)
        note_data = {
            "note_type": "common",  # Обычная текстовая заметка
            "params": {
                "text": transcription_text
            }
        }

        # 5. Выполняем создание заметки через специальный класс
        await notes_interaction.create(note_data)
        logging.info(f"СУПЕР! Заметка с транскрипцией успешно добавлена к сделке #{LEAD_ID_TO_UPDATE}.")
        logging.info("Пожалуйста, проверьте заметки в карточке сделки в AmoCRM!")

    except Exception as e:
        logging.error(f"Произошла ошибка: {e}", exc_info=True)

    finally:
        if amo_client:
            await amo_client.close()
            logging.info("Соединение с amoCRM закрыто.")


if __name__ == "__main__":
    asyncio.run(main())
