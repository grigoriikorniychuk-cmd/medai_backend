"""
Тест автодетекции конфигурации конверсий для клиники.
Проверяет, может ли система автоматически найти:
- Воронки "Первичные пациенты" и "Вторичные пациенты"
- Статусы "Записались" в этих воронках
- Кастомное поле "Подтверждение" и enum "Подтвержден"
"""
import asyncio
import json
import sys
import os
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient

# Добавляем путь к модулям
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mlab_amo_async.amocrm_client import AsyncAmoCRMClient

# === КОНФИГУРАЦИЯ ===
MONGO_URI = "mongodb://92.113.151.220:27018/"
DB_NAME = "medai"
TARGET_CLIENT_ID = "3306c1e4-6022-45e3-b7b7-45646a8a5db6"  # Новая клиника для теста
OUTPUT_FILE = f"autodetected_config_{TARGET_CLIENT_ID[:8]}.json"


async def detect_pipelines_config(client):
    """
    Автоматически определяет воронки и статусы конверсий.
    Ищет по типичным названиям.
    """
    print(f"\n{'='*60}")
    print(f"🔍 АВТОДЕТЕКЦИЯ ВОРОНОК И СТАТУСОВ")
    print(f"{'='*60}")
    
    config = {
        "primary": {"pipeline_id": None, "pipeline_name": None, "status_id": None, "status_name": None},
        "secondary": {"pipeline_id": None, "pipeline_name": None, "status_id": None, "status_name": None}
    }
    
    try:
        # Получаем все воронки
        pipelines_resp, status = await client.leads.request("get", "leads/pipelines")
        
        if status != 200:
            print(f"❌ Ошибка при получении воронок: HTTP {status}")
            return config
        
        pipelines = pipelines_resp.get("_embedded", {}).get("pipelines", [])
        print(f"\n📊 Всего воронок найдено: {len(pipelines)}")
        
        # Показываем все воронки
        print("\n📋 Список всех воронок:")
        for pipeline in pipelines:
            print(f"   • ID: {pipeline['id']}, Название: '{pipeline.get('name', 'Без названия')}'")
        
        # Ищем "Первичные"
        print(f"\n🔎 Поиск воронки 'Первичные'...")
        for pipeline in pipelines:
            name = pipeline.get("name", "").lower()
            
            if "первичн" in name:
                config["primary"]["pipeline_id"] = pipeline["id"]
                config["primary"]["pipeline_name"] = pipeline.get("name")
                print(f"✅ Найдена воронка 'Первичные': ID={pipeline['id']}, Название='{pipeline.get('name')}'")
                
                # Ищем статус "Записались" в этой воронке
                print(f"   🔎 Поиск статуса 'Записались' в воронке...")
                statuses = pipeline.get("_embedded", {}).get("statuses", [])
                
                print(f"   📋 Статусы в воронке:")
                for status in statuses:
                    print(f"      • ID: {status['id']}, Название: '{status.get('name', 'Без названия')}'")
                
                for status in statuses:
                    status_name = status.get("name", "").lower()
                    if "запис" in status_name:
                        config["primary"]["status_id"] = status["id"]
                        config["primary"]["status_name"] = status.get("name")
                        print(f"   ✅ Найден статус: ID={status['id']}, Название='{status.get('name')}'")
                        break
                
                if not config["primary"]["status_id"]:
                    print(f"   ⚠️ Статус 'Записались' не найден в воронке 'Первичные'")
                break
        
        if not config["primary"]["pipeline_id"]:
            print(f"⚠️ Воронка 'Первичные' не найдена")
        
        # Ищем "Вторичные"
        print(f"\n🔎 Поиск воронки 'Вторичные'...")
        for pipeline in pipelines:
            name = pipeline.get("name", "").lower()
            
            if "вторичн" in name:
                config["secondary"]["pipeline_id"] = pipeline["id"]
                config["secondary"]["pipeline_name"] = pipeline.get("name")
                print(f"✅ Найдена воронка 'Вторичные': ID={pipeline['id']}, Название='{pipeline.get('name')}'")
                
                # Ищем статус "Записались"
                print(f"   🔎 Поиск статуса 'Записались' в воронке...")
                statuses = pipeline.get("_embedded", {}).get("statuses", [])
                
                print(f"   📋 Статусы в воронке:")
                for status in statuses:
                    print(f"      • ID: {status['id']}, Название: '{status.get('name', 'Без названия')}'")
                
                for status in statuses:
                    status_name = status.get("name", "").lower()
                    if "запис" in status_name:
                        config["secondary"]["status_id"] = status["id"]
                        config["secondary"]["status_name"] = status.get("name")
                        print(f"   ✅ Найден статус: ID={status['id']}, Название='{status.get('name')}'")
                        break
                
                if not config["secondary"]["status_id"]:
                    print(f"   ⚠️ Статус 'Записались' не найден в воронке 'Вторичные'")
                break
        
        if not config["secondary"]["pipeline_id"]:
            print(f"⚠️ Воронка 'Вторичные' не найдена")
        
        return config
        
    except Exception as e:
        print(f"❌ Ошибка при детекции воронок: {e}")
        import traceback
        traceback.print_exc()
        return config


