"""
Репозиторий для работы с анализом звонков.
Реализует методы для доступа к данным анализа звонков в MongoDB.
"""

from typing import Any, Dict, List, Optional, Union
from datetime import datetime, date
from bson import ObjectId

from app.repositories.base_repository import BaseRepository
from app.models.call_analysis import (
    CallAnalysisModel,
    CallAnalysisSummary,
    CallMetricsAggregate,
)
from app.services.mongodb_service import MongoDBService
from fastapi import Depends
import logging

logger = logging.getLogger(__name__)


class CallAnalysisRepository(BaseRepository[CallAnalysisModel, str]):
    """
    Репозиторий для работы с анализом звонков.
    Наследуется от BaseRepository и реализует методы для работы с CallAnalysisModel.
    """

    def __init__(self, mongodb_service: MongoDBService = Depends()):
        """
        Инициализирует репозиторий для работы с анализом звонков.

        Args:
            mongodb_service: Сервис MongoDB для доступа к базе данных
        """
        super().__init__("call_analytics", mongodb_service)

    async def to_entity(self, data: Dict[str, Any]) -> CallAnalysisModel:
        """
        Преобразует документ MongoDB в модель CallAnalysisModel.

        Args:
            data: Данные из MongoDB

        Returns:
            Модель CallAnalysisModel
        """
        # Преобразуем _id в строку для совместимости с Pydantic
        if "_id" in data:
            data["id"] = str(data["_id"])

        return CallAnalysisModel(**data)

    async def to_document(self, entity: CallAnalysisModel) -> Dict[str, Any]:
        """
        Преобразует модель CallAnalysisModel в документ MongoDB.

        Args:
            entity: Модель CallAnalysisModel

        Returns:
            Документ MongoDB
        """
        # Проверяем наличие рекомендаций перед сохранением
        if hasattr(entity, "recommendations") and entity.recommendations is None:
            entity.recommendations = []
        
        document = entity.model_dump(by_alias=True, exclude_none=True)

        # Преобразуем id в ObjectId для MongoDB если он существует
        if "id" in document:
            document["_id"] = ObjectId(document["id"])
            del document["id"]
            
        # Проверяем, что рекомендации присутствуют в документе
        if "recommendations" not in document and hasattr(entity, "recommendations"):
            document["recommendations"] = entity.recommendations or []
            
        return document

    async def find_by_call_id(self, call_id: str) -> Optional[CallAnalysisModel]:
        """
        Находит анализ звонка по идентификатору звонка.

        Args:
            call_id: Идентификатор звонка

        Returns:
            Модель CallAnalysisModel или None
        """
        document = await self.mongodb_service.find_one(
            collection=self.collection_name, query={"call_id": call_id}
        )

        if document:
            return await self.to_entity(document)
        return None

    async def find_by_note_id(self, note_id: int) -> Optional[CallAnalysisModel]:
        """
        Находит анализ звонка по идентификатору заметки AmoCRM.

        Args:
            note_id: Идентификатор заметки AmoCRM

        Returns:
            Модель CallAnalysisModel или None
        """
        document = await self.mongodb_service.find_one(
            collection=self.collection_name, query={"note_id": note_id}
        )

        if document:
            return await self.to_entity(document)
        return None

    async def find_by_clinic_id(
        self, clinic_id: str, limit: int = 100, skip: int = 0
    ) -> List[CallAnalysisModel]:
        """
        Находит все анализы звонков для указанной клиники.

        Args:
            clinic_id: Идентификатор клиники
            limit: Максимальное количество результатов
            skip: Смещение для пагинации

        Returns:
            Список моделей CallAnalysisModel
        """
        return await self.find_by_query(
            query={"clinic_id": clinic_id}, limit=limit, skip=skip
        )

    async def find_by_administrator_id(
        self, administrator_id: str, limit: int = 100, skip: int = 0
    ) -> List[CallAnalysisModel]:
        """
        Находит все анализы звонков для указанного администратора.

        Args:
            administrator_id: Идентификатор администратора
            limit: Максимальное количество результатов
            skip: Смещение для пагинации

        Returns:
            Список моделей CallAnalysisModel
        """
        return await self.find_by_query(
            query={"administrator_id": administrator_id}, limit=limit, skip=skip
        )

    async def find_by_date_range(
        self,
        start_date: str,
        end_date: str,
        clinic_id: Optional[str] = None,
        administrator_id: Optional[str] = None,
        limit: int = 100,
        skip: int = 0,
    ) -> List[CallAnalysisModel]:
        """
        Находит все анализы звонков в указанном диапазоне дат с возможностью фильтрации по клинике и администратору.

        Args:
            start_date: Начальная дата в формате YYYY-MM-DD
            end_date: Конечная дата в формате YYYY-MM-DD
            clinic_id: Идентификатор клиники (опционально)
            administrator_id: Идентификатор администратора (опционально)
            limit: Максимальное количество результатов
            skip: Смещение для пагинации

        Returns:
            Список моделей CallAnalysisModel
        """
        query = {"date": {"$gte": start_date, "$lte": end_date}}

        if clinic_id:
            query["clinic_id"] = clinic_id

        if administrator_id:
            query["administrator_id"] = administrator_id

        return await self.find_by_query(query=query, limit=limit, skip=skip)

    async def get_call_analysis_summary(
        self,
        start_date: str,
        end_date: str,
        clinic_id: Optional[str] = None,
        administrator_id: Optional[str] = None,
        limit: int = 100,
        skip: int = 0,
    ) -> List[CallAnalysisSummary]:
        """
        Получает сводку по анализу звонков за указанный период.

        Args:
            start_date: Начальная дата в формате YYYY-MM-DD
            end_date: Конечная дата в формате YYYY-MM-DD
            clinic_id: Идентификатор клиники (опционально)
            administrator_id: Идентификатор администратора (опционально)
            limit: Максимальное количество результатов
            skip: Смещение для пагинации

        Returns:
            Список моделей CallAnalysisSummary
        """
        query = {"date": {"$gte": start_date, "$lte": end_date}}

        if clinic_id:
            query["clinic_id"] = clinic_id

        if administrator_id:
            query["administrator_id"] = administrator_id

        # Создаем пайплайн для агрегации, чтобы получить только нужные поля
        pipeline = [
            {"$match": query},
            {"$sort": {"timestamp": -1}},
            {"$skip": skip},
            {"$limit": limit},
            {
                "$project": {
                    "_id": 1,
                    "date": 1,
                    "timestamp": 1,
                    "administrator_name": 1,
                    "client.phone": 1,
                    "call_type.category_name": 1,
                    "call_type.direction": 1,
                    "metrics.overall_score": 1,
                    "conversion": 1,
                    "metrics.customer_satisfaction": 1,
                    "recommendations": 1,
                }
            },
        ]

        documents = await self.mongodb_service.aggregate(
            collection=self.collection_name, pipeline=pipeline
        )

        # Преобразуем результаты в модели CallAnalysisSummary
        result = []
        for doc in documents:
            # Преобразуем вложенные поля
            summary = {
                "id": str(doc["_id"]),
                "date": doc["date"],
                "timestamp": doc["timestamp"],
                "administrator_name": doc["administrator_name"],
                "client_phone": doc.get("client", {}).get("phone"),
                "call_category": doc.get("call_type", {}).get(
                    "category_name", "Неизвестно"
                ),
                "call_direction": doc.get("call_type", {}).get("direction"),
                "overall_score": doc.get("metrics", {}).get("overall_score", 0.0),
                "conversion": doc.get("conversion", False),
                "satisfaction": doc.get("metrics", {}).get("customer_satisfaction"),
                "recommendations": doc.get("recommendations", []),
            }

            result.append(CallAnalysisSummary(**summary))

        return result

    async def get_metrics_aggregate(
        self,
        start_date: str,
        end_date: str,
        clinic_id: Optional[str] = None,
        administrator_ids: Optional[List[str]] = None,
    ) -> CallMetricsAggregate:
        """
        Получает агрегированные метрики по звонкам за указанный период.

        Args:
            start_date: Начальная дата в формате YYYY-MM-DD
            end_date: Конечная дата в формате YYYY-MM-DD
            clinic_id: Идентификатор клиники (опционально)
            administrator_ids: Список идентификаторов администраторов (опционально)

        Returns:
            Агрегированные метрики CallMetricsAggregate
        """
        match_query = {"date": {"$gte": start_date, "$lte": end_date}}

        if clinic_id:
            match_query["clinic_id"] = clinic_id

        if administrator_ids:
            match_query["administrator_id"] = {"$in": administrator_ids}

        # Создаем пайплайн для агрегации метрик
        pipeline = [
            {"$match": match_query},
            {
                "$facet": {
                    "total": [{"$count": "count"}],
                    "incoming": [
                        {"$match": {"call_type.direction": "incoming"}},
                        {"$count": "count"},
                    ],
                    "outgoing": [
                        {"$match": {"call_type.direction": "outgoing"}},
                        {"$count": "count"},
                    ],
                    "conversion": [
                        {"$match": {"conversion": True}},
                        {"$count": "count"},
                    ],
                    "avg_score": [
                        {
                            "$group": {
                                "_id": None,
                                "avg": {"$avg": "$metrics.overall_score"},
                            }
                        }
                    ],
                    "administrators": [
                        {
                            "$group": {
                                "_id": "$administrator_id",
                                "name": {"$first": "$administrator_name"},
                                "count": {"$sum": 1},
                                "avg_score": {"$avg": "$metrics.overall_score"},
                                "conversion_count": {
                                    "$sum": {
                                        "$cond": [{"$eq": ["$conversion", True]}, 1, 0]
                                    }
                                },
                            }
                        }
                    ],
                    "call_types": [
                        {
                            "$group": {
                                "_id": "$call_type.category",
                                "name": {"$first": "$call_type.category_name"},
                                "count": {"$sum": 1},
                            }
                        }
                    ],
                    "traffic_sources": [
                        {
                            "$group": {
                                "_id": "$client.source",
                                "count": {"$sum": 1},
                                "conversion_count": {
                                    "$sum": {
                                        "$cond": [{"$eq": ["$conversion", True]}, 1, 0]
                                    }
                                },
                            }
                        }
                    ],
                }
            },
        ]

        results = await self.mongodb_service.aggregate(
            collection=self.collection_name, pipeline=pipeline
        )

        # Обрабатываем результаты агрегации
        if not results or len(results) == 0:
            return CallMetricsAggregate()

        result = results[0]

        # Извлекаем значения из результатов агрегации
        total_calls = result["total"][0]["count"] if result["total"] else 0
        incoming_calls = result["incoming"][0]["count"] if result["incoming"] else 0
        outgoing_calls = result["outgoing"][0]["count"] if result["outgoing"] else 0
        conversion_count = (
            result["conversion"][0]["count"] if result["conversion"] else 0
        )
        avg_score = result["avg_score"][0]["avg"] if result["avg_score"] else 0.0

        # Вычисляем процент конверсии
        conversion_rate = (
            (conversion_count / total_calls) * 100 if total_calls > 0 else 0.0
        )

        # Преобразуем данные администраторов
        administrators = []
        for admin in result["administrators"]:
            admin_conversion_rate = (
                (admin["conversion_count"] / admin["count"]) * 100
                if admin["count"] > 0
                else 0.0
            )
            administrators.append(
                {
                    "id": admin["_id"],
                    "name": admin["name"],
                    "call_count": admin["count"],
                    "avg_score": admin["avg_score"],
                    "conversion_count": admin["conversion_count"],
                    "conversion_rate": admin_conversion_rate,
                }
            )

        # Преобразуем данные типов звонков
        call_types = {}
        for call_type in result["call_types"]:
            call_types[call_type["_id"]] = {
                "name": call_type["name"],
                "count": call_type["count"],
                "percentage": (
                    (call_type["count"] / total_calls) * 100 if total_calls > 0 else 0.0
                ),
            }

        # Преобразуем данные источников трафика
        traffic_sources = {}
        for source in result["traffic_sources"]:
            source_conversion_rate = (
                (source["conversion_count"] / source["count"]) * 100
                if source["count"] > 0
                else 0.0
            )
            traffic_sources[source["_id"] or "unknown"] = {
                "count": source["count"],
                "percentage": (
                    (source["count"] / total_calls) * 100 if total_calls > 0 else 0.0
                ),
                "conversion_count": source["conversion_count"],
                "conversion_rate": source_conversion_rate,
            }

        # Создаем и возвращаем модель агрегированных метрик
        return CallMetricsAggregate(
            total_calls=total_calls,
            incoming_calls=incoming_calls,
            outgoing_calls=outgoing_calls,
            conversion_count=conversion_count,
            conversion_rate=conversion_rate,
            avg_score=avg_score,
            administrators=administrators,
            call_types=call_types,
            traffic_sources=traffic_sources,
        )

    async def save_multiple(self, entities: List[CallAnalysisModel]) -> List[str]:
        """
        Сохраняет несколько записей анализа звонков

        Args:
            entities: Список моделей анализа звонков

        Returns:
            Список идентификаторов созданных записей
        """
        try:
            documents = [self.to_document(entity) for entity in entities]
            result = await self.collection.insert_many(documents)
            return [str(id) for id in result.inserted_ids]
        except Exception as e:
            logger.error(f"Ошибка при сохранении анализов звонков: {str(e)}")
            return []

    async def create_test_analysis(
        self,
        clinic_id: str,
        administrator_id: str,
        administrator_name: str,
        timestamp: datetime,
        date: date,
        call_type: Dict[str, Any],
        client: Dict[str, Any],
        metrics: Dict[str, Any],
        recommendations: List[str],
        analysis_text: str,
        transcription_text: str,
        meta_info: Dict[str, Any] = None,
        conversion: bool = False
    ) -> Optional[str]:
        """
        Создает тестовый анализ звонка в базе данных

        Args:
            clinic_id: ID клиники
            administrator_id: ID администратора
            administrator_name: Имя администратора
            timestamp: Временная метка
            date: Дата звонка
            call_type: Информация о типе звонка
            client: Информация о клиенте
            metrics: Метрики звонка
            recommendations: Список рекомендаций
            analysis_text: Текст анализа
            transcription_text: Текст транскрипции
            meta_info: Метаданные
            conversion: Флаг конверсии

        Returns:
            ID созданной записи или None в случае ошибки
        """
        try:
            # Создаем модель анализа
            analysis = CallAnalysisModel(
                clinic_id=clinic_id,
                administrator_id=administrator_id,
                administrator_name=administrator_name,
                timestamp=timestamp,
                date=date,
                call_type=call_type,
                client=client,
                metrics=metrics,
                recommendations=recommendations,
                analysis_text=analysis_text,
                transcription_text=transcription_text,
                meta_info=meta_info or {},
                conversion=conversion
            )
            
            # Преобразуем в документ для MongoDB
            document = self.to_document(analysis)
            
            # Сохраняем в базу данных
            result = await self.collection.insert_one(document)
            
            # Возвращаем ID созданной записи
            return str(result.inserted_id)
        except Exception as e:
            logger.error(f"Ошибка при создании тестового анализа: {str(e)}")
            return None
