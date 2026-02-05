import os
import json
from datetime import date, datetime
import logging
from langchain_core.messages import HumanMessage

from app.settings.auth import get_langchain_token, get_mongodb
from app.settings.paths import DB_NAME

logger = logging.getLogger(__name__)

# Маппинг английских названий критериев на русские
CRITERIA_NAMES = {
    'greeting': 'Приветствие',
    'patient_name': 'Имя пациента',
    'needs_identification': 'Выявление потребностей',
    'service_presentation': 'Презентация услуги',
    'clinic_presentation': 'Презентация клиники',
    'doctor_presentation': 'Презентация врача',
    'appointment': 'Запись на прием',
    'appointment_offer': 'Предложение записи',
    'price': 'Цена',
    'expertise': 'Экспертность',
    'next_step': 'Следующий шаг',
    'patient_booking': 'Запись',
    'emotional_tone': 'Эмоциональный тон',
    'speech': 'Речь',
    'initiative': 'Инициатива',
    'clinic_address': 'Адрес клиники',
    'passport': 'Паспорт',
    'objection_handling': 'Работа с возражениями',
    'appeal': 'Апелляция',
    'question_clarification': 'Уточнение вопроса',
    'communication': 'Коммуникация',
    # Возражения
    'objection_no_time': 'Возражение: нет времени',
    'objection_expensive': 'Возражение: дорого',
    'objection_think': 'Возражение: подумаю',
    'objection_not_relevant': 'Возражение: не актуально',
    'objection_comparing': 'Возражение: сравниваю',
    'objection_consult': 'Возражение: нужна консультация',
}

