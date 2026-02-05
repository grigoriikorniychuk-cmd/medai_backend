from motor.motor_asyncio import AsyncIOMotorClient
from bson.objectid import ObjectId
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "medai"


class LimitsService:
    def __init__(self):
        self.client = AsyncIOMotorClient(MONGO_URI)
        self.db = self.client[DB_NAME]

    async def check_limits(self, administrator_id):
        """
        Проверяет, не превышены ли лимиты для администратора и клиники
        """
        try:
            # Получаем информацию об администраторе
            admin = await self.db.administrators.find_one(
                {"_id": ObjectId(administrator_id)}
            )

            if not admin:
                return False, "Администратор не найден", 0

            # Получаем информацию о клинике
            clinic = await self.db.clinics.find_one({"_id": admin["clinic_id"]})

            if not clinic:
                return False, "Клиника не найдена", 0

            # Проверяем лимит клиники
            clinic_limit = clinic.get("monthly_limit", 100)
            clinic_usage = clinic.get("current_month_usage", 0)

            if clinic_usage >= clinic_limit:
                return (
                    False,
                    f"Превышен месячный лимит клиники ({clinic_usage}/{clinic_limit})",
                    0,
                )

            # Проверяем персональный лимит администратора, если он установлен
            admin_limit = admin.get("monthly_limit")

            if admin_limit is not None:
                admin_usage = admin.get("current_month_usage", 0)

                if admin_usage >= admin_limit:
                    return (
                        False,
                        f"Превышен персональный лимит администратора ({admin_usage}/{admin_limit})",
                        0,
                    )

                # Расчет оставшегося количества для администратора
                remaining = min(clinic_limit - clinic_usage, admin_limit - admin_usage)
            else:
                # Если у администратора нет персонального лимита, используем лимит клиники
                remaining = clinic_limit - clinic_usage

            return True, None, remaining

        except Exception as e:
            logger.error(f"Ошибка при проверке лимитов: {e}")
            return False, f"Ошибка при проверке лимитов: {e}", 0

    async def increment_usage(self, administrator_id):
        """
        Увеличивает счетчик использования для администратора и клиники
        """
        try:
            # Получаем информацию об администраторе
            admin = await self.db.administrators.find_one(
                {"_id": ObjectId(administrator_id)}
            )

            if not admin:
                raise ValueError(f"Администратор с ID {administrator_id} не найден")

            # Увеличиваем счетчик использования для администратора
            await self.db.administrators.update_one(
                {"_id": ObjectId(administrator_id)},
                {"$inc": {"current_month_usage": 1}},
            )

            # Увеличиваем счетчик использования для клиники
            await self.db.clinics.update_one(
                {"_id": admin["clinic_id"]}, {"$inc": {"current_month_usage": 1}}
            )

            return True

        except Exception as e:
            logger.error(f"Ошибка при инкрементировании счетчика использования: {e}")
            return False
