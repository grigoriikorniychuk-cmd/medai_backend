"""
Сервис для анализа звонков.
Оптимизированная версия, основанная на test_save.py с использованием промпта из test_prompt.txt.
"""

import os
import re
import json
import logging
import asyncio
from typing import Dict, Any, List, Optional, Union
from datetime import datetime

from langchain_openai import ChatOpenAI

# Импортируем пути из настроек
from app.settings.paths import DATA_DIR, ANALYSIS_DIR, TRANSCRIPTION_DIR, DB_NAME

from app.settings.auth import get_langchain_token, get_mongodb
from app.models.call_analysis import (
    CallAnalysisModel,
    CallTypeInfo,
    ClientInfo,
    CallMetrics,
    CallAnalysisRequest,
    CallAnalysisResponse,
    CallDirectionEnum,
    CallCategoryEnum,
    ToneEnum,
    SatisfactionEnum,
)
from app.repositories.call_analysis_repository import CallAnalysisRepository
from app.services.mongodb_service import MongoDBService
from app.exceptions.base_exceptions import FileNotFoundError, AnalysisError
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser

# Настройка логирования
from app.utils.logging import ContextLogger

logger = ContextLogger("call_analysis_service")

# Словарь уменьшительных имён → полные формы
_DIMINUTIVE_MAP = {
    "юля": "юлия", "юлечка": "юлия",
    "настя": "анастасия", "настенька": "анастасия",
    "лена": "елена", "леночка": "елена",
    "лиза": "елизавета",
    "катя": "екатерина", "катюша": "екатерина",
    "саша": "александра", "шура": "александра",
    "женя": "евгения",
    "валя": "валентина",
    "лера": "валерия",
    "маша": "мария", "машенька": "мария",
    "даша": "дарья",
    "наташа": "наталья",
    "алёна": "елена",
    "люба": "любовь",
    "надя": "надежда",
    "аня": "анна", "анечка": "анна",
    "таня": "татьяна",
    "юра": "юрий",
    "миша": "михаил",
    "вика": "виктория",
    "оля": "ольга",
    "ира": "ирина",
    "света": "светлана",
    "галя": "галина",
    "люда": "людмила",
    "лариса": "лариса",
    "алиса": "алиса",
}


def _match_diminutive_name(ai_name: str, valid_names: set) -> Optional[str]:
    """
    Сопоставляет уменьшительное имя от AI с полным именем из графика.
    Возвращает полное имя из valid_names или None.
    """
    ai_lower = ai_name.strip().lower()

    for valid in valid_names:
        # Прямое совпадение без учёта регистра
        if ai_lower == valid.strip().lower():
            return valid

    # Ищем через словарь уменьшительных
    full_form = _DIMINUTIVE_MAP.get(ai_lower)
    if full_form:
        for valid in valid_names:
            if valid.strip().lower() == full_form:
                return valid

    return None


