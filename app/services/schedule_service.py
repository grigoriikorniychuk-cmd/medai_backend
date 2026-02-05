"""
Сервис для управления графиками работы администраторов.
Используется для определения администратора по транскрипции звонка + график работы.
"""

import logging
from datetime import datetime, date
from typing import Dict, Any, List, Optional
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

from app.settings.paths import MONGO_URI, DB_NAME

logger = logging.getLogger(__name__)



class ScheduleService:
    """Сервис для работы с графиками администраторов"""

    def __init__(self):
        client = AsyncIOMotorClient(MONGO_URI)
        self.db = client[DB_NAME]

    async def create_schedule(
        self,
        clinic_id: str,
        dates: List[str],  # Список дат в формате "YYYY-MM-DD"
        first_name: str,
        last_name: str,
    ) -> List[str]:
        """
        Создание записей графика для администратора на указанные даты.
        
        Args:
            clinic_id: ID клиники
            dates: Список дат в формате "YYYY-MM-DD"
            first_name: Имя администратора
            last_name: Фамилия администратора
            
        Returns:
            List[str]: Список созданных ID записей
        """
        try:
            # Создаём записи для каждой даты
            created_ids = []
            for date_str in dates:
                try:
                    # Парсим дату и конвертируем в datetime (MongoDB не поддерживает date)
                    schedule_datetime = datetime.strptime(date_str, "%Y-%m-%d")
                    
                    # Проверяем, нет ли уже записи для этого человека на эту дату
                    existing = await self.db.work_schedules.find_one({
                        "clinic_id": clinic_id,
                        "first_name": first_name,
                        "last_name": last_name,
                        "date": schedule_datetime
                    })
                    
                    if existing:
                        logger.warning(
                            f"График для {first_name} {last_name} на дату {date_str} "
                            f"уже существует, пропускаем"
                        )
                        continue
                    
                    # Создаём запись
                    schedule_doc = {
                        "clinic_id": clinic_id,
                        "date": schedule_datetime,
                        "first_name": first_name,
                        "last_name": last_name,
                        "created_at": datetime.utcnow(),
                    }
                    
                    result = await self.db.work_schedules.insert_one(schedule_doc)
                    created_ids.append(str(result.inserted_id))
                    
                    logger.info(
                        f"Создана запись графика {result.inserted_id} для "
                        f"{first_name} {last_name} на {date_str}"
                    )
                    
                except ValueError as e:
                    logger.error(f"Неверный формат даты {date_str}: {e}")
                    continue
                    
            return created_ids
            
        except Exception as e:
            logger.error(f"Ошибка при создании графика: {e}")
            return []

    async def update_schedule(
        self, schedule_id: str, updates: Dict[str, Any]
    ) -> bool:
        """
        Обновление записи графика.
        
        Args:
            schedule_id: ID записи графика
            updates: Словарь с полями для обновления
            
        Returns:
            bool: True если успешно
        """
        try:
            obj_id = ObjectId(schedule_id)
            
            # Фильтруем разрешённые поля
            allowed_fields = ["first_name", "last_name", "date"]
            filtered_updates = {k: v for k, v in updates.items() if k in allowed_fields}
            
            if not filtered_updates:
                logger.warning(f"Нет валидных полей для обновления графика {schedule_id}")
                return False
            
            # Если обновляется дата, парсим её
            if "date" in filtered_updates:
                if isinstance(filtered_updates["date"], str):
                    filtered_updates["date"] = datetime.strptime(
                        filtered_updates["date"], "%Y-%m-%d"
                    )
            
            filtered_updates["updated_at"] = datetime.utcnow()
            
            result = await self.db.work_schedules.update_one(
                {"_id": obj_id}, {"$set": filtered_updates}
            )
            
            if result.modified_count > 0:
                logger.info(f"График {schedule_id} обновлён: {filtered_updates}")
                return True
            else:
                logger.warning(f"График {schedule_id} не найден или не изменился")
                return False
                
        except Exception as e:
            logger.error(f"Ошибка при обновлении графика {schedule_id}: {e}")
            return False

    async def delete_schedule(self, schedule_id: str) -> bool:
        """
        Удаление записи графика.
        
        Args:
            schedule_id: ID записи графика
            
        Returns:
            bool: True если успешно
        """
        try:
            obj_id = ObjectId(schedule_id)
            
            result = await self.db.work_schedules.delete_one({"_id": obj_id})
            
            if result.deleted_count > 0:
                logger.info(f"График {schedule_id} удалён")
                return True
            else:
                logger.warning(f"График {schedule_id} не найден")
                return False
                
        except Exception as e:
            logger.error(f"Ошибка при удалении графика {schedule_id}: {e}")
            return False

    async def get_schedules_by_date_range(
        self,
        clinic_id: str,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Получение графиков клиники за период.
        
        Args:
            clinic_id: ID клиники
            date_from: Начальная дата в формате "YYYY-MM-DD" (опционально)
            date_to: Конечная дата в формате "YYYY-MM-DD" (опционально)
            
        Returns:
            List[Dict]: Список записей графика
        """
        try:
            query = {"clinic_id": clinic_id}
            
            # Добавляем фильтр по датам если указаны
            if date_from or date_to:
                date_filter = {}
                if date_from:
                    date_filter["$gte"] = datetime.strptime(date_from, "%Y-%m-%d")
                if date_to:
                    # Добавляем 1 день чтобы включить конечную дату полностью
                    end_date = datetime.strptime(date_to, "%Y-%m-%d")
                    date_filter["$lt"] = datetime.combine(end_date.date(), datetime.max.time())
                query["date"] = date_filter
            
            schedules = await self.db.work_schedules.find(query).sort("date", 1).to_list(length=1000)
            
            # Конвертируем ObjectId и datetime в строки
            for schedule in schedules:
                schedule["_id"] = str(schedule["_id"])
                # Конвертируем datetime в строку для JSON сериализации (только дата)
                if isinstance(schedule["date"], datetime):
                    schedule["date"] = schedule["date"].strftime("%Y-%m-%d")
            
            logger.info(f"Найдено {len(schedules)} записей графика для клиники {clinic_id}")
            return schedules
            
        except Exception as e:
            logger.error(f"Ошибка при получении графиков: {e}")
            return []

    async def get_schedule_for_date(
        self,
        clinic_id: str,
        call_date: date,
    ) -> List[Dict[str, str]]:
        """
        Получить список администраторов из графика на указанную дату.
        
        ПРАВИЛЬНЫЙ ПОДХОД: просто возвращаем список, AI сам сопоставит с транскрипцией.
        
        Args:
            clinic_id: ID клиники
            call_date: Дата звонка
            
        Returns:
            List[Dict]: Список администраторов в формате [{"first_name": "...", "last_name": "..."}, ...]
            Пустой список, если график не заполнен
        """
        try:
            logger.info(f"Получение графика для клиники {clinic_id} на дату {call_date}")
            
            # Конвертируем date в datetime для поиска в MongoDB
            if isinstance(call_date, date) and not isinstance(call_date, datetime):
                start_of_day = datetime.combine(call_date, datetime.min.time())
                end_of_day = datetime.combine(call_date, datetime.max.time())
            else:
                start_of_day = datetime.combine(call_date.date(), datetime.min.time())
                end_of_day = datetime.combine(call_date.date(), datetime.max.time())
            
            # Получаем все записи графика на эту дату
            schedules = await self.db.work_schedules.find({
                "clinic_id": clinic_id,
                "date": {
                    "$gte": start_of_day,
                    "$lte": end_of_day
                }
            }).to_list(length=100)
            
            if not schedules:
                logger.warning(f"График не заполнен для клиники {clinic_id} на дату {call_date}")
                return []
            
            # Формируем список администраторов
            administrators = [
                {
                    "first_name": schedule["first_name"],
                    "last_name": schedule["last_name"]
                }
                for schedule in schedules
            ]
            
            admin_names = ', '.join([f"{a['first_name']} {a['last_name']}" for a in administrators])
            logger.info(
                f"Найдено {len(administrators)} администраторов в графике на {call_date}: "
                f"{admin_names}"
            )
            
            return administrators
            
        except Exception as e:
            logger.error(f"Ошибка при получении графика: {e}")
            return []

