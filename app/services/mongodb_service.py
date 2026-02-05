import os
import re
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from bson.objectid import ObjectId

from ..settings.auth import get_mongodb
from ..settings.paths import DATA_DIR

# Настройка логирования
logger = logging.getLogger(__name__)

# Функция для сериализации данных из MongoDB
def serialize_mongodb_doc(doc):
    """
    Сериализует документ MongoDB, преобразуя ObjectId в строки.
    
    Args:
        doc: Документ или список документов MongoDB
        
    Returns:
        Сериализованный документ или список документов
    """
    if isinstance(doc, dict):
        # Преобразуем ObjectId в строки и рекурсивно обрабатываем словари
        result = {}
        for key, value in doc.items():
            if key == '_id' and isinstance(value, ObjectId):
                result['_id'] = str(value)
            elif isinstance(value, ObjectId):
                result[key] = str(value)
            elif isinstance(value, dict):
                result[key] = serialize_mongodb_doc(value)
            elif isinstance(value, list):
                result[key] = [serialize_mongodb_doc(item) for item in value]
            else:
                result[key] = value
        return result
    elif isinstance(doc, list):
        # Рекурсивно обрабатываем списки
        return [serialize_mongodb_doc(item) for item in doc]
    else:
        return doc

class MongoDBService:
    """Сервис для работы с MongoDB"""

    def __init__(self):
        """Инициализация сервиса MongoDB"""
        self.mongo_client = get_mongodb()
        self.db = self.mongo_client["medai"]

    async def insert_one(self, collection: str, document: Dict[str, Any]) -> Any:
        """
        Вставляет один документ в коллекцию.

        Args:
            collection: Имя коллекции
            document: Документ для вставки

        Returns:
            ID вставленного документа
        """
        try:
            result = await self.db[collection].insert_one(document)
            return result.inserted_id
        except Exception as e:
            logging.error(f"Ошибка при вставке документа в коллекцию {collection}: {str(e)}")
            import traceback
            logging.error(traceback.format_exc())
            return None
            
    async def find_one(self, collection: str, query: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Находит один документ в коллекции по запросу.

        Args:
            collection: Имя коллекции
            query: Запрос для поиска документа

        Returns:
            Найденный документ или None
        """
        try:
            doc = await self.db[collection].find_one(query)
            if doc:
                # Сериализуем документ перед возвратом
                return serialize_mongodb_doc(doc)
            return None
        except Exception as e:
            logging.error(f"Ошибка при поиске документа в коллекции {collection}: {str(e)}")
            import traceback
            logging.error(traceback.format_exc())
            return None
    
    async def aggregate(self, collection: str, pipeline: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Выполняет агрегационный запрос в коллекции.

        Args:
            collection: Имя коллекции
            pipeline: Агрегационный pipeline MongoDB

        Returns:
            Список результатов агрегации
        """
        try:
            results = []
            cursor = self.db[collection].aggregate(pipeline)
            async for document in cursor:
                results.append(document)
            return results
        except Exception as e:
            logging.error(f"Ошибка при выполнении агрегации в коллекции {collection}: {str(e)}")
            import traceback
            logging.error(traceback.format_exc())
            return []

    async def save_call_analysis(
        self,
        analysis_result: Dict[str, Any],
        transcription_filename: Optional[str] = None,
    ) -> str:
        """
        Сохраняет результаты анализа звонка в MongoDB

        :param analysis_result: Результат анализа звонка (из call_analysis_service)
        :param transcription_filename: Имя файла транскрипции (если есть)
        :return: ID записи в MongoDB
        """
        try:
            # Извлекаем метаданные
            meta_info = analysis_result.get("meta_info", {})
            note_id = meta_info.get("note_id")
            contact_id = meta_info.get("contact_id")
            lead_id = meta_info.get("lead_id")
            client_id = meta_info.get("client_id", "")

            # Проверяем, есть ли administrator_id в meta_info
            administrator_id = meta_info.get("administrator_id")
            administrator_name = meta_info.get(
                "administrator_name", "Неизвестный администратор"
            )

            # Если ID администратора не передан, пытаемся получить из анализа текста
            if not administrator_id:
                # Получаем имя администратора из анализа текста
                admin_name = self._extract_administrator_name(
                    analysis_result.get("analysis", "")
                )
                administrator_id = await self._get_or_create_administrator(admin_name)
                administrator_name = admin_name

            # Извлекаем телефон из имени файла транскрипции, если возможно
            phone = None
            if transcription_filename:
                phone_match = re.match(
                    r"^(\d+)_\d{8}_\d{6}\.txt$", transcription_filename
                )
                if phone_match:
                    phone = phone_match.group(1)

            # Получаем классификацию звонка
            call_classification = analysis_result.get("classification", "")

            # Получаем путь к файлу анализа
            analysis_filename = None
            if "output_filename" in analysis_result:
                analysis_filename = analysis_result.get("output_filename")

            # Извлекаем оценки и рекомендации из текста анализа
            analysis_text = analysis_result.get("analysis", "")
            parsed_data = self._parse_metrics_from_analysis(analysis_text)
            metrics = parsed_data.get("scores", {})
            recommendations = parsed_data.get("recommendations", {})

            # Формируем пути к файлам
            audio_filename = None
            if transcription_filename:
                base_name = os.path.splitext(transcription_filename)[0]
                audio_filename = f"{base_name}.mp3"

            # Получаем информацию о клинике из meta_info
            clinic_id = meta_info.get(
                "clinic_id", "818579a1-fc67-4a0f-a543-56f6eb828606"
            )

            # Определяем тип звонка (входящий/исходящий)
            call_direction = "incoming"  # По умолчанию считаем входящим

            # Вычисляем числовой код категории
            category_number = self._get_call_category_number(call_classification)

            if category_number in [2, 5, 6]:
                # Если это запись на прием, изменение/отмена или повторная консультация,
                # то с большей вероятностью это исходящий звонок
                call_direction = "outgoing"

            # Определяем конверсию на основе высокой удовлетворенности
            conversion = metrics.get("customer_satisfaction") == "high"

            # Формируем документ для MongoDB
            call_doc = {
                "note_id": note_id,
                "contact_id": contact_id,
                "lead_id": lead_id,
                "client_id": client_id,
                "clinic_id": clinic_id,
                "administrator_id": administrator_id,
                "administrator_name": administrator_name,
                "date": datetime.now().strftime("%Y-%m-%d"),
                "call_type": {
                    "direction": call_direction,
                    "category": category_number,
                    "category_name": call_classification,
                },
                "client": {
                    "phone": phone,
                    "source": "Unknown",  # Заглушка, следует получить из AmoCRM или другого источника
                },
                "metrics": metrics,
                "recommendations": recommendations,  # Добавляем рекомендации в документ
                "conversion": conversion,
                "files": {
                    "transcription": (
                        f"transcription/{transcription_filename}"
                        if transcription_filename
                        else None
                    ),
                    "analysis": (
                        f"analysis/{os.path.basename(analysis_filename)}"
                        if analysis_filename
                        else None
                    ),
                    "audio": f"audio/{audio_filename}" if audio_filename else None,
                },
                "links": {
                    "transcription": (
                        f"/api/transcriptions/{transcription_filename}/download"
                        if transcription_filename
                        else None
                    ),
                    "audio": (
                        f"/api/amocrm/contact/call/{note_id}/download?client_id={client_id}"
                        if note_id and client_id
                        else None
                    ),
                },
            }

            # Сохраняем в MongoDB
            result = await self.db.call_analytics.insert_one(call_doc)

            logger.info(
                f"Аналитика звонка сохранена в MongoDB с ID: {result.inserted_id}"
            )

            return str(result.inserted_id)

        except Exception as e:
            logger.error(f"Ошибка при сохранении аналитики звонка в MongoDB: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            # Возвращаем пустую строку в случае ошибки
            return ""
        finally:
            # Здесь можно добавить код для освобождения ресурсов
            # Например, закрытие файлов или других соединений, если они используются
            logger.debug("Завершение операции сохранения аналитики звонка")
            # В данном случае нет ресурсов, которые нужно явно освобождать,
            # так как MongoDB клиент управляется на уровне приложения

    async def find_many(self, collection: str, query: Dict[str, Any], limit: int = None) -> List[Dict[str, Any]]:
        """
        Находит документы в коллекции по запросу.

        Args:
            collection: Имя коллекции
            query: Запрос для поиска документов
            limit: Максимальное количество возвращаемых документов (если None - возвращает все документы)

        Returns:
            Список найденных документов
        """
        try:
            results = []
            if limit is not None:
                cursor = self.db[collection].find(query).limit(limit)
            else:
                cursor = self.db[collection].find(query)
            
            async for document in cursor:
                results.append(document)
            # Сериализуем результаты перед возвратом
            return serialize_mongodb_doc(results)
        except Exception as e:
            logging.error(f"Ошибка при поиске документов в коллекции {collection}: {str(e)}")
            import traceback
            logging.error(traceback.format_exc())
            return []

    async def update_one(self, collection: str, query: Dict[str, Any], update: Dict[str, Any]) -> int:
        """
        Обновляет один документ в коллекции.

        Args:
            collection: Имя коллекции
            query: Запрос для поиска документа
            update: Операции обновления документа

        Returns:
            Количество обновленных документов
        """
        try:
            result = await self.db[collection].update_one(query, update)
            return result.modified_count
        except Exception as e:
            logger.error(f"Ошибка при обновлении документа в коллекции {collection}: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return 0

    def _get_call_category_number(self, category_name: str) -> int:
        """
        Определяет числовой код категории звонка на основе текстового названия

        :param category_name: Текстовое название категории звонка
        :return: Числовой код категории
        """
        category_map = {
            "Первичное обращение (новый клиент)": 1,
            "Запись на приём": 2,
            "Запрос информации (цены, услуги и т.д.)": 3,
            "Проблема или жалоба": 4,
            "Изменение или отмена встречи": 5,
            "Повторная консультация": 6,
            "Запрос результатов анализов": 7,
            "Другое": 8,
        }

        # Сначала проверяем точное совпадение
        if category_name in category_map:
            return category_map[category_name]

        # Если точного совпадения нет, ищем частичное совпадение
        category_name_lower = category_name.lower()
        for key, value in category_map.items():
            if key.lower() in category_name_lower:
                return value

        # Если числовое значение (для обратной совместимости)
        try:
            if isinstance(category_name, str) and category_name.isdigit():
                category_number = int(category_name)
                if 1 <= category_number <= 8:
                    return category_number
        except (ValueError, TypeError):
            pass

        # По умолчанию возвращаем "Другое"
        return 8

    async def _get_or_create_administrator(self, admin_name: str) -> str:
        """
        Получает или создает запись администратора на основе имени

        :param admin_name: Имя администратора
        :return: ID администратора
        """
        if not admin_name or admin_name == "Неизвестный администратор":
            return "unknown_admin"

        # Нормализуем имя для использования в ID
        admin_id = f"admin_{re.sub(r'[^a-zA-Zа-яА-Я0-9]', '_', admin_name.lower())}"

        # Проверяем, существует ли администратор в базе
        admin = await self.db.administrators.find_one({"_id": admin_id})

        if not admin:
            # Создаем нового администратора
            admin_doc = {
                "_id": admin_id,
                "name": admin_name,
                "clinic_id": "818579a1-fc67-4a0f-a543-56f6eb828606",  # Заглушка
                "active": True,
                "created_at": datetime.now().isoformat(),
            }
            await self.db.administrators.insert_one(admin_doc)
            logger.info(f"Создан новый администратор: {admin_name} с ID: {admin_id}")

        return admin_id

    def _extract_administrator_name(self, analysis_text: str) -> str:
        """
        Извлекает имя администратора из текста анализа

        :param analysis_text: Текст анализа звонка
        :return: Имя администратора или "Неизвестный администратор"
        """
        # Поиск имени в строке "Менеджер (Имя)"
        manager_match = re.search(r"Менеджер\с*\(([^)]+)\)", analysis_text)
        if manager_match:
            return manager_match.group(1).strip()

        return "Неизвестный администратор"

    def _parse_metrics_from_analysis(self, analysis_text: str) -> Dict[str, Any]:
        """
        Парсит метрики и рекомендации из текста анализа

        :param analysis_text: Текст анализа звонка
        :return: Словарь с метриками и рекомендациями
        """
        metrics = {
            "greeting": 0,
            "patient_name": 0,  # Имя пациента
            "needs_identification": 0,
            "service_presentation": 0,  # Презентация услуги
            "clinic_presentation": 0,  # Презентация клиники
            "doctor_presentation": 0,  # Презентация врача
            "patient_booking": 0,  # Запись пациента
            "clinic_address": 0,  # Адрес клиники
            "passport": 0,  # Паспорт
            "price": 0,  # Цена "от"
            "expertise": 0,  # Экспертность
            "next_step": 0,  # Следующий шаг
            "appointment": 0,  # Запись на прием
            "emotional_tone": 0,  # Эмоциональный окрас
            "speech": 0,  # Речь
            "initiative": 0,  # Инициатива
            "solution_proposal": 0,
            "objection_handling": 0,
            "call_closing": 0,
            "tone": "neutral",
            "customer_satisfaction": "medium",
            "overall_score": 0,
            "conversion": False
        }

        # Словарь для рекомендаций по каждому этапу
        recommendations = {
            "greeting": "",
            "patient_name": "",
            "needs_identification": "",
            "service_presentation": "",
            "clinic_presentation": "",
            "doctor_presentation": "",
            "patient_booking": "",
            "clinic_address": "",
            "passport": "",
            "price": "",
            "expertise": "",
            "next_step": "",
            "appointment": "",
            "emotional_tone": "",
            "speech": "",
            "initiative": "",
            "solution_proposal": "",
            "objection_handling": "",
            "call_closing": "",
            "overall": "",
        }

        # Маппинг наименований из детального анализа к ключам в словаре
        detail_mapping = {
            "ПРИВЕТСТВИЕ": "greeting",
            "ИМЯ ПАЦИЕНТА": "patient_name",
            "ПОТРЕБНОСТЬ": "needs_identification",
            "ВЫЯВЛЕНИЕ ПОТРЕБНОСТЕЙ": "needs_identification",
            "ПРЕЗЕНТАЦИЯ УСЛУГИ": "service_presentation",
            "ПРЕЗЕНТАЦИЯ КЛИНИКИ": "clinic_presentation",
            "ПРЕЗЕНТАЦИЯ ВРАЧА": "doctor_presentation",
            "ЗАПИСЬ ПАЦИЕНТА": "patient_booking",
            "АДРЕС КЛИНИКИ": "clinic_address",
            "ПАСПОРТ": "passport",
            "ЦЕНА ОТ": "price",
            "ЭКСПЕРТНОСТЬ": "expertise",
            "СЛЕДУЮЩИЙ ШАГ": "next_step",
            "ЗАПИСЬ НА ПРИЕМ": "appointment",
            "ЭМОЦИОНАЛЬНЫЙ ОКРАС": "emotional_tone",
            "РЕЧЬ": "speech",
            "ИНИЦИАТИВА": "initiative",
            "ПРЕЗЕНТАЦИЯ": "service_presentation",
            "РАБОТА С ВОЗРАЖЕНИЯМИ": "objection_handling", 
            "ПРЕДЛОЖЕНИЕ РЕШЕНИЯ": "solution_proposal",
            "ЗАКРЫТИЕ ПРОДАЖИ": "call_closing",
            "ЗАВЕРШЕНИЕ РАЗГОВОРА": "call_closing",
            "ЗАВЕРШЕНИЕ ЗВОНКА": "call_closing",
            "ОБЩАЯ ОЦЕНКА": "overall_score",
        }

        # Маппинг для поиска в блоке "МЕТРИКИ ОЦЕНКИ ЗВОНКА"
        metrics_block_mapping = {
            "Приветствие": "greeting",
            "Имя пациента": "patient_name",
            "Потребность": "needs_identification",
            "Выявление потребностей": "needs_identification",
            "Презентация услуги": "service_presentation", 
            "Презентация клиники": "clinic_presentation",
            "Презентация врача": "doctor_presentation",
            "Запись пациента": "patient_booking",
            "Адрес клиники": "clinic_address",
            "Паспорт": "passport",
            "Цена \"от\"": "price",
            "Экспертность": "expertise",
            "Следующий шаг": "next_step",
            "Запись на прием": "appointment",
            "Эмоциональный окрас": "emotional_tone",
            "Речь": "speech",
            "Инициатива": "initiative",
            "Предложение решения": "solution_proposal",
            "Работа с возражениями": "objection_handling",
            "Завершение звонка": "call_closing",
            "Общая оценка": "overall_score"
        }

        # ПЕРВЫЙ ПРОХОД: ищем метрики в блоке "МЕТРИКИ ОЦЕНКИ ЗВОНКА"
        metrics_block = re.search(r"МЕТРИКИ\s+ОЦЕНКИ\s+ЗВОНКА:([\s\S]+?)(?:\n\s*\n|\Z)", analysis_text)
        if metrics_block:
            metrics_text = metrics_block.group(1).strip()
            # Ищем паттерны типа "Приветствие: 8/10"
            pattern = r"([^:]+):\s*(\d+)/10"
            matches = re.findall(pattern, metrics_text)
            
            for match in matches:
                metric_name = match[0].strip()
                try:
                    score = int(match[1])
                    # Проверяем, есть ли метрика в маппинге
                    if metric_name in metrics_block_mapping:
                        metric_key = metrics_block_mapping[metric_name]
                        metrics[metric_key] = score
                        logging.debug(f"Из блока метрик: {metric_name} -> {metric_key}: {score}")
                except (ValueError, KeyError) as e:
                    logging.warning(f"Ошибка при парсинге метрики из блока {metric_name}: {e}")

        # ВТОРОЙ ПРОХОД: ищем оценки в детальном анализе
        # Паттерны для поиска в различных форматах
        patterns = [
            # Формат: ### 1. ПРИВЕТСТВИЕ (0-10 баллов) \n **Оценка: 8/10**
            r"#+\s*\d*\.*\s*([A-ZА-Я\s]+)[\s\(\)0-9баловбаллов\-]*\n.*?\*\*Оценка:?\s*(\d+)/10\*\*",
            
            # Формат: ### ПРИВЕТСТВИЕ (0-10 баллов) \n **Оценка: 8/10**
            r"#+\s*([A-ZА-Я\s]+)[\s\(\)0-9баловбаллов\-]*\n.*?\*\*Оценка:?\s*(\d+)/10\*\*",
            
            # Формат: ### ПРИВЕТСТВИЕ \n **Оценка**: 8/10
            r"#+\s*([A-ZА-Я\s]+).*?\n.*?\*\*Оценка\*\*:?\s*(\d+)/10",
            
            # Формат: **ПРИВЕТСТВИЕ (8/10)**
            r"\*\*([A-ZА-Я\s]+)\s*\((\d+)/10\)\*\*",
            
            # Формат: **ПРИВЕТСТВИЕ** - **Оценка**: 8/10
            r"\*\*([A-ZА-Я\s]+)\*\*.*?\*\*Оценка\*\*:?\s*(\d+)/10",
            
            # Формат: ПРИВЕТСТВИЕ (8/10)
            r"([A-ZА-Я\s]+)\s*\((\d+)/10\)",
            
            # Формат: ПРИВЕТСТВИЕ: 8/10
            r"([A-ZА-Я\s]+):\s*(\d+)/10"
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, analysis_text, re.DOTALL)
            for match in matches:
                category = match[0].strip().upper()
                try:
                    score = int(match[1])
                    # Проверяем, соответствует ли категория какому-либо ключу в маппинге
                    for key, value in detail_mapping.items():
                        if category in key or key in category:
                            metrics[value] = score
                            logging.debug(f"Из детального анализа: {category} -> {value}: {score}")
                            break
                except (ValueError, IndexError) as e:
                    logging.warning(f"Ошибка при парсинге оценки из детального анализа {category}: {e}")

        # Парсим тональность разговора
        if "позитивн" in analysis_text.lower() or "позитивная" in analysis_text.lower():
            metrics["tone"] = "positive"
        elif "негативн" in analysis_text.lower() or "негативная" in analysis_text.lower():
            metrics["tone"] = "negative"
        else:
            metrics["tone"] = "neutral"

        # Парсим удовлетворенность клиента
        if "высок" in analysis_text.lower() and "удовлетворенность" in analysis_text.lower():
            metrics["customer_satisfaction"] = "high"
        elif "низк" in analysis_text.lower() and "удовлетворенность" in analysis_text.lower():
            metrics["customer_satisfaction"] = "low"
        else:
            metrics["customer_satisfaction"] = "medium"

        # Парсим конверсию
        if "КОНВЕРСИЯ: Да" in analysis_text or "Конверсия: Да" in analysis_text:
            metrics["conversion"] = True
        else:
            metrics["conversion"] = False

        # Извлекаем рекомендации для разделов из блока "РЕКОМЕНДАЦИИ ПО УЛУЧШЕНИЮ"
        recommendations_block = re.search(r"РЕКОМЕНДАЦИИ[^:]*:([\s\S]+?)(?:\n\s*\n|\Z)", analysis_text, re.IGNORECASE)
        if recommendations_block:
            rec_text = recommendations_block.group(1).strip()
            # Извлекаем каждую рекомендацию (в формате 1. Текст рекомендации)
            rec_pattern = r"\d+\.\s+([^\n]+)"
            rec_matches = re.findall(rec_pattern, rec_text, re.MULTILINE)
            # Сохраняем все рекомендации в поле "overall"
            recommendations["overall"] = "\n".join(rec_matches)

        # Возвращаем словарь с метриками и рекомендациями
        return {"scores": metrics, "recommendations": recommendations}

    async def get_call_analytics(
        self,
        start_date: str,
        end_date: str,
        clinic_id: Optional[str] = None,
        administrator_ids: Optional[List[str]] = None,
        analysis_exists: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Получает аналитику звонков за указанный период

        :param start_date: Начальная дата в формате YYYY-MM-DD
        :param end_date: Конечная дата в формате YYYY-MM-DD
        :param clinic_id: ID клиники (опционально)
        :param administrator_ids: Список ID администраторов (опционально)
        :param analysis_exists: Требовать наличие поля analysis (опционально)
        :return: Список звонков с аналитикой
        """
        try:
            # Формируем запрос к MongoDB
            query = {"date": {"$gte": start_date, "$lte": end_date}}

            if clinic_id:
                query["clinic_id"] = clinic_id

            if administrator_ids:
                query["administrator_id"] = {"$in": administrator_ids}
                
            # Добавляем фильтр по наличию поля analysis, если требуется
            if analysis_exists:
                query["analysis"] = {"$exists": True}
                
            # Получаем данные из MongoDB
            analytics = await self.db.call_analytics.find(query).to_list(length=None)
            
            # Если требуется фильтрация по наличию анализа, выводим дополнительную информацию
            if analysis_exists:
                logger.info(f"Найдено {len(analytics)} звонков с анализом в call_analytics за период {start_date} - {end_date}")

            return analytics
        except Exception as e:
            logger.error(f"Ошибка при получении аналитики звонков: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            return []

    async def calculate_call_metrics(
        self,
        start_date: str,
        end_date: str,
        clinic_id: Optional[str] = None,
        administrator_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Рассчитывает метрики звонков за указанный период

        :param start_date: Начальная дата в формате YYYY-MM-DD
        :param end_date: Конечная дата в формате YYYY-MM-DD
        :param clinic_id: ID клиники (опционально)
        :param administrator_ids: Список ID администраторов (опционально)
        :return: Словарь с метриками
        """
        try:
            # Получаем данные звонков за период
            calls = await self.get_call_analytics(
                start_date, end_date, clinic_id, administrator_ids
            )

            if not calls:
                return {
                    "total_calls": 0,
                    "incoming_calls": 0,
                    "outgoing_calls": 0,
                    "conversion_rate": 0,
                    "avg_score": 0,
                    "administrators": [],
                    "call_types": {},
                    "traffic_sources": {},
                }

            # Общие метрики
            total_calls = len(calls)
            incoming_calls = sum(
                1
                for call in calls
                if call.get("call_type", {}).get("direction") == "incoming"
            )
            outgoing_calls = total_calls - incoming_calls
            conversion_count = sum(1 for call in calls if call.get("conversion", False))
            conversion_rate = (
                (conversion_count / total_calls) * 100 if total_calls > 0 else 0
            )

            # Средняя оценка
            all_scores = [
                call.get("metrics", {}).get("overall_score", 0) for call in calls
            ]
            avg_score = sum(all_scores) / len(all_scores) if all_scores else 0

            # Группировка по администраторам
            admins_data = {}
            for call in calls:
                admin_id = call.get("administrator_id", "unknown_admin")
                admin_name = call.get("administrator_name", "Неизвестный администратор")

                if admin_id not in admins_data:
                    admins_data[admin_id] = {
                        "id": admin_id,
                        "name": admin_name,
                        "total_calls": 0,
                        "incoming_calls": 0,
                        "outgoing_calls": 0,
                        "conversions": 0,
                        "incoming_conversions": 0,
                        "outgoing_conversions": 0,
                        "scores": [],
                    }

                admins_data[admin_id]["total_calls"] += 1
                admins_data[admin_id]["scores"].append(
                    call.get("metrics", {}).get("overall_score", 0)
                )

                if call.get("call_type", {}).get("direction") == "incoming":
                    admins_data[admin_id]["incoming_calls"] += 1
                    if call.get("conversion", False):
                        admins_data[admin_id]["incoming_conversions"] += 1
                else:
                    admins_data[admin_id]["outgoing_calls"] += 1
                    if call.get("conversion", False):
                        admins_data[admin_id]["outgoing_conversions"] += 1

                if call.get("conversion", False):
                    admins_data[admin_id]["conversions"] += 1

            # Формируем финальный список администраторов с метриками
            administrators = []
            for admin_id, admin_data in admins_data.items():
                avg_admin_score = (
                    sum(admin_data["scores"]) / len(admin_data["scores"])
                    if admin_data["scores"]
                    else 0
                )

                incoming_conversion = 0
                if admin_data["incoming_calls"] > 0:
                    incoming_conversion = (
                        admin_data["incoming_conversions"]
                        / admin_data["incoming_calls"]
                    ) * 100

                outgoing_conversion = 0
                if admin_data["outgoing_calls"] > 0:
                    outgoing_conversion = (
                        admin_data["outgoing_conversions"]
                        / admin_data["outgoing_calls"]
                    ) * 100

                overall_conversion = 0
                if admin_data["total_calls"] > 0:
                    overall_conversion = (
                        admin_data["conversions"] / admin_data["total_calls"]
                    ) * 100

                administrators.append(
                    {
                        "id": admin_id,
                        "name": admin_data["name"],
                        "total_calls": admin_data["total_calls"],
                        "incoming_calls": admin_data["incoming_calls"],
                        "outgoing_calls": admin_data["outgoing_calls"],
                        "incoming_conversion": round(incoming_conversion, 1),
                        "outgoing_conversion": round(outgoing_conversion, 1),
                        "overall_conversion": round(overall_conversion, 1),
                        "avg_score": round(avg_admin_score, 1),
                    }
                )

            # Сортируем по количеству звонков (сначала больше)
            administrators.sort(key=lambda x: x["total_calls"], reverse=True)

            # Группировка по типам звонков
            call_types = {}
            for call in calls:
                category = call.get("call_type", {}).get("category", 8)
                category_name = call.get("call_type", {}).get(
                    "category_name", "Неизвестно"
                )

                if category not in call_types:
                    call_types[category] = {
                        "name": category_name,
                        "count": 0,
                        "conversion_count": 0,
                    }

                call_types[category]["count"] += 1
                if call.get("conversion", False):
                    call_types[category]["conversion_count"] += 1

            # Рассчитываем конверсию для каждого типа звонка
            for category, data in call_types.items():
                if data["count"] > 0:
                    data["conversion_rate"] = (
                        data["conversion_count"] / data["count"]
                    ) * 100
                else:
                    data["conversion_rate"] = 0

            # Группировка по источникам трафика
            traffic_sources = {}
            for call in calls:
                source = call.get("client", {}).get("source", "Unknown")

                if source not in traffic_sources:
                    traffic_sources[source] = {"count": 0, "conversion_count": 0}

                traffic_sources[source]["count"] += 1
                if call.get("conversion", False):
                    traffic_sources[source]["conversion_count"] += 1

            # Рассчитываем конверсию для каждого источника трафика
            for source, data in traffic_sources.items():
                if data["count"] > 0:
                    data["conversion_rate"] = (
                        data["conversion_count"] / data["count"]
                    ) * 100
                else:
                    data["conversion_rate"] = 0

            # Формируем итоговый результат
            result = {
                "total_calls": total_calls,
                "incoming_calls": incoming_calls,
                "outgoing_calls": outgoing_calls,
                "conversion_count": conversion_count,
                "conversion_rate": round(conversion_rate, 1),
                "avg_score": round(avg_score, 1),
                "administrators": administrators,
                "call_types": call_types,
                "traffic_sources": traffic_sources,
            }

            return result
        except Exception as e:
            logger.error(f"Ошибка при расчете метрик звонков: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            return {
                "total_calls": 0,
                "incoming_calls": 0,
                "outgoing_calls": 0,
                "conversion_rate": 0,
                "avg_score": 0,
                "administrators": [],
                "call_types": {},
                "traffic_sources": {},
            }

    
# Создаем экземпляр для использования в API
mongodb_service = MongoDBService()

"""
Базовый сервис для работы с MongoDB.
Предоставляет абстракцию для взаимодействия с базой данных.
"""
from typing import Any, Dict, List, Optional, TypeVar, Generic, Union
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from bson import ObjectId
from datetime import datetime
import logging
from abc import ABC, abstractmethod

from app.settings.config import get_settings
from app.utils.logging import ContextLogger

# Создаем типизированные переменные для обобщения
T = TypeVar("T")
ID = TypeVar("ID")

# Получаем настройки
settings = get_settings()
logger = ContextLogger("mongodb")


class MongoDBClient:
    """
    Синглтон-клиент для подключения к MongoDB.
    Обеспечивает единую точку доступа к базе данных.
    """

    _instance = None
    _client = None
    _db = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MongoDBClient, cls).__new__(cls)
            try:
                # Инициализация клиента MongoDB
                cls._client = AsyncIOMotorClient(
                    settings.DATABASE.URI,
                    minPoolSize=settings.DATABASE.MIN_CONNECTIONS_COUNT,
                    maxPoolSize=settings.DATABASE.MAX_CONNECTIONS_COUNT,
                    serverSelectionTimeoutMS=settings.DATABASE.TIMEOUT_MS,
                )
                cls._db = cls._client[settings.DATABASE.NAME]
                logger.info(
                    f"MongoDB клиент успешно инициализирован для БД {settings.DATABASE.NAME}"
                )
            except Exception as e:
                logger.critical(f"Ошибка подключения к MongoDB: {str(e)}")
                raise
        return cls._instance

    @property
    def client(self) -> AsyncIOMotorClient:
        """Возвращает клиент MongoDB."""
        return self._client

    @property
    def db(self) -> AsyncIOMotorDatabase:
        """Возвращает объект базы данных."""
        return self._db

    async def close(self) -> None:
        """Закрывает соединение с MongoDB."""
        if self._client:
            self._client.close()
            logger.info("MongoDB соединение закрыто")


class BaseRepository(Generic[T, ID], ABC):
    """
    Абстрактный базовый репозиторий для работы с MongoDB.
    Использует паттерн Repository для абстрагирования работы с данными.
    """

    def __init__(self, collection_name: str):
        """
        Инициализирует репозиторий.

        Args:
            collection_name: Имя коллекции в MongoDB
        """
        self._mongo_client = MongoDBClient()
        self._collection = self._mongo_client.db[collection_name]
        self._collection_name = collection_name

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
            Документ для MongoDB
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
        try:
            # Преобразуем строковый ID в ObjectId, если это строка
            document_id = ObjectId(id) if isinstance(id, str) else id
            document = await self._collection.find_one({"_id": document_id})

            if document:
                return await self.to_entity(document)
            return None
        except Exception as e:
            logger.error(
                f"Ошибка поиска по ID {id} в коллекции {self._collection_name}: {str(e)}"
            )
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
        try:
            cursor = self._collection.find().limit(limit).skip(skip)
            documents = await cursor.to_list(length=limit)

            result = []
            for document in documents:
                entity = await self.to_entity(document)
                result.append(entity)

            return result
        except Exception as e:
            logger.error(
                f"Ошибка получения всех документов из коллекции {self._collection_name}: {str(e)}"
            )
            return []

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
        try:
            cursor = self._collection.find(query).limit(limit).skip(skip)
            documents = await cursor.to_list(length=limit)

            result = []
            for document in documents:
                entity = await self.to_entity(document)
                result.append(entity)

            return result
        except Exception as e:
            logger.error(
                f"Ошибка поиска по запросу в коллекции {self._collection_name}: {str(e)}"
            )
            return []

    async def save(self, entity: T) -> Optional[ID]:
        """
        Сохраняет сущность в базу данных.

        Args:
            entity: Объект сущности

        Returns:
            ID сущности или None
        """
        try:
            document = await self.to_document(entity)

            # Если есть _id, обновляем документ
            if "_id" in document:
                result = await self._collection.replace_one(
                    {"_id": document["_id"]}, document
                )
                return document["_id"] if result.modified_count > 0 else None
            else:
                # Иначе создаем новый документ
                document["created_at"] = datetime.now()
                result = await self._collection.insert_one(document)
                return result.inserted_id
        except Exception as e:
            logger.error(
                f"Ошибка сохранения сущности в коллекцию {self._collection_name}: {str(e)}"
            )
            return None

    async def delete_by_id(self, id: ID) -> bool:
        """
        Удаляет сущность по ID.

        Args:
            id: Идентификатор сущности

        Returns:
            True если удаление успешно, иначе False
        """
        try:
            # Преобразуем строковый ID в ObjectId, если это строка
            document_id = ObjectId(id) if isinstance(id, str) else id
            result = await self._collection.delete_one({"_id": document_id})
            return result.deleted_count > 0
        except Exception as e:
            logger.error(
                f"Ошибка удаления по ID {id} из коллекции {self._collection_name}: {str(e)}"
            )
            return False

    async def count(self, query: Optional[Dict[str, Any]] = None) -> int:
        """
        Подсчитывает количество сущностей, соответствующих запросу.

        Args:
            query: Запрос MongoDB (если None, считает все документы)

        Returns:
            Количество сущностей
        """
        try:
            return await self._collection.count_documents(query or {})
        except Exception as e:
            logger.error(
                f"Ошибка подсчета документов в коллекции {self._collection_name}: {str(e)}"
            )
            return 0

    async def exists_by_id(self, id: ID) -> bool:
        """
        Проверяет существование сущности по ID.

        Args:
            id: Идентификатор сущности

        Returns:
            True если сущность существует, иначе False
        """
        try:
            # Преобразуем строковый ID в ObjectId, если это строка
            document_id = ObjectId(id) if isinstance(id, str) else id
            count = await self._collection.count_documents(
                {"_id": document_id}, limit=1
            )
            return count > 0
        except Exception as e:
            logger.error(
                f"Ошибка проверки существования по ID {id} в коллекции {self._collection_name}: {str(e)}"
            )
            return False

    async def aggregate(self, pipeline: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Выполняет агрегационный запрос.

        Args:
            pipeline: Агрегационный пайплайн MongoDB

        Returns:
            Результат агрегации
        """
        try:
            cursor = self._collection.aggregate(pipeline)
            return await cursor.to_list(length=None)
        except Exception as e:
            logger.error(
                f"Ошибка выполнения агрегации в коллекции {self._collection_name}: {str(e)}"
            )
            return []

    async def bulk_write(self, operations: List[Any]) -> bool:
        """
        Выполняет массовую запись операций.

        Args:
            operations: Список операций MongoDB

        Returns:
            True если операция успешна, иначе False
        """
        try:
            result = await self._collection.bulk_write(operations)
            return result.acknowledged
        except Exception as e:
            logger.error(
                f"Ошибка массовой записи в коллекцию {self._collection_name}: {str(e)}"
            )
            return False


# Создаем клиент MongoDB для использования в приложении
mongodb_client = MongoDBClient()
