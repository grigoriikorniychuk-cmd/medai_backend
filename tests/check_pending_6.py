#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Проверка 6 оставшихся pending звонков
"""

import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from amo_credentials import MONGODB_URI, MONGODB_NAME

async def check():
    client = AsyncIOMotorClient(MONGODB_URI)
    db = client[MONGODB_NAME]
    calls = db.calls
    
    print("\n🔍 Проверка 6 pending звонков:\n")
    
    async for call in calls.find({
        "client_id": "00a48347-547b-4c47-9484-b20243b05643",
        "created_date_for_filtering": "2025-10-03",
        "transcription_status": "pending"
    }):
        print(f"ID: {call['_id']}")
        print(f"  call_link: {call.get('call_link', 'N/A')[:100]}")
        print(f"  has_filename_transcription: {bool(call.get('filename_transcription'))}")
        
        # Проверяем, является ли это API заметки
        call_link = call.get('call_link', '')
        if '/api/v4/contacts/' in call_link and '/notes/' in call_link:
            print(f"  ⚠️ ЭТО ТОЖЕ API ЗАМЕТКИ!")
        else:
            print(f"  ✅ Похоже на настоящий звонок")
        print()
    
    client.close()

if __name__ == "__main__":
    asyncio.run(check())
