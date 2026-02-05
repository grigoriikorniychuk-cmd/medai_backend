"""
Базовый репозиторий для работы с MongoDB.
Предоставляет абстракцию для взаимодействия с базой данных.
"""

from typing import Any, Dict, List, Optional, TypeVar, Generic, Union
from bson import ObjectId
from datetime import datetime
import logging
from abc import ABC, abstractmethod

from app.services.mongodb_service import MongoDBService

# Создаем типизированные переменные для обобщения
T = TypeVar("T")
ID = TypeVar("ID")


class BaseRepository(Generic[T, ID], ABC):
    """
    Абстрактный базовый репозиторий для работы с MongoDB.
    Использует паттерн Repository для абстрагирования работы с данными.
    """

    def __init__(self, collection_name: str, mongodb_service: MongoDBService):
        """
        Инициализирует репозиторий.

        Args:
            collection_name: Имя коллекции в MongoDB
            mongodb_service: Сервис MongoDB для доступа к базе данных
        """
        self.mongodb_service = mongodb_service
        self.collection_name = collection_name

    @abstractmethod
    async def to_entity(self, data: Dict[str, Any]) -> T:
        """
        Преобразует данные из MongoDB в сущность.

        Args:
            data: Данные из MongoDB

        Returns:
            Объект сущности
        """
        pass

    @abstractmethod
    async def to_document(self, entity: T) -> Dict[str, Any]:
        """
        Преобразует сущность в документ MongoDB.

        Args:
            entity: Объект сущности

        Returns:
            Документ MongoDB
        """
        pass

    async def find_by_id(self, id: ID) -> Optional[T]:
        """
        Находит сущность по ID.

        Args:
            id: Идентификатор сущности

        Returns:
            Объект сущности или None
        """
        document = await self.mongodb_service.find_one(
            collection=self.collection_name,
            query={"_id": ObjectId(id) if isinstance(id, str) else id},
        )

        if document:
            return await self.to_entity(document)
        return None

    async def find_all(self, limit: int = 100, skip: int = 0) -> List[T]:
        """
        Находит все сущности с пагинацией.

        Args:
            limit: Максимальное количество результатов
            skip: Смещение для пагинации

        Returns:
            Список сущностей
        """
        documents = await self.mongodb_service.find_many(
            collection=self.collection_name, query={}, skip=skip, limit=limit
        )

        result = []
        for document in documents:
            entity = await self.to_entity(document)
            result.append(entity)

        return result

    async def find_by_query(
        self, query: Dict[str, Any], limit: int = 100, skip: int = 0
    ) -> List[T]:
        """
        Находит сущности по запросу с пагинацией.

        Args:
            query: Запрос MongoDB
            limit: Максимальное количество результатов
            skip: Смещение для пагинации

        Returns:
            Список сущностей
        """
        documents = await self.mongodb_service.find_many(
            collection=self.collection_name, query=query, skip=skip, limit=limit
        )

        result = []
        for document in documents:
            entity = await self.to_entity(document)
            result.append(entity)

        return result

    async def save(self, entity: T) -> Optional[ID]:
        """
        Сохраняет сущность в базу данных.

        Args:
            entity: Объект сущности

        Returns:
            ID сущности или None
        """
        document = await self.to_document(entity)

        # Если есть _id, обновляем документ
        if "_id" in document:
            document_id = document.pop("_id")
            await self.mongodb_service.update_one(
                collection=self.collection_name,
                query={"_id": document_id},
                update={"$set": {**document, "updated_at": datetime.now()}},
            )
            return document_id
        else:
            # Иначе создаем новый документ
            document["created_at"] = datetime.now()
            result = await self.mongodb_service.insert_one(
                collection=self.collection_name, document=document
            )
            return result

    async def delete_by_id(self, id: ID) -> bool:
        """
        Удаляет сущность по ID.

        Args:
            id: Идентификатор сущности

        Returns:
            True если удаление успешно, else False
        """
        result = await self.mongodb_service.delete_one(
            collection=self.collection_name,
            query={"_id": ObjectId(id) if isinstance(id, str) else id},
        )
        return result > 0

    async def count(self, query: Optional[Dict[str, Any]] = None) -> int:
        """
        Подсчитывает количество сущностей, соответствующих запросу.

        Args:
            query: Запрос MongoDB (если None, считает все документы)

        Returns:
            Количество сущностей
        """
        return await self.mongodb_service.count_documents(
            collection=self.collection_name, query=query or {}
        )

    async def exists_by_id(self, id: ID) -> bool:
        """
        Проверяет существование сущности по ID.

        Args:
            id: Идентификатор сущности

        Returns:
            True если сущность существует, else False
        """
        count = await self.mongodb_service.count_documents(
            collection=self.collection_name,
            query={"_id": ObjectId(id) if isinstance(id, str) else id},
            limit=1,
        )
        return count > 0

    async def aggregate(self, pipeline: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Выполняет агрегационный запрос.

        Args:
            pipeline: Агрегационный пайплайн MongoDB

        Returns:
            Результат агрегации
        """
        return await self.mongodb_service.aggregate(
            collection=self.collection_name, pipeline=pipeline
        )