class RecommendationAnalysisService:
    def __init__(self, client_id: str):
        self.client_id = client_id
        self.mongo_client = get_mongodb()
        self.db = self.mongo_client[DB_NAME]
        self.calls_collection = self.db.calls
        self.analysis_collection = self.db.recommendation_analysis_results
        self.llm = get_langchain_token()

    async def analyze_recommendations_for_period(self, start_date: date, end_date: date) -> dict:
        logger.info(f"Анализ рекомендаций для client_id: {self.client_id} за период с {start_date} по {end_date}")

        # Проверяем, есть ли уже результат в кэше
        cached_result = await self.analysis_collection.find_one({
            "client_id": self.client_id,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat()
        })
        if cached_result:
            logger.info("Найден кэшированный результат анализа.")
            return cached_result.get("analysis_data", {})

        # 1. Получаем все звонки за период с метриками и рекомендациями
        query = {
            "client_id": self.client_id,
            "created_date_for_filtering": {
                "$gte": start_date.isoformat(),
                "$lte": end_date.isoformat()
            }
        }
        
        calls_cursor = self.calls_collection.find(query, {"recommendations": 1, "metrics": 1})
        all_recommendations = []
        all_metrics = []
        
        async for doc in calls_cursor:
            if doc.get("recommendations"):
                all_recommendations.extend(doc["recommendations"])
            if doc.get("metrics") and isinstance(doc["metrics"], dict):
                all_metrics.append(doc["metrics"])

        # 2. Рассчитываем средние баллы по критериям
        avg_scores = self._calculate_average_scores(all_metrics)
        
        # 3. Классифицируем критерии по зонам
        classification = self._classify_criteria(avg_scores)
        
        logger.info(f"Средние баллы по критериям: {avg_scores}")
        logger.info(f"Классификация: сильные={len(classification['strong'])}, рост={len(classification['growth'])}, критические={len(classification['critical'])}")

        if not all_recommendations and not avg_scores:
            logger.warning("Рекомендации и метрики за указанный период не найдены.")
            return {"summary_points": [], "overall_summary": "Данные для анализа отсутствуют."}

        # 4. Формируем промпт для LLM с данными из таблицы
        prompt = self._create_llm_prompt(all_recommendations, avg_scores, classification)

        # 5. Выполняем анализ с помощью LLM
        try:
            message = HumanMessage(content=prompt)
            response = self.llm.invoke([message])
            
            content = response.content
            # Очищаем ответ от markdown-форматирования
            if '```json' in content:
                content = content.split('```json')[1].split('```')[0].strip()
            elif '```' in content:
                content = content.split('```')[1].split('```')[0].strip()

            analysis_result = json.loads(content)

        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON ответа от LLM: {response.content}")
            raise ValueError(f"Ошибка обработки ответа от нейросети: не удалось разобрать JSON. Ответ: {response.content}")
        except Exception as e:
            logger.error(f"Ошибка при анализе рекомендаций с помощью LLM: {e}")
            raise

        # 6. Сохраняем результат в кэш
        await self.analysis_collection.insert_one({
            "client_id": self.client_id,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "analysis_data": analysis_result,
            "avg_scores": avg_scores,
            "classification": classification,
            "summary_analyze_status": "success",
            "created_at": datetime.utcnow()
        })
        logger.info("Результат анализа сохранен в кэш.")

        return analysis_result

    def _calculate_average_scores(self, metrics_list: list[dict]) -> dict:
        """
        Рассчитывает средние баллы по каждому критерию из списка метрик звонков
        """
        if not metrics_list:
            return {}
        
        # Собираем все значения по каждому критерию
        criteria_values = {}
        for metrics in metrics_list:
            for key, value in metrics.items():
                if key in ['overall_score', 'conversion', 'call_type_classification']:
                    continue  # Пропускаем служебные поля
                if isinstance(value, (int, float)) and value >= 0:
                    if key not in criteria_values:
                        criteria_values[key] = []
                    criteria_values[key].append(value)
        
        # Вычисляем средние значения
        avg_scores = {}
        for key, values in criteria_values.items():
            if values:
                avg_scores[key] = round(sum(values) / len(values), 1)
        
        return avg_scores

    def _classify_criteria(self, avg_scores: dict) -> dict:
        """
        Классифицирует критерии по зонам на основе средних баллов:
        - 8-10 баллов: Сильные стороны
        - 5-7 баллов: Зоны роста  
        - 0-4 балла: Критические слабые места
        """
        classification = {
            'strong': [],      # 8-10 баллов
            'growth': [],      # 5-7 баллов
            'critical': []     # 0-4 балла
        }
        
        for criterion, score in avg_scores.items():
            criterion_name = CRITERIA_NAMES.get(criterion, criterion)
            item = {'key': criterion, 'name': criterion_name, 'score': score}
            
            if score >= 8:
                classification['strong'].append(item)
            elif score >= 5:
                classification['growth'].append(item)
            else:
                classification['critical'].append(item)
        
        # Сортируем по баллам
        classification['strong'].sort(key=lambda x: x['score'], reverse=True)
        classification['growth'].sort(key=lambda x: x['score'], reverse=True)
        classification['critical'].sort(key=lambda x: x['score'])
        
        return classification

    def _create_llm_prompt(self, recommendations: list[str], avg_scores: dict, classification: dict) -> str:
        recommendations_text = "\n".join(f"- {r}" for r in recommendations) if recommendations else "Нет рекомендаций"
        
        # Формируем текст с баллами по критериям
        scores_text = ""
        if avg_scores:
            scores_lines = []
            for key, score in sorted(avg_scores.items(), key=lambda x: x[1], reverse=True):
                name = CRITERIA_NAMES.get(key, key)
                scores_lines.append(f"- {name}: {score} баллов")
            scores_text = "\n".join(scores_lines)
        
        # Формируем текст классификации
        strong_text = "\n".join([f"- {item['name']}: {item['score']} баллов" for item in classification['strong']]) or "Нет критериев"
        growth_text = "\n".join([f"- {item['name']}: {item['score']} баллов" for item in classification['growth']]) or "Нет критериев"
        critical_text = "\n".join([f"- {item['name']}: {item['score']} баллов" for item in classification['critical']]) or "Нет критериев"
        
        prompt = f"""
Проанализируй данные о качестве работы администраторов колл-центра за период.

## ВАЖНО: Используй ТОЛЬКО предоставленные данные!

### Сводная таблица средних баллов по критериям (0-10):
{scores_text}

### Классификация критериев (на основе баллов):

**СИЛЬНЫЕ СТОРОНЫ (8-10 баллов):**
{strong_text}

**ЗОНЫ РОСТА (5-7 баллов):**
{growth_text}

**КРИТИЧЕСКИЕ СЛАБЫЕ МЕСТА (0-4 балла):**
{critical_text}

### Рекомендации из отдельных звонков:
{recommendations_text}

---

## ПРАВИЛА ФОРМИРОВАНИЯ ОТЧЁТА:

1. **Сильные стороны** — ТОЛЬКО критерии с баллами 8-10. Укажи как поддерживать высокий уровень.
2. **Зоны роста** — ТОЛЬКО критерии с баллами 5-7. Укажи что нужно улучшить для перехода в "сильные стороны".
3. **Критические слабые места** — ТОЛЬКО критерии с баллами 0-4. Укажи срочные меры для исправления.
4. Рекомендации должны быть конкретными с примерами фраз и действий.
5. НЕЛЬЗЯ относить критерий с баллом 0-4 к "Сильным сторонам" или с баллом 8-10 к "Критическим".

Верни ответ в формате JSON:
{{
  "summary_points": [
    "1. [Обобщённая рекомендация]",
    "2. [Обобщённая рекомендация]"
  ],
  "overall_summary": "# 📊 Общие выводы\\n\\n[Markdown текст отчёта с разделами]"
}}

Шаблон для overall_summary:

# 📊 Общие выводы  

По результатам анализа качества работы администраторов:

---

## ✅ Сильные стороны (8-10 баллов)
[Перечисли ТОЛЬКО критерии с баллами 8-10 из предоставленных данных]
- **[Критерий] — [балл] баллов**  
  [Как поддерживать высокий уровень]

---

## ⚠️ Зоны роста (5-7 баллов)
[Перечисли ТОЛЬКО критерии с баллами 5-7 из предоставленных данных]
- **[Критерий] — [балл] баллов**  
  [Что нужно улучшить для перехода в сильные стороны]

---

## ❗ Критические слабые места (0-4 балла)
[Перечисли ТОЛЬКО критерии с баллами 0-4 из предоставленных данных]
- **[Критерий] — [балл] баллов**  
  [Срочные меры для исправления]

---

## 🛠 Рекомендации  
[Конкретные рекомендации с примерами фраз]

---

## 📝 Итог  
[Общий вывод]

Не добавляй ничего, кроме объекта JSON.
"""
        return prompt

    async def clear_cache_for_period(self, start_date: date, end_date: date) -> bool:
        """
        Очищает кэш анализа рекомендаций для указанного периода.
        Используется для принудительной перегенерации с новой логикой.
        """
        try:
            result = await self.analysis_collection.delete_many({
                "client_id": self.client_id,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat()
            })
            logger.info(f"Удалено {result.deleted_count} записей из кэша для client_id={self.client_id}")
            return True
        except Exception as e:
            logger.error(f"Ошибка при очистке кэша: {e}")
            return False

    async def analyze_recommendations_force_refresh(self, start_date: date, end_date: date) -> dict:
        """
        Принудительно перегенерирует анализ рекомендаций, очищая кэш.
        """
        await self.clear_cache_for_period(start_date, end_date)
        return await self.analyze_recommendations_for_period(start_date, end_date)

    async def analyze_monthly_recommendations(self, year: int, month: int) -> dict:
        """
        Генерирует месячный анализ рекомендаций на основе недельных анализов за месяц.
        Собирает все недельные summary_points и overall_summary, затем агрегирует их через LLM.
        """
        from calendar import monthrange
        
        # Определяем границы месяца
        first_day = date(year, month, 1)
        last_day = date(year, month, monthrange(year, month)[1])
        
        logger.info(f"Генерация месячного анализа для client_id: {self.client_id} за {month}/{year}")
        
        # Проверяем кэш для месячного анализа
        cached_result = await self.analysis_collection.find_one({
            "client_id": self.client_id,
            "start_date": first_day.isoformat(),
            "end_date": last_day.isoformat(),
            "period_type": "monthly"
        })
        if cached_result:
            logger.info("Найден кэшированный месячный результат анализа.")
            return cached_result.get("analysis_data", {})
        
        # Получаем все недельные анализы за этот месяц
        weekly_analyses_cursor = self.analysis_collection.find({
            "client_id": self.client_id,
            "start_date": {"$gte": first_day.isoformat(), "$lte": last_day.isoformat()},
            "$or": [
                {"period_type": {"$exists": False}},
                {"period_type": "weekly"}
            ]
        })
        
        weekly_analyses = []
        all_summary_points = []
        all_overall_summaries = []
        
        async for doc in weekly_analyses_cursor:
            weekly_analyses.append(doc)
            analysis_data = doc.get("analysis_data", {})
            
            if analysis_data.get("summary_points"):
                all_summary_points.extend(analysis_data["summary_points"])
            if analysis_data.get("overall_summary"):
                all_overall_summaries.append({
                    "period": f"{doc.get('start_date')} - {doc.get('end_date')}",
                    "summary": analysis_data["overall_summary"]
                })
        
        if not weekly_analyses:
            logger.warning(f"Недельные анализы за {month}/{year} не найдены.")
            return {"summary_points": [], "overall_summary": "Данные для анализа за месяц отсутствуют."}
        
        logger.info(f"Найдено {len(weekly_analyses)} недельных анализов для агрегации")
        
        # Формируем промпт для месячной агрегации
        prompt = self._create_monthly_llm_prompt(all_summary_points, all_overall_summaries, year, month)
        
        # Выполняем анализ с помощью LLM
        try:
            message = HumanMessage(content=prompt)
            response = self.llm.invoke([message])
            
            content = response.content
            # Очищаем ответ от markdown-форматирования
            if '```json' in content:
                content = content.split('```json')[1].split('```')[0].strip()
            elif '```' in content:
                content = content.split('```')[1].split('```')[0].strip()

            analysis_result = json.loads(content)

        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON ответа от LLM: {response.content}")
            raise ValueError(f"Ошибка обработки ответа от нейросети: {e}")
        except Exception as e:
            logger.error(f"Ошибка при анализе месячных рекомендаций с помощью LLM: {e}")
            raise
        
        # Сохраняем результат в кэш
        await self.analysis_collection.insert_one({
            "client_id": self.client_id,
            "start_date": first_day.isoformat(),
            "end_date": last_day.isoformat(),
            "period_type": "monthly",
            "analysis_data": analysis_result,
            "weekly_analyses_count": len(weekly_analyses),
            "summary_analyze_status": "success",
            "created_at": datetime.utcnow()
        })
        logger.info("Месячный результат анализа сохранен в кэш.")
        
        return analysis_result

    def _create_monthly_llm_prompt(self, summary_points: list[str], overall_summaries: list[dict], year: int, month: int) -> str:
        """
        Создает промпт для агрегации недельных анализов в месячный отчёт.
        """
        # Названия месяцев на русском
        month_names = {
            1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
            5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
            9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"
        }
        month_name = month_names.get(month, str(month))
        
        # Форматируем summary_points
        points_text = "\n".join(summary_points) if summary_points else "Нет данных"
        
        # Форматируем недельные отчёты
        summaries_text = ""
        for i, item in enumerate(overall_summaries, 1):
            summaries_text += f"\n### Неделя {i} ({item['period']}):\n{item['summary']}\n"
        
        if not summaries_text:
            summaries_text = "Нет данных"
        
        prompt = f"""
Сформируй СВОДНЫЙ МЕСЯЧНЫЙ ОТЧЁТ о качестве работы администраторов колл-центра за {month_name} {year}.

## Исходные данные:

### Все рекомендации из недельных отчётов:
{points_text}

### Недельные отчёты:
{summaries_text}

---

## ЗАДАЧА:

Проанализируй все недельные отчёты и создай **единый месячный отчёт**, который:

1. **Выделяет ключевые тренды** — что улучшилось/ухудшилось за месяц
2. **Обобщает повторяющиеся проблемы** — если проблема встречается в нескольких неделях, это системная проблема
3. **Приоритизирует рекомендации** — от самых критичных к менее важным
4. **Даёт стратегические рекомендации** — не только тактические для отдельных звонков

## ФОРМАТ ОТВЕТА:

Верни JSON:
{{
  "summary_points": [
    "1. [Главная рекомендация месяца с высоким приоритетом]",
    "2. [Вторая по важности рекомендация]",
    "3. [Третья рекомендация]",
    ... (до 10 ключевых рекомендаций)
  ],
  "overall_summary": "# 📊 Месячный отчёт: {month_name} {year}\\n\\n[Markdown текст]"
}}

Шаблон для overall_summary:

# 📊 Месячный отчёт: {month_name} {year}

## 📈 Динамика за месяц
[Краткое описание трендов: что улучшилось, что ухудшилось]

---

## ✅ Сильные стороны
[Стабильно высокие показатели за весь месяц]

---

## ⚠️ Системные проблемы
[Проблемы, которые повторялись из недели в неделю]

---

## ❗ Критические области для улучшения
[Самые низкие показатели, требующие срочного внимания]

---

## 🛠 Стратегические рекомендации
[Рекомендации на уровне процессов и обучения, не только отдельных звонков]

---

## 📝 Итоги месяца
[Общий вывод и ключевые метрики]

Не добавляй ничего, кроме объекта JSON.
"""
        return prompt

    async def analyze_monthly_force_refresh(self, year: int, month: int) -> dict:
        """
        Принудительно перегенерирует месячный анализ, очищая кэш.
        """
        from calendar import monthrange
        
        first_day = date(year, month, 1)
        last_day = date(year, month, monthrange(year, month)[1])
        
        # Удаляем кэш месячного анализа
        await self.analysis_collection.delete_many({
            "client_id": self.client_id,
            "start_date": first_day.isoformat(),
            "end_date": last_day.isoformat(),
            "period_type": "monthly"
        })
        
        return await self.analyze_monthly_recommendations(year, month)

