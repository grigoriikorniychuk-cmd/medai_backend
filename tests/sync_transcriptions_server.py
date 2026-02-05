"""
Скрипт для синхронизации транскрипций на ПРОДАКШН СЕРВЕРЕ.
Запускается НАПРЯМУЮ на сервере, где есть доступ к файлам транскрипций.
"""
import asyncio
from bson import ObjectId
from datetime import datetime

# Целевые клиники
TARGET_CLIENT_IDS = [
    "4cdd8fc0-c5fa-4c3c-a2a8-19b062f37fc9",  # Клиника Киров
    "3306c1e4-6022-45e3-b7b7-45646a8a5db6"   # Новая клиника
]

async def sync_transcriptions_on_server():
    """
    Синхронизирует готовые транскрипции с AmoCRM.
    Использует ПРОДАКШН mongodb_service и amo_sync_service.
    """
    from app.services.mongodb_service import mongodb_service
    from app.services.amo_sync_service import sync_transcription_to_amo
    from collections import Counter
    
    print(f"\n{'='*80}")
    print(f"🔄 СИНХРОНИЗАЦИЯ ТРАНСКРИПЦИЙ С AmoCRM (НА СЕРВЕРЕ)")
    print(f"{'='*80}\n")
    print(f"📌 Целевые клиники:")
    for idx, client_id in enumerate(TARGET_CLIENT_IDS, 1):
        print(f"  {idx}. {client_id}")
    print()
    
    # Ищем звонки с готовой транскрипцией, но не синхронизированные
    calls_collection = mongodb_service.db["calls"]
    
    query = {
        "client_id": {"$in": TARGET_CLIENT_IDS},
        "transcription_status": "success",
        "filename_transcription": {"$exists": True, "$ne": None, "$ne": ""},
        "$or": [
            {"amo_transcription_synced": {"$exists": False}},
            {"amo_transcription_synced": False}
        ]
    }
    
    calls = await calls_collection.find(query).to_list(length=10000)
    
    if not calls:
        print("✅ Нет транскрипций для синхронизации")
        return
    
    # Статистика по клиникам
    clinic_counts = Counter(call.get("client_id") for call in calls)
    
    print(f"📊 Найдено транскрипций для синхронизации: {len(calls)}")
    print(f"\n📋 Распределение по клиникам:")
    for client_id, count in clinic_counts.items():
        print(f"  • {client_id}: {count} транскрипций")
    print()
    
    # Подтверждение
    print(f"⚠️  ВНИМАНИЕ: Будет синхронизировано {len(calls)} транскрипций!")
    print(f"   Это займёт примерно {len(calls) * 0.5 / 60:.1f} минут")
    print()
    
    response = input("Продолжить? (yes/no): ")
    if response.lower() != "yes":
        print("❌ Отменено")
        return
    
    print()
    synced_count = 0
    failed_count = 0
    skipped_count = 0
    
    for idx, call in enumerate(calls, 1):
        call_id = str(call["_id"])
        lead_id = call.get("lead_id")
        phone = call.get("phone", "Неизвестно")
        
        print(f"[{idx}/{len(calls)}] Синхронизация звонка:")
        print(f"  • call_id: {call_id}")
        print(f"  • lead_id: {lead_id}")
        print(f"  • phone: {phone}")
        print(f"  • transcription: {call.get('filename_transcription')}")
        
        try:
            # Используем продакшн функцию
            await sync_transcription_to_amo(call_id)
            synced_count += 1
            print(f"  ✅ Синхронизирована\n")
        except FileNotFoundError as e:
            skipped_count += 1
            print(f"  ⏭️  Файл не найден, пропускаем\n")
        except Exception as e:
            failed_count += 1
            print(f"  ❌ Ошибка: {str(e)[:100]}\n")
        
        # Задержка между запросами
        if idx < len(calls):
            await asyncio.sleep(0.5)
        
        # Промежуточная статистика каждые 100 звонков
        if idx % 100 == 0:
            print(f"\n--- Промежуточная статистика ---")
            print(f"Обработано: {idx}/{len(calls)}")
            print(f"✅ Синхронизировано: {synced_count}")
            print(f"❌ Ошибок: {failed_count}")
            print(f"⏭️  Пропущено: {skipped_count}")
            print(f"---------------------------------\n")
    
    print(f"\n{'='*80}")
    print(f"📊 ИТОГИ СИНХРОНИЗАЦИИ")
    print(f"{'='*80}")
    print(f"✅ Синхронизировано: {synced_count}")
    print(f"❌ Ошибок: {failed_count}")
    print(f"⏭️  Пропущено (файл не найден): {skipped_count}")
    print(f"📊 Всего обработано: {len(calls)}")
    print(f"{'='*80}\n")

if __name__ == "__main__":
    asyncio.run(sync_transcriptions_on_server())
