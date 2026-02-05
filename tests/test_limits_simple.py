#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Простой тест для проверки механики лимитов ElevenLabs.
Запуск: python tests/test_limits_simple.py
"""

import sys
import os

# Добавляем корень проекта в path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_calculate_credits():
    """Тест расчёта кредитов по длительности аудио."""
    
    # Формула из clinic_limits_service.py
    CREDITS_PER_MINUTE = 27.78  # PRO тариф: 500k / 300 часов
    
    def calculate_credits_from_duration(duration_seconds: float) -> int:
        duration_minutes = duration_seconds / 60
        credits = int(duration_minutes * CREDITS_PER_MINUTE) + 1
        return credits
    
    print("=" * 60)
    print("Тестирование механики лимитов ElevenLabs")
    print("=" * 60)
    
    test_durations = [0, 60, 180, 300, 600, 1800]  # 0, 1, 3, 5, 10, 30 минут
    
    print("\n📊 Расчёт кредитов по длительности аудио:")
    print("-" * 40)
    for duration in test_durations:
        credits = calculate_credits_from_duration(duration)
        minutes = duration / 60
        print(f"  {minutes:5.1f} мин ({duration:4d} сек) = {credits:5d} кредитов")
    
    # Проверка: 300 часов = 500k кредитов
    total_minutes = 300 * 60  # 18000 минут
    total_credits = calculate_credits_from_duration(total_minutes * 60)
    print(f"\n📊 Проверка полного PRO тарифа:")
    print(f"  300 часов ({total_minutes} минут) = {total_credits:,} кредитов")
    print(f"  Ожидалось ~500,000 кредитов")
    
    if 490000 < total_credits < 510000:
        print("\n✅ Расчёт корректный!")
    else:
        print("\n❌ Ошибка в расчёте!")
        return False
    
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
    
    # Сколько звонков можно сделать с 85000 кредитов?
    clinic_limit = 85000
    avg_call_duration = 300  # 5 минут
    credits_per_call = calculate_credits_from_duration(avg_call_duration)
    max_calls = clinic_limit // credits_per_call
    total_hours = max_calls * avg_call_duration / 3600
    
    print(f"\n📈 При лимите {clinic_limit:,} кредитов на клинику:")
    print(f"  Средний звонок ({avg_call_duration // 60} мин) = {credits_per_call} кредитов")
    print(f"  Максимум ~{max_calls} звонков в месяц")
    print(f"  Это ~{total_hours:.1f} часов аудио")
    
    return True


def test_elevenlabs_api():
    """Тест подключения к ElevenLabs API."""
    print("\n" + "=" * 60)
    print("Проверка подключения к ElevenLabs API")
    print("=" * 60)
    
    try:
        import requests
        
        # API ключ напрямую (тот же что в auth.py)
        api_key = "sk_4129c58f4a22730e19df27ad0a6a1c6b4391a7aaea7ba6a1"
        
        url = "https://api.elevenlabs.io/v1/user/subscription"
        headers = {"xi-api-key": api_key}
        
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            used = data.get("character_count", 0)
            limit = data.get("character_limit", 0)
            tier = data.get("tier", "unknown")
            remaining = limit - used
            percent = (used / limit * 100) if limit > 0 else 0
            
            print(f"\n✅ Подключение успешно!")
            print(f"  Тариф: {tier}")
            print(f"  Использовано: {used:,} / {limit:,} ({percent:.1f}%)")
            print(f"  Осталось: {remaining:,} кредитов")
            
            # Сколько это в часах
            remaining_hours = remaining / (27.78 * 60)
            print(f"  Это примерно {remaining_hours:.1f} часов аудио")
            return True
        else:
            print(f"❌ Ошибка API: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return False


if __name__ == "__main__":
    print("\n")
    
    ok1 = test_calculate_credits()
    ok2 = test_elevenlabs_api()
    
    print("\n" + "=" * 60)
    if ok1 and ok2:
        print("✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ!")
    else:
        print("❌ Есть ошибки!")
    print("=" * 60 + "\n")
