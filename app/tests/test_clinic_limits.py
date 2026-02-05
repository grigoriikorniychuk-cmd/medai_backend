# -*- coding: utf-8 -*-
"""
Тесты для проверки механики лимитов использования ElevenLabs по клиникам.

Запуск простого теста:
    python app/tests/test_clinic_limits.py
    
Запуск полных тестов (требует pytest):
    pytest app/tests/test_clinic_limits.py -v
"""

# Простой тест который можно запустить напрямую (без pytest)
if __name__ == "__main__":
    import sys
    import os
    
    # Добавляем корневую директорию в path
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    
    # Импортируем напрямую из файла, минуя __init__.py
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "clinic_limits_service", 
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                     "services", "clinic_limits_service.py")
    )
    clinic_limits = importlib.util.module_from_spec(spec)
    
    # Мокаем зависимости перед загрузкой
    import logging
    logging.basicConfig(level=logging.INFO)
    
    # Создаём фейковый mongodb_service
    class FakeMongoService:
        async def find_one(self, *args, **kwargs): return None
        async def update_one(self, *args, **kwargs): return True
    
    # Подставляем мок
    import types
    fake_mongodb = types.ModuleType("mongodb_service")
    fake_mongodb.mongodb_service = FakeMongoService()
    sys.modules["app.services.mongodb_service"] = fake_mongodb
    sys.modules[".mongodb_service"] = fake_mongodb
    
    spec.loader.exec_module(clinic_limits)
    calculate_credits_from_duration = clinic_limits.calculate_credits_from_duration
    
    print("=" * 60)
    print("Тестирование механики лимитов ElevenLabs")
    print("=" * 60)
    
    # Тест расчёта кредитов
    test_durations = [0, 60, 180, 300, 600, 1800]  # 0, 1, 3, 5, 10, 30 минут
    
    print("\n📊 Расчёт кредитов по длительности аудио:")
    print("-" * 40)
    for duration in test_durations:
        credits = calculate_credits_from_duration(duration)
        minutes = duration / 60
        print(f"  {minutes:5.1f} мин ({duration:4d} сек) = {credits:5d} кредитов")
    
    # Проверка: 300 часов = 500k кредитов
    total_minutes = 300 * 60  # 18000 минут
    total_credits = calculate_credits_from_duration(total_minutes * 60)  # в секундах
    print(f"\n📊 Проверка полного PRO тарифа:")
    print(f"  300 часов ({total_minutes} минут) = {total_credits:,} кредитов")
    print(f"  Ожидалось ~500,000 кредитов")
    
    if 490000 < total_credits < 510000:
        print("\n✅ Расчёт корректный!")
    else:
        print("\n❌ Ошибка в расчёте!")
        sys.exit(1)
    
    # Тест типичных звонков
    print("\n📞 Типичные звонки:")
    print("-" * 40)
    typical_calls = [
        (120, "короткий звонок 2 мин"),
        (300, "средний звонок 5 мин"),
        (600, "длинный звонок 10 мин"),
    ]
    for duration, desc in typical_calls:
        credits = calculate_credits_from_duration(duration)
        print(f"  {desc}: {credits} кредитов")
    
    # Сколько звонков можно сделать с 85000 кредитов (лимит на клинику)?
    clinic_limit = 85000
    avg_call_duration = 300  # 5 минут средний звонок
    credits_per_call = calculate_credits_from_duration(avg_call_duration)
    max_calls = clinic_limit // credits_per_call
    
    print(f"\n📈 При лимите {clinic_limit:,} кредитов на клинику:")
    print(f"  Средний звонок ({avg_call_duration // 60} мин) = {credits_per_call} кредитов")
    print(f"  Максимум ~{max_calls} звонков в месяц")
    print(f"  Это ~{max_calls * avg_call_duration // 60} минут = ~{max_calls * avg_call_duration // 3600} часов")
    
    print("\n" + "=" * 60)
    print("✅ Все тесты пройдены успешно!")
    print("=" * 60)


# Pytest тесты (опциональные)
try:
    import pytest
    import asyncio
    from datetime import datetime
    
    class TestCreditsCalculation:
        """Тесты расчёта кредитов на основе длительности аудио."""
        
        def test_calculate_credits_from_duration_1_minute(self):
            """Тест: 1 минута аудио = ~28 кредитов."""
            from app.services.clinic_limits_service import calculate_credits_from_duration
            
            credits = calculate_credits_from_duration(60)
            assert credits == 28 or credits == 29, f"Expected ~28, got {credits}"
        
        def test_calculate_credits_from_duration_5_minutes(self):
            """Тест: 5 минут аудио = ~139 кредитов."""
            from app.services.clinic_limits_service import calculate_credits_from_duration
            
            credits = calculate_credits_from_duration(300)
            assert 138 <= credits <= 141, f"Expected ~140, got {credits}"

except ImportError:
    pass  # pytest не установлен, пропускаем эти тесты
