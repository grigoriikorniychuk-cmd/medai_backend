#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Проверка статистики за 04.10.2025
"""

import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from amo_credentials import MONGODB_NAME
MONGODB_URI = 'mongodb://92.113.151.220:27018/'

async def check():
    client = AsyncIOMotorClient(MONGODB_URI)
    db = client[MONGODB_NAME]
    calls = db.calls
    
    total = await calls.count_documents({
        "client_id": "00a48347-547b-4c47-9484-b20243b05643",
        "created_date_for_filtering": "2025-10-04"
    })
    
    success = await calls.count_documents({
        "client_id": "00a48347-547b-4c47-9484-b20243b05643",
        "created_date_for_filtering": "2025-10-04",
        "transcription_status": "success"
    })
    
    failed = await calls.count_documents({
        "client_id": "00a48347-547b-4c47-9484-b20243b05643",
        "created_date_for_filtering": "2025-10-04",
        "transcription_status": "failed"
    })
    
    pending = await calls.count_documents({
        "client_id": "00a48347-547b-4c47-9484-b20243b05643",
        "created_date_for_filtering": "2025-10-04",
        "transcription_status": "pending"
    })
    
    processing = await calls.count_documents({
        "client_id": "00a48347-547b-4c47-9484-b20243b05643",
        "created_date_for_filtering": "2025-10-04",
        "transcription_status": "processing"
    })
    
    no_status = await calls.count_documents({
        "client_id": "00a48347-547b-4c47-9484-b20243b05643",
        "created_date_for_filtering": "2025-10-04",
        "$or": [
            {"transcription_status": {"$exists": False}},
            {"transcription_status": None},
            {"transcription_status": ""}
        ]
    })
    
    print(f"\n📊 АКТУАЛЬНАЯ статистика за 04.10.2025:")
    print(f"Всего: {total}")
    print(f"✅ Success: {success}")
    print(f"❌ Failed: {failed}")
    print(f"⏳ Processing: {processing}")
    print(f"⏱ Pending: {pending}")
    print(f"❓ Без статуса: {no_status}")
    
    completed = success + failed
    if total > 0:
        print(f"\n💡 Прогресс: {completed}/{total} ({completed/total*100:.1f}%)")
        
        if pending == 0 and processing == 0:
            print(f"\n🎉 ВСЕ ОБРАБОТАНО! overall_status = 'completed'")
        elif pending > 0 and processing == 0:
            print(f"\n⚠️ {pending} звонков в pending, но не обрабатываются!")
            print(f"   Запустите транскрибацию заново с фронта")
    
    # Если есть звонки без статуса, покажем их
    if no_status > 0:
        print(f"\n🔍 Примеры звонков БЕЗ статуса:")
        async for call in calls.find({
            "client_id": "00a48347-547b-4c47-9484-b20243b05643",
            "created_date_for_filtering": "2025-10-04",
            "$or": [
                {"transcription_status": {"$exists": False}},
                {"transcription_status": None},
                {"transcription_status": ""}
            ]
        }).limit(3):
            print(f"  - ID: {call['_id']}")
            print(f"    call_link: {call.get('call_link', 'N/A')[:80]}")
    
    client.close()

if __name__ == "__main__":
    asyncio.run(check())
