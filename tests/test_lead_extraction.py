#!/usr/bin/env python3
"""
Тестовый скрипт для проверки извлечения lead_id из событий amoCRM
Повторяет логику эндпоинта /api/calls-events/export
Результат сохраняется в test_calls_export.json
"""
import asyncio
import json
from datetime import datetime
from mlab_amo_async.amocrm_client import AsyncAmoCRMClient
from app.routers.calls_events import get_call_details, get_calls_from_events
from motor.motor_asyncio import AsyncIOMotorClient
import os

# НАСТРОЙКИ ТЕСТА
# ============================================
TEST_CLIENT_ID = "500655e7-f5b7-49e2-bd8f-5907f68e5578"
TEST_DATE = "01.10.2025"
OUTPUT_FILE = "test_calls_export.json"
MAX_CALLS_TO_TEST = 10  # Максимум звонков для теста
MAX_CALLS_TO_CONTACT_ID = 34722513  # Контакт из свежих данных test_calls_export.json (01.10.2025) теста

# MongoDB - используем продакшн
MONGO_URI = "mongodb://92.113.151.220:27018/"
DB_NAME = "medai"
# ============================================
async def test_lead_extraction():
    """Тестирует извлечение lead_id из событий за указанную дату"""
    
    print("="*60)
    print("🚀 ТЕСТ ИЗВЛЕЧЕНИЯ lead_id ИЗ СОБЫТИЙ")
    print("="*60)
    print(f"📋 Client ID: {TEST_CLIENT_ID}")
    print(f"📅 Дата: {TEST_DATE}")
    print(f"💾 Файл результата: {OUTPUT_FILE}")
    print(f"🗄️  MongoDB: {MONGO_URI}")
    print("="*60)
    
    # Шаг 1: Подключаемся к MongoDB напрямую
    print("\n[1/5] Подключение к продакшн MongoDB...")
    mongo_client = AsyncIOMotorClient(MONGO_URI)
    db = mongo_client[DB_NAME]
    
    # Получаем клинику из коллекции clinics
    print(f"[1/5] Поиск клиники с client_id={TEST_CLIENT_ID}...")
    clinic = await db.clinics.find_one({"client_id": TEST_CLIENT_ID})
    
    if not clinic:
        print(f"❌ ОШИБКА: Клиника с client_id={TEST_CLIENT_ID} не найдена в БД")
        mongo_client.close()
        return
    
    subdomain = clinic.get("amocrm_subdomain")
    print(f"✅ Клиника найдена: {clinic.get('name')} (subdomain={subdomain})")
    
    # Шаг 2: Инициализируем клиент amoCRM (токены из MongoDB)
    print("\n[2/5] Инициализация клиента amoCRM...")
    client = AsyncAmoCRMClient(
        client_id=clinic["client_id"],
        client_secret=clinic["client_secret"],
        subdomain=subdomain,
        redirect_url=clinic["redirect_url"],
        mongo_uri=MONGO_URI,
        db_name=DB_NAME
    )
    print("✅ Клиент amoCRM создан (токены из MongoDB)")
    
    # Шаг 3: Конвертируем дату в timestamp
    print(f"\n[3/5] Подготовка периода для фильтрации...")
    target_datetime = datetime.strptime(TEST_DATE, "%d.%m.%Y")
    start_timestamp = int(target_datetime.timestamp())
    end_timestamp = start_timestamp + 86400  # +24 часа
    print(f"✅ Период: {target_datetime.strftime('%Y-%m-%d %H:%M:%S')} -> {datetime.fromtimestamp(end_timestamp).strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Шаг 4: Получаем события звонков через функцию get_calls_from_events
    print(f"\n[4/5] Получение событий звонков из amoCRM...")
    try:
        # Используем ту же функцию, что и в эндпоинте
        events = await get_calls_from_events(
            client=client,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            max_pages=5  # Ограничиваем для теста
        )
        
        if not events:
            print("❌ Нет событий за указанную дату")
            return
        
        print(f"✅ Получено {len(events)} событий за {TEST_DATE}")
        
        # Берем максимум MAX_CALLS_TO_TEST для теста
        events_to_process = events[:MAX_CALLS_TO_TEST]
        print(f"✅ Будет обработано: {len(events_to_process)} событий")
        
        # Шаг 5: Обрабатываем события через get_call_details
        print(f"\n[5/5] Обработка событий через get_call_details()...")
        print("="*60)
        
        results = []
        administrator = "Неизвестный"  # Значения по умолчанию
        source = "Неопределенный"
        
        for i, event in enumerate(events_to_process, 1):
            event_id = event.get('id')
            entity_type = event.get("entity_type")
            entity_id = event.get("entity_id")
            event_type = event.get("type")
            created_at = event.get("created_at")
            
            print(f"\n[Событие {i}/{len(events_to_process)}]")
            print(f"   ID: {event_id}")
            print(f"   Тип: {event_type} | Сущность: {entity_type} (ID: {entity_id})")
            print(f"   Время: {datetime.fromtimestamp(created_at).strftime('%Y-%m-%d %H:%M:%S')}")
            
            try:
                # ⚡ КЛЮЧЕВОЙ МОМЕНТ: Вызываем get_call_details - ту же функцию, что в эндпоинте!
                print(f"   ⚙️  Вызов get_call_details()...")
                call_record = await get_call_details(
                    event=event,
                    client=client,
                    administrator=administrator,
                    source=source,
                    client_id_str=TEST_CLIENT_ID,
                    subdomain_str=subdomain
                )
                
                if call_record:
                    lead_id = call_record.get('lead_id')
                    
                    if lead_id:
                        print(f"   ✅ lead_id = {lead_id}")
                    else:
                        print(f"   ❌ lead_id = None")
                    
                    # Добавляем в результаты
                    results.append(call_record)
                else:
                    print(f"   ⚠️  get_call_details вернул None")
                    
            except Exception as e:
                print(f"   ❌ ОШИБКА при обработке: {e}")
                import traceback
                traceback.print_exc()
        
        # Финальная статистика
        print("\n" + "="*60)
        print("📊 ИТОГОВАЯ СТАТИСТИКА")
        print("="*60)
        
        total = len(results)
        with_lead = sum(1 for r in results if r.get("lead_id"))
        without_lead = total - with_lead
        
        print(f"Всего обработано событий: {total}")
        if total > 0:
            print(f"С lead_id: {with_lead} ({with_lead/total*100:.1f}%)")
            print(f"БЕЗ lead_id (null): {without_lead} ({without_lead/total*100:.1f}%)")
        else:
            print(f"⚠️  Ни одно событие не было успешно обработано")
        
        # Сохраняем результаты в JSON
        print(f"\n💾 Сохранение результатов в {OUTPUT_FILE}...")
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "test_info": {
                    "test_time": datetime.now().isoformat(),
                    "client_id": TEST_CLIENT_ID,
                    "subdomain": subdomain,
                    "target_date": TEST_DATE
                },
                "statistics": {
                    "total_events": total,
                    "events_with_lead_id": with_lead,
                    "events_without_lead_id": without_lead,
                    "percentage_with_lead": round(with_lead/total*100, 1) if total > 0 else 0
                },
                "calls": results
            }, f, indent=2, ensure_ascii=False)
        
        print(f"✅ Файл сохранён: {OUTPUT_FILE}")
        print("="*60)
        
    except Exception as e:
        print(f"\n❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Закрываем подключение к MongoDB
        if 'mongo_client' in locals():
            mongo_client.close()
            print("\n🔌 MongoDB соединение закрыто")

if __name__ == "__main__":
    asyncio.run(test_lead_extraction())
