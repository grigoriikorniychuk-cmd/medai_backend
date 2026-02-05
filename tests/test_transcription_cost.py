#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Эксперимент: точное измерение стоимости транскрибации

Скрипт измеряет реальное количество кредитов, списанных за транскрибацию.
"""

import asyncio
import sys
import os
import requests
import json
from datetime import datetime

# Добавляем корневую директорию проекта в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# API ключ ElevenLabs
# API_KEY = "sk_496a68bf0f91cde4c3069e39c9dc9b8b54339285daf412f5"
# API_KEY = "sk_a366693fc3a5882b3f8dd02d20b81aaccc92d0d307544863"
API_KEY = "sk_4129c58f4a22730e19df27ad0a6a1c6b4391a7aaea7ba6a1"

from app.services.transcription_service import transcribe_and_save
from app.settings import AUDIO_DIR, TRANSCRIPTION_DIR


def get_elevenlabs_usage():
    """Получает текущее использование из ElevenLabs API."""
    url = "https://api.elevenlabs.io/v1/user/subscription"
    headers = {
        "Accept": "application/json",
        "xi-api-key": API_KEY
    }
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        # Извлекаем ключевые данные
        character_count = data.get("character_count", 0)
        character_limit = data.get("character_limit", 0)
        
        return {
            "character_count": character_count,
            "character_limit": character_limit,
            "remaining": character_limit - character_count,
            "raw_data": data
        }
    except Exception as e:
        print(f"Ошибка при получении usage: {e}")
        return None


async def run_experiment():
    """Основной эксперимент."""
    
    print("=" * 80)
    print("🧪 ЭКСПЕРИМЕНТ: Измерение стоимости транскрибации")
    print("=" * 80)
    print()
    
    # Тестовый файл
    audio_file = "call_79963823017_20250930095628.mp3"
    
    if not os.path.exists(audio_file):
        print(f"❌ Файл не найден: {audio_file}")
        return
    
    print(f"📁 Тестовый файл: {os.path.basename(audio_file)}")
    print()
    
    # ШАГ 1: Получаем баланс ДО
    print("📊 ШАГ 1: Получение баланса ДО транскрибации...")
    usage_before = get_elevenlabs_usage()
    
    if not usage_before:
        print("❌ Не удалось получить баланс. Проверьте API ключ.")
        return
    
    print(f"   • Использовано:  {usage_before['character_count']:,} кредитов")
    print(f"   • Лимит:         {usage_before['character_limit']:,} кредитов")
    print(f"   • Осталось:      {usage_before['remaining']:,} кредитов")
    print()
    
    # Сохраняем полные данные для анализа
    with open("balance_before.json", "w", encoding="utf-8") as f:
        json.dump(usage_before['raw_data'], f, indent=2, ensure_ascii=False)
    print("   💾 Полные данные сохранены в: balance_before.json")
    print()
    
    # ШАГ 2: Транскрибация
    print("🎙️  ШАГ 2: Запуск транскрибации...")
    print("   ⏳ Подождите, это займет около минуты...")
    print()
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    transcription_path = os.path.join(TRANSCRIPTION_DIR, f"test_transcription_{timestamp}.txt")
    
    try:
        await transcribe_and_save(
            call_id=None,
            audio_path=audio_file,
            output_path=transcription_path,
            num_speakers=2,
            diarize=True,
            phone=None,
            manager_name=None,
            client_name=None,
            is_first_contact=False,
            note_data=None
        )
        print("   ✅ Транскрибация завершена!")
        print(f"   📄 Результат: {transcription_path}")
        print()
    except Exception as e:
        print(f"   ❌ Ошибка транскрибации: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Небольшая задержка для обновления баланса в системе ElevenLabs
    print("   ⏳ Ожидание 15 секунд для обновления баланса в ElevenLabs...")
    await asyncio.sleep(15)
    print()
    
    # ШАГ 3: Получаем баланс ПОСЛЕ
    print("📊 ШАГ 3: Получение баланса ПОСЛЕ транскрибации...")
    usage_after = get_elevenlabs_usage()
    
    if not usage_after:
        print("❌ Не удалось получить баланс после транскрибации.")
        return
    
    print(f"   • Использовано:  {usage_after['character_count']:,} кредитов")
    print(f"   • Лимит:         {usage_after['character_limit']:,} кредитов")
    print(f"   • Осталось:      {usage_after['remaining']:,} кредитов")
    print()
    
    # Сохраняем полные данные
    with open("balance_after.json", "w", encoding="utf-8") as f:
        json.dump(usage_after['raw_data'], f, indent=2, ensure_ascii=False)
    print("   💾 Полные данные сохранены в: balance_after.json")
    print()
    
    # ШАГ 4: Анализ результатов
    print("=" * 80)
    print("📈 РЕЗУЛЬТАТЫ ЭКСПЕРИМЕНТА")
    print("=" * 80)
    
    credits_used = usage_after['character_count'] - usage_before['character_count']
    
    print(f"\n✨ СПИСАНО КРЕДИТОВ: {credits_used}")
    print()
    
    # Получаем длительность из debug-файла (последнее слово)
    debug_file = transcription_path + ".debug.json"
    if os.path.exists(debug_file):
        with open(debug_file, 'r', encoding='utf-8') as f:
            debug_data = json.load(f)
            words = debug_data.get('words', [])
            
            # Находим максимальное значение end - это и есть длительность
            if words:
                duration_from_api = max(word.get('end', 0) for word in words)
            else:
                duration_from_api = 0
            
            print(f"📊 АНАЛИЗ:")
            print(f"   • Длительность аудио:  {duration_from_api:.1f} секунд ({duration_from_api/60:.2f} минут)")
            print(f"   • Списано кредитов:    {credits_used}")
            print()
            
            # Используем длительность из API
            actual_duration = duration_from_api
            
            if actual_duration > 0:
                if credits_used > 0:
                    credits_per_second = credits_used / actual_duration
                    credits_per_minute = credits_per_second * 60
                    
                    print(f"📐 ФОРМУЛЫ:")
                    print(f"   • {credits_per_second:.4f} кредитов/секунду")
                    print(f"   • {credits_per_minute:.2f} кредитов/минуту")
                    print()
                    
                    # Расчет для 3000 минут
                    total_for_3000_min = credits_per_minute * 3000
                    print(f"💡 ДЛЯ 3000 МИНУТ:")
                    print(f"   • Потребуется примерно: {total_for_3000_min:,.0f} кредитов")
                    print()
                else:
                    print(f"⚠️  КРЕДИТЫ НЕ СПИСАЛИСЬ!")
                    print(f"   Возможные причины:")
                    print(f"   • ElevenLabs кэширует этот файл (уже транскрибировался ранее)")
                    print(f"   • Задержка обновления статистики (попробуйте проверить через 1-2 минуты)")
                    print(f"   • Попробуйте другой аудиофайл, который точно не транскрибировался")
                    print()
    
    print("=" * 80)
    print("✅ Эксперимент завершен!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_experiment())