class CallAnalysisService:
    """
    Сервис для анализа звонков и сохранения результатов в базу данных.
    Оптимизированная версия с использованием структурированного JSON-вывода.
    """

    def __init__(
        self,
        call_analysis_repository: Optional[CallAnalysisRepository] = None,
        mongodb_service: Optional[MongoDBService] = None,
    ):
        """
        Инициализирует сервис анализа звонков.

        Args:
            call_analysis_repository: Репозиторий для работы с данными анализа звонков
            mongodb_service: Сервис MongoDB для прямого доступа к базе данных
        """
        self.call_analysis_repository = call_analysis_repository or CallAnalysisRepository(MongoDBService())
        self.mongodb_service = mongodb_service or MongoDBService()
        # self.efficiency_service = CallEfficiencyService()  # Temporarily disabled
        self.llm = get_langchain_token()

        # Отдельная модель для определения администратора (gpt-5-mini лучше справляется)
        self.admin_llm = ChatOpenAI(
            model_name="gpt-5-mini",
            temperature=1,  # gpt-5-mini поддерживает только temperature=1
            openai_api_key=os.getenv("OPENAI"),
        )

        # Создаем директории для данных
        os.makedirs(ANALYSIS_DIR, exist_ok=True)
        os.makedirs(TRANSCRIPTION_DIR, exist_ok=True)

        # Директория с промптами для разных типов звонков
        self.prompts_dir = os.path.join("app", "data", "prompts")

        # Загружаем промпт для классификации звонков
        self.classification_prompt_template = self._load_classification_prompt()

        # Кэш для промптов разных типов звонков
        self.prompt_templates_cache = {}

    def _load_classification_prompt(self) -> str:
        """
        Загружает шаблон промпта для классификации типа звонка.

        Returns:
            Шаблон промпта для классификации
        """
        try:
            prompt_path = os.path.join(self.prompts_dir, "classification_call.txt")
            if os.path.exists(prompt_path):
                with open(prompt_path, 'r', encoding='utf-8') as file:
                    logger.info(f"Загружен промпт классификации из файла {prompt_path}")
                    return file.read()
            else:
                logger.error(f"Файл промпта классификации не найден: {prompt_path}")
                raise FileNotFoundError(f"Файл промпта классификации не найден: {prompt_path}")
        except Exception as e:
            logger.error(f"Ошибка при загрузке промпта классификации: {str(e)}")
            raise

    def _load_prompt_for_call_type(self, call_type: str) -> str:
        """
        Загружает промпт для конкретного типа звонка.

        Args:
            call_type: Тип звонка (первичка, вторичка, перезвон, подтверждение, другое)

        Returns:
            Шаблон промпта для данного типа звонка
        """
        # Если промпт уже есть в кэше, возвращаем его
        if call_type in self.prompt_templates_cache:
            return self.prompt_templates_cache[call_type]

        try:
            # Маппинг типов звонков на файлы промптов
            type_to_file = {
                "первичка": "initial_call.txt",
                "вторичка": "secondary_call.txt",
                "перезвон": "re_call.txt",
                "подтверждение": "confirmation_call.txt",
                "другое": "other_call.txt"
            }

            filename = type_to_file.get(call_type, "other_call.txt")
            prompt_path = os.path.join(self.prompts_dir, filename)

            if os.path.exists(prompt_path):
                with open(prompt_path, 'r', encoding='utf-8') as file:
                    prompt_template = file.read()
                    # Кэшируем промпт
                    self.prompt_templates_cache[call_type] = prompt_template
                    logger.info(f"Загружен промпт для типа '{call_type}' из файла {prompt_path}")
                    return prompt_template
            else:
                logger.warning(f"Файл промпта для типа '{call_type}' не найден: {prompt_path}")
                # Используем промпт "другое" по умолчанию
                return self._load_prompt_for_call_type("другое")
        except Exception as e:
            logger.error(f"Ошибка при загрузке промпта для типа '{call_type}': {str(e)}")
            raise

    def load_transcription(self, file_path: str) -> str:
        """
        Загружает транскрипцию звонка из файла.

        Args:
            file_path: Путь к файлу транскрипции

        Returns:
            Текст транскрипции

        Raises:
            FileNotFoundError: Если файл не найден
        """
        try:
            with open(file_path, "r", encoding="utf-8") as file:
                return file.read().strip()
        except FileNotFoundError:
            logger.error(f"Файл транскрипции не найден: {file_path}")
            raise FileNotFoundError(f"Файл транскрипции не найден: {file_path}")
        except Exception as e:
            logger.error(f"Ошибка при чтении файла транскрипции: {str(e)}")
            raise

    async def classify_call(self, dialogue: str) -> str:
        """
        Классифицирует тип звонка.

        Args:
            dialogue: Текст диалога для классификации

        Returns:
            Тип звонка (первичка, вторичка, перезвон, подтверждение, другое)

        Raises:
            AnalysisError: Если произошла ошибка при классификации
        """
        try:
            logger.info("Начало классификации звонка...")

            # Создаем промпт из шаблона
            prompt = PromptTemplate.from_template(self.classification_prompt_template)

            # Устанавливаем цепочку обработки
            chain = prompt | self.llm | StrOutputParser()

            # Выполняем классификацию
            logger.info("Выполняется вызов модели для классификации...")
            output = chain.invoke({"transcription": dialogue})
            logger.info("Ответ от модели получен, обработка результатов...")

            # Извлекаем JSON из ответа
            json_match = re.search(r'```json\s*(.*?)\s*```', output, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group(1))
            else:
                result = json.loads(output)

            call_type = result.get("call_type", "другое")
            logger.info(f"Звонок классифицирован как: {call_type}")
            return call_type

        except Exception as e:
            logger.error(f"Ошибка при классификации звонка: {str(e)}")
            # В случае ошибки классификации используем тип "другое"
            return "другое"

    async def analyze_call(self, dialogue: str, appointment_booking: bool = False) -> Dict[str, Any]:
        """
        Выполняет анализ звонка, используя промпт для определенного типа звонка.

        Args:
            dialogue: Текст диалога для анализа
            appointment_booking: Была ли запись (из AmoCRM)

        Returns:
            Словарь с результатами анализа звонка

        Raises:
            AnalysisError: Если произошла ошибка при анализе
        """
        try:
            logger.info("Начало анализа звонка...")

            # Шаг 1: Классифицируем тип звонка
            call_type = await self.classify_call(dialogue)
            logger.info(f"Тип звонка определен: {call_type}")

            # Шаг 2: Загружаем промпт для этого типа звонка
            prompt_template = self._load_prompt_for_call_type(call_type)

            # Создаем промпт из шаблона
            prompt = PromptTemplate.from_template(prompt_template)

            # Устанавливаем цепочку обработки
            chain = prompt | self.llm | StrOutputParser()

            # Выполняем анализ
            logger.info("Выполняется вызов модели для анализа...")
            appointment_booking_str = "true" if appointment_booking else "false"
            output = chain.invoke({
                "transcription": dialogue,
                "appointment_booking": appointment_booking_str
            })
            logger.info("Ответ от модели получен, обработка результатов...")

            # Обрабатываем результат
            try:
                # Пытаемся извлечь JSON из ответа
                json_match = re.search(r'```json\s*(.*?)\s*```', output, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group(1))
                    logger.debug("JSON извлечен из блока кода")
                else:
                    result = json.loads(output)
                    logger.debug("JSON извлечен напрямую из ответа")

                # Определение категории звонка на основе анализа
                # По умолчанию - запись на прием (наиболее частый сценарий)
                call_category = CallCategoryEnum.APPOINTMENT
                category_name = "Запись на приём"

                # Определяем направление звонка (по умолчанию - входящий)
                direction = CallDirectionEnum.INCOMING

                # Получаем классификацию звонка из ответа LLM
                call_type_classification = result.get("call_type", call_type)

                # Формируем metrics и comments динамически на основе полученных данных
                metrics = {}
                comments = {}

                # Извлекаем все критерии с их оценками из результата
                for key, value in result.items():
                    if isinstance(value, dict) and "score" in value and "comment" in value:
                        metrics[key] = value["score"]
                        comments[key] = value["comment"]

                # Добавляем служебные поля
                metrics["tone"] = result.get("tone", "neutral")
                metrics["customer_satisfaction"] = result.get("customer_satisfaction", "medium")
                metrics["overall_score"] = result.get("overall_score", 0.0)
                metrics["call_type_classification"] = call_type_classification

                # Формируем структурированный результат анализа
                analysis_result = {
                    "call_type": {
                        "category": call_category,
                        "category_name": category_name,
                        "direction": direction,
                        "classification": call_type_classification
                    },
                    "metrics": metrics,
                    "comments": comments,
                    "recommendations": result.get("recommendations", []),
                    "analysis_text": self._generate_analysis_text(result, call_type_classification),
                    "transcription_text": dialogue,
                    # ❌ УБРАЛИ "conversion" - конверсия определяется ТОЛЬКО через AmoCRM!
                    "timestamp": datetime.now()
                }

                logger.info(f"Анализ звонка завершен успешно. Общая оценка: {result['overall_score']}")
                return analysis_result
                
            except json.JSONDecodeError as e:
                logger.error(f"Ошибка при разборе JSON: {str(e)}")
                logger.debug(f"Полученный ответ: {output[:500]}...")
                raise AnalysisError(f"Ошибка при разборе JSON-ответа от модели: {str(e)}")
                
        except Exception as e:
            logger.error(f"Ошибка при анализе звонка: {str(e)}", exc_info=True)
            raise AnalysisError(f"Ошибка при анализе звонка: {str(e)}")

    def _generate_analysis_text(self, result: Dict[str, Any], call_type: str = "первичка") -> str:
        """
        Генерирует текстовое представление анализа из структурированных данных.

        Args:
            result: Словарь с результатами анализа
            call_type: Тип звонка для адаптации форматирования

        Returns:
            Текстовое представление анализа
        """
        analysis_text = f"# АНАЛИЗ ЗВОНКА ({call_type.upper()})\n\n"

        criteria_titles = {
            "greeting": "ПРИВЕТСТВИЕ",
            "patient_name": "ИМЯ ПАЦИЕНТА",
            "needs_identification": "ВЫЯВЛЕНИЕ ПОТРЕБНОСТЕЙ",
            "service_presentation": "ПРЕЗЕНТАЦИЯ УСЛУГИ",
            "clinic_presentation": "ПРЕЗЕНТАЦИЯ КЛИНИКИ",
            "doctor_presentation": "ПРЕЗЕНТАЦИЯ ВРАЧА",
            "appointment": "ЗАПИСЬ",
            "price": "ЦЕНА",
            "expertise": "ЭКСПЕРТНОСТЬ",
            "next_step": "СЛЕДУЮЩИЙ ШАГ",
            "appointment_booking": "ЗАПИСЬ НА ПРИЕМ",
            "emotional_tone": "ЭМОЦИОНАЛЬНЫЙ ОКРАС",
            "speech": "РЕЧЬ",
            "initiative": "ИНИЦИАТИВА",
            "clinic_address": "АДРЕС КЛИНИКИ",
            "passport": "ПАСПОРТ",
            "objection_handling": "РАБОТА С ВОЗРАЖЕНИЯМИ",
            "appeal": "АПЕЛЛЯЦИЯ",
            "question_clarification": "УТОЧНЕНИЕ ВОПРОСА"
        }

        # Добавляем секции для каждой метрики, которая есть в результате
        for key, value in result.items():
            if isinstance(value, dict) and "score" in value and "comment" in value:
                title = criteria_titles.get(key, key.upper())
                score = value["score"]
                comment = value["comment"]
                analysis_text += f"### {title} (0-10 баллов)\n"
                analysis_text += f"**Оценка: {score}/10**\n\n"
                analysis_text += f"{comment}\n\n"

        # Добавляем классификацию звонка
        call_type_classification = result.get("call_type", call_type)
        analysis_text += f"### КЛАССИФИКАЦИЯ ЗВОНКА\n"
        analysis_text += f"**Тип: {call_type_classification}**\n\n"

        # Добавляем тональность и удовлетворенность с локализацией
        tone_map = {
            "positive": "Позитивная",
            "neutral": "Нейтральная",
            "negative": "Негативная"
        }
        tone = tone_map.get(result.get("tone", "neutral"), "Нейтральная")
        analysis_text += f"### ОЦЕНКА ТОНАЛЬНОСТИ РАЗГОВОРА\n"
        analysis_text += f"**Оценка: {tone}**\n\n"

        satisfaction_map = {
            "high": "Высокая",
            "medium": "Средняя",
            "low": "Низкая"
        }
        satisfaction = satisfaction_map.get(result.get("customer_satisfaction", "medium"), "Средняя")
        analysis_text += f"### ОЦЕНКА УДОВЛЕТВОРЕННОСТИ КЛИЕНТА\n"
        analysis_text += f"**Оценка: {satisfaction}**\n\n"

        # Добавляем общую оценку
        analysis_text += f"### ОБЩАЯ ОЦЕНКА (0-10 баллов)\n"
        analysis_text += f"**Оценка: {result.get('overall_score', 0.0)}/10**\n\n"

        # ❌ УБРАЛИ секцию "КОНВЕРСИЯ" - конверсия определяется ТОЛЬКО через AmoCRM!

        # Добавляем рекомендации
        analysis_text += "### РЕКОМЕНДАЦИИ\n\n"
        recommendations = result.get("recommendations", [])
        for i, rec in enumerate(recommendations, 1):
            analysis_text += f"{i}. {rec}\n"

        return analysis_text

    async def save_to_mongodb(self, analysis_result: Dict[str, Any], meta_info: Optional[Dict[str, Any]] = None) -> str:
        """
        Сохраняет результат анализа в MongoDB.

        Args:
            analysis_result: Результаты анализа звонка
            meta_info: Дополнительная метаинформация о звонке

        Returns:
            ID сохраненного документа
        """
        try:
            logger.info("Сохранение результатов анализа в MongoDB...")
            
            # Получаем клиент MongoDB
            client = get_mongodb()
            
            # Выбор базы данных и коллекции
            db = client[DB_NAME]
            collection = db['call_analysis']
            
            # Подготовка документа для сохранения
            document = {
                "timestamp": datetime.now(),
                "source_file": meta_info.get("source_file") if meta_info else None,
                "meta_info": meta_info or {},
                "call_type": analysis_result["call_type"],
                "metrics": analysis_result["metrics"],
                "comments": analysis_result["comments"],
                "recommendations": analysis_result["recommendations"],
                "analysis_text": analysis_result["analysis_text"],
                "transcription_text": analysis_result["transcription_text"],
                "overall_score": analysis_result["metrics"]["overall_score"],
                # ❌ УБРАЛИ "conversion" - конверсия определяется ТОЛЬКО через AmoCRM!
                "tone": analysis_result["metrics"]["tone"],
                "customer_satisfaction": analysis_result["metrics"]["customer_satisfaction"],
                "call_type_classification": analysis_result["metrics"].get("call_type_classification", "первичка"),
                # Поля эффективности (ТЗ) - новая структура
                "efficiency": analysis_result.get("efficiency", {}),
                # Для обратной совместимости (устаревшие поля)
                "is_effective": analysis_result.get("efficiency", {}).get("is_effective"),
                "matched_criteria": analysis_result.get("efficiency", {}).get("matched_criteria", [])
            }
            
            # Вставка документа в коллекцию (асинхронная операция)
            result = await collection.insert_one(document)
            document_id = str(result.inserted_id)
            
            logger.info(f"Результаты анализа сохранены в MongoDB с ID: {document_id}")
            return document_id
        except Exception as e:
            logger.error(f"Ошибка при сохранении в MongoDB: {str(e)}")
            raise

    def save_analysis_to_file(self, analysis_result: Dict[str, Any], filename: Optional[str] = None) -> str:
        """
        Сохраняет результат анализа звонка в текстовый файл.

        Args:
            analysis_result: Результат анализа звонка
            filename: Имя файла (опционально)

        Returns:
            Путь к сохраненному файлу
        """
        try:
            # Создаем директорию, если она не существует
            os.makedirs(ANALYSIS_DIR, exist_ok=True)
            
            # Определяем имя файла
            if not filename:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"analysis_{timestamp}.txt"

            # Формируем полный путь к файлу
            file_path = os.path.join(ANALYSIS_DIR, filename)
            
            # Сохраняем анализ в файл
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(analysis_result["analysis_text"])
            
            logger.info(f"Результат анализа сохранен в файл: {file_path}")
            return file_path
        except Exception as e:
            logger.error(f"Ошибка при сохранении результата анализа в файл: {str(e)}")
            raise

    async def create_call_analysis(self, request: CallAnalysisRequest) -> CallAnalysisResponse:
        """
        Создает полный анализ звонка на основе запроса.

        Args:
            request: Запрос на анализ звонка

        Returns:
            Ответ с результатами анализа
        """
        try:
            logger.info("Начало обработки запроса на анализ звонка")

            # Проверяем наличие текста транскрипции или имени файла
            if not request.transcription_text and not request.transcription_filename:
                logger.error("Отсутствует текст транскрипции и имя файла")
                return CallAnalysisResponse(
                    success=False,
                    message="Необходимо предоставить текст транскрипции или имя файла",
                )

            # Если передан только файл, загружаем из него текст
            dialogue = request.transcription_text
            transcription_path = None
            if not dialogue and request.transcription_filename:
                try:
                    transcription_path = os.path.join(
                        TRANSCRIPTION_DIR, request.transcription_filename
                    )
                    dialogue = self.load_transcription(transcription_path)
                except Exception as e:
                    logger.error(f"Ошибка при загрузке транскрипции: {str(e)}")
                    return CallAnalysisResponse(
                        success=False,
                        message=f"Ошибка при загрузке транскрипции: {str(e)}",
                    )

            # Формируем метаданные
            meta_info = request.meta_info or {}
            if request.note_id:
                meta_info["note_id"] = request.note_id
            if request.contact_id:
                meta_info["contact_id"] = request.contact_id
            if request.lead_id:
                meta_info["lead_id"] = request.lead_id
            if transcription_path:
                meta_info["source_file"] = transcription_path

            # Выполняем анализ звонка
            conversion = request.conversion or False
            analysis_result = await self.analyze_call(dialogue, appointment_booking=conversion)
            
            # === ФИЛЬТРАЦИЯ "ДРУГОЕ" (ТЗ: Исключить из статистики) ===
            # Если тип звонка определен как "другое", мы НЕ сохраняем его в базу для аналитики
            call_type_lower = analysis_result["call_type"]["classification"].lower()
            if call_type_lower in ["другое", "other", "undefined"]:
                logger.warning(f"Звонок классифицирован как '{call_type_lower}'. Пропуск сохранения в БД (фильтрация мусора).")
                
                # Мы все равно возвращаем ответ, чтобы клиент знал, что анализ прошел,
                # но помечаем его как ignored/skipped в самом ответе, если нужно,
                # или просто возвращаем результат без ID документа (или с фейковым).
                # Но лучше просто вернуть успешный ответ без сохранения.
                
                return CallAnalysisResponse(
                    success=True,
                    message="Звонок классифицирован как 'Другое' и исключен из сохранения.",
                    data={
                        "id": "skipped_other",
                        "call_type": "Другое",
                        "direction": analysis_result["call_type"]["direction"],
                        "overall_score": 0,
                        "recommendations": []
                    }
                )
            
            # === РАСЧЁТ ЭФФЕКТИВНОСТИ (ТЗ) - ПЕРЕД СОХРАНЕНИЕМ ===
            client_id = meta_info.get("client_id") or meta_info.get("clinic_id") or request.clinic_id
            
            # Получаем настройки эффективности из клиники
            clinic_efficiency_settings = None
            if client_id:
                try:
                    from app.services.clinic_service import clinic_service
                    clinic_data = await clinic_service.get_clinic_by_id(str(client_id))
                    if clinic_data:
                        clinic_efficiency_settings = clinic_data.get("efficiency_settings")
                        logger.info(f"Загружены настройки эффективности для клиники {client_id}")
                except Exception as e:
                    logger.warning(f"Не удалось загрузить настройки эффективности для клиники {client_id}: {e}")

            # Рассчитываем эффективность
            from app.utils.effectiveness_calculator import calculate_call_effectiveness
            effectiveness_result = calculate_call_effectiveness(
                metrics=analysis_result["metrics"],
                call_type=analysis_result["call_type"]["classification"],
                clinic_settings=clinic_efficiency_settings
            )
            
            # Добавляем efficiency в analysis_result ДО сохранения
            analysis_result["efficiency"] = {
                "is_effective": effectiveness_result["is_effective"],
                "matched_criteria": effectiveness_result["matched_criteria"],
                "effectiveness_label": effectiveness_result["effectiveness_label"],
                "average_score": effectiveness_result["average_score"]
            }
            
            logger.info(
                f"Эффективность: {effectiveness_result['effectiveness_label']}, "
                f"Средний балл: {effectiveness_result['average_score']}, "
                f"Критерии: {effectiveness_result['matched_criteria']}"
            )

            # Сохраняем результат в MongoDB (теперь с полем efficiency)
            document_id = await self.save_to_mongodb(analysis_result, meta_info)
            
            # Сохраняем анализ в файл
            analysis_filename = None
            if request.transcription_filename:
                base_name = os.path.splitext(request.transcription_filename)[0]
                analysis_filename = f"{base_name}_analysis.txt"
            
            file_path = self.save_analysis_to_file(analysis_result, analysis_filename)
            
            # Формируем ответ
            response_data = {
                "id": document_id,
                "file_path": file_path,
                "call_type": analysis_result["call_type"]["category_name"],
                "direction": analysis_result["call_type"]["direction"],
                "overall_score": analysis_result["metrics"]["overall_score"],
                "recommendations": analysis_result["recommendations"],
                # Поля эффективности
                "is_effective": effectiveness_result["is_effective"],
                "matched_criteria": effectiveness_result["matched_criteria"],
                "effectiveness_label": effectiveness_result["effectiveness_label"],
                "average_score": effectiveness_result["average_score"]
            }
            
            # === СИНХРОНИЗАЦИЯ С КОЛЛЕКЦИЕЙ CALLS (для DataLens) ===
            if request.note_id:
                try:
                    from app.settings.paths import DB_NAME
                    db = get_mongodb()[DB_NAME]
                    
                    # Обновляем документ звонка с данными эффективности
                    await db['calls'].update_one(
                        {"_id": request.note_id},
                        {
                            "$set": {
                                "efficiency": analysis_result.get("efficiency", {}),
                                "analysis_synced_at": datetime.now()
                            }
                        }
                    )
                    logger.info(f"Данные эффективности синхронизированы с коллекцией calls для note_id={request.note_id}")
                except Exception as e:
                    logger.error(f"Ошибка синхронизации с коллекцией calls: {e}")

            # Добавляем в ответ категории с высокими оценками (сильные стороны)
            strong_categories = []
            metrics_data = [(key, value) for key, value in analysis_result["metrics"].items() 
                           if isinstance(value, (int, float)) and key not in ["overall_score"]]
            
            # Сортируем метрики по убыванию оценки
            metrics_data.sort(key=lambda x: x[1], reverse=True)
            
            # Получаем топ-3 метрики с оценкой выше 7
            for key, score in metrics_data[:3]:
                if score >= 7:
                    # Получаем русское название метрики
                    category_name = {
                        'greeting': 'Приветствие',
                        'patient_name': 'Имя пациента',
                        'needs_identification': 'Выявление потребности',
                        'service_presentation': 'Презентация услуги',
                        'clinic_presentation': 'Презентация клиники',
                        'doctor_presentation': 'Презентация врача',
                        'patient_booking': 'Запись пациента',
                        'clinic_address': 'Адрес клиники',
                        'passport': 'Паспорт',
                        'price': 'Цена "от"',
                        'expertise': 'Экспертность',
                        'next_step': 'Следующий шаг',
                        'appointment': 'Запись на прием',
                        'emotional_tone': 'Эмоциональный окрас',
                        'speech': 'Речь',
                        'initiative': 'Инициатива'
                    }.get(key, key)
                    
                    strong_categories.append({"name": category_name, "score": score})
            
            response_data["strong_categories"] = strong_categories
            
            return CallAnalysisResponse(
                success=True,
                message="Анализ звонка успешно создан",
                data=response_data,
            )
        except Exception as e:
            logger.error(f"Ошибка при создании анализа звонка: {str(e)}", exc_info=True)
            return CallAnalysisResponse(
                success=False,
                message=f"Ошибка при создании анализа звонка: {str(e)}"
            )

    async def get_call_analysis_by_id(self, analysis_id: str) -> Optional[CallAnalysisModel]:
        """
        Получает анализ звонка по ID.

        Args:
            analysis_id: Идентификатор анализа звонка

        Returns:
            Модель анализа звонка или None
        """
        return await self.call_analysis_repository.find_by_id(analysis_id)

    async def get_call_analysis_by_note_id(self, note_id: int) -> Optional[CallAnalysisModel]:
        """
        Получает анализ звонка по ID заметки AmoCRM.

        Args:
            note_id: Идентификатор заметки AmoCRM

        Returns:
            Модель анализа звонка или None
        """
        return await self.call_analysis_repository.find_by_note_id(note_id)

    async def extract_administrator_name(
        self, 
        transcription_text: str,
        administrators_list: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        """
        Извлекает имя и фамилию администратора из транскрипции звонка.
        
        Использует промпт ADMIN_NAME_EXTRACTION для определения сотрудника клиники.
        ПРАВИЛЬНЫЙ ПОДХОД: передаём список администраторов из графика, AI сам выбирает нужного.
        
        Args:
            transcription_text: Текст транскрипции звонка
            administrators_list: Список администраторов из графика в формате
                [{"first_name": "Ольга", "last_name": "Левина"}, ...]
            
        Returns:
            Dict с полями:
                - first_name: str | None
                - last_name: str | None  
                - confidence: float (0.0 - 1.0)
        """
        try:
            from app.prompts.templates import DEFAULT_PROMPT_TEMPLATES, PromptType
            
            # Получаем промпт для извлечения имени админа
            prompt_template = DEFAULT_PROMPT_TEMPLATES[PromptType.ADMIN_NAME_EXTRACTION]
            
            # Форматируем список администраторов для промпта
            if administrators_list:
                admins_formatted = "\n".join([
                    f"- {admin['first_name']} {admin['last_name']}" 
                    for admin in administrators_list
                ])
            else:
                admins_formatted = "(список не предоставлен - режим свободного извлечения)"
            
            # Форматируем промпт с транскрипцией и списком админов
            prompt_text = prompt_template.template.format(
                transcription=transcription_text,
                administrators_list=admins_formatted
            )
            
            logger.info(f"Определение администратора из {len(administrators_list) if administrators_list else 0} вариантов...")
            
            # Вызываем LLM (gpt-5-mini для лучшего определения администратора)
            response = await self.admin_llm.ainvoke(prompt_text)
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            logger.debug(f"Ответ LLM для извлечения имени: {response_text}")
            
            # Парсим JSON из ответа
            # Убираем возможные markdown блоки ```json ... ```
            cleaned_response = re.sub(r'```json\s*|\s*```', '', response_text).strip()
            
            result = json.loads(cleaned_response)

            first_name = result.get('first_name')
            last_name = result.get('last_name')
            confidence = result.get('confidence', 0.0)

            # === КРИТИЧЕСКАЯ ВАЛИДАЦИЯ ===
            # Проверяем что AI вернул имя которое ЕСТЬ в списке администраторов
            if first_name and administrators_list:
                # Формируем множество валидных имён
                valid_first_names = {admin['first_name'] for admin in administrators_list}

                if first_name not in valid_first_names:
                    # Пробуем сопоставить уменьшительное имя с полным
                    matched = _match_diminutive_name(first_name, valid_first_names)
                    if matched:
                        logger.info(
                            f"Сопоставлено уменьшительное имя: '{first_name}' → '{matched}'"
                        )
                        first_name = matched
                        result['first_name'] = matched
                    else:
                        logger.warning(
                            f"⚠️ AI вернул имя '{first_name}' которого НЕТ в графике! "
                            f"Валидные имена: {valid_first_names}. Заменяем на null."
                        )
                        return {"first_name": None, "last_name": None, "confidence": 0.0}

                # Если AI вернул имя без фамилии — подставляем фамилию из графика
                # (берём первого администратора с таким именем)
                if not last_name:
                    matching = [a for a in administrators_list if a['first_name'] == first_name]
                    if matching:
                        last_name = matching[0]['last_name']
                        result['last_name'] = last_name
                        logger.info(
                            f"AI вернул '{first_name}' без фамилии — "
                            f"подставлена фамилия из графика: {last_name}"
                        )

            logger.info(
                f"Определён администратор: {first_name} "
                f"{last_name} (confidence: {confidence})"
            )

            return result
            
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON из ответа LLM: {e}. Ответ: {response_text}")
            return {"first_name": None, "last_name": None, "confidence": 0.0}
        except Exception as e:
            logger.error(f"Ошибка при извлечении имени администратора: {e}")
            return {"first_name": None, "last_name": None, "confidence": 0.0}


# Создаем экземпляр для использования в API
mongodb_service = MongoDBService()
call_analysis_repository = CallAnalysisRepository(mongodb_service)
call_analysis_service = CallAnalysisService(call_analysis_repository, mongodb_service) 