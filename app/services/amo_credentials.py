from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
from typing import Dict, Any
import os
from dotenv import load_dotenv
import traceback

load_dotenv()

# Получаем URL для подключения к MongoDB из переменных окружения
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_NAME = os.getenv("MONGODB_NAME", "medai")

print(f"Подключение к MongoDB: {MONGODB_URI}, база данных: {MONGODB_NAME}")

try:
    # Создаем клиент MongoDB
    mongo_client = AsyncIOMotorClient(MONGODB_URI)
    db = mongo_client[MONGODB_NAME]
    print("Подключение к MongoDB успешно установлено")
except Exception as e:
    print(f"Ошибка подключения к MongoDB: {e}")
    traceback.print_exc()

async def get_amo_credentials() -> Dict[str, Any]:
    """
    Получает актуальные данные для авторизации в amoCRM из MongoDB.
    """
    try:
        print("Запрос токенов из коллекции tokens...")
        # Получаем самый актуальный токен
        token_data = await db.tokens.find_one(
            sort=[("updated_at", -1)]  # Сортировка по дате обновления (самый новый)
        )
        
        if not token_data:
            raise ValueError("Токены amoCRM не найдены в базе данных")
        
        print(f"Найден токен: client_id={token_data.get('client_id')}, subdomain={token_data.get('subdomain')}")
        
        return {
            "client_id": token_data.get("client_id", ""),
            "access_token": token_data.get("access_token", ""),
            "refresh_token": token_data.get("refresh_token", ""),
            "subdomain": token_data.get("subdomain", ""),
            "updated_at": token_data.get("updated_at")
        }
    except Exception as e:
        print(f"Ошибка при получении токенов: {e}")
        traceback.print_exc()
        raise

async def get_amo_clinic_details(client_id: str = None, subdomain: str = None) -> Dict[str, str]:
    """
    Получает client_secret и redirect_url из коллекции clinics.
    """
    try:
        query = {}
        if client_id:
            query["client_id"] = client_id
            print(f"Поиск клиники по client_id: {client_id}")
        elif subdomain:
            query["amocrm_subdomain"] = subdomain
            print(f"Поиск клиники по subdomain: {subdomain}")
        else:
            # Если параметры не указаны, получаем их из tokens
            print("Параметры не указаны, получаем их из tokens")
            token_data = await get_amo_credentials()
            if token_data["client_id"]:
                query["client_id"] = token_data["client_id"]
                print(f"Используем client_id из токена: {token_data['client_id']}")
            elif token_data["subdomain"]:
                query["amocrm_subdomain"] = token_data["subdomain"]
                print(f"Используем subdomain из токена: {token_data['subdomain']}")
        
        print(f"Запрос данных клиники с параметрами: {query}")
        clinic_data = await db.clinics.find_one(query)
        
        if not clinic_data:
            raise ValueError(f"Данные клиники не найдены в базе данных для запроса: {query}")
        
        print(f"Найдены данные клиники: {clinic_data.get('name', 'Без имени')}")
        
        return {
            "client_secret": clinic_data.get("client_secret", ""),
            "redirect_url": clinic_data.get("redirect_url", "")
        }
    except Exception as e:
        print(f"Ошибка при получении данных клиники: {e}")
        traceback.print_exc()
        raise

async def get_full_amo_credentials(client_id: str = None) -> Dict[str, Any]:
    """
    Получает полный набор данных для авторизации в amoCRM.
    """
    try:
        if client_id:
            print(f"Получение полных данных по client_id: {client_id}")
            # Получаем детали клиники по client_id
            clinic_data = await get_amo_clinic_details(client_id=client_id)
            
            # Ищем токены для этого client_id
            print(f"Поиск токенов для client_id: {client_id}")
            token_data = await db.tokens.find_one(
                {"client_id": client_id},
                sort=[("updated_at", -1)]
            )
            
            if not token_data:
                raise ValueError(f"Токены для client_id {client_id} не найдены в базе данных")
            
            print(f"Найдены токены для client_id: {client_id}")
            
            return {
                "client_id": token_data.get("client_id", ""),
                "access_token": token_data.get("access_token", ""),
                "refresh_token": token_data.get("refresh_token", ""),
                "subdomain": token_data.get("subdomain", ""),
                "updated_at": token_data.get("updated_at"),
                **clinic_data
            }
        else:
            print("Получение полных данных по последнему токену")
            # Стандартное поведение - получаем самый свежий токен
            token_data = await get_amo_credentials()
            
            # Получаем детали клиники
            print(f"Получение данных клиники для client_id: {token_data['client_id']}")
            clinic_data = await get_amo_clinic_details(client_id=token_data["client_id"])
            
            # Объединяем данные
            return {
                **token_data,
                **clinic_data
            }
    except Exception as e:
        print(f"Ошибка при получении полных данных авторизации: {e}")
        traceback.print_exc()
        raise

async def update_amo_tokens(access_token: str, refresh_token: str) -> None:
    """
    Обновляет токены amoCRM в базе данных.
    """
    try:
        print("Поиск последней записи токенов для обновления")
        # Находим самую последнюю запись
        token_data = await db.tokens.find_one(
            sort=[("updated_at", -1)]
        )
        
        if not token_data:
            raise ValueError("Токены amoCRM не найдены в базе данных")
        
        print(f"Обновление токенов для записи с ID: {token_data['_id']}")
        
        # Обновляем токены
        await db.tokens.update_one(
            {"_id": token_data["_id"]},
            {
                "$set": {
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "updated_at": datetime.now(datetime.timezone.utc)
                }
            }
        )
        print("Токены успешно обновлены")
    except Exception as e:
        print(f"Ошибка при обновлении токенов: {e}")
        traceback.print_exc()
        raise