#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Проверка: какие звонки будут найдены для транскрибации
"""

import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from amo_credentials import MONGODB_NAME
MONGODB_URI = 'mongodb://92.113.151.220:27018/'

async def check_query():
    client = AsyncIOMotorClient(MONGODB_URI)
    db = client[MONGODB_NAME]
    calls = db.calls
    
    # Это тот же запрос, что использует эндпоинт /api/calls/transcribe-by-date-range
    mongo_query = {
        "created_date_for_filtering": {"$gte": "2025-10-03", "$lte": "2025-10-03"},
        "call_link": {"$exists": True, "$ne": None, "$ne": ""},
        "client_id": "00a48347-547b-4c47-9484-b20243b05643",
        "$or": [
            {"filename_transcription": {"$exists": False}},
            {"filename_transcription": None},
            {"filename_transcription": ""},
        ]
    }
    
    count = await calls.count_documents(mongo_query)
    print(f"\n🔍 Звонков будет найдено для транскрибации: {count}\n")
    
    # Примеры
    print("Примеры звонков:")
    async for call in calls.find(mongo_query).limit(3):
        print(f"  - ID: {call['_id']}")
        print(f"    status: {call.get('transcription_status', 'NO STATUS')}")
        print(f"    call_link: {call.get('call_link', 'N/A')[:80]}")
        print(f"    has_transcription: {bool(call.get('filename_transcription'))}")
        print()
    
    client.close()

if __name__ == "__main__":
    asyncio.run(check_query())
