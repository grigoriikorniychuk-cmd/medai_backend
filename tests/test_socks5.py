import aiohttp
import ssl
from aiohttp_socks import ProxyType, ProxyConnector
import os
from dotenv import load_dotenv
import httpx
from elevenlabs.client import AsyncElevenLabs
import traceback

# Загрузка переменных окружения из .env файла
load_dotenv()

# Настройки прокси и API ключа из .env
PROXY_HOST = os.getenv("PROXY_HOST")
PROXY_PORT_STR = os.getenv("PROXY_PORT")
PROXY_USER = os.getenv("PROXY_USER")
PROXY_PASS = os.getenv("PROXY_PASS")
ELEVENLABS_API_KEY = os.getenv("EVENLABS") # Используем EVENLABS как было в elevenlab.py

AUDIO_FILE_PATH = "app/data/audio/lead_45187755_note_272274329.mp3" # Путь к твоему аудиофайлу

async def check_ip_via_aiohttp():
    """Проверяет IP через aiohttp с SOCKS5 прокси и отключенным SSL verify."""
    if not all([PROXY_HOST, PROXY_PORT_STR]):
        print("AIOHTTP: Прокси не настроен (PROXY_HOST или PROXY_PORT не указаны).")
        return None
    try:
        proxy_port = int(PROXY_PORT_STR)
    except ValueError:
        print(f"AIOHTTP: Ошибка: PROXY_PORT ('{PROXY_PORT_STR}') не является числом.")
        return None

    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    connector = ProxyConnector(
        proxy_type=ProxyType.SOCKS5,
        host=PROXY_HOST,
        port=proxy_port,
        username=PROXY_USER,
        password=PROXY_PASS,
        rdns=True,
        ssl=ssl_context
    )
    try:
        async with aiohttp.ClientSession(connector=connector) as session:
            print("AIOHTTP: Запрос на https://httpbin.org/ip через прокси...")
            async with session.get('https://httpbin.org/ip') as response:
                response_text = await response.text()
                print(f"AIOHTTP: IP check response: {response_text.strip()}")
                return response_text
    except Exception as e:
        print(f"AIOHTTP: Ошибка при проверке IP: {e}")
        traceback.print_exc()
        return None

async def transcribe_audio_elevenlabs():
    """Транскрибирует аудио через ElevenLabs SDK с httpx.AsyncClient, SOCKS5 прокси и SSL bypass."""
    if not ELEVENLABS_API_KEY:
        print("ElevenLabs: API ключ EVENLABS не найден в .env.")
        return

    custom_httpx_async_client = None
    if all([PROXY_HOST, PROXY_PORT_STR]):
        try:
            proxy_port = int(PROXY_PORT_STR)
            proxy_url_httpx = f"socks5://{PROXY_USER}:{PROXY_PASS}@{PROXY_HOST}:{proxy_port}" if PROXY_USER and PROXY_PASS else f"socks5://{PROXY_HOST}:{proxy_port}"
            
            print(f"ElevenLabs: Настройка httpx.AsyncClient с прокси: {proxy_url_httpx}")
            # Для httpx отключение проверки SSL проще через verify=False
            custom_httpx_async_client = httpx.AsyncClient(
                proxies={"all://": proxy_url_httpx},
                verify=False, 
                timeout=60.0
            )
            print("ElevenLabs: httpx.AsyncClient успешно создан.")
        except ValueError:
            print(f"ElevenLabs: Ошибка: PROXY_PORT ('{PROXY_PORT_STR}') не является числом. Прокси для httpx не будет использован.")
        except Exception as e_httpx_create:
            print(f"ElevenLabs: Ошибка при создании httpx.AsyncClient с прокси: {e_httpx_create}. Прокси не будет использован.")
            traceback.print_exc()
            custom_httpx_async_client = None # Сбрасываем, если создание не удалось
    else:
        print("ElevenLabs: Прокси не настроен (PROXY_HOST или PROXY_PORT не указаны), запрос пойдет напрямую (если custom_httpx_async_client не был создан).")

    eleven_client = AsyncElevenLabs(
        api_key=ELEVENLABS_API_KEY,
        httpx_client=custom_httpx_async_client  # Передаем наш настроенный клиент или None
    )

    try:
        if not os.path.exists(AUDIO_FILE_PATH):
            print(f"ElevenLabs: Аудиофайл не найден: {AUDIO_FILE_PATH}")
            return

        print(f"ElevenLabs: Отправка файла {AUDIO_FILE_PATH} на транскрибацию...")
        with open(AUDIO_FILE_PATH, "rb") as audio_file_obj:
            response = await eleven_client.speech_to_text.convert(
                file=audio_file_obj,
                model_id="eleven_multilingual_v2" # Убедись, что модель верная, или убери для автодетекта
            )
        print("\nElevenLabs: Транскрибация успешна!")
        print("--- Текст от ElevenLabs ---")
        print(response.text)
        print("---------------------------")

    except httpx.ProxyError as e_proxy:
        print(f"\nElevenLabs: ❌ Ошибка ПРОКСИ (httpx): {e_proxy}")
        if e_proxy.request:
            print(f"   URL запроса: {e_proxy.request.url}")
        traceback.print_exc()
    except httpx.HTTPStatusError as e_http:
        print(f"\nElevenLabs: ❌ Ошибка HTTP от API (httpx): {e_http.response.status_code}")
        print(f"   Ответ: {e_http.response.text}")
        traceback.print_exc()
    except Exception as e_main:
        print(f"\nElevenLabs: ❌ Непредвиденная ошибка: {e_main}")
        traceback.print_exc()
    finally:
        # Закрываем AsyncElevenLabs клиент (он закроет переданный httpx_client, если он был создан SDK)
        # Если мы передали свой httpx_client, хорошей практикой будет закрыть его явно,
        # но AsyncElevenLabs().aclose() должен это сделать.
        print("ElevenLabs: Закрытие клиента...")
        await eleven_client.aclose()
        if custom_httpx_async_client is not None and not custom_httpx_async_client.is_closed:
             # Убедимся, что наш клиент точно закрыт, если мы его создавали
            await custom_httpx_async_client.aclose()
        print("ElevenLabs: Клиент закрыт.")

if __name__ == '__main__':
    import asyncio
    print("--- Запуск проверки IP через aiohttp ---")
    asyncio.run(check_ip_via_aiohttp())
    print("\n--- Запуск транскрибации через ElevenLabs (httpx) ---")
    asyncio.run(transcribe_audio_elevenlabs())