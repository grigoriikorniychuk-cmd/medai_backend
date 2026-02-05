import os
import requests
import json
import socket
import socks  # Для работы с SOCKS
from dotenv import load_dotenv
from app.settings.auth import evenlabs

# Загружаем переменные окружения из .env
load_dotenv()

# ===== НАСТРОЙКИ ПРОКСИ =====
# Выберите тип прокси (http/socks5)
PROXY_TYPE = 'socks5'  # 'http' или 'socks5'

# Настройки прокси
PROXY_HOST = '166.88.9.236'
PROXY_PORT = 62127
PROXY_USER = 'nraNmsdP'
PROXY_PASS = '5TFRSPJz'

# Формируем настройки прокси в зависимости от типа
if PROXY_TYPE == 'socks5':
    # Для SOCKS5
    socks.set_default_proxy(
        socks.SOCKS5,
        PROXY_HOST,
        PROXY_PORT,
        True,  # Использовать аутентификацию
        PROXY_USER,
        PROXY_PASS
    )
    
    # Подменяем сокеты по умолчанию на сокеты через прокси
    socket.socket = socks.socksocket
    
    # Для requests
    PROXIES = {}
    PROXY_URL = f"socks5://{PROXY_USER}:{PROXY_PASS}@{PROXY_HOST}:{PROXY_PORT}"
    print(f"Используем SOCKS5 прокси: {PROXY_URL}")
else:
    # Для HTTP/HTTPS прокси
    PROXY_URL = f"http://{PROXY_USER}:{PROXY_PASS}@{PROXY_HOST}:{PROXY_PORT}"
    PROXIES = {
        'http': PROXY_URL,
        'https': PROXY_URL
    }
    print(f"Используем HTTP прокси: {PROXY_URL}")

