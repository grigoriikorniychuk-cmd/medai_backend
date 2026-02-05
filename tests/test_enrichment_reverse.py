"""
ПРАВИЛЬНЫЙ подход к обогащению lead_id:
Идём от сделок к контактам, а не наоборот!
"""
import requests
import json
from datetime import datetime

TEST_CLIENT_ID = "500655e7-f5b7-49e2-bd8f-5907f68e5578"
API_BASE = "https://api.mlab-electronics.ru"
TEST_DATE = "01.10.2025"
OUTPUT_FILE = "test_enriched_calls.json"

def test_reverse_enrichment():
    """Тест обогащения через сделки → контакты"""
    
    print("="*60)
    print("🔄 ОБРАТНЫЙ ПОДХОД К ОБОГАЩЕНИЮ")
    print("="*60)
    
    # Отключаем проверку SSL
    requests.packages.urllib3.disable_warnings()
    
    # Шаг 1: Получаем все сделки за дату
    print(f"\n1️⃣ Получаем сделки за {TEST_DATE}...")
    
    leads_url = f"{API_BASE}/api/amocrm/leads/by-date"
    leads_payload = {
        "client_id": TEST_CLIENT_ID,
        "date": TEST_DATE
    }
    
    resp = requests.post(leads_url, json=leads_payload, verify=False)
    leads_result = resp.json()
    
    if not leads_result.get("success"):
        print(f"❌ Ошибка: {leads_result.get('message')}")
        return
    
    leads = leads_result["data"]["leads"]
    print(f"✅ Найдено сделок: {len(leads)}")
    
    # Шаг 2: Создаём мапу lead_id → contact_id
    print(f"\n2️⃣ Получаем контакты для каждой сделки...")
    lead_to_contact = {}  # {lead_id: contact_id}
    
    for idx, lead in enumerate(leads, 1):  # Обрабатываем ВСЕ сделки
        lead_id = lead["id"]
        lead_name = lead["name"]
        
        contact_url = f"{API_BASE}/api/amocrm/lead/contact"
        contact_payload = {
            "client_id": TEST_CLIENT_ID,
            "lead_id": lead_id
        }
        
        try:
            resp = requests.post(contact_url, json=contact_payload, verify=False)
            contact_result = resp.json()
                
            if contact_result.get("success"):
                contact_id = contact_result["data"]["id"]
                contact_name = contact_result["data"]["name"]
                lead_to_contact[lead_id] = contact_id
                print(f"   {idx}. Lead {lead_id} ('{lead_name[:30]}...') → Contact {contact_id} ('{contact_name[:30]}...')")
            else:
                print(f"   {idx}. Lead {lead_id} - нет контакта")
        except Exception as e:
            print(f"   {idx}. Lead {lead_id} - ошибка: {e}")
    
    print(f"\n✅ Создана мапа: {len(lead_to_contact)} пар lead→contact")
    
    # Шаг 3: Создаём ОБРАТНУЮ мапу contact_id → lead_id
    contact_to_lead = {v: k for k, v in lead_to_contact.items()}
    print(f"✅ Обратная мапа: {len(contact_to_lead)} пар contact→lead")
    
    # Шаг 4: Тестируем обогащение на примере
    print(f"\n3️⃣ Пример обогащения:")
    print(f"   Если у события contact_id = {list(contact_to_lead.keys())[0] if contact_to_lead else 'N/A'}")
    if contact_to_lead:
        sample_contact = list(contact_to_lead.keys())[0]
        sample_lead = contact_to_lead[sample_contact]
        print(f"   То lead_id = {sample_lead}")
        print(f"   ✅ ОБОГАЩЕНИЕ РАБОТАЕТ!")
    
    # Показываем всю мапу
    print(f"\n📊 ПОЛНАЯ МАПА contact_id → lead_id:")
    for contact_id, lead_id in list(contact_to_lead.items())[:20]:
        print(f"   Contact {contact_id} → Lead {lead_id}")
    
    # Шаг 5: Получаем детальные звонки через API
    print(f"\n4️⃣ Получаем звонки через API за {TEST_DATE}...")
    
    try:
        # Конвертируем дату для MongoDB
        date_parts = TEST_DATE.split('.')
        formatted_date = f"{date_parts[2]}-{date_parts[1]}-{date_parts[0]}"
        
        # Используем правильный эндпоинт
        events_url = f"{API_BASE}/api/admin/amocrm/events"
        
        events_payload = {
            "client_id": TEST_CLIENT_ID,
            "date": TEST_DATE
        }
        
        resp = requests.post(events_url, json=events_payload, verify=False)
        events_result = resp.json()
        
        if not events_result.get("success"):
            print(f"❌ Ошибка: {events_result}")
            return
        
        events = events_result.get("data", {}).get("events", [])
        print(f"✅ Найдено событий: {len(events)}")
        
        # Обогащаем каждое событие
        enriched_calls = []
        enriched_count = 0
        
        for event in events:
            # Извлекаем данные из события AmoCRM
            contact_id = event.get("entity_id")
            note_id = event.get("id")
            
            # Извлекаем данные звонка из value_after
            value_after = event.get("value_after", [])
            call_data = value_after[0] if value_after else {}
            event_details = call_data.get("event", {})
            
            # Создаём документ в формате MongoDB
            call_doc = {
                "note_id": note_id,
                "event_id": event_details.get("id"),
                "lead_id": None,
                "lead_name": "",
                "contact_id": contact_id,
                "contact_name": "",
                "client_id": TEST_CLIENT_ID,
                "subdomain": "atmosferaryazanyandexru",
                "administrator": call_data.get("responsible_user_name", "Неизвестный"),
                "source": "Неопределенный",
                "processing_speed": 0,
                "processing_speed_str": "0 мин",
                "call_direction": call_data.get("direction", "Входящий"),
                "duration": call_data.get("duration", 0),
                "duration_formatted": str(call_data.get("duration", 0)),
                "phone": call_data.get("phone", ""),
                "call_link": call_data.get("link", ""),
                "created_at": event.get("created_at"),
                "created_date": datetime.fromtimestamp(event.get("created_at", 0)).strftime("%Y-%m-%d %H:%M:%S"),
                "recorded_at": datetime.now().isoformat(),
                "created_date_for_filtering": formatted_date
            }
            
            # ОБОГАЩЕНИЕ: Если контакт есть в мапе - добавляем lead_id и lead_name
            if contact_id and contact_id in contact_to_lead:
                lead_id = contact_to_lead[contact_id]
                call_doc["lead_id"] = lead_id
                
                # Ищем имя сделки
                for lead in leads:
                    if lead["id"] == lead_id:
                        call_doc["lead_name"] = lead["name"]
                        break
                
                enriched_count += 1
            
            enriched_calls.append(call_doc)
        
        percentage = round(enriched_count/len(enriched_calls)*100, 2) if enriched_calls else 0
        print(f"✅ Обогащено: {enriched_count} из {len(enriched_calls)} ({percentage}%)")
        
        # Сохраняем в JSON
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(enriched_calls, f, ensure_ascii=False, indent=2)
        
        print(f"💾 Сохранено {len(enriched_calls)} записей в {OUTPUT_FILE}")
        
        # Показываем примеры
        enriched_only = [c for c in enriched_calls if c.get("lead_id")]
        if enriched_only:
            print(f"\n📋 Примеры обогащённых звонков:")
            for i, call in enumerate(enriched_only[:5], 1):
                print(f"   {i}. Contact {call['contact_id']} → Lead {call['lead_id']} ('{call.get('lead_name', '')[:40]}...')")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "="*60)
    print("✅ Тест завершён")

if __name__ == "__main__":
    test_reverse_enrichment()