async def detect_confirmation_field_config(client):
    """
    Автоматически определяет кастомное поле "Подтверждение" и enum "Подтвержден".
    """
    print(f"\n{'='*60}")
    print(f"🔍 АВТОДЕТЕКЦИЯ КАСТОМНОГО ПОЛЯ 'ПОДТВЕРЖДЕНИЕ'")
    print(f"{'='*60}")
    
    config = {
        "field_id": None,
        "field_name": None,
        "enum_id": None,
        "enum_name": None
    }
    
    try:
        page = 1
        all_fields = []
        
        while True:
            params = {"page": page, "limit": 250}
            resp, status = await client.leads.request("get", "leads/custom_fields", params=params)
            
            if status != 200:
                print(f"❌ Ошибка при получении кастомных полей: HTTP {status}")
                break
            
            fields = resp.get("_embedded", {}).get("custom_fields", [])
            if not fields:
                break
            
            all_fields.extend(fields)
            
            if "next" in resp.get("_links", {}):
                page += 1
            else:
                break
        
        print(f"\n📊 Всего кастомных полей найдено: {len(all_fields)}")
        
        # Показываем все поля типа "список" (enum)
        print(f"\n📋 Кастомные поля типа 'список':")
        enum_fields = [f for f in all_fields if f.get("type") == "select" or f.get("type") == "multiselect"]
        for field in enum_fields:
            print(f"   • ID: {field['id']}, Название: '{field.get('name', 'Без названия')}', Тип: {field.get('type')}")
        
        # Ищем поле "Подтверждение"
        print(f"\n🔎 Поиск поля 'Подтверждение'...")
        for field in all_fields:
            name = field.get("name", "").lower()
            
            if "подтвержд" in name or "подтверж" in name:
                config["field_id"] = field["id"]
                config["field_name"] = field.get("name")
                print(f"✅ Найдено поле: ID={field['id']}, Название='{field.get('name')}', Тип={field.get('type')}")
                
                # Ищем enum "Подтвержден"
                print(f"   🔎 Поиск enum 'Подтвержден' в поле...")
                enums = field.get("enums", [])
                
                print(f"   📋 Значения enum в поле:")
                for enum in enums:
                    print(f"      • ID: {enum['id']}, Значение: '{enum.get('value', 'Без значения')}'")
                
                for enum in enums:
                    enum_value = enum.get("value", "").lower()
                    # Ищем "подтвержд", но не "не подтвержден"
                    if "подтвержд" in enum_value and "не" not in enum_value:
                        config["enum_id"] = enum["id"]
                        config["enum_name"] = enum.get("value")
                        print(f"   ✅ Найден enum: ID={enum['id']}, Значение='{enum.get('value')}'")
                        break
                
                if not config["enum_id"]:
                    print(f"   ⚠️ Enum 'Подтвержден' не найден в поле")
                break
        
        if not config["field_id"]:
            print(f"⚠️ Поле 'Подтверждение' не найдено")
        
        return config
        
    except Exception as e:
        print(f"❌ Ошибка при детекции кастомного поля: {e}")
        import traceback
        traceback.print_exc()
        return config


