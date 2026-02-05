import os
from dotenv import load_dotenv
# Удаляем import elevenlabs отсюда, будем импортировать его внутри функции
from langchain_openai import ChatOpenAI
from motor.motor_asyncio import AsyncIOMotorClient
from .paths import MONGO_URI, DB_NAME

load_dotenv()

def get_elevenlabs_api_key():
    """Возвращает API-ключ для ElevenLabs."""
    return os.getenv("EVENLABS")

def evenlabs():
    """Возвращает инициализированный клиент ElevenLabs"""
    try:
        from elevenlabs.client import ElevenLabs
        api_key = get_elevenlabs_api_key()
        if not api_key:
            raise ValueError("API-ключ для ElevenLabs не найден.")
        return ElevenLabs(api_key=api_key)

    except (ImportError, ValueError) as e:
        print(f"Warning: Unable to initialize ElevenLabs client: {e}")
        print("Voice synthesis functionality will be unavailable.")
        return None


def get_langchain_token():
    """Возвращает инициализированный клиент LangChain для OpenAI"""
    try:
        return ChatOpenAI(
            # model_name="gpt-4o-mini", temperature=0.3, openai_api_key=os.getenv("OPENAI")
            model_name="gpt-4.1-mini", temperature=0.3, openai_api_key=os.getenv("OPENAI")
        )
    except Exception as e:
        print(f"Warning: Unable to initialize ChatOpenAI: {e}")
        return None


def get_mongodb():
    """Возвращает клиент MongoDB с использованием настроек из переменных окружения или значений по умолчанию"""
    uri = os.getenv("MONGO_URI", MONGO_URI)
    return AsyncIOMotorClient(uri)


# Функция для получения соединения с базой данных и коллекцией
def get_db_collection(collection_name):
    """
    Возвращает объект коллекции MongoDB

    Args:
        collection_name: Имя коллекции

    Returns:
        Объект коллекции MongoDB
    """
    client = get_mongodb()
    db = client[DB_NAME]
    return db[collection_name]