def check_proxy_connection():
    """Проверяем работу прокси через сервис определения IP"""
    test_urls = [
        'https://api.ipify.org?format=json',
        'http://ip-api.com/json/'
    ]
    
    session = requests.Session()
    session.proxies = PROXIES
    
    print(f"Проверяем подключение через прокси: {PROXY_HOST}:{PROXY_PORT}")
    
    for url in test_urls:
        try:
            print(f"\nПопытка подключения к {url}")
            response = session.get(url, timeout=10)
            response.raise_for_status()
            
            print(f"✅ Успешное подключение через прокси!")
            print("Ответ сервера:")
            print(json.dumps(response.json(), indent=2, ensure_ascii=False))
            return True
            
        except requests.exceptions.RequestException as e:
            print(f"❌ Ошибка при подключении к {url}:")
            print(f"   {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"   Код состояния: {e.response.status_code}")
                print(f"   Ответ сервера: {e.response.text}")
        except Exception as e:
            print(f"❌ Неожиданная ошибка: {str(e)}")
    
    print("\n⚠️ Не удалось подключиться ни к одному из сервисов проверки IP")
    return False

def check_elevenlabs_credits():
    """Проверяем оставшиеся кредиты в ElevenLabs"""
    try:
        # Инициализируем клиент ElevenLabs
        client = evenlabs()
        if client is None:
            print("❌ Ошибка: Не удалось инициализировать клиент ElevenLabs")
            return False
            
        print("\n=== ElevenLabs User Information ===")
        
        # Получаем информацию о пользователе
        try:
            user_info = client.user.get()
            print(f"User ID: {user_info.subscription.tier}")
            print(f"Subscription: {user_info.subscription.tier}")
            print(f"Character Count: {user_info.subscription.character_count}")
            print(f"Character Limit: {user_info.subscription.character_limit}")
            print(f"Next Character Reset: {user_info.subscription.next_character_count_reset_unix}")
            print("=" * 30)
            return True
        except Exception as e:
            print(f"❌ Ошибка при получении информации о пользователе: {str(e)}")
            
        # Пробуем получить информацию о подписке
        try:
            subscription = client.user.subscription.get()
            print("\n=== Subscription Details ===")
            print(f"Status: {subscription.status}")
            print(f"Tier: {subscription.tier}")
            print(f"Character Count: {subscription.character_count}")
            print(f"Character Limit: {subscription.character_limit}")
            print("=" * 30)
            return True
        except Exception as e:
            print(f"❌ Ошибка при получении информации о подписке: {str(e)}")
            
        # Пробуем получить информацию об использовании
        try:
            usage = client.usage.get()
            print("\n=== Usage Information ===")
            print(f"Character Count: {usage.character_count}")
            print(f"Character Limit: {usage.character_limit}")
            print(f"Next Reset: {usage.next_reset_date}")
            print("=" * 30)
            return True
        except Exception as e:
            print(f"❌ Ошибка при получении информации об использовании: {str(e)}")
            
        return False
            
    except Exception as e:
        print(f"❌ Произошла ошибка: {str(e)}")
        return False

def test_elevenlabs_connection():
    """Тестируем подключение к ElevenLabs API через прокси"""
    try:
        # Получаем клиент ElevenLabs
        client = evenlabs()
        if client is None:
            print("❌ Ошибка: Не удалось инициализировать клиент ElevenLabs")
            return False
        
        # Устанавливаем сессию с прокси
        session = requests.Session()
        if PROXIES:
            session.proxies = PROXIES
        
        # Тестируем запрос к API
        print("Пытаемся подключиться к ElevenLabs API через прокси...")
        
        # Получаем список голосов
        response = session.get(
            "https://api.elevenlabs.io/v1/voices",
            headers={"xi-api-key": os.getenv("EVENLABS")},
            timeout=10
        )
        
        if response.status_code == 200:
            voices = response.json().get('voices', [])
            print(f"✅ Успешное подключение! Доступно голосов: {len(voices)}")
            return True
        else:
            print(f"❌ Ошибка подключения (код {response.status_code}): {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Произошла ошибка: {str(e)}")
        return False

def transcribe_audio(file_path):
    """Отправляет аудиофайл на транскрипцию через SDK ElevenLabs, используя evenlabs() для инициализации клиента."""
    client = None # Для корректной работы evenlabs(), если она может вернуть None
    try:
        print(f"\n=== Тестирование транскрипции файла: {file_path} через SDK ElevenLabs ===")
        
        # Инициализируем клиент ElevenLabs через нашу функцию (которая должна учитывать прокси)
        client = evenlabs() 
        if not client:
            print("❌ Ошибка: Не удалось инициализировать клиент ElevenLabs через evenlabs()")
            return None

        # Проверяем существование файла перед открытием
        if not os.path.exists(file_path):
            print(f"❌ Ошибка: Аудиофайл не найден по пути {file_path}")
            return None

        # Параметры для транскрибации
        model_id = "scribe_v1"  # 'scribe_v1' или 'eleven_multilingual_v2'
        diarize = True          # Установите True, если нужна диаризация
        num_speakers = 2       # Укажите, если diarize=True
        language = "ru"      # Для eleven_multilingual_v2 можно указать язык исходного аудио, если отличается от автодетекта

        print(f"Используемая модель: {model_id}, Диализация: {diarize}")

        with open(file_path, "rb") as audio_file_object:
            response_sdk = client.speech_to_text.convert(
                file=audio_file_object,
                model_id=model_id,
                diarize=diarize,
                num_speakers=num_speakers, # Передавать, если diarize=True
                # language=language # если модель поддерживает и нужно указать
            )
        
        # Объект response_sdk будет типа elevenlabs.types.SpeechToTextResponse
        # Текстовое содержимое находится в response_sdk.text
        print("✅ Транскрипция успешно получена через SDK:")
        transcribed_text = response_sdk.text
        print(f"Транскрибированный текст: {transcribed_text}")

        # Сохраняем полный ответ SDK в файл для отладки (если нужно)
        # Это будет объект Pydantic, можно преобразовать в dict
        debug_file_sdk = file_path + ".transcription_sdk.json"
        try:
            with open(debug_file_sdk, 'w', encoding='utf-8') as f:
                # response_sdk может быть объектом Pydantic, используем .model_dump_json() или .dict()
                if hasattr(response_sdk, 'model_dump_json'):
                    f.write(response_sdk.model_dump_json(indent=2))
                elif hasattr(response_sdk, 'dict'): # Для более старых версий Pydantic или совместимых объектов
                    json.dump(response_sdk.dict(), f, ensure_ascii=False, indent=2)
                else:
                    f.write(str(response_sdk)) # Как крайний случай
            print(f"Полный ответ SDK сохранен в: {debug_file_sdk}")
        except Exception as e_dump:
            print(f"⚠️ Не удалось сохранить полный ответ SDK в JSON: {e_dump}")
            print(f"Ответ SDK (строковое представление): {str(response_sdk)}")

        # Пример дополнительной информации из ответа, если она есть и нужна
        # if response_sdk.words:
        # print(f"\nРаспознано {len(response_sdk.words)} слов (если модель вернула слова)")
        # if response_sdk.words and response_sdk.words[0].speaker is not None:
        # print(f"Первый говорящий: {response_sdk.words[0].speaker}")
        
        return response_sdk # Возвращаем весь объект ответа SDK

    except AttributeError as e_attr:
        print(f"❌ Ошибка атрибута при вызове SDK ElevenLabs: {e_attr}")
        print("   Возможно, объект client, возвращенный evenlabs(), не имеет метода 'speech_to_text.convert'.")
        print("   Проверьте реализацию evenlabs() и версию SDK.")
    except Exception as e:
        print(f"❌ Непредвиденная ошибка при транскрибации через SDK: {str(e)}")
        # В случае ошибок от API ElevenLabs, они обычно являются подклассами APIError
        # из elevenlabs.core.api_error - можно добавить более специфичную обработку
        import traceback
        traceback.print_exc()
        
    return None # В случае ошибки

if __name__ == "__main__":
    print(f"Используем прокси: {PROXY_URL}")
    
    # Сначала проверяем работу прокси
    if check_proxy_connection():
        # Если прокси работает, проверяем доступность ElevenLabs
        print("\n" + "="*50)
        print("Проверяем доступность ElevenLabs...")
        if test_elevenlabs_connection():
            # Если подключение успешно, проверяем кредиты
            print("\n" + "="*50)
            check_elevenlabs_credits()
            
            # Тестируем транскрипцию
            audio_file = "app/data/audio/lead_45190901_note_273263115.mp3"
            transcribe_audio(audio_file)
    else:
        print("\n⚠️ Пожалуйста, проверьте настройки прокси и повторите попытку.")
        print("Убедитесь, что:")
        print("1. Прокси-сервер доступен")
        print("2. Указаны правильные учетные данные")
        print("3. Прокси поддерживает HTTPS соединения (если требуется)")
