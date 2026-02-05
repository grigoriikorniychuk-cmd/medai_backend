"""
Скрипт для синхронизации уже готовых транскрипций с AmoCRM.
Находит звонки с готовой транскрипцией, которые ещё не синхронизированы.
"""
import asyncio
import sys
import os
from pathlib import Path
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
from bson import ObjectId
from collections import Counter

# Добавляем путь к модулям
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MONGO_URI = "mongodb://92.113.151.220:27018/"
DB_NAME = "medai"

# Целевые клиники
TARGET_CLIENT_IDS = [
    "4cdd8fc0-c5fa-4c3c-a2a8-19b062f37fc9",  # Клиника Киров
    "3306c1e4-6022-45e3-b7b7-45646a8a5db6"   # Новая клиника
]


async def sync_transcription_to_amo_local(call_doc, mongo_client):
    """
    Локальная версия синхронизации для тестового скрипта.
    Использует прямое подключение к MongoDB.
    """
    from amo_credentials import get_full_amo_credentials
    from mlab_amo_async.amocrm_client import AsyncAmoCRMClient, AsyncNotesInteraction
    
    call_id = str(call_doc["_id"])
    amo_client = None
    
    try:
        # Проверка: уже синхронизирован?
        if call_doc.get("amo_transcription_synced"):
            print(f"  ⏭️  Уже синхронизирована (note_id: {call_doc.get('amo_transcription_note_id')})")
            return True
        
        lead_id = call_doc.get("lead_id")
        client_id = call_doc.get("client_id")
        filename_transcription = call_doc.get("filename_transcription")
        
        if not all([lead_id, client_id, filename_transcription]):
            print(f"  ❌ Отсутствуют необходимые поля")
            return False
        
        # Прочитать файл транскрипции
        transcription_path = Path('app/data/transcription') / filename_transcription
        if not transcription_path.exists():
            print(f"  ❌ Файл транскрипции не найден: {transcription_path}")
            return False
        
        transcription_text = transcription_path.read_text(encoding='utf-8').strip()
        if not transcription_text:
            print(f"  ❌ Файл транскрипции пуст")
            return False
        
        full_transcription_text = f"Транскрипция звонка:\\n\\n{transcription_text}"
        
        # Инициализировать AmoCRM клиент
        credentials = await get_full_amo_credentials(client_id=client_id)
        amo_client = AsyncAmoCRMClient(
            client_id=credentials["client_id"],
            client_secret=credentials["client_secret"],
            subdomain=credentials["subdomain"],
            redirect_url=credentials["redirect_url"],
            mongo_uri=MONGO_URI,
            db_name=DB_NAME
        )
        
        # Создать заметку в сделке
        notes_interaction = AsyncNotesInteraction(
            token_manager=amo_client.token_manager,
            entity_type="leads",
            entity_id=lead_id
        )
        note_data = {
            "note_type": "common",
            "params": {"text": full_transcription_text}
        }
        created_note = await notes_interaction.create(note_data)
        created_note_id = created_note.get("id") if isinstance(created_note, dict) else None
        
        # Сохраняем флаг синхронизации
        db = mongo_client[DB_NAME]
        calls_collection = db["calls"]
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
        
        return True
        
    except Exception as e:
        print(f"  ❌ Ошибка: {str(e)}")
        return False
    finally:
        if amo_client:
            await amo_client.close()

async def sync_transcriptions():
    """Синхронизирует готовые транскрипции с AmoCRM."""
    mongo_client = AsyncIOMotorClient(MONGO_URI)
    db = mongo_client[DB_NAME]
    calls_collection = db.calls
    
    print(f"\n{'='*80}")
    print(f"🔄 СИНХРОНИЗАЦИЯ ТРАНСКРИПЦИЙ С AmoCRM")
    print(f"{'='*80}\n")
    print(f"📌 Целевые клиники:")
    for idx, client_id in enumerate(TARGET_CLIENT_IDS, 1):
        print(f"  {idx}. {client_id}")
    print()
    
    # Ищем звонки с готовой транскрипцией, но не синхронизированные (только для целевых клиник)
    query = {
        "client_id": {"$in": TARGET_CLIENT_IDS},
        "transcription_status": "success",
        "filename_transcription": {"$exists": True, "$ne": None, "$ne": ""},
        "$or": [
            {"amo_transcription_synced": {"$exists": False}},
            {"amo_transcription_synced": False}
        ]
    }
    
    calls = await calls_collection.find(query).to_list(length=10000)  # Увеличиваем лимит
    
    if not calls:
        print("✅ Нет транскрипций для синхронизации")
        mongo_client.close()
        return
    
    # Статистика по клиникам
    from collections import Counter
    clinic_counts = Counter(call.get("client_id") for call in calls)
    
    print(f"📊 Найдено транскрипций для синхронизации: {len(calls)}")
    print(f"\n📋 Распределение по клиникам:")
    for client_id, count in clinic_counts.items():
        print(f"  • {client_id}: {count} транскрипций")
    print()
    
    synced_count = 0
    failed_count = 0
    
    for idx, call in enumerate(calls, 1):
        call_id = str(call["_id"])
        lead_id = call.get("lead_id")
        phone = call.get("phone", "Неизвестно")
        
        print(f"[{idx}/{len(calls)}] Синхронизация звонка:")
        print(f"  • call_id: {call_id}")
        print(f"  • lead_id: {lead_id}")
        print(f"  • phone: {phone}")
        print(f"  • transcription: {call.get('filename_transcription')}")
        
        result = await sync_transcription_to_amo_local(call, mongo_client)
        if result:
            synced_count += 1
            print(f"  ✅ Синхронизирована\n")
        else:
            failed_count += 1
            print()
        
        # Небольшая задержка между запросами
        if idx < len(calls):
            await asyncio.sleep(0.5)
    
    print(f"\n{'='*80}")
    print(f"📊 ИТОГИ СИНХРОНИЗАЦИИ")
    print(f"{'='*80}")
    print(f"✅ Синхронизировано: {synced_count}")
    print(f"❌ Ошибок: {failed_count}")
    print(f"📊 Всего обработано: {len(calls)}")
    print(f"{'='*80}\n")
    
    mongo_client.close()

if __name__ == "__main__":
    asyncio.run(sync_transcriptions())
