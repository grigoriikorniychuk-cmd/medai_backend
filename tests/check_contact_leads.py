"""
Проверяем все сделки контакта 27597081
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
TARGET_CONTACT_ID = 27597081


async def main():
    print(f"\n{'='*60}")
    print(f"🔍 Проверка всех сделок контакта {TARGET_CONTACT_ID}")
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
        # Получаем контакт с сделками
        print(f"\n📞 Получение контакта с сделками...")
        contact_info, status = await amo_client.contacts.request(
            "get", f"contacts/{TARGET_CONTACT_ID}", params={"with": "leads"}
        )
        
        if status != 200:
            print(f"❌ Ошибка: статус {status}")
            return
        
        print(f"✅ Контакт: {contact_info.get('name')}")
        
        leads = contact_info.get("_embedded", {}).get("leads", [])
        print(f"\n📊 Всего сделок у контакта: {len(leads)}")
        
        if not leads:
            print("❌ Нет сделок")
            return
        
        # Сортируем по updated_at
        def lead_sort_key(l):
            return l.get("updated_at", 0) or l.get("created_at", 0)
        
        sorted_leads = sorted(leads, key=lead_sort_key, reverse=True)
        
        print(f"\n{'='*60}")
        print("📋 ВСЕ СДЕЛКИ (по убыванию updated_at):")
        print(f"{'='*60}\n")
        
        for idx, lead in enumerate(sorted_leads, 1):
            lead_id = lead.get("id")
            lead_name = lead.get("name", "Без названия")
            created_at = lead.get("created_at", 0)
            updated_at = lead.get("updated_at", 0)
            pipeline_id = lead.get("pipeline_id")
            status_id = lead.get("status_id")
            
            created_date = datetime.fromtimestamp(created_at).strftime('%Y-%m-%d %H:%M') if created_at else "N/A"
            updated_date = datetime.fromtimestamp(updated_at).strftime('%Y-%m-%d %H:%M') if updated_at else "N/A"
            
            marker = "🎯" if lead_id == 23243211 else f"{idx}."
            
            print(f"{marker} Сделка ID: {lead_id}")
            print(f"   Название: {lead_name}")
            print(f"   Создана: {created_date}")
            print(f"   Обновлена: {updated_date}")
            print(f"   Воронка: {pipeline_id}, Статус: {status_id}")
            
            # Проверяем подтверждение для каждой сделки
            full_lead = await amo_client.get_lead(lead_id)
            if full_lead:
                custom_fields = full_lead.get('custom_fields_values', [])
                has_confirmation = False
                for cf in custom_fields:
                    if cf.get('field_id') == 1054011:  # Подтверждение
                        for val in cf.get('values', []):
                            if val.get('enum_id') == 1144793:  # Подтвержден
                                has_confirmation = True
                
                if has_confirmation:
                    print(f"   ✅ ПОДТВЕРЖДЕНИЕ: Подтвержден")
                
                # Проверяем статусы конверсии
                if (pipeline_id == 6869034 and status_id == 57882910):
                    print(f"   ✅ КОНВЕРСИЯ: Первичные -> Записались")
                elif (pipeline_id == 6888086 and status_id == 58011926):
                    print(f"   ✅ КОНВЕРСИЯ: Вторичные -> Записались")
            
            print()
        
        print(f"{'='*60}")
        print(f"⚠️ ПРОБЛЕМА: Скрипт выбрал сделку #{sorted_leads[0].get('id')}")
        print(f"   (последняя обновленная)")
        if 23243211 in [l.get('id') for l in sorted_leads]:
            print(f"✅ Сделка 23243211 ЕСТЬ в списке, но не выбрана!")
        else:
            print(f"❌ Сделки 23243211 НЕТ в списке!")
        print(f"{'='*60}\n")
        
    finally:
        await amo_client.close()
        mongo_client.close()


if __name__ == "__main__":
    asyncio.run(main())
