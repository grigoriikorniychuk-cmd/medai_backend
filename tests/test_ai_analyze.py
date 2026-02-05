import os
import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('ai_analyze.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv()

# Пути к данным
TRANSCRIPTION_DIR = Path('app/data/transcription')

# Промпт для классификации типа звонка
CLASSIFICATION_TEMPLATE = """
Проанализируй транскрипцию телефонного разговора между менеджером клиники и клиентом.

ВАЖНО: СНАЧАЛА ОПРЕДЕЛИ ПРАВИЛЬНЫЕ РОЛИ УЧАСТНИКОВ!
В транскрипциях роли могут быть перепутаны. Внимательно изучи содержание реплик:
- Менеджер обычно представляется, называет клинику, задает вопросы и презентует услуги
- Клиент обычно задает вопросы о ценах, услугах и высказывает сомнения

Убедись, что анализируешь работу настоящего менеджера, а не клиента, обращая внимание на содержание реплик, а не только на метки в транскрипции.

Транскрипция:
{transcription}

ОПРЕДЕЛИ ТИП ЗВОНКА:
1 - Первичка (клиент звонит первый раз, первый контакт с клиникой)
2 - Вторичка (клиент звонит повторно, уже был контакт)
3 - Перезвон (клиент или администратор перезванивает)
4 - Подтверждение (звонок для подтверждения визита)
5 - Другое (ни одна категория не подходит)

Укажи номер соответствующей категории и краткое обоснование своего выбора.

Формат ответа - только JSON без дополнительных комментариев:
```json
{{
    "call_type_id": int,  // номер категории (1-5)
    "call_type": string,  // название категории ("первичка", "вторичка", "перезвон", "подтверждение", "другое")
    "explanation": string  // краткое обоснование (1-2 предложения)
}}
```
"""

# Промпты для анализа разных типов звонков
ANALYSIS_TEMPLATES = {
    # Первичка (первый звонок)
    1: """
Проанализируй транскрипцию первичного телефонного звонка (первый контакт клиента с клиникой).
Транскрипция:
{transcription}

ЧЕКЛИСТ ИДЕАЛЬНОЙ ОТРАБОТКИ ПЕРВИЧНОГО ЗВОНКА:

1. ПРИВЕТСТВИЕ (0-10 баллов)
   - Назвал название клиники
   - Представился по имени

2. ИМЯ ПАЦИЕНТА (0-10 баллов)
   - Обратился по имени, если оно известно
   - Спросил имя пациента, если оно неизвестно

3. ПОТРЕБНОСТЬ (0-10 баллов)
   - Уточнил, что интересует клиента
   - Задал уточняющие вопросы по запросу

4. ПРЕЗЕНТАЦИЯ УСЛУГИ (0-10 баллов)
   - Рассказал, что будет входить в услугу
   - Описал процесс оказания услуги

5. ПРЕЗЕНТАЦИЯ КЛИНИКИ (0-10 баллов)
   - Подчеркнул ценности и преимущества клиники
   - Рассказал о возможностях клиники

6. ПРЕЗЕНТАЦИЯ ВРАЧА (0-10 баллов)
   - Подчеркнул квалификацию и опыт врача
   - Рассказал о специализации врача

7. ЗАПИСЬ ПАЦИЕНТА (0-10 баллов)
   - Предложил варианты времени для записи
   - Подтвердил выбранное время

8. АДРЕС КЛИНИКИ (0-10 баллов)
   - Подробно объяснил расположение клиники
   - Дал ориентиры для нахождения клиники

9. ПАСПОРТ (0-10 баллов)
   - Попросил взять паспорт для оформления
   - Объяснил, зачем нужен документ

10. ЦЕНА "ОТ" (0-10 баллов)
    - Назвал цену "от" после презентации услуги
    - Озвучил стоимость в правильный момент разговора

11. ЭКСПЕРТНОСТЬ (0-10 баллов)
    - Продемонстрировал знание видов услуг и материалов
    - Компетентно ответил на вопросы клиента

12. СЛЕДУЮЩИЙ ШАГ (0-10 баллов)
    - Обозначил дальнейшие действия 
    - Сообщил о напоминании о визите или предстоящем перезвоне

13. ЗАПИСЬ НА ПРИЕМ (0-10 баллов)
    - Успешно записал клиента на прием
    - Четко зафиксировал достигнутые договоренности

14. ЭМОЦИОНАЛЬНЫЙ ОКРАС (0-10 баллов)
    - Говорил с улыбкой в голосе
    - Поддерживал доброжелательный тон

15. РЕЧЬ (0-10 баллов)
    - Говорил чисто, без речевых ошибок 
    - Не перебивал клиента

16. ИНИЦИАТИВА (0-10 баллов)
    - Уверенно управлял диалогом
    - Направлял разговор к цели

Оцени КОНВЕРСИЮ:
- Завершился ли звонок записью на прием (Да/Нет)

Верни результат в формате JSON:
```json
{{
    "greeting": {{
        "score": int,  // оценка от 0 до 10
        "comment": string  // краткое обоснование оценки
    }},
    "patient_name": {{
        "score": int,
        "comment": string
    }},
    "needs_identification": {{
        "score": int,
        "comment": string
    }},
    "service_presentation": {{
        "score": int,
        "comment": string
    }},
    "clinic_presentation": {{
        "score": int,
        "comment": string
    }},
    "doctor_presentation": {{
        "score": int,
        "comment": string
    }},
    "patient_booking": {{
        "score": int,
        "comment": string
    }},
    "clinic_address": {{
        "score": int,
        "comment": string
    }},
    "passport": {{
        "score": int,
        "comment": string
    }},
    "price": {{
        "score": int,
        "comment": string
    }},
    "expertise": {{
        "score": int,
        "comment": string
    }},
    "next_step": {{
        "score": int,
        "comment": string
    }},
    "appointment": {{
        "score": int,
        "comment": string
    }},
    "emotional_tone": {{
        "score": int,
        "comment": string
    }},
    "speech": {{
        "score": int,
        "comment": string
    }},
    "initiative": {{
        "score": int,
        "comment": string
    }},
    "tone": string,  // "positive", "neutral", или "negative"
    "customer_satisfaction": string,  // "high", "medium", или "low"
    "overall_score": float,  // средний балл из всех оценок
    "conversion": bool,  // произошла ли конверсия
    "recommendations": [string]  // список рекомендаций для улучшения
}}
```
""",
    
    # Вторичка (повторный звонок)
    2: """
Проанализируй транскрипцию вторичного телефонного звонка (клиент уже имел контакт с клиникой).
Транскрипция:
{transcription}

ЧЕКЛИСТ ИДЕАЛЬНОЙ ОТРАБОТКИ ВТОРИЧНОГО ЗВОНКА:

1. ПРИВЕТСТВИЕ (0-10 баллов)
   - Назвал название клиники
   - Представился по имени

2. ИМЯ ПАЦИЕНТА (0-10 баллов)
   - Обратился по имени
   - Подтвердил, что общается с нужным человеком

3. УТОЧНЕНИЕ ВОПРОСА (0-10 баллов)
   - Выяснил цель звонка клиента
   - Уточнил детали обращения

4. ЭКСПЕРТНОСТЬ (0-10 баллов)
   - Продемонстрировал компетентность в вопросе клиента
   - Дал четкие и исчерпывающие ответы

5. СЛЕДУЮЩИЙ ШАГ (0-10 баллов)
   - Обозначил дальнейшие действия
   - Предложил конкретное решение вопроса клиента

6. ЭМОЦИОНАЛЬНЫЙ ОКРАС (0-10 баллов)
   - Говорил с улыбкой в голосе
   - Поддерживал доброжелательный тон

7. РЕЧЬ (0-10 баллов)
   - Говорил чисто, без речевых ошибок 
   - Не перебивал клиента

Верни результат в формате JSON:
```json
{{
    "greeting": {{
        "score": int,  // оценка от 0 до 10
        "comment": string  // краткое обоснование оценки
    }},
    "patient_name": {{
        "score": int,
        "comment": string
    }},
    "question_clarification": {{
        "score": int,
        "comment": string
    }},
    "expertise": {{
        "score": int,
        "comment": string
    }},
    "next_step": {{
        "score": int,
        "comment": string
    }},
    "emotional_tone": {{
        "score": int,
        "comment": string
    }},
    "speech": {{
        "score": int,
        "comment": string
    }},
    "tone": string,  // "positive", "neutral", или "negative"
    "customer_satisfaction": string,  // "high", "medium", или "low"
    "overall_score": float,  // средний балл из всех оценок
    "recommendations": [string]  // список рекомендаций для улучшения
}}
```
""",
    
    # Перезвон (клиент или администратор перезванивает)
    3: """
Проанализируй транскрипцию звонка-перезвона (клиент или администратор перезванивает после предыдущего контакта).
Транскрипция:
{transcription}

ЧЕКЛИСТ ИДЕАЛЬНОЙ ОТРАБОТКИ ЗВОНКА-ПЕРЕЗВОНА:

1. ПРИВЕТСТВИЕ (0-10 баллов)
   - Назвал название клиники
   - Представился по имени

2. ИМЯ ПАЦИЕНТА (0-10 баллов)
   - Обратился по имени
   - Подтвердил, что общается с нужным человеком

3. АПЕЛЛЯЦИЯ (0-10 баллов)
   - Напомнил о предыдущем разговоре
   - Обозначил цель текущего звонка

4. ОТРАБОТКА ВОЗРАЖЕНИЙ (0-10 баллов)
   - Эффективно работал с возражениями клиента
   - Убедительно ответил на сомнения

5. СЛЕДУЮЩИЙ ШАГ (0-10 баллов)
   - Обозначил дальнейшие действия
   - Предложил конкретное решение

6. ИНИЦИАТИВА (0-10 баллов)
   - Уверенно управлял диалогом
   - Направлял разговор к цели

7. АДРЕС И ПАСПОРТ (0-10 баллов)
   - Напомнил о необходимых документах (если требуется)
   - Подтвердил или объяснил адрес клиники (если требуется)

8. РЕЧЬ (0-10 баллов)
   - Говорил чисто, без речевых ошибок 
   - Не перебивал клиента

Оцени КОНВЕРСИЮ:
- Завершился ли звонок договоренностью о визите или следующем шаге (Да/Нет)

Верни результат в формате JSON:
```json
{{
    "greeting": {{
        "score": int,  // оценка от 0 до 10
        "comment": string  // краткое обоснование оценки
    }},
    "patient_name": {{
        "score": int,
        "comment": string
    }},
    "appeal": {{
        "score": int,
        "comment": string
    }},
    "objection_handling": {{
        "score": int,
        "comment": string
    }},
    "next_step": {{
        "score": int,
        "comment": string
    }},
    "initiative": {{
        "score": int,
        "comment": string
    }},
    "address_passport": {{
        "score": int,
        "comment": string
    }},
    "speech": {{
        "score": int,
        "comment": string
    }},
    "tone": string,  // "positive", "neutral", или "negative"
    "customer_satisfaction": string,  // "high", "medium", или "low"
    "overall_score": float,  // средний балл из всех оценок
    "conversion": bool,  // произошла ли конверсия
    "recommendations": [string]  // список рекомендаций для улучшения
}}
```
""",
    
    # Подтверждение (звонок для подтверждения визита)
    4: """
Проанализируй транскрипцию звонка-подтверждения (звонок для подтверждения визита пациента).
Транскрипция:
{transcription}

ЧЕКЛИСТ ИДЕАЛЬНОЙ ОТРАБОТКИ ЗВОНКА-ПОДТВЕРЖДЕНИЯ:

1. ПРИВЕТСТВИЕ (0-10 баллов)
   - Назвал название клиники
   - Представился по имени

2. ИМЯ ПАЦИЕНТА (0-10 баллов)
   - Обратился по имени
   - Подтвердил, что общается с нужным человеком

3. АПЕЛЛЯЦИЯ (0-10 баллов)
   - Четко сообщил о записи на приём с указанием даты и времени
   - Уточнил, действительна ли запись

4. ОТРАБОТКА ВОЗРАЖЕНИЙ (0-10 баллов)
   - Эффективно работал с возражениями, если пациент не может посетить клинику
   - Предложил альтернативы, если запись отменяется

5. СЛЕДУЮЩИЙ ШАГ (0-10 баллов)
   - Обозначил дальнейшие действия
   - Подтвердил договоренность

6. ИНИЦИАТИВА (0-10 баллов)
   - Уверенно управлял диалогом
   - Направлял разговор к цели

7. АДРЕС И ПАСПОРТ (0-10 баллов)
   - Напомнил о необходимых документах
   - Подтвердил адрес клиники, если нужно

8. РЕЧЬ (0-10 баллов)
   - Говорил чисто, без речевых ошибок 
   - Не перебивал клиента

Оцени ПОДТВЕРЖДЕНИЕ:
- Подтвердил ли клиент свой визит (Да/Нет)

Верни результат в формате JSON:
```json
{{
    "greeting": {{
        "score": int,  // оценка от 0 до 10
        "comment": string  // краткое обоснование оценки
    }},
    "patient_name": {{
        "score": int,
        "comment": string
    }},
    "appeal": {{
        "score": int,
        "comment": string
    }},
    "objection_handling": {{
        "score": int,
        "comment": string
    }},
    "next_step": {{
        "score": int,
        "comment": string
    }},
    "initiative": {{
        "score": int,
        "comment": string
    }},
    "address_passport": {{
        "score": int,
        "comment": string
    }},
    "speech": {{
        "score": int,
        "comment": string
    }},
    "tone": string,  // "positive", "neutral", или "negative"
    "customer_satisfaction": string,  // "high", "medium", или "low"
    "overall_score": float,  // средний балл из всех оценок
    "visit_confirmed": bool,  // подтвердил ли клиент визит
    "recommendations": [string]  // список рекомендаций для улучшения
}}
```
""",
    
    # Другое (другие типы звонков)
    5: """
Проанализируй транскрипцию телефонного звонка, который не относится к стандартным категориям.
Транскрипция:
{transcription}

Оцени следующие аспекты звонка:

1. ПРИВЕТСТВИЕ (0-10 баллов)
   - Назвал название клиники
   - Представился по имени

2. ПОНИМАНИЕ ЗАПРОСА (0-10 баллов)
   - Выяснил цель звонка клиента
   - Правильно понял суть обращения

3. РЕШЕНИЕ ВОПРОСА (0-10 баллов)
   - Предложил адекватное решение проблемы
   - Четко ответил на вопросы клиента

4. ЭМОЦИОНАЛЬНЫЙ ОКРАС (0-10 баллов)
   - Говорил с улыбкой в голосе
   - Поддерживал доброжелательный тон

5. РЕЧЬ (0-10 баллов)
   - Говорил чисто, без речевых ошибок 
   - Не перебивал клиента

Верни результат в формате JSON:
```json
{{
    "greeting": {{
        "score": int,  // оценка от 0 до 10
        "comment": string  // краткое обоснование оценки
    }},
    "understanding_request": {{
        "score": int,
        "comment": string
    }},
    "problem_solving": {{
        "score": int,
        "comment": string
    }},
    "emotional_tone": {{
        "score": int,
        "comment": string
    }},
    "speech": {{
        "score": int,
        "comment": string
    }},
    "tone": string,  // "positive", "neutral", или "negative"
    "customer_satisfaction": string,  // "high", "medium", или "low"
    "overall_score": float,  // средний балл из всех оценок
    "call_summary": string,  // краткое описание сути звонка
    "recommendations": [string]  // список рекомендаций для улучшения
}}
```
"""
}

def read_transcription(file_path: str) -> str:
    """Чтение транскрипции звонка из файла"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        logger.error(f"Ошибка при чтении файла {file_path}: {e}")
        return ""

def classify_call_type(llm: ChatOpenAI, transcription: str) -> Dict[str, Any]:
    """Классификация типа звонка"""
    try:
        # Подготовка промпта
        classification_prompt = ChatPromptTemplate.from_template(CLASSIFICATION_TEMPLATE)

        # Создание цепочки для классификации
        classification_chain = classification_prompt | llm | StrOutputParser()
        
        # Запуск классификации
        logger.info("Отправка запроса на классификацию звонка...")
        output = classification_chain.invoke({"transcription": transcription})
        
        # Извлечение JSON из ответа
        try:
            # Пытаемся извлечь JSON из ответа
            json_match = re.search(r'```json\s*(.*?)\s*```', output, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group(1))
                logger.info("JSON извлечен из блока кода")
            else:
                result = json.loads(output)
                logger.info("JSON извлечен напрямую из ответа")
                
            # Проверяем наличие требуемых полей
            if 'call_type_id' not in result or 'call_type' not in result:
                raise ValueError("В ответе отсутствуют обязательные поля call_type_id или call_type")
                
            logger.info(f"Тип звонка: {result['call_type']} (ID: {result['call_type_id']})")
        except Exception as json_error:
            logger.error(f"Ошибка при извлечении JSON из ответа: {json_error}")
            logger.debug(f"Полученный ответ: {output}")
            raise
        return result
    except Exception as e:
        logger.error(f"Ошибка при классификации звонка: {e}")
        # Создаем результат по умолчанию в случае ошибки
        return {
            "call_type_id": 5,  # Другое по умолчанию
            "call_type": "другое",
            "explanation": "Не удалось определить тип звонка из-за ошибки"
        }
    except Exception as e:
        logger.error(f"Ошибка при классификации звонка: {e}")
        return {
            "call_type_id": 5,
            "call_type": "другое",
            "explanation": "Не удалось определить тип звонка из-за ошибки"
        }

def analyze_call(llm: ChatOpenAI, transcription: str, call_type_id: int) -> Dict[str, Any]:
    """Анализ звонка в зависимости от его типа"""
    try:
        # Проверяем, что для данного типа звонка есть шаблон
        if call_type_id not in ANALYSIS_TEMPLATES:
            logger.warning(f"Неизвестный тип звонка {call_type_id}, используем тип 5 (Другое)")
            call_type_id = 5  # Используем тип "Другое" по умолчанию
        
        # Подготовка промпта для выбранного типа звонка
        analysis_prompt = ChatPromptTemplate.from_template(ANALYSIS_TEMPLATES[call_type_id])

        # Создание цепочки для анализа
        analysis_chain = analysis_prompt | llm | StrOutputParser()
        
        # Запуск анализа
        logger.info("Выполняется анализ звонка...")
        output = analysis_chain.invoke({"transcription": transcription})
        
        # Извлечение JSON из ответа
        try:
            # Пытаемся извлечь JSON из ответа
            json_match = re.search(r'```json\s*(.*?)\s*```', output, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group(1))
                logger.debug("JSON извлечен из блока кода")
            else:
                result = json.loads(output)
                logger.debug("JSON извлечен напрямую из ответа")
                
            # Расчёт общей оценки - все отсутствующие оценки считаем нулевыми
            if 'overall_score' not in result:
                # Создаём список всех полей с оценками
                scores = []
                for key, value in result.items():
                    if isinstance(value, dict) and 'score' in value:
                        scores.append(value['score'])
                
                # Расчёт среднего значения, если есть оценки
                if scores:
                    result['overall_score'] = round(sum(scores) / len(scores), 2)
                else:
                    result['overall_score'] = 0.0
                    
            logger.info(f"Анализ звонка завершен, общая оценка: {result.get('overall_score', 0)}")
            return result
        except Exception as json_error:
            logger.error(f"Ошибка при извлечении JSON из ответа: {json_error}")
            logger.error(f"Полученный ответ: {output}")
            raise
    except Exception as e:
        logger.error(f"Ошибка при анализе звонка: {e}")
        return {"error": f"Ошибка анализа звонка: {str(e)}"}

def save_analysis_results(results: Dict[str, Any], output_file: str) -> None:
    """Сохранение результатов анализа в JSON-файл"""
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=4)
        logger.info(f"Результаты анализа сохранены в {output_file}")
    except Exception as e:
        logger.error(f"Ошибка при сохранении результатов: {e}")

def process_transcription_file(file_path: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Обработка одного файла транскрипции"""
    # Инициализация LangChain LLM
    llm = ChatOpenAI(
        model_name="gpt-4.1-mini",
        temperature=0.3,
        openai_api_key=os.getenv("OPENAI")
    )
    
    # Чтение транскрипции
    transcription = read_transcription(file_path)
    if not transcription:
        logger.error(f"Не удалось прочитать транскрипцию из {file_path}")
        return {}, {}
    
    # Классификация типа звонка
    logger.info(f"Классификация типа звонка для {file_path}")
    call_type = classify_call_type(llm, transcription)
    
    # Анализ звонка в зависимости от его типа
    logger.info(f"Анализ звонка типа {call_type['call_type']} для {file_path}")
    call_analysis = analyze_call(llm, transcription, call_type['call_type_id'])
    
    # Добавляем информацию о типе звонка в результаты анализа
    call_analysis['call_type_id'] = call_type['call_type_id']
    call_analysis['call_type'] = call_type['call_type']
    call_analysis['call_type_explanation'] = call_type['explanation']
    
    return call_type, call_analysis

def process_all_transcriptions():
    """Обработка всех файлов транскрипций в папке"""
    # Получаем список всех .txt файлов в папке транскрипций
    transcription_files = list(TRANSCRIPTION_DIR.glob('*.txt'))
    
    if not transcription_files:
        logger.error("В папке не найдено файлов транскрипций")
        return
    
    # Статистика по типам звонков
    call_types_stats = {
        1: 0,  # Первичка
        2: 0,  # Вторичка
        3: 0,  # Перезвон
        4: 0,  # Подтверждение
        5: 0   # Другое
    }
    
    # Информация о процессе
    total_files = len(transcription_files)
    processed_files = 0
    successful_files = 0
    failed_files = 0
    overall_scores = []
    
    logger.info(f"Найдено {total_files} файлов транскрипций для анализа")
    
    # Обрабатываем каждый файл
    for file_path in transcription_files:
        processed_files += 1
        logger.info(f"[{processed_files}/{total_files}] Обработка файла: {file_path.name}")
        
        try:
            # Анализ транскрипции
            call_type, analysis_results = process_transcription_file(str(file_path))
            
            # Статистика по типам звонков
            if 'call_type_id' in call_type:
                call_type_id = call_type['call_type_id']
                call_types_stats[call_type_id] = call_types_stats.get(call_type_id, 0) + 1
            
            # Сохранение результатов
            filename = file_path.stem
            output_file = f"{filename}_analysis.json"
            save_analysis_results(analysis_results, output_file)
            
            # Сбор статистики
            if 'overall_score' in analysis_results:
                overall_scores.append(analysis_results['overall_score'])
            
            successful_files += 1
        except Exception as e:
            logger.error(f"Ошибка при обработке файла {file_path.name}: {str(e)}")
            failed_files += 1
    
    # Формирование сводного отчета
    avg_score = sum(overall_scores) / len(overall_scores) if overall_scores else 0
    
    # Отчет о проделанной работе
    report = {
        "total_files": total_files,
        "processed_files": processed_files,
        "successful_files": successful_files,
        "failed_files": failed_files,
        "avg_score": round(avg_score, 2),
        "call_types": {
            "1_pervichka": call_types_stats.get(1, 0),
            "2_vtorichka": call_types_stats.get(2, 0),
            "3_perezvon": call_types_stats.get(3, 0),
            "4_podtverzhdenie": call_types_stats.get(4, 0),
            "5_drugoe": call_types_stats.get(5, 0)
        }
    }
    
    # Сохраняем сводный отчет
    save_analysis_results(report, "transcription_analysis_report.json")
    
    # Вывод итоговой статистики
    logger.info("=== Итоги анализа ====")
    logger.info(f"Всего файлов: {total_files}")
    logger.info(f"Успешно обработано: {successful_files}")
    logger.info(f"Ошибок: {failed_files}")
    logger.info(f"Средняя оценка: {round(avg_score, 2)}")
    logger.info("Типы звонков:")
    logger.info(f"  Первичка: {call_types_stats.get(1, 0)}")
    logger.info(f"  Вторичка: {call_types_stats.get(2, 0)}")
    logger.info(f"  Перезвон: {call_types_stats.get(3, 0)}")
    logger.info(f"  Подтверждение: {call_types_stats.get(4, 0)}")
    logger.info(f"  Другое: {call_types_stats.get(5, 0)}")
    logger.info("Анализ всех транскрипций завершен")

def main():
    """Основная функция для запуска анализа транскрипций"""
    # Запускаем обработку всех файлов транскрипций
    process_all_transcriptions()

if __name__ == "__main__":
    main()  