#!/usr/bin/env python3
"""
Тестируем получение заметки с параметром with=leads
"""
import asyncio
import json
from mlab_amo_async.amocrm_client import AsyncAmoCRMClient
from motor.motor_asyncio import AsyncIOMotorClient

# Настройки
TEST_CLIENT_ID = "500655e7-f5b7-49e2-bd8f-5907f68e5578"
MONGO_URI = "mongodb://92.113.151.220:27018/"
DB_NAME = "medai"
CONTACT_ID = 34590537
NOTE_ID = 200306359  # ID первой заметки из теста

async def test_get_note_with_leads():
    """Тестирует получение заметки с _embedded.leads"""
    
    print("="*60)
    print("🔍 ТЕСТ: Получение заметки с with=leads")
    print("="*60)
    
    # Подключаемся к MongoDB
    mongo_client = AsyncIOMotorClient(MONGO_URI)
    db = mongo_client[DB_NAME]
    
    # Получаем клинику
    clinic = await db.clinics.find_one({"client_id": TEST_CLIENT_ID})
    if not clinic:
        print("❌ Клиника не найдена")
        return
    
    print(f"✅ Клиника: {clinic.get('name')}")
    
    # Создаем клиент amoCRM
    client = AsyncAmoCRMClient(
        client_id=clinic["client_id"],
        client_secret=clinic["client_secret"],
        subdomain=clinic["amocrm_subdomain"],
        redirect_url=clinic["redirect_url"],
        mongo_uri=MONGO_URI,
        db_name=DB_NAME
    )
    
    print(f"\n📝 Запрашиваем заметку {NOTE_ID} для контакта {CONTACT_ID}...")
    
    try:
        # Вариант 1: Запрос через contacts.request с параметром with=leads
        api_path = f"api/v4/contacts/{CONTACT_ID}/notes/{NOTE_ID}"
        params = {"with": "leads"}
        
        print(f"   API путь: {api_path}")
        print(f"   Параметры: {params}")
        
        response, status = await client.contacts.request("get", api_path, params=params)
        
        if status != 200:
            print(f"❌ Ошибка: статус {status}")
            return
        
        print(f"✅ Заметка получена (статус {status})")
        
        print("\n" + "="*60)
        print("📋 СТРУКТУРА ЗАМЕТКИ С with=leads:")
        print("="*60)
        print(json.dumps(response, indent=2, ensure_ascii=False))
        
        # Проверяем наличие _embedded.leads
        embedded = response.get("_embedded", {})
        leads = embedded.get("leads", [])
        
        print("\n" + "="*60)
        print("🔍 АНАЛИЗ:")
        print("="*60)
        print(f"Есть _embedded: {bool(embedded)}")
        print(f"Есть _embedded.leads: {bool(leads)}")
        
        if leads:
            print(f"Количество leads: {len(leads)}")
            print(f"\n✅ НАЙДЕН lead_id: {leads[0].get('id')}")
            print(f"   lead_name: {leads[0].get('name', 'Без названия')}")
        else:
            print("⚠️  _embedded.leads пустой или отсутствует")
        
        # Сохраняем в файл
        with open("note_with_leads.json", "w", encoding="utf-8") as f:
            json.dump(response, f, indent=2, ensure_ascii=False)
        
        print(f"\n💾 Результат сохранён в: note_with_leads.json")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        mongo_client.close()
        await client.close()

if __name__ == "__main__":
    asyncio.run(test_get_note_with_leads())