async def main():
    """Основная функция теста."""
    print(f"\n{'='*60}")
    print(f"🧪 ТЕСТ АВТОДЕТЕКЦИИ КОНФИГУРАЦИИ КОНВЕРСИЙ")
    print(f"{'='*60}")
    
    # Подключаемся к MongoDB
    mongo_client = AsyncIOMotorClient(MONGO_URI)
    db = mongo_client[DB_NAME]
    clinics_collection = db.clinics
    
    # Находим клинику
    clinic = await clinics_collection.find_one({"client_id": TARGET_CLIENT_ID})
    
    if not clinic:
        print(f"❌ Клиника с client_id={TARGET_CLIENT_ID} не найдена в БД")
        mongo_client.close()
        return
    
    print(f"✅ Клиника найдена: {clinic.get('clinic_name', 'Без названия')}")
    print(f"   Субдомен: {clinic.get('amocrm_subdomain', 'Неизвестно')}")
    
    # Создаем клиент AmoCRM
    amo_client = AsyncAmoCRMClient(
        client_id=clinic["client_id"],
        client_secret=clinic["client_secret"],
        subdomain=clinic["amocrm_subdomain"],
        redirect_url=clinic["redirect_url"],
        mongo_uri=MONGO_URI,
        db_name=DB_NAME
    )
    
    try:
        # 1. Детектим воронки и статусы
        pipelines_config = await detect_pipelines_config(amo_client)
        
        # 2. Детектим кастомное поле подтверждения
        confirmation_config = await detect_confirmation_field_config(amo_client)
        
        # 3. Формируем итоговую конфигурацию
        final_config = {
            "client_id": TARGET_CLIENT_ID,
            "clinic_name": clinic.get("clinic_name", "Без названия"),
            "subdomain": clinic.get("amocrm_subdomain", "Неизвестно"),
            "auto_detected": True,
            "detected_at": datetime.now().isoformat(),
            "primary": pipelines_config["primary"],
            "secondary": pipelines_config["secondary"],
            "confirmation_field": confirmation_config
        }
        
        # 4. Проверяем полноту конфигурации
        print(f"\n{'='*60}")
        print(f"📊 ИТОГОВАЯ КОНФИГУРАЦИЯ")
        print(f"{'='*60}")
        
        is_complete = all([
            final_config["primary"]["pipeline_id"],
            final_config["primary"]["status_id"],
            final_config["secondary"]["pipeline_id"],
            final_config["secondary"]["status_id"],
            final_config["confirmation_field"]["field_id"],
            final_config["confirmation_field"]["enum_id"]
        ])
        
        print(f"\n🎯 Статус конфигурации: {'✅ ПОЛНАЯ' if is_complete else '⚠️ НЕПОЛНАЯ'}")
        print(f"\nДетали:")
        print(f"  Первичные:")
        print(f"    • Воронка: {'✅' if final_config['primary']['pipeline_id'] else '❌'} {final_config['primary']['pipeline_name']} (ID: {final_config['primary']['pipeline_id']})")
        print(f"    • Статус: {'✅' if final_config['primary']['status_id'] else '❌'} {final_config['primary']['status_name']} (ID: {final_config['primary']['status_id']})")
        print(f"  Вторичные:")
        print(f"    • Воронка: {'✅' if final_config['secondary']['pipeline_id'] else '❌'} {final_config['secondary']['pipeline_name']} (ID: {final_config['secondary']['pipeline_id']})")
        print(f"    • Статус: {'✅' if final_config['secondary']['status_id'] else '❌'} {final_config['secondary']['status_name']} (ID: {final_config['secondary']['status_id']})")
        print(f"  Подтверждение:")
        print(f"    • Поле: {'✅' if final_config['confirmation_field']['field_id'] else '❌'} {final_config['confirmation_field']['field_name']} (ID: {final_config['confirmation_field']['field_id']})")
        print(f"    • Enum: {'✅' if final_config['confirmation_field']['enum_id'] else '❌'} {final_config['confirmation_field']['enum_name']} (ID: {final_config['confirmation_field']['enum_id']})")
        
        # 5. Сохраняем в JSON файл
        output_file = f"autodetected_config_{TARGET_CLIENT_ID[:8]}.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(final_config, f, ensure_ascii=False, indent=2)
        
        print(f"\n💾 Конфигурация сохранена в: {output_file}")
        
        # 6. Рекомендации
        print(f"\n{'='*60}")
        print(f"💡 РЕКОМЕНДАЦИИ")
        print(f"{'='*60}")
        
        if is_complete:
            print("✅ Конфигурация полная и готова к использованию!")
            print("   Можно автоматически использовать для обогащения конверсий.")
        else:
            print("⚠️ Конфигурация неполная. Возможные причины:")
            if not final_config["primary"]["pipeline_id"]:
                print("   • Не найдена воронка 'Первичные пациенты' (или название отличается)")
            if not final_config["primary"]["status_id"]:
                print("   • Не найден статус 'Записались' в воронке 'Первичные'")
            if not final_config["secondary"]["pipeline_id"]:
                print("   • Не найдена воронка 'Вторичные пациенты' (или название отличается)")
            if not final_config["secondary"]["status_id"]:
                print("   • Не найден статус 'Записались' в воронке 'Вторичные'")
            if not final_config["confirmation_field"]["field_id"]:
                print("   • Не найдено кастомное поле 'Подтверждение'")
            if not final_config["confirmation_field"]["enum_id"]:
                print("   • Не найден enum 'Подтвержден' в поле 'Подтверждение'")
            print("\n   Потребуется ручная настройка через админ-панель.")
        
        print(f"{'='*60}\n")
        
    finally:
        await amo_client.close()
        mongo_client.close()


if __name__ == "__main__":
    asyncio.run(main())
