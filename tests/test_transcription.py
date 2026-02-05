import os
# import asyncio # Больше не используется, функция стала синхронной
import logging
from dotenv import load_dotenv
from pprint import pprint

# Импортируем функцию evenlabs из нашего приложения
from app.settings.auth import evenlabs

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения из .env файла
load_dotenv()

def test_transcription():  # Изменено на синхронную функцию
    """Тестирование транскрибации аудио через прокси с использованием SDK ElevenLabs"""
    client = None  # Инициализируем client для использования в finally
    try:
        # Получаем клиент ElevenLabs с настройками прокси из auth.py
        client = evenlabs()
        if not client:
            logger.error("Не удалось инициализировать клиент ElevenLabs")
            return
            
        # Путь к аудиофайлу
        audio_file_path = "app/data/audio/lead_45187755_note_272274329.mp3"
        
        # Проверяем существование файла
        if not os.path.exists(audio_file_path):
            logger.error(f"Файл не найден: {audio_file_path}")
            return
            
        logger.info(f"Начинаем транскрибацию файла: {audio_file_path} с использованием SDK ElevenLabs")
        
        # Параметры для транскрибации
        model_id = "scribe_v1"  # Используем модель scribe_v1 или eleven_multilingual_v2
        diarize = False         # Установите True, если нужна диаризация (разделение по спикерам)
        # num_speakers = 2      # Укажите, если diarize=True и известно количество спикеров

        try:
            with open(audio_file_path, "rb") as audio_file_object:
                response = client.speech_to_text.convert(
                    file=audio_file_object,
                    model_id=model_id,
                    diarize=diarize
                    # num_speakers=num_speakers # Передавать, если diarize=True
                )
            
            # Объект response будет типа elevenlabs.types.SpeechToTextResponse
            # Его текстовое содержимое находится в response.text
            logger.info("Транскрибация успешна.")
            logger.info(f"Полученный текст: {response.text}")
            
            # Если нужна более подробная информация из ответа:
            # logger.info("Полный ответ от API:")
            # pprint(response.dict()) # Использует импортированный pprint

        except Exception as e:
            # Здесь могут быть ошибки API ElevenLabs или другие исключения
            logger.error(f"Ошибка во время вызова client.speech_to_text.convert: {e}", exc_info=True)
            
    except Exception as e:
        logger.error(f"Общая ошибка в функции test_transcription: {e}", exc_info=True)
    finally:
        # Логика закрытия HTTP-клиента, если это необходимо для вашей реализации evenlabs()
        if client and hasattr(client, '_client') and client._client: # Проверяем, что _client не None
            try:
                if hasattr(client._client, 'is_closed'): # Современный httpx клиент
                    if not client._client.is_closed:
                        logger.info("Закрытие HTTP клиента ElevenLabs...")
                        client._client.close()
                        logger.info("HTTP клиент ElevenLabs успешно закрыт.")
                    else:
                        logger.info("HTTP клиент ElevenLabs уже был закрыт.")
                elif hasattr(client._client, 'close'): # Для обратной совместимости или других реализаций клиента
                     logger.info("Закрытие HTTP клиента ElevenLabs (без проверки is_closed)...")
                     client._client.close()
                     logger.info("HTTP клиент ElevenLabs закрыт (без проверки is_closed).")
            except Exception as e_close:
                logger.error(f"Ошибка при закрытии HTTP клиента: {e_close}", exc_info=True)

if __name__ == "__main__":
    test_transcription()  # Вызов синхронной функции
