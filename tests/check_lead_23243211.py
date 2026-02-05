"""
Проверяем сделку 23243211 - почему её звонки не попали в результаты
"""
import asyncio
import sys
import os
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mlab_amo_async.amocrm_client import AsyncAmoCRMClient

MONGO_URI = "mongodb://92.113.151.220:27018/"
DB_NAME = "medai"
TARGET_CLIENT_ID = "4cdd8fc0-c5fa-4c3c-a2a8-19b062f37fc9"
TARGET_LEAD_ID = 23243211
TARGET_DATE_STR = "2025-10-17"


async def check_lead():
    print(f"\n{'='*60}")
    print(f"🔍 Проверка сделки {TARGET_LEAD_ID}")
    print(f"{'='*60}")
    
    mongo_client = AsyncIOMotorClient(MONGO_URI)
    db = mongo_client[DB_NAME]
    
    clinic = await db.clinics.find_one({"client_id": TARGET_CLIENT_ID})
    if not clinic:
        print("❌ Клиника не найдена")
        return
    
    amo_client = AsyncAmoCRMClient(
        client_id=clinic["client_id"],
        client_secret=clinic["client_secret"],
        subdomain=clinic["amocrm_subdomain"],
        redirect_url=clinic["redirect_url"],
        mongo_uri=MONGO_URI,
        db_name=DB_NAME
    )
    
    try:
        # Получаем сделку
        print(f"\n1️⃣ Получение сделки {TARGET_LEAD_ID}...")
        lead = await amo_client.get_lead(TARGET_LEAD_ID)
        
        if not lead:
            print("❌ Сделка не найдена")
            return
        
        print(f"✅ Сделка: {lead.get('name')}")
        print(f"   created_at: {datetime.fromtimestamp(lead.get('created_at')).strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"   pipeline_id: {lead.get('pipeline_id')}")
        print(f"   status_id: {lead.get('status_id')}")
        
        # Получаем контакт из сделки
        print(f"\n2️⃣ Получение контакта из сделки...")
        contact = await amo_client.get_contact_from_lead(TARGET_LEAD_ID)
        
        if not contact:
            print("❌ Контакт не найден")
            return
        
        contact_id = contact.get('id')
        print(f"✅ Контакт: {contact.get('name')} (ID: {contact_id})")
        
        # Получаем ВСЕ звонки контакта
        print(f"\n3️⃣ Получение звонков контакта {contact_id}...")
        call_links = await amo_client.get_call_links(contact_id)
        
        if not call_links:
            print("❌ Звонки не найдены")
            return
        
        print(f"✅ Всего звонков у контакта: {len(call_links)}")
        
        # Фильтруем звонки за 17 октября
        target_date = datetime.strptime(TARGET_DATE_STR, "%Y-%m-%d")
        target_start = int(datetime.combine(target_date.date(), datetime.min.time()).timestamp())
        target_end = int(datetime.combine(target_date.date(), datetime.max.time()).timestamp())
        
        calls_on_date = []
        for call in call_links:
            note = call.get('note', {})
            created_at = note.get('created_at', 0)
            
            if target_start <= created_at <= target_end:
                calls_on_date.append({
                    'note_id': call.get('note_id'),
                    'created_at': created_at,
                    'created_date': datetime.fromtimestamp(created_at).strftime('%Y-%m-%d %H:%M:%S'),
                    'params': note.get('params', {})
                })
        
        print(f"\n4️⃣ Звонки за {TARGET_DATE_STR}:")
        if calls_on_date:
            for idx, call in enumerate(calls_on_date, 1):
                print(f"\n   Звонок #{idx}:")
                print(f"   note_id: {call['note_id']}")
                print(f"   Дата: {call['created_date']}")
                print(f"   Длительность: {call['params'].get('duration', 0)} сек")
                print(f"   Телефон: {call['params'].get('phone', 'N/A')}")
        else:
            print("   ❌ Нет звонков за эту дату")
        
        # Проверяем события звонков за эту дату через API events
        print(f"\n5️⃣ Проверка событий через API /events за {TARGET_DATE_STR}...")
        
        api_path = "events"
        params = {
            "page": 1,
            "limit": 250,
            "filter[type]": "incoming_call,outgoing_call",
            "filter[created_at][from]": target_start,
            "filter[created_at][to]": target_end,
            "filter[entity_id]": contact_id,
            "filter[entity_type]": "contact"
        }
        
        response, status = await amo_client.contacts.request("get", api_path, params=params)
        
        if status == 200:
            events = response.get("_embedded", {}).get("events", [])
            print(f"✅ Найдено событий звонков для контакта: {len(events)}")
            
            if events:
                for idx, event in enumerate(events[:5], 1):  # Первые 5
                    print(f"\n   Событие #{idx}:")
                    print(f"   ID: {event.get('id')}")
                    print(f"   Тип: {event.get('type')}")
                    print(f"   Дата: {datetime.fromtimestamp(event.get('created_at')).strftime('%Y-%m-%d %H:%M:%S')}")
            else:
                print("   ⚠️ События НЕ найдены через API events!")
        else:
            print(f"   ❌ Ошибка: статус {status}")
        
        print(f"\n{'='*60}")
        print("📊 ИТОГ:")
        print(f"Сделка создана: {datetime.fromtimestamp(lead.get('created_at')).strftime('%Y-%m-%d')}")
        print(f"Звонков у контакта за {TARGET_DATE_STR}: {len(calls_on_date)}")
        print(f"Событий звонков через API events: {len(events) if status == 200 else 'N/A'}")
        print(f"{'='*60}\n")
        
    finally:
        await amo_client.close()
        mongo_client.close()


if __name__ == "__main__":
    asyncio.run(check_lead())
