"""
Скрипт для перерасчёта администраторов для звонков
Использует существующие транскрипции, не тратит токены на повторную транскрипцию

Использование:
    python recalculate_admins_jan5.py [дата]
    
Примеры:
    python recalculate_admins_jan5.py 2026-01-07
    python recalculate_admins_jan5.py  # по умолчанию 2026-01-05
"""

import asyncio
import os
import sys
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId

# Настройки
MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongodb:27017/")
DB_NAME = "medai"

# Дата из аргумента командной строки или по умолчанию
TARGET_DATE = sys.argv[1] if len(sys.argv) > 1 else "2026-01-05"

# Можно указать конкретную клинику или None для всех клиник с методом ai_schedule
CLINIC_ID = None  # None = все клиники с ai_schedule


async def recalculate_administrators():
    """Перерасчитывает администраторов для звонков с существующими транскрипциями"""
    
    client = AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]
    
    try:
        print(f"🔍 Поиск звонков на дату {TARGET_DATE}...")
        
        # Формируем запрос
        query = {
            "created_date_for_filtering": TARGET_DATE,
            "transcription_status": "success"
        }
        
        # Если указана конкретная клиника
        if CLINIC_ID:
            query["client_id"] = CLINIC_ID
            print(f"   Клиника: {CLINIC_ID}")
        else:
            # Ищем все клиники с методом ai_schedule
            clinics = await db.clinics.find({"admin_detection_method": "ai_schedule"}).to_list(length=100)
            clinic_ids = [c["client_id"] for c in clinics]
            query["client_id"] = {"$in": clinic_ids}
            print(f"   Найдено клиник с методом ai_schedule: {len(clinic_ids)}")
        
        calls = await db.calls.find(query).to_list(length=10000)
        total = len(calls)
        
        print(f"📋 Найдено {total} звонков с транскрипциями\n")
        
        if total == 0:
            print("❌ Нет звонков для обработки")
            return
        
        # Импортируем функцию определения администратора
        from app.services.admin_detection_service import determine_administrator_for_call
        
        updated = 0
        errors = 0
        unchanged = 0
        
        for i, call in enumerate(calls, 1):
            call_id = str(call["_id"])
            old_admin = call.get("administrator", "Неизвестный администратор")
            
            try:
                # Получаем транскрипцию из файла
                transcription_file = call.get("filename_transcription")
                if not transcription_file:
                    print(f"⚠️  [{i}/{total}] Звонок {call_id}: нет файла транскрипции")
                    errors += 1
                    continue
                
                # Определяем путь к транскрипциям (Docker или локально)
                if os.path.exists("/app/app/data/transcription"):
                    transcription_path = f"/app/app/data/transcription/{transcription_file}"
                else:
                    transcription_path = f"/home/mpr0/Develop/medai_backend/app/data/transcriptions/{transcription_file}"
                
                if not os.path.exists(transcription_path):
                    print(f"⚠️  [{i}/{total}] Звонок {call_id}: файл не найден {transcription_path}")
                    errors += 1
                    continue
                
                # Читаем транскрипцию
                with open(transcription_path, 'r', encoding='utf-8') as f:
                    transcription_text = f.read()
                
                if not transcription_text.strip():
                    print(f"⚠️  [{i}/{total}] Звонок {call_id}: пустая транскрипция")
                    errors += 1
                    continue
                
                # Получаем дату звонка из created_date_for_filtering
                call_date = datetime.strptime(TARGET_DATE, "%Y-%m-%d").date()
                
                # Определяем администратора
                new_admin = await determine_administrator_for_call(
                    clinic_id=call["client_id"],  # Используем client_id из звонка
                    call_date=call_date,
                    transcription_text=transcription_text,
                    responsible_user_id=call.get("responsible_user_id"),
                )

                # === КРИТИЧЕСКАЯ ПРАВКА ===
                # Если AI вернул имя, которого нет в графике - заменяем на "Неизвестный администратор"
                if new_admin and new_admin != "Неизвестный администратор":
                    # Проверяем что этот администратор ЕСТЬ в графике
                    from app.services.schedule_service import ScheduleService
                    schedule_service = ScheduleService()
                    admins_in_schedule = await schedule_service.get_schedule_for_date(
                        clinic_id=call["client_id"],
                        call_date=call_date
                    )

                    if admins_in_schedule:
                        # Формируем список полных имён из графика
                        valid_admins = set()
                        for admin in admins_in_schedule:
                            full_name = f"{admin['first_name']} {admin['last_name']}".strip()
                            valid_admins.add(full_name)
                            # Добавляем и просто имя (без фамилии)
                            valid_admins.add(admin['first_name'])

                        # Проверяем что new_admin есть в списке валидных
                        if new_admin not in valid_admins:
                            print(f"⚠️  [{i}/{total}] AI вернул имя '{new_admin}' которого нет в графике {valid_admins}")
                            new_admin = "Неизвестный администратор"

                # Обновляем только если администратор изменился
                if new_admin != old_admin:
                    await db.calls.update_one(
                        {"_id": ObjectId(call_id)},
                        {"$set": {
                            "administrator": new_admin,
                            "updated_at": datetime.now()
                        }}
                    )
                    
                    print(f"✅ [{i}/{total}] Звонок {call_id}: '{old_admin}' → '{new_admin}'")
                    updated += 1
                else:
                    print(f"➖ [{i}/{total}] Звонок {call_id}: без изменений ('{old_admin}')")
                    unchanged += 1
                    
            except Exception as e:
                print(f"❌ [{i}/{total}] Ошибка для звонка {call_id}: {e}")
                errors += 1
                continue
        
        print(f"\n{'='*60}")
        print(f"📊 ИТОГО:")
        print(f"   Обработано: {total}")
        print(f"   ✅ Обновлено: {updated}")
        print(f"   ➖ Без изменений: {unchanged}")
        print(f"   ❌ Ошибок: {errors}")
        print(f"{'='*60}")
        
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(recalculate_administrators())
