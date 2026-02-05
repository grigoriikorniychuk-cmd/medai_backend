#!/usr/bin/env python3
"""
Тестируем получение контакта с параметром with=leads
Чтобы узнать, к каким сделкам привязан контакт
"""
import asyncio
import json
from mlab_amo_async.amocrm_client import AsyncAmoCRMClient
from motor.motor_asyncio import AsyncIOMotorClient

# Настройки
TEST_CLIENT_ID = "500655e7-f5b7-49e2-bd8f-5907f68e5578"
MONGO_URI = "mongodb://92.113.151.220:27018/"
DB_NAME = "medai"
CONTACT_ID = 34722513  # Контакт из реальных данных test_calls_export.json

async def test_contact_with_leads():
    """Тестирует получение контакта с _embedded.leads"""
    
    print("="*60)
    print("🔍 ТЕСТ: Получение контакта с with=leads")
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
    
    print(f"\n👤 Получаем контакт {CONTACT_ID}...")
    
    try:
        # Согласно документации: GET /api/v4/contacts/{id} возвращает _embedded.leads
        api_path = f"api/v4/contacts/{CONTACT_ID}"
        
        print(f"   API: {api_path}")
        
        response, status = await client.contacts.request("get", api_path)
        
        if status != 200:
            print(f"❌ Ошибка: статус {status}")
            return
        
        # Извлекаем сделки из ответа
        embedded = response.get("_embedded", {})
        leads = embedded.get("leads", [])
        
        if not leads:
            print("❌ У контакта нет сделок")
            return
        
        print(f"✅ Найдено сделок: {len(leads)}")
        
        print("\n" + "="*60)
        print("📋 СДЕЛКИ КОНТАКТА:")
        print("="*60)
        
        for i, lead in enumerate(leads, 1):
            print(f"\n{i}. Lead ID: {lead.get('id')}")
            print(f"   Название: {lead.get('name', 'Без названия')}")
            print(f"   Статус: {lead.get('status_id')}")
            print(f"   Создана: {lead.get('created_at')}")
            print(f"   Обновлена: {lead.get('updated_at')}")
        
        # Сохраняем в файл
        with open("contact_leads.json", "w", encoding="utf-8") as f:
            json.dump(response, f, indent=2, ensure_ascii=False)
        
        print(f"\n💾 Результат сохранён в: contact_leads.json")
        
        print("\n" + "="*60)
        print("💡 ВЫВОД:")
        print("="*60)
        print(f"✅ Для контакта {CONTACT_ID} найдено {len(leads)} сделок")
        print(f"✅ Можно использовать lead_id из первой/последней сделки")
        print(f"✅ Или выбрать сделку по дате создания/обновления")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        mongo_client.close()
        await client.close()

if __name__ == "__main__":
    asyncio.run(test_contact_with_leads())
