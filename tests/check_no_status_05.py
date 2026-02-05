#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Проверка всех статусов за 05.10.2025
"""

import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from amo_credentials import MONGODB_NAME
MONGODB_URI = 'mongodb://92.113.151.220:27018/'

async def check():
    client = AsyncIOMotorClient(MONGODB_URI)
    db = client[MONGODB_NAME]
    calls = db.calls
    
    print("\n📊 Полная статистика за 05.10.2025:\n")
    
    # Все звонки
    all_calls = await calls.find({
        "client_id": "00a48347-547b-4c47-9484-b20243b05643",
        "created_date_for_filtering": "2025-10-05"
    }).to_list(length=100)
    
    print(f"Всего звонков: {len(all_calls)}\n")
    
    # Группируем по статусам
    statuses = {}
    no_status = []
    
    for call in all_calls:
        status = call.get('transcription_status')
        if status:
            statuses[status] = statuses.get(status, 0) + 1
        else:
            no_status.append(call)
            statuses['NO_STATUS'] = statuses.get('NO_STATUS', 0) + 1
    
    print("Разбивка по статусам:")
    for status, count in sorted(statuses.items()):
        print(f"  {status}: {count}")
    
    # Показываем записи без статуса
    if no_status:
        print(f"\n⚠️ Записи БЕЗ transcription_status ({len(no_status)} шт):")
        for call in no_status[:5]:
            call_link = call.get('call_link', '')
            print(f"\n  ID: {call['_id']}")
            print(f"    call_link: {call_link[:80]}")
            
            if '/api/v4/contacts/' in call_link and '/notes/' in call_link:
                print(f"    Тип: ❌ API ЗАМЕТКИ (МУСОР)")
            elif 'api.cloudpbx.rt.ru' in call_link:
                print(f"    Тип: ✅ RT звонок")
            elif 'mango' in call_link.lower():
                print(f"    Тип: ✅ Mango звонок")
            else:
                print(f"    Тип: ❓ Неизвестный")
    
    client.close()

if __name__ == "__main__":
    asyncio.run(check())
