"""
Простой тест для проверки обогащения lead_id для событий контактов
"""
import asyncio
from mlab_amo_async.amocrm_client import AsyncAmoCRMClient
from motor.motor_asyncio import AsyncIOMotorClient

TEST_CLIENT_ID = "500655e7-f5b7-49e2-bd8f-5907f68e5578"
MONGO_URI = "mongodb://92.113.151.220:27018/"
DB_NAME = "medai"
TEST_DATE = "01.10.2025"

# Возьмем контакт из свежих данных (существующий)
TEST_CONTACT_ID = 22037801  # БАНТУШ АРТЕМ ВАСИЛЬЕВИЧ
TEST_NOTE_ID = 200308167  # note_id из test_calls_export.json

async def test_enrichment():
    """Простой тест обогащения lead_id"""
    
    print("="*60)
    print("🧪 ТЕСТ ОБОГАЩЕНИЯ lead_id")
    print("="*60)
    
    # Подключаемся к MongoDB
    mongo_client = AsyncIOMotorClient(MONGO_URI)
    db = mongo_client[DB_NAME]
    
    # Находим клинику
    clinic = await db.clinics.find_one({"client_id": TEST_CLIENT_ID})
    
    if not clinic:
        print(f"❌ Клиника не найдена")
        return
    
    print(f"✅ Клиника: {clinic.get('clinic_name')}")
    
    # Создаем клиент amoCRM
    client = AsyncAmoCRMClient(
        client_id=clinic["client_id"],
        client_secret=clinic["client_secret"],
        subdomain=clinic["amocrm_subdomain"],
        redirect_url=clinic["redirect_url"],
        mongo_uri=MONGO_URI,
        db_name=DB_NAME
    )
    
    print(f"\n📞 Тестируем контакт {TEST_CONTACT_ID}...")
    
    try:
        # Шаг 1: Запрашиваем заметку напрямую по note_id
        print(f"\n1️⃣ Запрашиваем заметку {TEST_NOTE_ID} напрямую...")
        note_response, note_status = await client.contacts.request(
            "get", f"contacts/{TEST_CONTACT_ID}/notes/{TEST_NOTE_ID}"
        )
        
        print(f"   Статус ответа: {note_status}")
        
        if note_status == 200 and note_response:
            print(f"   ✅ Заметка получена!")
            
            # Проверяем _embedded.leads в заметке
            note_embedded = note_response.get("_embedded", {})
            note_leads = note_embedded.get("leads", [])
            
            print(f"   📋 _embedded.leads в заметке: {len(note_leads) if note_leads else 0} сделок")
            
            if note_leads:
                for idx, lead in enumerate(note_leads, 1):
                    print(f"      ✅ Сделка #{idx}: id={lead.get('id')}")
            else:
                print(f"      ⚠️ В заметке нет _embedded.leads")
        else:
            print(f"   ❌ Ошибка: статус {note_status}")
    
    except Exception as e:
        print(f"   ❌ Ошибка при запросе заметки: {e}")
    
    try:
        # Шаг 2: Запрашиваем сделки контакта напрямую
        print(f"\n2️⃣ Запрашиваем сделки контакта {TEST_CONTACT_ID} через API...")
        leads_response, leads_status = await client.contacts.request(
            "get", f"contacts/{TEST_CONTACT_ID}/leads"
        )
        
        print(f"   Статус ответа: {leads_status}")
        
        if leads_status == 200 and leads_response:
            contact_embedded = leads_response.get("_embedded", {})
            contact_leads = contact_embedded.get("leads", [])
            
            print(f"   ✅ Найдено сделок у контакта: {len(contact_leads) if contact_leads else 0}")
            
            if contact_leads:
                for idx, lead in enumerate(contact_leads[:5], 1):  # Показываем первые 5
                    print(f"      Сделка #{idx}: id={lead.get('id')}, name='{lead.get('name')}'")
            else:
                print(f"   ⚠️ У контакта нет привязанных сделок")
        else:
            print(f"   ❌ Ошибка: статус {leads_status}")
            
    except Exception as e:
        error_msg = str(e)
        if "404" in error_msg:
            print(f"   ⚠️ Контакт {TEST_CONTACT_ID} не найден (удален из AmoCRM)")
        else:
            print(f"   ❌ Ошибка: {e}")
    
    # Закрываем соединения
    mongo_client.close()
    await client.close()
    
    print("\n" + "="*60)
    print("✅ Тест завершен")

if __name__ == "__main__":
    asyncio.run(test_enrichment())
