from motor.motor_asyncio import AsyncIOMotorClient
from bson.objectid import ObjectId
from datetime import datetime
import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "medai"


class CallRecordService:
    def __init__(self):
        self.client = AsyncIOMotorClient(MONGO_URI)
        self.db = self.client[DB_NAME]

    async def save_call_record(self, record_data):
        """
        Сохраняет запись о звонке в базу данных
        """
        try:
            # Получаем администратора
            admin = await self.db.administrators.find_one(
                {"_id": ObjectId(record_data["administrator_id"])}
            )

            if not admin:
                raise ValueError(
                    f"Администратор с ID {record_data['administrator_id']} не найден"
                )

            # Формируем запись для базы данных
            now = datetime.now().isoformat()
            call_record = {
                "administrator_id": ObjectId(record_data["administrator_id"]),
                "clinic_id": admin["clinic_id"],
                "amocrm_lead_id": record_data.get("amocrm_lead_id"),
                "amocrm_contact_id": record_data.get("amocrm_contact_id"),
                "amocrm_note_id": record_data.get("amocrm_note_id"),
                "call_date": record_data.get("call_date", now),
                "call_type": record_data.get("call_type", "unknown"),
                "call_duration": record_data.get("call_duration", 0),
                "audio_file": record_data.get("audio_file"),
                "transcription_file": record_data.get("transcription_file"),
                "analysis_file": record_data.get("analysis_file"),
                "call_category": record_data.get("call_category", "unknown"),
                "traffic_source": record_data.get("traffic_source", "unknown"),
                "is_converted": record_data.get("is_converted", False),
                "metrics": record_data.get("metrics", {}),
                "created_at": now,
                "updated_at": now,
            }

            # Вставляем запись в базу данных
            result = await self.db.call_records.insert_one(call_record)

            return {
                "record_id": str(result.inserted_id),
                "administrator_id": record_data["administrator_id"],
                "clinic_id": str(admin["clinic_id"]),
            }

        except Exception as e:
            logger.error(f"Ошибка при сохранении записи о звонке: {e}")
            raise

    async def get_call_records(
        self, clinic_id=None, administrator_id=None, start_date=None, end_date=None
    ):
        """
        Получает записи о звонках с возможностью фильтрации
        """
        try:
            # Формируем фильтр
            filter_query = {}

            if clinic_id:
                filter_query["clinic_id"] = ObjectId(clinic_id)

            if administrator_id:
                filter_query["administrator_id"] = ObjectId(administrator_id)

            if start_date or end_date:
                date_filter = {}

                if start_date:
                    date_filter["$gte"] = start_date

                if end_date:
                    date_filter["$lte"] = end_date

                if date_filter:
                    filter_query["call_date"] = date_filter

            # Получаем записи
            cursor = self.db.call_records.find(filter_query).sort("call_date", -1)

            records = []
            async for record in cursor:
                records.append(
                    {
                        "id": str(record["_id"]),
                        "administrator_id": str(record["administrator_id"]),
                        "clinic_id": str(record["clinic_id"]),
                        "amocrm_lead_id": record.get("amocrm_lead_id"),
                        "amocrm_contact_id": record.get("amocrm_contact_id"),
                        "call_date": record.get("call_date"),
                        "call_type": record.get("call_type"),
                        "call_duration": record.get("call_duration"),
                        "call_category": record.get("call_category"),
                        "traffic_source": record.get("traffic_source"),
                        "is_converted": record.get("is_converted"),
                        "metrics": record.get("metrics"),
                        "files": {
                            "audio": record.get("audio_file"),
                            "transcription": record.get("transcription_file"),
                            "analysis": record.get("analysis_file"),
                        },
                    }
                )

            return records

        except Exception as e:
            logger.error(f"Ошибка при получении записей о звонках: {e}")
            raise

    async def update_call_record(self, record_id: str, update_data: Dict[str, Any]) -> bool:
        """
        Обновляет запись о звонке в базе данных

        Args:
            record_id: ID записи
            update_data: Данные для обновления

        Returns:
            True если обновление успешно, иначе False
        """
        try:
            # Подготавливаем данные для обновления
            update_doc = {
                "$set": {
                    **update_data,
                    "updated_at": datetime.now().isoformat()
                }
            }
            
            # Преобразуем id в ObjectId
            record_id_obj = ObjectId(record_id)
            
            # Выполняем обновление
            result = await self.db.call_records.update_one(
                {"_id": record_id_obj},
                update_doc
            )
            
            if result.modified_count > 0:
                logger.info(f"Запись о звонке {record_id} успешно обновлена")
                return True
            else:
                logger.warning(f"Запись о звонке {record_id} не найдена или не обновлена")
                return False
                
        except Exception as e:
            logger.error(f"Ошибка при обновлении записи о звонке {record_id}: {str(e)}")
            return False
