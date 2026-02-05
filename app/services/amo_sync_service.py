import logging
from pathlib import Path
from bson import ObjectId
from datetime import datetime

from .mongodb_service import mongodb_service
from ..settings.paths import TRANSCRIPTION_DIR
from app.services.amo_credentials import get_full_amo_credentials, MONGODB_URI, MONGODB_NAME
from mlab_amo_async.amocrm_client import AsyncAmoCRMClient, AsyncNotesInteraction

logger = logging.getLogger(__name__)

async def sync_transcription_to_amo(call_id: str):
    """
    Находит звонок по call_id, читает его транскрипцию и отправляет ее в виде заметки в AmoCRM.
    Предотвращает дубликаты - проверяет флаг amo_transcription_synced перед отправкой.
    """
    logger.info(f"Запуск синхронизации транскрипции для call_id: {call_id}")
    amo_client = None
    try:
        # 1. Найти документ звонка в MongoDB
        calls_collection = mongodb_service.db["calls"]
        call_doc = await calls_collection.find_one({"_id": ObjectId(call_id)})

        if not call_doc:
            logger.error(f"Звонок с call_id: {call_id} не найден в MongoDB.")
            return

        # Проверка: уже синхронизирован?
        if call_doc.get("amo_transcription_synced"):
            logger.info(f"Транскрипция для звонка {call_id} уже синхронизирована с AmoCRM (note_id: {call_doc.get('amo_transcription_note_id')}). Пропускаем.")
            return

        lead_id = call_doc.get("lead_id")
        client_id = call_doc.get("client_id")
        filename_transcription = call_doc.get("filename_transcription")

        if not all([lead_id, client_id, filename_transcription]):
            logger.error(f"В документе звонка {call_id} отсутствуют необходимые поля: lead_id, client_id или filename_transcription.")
            return

        # 2. Прочитать файл транскрипции
        transcription_path = Path(TRANSCRIPTION_DIR) / filename_transcription
        if not transcription_path.exists():
            logger.error(f"Файл транскрипции не найден: {transcription_path}")
            return

        transcription_text = transcription_path.read_text(encoding='utf-8').strip()
        if not transcription_text:
            logger.warning(f"Файл транскрипции {transcription_path} пуст.")
            return
        
        full_transcription_text = f"Транскрипция звонка:\n\n{transcription_text}"

        # 3. Инициализировать AmoCRM клиент
        credentials = await get_full_amo_credentials(client_id=client_id)
        amo_client = AsyncAmoCRMClient(
            client_id=credentials["client_id"],
            client_secret=credentials["client_secret"],
            subdomain=credentials["subdomain"],
            redirect_url=credentials["redirect_url"],
            mongo_uri=MONGODB_URI,
            db_name=MONGODB_NAME
        )

        # 4. Создать заметку в сделке
        notes_interaction = AsyncNotesInteraction(
            token_manager=amo_client.token_manager,
            entity_type="leads",
            entity_id=lead_id
        )
        note_data = {
            "note_type": "common",
            "params": {
                "text": full_transcription_text
            }
        }
        created_note = await notes_interaction.create(note_data)
        created_note_id = created_note.get("id") if isinstance(created_note, dict) else None
        
        logger.info(f"Транскрипция для звонка {call_id} успешно добавлена как заметка к сделке {lead_id} (note_id: {created_note_id}).")
        
        # 5. Сохраняем флаг синхронизации в MongoDB
        await calls_collection.update_one(
            {"_id": ObjectId(call_id)},
            {
                "$set": {
                    "amo_transcription_synced": True,
                    "amo_transcription_note_id": created_note_id,
                    "amo_transcription_synced_at": datetime.now()
                }
            }
        )
        logger.info(f"Флаг синхронизации установлен для call_id: {call_id}")

    except Exception as e:
        logger.error(f"Ошибка при синхронизации транскрипции для call_id {call_id}: {e}", exc_info=True)
    finally:
        if amo_client:
            await amo_client.close()
