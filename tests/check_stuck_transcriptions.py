#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для проверки застрявших транскрибаций
"""

import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from amo_credentials import MONGODB_NAME

MONGODB_URI = 'mongodb://92.113.151.220:27018/'

async def check_stuck():
    client = AsyncIOMotorClient(MONGODB_URI)
    db = client[MONGODB_NAME]
    calls = db.calls
    
    # Ищем звонки в статусе processing
    processing = await calls.count_documents({
        "client_id": "00a48347-547b-4c47-9484-b20243b05643",
        "created_date_for_filtering": "2025-10-03",
        "transcription_status": "processing"
    })
    
    # Ищем звонки в статусе pending
    pending = await calls.count_documents({
        "client_id": "00a48347-547b-4c47-9484-b20243b05643",
        "created_date_for_filtering": "2025-10-03",
        "transcription_status": "pending"
    })
    
    # Ищем звонки без статуса или пустой статус
    no_status = await calls.count_documents({
        "client_id": "00a48347-547b-4c47-9484-b20243b05643",
        "created_date_for_filtering": "2025-10-03",
        "$or": [
            {"transcription_status": {"$exists": False}},
            {"transcription_status": None},
            {"transcription_status": ""}
        ]
    })
    
    # Ищем успешные
    success = await calls.count_documents({
        "client_id": "00a48347-547b-4c47-9484-b20243b05643",
        "created_date_for_filtering": "2025-10-03",
        "transcription_status": "success"
    })
    
    # Ищем failed
    failed = await calls.count_documents({
        "client_id": "00a48347-547b-4c47-9484-b20243b05643",
        "created_date_for_filtering": "2025-10-03",
        "transcription_status": "failed"
    })
    
    total = await calls.count_documents({
        "client_id": "00a48347-547b-4c47-9484-b20243b05643",
        "created_date_for_filtering": "2025-10-03"
    })
    
    print(f"\n📊 Статистика звонков за 03.10.2025:")
    print(f"Всего звонков: {total}")
    print(f"✅ Success: {success}")
    print(f"❌ Failed: {failed}")
    print(f"⏳ Processing: {processing}")
    print(f"⏱ Pending: {pending}")
    print(f"❓ Без статуса: {no_status}")
    
    # Показываем несколько застрявших в processing
    if processing > 0:
        print(f"\n🔍 Примеры звонков в статусе 'processing':")
        async for call in calls.find({
            "client_id": "00a48347-547b-4c47-9484-b20243b05643",
            "created_date_for_filtering": "2025-10-03",
            "transcription_status": "processing"
        }).limit(5):
            print(f"  - ID: {call['_id']}, call_link: {call.get('call_link', 'N/A')[:50]}...")
    
    client.close()

if __name__ == "__main__":
    asyncio.run(check_stuck())
