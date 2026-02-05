#!/usr/bin/env python3
"""
Скрипт миграции для исправления неправильных оценок бинарных критериев в MongoDB.

Исправляет:
- appointment (должен быть 0 или 10)
- patient_booking (должен быть 0 или 10, берется из conversion)
- clinic_address (должен быть 0 или 10)
- passport (должен быть 0 или 10)

AI иногда игнорировал инструкции и ставил промежуточные оценки (2-9).
"""
import os
import sys
from pymongo import MongoClient
from datetime import datetime

# Добавляем корневую директорию в PYTHONPATH
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Настройки MongoDB
MONGO_URI = os.getenv("MONGODB_URI", "mongodb://92.113.151.220:27018/")
MONGO_DB = os.getenv("MONGODB_NAME", "medai")


def fix_binary_criteria():
    """Исправляет бинарные критерии в MongoDB"""
    print("🔧 Подключение к MongoDB...")
    client = MongoClient(MONGO_URI)
    db = client[MONGO_DB]
    calls_collection = db['calls']

    # Бинарные критерии
    binary_criteria = ['appointment', 'patient_booking', 'clinic_address', 'passport']

    # Статистика
    total_calls = 0
    total_fixes = 0
    fixes_by_criterion = {criterion: 0 for criterion in binary_criteria}

    print(f"📊 Поиск звонков с метриками...")

    # Находим все звонки с метриками
    calls = calls_collection.find({
        'metrics': {'$exists': True, '$ne': None}
    })

    for call in calls:
        total_calls += 1
        metrics = call.get('metrics', {})
        conversion = metrics.get('conversion', False)

        updates = {}
        call_has_fixes = False

        for criterion in binary_criteria:
            if criterion in metrics:
                original_value = metrics[criterion]

                # Пропускаем если значение None
                if original_value is None:
                    continue

                # Специальная обработка для patient_booking - берем из conversion
                if criterion == 'patient_booking':
                    correct_value = 10 if conversion else 0
                else:
                    # Для остальных: < 5 -> 0, >= 5 -> 10
                    correct_value = 10 if original_value >= 5 else 0

                # Проверяем нужна ли корректировка
                if original_value not in [0, 10] or (criterion == 'patient_booking' and original_value != correct_value):
                    updates[f'metrics.{criterion}'] = correct_value
                    fixes_by_criterion[criterion] += 1
                    print(f"  🔧 note_id={call.get('note_id')}: {criterion} {original_value} -> {correct_value}")

        # Применяем исправления если есть
        if updates:
            total_fixes += 1
            calls_collection.update_one(
                {'_id': call['_id']},
                {'$set': updates}
            )

    print("\n" + "="*60)
    print("✅ МИГРАЦИЯ ЗАВЕРШЕНА")
    print("="*60)
    print(f"Всего обработано звонков: {total_calls}")
    print(f"Исправлено звонков: {total_fixes}")
    print(f"\nИсправлений по критериям:")
    for criterion, count in fixes_by_criterion.items():
        if count > 0:
            print(f"  - {criterion}: {count}")

    client.close()


if __name__ == "__main__":
    print("🚀 Запуск миграции для исправления бинарных критериев")
    print(f"📅 Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)

    try:
        fix_binary_criteria()
    except Exception as e:
        print(f"\n❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
