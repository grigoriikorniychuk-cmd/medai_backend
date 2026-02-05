#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Проверка 2 pending звонков за 04.10.2025
"""

import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from amo_credentials import MONGODB_NAME
MONGODB_URI = 'mongodb://92.113.151.220:27018/'

async def check():
    client = AsyncIOMotorClient(MONGODB_URI)
    db = client[MONGODB_NAME]
    calls = db.calls
    
    print("\n🔍 Проверка 2 pending звонков за 04.10.2025:\n")
    
    async for call in calls.find({
        "client_id": "00a48347-547b-4c47-9484-b20243b05643",
        "created_date_for_filtering": "2025-10-04",
        "transcription_status": "pending"
    }):
        print(f"ID: {call['_id']}")
        print(f"  call_link: {call.get('call_link', 'N/A')[:100]}")
        print(f"  has_filename_transcription: {bool(call.get('filename_transcription'))}")
        print(f"  transcription_status: {call.get('transcription_status')}")
        
        call_link = call.get('call_link', '')
        if '/api/v4/contacts/' in call_link and '/notes/' in call_link:
            print(f"  ⚠️ ЭТО API ЗАМЕТКИ AmoCRM!")
        elif 'api.cloudpbx.rt.ru' in call_link:
            print(f"  ✅ RT звонок")
        else:
            print(f"  ❓ Неизвестный тип")
        print()
    
    client.close()

if __name__ == "__main__":
    asyncio.run(check())
