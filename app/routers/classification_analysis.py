import asyncio
import json
import logging
import os
import httpx
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from langchain_core.messages import HumanMessage
from app.settings.auth import get_langchain_token, get_mongodb
from app.settings.paths import DB_NAME
from bson.objectid import ObjectId
from app.routers.calls import convert_date_string # Добавлено
from app.services.recommendation_analysis_service import RecommendationAnalysisService
from app.models.call_analysis import CallScoresResponse, CriterionScore

router = APIRouter(tags=["Classification Call Analysis"])
logger = logging.getLogger(__name__)

# Загрузка промптов
CLASSIFICATION_TEMPLATE = Path('app/data/prompts/classification_call.txt').read_text()
ANALYSIS_TEMPLATES = {
    1: Path('app/data/prompts/initial_call.txt').read_text(),
    2: Path('app/data/prompts/secondary_call.txt').read_text(),
    3: Path('app/data/prompts/re_call.txt').read_text(),
    4: Path('app/data/prompts/confirmation_call.txt').read_text(),
    5: Path('app/data/prompts/other_call.txt').read_text()
}

# Инициализация ChatGPT
llm = get_langchain_token()

async def wait_for_transcription_file(transcription_path: Path, max_wait_seconds: int = 60) -> bool:
    """
    Ожидает появления файла транскрипции с повторными попытками.
    Возвращает True если файл найден, False если превышено время ожидания.
    """
    wait_interval = 5  # секунд между проверками
    attempts = max_wait_seconds // wait_interval
    
    for attempt in range(attempts):
        if transcription_path.exists() and transcription_path.stat().st_size > 0:
            logger.info(f"Файл транскрипции найден: {transcription_path}")
            return True
        
        if attempt < attempts - 1:  # не ждем после последней попытки
            logger.info(f"Файл транскрипции еще не готов, ожидание {wait_interval}с... (попытка {attempt + 1}/{attempts})")
            await asyncio.sleep(wait_interval)
    
    logger.warning(f"Файл транскрипции не найден после {max_wait_seconds}с ожидания: {transcription_path}")
    return False

