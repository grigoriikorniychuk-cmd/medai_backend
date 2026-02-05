#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Очистка всех мусорных записей (API эндпоинты заметок) из базы
"""

import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from amo_credentials import MONGODB_NAME
MONGODB_URI = 'mongodb://92.113.151.220:27018/'

async def cleanup():
    client = AsyncIOMotorClient(MONGODB_URI)
    db = client[MONGODB_NAME]
    calls = db.calls
    
    print("\n🔍 Поиск мусорных записей (API эндпоинты заметок)...\n")
    
    # Находим все записи с API эндпоинтами заметок
    count_before = await calls.count_documents({
        "call_link": {"$regex": ".*api/v4/contacts/.*/notes.*", "$options": "i"},
        "transcription_status": {"$nin": ["failed"]}
    })
    
    print(f"Найдено мусорных записей: {count_before}")
    
    if count_before > 0:
        # Помечаем как failed
        result = await calls.update_many(
            {
                "call_link": {"$regex": ".*api/v4/contacts/.*/notes.*", "$options": "i"},
                "transcription_status": {"$nin": ["failed"]}
            },
            {
                "$set": {
                    "transcription_status": "failed",
                    "transcription_error": "Invalid call_link: это API эндпоинт заметки AmoCRM, а не аудиофайл"
                }
            }
        )
        
        print(f"✅ Помечено как failed: {result.modified_count} записей\n")
        
        # Показываем примеры
        print("Примеры помеченных записей:")
        async for call in calls.find({
            "call_link": {"$regex": ".*api/v4/contacts/.*/notes.*", "$options": "i"},
            "transcription_status": "failed"
        }).limit(3):
            print(f"  - ID: {call['_id']}")
            print(f"    Дата: {call.get('created_date_for_filtering', 'N/A')}")
            print(f"    call_link: {call.get('call_link', '')[:80]}")
            print()
    else:
        print("✅ Мусорных записей не найдено!")
    
    client.close()

if __name__ == "__main__":
    asyncio.run(cleanup())
