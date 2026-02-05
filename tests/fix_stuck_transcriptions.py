#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для исправления застрявших транскрибаций
"""

import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from amo_credentials import MONGODB_NAME
MONGODB_URI = 'mongodb://92.113.151.220:27018/'

async def fix_stuck():
    client = AsyncIOMotorClient(MONGODB_URI)
    db = client[MONGODB_NAME]
    calls = db.calls
    
    print("\n🔧 Исправление застрявших транскрибаций...\n")
    
    # 1. Сбрасываем звонки из processing в pending
    result1 = await calls.update_many(
        {
            "client_id": "00a48347-547b-4c47-9484-b20243b05643",
            "created_date_for_filtering": "2025-10-03",
            "transcription_status": "processing"
        },
        {
            "$set": {"transcription_status": "pending"}
        }
    )
    print(f"✅ Сброшено из 'processing' в 'pending': {result1.modified_count} звонков")
    
    # 2. Проверяем звонки без статуса - есть ли у них call_link
    no_status_calls = []
    async for call in calls.find({
        "client_id": "00a48347-547b-4c47-9484-b20243b05643",
        "created_date_for_filtering": "2025-10-03",
        "$or": [
            {"transcription_status": {"$exists": False}},
            {"transcription_status": None},
            {"transcription_status": ""}
        ]
    }).limit(5):
        no_status_calls.append({
            "_id": str(call["_id"]),
            "has_call_link": bool(call.get("call_link")),
            "call_link": call.get("call_link", "")[:80] if call.get("call_link") else "N/A",
            "has_transcription": bool(call.get("filename_transcription"))
        })
    
    print(f"\n🔍 Примеры звонков БЕЗ статуса:")
    for call in no_status_calls:
        print(f"  ID: {call['_id']}")
        print(f"    - call_link: {call['call_link']}")
        print(f"    - has_call_link: {call['has_call_link']}")
        print(f"    - has_transcription: {call['has_transcription']}")
    
    # 3. Устанавливаем pending для звонков без статуса, которые имеют call_link
    result2 = await calls.update_many(
        {
            "client_id": "00a48347-547b-4c47-9484-b20243b05643",
            "created_date_for_filtering": "2025-10-03",
            "$or": [
                {"transcription_status": {"$exists": False}},
                {"transcription_status": None},
                {"transcription_status": ""}
            ],
            "call_link": {"$exists": True, "$ne": None, "$ne": ""}
        },
        {
            "$set": {"transcription_status": "pending"}
        }
    )
    print(f"\n✅ Установлен статус 'pending' для звонков с call_link: {result2.modified_count} звонков")
    
    # 4. Итоговая статистика
    pending = await calls.count_documents({
        "client_id": "00a48347-547b-4c47-9484-b20243b05643",
        "created_date_for_filtering": "2025-10-03",
        "transcription_status": "pending"
    })
    
    success = await calls.count_documents({
        "client_id": "00a48347-547b-4c47-9484-b20243b05643",
        "created_date_for_filtering": "2025-10-03",
        "transcription_status": "success"
    })
    
    print(f"\n📊 Финальная статистика:")
    print(f"✅ Success: {success}")
    print(f"⏱ Pending (готовы к обработке): {pending}")
    print(f"\n💡 Теперь запустите транскрибацию с фронта с force_transcribe=false")
    
    client.close()

if __name__ == "__main__":
    asyncio.run(fix_stuck())
