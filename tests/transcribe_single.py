#!/usr/bin/env python3
"""
Скрипт для транскрипции одного аудиофайла с помощью ElevenLabs API
"""

import asyncio
import os
import sys
import shutil
from pathlib import Path
from datetime import datetime

# Добавляем корневую директорию проекта в путь для импорта
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

# Используем тот же API ключ, что и в eleven2.py
API_KEY = "sk_496a68bf0f91cde4c3069e39c9dc9b8b54339285daf412f5"

from app.services.transcription_service import transcribe_and_save
from app.settings import AUDIO_DIR, TRANSCRIPTION_DIR


async def transcribe_single_file(audio_file_path: str, num_speakers: int = 2):
    """
    Транскрибирует один аудиофайл

    Args:
        audio_file_path: Путь к аудиофайлу
        num_speakers: Количество говорящих в файле
    """
    try:
        # Проверяем, существует ли файл
        if not os.path.exists(audio_file_path):
            print(f"Ошибка: Файл {audio_file_path} не найден")
            return False

        # Создаем директории, если они не существуют
        os.makedirs(AUDIO_DIR, exist_ok=True)
        os.makedirs(TRANSCRIPTION_DIR, exist_ok=True)

        # Копируем файл в AUDIO_DIR, если он еще не там
        file_name = os.path.basename(audio_file_path)
        dest_path = os.path.join(AUDIO_DIR, file_name)

        if audio_file_path != dest_path:
            shutil.copy2(audio_file_path, dest_path)
            print(f"Файл скопирован в {dest_path}")

        # Генерируем имя для файла транскрипции
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        transcription_filename = f"transcription_{file_name}_{timestamp}.txt"
        transcription_path = os.path.join(TRANSCRIPTION_DIR, transcription_filename)

        print("Начинаем транскрипцию...")
        # Вызываем функцию транскрипции
        await transcribe_and_save(
            call_id=None,
            audio_path=dest_path,
            output_path=transcription_path,
            num_speakers=num_speakers,
            diarize=True,
            phone=None,
            manager_name=None,
            client_name=None,
            is_first_contact=False,
            note_data=None
        )

        print(f"Транскрипция завершена! Результат сохранен в: {transcription_path}")
        return True

    except Exception as e:
        print(f"Ошибка при транскрипции: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    # Путь к файлу для транскрипции
    audio_file = "/Users/mpr0/Development/[Sandbox]/medai_final/medai_backend/app/data/audio/lead_45209989_note_273360871.mp3"

    # Количество говорящих (обычно 2 для звонков)
    num_speakers = 2

    # Запускаем транскрипцию
    success = asyncio.run(transcribe_single_file(audio_file, num_speakers))

    if success:
        print("\nТранскрипция успешно выполнена!")
    else:
        print("\nТранскрипция завершилась с ошибкой!")
        sys.exit(1)