@router.post("/api/call/analyze-call-new/{call_id}")
async def analyze_call_type(call_id: str) -> Dict[str, Any]:
    
    """Анализ типа звонка и его метрик"""
    try:
        
        # Подключение к MongoDB
        client = get_mongodb()
        db = client[DB_NAME]
        
        # Получение данных звонка
        call = await db.calls.find_one({"_id": ObjectId(call_id)})
        if not call:
            raise HTTPException(status_code=404, detail="Call not found")

        # ВАЖНО: Сохраняем конверсию из AmoCRM (НЕ перезаписываем AI-анализом!)
        amocrm_conversion = call.get("metrics", {}).get("conversion")
        amocrm_conversion_type = call.get("conversion_type")
        amocrm_duration = call.get("metrics", {}).get("duration")
        logger.info(f"💾 [Preserve AmoCRM Data] conversion={amocrm_conversion}, type={amocrm_conversion_type}, duration={amocrm_duration}")

        # Получение транскрипции с ожиданием готовности файла
        transcription_path = Path('app/data/transcription') / call['filename_transcription']
        
        # Ожидаем готовности файла транскрипции до 60 секунд
        if not await wait_for_transcription_file(transcription_path, max_wait_seconds=60):
            raise HTTPException(status_code=404, detail="Transcription file not found")
            
        transcription = transcription_path.read_text(encoding='utf-8')
        
        # Инициализация ChatGPT
        llm = get_langchain_token()
        
        # Определение типа звонка
        classification_message = HumanMessage(content=CLASSIFICATION_TEMPLATE.format(transcription=transcription))
        call_type_response = llm.invoke([classification_message])
        try:
            # Очищаем ответ от markdown-форматирования
            content = call_type_response.content
            if '```json' in content:
                content = content.split('```json')[1].split('```')[0].strip()
            elif '```' in content:
                content = content.split('```')[1].split('```')[0].strip()
                
            call_type = json.loads(content)
            logger.info(f"Определен тип звонка: {call_type}")
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга ответа классификации: {call_type_response.content}")
            raise HTTPException(status_code=500, detail="Ошибка анализа типа звонка")
        
        # Анализ звонка на основе его типа
        template = ANALYSIS_TEMPLATES[call_type['call_type_id']]
        # ВАЖНО: Передаем conversion в промпт для правильного расчета overall_score
        patient_booking_value = "true" if amocrm_conversion else "false"
        analysis_message = HumanMessage(content=template.format(
            transcription=transcription,
            patient_booking=patient_booking_value
        ))
        analysis_response = llm.invoke([analysis_message])
        try:
            # Очищаем ответ от markdown-форматирования
            content = analysis_response.content
            if '```json' in content:
                content = content.split('```json')[1].split('```')[0].strip()
            elif '```' in content:
                content = content.split('```')[1].split('```')[0].strip()
                
            analysis_results = json.loads(content)
            logger.info(f"Получены результаты анализа")
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга результатов анализа: {analysis_response.content}")
            raise HTTPException(status_code=500, detail="Ошибка анализа звонка")
        
        # Преобразуем результаты в нужный формат
        metrics = {}
        recommendations = []
        
        # Добавляем метрики
        for key, data in analysis_results.items():
            if isinstance(data, dict) and 'score' in data:
                metrics[key] = data['score']
            elif key == 'recommendations':
                recommendations = data
            elif key == 'overall_score':
                # overall_score - это float, а не dict
                metrics[key] = data

        # Для типа "другое" может не быть overall_score - добавляем 0
        if 'overall_score' not in metrics:
            metrics['overall_score'] = 0.0
            logger.info(f"Тип звонка '{call_type['call_type']}' не имеет overall_score - установлено 0.0")

        # ВАЖНО: Бинарные критерии должны быть строго 0 или 10
        # AI иногда игнорирует инструкцию и ставит промежуточные оценки
        binary_criteria = ['appointment', 'patient_booking', 'clinic_address', 'passport']
        for criterion in binary_criteria:
            if criterion in metrics:
                # Округляем: < 5 -> 0, >= 5 -> 10
                original_value = metrics[criterion]
                metrics[criterion] = 10 if original_value >= 5 else 0
                if original_value not in [0, 10]:
                    logger.warning(f"🔧 [Binary Fix] {criterion}: {original_value} -> {metrics[criterion]}")

        # ВАЖНО: patient_booking ВСЕГДА берем из AmoCRM conversion, НЕ от AI!
        if amocrm_conversion is not None:
            metrics['patient_booking'] = 10 if amocrm_conversion else 0
            logger.info(f"✅ [Override patient_booking] AmoCRM conversion={amocrm_conversion} -> patient_booking={metrics['patient_booking']}")

        # ВАЖНО: Восстанавливаем конверсию из AmoCRM (НЕ из AI!)
        if amocrm_conversion is not None:
            metrics['conversion'] = amocrm_conversion
            logger.info(f"✅ [Restore AmoCRM Conversion] metrics.conversion={amocrm_conversion}")

        # Восстанавливаем duration
        if amocrm_duration is not None:
            metrics['duration'] = amocrm_duration

        # Добавляем тип звонка
        metrics['call_type_classification'] = call_type['call_type']
        
        # Создаем имя файла анализа
        analysis_filename = f"{call['phone']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_analysis.txt"
        analysis_path = f"/app/app/data/analysis/{analysis_filename}"
        
        # Словарь перевода метрик для записи в файл анализа
        metrics_translation = {
            'greeting': 'ПРИВЕТСТВИЕ',
            'patient_name': 'ИМЯ ПАЦИЕНТА',
            'needs_identification': 'ВЫЯВЛЕНИЕ ПОТРЕБНОСТЕЙ',
            'service_presentation': 'ПРЕЗЕНТАЦИЯ УСЛУГ',
            'clinic_presentation': 'ПРЕЗЕНТАЦИЯ КЛИНИКИ',
            'doctor_presentation': 'ПРЕЗЕНТАЦИЯ ВРАЧА',
            'patient_booking': 'ЗАПИСЬ ПАЦИЕНТА',
            'clinic_address': 'АДРЕС КЛИНИКИ',
            'passport': 'ПАСПОРТ',
            'price': 'ЦЕНА',
            'expertise': 'ЭКСПЕРТНОСТЬ',
            'next_step': 'СЛЕДУЮЩИЙ ШАГ',
            'appointment': 'ЗАПИСЬ',
            'emotional_tone': 'ЭМОЦИОНАЛЬНЫЙ ТОН',
            'speech': 'РЕЧЬ',
            'initiative': 'ИНИЦИАТИВНОСТЬ'
        }
        
        # Создаем детальный отчет для файла
        analysis_content = []
        analysis_content.append(f"# Анализ звонка {call['phone']}\n\n")
        
        # Добавляем метаданные
        analysis_content.append("## МЕТАДАННЫЕ\n")
        analysis_content.append(f"Дата и время анализа: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        analysis_content.append(f"Клиника: {call.get('subdomain', 'Не указана')}\n")
        analysis_content.append(f"Администратор: {call.get('administrator', 'Не указан')}\n")
        analysis_content.append(f"Контакт: {call.get('contact_name', 'Не указан')}\n")
        analysis_content.append(f"Note ID: {call.get('note_id', 'Не указан')}\n")
        analysis_content.append(f"Contact ID: {call.get('contact_id', 'Не указан')}\n")
        analysis_content.append(f"Lead ID: {call.get('lead_id', 'Не указан')}\n\n")
        
        analysis_content.append(f"## Тип звонка: {call_type['call_type']}\n")
        analysis_content.append(f"Объяснение: {call_type['explanation']}\n")
        
        # Добавляем метрики
        for key, data in analysis_results.items():
            if isinstance(data, dict) and 'score' in data:
                metric_name = metrics_translation.get(key, key.upper())
                analysis_content.append(f"\n### {metric_name} (0-10 баллов)\n")
                analysis_content.append(f"**Оценка: {data['score']}/10**\n")
                analysis_content.append(f"Комментарий: {data['comment']}\n")
        
        # Добавляем общие показатели
        analysis_content.append(f"\n## Общие показатели\n")

        # Для типа "другое" нет overall_score (технические/неинформативные звонки)
        if 'overall_score' in analysis_results:
            analysis_content.append(f"* Общая оценка: {analysis_results['overall_score']:.2f}\n")
        else:
            # Для типа "другое" ставим 0 или пропускаем
            logger.info(f"Тип звонка '{call_type['call_type']}' не имеет overall_score - пропускаем")
            analysis_content.append(f"* Общая оценка: Не применимо (тип '{call_type['call_type']}')\n")

        # Конверсия берется из AmoCRM, а НЕ из AI анализа
        analysis_content.append(f"* Конверсия (из AmoCRM): {'Да' if amocrm_conversion else 'Нет'}\n")

        # Добавляем рекомендации (если есть)
        if 'recommendations' in analysis_results and analysis_results['recommendations']:
            analysis_content.append(f"\n## Рекомендации\n")
            for rec in analysis_results['recommendations']:
                analysis_content.append(f"* {rec}\n")
        else:
            logger.info(f"Тип звонка '{call_type['call_type']}' не имеет рекомендаций")
        
        # Сохраняем в файл
        with open(analysis_path, 'w', encoding='utf-8') as f:
            f.writelines(analysis_content)
        
        # Сохранение результатов в MongoDB
        update_data = {
            "metrics": metrics,
            "recommendations": recommendations,
            "analysis_id": analysis_filename,
            "analyzed_at": datetime.now(),
            "call_type_id": call_type['call_type_id'],
            "call_type_name": call_type['call_type'],
            "analyze_status": "success"
        }

        # ВАЖНО: Сохраняем conversion_type из AmoCRM (если есть)
        if amocrm_conversion_type:
            update_data["conversion_type"] = amocrm_conversion_type
            logger.info(f"✅ [Restore AmoCRM] conversion_type={amocrm_conversion_type}")

        await db.calls.update_one(
            {"_id": ObjectId(call_id)},
            {"$set": update_data}
        )
        logger.info(f"💾 [Save to DB] call_id={call_id}, metrics.conversion={metrics.get('conversion')}, conversion_type={update_data.get('conversion_type')}")

        return {
            "success": True,
            "call_id": call_id,
            "call_type": call_type,
            "analysis_results": analysis_results
        }
        
    except json.JSONDecodeError as e:
        logger.error(f"JSON parsing error: {str(e)}")
        raise HTTPException(status_code=500, detail="Error parsing AI response")
        
    except Exception as e:
        logger.error(f"Error processing call analysis: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/analyze-by-date-range", summary="Массовый анализ звонков за диапазон дат")
async def analyze_calls_by_date_range(
    background_tasks: BackgroundTasks,
    start_date_str: str = Query(..., description="Начальная дата (DD.MM.YYYY или YYYY-MM-DD)"),
    end_date_str: str = Query(..., description="Конечная дата (DD.MM.YYYY или YYYY-MM-DD)"),
    client_id: Optional[str] = Query(None, description="ID клиента для фильтрации звонков (если применимо)"),
    force_analyze: bool = Query(False, description="Принудительно анализировать звонки, даже если они уже были проанализированы")
) -> Dict[str, Any]:
    """
    Запускает массовый анализ звонков из MongoDB за указанный диапазон дат.
    Звонки отбираются по дате создания (`created_date_for_filtering`), наличию транскрипции 
    и, опционально, по `client_id`.
    Если `force_analyze`=False, уже проанализированные звонки (имеющие `analysis_id`) пропускаются.
    Задачи на анализ добавляются в фон.
    """
    logger.info(
        f"Запрос на массовый анализ: {start_date_str} - {end_date_str}, client_id: {client_id}, "
        f"force_analyze: {force_analyze}"
    )

    start_time_global = datetime.now()

    start_date_obj = convert_date_string(start_date_str)
    end_date_obj = convert_date_string(end_date_str)

    if not start_date_obj or not end_date_obj:
        raise HTTPException(status_code=400, detail="Неверный формат даты. Используйте DD.MM.YYYY или YYYY-MM-DD.")

    if start_date_obj > end_date_obj:
        raise HTTPException(status_code=400, detail="Начальная дата не может быть позже конечной даты.")

    # Формируем строки для фильтрации по полю "created_date_for_filtering"
    start_date_filter_str = start_date_obj.strftime("%Y-%m-%d")
    end_date_filter_str = end_date_obj.strftime("%Y-%m-%d")
    
    mongo_query = {
        "created_date_for_filtering": {"$gte": start_date_filter_str, "$lte": end_date_filter_str},
        "filename_transcription": {"$exists": True, "$ne": None, "$ne": ""} 
    }

    if client_id:
        mongo_query["client_id"] = client_id

    if not force_analyze:
        mongo_query["$or"] = [
            {"analysis_id": {"$exists": False}},
            {"analysis_id": None},
            {"analysis_id": ""}
        ]
        
    mongo_client = get_mongodb()
    db = mongo_client[DB_NAME]
    
    # Запрашиваем только _id для оптимизации
    calls_to_analyze_cursor = db.calls.find(mongo_query, {"_id": 1})
    calls_to_analyze_list = await calls_to_analyze_cursor.to_list(length=None) 

    if not calls_to_analyze_list:
        logger.info("Не найдено звонков для анализа по указанным критериям.")
        return {
            "message": "Не найдено звонков для анализа.",
            "total_found": 0,
            "tasks_queued": 0,
            "duration_seconds": (datetime.now() - start_time_global).total_seconds()
        }

    logger.info(f"Найдено {len(calls_to_analyze_list)} звонков для запуска анализа.")

    tasks_queued_count = 0
    
    for call_doc in calls_to_analyze_list:
        call_id_str = str(call_doc["_id"])
        try:
            logger.info(f"Добавление задачи на анализ для call_id: {call_id_str}")
            # Используем существующую функцию analyze_call_type для анализа
            background_tasks.add_task(analyze_call_type, call_id=call_id_str)
            tasks_queued_count += 1
        except Exception as e:
            logger.error(f"Ошибка при постановке задачи на анализ для call_id {call_id_str}: {e}")

    duration = (datetime.now() - start_time_global).total_seconds()
    logger.info(f"Массовый анализ: {tasks_queued_count} задач добавлено в фон. Длительность постановки: {duration:.2f} сек.")

    return {
        "message": f"{tasks_queued_count} задач на анализ успешно добавлено в фоновый режим.",
        "total_found": len(calls_to_analyze_list),
        "tasks_queued": tasks_queued_count,
        "duration_seconds": duration
    }


@router.get("/api/analyze-by-date-range-status")
async def get_analysis_status_by_date_range(
    start_date_str: str = Query(..., description="Начальная дата (DD.MM.YYYY или YYYY-MM-DD)"),
    end_date_str: str = Query(..., description="Конечная дата (DD.MM.YYYY или YYYY-MM-DD)"),
    client_id: Optional[str] = Query(None, description="ID клиента для фильтрации звонков")
) -> Dict[str, Any]:
    """
    Получить статус анализа звонков за указанный период для проверки завершения процесса.
    """
    try:
        start_date_obj = convert_date_string(start_date_str)
        end_date_obj = convert_date_string(end_date_str)

        if not start_date_obj or not end_date_obj:
            raise HTTPException(status_code=400, detail="Неверный формат даты. Используйте DD.MM.YYYY или YYYY-MM-DD.")

        # Формируем строки для фильтрации
        start_date_filter_str = start_date_obj.strftime("%Y-%m-%d")
        end_date_filter_str = end_date_obj.strftime("%Y-%m-%d")
        
        query = {
            "created_date_for_filtering": {"$gte": start_date_filter_str, "$lte": end_date_filter_str},
            "filename_transcription": {"$exists": True, "$ne": None, "$ne": ""} 
        }

        if client_id:
            query["client_id"] = client_id

        mongo_client = get_mongodb()
        db = mongo_client[DB_NAME]
        
        # Получаем звонки с транскрипциями за период
        calls_cursor = db.calls.find(query)
        calls = await calls_cursor.to_list(length=None)
        
        # Подсчитываем статистику по статусам анализа
        total_calls = len(calls)
        processing_count = 0
        success_count = 0
        failed_count = 0
        pending_count = 0

        for call in calls:
            analyze_status = call.get("analyze_status", "pending")
            if analyze_status == "processing":
                processing_count += 1
            elif analyze_status == "success":
                success_count += 1
            elif analyze_status == "failed":
                failed_count += 1
            else:
                pending_count += 1

        # Определяем общий статус процесса
        if processing_count > 0:
            overall_status = "processing"
        elif pending_count > 0:
            overall_status = "pending"
        elif total_calls == success_count:
            overall_status = "completed"
        else:
            overall_status = "partial"

        return {
            "overall_status": overall_status,
            "total_calls": total_calls,
            "status_breakdown": {
                "pending": pending_count,
                "processing": processing_count,
                "success": success_count,
                "failed": failed_count
            },
            "progress_percentage": round((success_count / total_calls * 100), 2) if total_calls > 0 else 0
        }

    except Exception as e:
        logger.error(f"Ошибка при получении статуса анализа: {e}")
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка сервера: {str(e)}")


@router.post("/api/recommendations/analyze-monthly")
async def analyze_monthly_recommendations(
    client_id: str = Query(..., description="ID клиента для анализа рекомендаций"),
    year: int = Query(..., description="Год (например, 2025)"),
    month: int = Query(..., ge=1, le=12, description="Месяц (1-12)"),
    force_refresh: bool = Query(False, description="Принудительно перегенерировать анализ (игнорировать кэш)"),
) -> Dict[str, Any]:
    """
    Генерирует МЕСЯЧНЫЙ анализ рекомендаций на основе недельных отчётов.
    
    Агрегирует все недельные анализы за указанный месяц и создаёт:
    - Сводку ключевых трендов за месяц
    - Выделение системных проблем (повторяющихся из недели в неделю)
    - Стратегические рекомендации на уровне процессов
    
    Результаты кэшируются с period_type='monthly'. 
    Используйте force_refresh=true для перегенерации.
    """
    logger.info(
        f"Запрос на месячный анализ рекомендаций: client_id={client_id}, "
        f"период: {month}/{year}, force_refresh={force_refresh}"
    )

    try:
        service = RecommendationAnalysisService(client_id=client_id)
        
        if force_refresh:
            logger.info("Принудительная перегенерация месячного анализа (force_refresh=True)")
            analysis_result = await service.analyze_monthly_force_refresh(year=year, month=month)
        else:
            analysis_result = await service.analyze_monthly_recommendations(year=year, month=month)
        
        # Автоматический запуск синхронизации PostgreSQL после завершения анализа
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                postgres_sync_url = f"{os.getenv('API_BASE_URL', 'http://localhost:8001/api')}/postgres/sync-now"
                headers = {"X-API-Key": os.getenv("API_KEY", "")}
                logger.info("Запуск автоматической синхронизации PostgreSQL после месячного анализа")
                postgres_response = await client.post(postgres_sync_url, headers=headers)
                if postgres_response.status_code == 200:
                    logger.info("Синхронизация PostgreSQL успешно запущена")
                else:
                    logger.warning(f"Проблема с запуском синхронизации PostgreSQL: {postgres_response.status_code}")
        except Exception as postgres_error:
            logger.error(f"Ошибка при запуске синхронизации PostgreSQL: {postgres_error}")
        
        # Названия месяцев
        month_names = {
            1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
            5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
            9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"
        }
        
        return {
            "message": f"Месячный анализ рекомендаций за {month_names[month]} {year} успешно завершен.",
            "period": f"{month_names[month]} {year}",
            "period_type": "monthly",
            "data": analysis_result
        }
    except Exception as e:
        logger.error(f"Ошибка при месячном анализе рекомендаций для client_id {client_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка сервера: {e}")


@router.post("/api/recommendations/analyze-by-date-range")
async def analyze_recommendations_by_date_range(
    client_id: str = Query(..., description="ID клиента для анализа рекомендаций"),
    start_date_str: str = Query(..., description="Начальная дата в формате DD.MM.YYYY или YYYY-MM-DD"),
    end_date_str: str = Query(..., description="Конечная дата в формате DD.MM.YYYY или YYYY-MM-DD"),
    force_refresh: bool = Query(False, description="Принудительно перегенерировать анализ (игнорировать кэш)"),
) -> Dict[str, Any]:
    """
    Запускает анализ и обобщение всех рекомендаций для указанного клиента за период.
    
    ВАЖНО: Рекомендации теперь формируются на основе РЕАЛЬНЫХ БАЛЛОВ из сводной таблицы:
    - Сильные стороны: критерии с баллами 8-10
    - Зоны роста: критерии с баллами 5-7
    - Критические слабые места: критерии с баллами 0-4
    
    Результаты кэшируются. Используйте force_refresh=true для перегенерации.
    """
    logger.info(
        f"Запрос на анализ рекомендаций: client_id={client_id}, "
        f"период с {start_date_str} по {end_date_str}, force_refresh={force_refresh}"
    )

    start_date_obj = convert_date_string(start_date_str)
    end_date_obj = convert_date_string(end_date_str)

    if not start_date_obj or not end_date_obj:
        raise HTTPException(status_code=400, detail="Неверный формат даты. Используйте DD.MM.YYYY или YYYY-MM-DD.")

    if start_date_obj > end_date_obj:
        raise HTTPException(status_code=400, detail="Начальная дата не может быть позже конечной даты.")

    # Сервис ожидает объекты date, а не datetime
    start_date_val = start_date_obj.date()
    end_date_val = end_date_obj.date()

    try:
        service = RecommendationAnalysisService(client_id=client_id)
        
        # Если force_refresh=True, принудительно перегенерируем
        if force_refresh:
            logger.info("Принудительная перегенерация анализа (force_refresh=True)")
            analysis_result = await service.analyze_recommendations_force_refresh(
                start_date=start_date_val,
                end_date=end_date_val
            )
        else:
            analysis_result = await service.analyze_recommendations_for_period(
                start_date=start_date_val,
                end_date=end_date_val
            )
        
        # Автоматический запуск синхронизации PostgreSQL после завершения анализа
        try:
            async with httpx.AsyncClient(timeout=None) as client:  # Без таймаута для больших объемов данных
                # URL для синхронизации PostgreSQL
                postgres_sync_url = f"{os.getenv('API_BASE_URL', 'http://localhost:8001/api')}/postgres/sync-now"
                headers = {"X-API-Key": os.getenv("API_KEY", "")}
                logger.info("Запуск автоматической синхронизации PostgreSQL после анализа рекомендаций")
                postgres_response = await client.post(postgres_sync_url, headers=headers)
                if postgres_response.status_code == 200:
                    logger.info("Синхронизация PostgreSQL успешно запущена")
                else:
                    logger.warning(f"Проблема с запуском синхронизации PostgreSQL: {postgres_response.status_code}")
        except Exception as postgres_error:
            logger.error(f"Ошибка при запуске синхронизации PostgreSQL: {postgres_error}")
            # Не прерываем основной процесс из-за ошибки синхронизации
        
        return {
            "message": "Анализ рекомендаций успешно завершен.",
            "data": analysis_result
        }
    except Exception as e:
        logger.error(f"Ошибка при анализе рекомендаций для client_id {client_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка сервера: {e}")


@router.get("/api/recommendations/analyze-by-date-range-status")
async def get_recommendations_analysis_status_by_date_range(
    client_id: str = Query(..., description="ID клиента"),
    start_date_str: str = Query(..., description="Начальная дата в формате DD.MM.YYYY или YYYY-MM-DD"),
    end_date_str: str = Query(..., description="Конечная дата в формате DD.MM.YYYY или YYYY-MM-DD"),
) -> Dict[str, Any]:
    """
    Получить статус анализа рекомендаций за указанный период для проверки завершения процесса.
    """
    try:
        start_date_obj = convert_date_string(start_date_str)
        end_date_obj = convert_date_string(end_date_str)

        if not start_date_obj or not end_date_obj:
            raise HTTPException(status_code=400, detail="Неверный формат даты. Используйте DD.MM.YYYY или YYYY-MM-DD.")

        # Создаем подключение к MongoDB для анализа рекомендаций
        mongo_client = get_mongodb()
        db = mongo_client[DB_NAME]
        analysis_collection = db["recommendation_analysis"]
        
        # Ищем кэшированный результат анализа рекомендаций
        start_date_val = start_date_obj.date()
        end_date_val = end_date_obj.date()
        
        cache_query = {
            "client_id": client_id,
            "start_date": start_date_val.isoformat(),
            "end_date": end_date_val.isoformat()
        }
        
        cached_result = await analysis_collection.find_one(cache_query)
        
        if cached_result:
            # Анализ уже выполнен и результат кэширован
            summary_analyze_status = cached_result.get("summary_analyze_status", "success")
            return {
                "overall_status": "completed",
                "summary_analyze_status": summary_analyze_status,
                "has_cached_result": True,
                "cache_created_at": cached_result.get("created_at"),
                "analysis_available": True
            }
        else:
            # Проверяем, есть ли звонки с рекомендациями за период для анализа
            calls_query = {
                "client_id": client_id,
                "created_date_for_filtering": {
                    "$gte": start_date_val.isoformat(),
                    "$lte": end_date_val.isoformat()
                },
                "recommendations": {"$exists": True, "$ne": []}
            }
            
            calls_cursor = db.calls.find(calls_query, {"_id": 1})
            calls_with_recommendations = await calls_cursor.to_list(length=None)
            
            if not calls_with_recommendations:
                return {
                    "overall_status": "no_data",
                    "summary_analyze_status": "not_applicable",
                    "has_cached_result": False,
                    "calls_with_recommendations": 0,
                    "analysis_available": False,
                    "message": "Не найдено звонков с рекомендациями за указанный период"
                }
            
            return {
                "overall_status": "pending",
                "summary_analyze_status": "pending",
                "has_cached_result": False,
                "calls_with_recommendations": len(calls_with_recommendations),
                "analysis_available": False,
                "message": "Анализ рекомендаций еще не выполнен для данного периода"
            }

    except Exception as e:
        logger.error(f"Ошибка при получении статуса анализа рекомендаций: {e}")
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка сервера: {str(e)}")


@router.get("/api/call/scores", response_model=CallScoresResponse, summary="Получить оценки звонка по критериям")
async def get_call_scores(
    note_id: int = Query(..., description="ID заметки в AmoCRM"),
    client_id: Optional[str] = Query(None, description="ID клиники (опционально для дополнительной валидации)")
) -> CallScoresResponse:
    """
    Получить оценки звонка по всем критериям из новой шкалы оценок.

    Возвращает:
    - Оценки по всем критериям (0-10 баллов)
    - Общую оценку (overall_score)
    - Информацию о конверсии
    - Рекомендации по улучшению

    Типы звонков и их критерии:
    - **Первичка** (17 критериев): приветствие, имя пациента, выявление потребностей, презентация услуги/клиники/врача, запись, цена, экспертность, следующий шаг, запись на прием, эмоциональный окрас, речь, инициатива, адрес, паспорт, работа с возражениями
    - **Вторичка** (10 критериев): приветствие, имя пациента, выявление потребностей, экспертность, следующий шаг, запись на прием, эмоциональный окрас, речь, инициатива, работа с возражениями
    - **Перезвон** (9 критериев): приветствие, имя пациента, апелляция, следующий шаг, инициатива, речь, адрес, паспорт, работа с возражениями
    """
    try:
        # Подключение к MongoDB
        mongo_client = get_mongodb()
        db = mongo_client[DB_NAME]

        # Формирование запроса
        query = {"note_id": note_id}
        if client_id:
            query["client_id"] = client_id

        # Получение звонка из базы данных
        call = await db.calls.find_one(query)

        if not call:
            raise HTTPException(
                status_code=404,
                detail=f"Звонок с note_id={note_id}" + (f" и client_id={client_id}" if client_id else "") + " не найден"
            )

        # Проверка наличия анализа
        if not call.get("metrics") or not call.get("analyze_status") == "success":
            raise HTTPException(
                status_code=404,
                detail=f"Звонок с note_id={note_id} еще не был проанализирован. Сначала запустите анализ через /api/call/analyze-call-new/{call['_id']}"
            )

        # Маппинг критериев на русские названия согласно документации
        CRITERIA_NAMES = {
            "greeting": "Приветствие",
            "patient_name": "Имя пациента",
            "needs_identification": "Выявление потребностей",
            "objection_handling": "Работа с возражениями",
            "service_presentation": "Презентация услуги",
            "clinic_presentation": "Презентация клиники",
            "doctor_presentation": "Презентация врача",
            "patient_booking": "Запись пациента",
            "clinic_address": "Адрес клиники",
            "passport": "Паспорт",
            "price": "Цена",
            "expertise": "Экспертность",
            "next_step": "Следующий шаг",
            "appointment": "Запись на прием",
            "emotional_tone": "Эмоциональный окрас",
            "speech": "Речь",
            "initiative": "Инициатива",
            "appeal": "Апелляция"
        }

        # Получаем метрики из звонка
        metrics = call.get("metrics", {})

        # Формируем оценки по критериям
        scores = {}
        for criterion_key, criterion_value in metrics.items():
            # Пропускаем не-числовые метрики
            if criterion_key in ["conversion", "duration", "call_type_classification", "overall_score"]:
                continue

            # Проверяем, что это число
            if isinstance(criterion_value, (int, float)):
                criterion_name = CRITERIA_NAMES.get(criterion_key, criterion_key.replace("_", " ").title())
                scores[criterion_key] = CriterionScore(
                    name=criterion_name,
                    score=int(criterion_value),
                    comment=None  # Комментарии можно добавить из файла анализа при необходимости
                )

        # Формируем ссылку на скачивание транскрибации
        transcription_url = None
        if call.get("filename_transcription"):
            transcription_url = f"/api/transcriptions/{call.get('filename_transcription')}/download"

        # Формируем ответ
        response = CallScoresResponse(
            note_id=call.get("note_id"),
            client_id=call.get("client_id"),
            call_type=call.get("call_type_name", "Не определен"),
            call_type_id=call.get("call_type_id"),
            administrator=call.get("administrator"),
            created_date=call.get("created_date_for_filtering"),
            overall_score=metrics.get("overall_score"),
            conversion=metrics.get("conversion"),
            scores=scores,
            recommendations=call.get("recommendations", []),
            transcription_url=transcription_url
        )

        logger.info(f"Успешно получены оценки для звонка note_id={note_id}, тип={response.call_type}")
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при получении оценок звонка: {e}")
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка сервера: {str(e)}")
