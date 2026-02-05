#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для пересчета администраторов для звонков с 'Неизвестный администратор'
для клиник с методом определения 'ai_schedule'.

Использует исправленную логику fuzzy matching.

Запуск:
    python scripts/recalculate_administrators.py --client-id be735efe-2f45-4262-9df1-289db57a71b5 --dry-run
    python scripts/recalculate_administrators.py --client-id be735efe-2f45-4262-9df1-289db57a71b5 --date 2025-12-29
    python scripts/recalculate_administrators.py --client-id be735efe-2f45-4262-9df1-289db57a71b5
"""

import asyncio
import argparse
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path
import sys

# Добавляем корень проекта в sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId

MONGO_URI = "mongodb://92.113.151.220:27018/"
DB_NAME = "medai"


async def recalculate_administrators(
    client_id: str,
    date_filter: Optional[str] = None,
    dry_run: bool = True,
    limit: int = 0,
    yes: bool = False
):
    """
    Пересчитывает администраторов для звонков с 'Неизвестный администратор'
    
    Args:
        client_id: ID клиники
        date_filter: Дата в формате YYYY-MM-DD (опционально)
        dry_run: Если True, только показывает что будет изменено
        limit: Максимальное количество звонков для обработки (0 = без лимита)
        yes: Автоматическое подтверждение без запроса (для Docker)
    """
    
    mongo_client = AsyncIOMotorClient(MONGO_URI)
    db = mongo_client[DB_NAME]
    
    try:
        # Проверяем клинику
        clinic = await db.clinics.find_one({"client_id": client_id})
        if not clinic:
            print(f"❌ Клиника с client_id={client_id} не найдена")
            return
        
        detection_method = clinic.get("admin_detection_method", "amocrm")
        
        print("=" * 80)
        print(f"🏥 Клиника: {clinic.get('name')}")
        print(f"   ID: {client_id}")
        print(f"   Метод определения: {detection_method}")
        
        if detection_method != "ai_schedule":
            print(f"⚠️  Внимание: метод определения не 'ai_schedule'")
            response = input("   Продолжить? (y/n): ")
            if response.lower() != 'y':
                return
        
        # Формируем запрос
        query = {
            "client_id": client_id,
            "administrator": "Неизвестный администратор",
            "transcription_status": "success"  # Только с готовой транскрипцией
        }
        
        if date_filter:
            query["created_date_for_filtering"] = date_filter
            print(f"   Дата фильтра: {date_filter}")
        
        print(f"   Режим: {'DRY RUN (без изменений)' if dry_run else 'ЗАПИСЬ В БАЗУ'}")
        if limit > 0:
            print(f"   Лимит: {limit} звонков")
        print("=" * 80)
        
        # Подсчитываем звонки
        total_calls = await db.calls.count_documents(query)
        print(f"\n📞 Найдено звонков с 'Неизвестный администратор': {total_calls}")
        
        if total_calls == 0:
            print("✅ Нет звонков для обработки")
            return
        
        if not dry_run and not yes:
            response = input(f"\n⚠️  Будет обновлено {total_calls} звонков. Продолжить? (y/n): ")
            if response.lower() != 'y':
                print("❌ Отменено пользователем")
                return
        
        # Получаем звонки
        cursor = db.calls.find(query)
        if limit > 0:
            cursor = cursor.limit(limit)
        
        calls = await cursor.to_list(length=limit if limit > 0 else None)
        
        print(f"\n🔄 Обработка {len(calls)} звонков...")
        print("=" * 80)
        
        # Импортируем сервис
        from app.services.admin_detection_service import determine_administrator_for_call
        
        # Статистика
        stats = {
            "processed": 0,
            "updated": 0,
            "no_change": 0,
            "errors": 0,
            "by_admin": {}
        }
        
        # Обрабатываем каждый звонок
        for i, call in enumerate(calls, 1):
            call_id = str(call["_id"])
            
            try:
                # Получаем транскрипцию
                transcription_file = call.get("filename_transcription")
                if not transcription_file:
                    print(f"   {i}/{len(calls)}: ⚠️  Нет файла транскрипции, пропускаем")
                    stats["errors"] += 1
                    continue
                
                # Читаем транскрипцию
                import os
                
                # Пробуем несколько путей (локально и на сервере)
                possible_paths = [
                    f"/home/mpr0/Develop/medai_backend/app/data/transcription/{transcription_file}",
                    f"/app/data/transcription/{transcription_file}",
                    f"app/data/transcription/{transcription_file}",
                ]
                
                transcription_text = None
                for transcription_path in possible_paths:
                    if os.path.exists(transcription_path):
                        with open(transcription_path, 'r', encoding='utf-8') as f:
                            transcription_text = f.read()
                        break
                
                if not transcription_text:
                    print(f"   {i}/{len(calls)}: ⚠️  Файл транскрипции не найден ({transcription_file}), пропускаем")
                    stats["errors"] += 1
                    continue
                
                # Определяем дату звонка
                call_date = datetime.fromtimestamp(call["created_at"]).date()
                
                # Определяем администратора
                new_admin = await determine_administrator_for_call(
                    clinic_id=client_id,
                    call_date=call_date,
                    transcription_text=transcription_text,
                    responsible_user_id=call.get("responsible_user_id")
                )
                
                stats["processed"] += 1
                
                if new_admin != "Неизвестный администратор":
                    # Обновляем в базе
                    if not dry_run:
                        await db.calls.update_one(
                            {"_id": call["_id"]},
                            {"$set": {"administrator": new_admin}}
                        )
                    
                    stats["updated"] += 1
                    stats["by_admin"][new_admin] = stats["by_admin"].get(new_admin, 0) + 1
                    
                    print(f"   {i}/{len(calls)}: ✅ {call.get('contact_name', 'Без имени')[:30]:30} -> {new_admin}")
                else:
                    stats["no_change"] += 1
                    if i % 10 == 0:  # Показываем каждый 10-й
                        print(f"   {i}/{len(calls)}: ⚠️  Не определён")
                
            except Exception as e:
                stats["errors"] += 1
                print(f"   {i}/{len(calls)}: ❌ Ошибка: {str(e)}")
        
        # Итоговая статистика
        print("\n" + "=" * 80)
        print("📊 СТАТИСТИКА:")
        print("=" * 80)
        print(f"   Обработано звонков: {stats['processed']}")
        print(f"   Обновлено: {stats['updated']}")
        print(f"   Без изменений: {stats['no_change']}")
        print(f"   Ошибок: {stats['errors']}")
        
        if stats["by_admin"]:
            print("\n   Распределение по администраторам:")
            for admin, count in sorted(stats["by_admin"].items(), key=lambda x: x[1], reverse=True):
                print(f"      - {admin}: {count}")
        
        print("=" * 80)
        
        if dry_run:
            print("\n⚠️  DRY RUN: изменения не были сохранены в базу")
            print("   Для сохранения запустите без флага --dry-run")
        else:
            print("\n✅ Изменения сохранены в базу данных")
        
    finally:
        mongo_client.close()


async def main():
    parser = argparse.ArgumentParser(
        description="Пересчёт администраторов для звонков с 'Неизвестный администратор'"
    )
    parser.add_argument(
        "--client-id",
        required=True,
        help="ID клиники (client_id)"
    )
    parser.add_argument(
        "--date",
        help="Дата для фильтрации в формате YYYY-MM-DD (опционально)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только показать изменения без записи в базу"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Максимальное количество звонков для обработки (0 = без лимита)"
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Автоматическое подтверждение без запроса (для Docker)"
    )
    
    args = parser.parse_args()
    
    await recalculate_administrators(
        client_id=args.client_id,
        date_filter=args.date,
        dry_run=args.dry_run,
        limit=args.limit,
        yes=args.yes
    )


if __name__ == "__main__":
    asyncio.run(main())
