from motor.motor_asyncio import AsyncIOMotorClient
from bson.objectid import ObjectId
from datetime import datetime
import logging
from typing import List, Dict, Any, Optional

from mlab_amo_async.amocrm_client import AsyncAmoCRMClient
from bot.config.config import MONGO_URI, DB_NAME


logger = logging.getLogger(__name__)


class ClinicService:
    def __init__(self):
        self.client = AsyncIOMotorClient(MONGO_URI)
        self.db = self.client[DB_NAME]

    async def register_clinic(self, clinic_data):
        """
        Регистрирует новую клинику и создает администраторов из AmoCRM.
        Предотвращает создание дубликатов по client_id.
        """
        try:
            # Логируем входные данные
            logger.info(
                f"Начинаем регистрацию клиники: {clinic_data.get('name', 'Unknown')}"
            )

            # Проверяем, существует ли уже клиника с таким client_id
            existing_clinic = await self.db.clinics.find_one(
                {"client_id": clinic_data["client_id"]}
            )

            now = datetime.now().isoformat()

            if existing_clinic:
                # Клиника уже существует - обновляем её данные
                clinic_id = (
                    str(existing_clinic["_id"])
                    if not isinstance(existing_clinic["_id"], str)
                    else existing_clinic["_id"]
                )
                logger.info(
                    f"Клиника с client_id {clinic_data['client_id']} уже существует (ID: {clinic_id})"
                )

                # Обновляем данные клиники
                await self.db.clinics.update_one(
                    {"client_id": clinic_data["client_id"]},
                    {
                        "$set": {
                            "name": clinic_data["name"],
                            "amocrm_subdomain": clinic_data["amocrm_subdomain"],
                            "client_secret": clinic_data["client_secret"],
                            "redirect_url": clinic_data["redirect_url"],
                            "amocrm_pipeline_id": clinic_data.get("amocrm_pipeline_id"),
                            "monthly_limit": clinic_data.get("monthly_limit", 100),
                            "updated_at": now,
                        }
                    },
                )
                logger.info(f"Данные клиники {clinic_id} обновлены")
            else:
                # Новая клиника - создаем
                # Генерируем UUID для id
                import uuid

                clinic_doc = {
                    "_id": str(uuid.uuid4()),  # Используем UUID как строковый _id
                    "name": clinic_data["name"],
                    "amocrm_subdomain": clinic_data["amocrm_subdomain"],
                    "client_id": clinic_data["client_id"],
                    "client_secret": clinic_data["client_secret"],
                    "redirect_url": clinic_data["redirect_url"],
                    "amocrm_pipeline_id": clinic_data.get("amocrm_pipeline_id"),
                    "monthly_limit": clinic_data.get("monthly_limit", 100),
                    "current_month_usage": 0,
                    "last_reset_date": now,
                    "created_at": now,
                    "updated_at": now,
                }
                # Добавляю telegram_ids, если есть
                if "telegram_ids" in clinic_data:
                    clinic_doc["telegram_ids"] = clinic_data["telegram_ids"]

                # Сначала валидируем данные через AmoCRM
                amocrm_client = AsyncAmoCRMClient(
                    client_id=clinic_data["client_id"],
                    client_secret=clinic_data["client_secret"],
                    subdomain=clinic_data["amocrm_subdomain"],
                    redirect_url=clinic_data["redirect_url"],
                    mongo_uri=MONGO_URI,
                    db_name=DB_NAME,
                )
                try:
                    await amocrm_client.init_token(clinic_data["auth_code"])
                    logger.info("Токен AmoCRM инициализирован успешно")
                except Exception as e:
                    logger.error(f"Ошибка инициализации токена AmoCRM: {e}")
                    raise Exception(f"Ошибка AmoCRM: введен не верный auth_code")

                # Вставляем клинику в базу данных
                await self.db.clinics.insert_one(clinic_doc)
                clinic_id = clinic_doc["_id"]
                logger.info(f"Новая клиника создана с ID: {clinic_id}")

            # Получаем пользователей из AmoCRM
            users = await self.get_amocrm_users(amocrm_client)
            logger.info(
                f"Получено {len(users) if users else 0} пользователей из AmoCRM"
            )

            if not users:
                # Если не удалось получить пользователей, создадим хотя бы одного админа вручную
                logger.warning(
                    "Не удалось получить пользователей из AmoCRM, создаем базового админа"
                )

                # Проверяем, существует ли уже базовый администратор
                existing_admin = await self.db.administrators.find_one(
                    {"clinic_id": clinic_id, "amocrm_user_id": "default_admin"}
                )

                if existing_admin:
                    admin_ids = [
                        (
                            str(existing_admin["_id"])
                            if not isinstance(existing_admin["_id"], str)
                            else existing_admin["_id"]
                        )
                    ]
                    logger.info("Базовый администратор уже существует")
                else:
                    import uuid

                    admin_doc = {
                        "_id": str(uuid.uuid4()),  # Используем UUID как строковый _id
                        "clinic_id": clinic_id,
                        "name": "Администратор по умолчанию",
                        "amocrm_user_id": "default_admin",
                        "email": None,
                        "monthly_limit": None,
                        "current_month_usage": 0,
                        "created_at": now,
                        "updated_at": now,
                    }
                    await self.db.administrators.insert_one(admin_doc)
                    admin_ids = [admin_doc["_id"]]
                    logger.info("Создан базовый администратор")
            else:
                # Создаем администраторов в базе данных
                admin_ids = await self.create_administrators(users, clinic_id)

            logger.info(f"Всего администраторов: {len(admin_ids)}")

            # Обновляем клинику с добавлением ID администраторов
            await self.db.clinics.update_one(
                {"_id": clinic_id}, {"$set": {"administrator_ids": admin_ids}}
            )
            logger.info("Клиника обновлена с ID администраторов")

            # Возвращаем информацию о созданной/обновленной клинике
            return {
                "clinic_id": clinic_id,
                "name": clinic_data["name"],
                "administrator_count": len(admin_ids),
                "is_new": not existing_clinic,
            }

        except Exception as e:
            logger.error(f"Ошибка при регистрации клиники: {e}")
            import traceback

            logger.error(f"Трассировка: {traceback.format_exc()}")
            raise

    async def get_amocrm_users(self, amocrm_client):
        """
        Получает пользователей из AmoCRM
        """
        try:
            logger.info("Запрашиваем пользователей из AmoCRM")
            response, status_code = await amocrm_client.contacts.request("get", "users")

            logger.info(f"Получен ответ от AmoCRM: статус {status_code}")

            if status_code != 200:
                logger.error(
                    f"Ошибка при получении пользователей AmoCRM: статус {status_code}"
                )
                return []

            if "_embedded" not in response:
                logger.error(
                    f"В ответе AmoCRM отсутствует ключ '_embedded': {response}"
                )
                return []

            if "users" not in response["_embedded"]:
                logger.error(
                    f"В ответе AmoCRM отсутствует ключ 'users': {response['_embedded']}"
                )
                return []

            users = response["_embedded"]["users"]
            logger.info(f"Получено {len(users)} пользователей из AmoCRM")
            return users

        except Exception as e:
            logger.error(f"Исключение при получении пользователей AmoCRM: {e}")
            import traceback

            logger.error(f"Трассировка: {traceback.format_exc()}")
            return []

    async def create_administrators(self, amocrm_users, clinic_id):
        """
        Создает администраторов на основе пользователей AmoCRM.
        Предотвращает создание дубликатов.
        """
        admin_ids = []

        for user in amocrm_users:
            try:
                user_id = str(user["id"])
                # Проверяем, существует ли уже такой администратор
                existing_admin = await self.db.administrators.find_one(
                    {"amocrm_user_id": user_id, "clinic_id": clinic_id}
                )

                now = datetime.now().isoformat()

                if existing_admin:
                    # Обновляем существующего администратора
                    await self.db.administrators.update_one(
                        {"_id": existing_admin["_id"]},
                        {
                            "$set": {
                                "name": user.get("name", "Неизвестный администратор"),
                                "email": user.get("email"),
                                "updated_at": now,
                            }
                        },
                    )
                    admin_id = (
                        str(existing_admin["_id"])
                        if not isinstance(existing_admin["_id"], str)
                        else existing_admin["_id"]
                    )
                    admin_ids.append(admin_id)
                    logger.info(
                        f"Обновлен администратор: {user.get('name')} (ID: {admin_id})"
                    )
                else:
                    # Создаем нового администратора с уникальным ID
                    import uuid

                    admin_doc = {
                        "_id": str(uuid.uuid4()),  # Используем UUID как строковый _id
                        "clinic_id": clinic_id,
                        "name": user.get("name", "Неизвестный администратор"),
                        "amocrm_user_id": user_id,
                        "email": user.get("email"),
                        "monthly_limit": None,  # Используется лимит клиники
                        "current_month_usage": 0,
                        "created_at": now,
                        "updated_at": now,
                    }

                    await self.db.administrators.insert_one(admin_doc)
                    admin_ids.append(admin_doc["_id"])
                    logger.info(
                        f"Создан новый администратор: {user.get('name')} (ID: {admin_doc['_id']})"
                    )
            except Exception as e:
                logger.error(f"Ошибка при создании/обновлении администратора: {e}")
                continue

        return admin_ids

    async def get_clinic_by_id(self, clinic_id: str) -> Optional[Dict[str, Any]]:
        """
        Получает информацию о клинике по ID
        """
        try:
            # Пробуем несколько вариантов поиска
            clinic = None

            # 1. Пытаемся найти по _id как ObjectId (если это 24-символьная hex строка)
            if len(clinic_id) == 24 and all(
                c in "0123456789abcdefABCDEF" for c in clinic_id
            ):
                try:
                    clinic = await self.db.clinics.find_one(
                        {"_id": ObjectId(clinic_id)}
                    )
                except:
                    pass

            # 2. Если не нашли, пробуем искать по строковому _id
            if not clinic:
                clinic = await self.db.clinics.find_one({"_id": clinic_id})

            # 3. Пробуем по полю id
            if not clinic:
                clinic = await self.db.clinics.find_one({"id": clinic_id})

            # 4. Пробуем по полю client_id, если предыдущие варианты не сработали
            if not clinic:
                clinic = await self.db.clinics.find_one({"client_id": clinic_id})

            if not clinic:
                return None

            # Получаем администраторов клиники
            administrators = []

            # Определяем правильный тип clinic_id для запроса администраторов
            clinic_id_for_query = clinic["_id"]
            if isinstance(clinic_id_for_query, str):
                clinic_id_obj = clinic_id_for_query
            else:
                clinic_id_obj = clinic_id_for_query

            admin_cursor = self.db.administrators.find({"clinic_id": clinic_id_obj})

            async for admin in admin_cursor:
                administrators.append(
                    {
                        "id": (
                            str(admin["_id"])
                            if not isinstance(admin["_id"], str)
                            else admin["_id"]
                        ),
                        "name": admin["name"],
                        "email": admin.get("email"),
                        "amocrm_user_id": admin["amocrm_user_id"],
                        "monthly_limit": admin.get("monthly_limit"),
                        "current_month_usage": admin.get("current_month_usage", 0),
                    }
                )

            # Форматируем данные клиники
            clinic_data = {
                "id": (
                    str(clinic["_id"])
                    if not isinstance(clinic["_id"], str)
                    else clinic["_id"]
                ),
                "name": clinic["name"],
                "client_id": clinic["client_id"],
                "client_secret": clinic["client_secret"],
                "amocrm_subdomain": clinic["amocrm_subdomain"],
                "redirect_url": clinic["redirect_url"],
                "amocrm_pipeline_id": clinic.get("amocrm_pipeline_id"),
                "monthly_limit": clinic.get("monthly_limit", 100),
                "current_month_usage": clinic.get("current_month_usage", 0),
                "last_reset_date": clinic.get("last_reset_date"),
                "administrators": administrators,
            }

            return clinic_data

        except Exception as e:
            logger.error(f"Ошибка при получении информации о клинике: {e}")
            return None

    async def sync_administrators(self, clinic_id: str):
        """
        Синхронизирует администраторов клиники с AmoCRM
        """
        try:
            # Получаем информацию о клинике
            clinic = await self.db.clinics.find_one({"_id": ObjectId(clinic_id)})

            if not clinic:
                raise ValueError(f"Клиника с ID {clinic_id} не найдена")

            # Создаем клиент AmoCRM
            amocrm_client = AsyncAmoCRMClient(
                client_id=clinic["client_id"],
                client_secret=clinic["client_secret"],
                subdomain=clinic["amocrm_subdomain"],
                redirect_url=clinic["redirect_url"],
                mongo_uri=MONGO_URI,
                db_name=DB_NAME,
            )

            # Получаем пользователей из AmoCRM
            users = await self.get_amocrm_users(amocrm_client)

            # Получаем существующих администраторов
            existing_admins = {}
            admin_cursor = self.db.administrators.find(
                {"clinic_id": ObjectId(clinic_id)}
            )

            async for admin in admin_cursor:
                existing_admins[admin["amocrm_user_id"]] = admin

            # Обновляем/создаем администраторов
            added = 0
            updated = 0

            for user in users:
                user_id = str(user["id"])

                if user_id in existing_admins:
                    # Обновляем существующего администратора
                    await self.db.administrators.update_one(
                        {"_id": existing_admins[user_id]["_id"]},
                        {
                            "$set": {
                                "name": user.get("name", "Неизвестный администратор"),
                                "email": user.get("email"),
                                "updated_at": datetime.now().isoformat(),
                            }
                        },
                    )
                    updated += 1
                else:
                    # Создаем нового администратора
                    now = datetime.now().isoformat()
                    admin_doc = {
                        "clinic_id": ObjectId(clinic_id),
                        "name": user.get("name", "Неизвестный администратор"),
                        "amocrm_user_id": user_id,
                        "email": user.get("email"),
                        "monthly_limit": None,  # Используется лимит клиники
                        "current_month_usage": 0,
                        "created_at": now,
                        "updated_at": now,
                    }

                    await self.db.administrators.insert_one(admin_doc)
                    added += 1

            return {
                "added_administrators": added,
                "updated_administrators": updated,
                "total_administrators": len(users),
            }

        except Exception as e:
            logger.error(f"Ошибка при синхронизации администраторов: {e}")
            raise

    async def update_administrator(self, administrator_id: str, data: Dict[str, Any]):
        """
        Обновляет информацию об администраторе
        """
        try:
            # Проверяем, существует ли администратор
            admin = await self.db.administrators.find_one(
                {"_id": ObjectId(administrator_id)}
            )

            if not admin:
                raise ValueError(f"Администратор с ID {administrator_id} не найден")

            # Обновляем данные администратора
            update_data = {"updated_at": datetime.now().isoformat()}

            # Добавляем поля, которые нужно обновить
            valid_fields = ["name", "email", "monthly_limit"]
            for field in valid_fields:
                if field in data:
                    update_data[field] = data[field]

            await self.db.administrators.update_one(
                {"_id": ObjectId(administrator_id)}, {"$set": update_data}
            )

            # Получаем обновленного администратора
            updated_admin = await self.db.administrators.find_one(
                {"_id": ObjectId(administrator_id)}
            )

            return {
                "id": str(updated_admin["_id"]),
                "name": updated_admin["name"],
                "email": updated_admin.get("email"),
                "amocrm_user_id": updated_admin["amocrm_user_id"],
                "monthly_limit": updated_admin.get("monthly_limit"),
                "current_month_usage": updated_admin.get("current_month_usage", 0),
                "clinic_id": str(updated_admin["clinic_id"]),
            }

        except Exception as e:
            logger.error(f"Ошибка при обновлении администратора: {e}")
            raise

    async def reset_monthly_limits(self):
        """
        Сбрасывает месячные счетчики использования
        """
        try:
            now = datetime.now().isoformat()

            # Сбрасываем счетчики для клиник
            clinics_result = await self.db.clinics.update_many(
                {}, {"$set": {"current_month_usage": 0, "last_reset_date": now}}
            )

            # Сбрасываем счетчики для администраторов
            admins_result = await self.db.administrators.update_many(
                {}, {"$set": {"current_month_usage": 0}}
            )

            return {
                "reset_clinics": clinics_result.modified_count,
                "reset_administrators": admins_result.modified_count,
                "reset_date": now,
            }

        except Exception as e:
            logger.error(f"Ошибка при сбросе месячных счетчиков: {e}")
            raise

    async def find_clinic_by_client_id(self, client_id: str):
        """
        Находит клинику по client_id
        """
        try:
            clinic = await self.db.clinics.find_one({"client_id": client_id})

            if not clinic:
                return None

            return {
                "id": str(clinic["_id"]),
                "name": clinic["name"],
                "client_id": clinic["client_id"],
                "client_secret": clinic["client_secret"],
                "amocrm_subdomain": clinic["amocrm_subdomain"],
                "redirect_url": clinic["redirect_url"],
                "amocrm_pipeline_id": clinic.get("amocrm_pipeline_id"),
            }
        except Exception as e:
            logger.error(f"Ошибка при поиске клиники по client_id: {e}")
            return None

    async def test_mongodb_connection(self):
        """Тестирует подключение к MongoDB и возможность записи данных"""
        try:
            # Проверка подключения
            await self.db.command("ping")
            logger.info("MongoDB подключение работает")

            # Проверка записи и чтения
            test_collection = self.db.test_connection
            test_id = "test_" + datetime.now().isoformat()
            await test_collection.insert_one({"_id": test_id, "test": True})
            test_doc = await test_collection.find_one({"_id": test_id})
            await test_collection.delete_one({"_id": test_id})

            if test_doc and test_doc.get("test") == True:
                logger.info("MongoDB запись и чтение работают")
                return {"status": "ok", "message": "MongoDB подключение и операции работают"}
            else:
                logger.error("MongoDB чтение не работает")
                return {"status": "error", "message": "MongoDB чтение не работает"}

        except Exception as e:
            logger.error(f"Ошибка при тестировании MongoDB: {e}")
            return {"status": "error", "message": f"Ошибка подключения к MongoDB: {str(e)}"}

    async def check_monthly_limit(self, clinic_id: str, administrator_id: str = None):
        """
        Проверяет, не превышен ли месячный лимит для клиники или администратора
        """
        try:
            # Получаем данные клиники
            clinic = await self.db.clinics.find_one({"_id": clinic_id})
            if not clinic:
                raise ValueError(f"Клиника с ID {clinic_id} не найдена")

            clinic_limit_exceeded = False
            admin_limit_exceeded = False
            clinic_monthly_limit = clinic.get("monthly_limit", 100)
            clinic_current_usage = clinic.get("current_month_usage", 0)

            # Проверяем лимит клиники
            if clinic_current_usage >= clinic_monthly_limit:
                clinic_limit_exceeded = True

            # Если указан администратор, проверяем его лимит
            admin_info = None
            if administrator_id:
                admin = await self.db.administrators.find_one({"_id": administrator_id})
                if admin:
                    admin_monthly_limit = admin.get("monthly_limit")
                    admin_current_usage = admin.get("current_month_usage", 0)

                    # Если у администратора установлен лимит, проверяем его
                    if admin_monthly_limit is not None and admin_current_usage >= admin_monthly_limit:
                        admin_limit_exceeded = True

                    admin_info = {
                        "id": str(admin["_id"]),
                        "name": admin.get("name", "Неизвестный"),
                        "monthly_limit": admin_monthly_limit,
                        "current_usage": admin_current_usage,
                        "limit_exceeded": admin_limit_exceeded
                    }

            return {
                "clinic": {
                    "id": str(clinic["_id"]),
                    "name": clinic.get("name", "Неизвестная клиника"),
                    "monthly_limit": clinic_monthly_limit,
                    "current_usage": clinic_current_usage,
                    "limit_exceeded": clinic_limit_exceeded
                },
                "administrator": admin_info,
                "limit_exceeded": clinic_limit_exceeded or admin_limit_exceeded
            }

        except Exception as e:
            logger.error(f"Ошибка при проверке месячного лимита: {e}")
            raise

    async def increment_usage_counter(self, clinic_id: str, administrator_id: str = None):
        """
        Увеличивает счетчик использования для клиники и администратора
        """
        try:
            # Увеличиваем счетчик для клиники
            await self.db.clinics.update_one(
                {"_id": clinic_id},
                {"$inc": {"current_month_usage": 1}}
            )

            # Если указан администратор, увеличиваем его счетчик
            if administrator_id:
                await self.db.administrators.update_one(
                    {"_id": administrator_id},
                    {"$inc": {"current_month_usage": 1}}
                )

            return True
        except Exception as e:
            logger.error(f"Ошибка при увеличении счетчика использования: {e}")
            return False
