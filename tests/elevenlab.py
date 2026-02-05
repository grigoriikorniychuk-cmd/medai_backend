import os
import httpx
import socket  # Для глобальной настройки SOCKS
import socks   # Для глобальной настройки SOCKS
from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs
import traceback

# Загрузка переменных окружения из .env файла
load_dotenv()

def main():
    # Настройки прокси (берутся из .env)
    proxy_type = os.getenv("PROXY_TYPE", "socks5").lower()
    proxy_host = os.getenv("PROXY_HOST")
    proxy_port_str = os.getenv("PROXY_PORT")
    proxy_user = os.getenv("PROXY_USER")
    proxy_pass = os.getenv("PROXY_PASS")

    custom_httpx_client = None

    if proxy_host and proxy_port_str:
        try:
            proxy_port = int(proxy_port_str)
        except ValueError:
            print(f"Ошибка: PROXY_PORT ('{proxy_port_str}') не является числом.")
            return

        proxy_auth_str = f"{proxy_user}:{proxy_pass}@" if proxy_user and proxy_pass else ""
        
        # Глобальная настройка SOCKS5 прокси (может быть полезна для других библиотек, но httpx требует явной настройки)
        if proxy_type == 'socks5':
            print(f"Попытка глобальной настройки SOCKS5 прокси: {proxy_host}:{proxy_port} (для информации, httpx ее не использует по умолчанию)")
            try:
                socks.set_default_proxy(
                    socks.SOCKS5,
                    proxy_host,
                    proxy_port,
                    username=proxy_user if proxy_user else None,
                    password=proxy_pass if proxy_pass else None
                )
                socket.socket = socks.socksocket
                print("Глобальный SOCKS5 прокси настроен (но httpx требует явной передачи).")
            except Exception as e_socks_global:
                print(f"Ошибка при глобальной настройке SOCKS5: {e_socks_global}")
                # Не прерываем, так как основная логика для httpx ниже

        # Явная настройка httpx.Client для ElevenLabs SDK
        full_proxy_url = f"{proxy_type}://{proxy_auth_str}{proxy_host}:{proxy_port}"
        
        proxies_for_httpx = {
            "all://": full_proxy_url # Основной ключ для httpx >= 0.26.0
        }
        print(f"Настройка httpx.Client с прокси: {full_proxy_url} используя proxies_for_httpx: {proxies_for_httpx}")
        print(f"Тип httpx.Client перед созданием экземпляра: {type(httpx.Client)}")
        try:
            custom_httpx_client = httpx.Client(proxies=proxies_for_httpx, timeout=60.0)
            print("httpx.Client успешно создан с настройками прокси.")
        except Exception as e_httpx_create:
            print(f"Ошибка при создании httpx.Client с прокси: {e_httpx_create}")
            # Если не удалось создать клиент с прокси, SDK будет пытаться идти напрямую или упадет.
            # Для чистоты эксперимента, если клиент не создан, не будем продолжать.
            return
    else:
        print("Прокси не настроен (PROXY_HOST или PROXY_PORT не указаны в .env), запрос пойдет напрямую.")
        # custom_httpx_client останется None, SDK создаст свой клиент по умолчанию

    audio_path = "app/data/audio/lead_45187755_note_272274329.mp3"
    if not os.path.exists(audio_path):
        print(f"Ошибка: Аудиофайл не найден: {audio_path}")
        return

    try:
        api_key = os.getenv("EVENLABS")
        if not api_key:
            print("Ошибка: API ключ EVENLABS не найден в .env.")
            return

        print("Инициализация клиента ElevenLabs с кастомным httpx_client (если настроен)...")
        client = ElevenLabs(
            api_key=api_key,
            httpx_client=custom_httpx_client # Передаем наш настроенный или None
        )

        print(f"Отправка файла {audio_path} на транскрибацию...")
        with open(audio_path, "rb") as audio_file_obj:
            response = client.speech_to_text.convert(
                file=audio_file_obj,
                model_id="scribe_v1",
                # diarize=True, # Опционально
                # num_speakers=2 # Опционально
            )
        
        print("\nТранскрибация успешна!")
        print("--- Текст ---")
        print(response.text)
        print("---------------")

    except httpx.ProxyError as e_proxy:
        print(f"\n❌ Ошибка ПРОКСИ при запросе к ElevenLabs (через httpx): {e_proxy}")
        print(f"   URL запроса: {e_proxy.request.url if e_proxy.request else 'N/A'}")
        print("   Это может быть проблема с доступностью прокси-сервера или его конфигурацией для данного типа запроса.")
        traceback.print_exc()
    except httpx.HTTPStatusError as e_http:
        print(f"\n❌ Ошибка HTTP от ElevenLabs API (через httpx): {e_http}")
        print(f"   Статус код: {e_http.response.status_code}")
        print(f"   Ответ: {e_http.response.text}")
        traceback.print_exc()
    except Exception as e_main:
        print(f"\n❌ Произошла непредвиденная ошибка: {e_main}")
        traceback.print_exc()

if __name__ == "__main__":
    main()
