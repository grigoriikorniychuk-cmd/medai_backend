# -*- coding: utf-8 -*-
"""
Скрипт для обновления лимитов транскрибации всех клиник в базе данных.

Обновляет monthly_limit с 100 на 83,333 кредитов (эквивалент 3000 минут аудио).

Формула ElevenLabs PRO: 500,000 кредитов = 18,000 минут
27.78 кредитов/минуту = 0.463 кредитов/секунду

Лимит на клинику: 3000 минут × 27.78 = 83,333 кредитов (округлим до 85,000)

Запуск:
    python3 scripts/update_clinic_limits.py
"""

import asyncio
import sys
import os
from datetime import datetime

# Добавляем корневую директорию проекта в PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from motor.motor_asyncio import AsyncIOMotorClient
from app.config import MONGO_URI, DB_NAME


async def update_clinic_limits():
    """Обновляет monthly_limit для всех клиник с 100 на 80000 токенов."""
    
    print("=" * 80)
    print("📊 ОБНОВЛЕНИЕ ЛИМИТОВ ТРАНСКРИБАЦИИ ДЛЯ ВСЕХ КЛИНИК")
    print("=" * 80)
    print(f"\nПодключение к MongoDB: {MONGO_URI}")
    print(f"База данных: {DB_NAME}\n")
    
    mongo_client = None
    try:
        mongo_client = AsyncIOMotorClient(MONGO_URI)
        db = mongo_client[DB_NAME]
        clinics_collection = db.clinics
        
        # Получаем все клиники
        clinics = await clinics_collection.find({}).to_list(length=None)
        
        if not clinics:
            print("❌ В базе данных не найдено ни одной клиники.")
            return
        
        print(f"✅ Найдено {len(clinics)} клиник в базе данных.\n")
        print("-" * 80)
        
        updated_count = 0
        skipped_count = 0
        
        for clinic in clinics:
            clinic_id = clinic.get("_id")
            clinic_name = clinic.get("name", "Неизвестно")
            current_limit = clinic.get("monthly_limit", 0)
            current_usage = clinic.get("current_month_usage", 0)
            
            print(f"\n🏥 Клиника: {clinic_name} (ID: {clinic_id})")
            print(f"   Текущий лимит: {current_limit}")
            
            # Если лимит уже установлен на 85000, пропускаем
            if current_limit == 85000:
                print(f"   ℹ️  Лимит уже установлен на 85000 кредитов, пропускаем")
                skipped_count += 1
                continue
            
            # Обновляем лимит
            result = await clinics_collection.update_one(
                {"_id": clinic_id},
                {
                    "$set": {
                        "monthly_limit": 85000,
                        "updated_at": datetime.now().isoformat()
                    }
                }
            )
            
            if result.modified_count > 0:
                print(f"   ✅ Лимит обновлен: {current_limit} → 85000 кредитов")
                print(f"   📈 Текущее использование: {current_usage} токенов")
                updated_count += 1
            else:
                print(f"   ⚠️  Не удалось обновить лимит")
        
        print("\n" + "=" * 80)
        print("📊 ИТОГИ ОБНОВЛЕНИЯ:")
        print(f"   • Всего клиник: {len(clinics)}")
        print(f"   • Обновлено: {updated_count}")
        print(f"   • Пропущено (уже 85000): {skipped_count}")
        print("=" * 80)
        
        if updated_count > 0:
            print("\n✅ Лимиты успешно обновлены!")
            print("\nТеперь каждая клиника имеет месячный лимит: 85,000 кредитов (~3000 минут)")
        else:
            print("\nℹ️  Все клиники уже имеют актуальные лимиты.")
        
    except Exception as e:
        print(f"\n❌ Ошибка при обновлении лимитов: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if mongo_client:
            mongo_client.close()
            print("\n✅ Соединение с MongoDB закрыто.")


if __name__ == "__main__":
    print("\n🚀 Запуск скрипта обновления лимитов...\n")
    asyncio.run(update_clinic_limits())
    print("\n✅ Скрипт завершен.\n")
