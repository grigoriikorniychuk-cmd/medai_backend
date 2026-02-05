#!/usr/bin/env python3
"""
Скрипт для ручного сброса недельных лимитов всех клиник.
Использовать когда нужно принудительно сбросить счетчики.
"""

import asyncio
import os
from datetime import datetime, timedelta
from motor.motor_asyncio import AsyncIOMotorClient

# Настройки MongoDB
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "medai")

async def reset_all_weekly_limits():
    """Сбрасывает недельные лимиты всех клиник"""
    
    client = AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]
    
    # Находим последний понедельник 00:00
    now = datetime.now()
    days_since_monday = now.weekday()
    last_monday = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_since_monday)
    
    print(f"Сброс недельных лимитов на дату: {last_monday}")
    print("-" * 50)
    
    # Получаем все клиники
    clinics = await db.clinics.find({}).to_list(length=100)
    
    for clinic in clinics:
        client_id = clinic.get("client_id")
        name = clinic.get("name", "Unknown")
        current_week = clinic.get("current_week_minutes", 0)
        last_reset = clinic.get("last_week_reset_date")
        
        # Обновляем
        await db.clinics.update_one(
            {"client_id": client_id},
            {
                "$set": {
                    "current_week_minutes": 0,
                    "last_week_reset_date": last_monday.isoformat()
                }
            }
        )
        
        print(f"✅ {name} ({client_id})")
        print(f"   Было: {current_week:.2f} минут")
        print(f"   Последний сброс: {last_reset}")
        print(f"   Новый сброс: {last_monday.isoformat()}")
        print()
    
    print(f"Всего обработано клиник: {len(clinics)}")
    client.close()

if __name__ == "__main__":
    asyncio.run(reset_all_weekly_limits())
