#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Проверка: какие поля со ссылками есть у звонков
"""

import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from amo_credentials import MONGODB_URI, MONGODB_NAME

async def check_links():
    client = AsyncIOMotorClient(MONGODB_URI)
    db = client[MONGODB_NAME]
    calls = db.calls
    
    # Берём один pending звонок
    call = await calls.find_one({
        "client_id": "00a48347-547b-4c47-9484-b20243b05643",
        "created_date_for_filtering": "2025-10-03",
        "transcription_status": "pending"
    })
    
    if call:
        print(f"\n🔍 Проверка звонка ID: {call['_id']}\n")
        print("Поля со ссылками:")
        
        link_fields = ['call_link', 'record_link', 'audio_url', 'file_url', 'attachment_url']
        for field in link_fields:
            value = call.get(field)
            if value:
                print(f"  ✅ {field}: {value[:100]}")
            else:
                print(f"  ❌ {field}: отсутствует")
        
        # Показываем все ключи документа
        print(f"\n📋 Все поля документа:")
        for key in sorted(call.keys()):
            if key != '_id':
                value = str(call[key])[:80]
                print(f"  - {key}: {value}")
    else:
        print("❌ Звонок не найден")
    
    client.close()

if __name__ == "__main__":
    asyncio.run(check_links())
