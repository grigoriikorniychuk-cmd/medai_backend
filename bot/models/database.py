import motor.motor_asyncio
from datetime import datetime
from bot.config.config import MONGO_URI, DB_NAME

# Инициализация MongoDB клиента
client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
db = client[DB_NAME]

# Коллекции
tokens_collection = db["tokens"]
clinics_collection = db["clinics"]
transcriptions_collection = db["transcription"]
administrators_collection = db["administrators"]

# Функции для работы с базой данных клиник
async def get_clinic_by_client_id(client_id: str):
    """Получить клинику по client_id"""
    return await clinics_collection.find_one({"client_id": client_id})

async def get_clinics_by_user_id(user_id: int):
    """Получить все клиники пользователя"""
    return await clinics_collection.find({"telegram_ids": user_id}).to_list(length=100)

async def add_user_to_clinic(client_id: str, user_id: int):
    """Привязать пользователя к клинике"""
    return await clinics_collection.update_one(
        {"client_id": client_id},
        {"$addToSet": {"telegram_ids": user_id}}
    )

async def create_clinic(clinic_data: dict):
    """Создать новую клинику"""
    return await clinics_collection.insert_one(clinic_data)

async def create_clinic_with_user(clinic_data: dict, user_id: int):
    """Создать новую клинику и сразу добавить user_id в telegram_ids"""
    clinic_data = dict(clinic_data)
    clinic_data["telegram_ids"] = [user_id]
    return await clinics_collection.insert_one(clinic_data)

# Функции для работы с транскрибациями
async def get_transcription(call_id: str):
    """Получить транскрибацию по ID звонка"""
    return await transcriptions_collection.find_one({"call_id": call_id})

async def save_transcription(call_id: str, client_id: str, filename: str):
    """Сохранить информацию о транскрибации"""
    return await transcriptions_collection.update_one(
        {"call_id": call_id},
        {"$set": {
            "call_id": call_id,
            "client_id": client_id,
            "filename": filename,
            "created_at": datetime.now()
        }},
        upsert=True
    )

# Функции для работы с токенами
async def get_tokens_for_clients(client_ids: list):
    """Получить токены для списка client_id"""
    return await tokens_collection.find({"client_id": {"$in": client_ids}}).to_list(length=100)

# Создание индексов MongoDB при запуске
async def create_indexes():
    """Создает необходимые индексы в MongoDB"""
    await clinics_collection.create_index("client_id")
    await clinics_collection.create_index("telegram_ids")
    await tokens_collection.create_index("client_id") 