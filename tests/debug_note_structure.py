#!/usr/bin/env python3
"""
Скрипт для отладки структуры заметок из get_call_links
Показывает, где именно находится lead_id в заметке
"""
import asyncio
import json
from mlab_amo_async.amocrm_client import AsyncAmoCRMClient
from motor.motor_asyncio import AsyncIOMotorClient

# Настройки
TEST_CLIENT_ID = "500655e7-f5b7-49e2-bd8f-5907f68e5578"
MONGO_URI = "mongodb://92.113.151.220:27018/"
DB_NAME = "medai"
CONTACT_ID = 34590537  # Один из контактов из теста

async def debug_note_structure():
    """Отлаживает структуру заметки"""
    
    print("="*60)
    print("🔍 ОТЛАДКА СТРУКТУРЫ ЗАМЕТОК")
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
    
    print(f"\n📞 Получаем заметки для контакта {CONTACT_ID}...")
    
    try:
        call_links = await client.get_call_links(CONTACT_ID)
        
        if not call_links:
            print("❌ Нет заметок")
            return
        
        print(f"✅ Получено {len(call_links)} заметок\n")
        
        # Берем первую заметку для анализа
        first_call = call_links[0]
        
        print("="*60)
        print("📋 СТРУКТУРА ПЕРВОЙ ЗАМЕТКИ:")
        print("="*60)
        print(json.dumps(first_call, indent=2, ensure_ascii=False))
        
        # Анализируем структуру
        print("\n" + "="*60)
        print("🔍 АНАЛИЗ СТРУКТУРЫ:")
        print("="*60)
        
        note = first_call.get("note", {})
        print(f"\n1️⃣ Ключи в 'note': {list(note.keys())}")
        
        embedded = note.get("_embedded", {})
        print(f"\n2️⃣ Ключи в 'note._embedded': {list(embedded.keys())}")
        
        if "_embedded" in note:
            leads = embedded.get("leads", [])
            print(f"\n3️⃣ Количество leads в '_embedded.leads': {len(leads)}")
            
            if leads:
                print(f"\n4️⃣ Первый lead:")
                print(json.dumps(leads[0], indent=2, ensure_ascii=False))
        else:
            print(f"\n⚠️  Поле '_embedded' отсутствует в заметке!")
            print(f"\n🔍 Проверяем альтернативные места для lead_id:")
            
            # Проверяем entity_id
            entity_id = note.get("entity_id")
            entity_type = note.get("entity_type")
            print(f"   - note.entity_id: {entity_id}")
            print(f"   - note.entity_type: {entity_type}")
            
            # Проверяем params
            params = note.get("params", {})
            print(f"   - note.params keys: {list(params.keys())}")
        
        # Сохраняем полную структуру в файл
        with open("note_structure_debug.json", "w", encoding="utf-8") as f:
            json.dump(call_links[0], f, indent=2, ensure_ascii=False)
        
        print(f"\n💾 Полная структура сохранена в: note_structure_debug.json")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        mongo_client.close()
        await client.close()

if __name__ == "__main__":
    asyncio.run(debug_note_structure())
