"""
Пересчёт администраторов за 2 февраля 2026 через AI.
Запуск на сервере: docker exec -it medai-api python -m scripts.recalc_admins_feb2
"""

import asyncio
import os
import sys
import logging
from datetime import date

# Добавляем корень проекта в sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from motor.motor_asyncio import AsyncIOMotorClient
from app.settings.paths import MONGO_URI, DB_NAME, TRANSCRIPTION_DIR
from app.services.admin_detection_service import determine_administrator_for_call

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATES = ["2026-02-02"]
DATE_MAP = {
    "2026-02-02": date(2026, 2, 2),
}

# Клиники с ai_schedule
AI_SCHEDULE_CLIENTS = {
    "9476ab76-c2a6-4fef-b4f8-33e1284ef261",  # newdental
    "00a48347-547b-4c47-9484-b20243b05643",  # perfettoclinic78
    "3306c1e4-6022-45e3-b7b7-45646a8a5db6",  # stomdv
    "4c640248-8904-412e-ae85-14dda10edd1b",  # iqdentalclinic
}


async def main():
    client = AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]

    calls = await db.calls.find({
        "created_date_for_filtering": {"$in": DATES},
        "transcription_status": "success",
        "client_id": {"$in": list(AI_SCHEDULE_CLIENTS)},
        "administrator": "Неизвестный администратор",
    }).to_list(length=None)

    logger.info(f"Найдено {len(calls)} звонков для пересчёта")

    updated = 0
    errors = 0
    unchanged = 0
    semaphore = asyncio.Semaphore(5)  # Ограничиваем параллельность

    async def process_call(call):
        nonlocal updated, errors, unchanged
        async with semaphore:
            note_id = call["note_id"]
            client_id = call["client_id"]
            old_admin = call.get("administrator", "")
            call_date_str = call["created_date_for_filtering"]
            call_date = DATE_MAP[call_date_str]

            # Загружаем транскрипцию
            fn = call.get("filename_transcription")
            if not fn:
                logger.warning(f"note_id={note_id}: нет filename_transcription, пропуск")
                return

            path = os.path.join(TRANSCRIPTION_DIR, fn)
            if not os.path.exists(path):
                logger.warning(f"note_id={note_id}: файл {fn} не найден, пропуск")
                return

            try:
                with open(path, "r", encoding="utf-8") as f:
                    text = f.read()
            except Exception as e:
                logger.error(f"note_id={note_id}: ошибка чтения {fn}: {e}")
                errors += 1
                return

            try:
                new_admin = await determine_administrator_for_call(
                    clinic_id=client_id,
                    call_date=call_date,
                    transcription_text=text,
                )
            except Exception as e:
                logger.error(f"note_id={note_id}: ошибка AI: {e}")
                errors += 1
                return

            if new_admin == old_admin:
                unchanged += 1
                return

            logger.info(f"note_id={note_id}: '{old_admin}' → '{new_admin}'")
            await db.calls.update_one(
                {"_id": call["_id"]},
                {"$set": {"administrator": new_admin}}
            )
            updated += 1

    # Запускаем батчами по 20
    batch_size = 20
    for i in range(0, len(calls), batch_size):
        batch = calls[i:i + batch_size]
        tasks = [process_call(c) for c in batch]
        await asyncio.gather(*tasks)
        logger.info(f"Прогресс: {min(i + batch_size, len(calls))}/{len(calls)} "
                     f"(обновлено={updated}, без изменений={unchanged}, ошибки={errors})")

    logger.info(f"\nИТОГО: обновлено={updated}, без изменений={unchanged}, ошибки={errors}")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
