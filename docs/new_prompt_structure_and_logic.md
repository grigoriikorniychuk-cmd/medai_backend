# Структура промптов и логика оценки звонков

**Версия:** 4.0
**Дата обновления:** 18.11.2025
**Статус:** Активная реализация

---

## Оглавление

1. [Общая архитектура](#общая-архитектура)
2. [Типы звонков и критерии оценки](#типы-звонков-и-критерии-оценки)
3. [Файловая структура промптов](#файловая-структура-промптов)
4. [Сервисы и функции](#сервисы-и-функции)
5. [Процесс обработки звонка](#процесс-обработки-звонка)
6. [Расчёт средних значений в отчётах](#расчёт-средних-значений-в-отчётах)
7. [Примеры работы](#примеры-работы)

---

## Общая архитектура

### Проблема, которую решает система

До внедрения типо-специфичной оценки все звонки оценивались по 16 критериям первичного звонка, что приводило к:
- Некорректным средним значениям в дашборде
- Оценке "0" по неприменимым критериям (например, "презентация врача" во вторичном звонке)
- Искажению статистики качества обслуживания

### Решение

Двухэтапная система оценки:

```
┌─────────────────────────────────────────────────────────────┐
│  1. КЛАССИФИКАЦИЯ ЗВОНКА                                    │
│     (определение типа: первичка/вторичка/перезвон/          │
│      подтверждение/другое)                                  │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  2. АНАЛИЗ ЗВОНКА                                           │
│     (использование типо-специфичного промпта с              │
│      соответствующим количеством критериев)                 │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  3. СОХРАНЕНИЕ РЕЗУЛЬТАТА                                   │
│     (сохранение только релевантных метрик в MongoDB)        │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  4. ГЕНЕРАЦИЯ ОТЧЁТОВ                                       │
│     (расчёт средних только по ненулевым критериям)          │
└─────────────────────────────────────────────────────────────┘
```

---

## Типы звонков и критерии оценки

### 1. Первичка (initial_call) - 16 критериев + 6 типов возражений

**Описание:** Первый звонок клиента в клинику для получения информации и потенциальной записи.

**Основные критерии (16):**
1. `greeting` - Приветствие (0/4/6/10)
2. `patient_name` - Уточнение имени (0/2/5/7/10)
3. `needs_identification` - Выявление потребностей (0/2/4/6/8/10)
4. `service_presentation` - Презентация услуги (0/2/6/10)
5. `clinic_presentation` - Презентация клиники (0-10)
6. `doctor_presentation` - Презентация врача (0/2/4/6/8/10)
7. `patient_booking` - Бронирование пациента (0/10)
8. `clinic_address` - Адрес клиники (0/10)
9. `passport` - Паспорт (0/10)
10. `price` - Цена (0/2/4/6/10)
11. `expertise` - Экспертность (0/5/10)
12. `next_step` - Следующий шаг (0/2/4/8/10)
13. `appointment` - Назначение встречи (0/10)
14. `emotional_tone` - Эмоциональный окрас (0/4/6-8/10)
15. `speech` - Речь (0/5-8/9/10)
16. `initiative` - Инициатива (0/2-8/10)

**Возражения (опциональные, возвращаются только при наличии):**
- `objection_no_time` - "Нет времени" (0/5/10)
- `objection_expensive` - "Дорого" (0/5/10)
- `objection_think` - "Подумаю" (0/5/10)
- `objection_not_relevant` - "Не актуально" (0/10)
- `objection_comparing` - "Сравниваю варианты" (0/10)
- `objection_consult` - "Нужна консультация" (0/10)

**Дополнительные поля:**
- `call_type`: "первичка"
- `tone`: "positive"/"neutral"/"negative"
- `customer_satisfaction`: "high"/"medium"/"low"
- `overall_score`: float (среднее по 16 критериям)
- `recommendations`: array[3] (рекомендации по улучшению)
- `conversion`: boolean (опционально)

---

### 2. Вторичка (secondary_call) - 7 критериев

**Описание:** Звонок клиента, который уже имел контакт с клиникой (был на консультации, звонил ранее, проходит лечение).

**Критерии (7):**
1. `greeting` - Приветствие (0/4/6/10)
2. `patient_name` - Имя пациента (0/5/10)
3. `question_clarification` - Уточнение вопроса (0/5/10)
4. `expertise` - Экспертность (0/5/10)
5. `next_step` - Следующий шаг (0/5/10)
6. `emotional_tone` - Эмоциональный окрас (0/4/7/10)
7. `speech` - Речь (0/5-8/9/10)

**Особенности:**
- Фокус на скорости и компетентности
- Экспертность имеет повышенный вес (x2)
- Следующий шаг имеет повышенный вес (x1.5)

**Дополнительные поля:**
- `call_type`: "вторичка"
- `tone`, `customer_satisfaction`, `overall_score`, `recommendations`

---

### 3. Перезвон (re_call) - 8 критериев

**Описание:** Администратор или клиент звонит после предыдущего разговора (обещанный перезвон, возврат к обсуждению записи).

**Критерии (8):**
1. `greeting` - Приветствие (0/4/6/10)
2. `patient_name` - Имя пациента (0/5/10)
3. `appeal` - Апелляция (напоминание о разговоре) (0/5/10)
4. `objection_handling` - Отработка возражений (0/5/10)
5. `next_step` - Следующий шаг (0/5/10)
6. `initiative` - Инициатива (0/5/10)
7. `address_passport` - Адрес и паспорт (0/5/10)
8. `speech` - Речь (0/5-8/9/10)

**Особенности:**
- Критичны: отработка возражений (вес x2), следующий шаг (x1.5), инициатива (x1.5)
- Фокус на доведении до записи

**Дополнительные поля:**
- `call_type`: "перезвон"
- `tone`, `customer_satisfaction`, `overall_score`, `recommendations`

---

### 4. Подтверждение (confirmation_call) - 8 критериев

**Описание:** Администратор звонит клиенту для подтверждения предстоящего визита (обычно за 1-2 дня).

**Критерии (8):**
1. `greeting` - Приветствие (0/4/6/10)
2. `patient_name` - Имя пациента (0/5/10)
3. `appeal` - Апелляция (сообщение о записи) (0/5/10)
4. `objection_handling` - Отработка возражений (перенос/отмена) (0/5/10)
5. `next_step` - Следующий шаг (0/5/10)
6. `initiative` - Инициатива (0/5/10)
7. `address_passport` - Адрес и паспорт (0/5/10)
8. `speech` - Речь (0/5-8/9/10)

**Особенности:**
- Апелляция имеет повышенный вес (x2) - важно четко назвать дату/время
- Цель: снизить количество no-show

**Дополнительные поля:**
- `call_type`: "подтверждение"
- `tone`, `customer_satisfaction`, `overall_score`, `recommendations`

---

### 5. Другое (other_call) - 6 критериев

**Описание:** Нестандартные звонки (жалобы, благодарности, технические вопросы, прочее).

**Критерии (6):**
1. `greeting` - Приветствие (0/4/6/10)
2. `communication` - Коммуникация с клиентом (0/5/10)
3. `expertise` - Экспертность (0/5/10)
4. `problem_solving` - Решение вопроса (0/5/10)
5. `emotional_tone` - Эмоциональный окрас (0/4/7/10)
6. `speech` - Речь (0/5-8/9/10)

**Особенности:**
- Фокус на гибкости и решении нестандартных ситуаций
- Все критерии равноценны

**Дополнительные поля:**
- `call_type`: "другое"
- `tone`, `customer_satisfaction`, `overall_score`, `recommendations`

---

## Файловая структура промптов

### Основные промпты (активные)

```
app/data/prompts/
├── classification_prompt.txt          # Промпт для классификации типа звонка
├── initial_call.txt                   # Первичка - 16 критериев
├── secondary_call.txt                 # Вторичка - 7 критериев
├── re_call.txt                        # Перезвон - 8 критериев
├── confirmation_call.txt              # Подтверждение - 8 критериев
└── other_call.txt                     # Другое - 6 критериев
```

### Enhanced версии (для тестирования, не активны)

```
app/data/prompts/
├── initial_call_enhanced.txt          # Расширенная версия с примерами
├── secondary_call_enhanced.txt
├── re_call_enhanced.txt
├── confirmation_call_enhanced.txt
└── other_call_enhanced.txt
```

**Примечание:** Enhanced версии содержат детальные примеры градации оценок и не используются в продакшене до проведения A/B тестирования.

---

## Сервисы и функции

### 1. CallAnalysisServiceNew

**Файл:** `app/services/call_analysis_service_new.py`

**Ключевые методы:**

#### `__init__()`
```python
def __init__(self, mongodb_service, model_name: str = "gpt-4o-mini", temperature: float = 0.1):
    self.prompts_dir = os.path.join("app", "data", "prompts")
    self.classification_prompt_template = self._load_classification_prompt()
    self.prompt_templates_cache = {}  # Кэш загруженных промптов
```

#### `classify_call(dialogue: str) -> str`
**Назначение:** Классификация типа звонка перед анализом

**Вход:** Транскрипция диалога
**Выход:** Один из типов: "первичка", "вторичка", "перезвон", "подтверждение", "другое"

**Процесс:**
1. Загружает `classification_prompt.txt`
2. Отправляет транскрипцию в OpenAI
3. Получает тип звонка
4. Логирует результат классификации

**Пример:**
```python
call_type = await service.classify_call(transcription)
# -> "первичка"
```

#### `_load_classification_prompt() -> PromptTemplate`
**Назначение:** Загрузка промпта для классификации

**Процесс:**
1. Читает `app/data/prompts/classification_prompt.txt`
2. Создает `PromptTemplate` с переменной `{transcription}`
3. Возвращает шаблон

#### `_load_prompt_for_call_type(call_type: str) -> PromptTemplate`
**Назначение:** Загрузка типо-специфичного промпта с кэшированием

**Маппинг типов на файлы:**
```python
type_to_file = {
    "первичка": "initial_call.txt",
    "вторичка": "secondary_call.txt",
    "перезвон": "re_call.txt",
    "подтверждение": "confirmation_call.txt",
    "другое": "other_call.txt"
}
```

**Процесс:**
1. Проверяет кэш `prompt_templates_cache`
2. Если нет в кэше - читает файл промпта
3. Создает `PromptTemplate` с переменной `{transcription}`
4. Сохраняет в кэш
5. Возвращает шаблон

#### `analyze_call(dialogue: str) -> Dict[str, Any]`
**Назначение:** Основной метод анализа звонка

**Процесс:**
```python
async def analyze_call(self, dialogue: str) -> Dict[str, Any]:
    # 1. Классификация
    call_type = await self.classify_call(dialogue)

    # 2. Загрузка соответствующего промпта
    prompt_template = self._load_prompt_for_call_type(call_type)

    # 3. Создание цепочки LangChain
    chain = prompt_template | self.model | StrOutputParser()

    # 4. Вызов OpenAI
    response = await chain.ainvoke({"transcription": dialogue})

    # 5. Парсинг JSON
    result = json.loads(response_clean)

    # 6. Динамическое извлечение метрик
    metrics = {}
    comments = {}
    for key, value in result.items():
        if isinstance(value, dict) and "score" in value and "comment" in value:
            metrics[key] = value["score"]
            comments[key] = value["comment"]

    # 7. Формирование результата
    return {
        "metrics": metrics,
        "comments": comments,
        "call_type": result.get("call_type"),
        "tone": result.get("tone"),
        "customer_satisfaction": result.get("customer_satisfaction"),
        "overall_score": result.get("overall_score"),
        "recommendations": result.get("recommendations", []),
        "conversion": result.get("conversion")
    }
```

**Ключевая особенность:** Динамическое извлечение метрик позволяет работать с любым количеством критериев без хардкода.

#### `_generate_analysis_text(analysis_data: Dict) -> str`
**Назначение:** Генерация текстового представления анализа

**Процесс:**
1. Извлекает метрики, комментарии, общий балл
2. Формирует читаемый текст с названиями критериев
3. Добавляет рекомендации

---

### 2. CallReportServiceNew

**Файл:** `app/services/call_report_service_new.py`

**Ключевые методы для работы с критериями:**

#### `generate_call_report()` - расширенный список критериев

**Изменение:**
```python
# БЫЛО (только критерии первички):
criteria = [
    'greeting', 'patient_name', 'needs_identification',
    'service_presentation', 'clinic_presentation', 'doctor_presentation',
    # ... только 16 критериев
]

# СТАЛО (все возможные критерии из всех типов):
all_possible_criteria = [
    # Критерии первички (16)
    'greeting', 'patient_name', 'needs_identification',
    'service_presentation', 'clinic_presentation', 'doctor_presentation',
    'patient_booking', 'clinic_address', 'passport', 'price',
    'expertise', 'next_step', 'appointment', 'emotional_tone',
    'speech', 'initiative',

    # Дополнительные критерии вторички
    'question_clarification',

    # Дополнительные критерии перезвона/подтверждения
    'appeal', 'objection_handling', 'address_passport',

    # Дополнительные критерии "другое"
    'communication', 'problem_solving'
]
```

#### Извлечение метрик с обработкой null

**Процесс:**
```python
# Извлекаем все возможные критерии в отдельные колонки
for criterion in all_possible_criteria:
    df_copy[criterion] = df_copy['metrics'].apply(
        lambda x: x.get(criterion, None) if isinstance(x, dict) else None
    )

# Определяем какие критерии реально присутствуют в данных
available_criteria = [
    c for c in all_possible_criteria
    if c in df_copy.columns and df_copy[c].notna().any()
]
```

**Результат:** Если критерий отсутствует в звонке (например, `doctor_presentation` во вторичке), он будет `None` и не повлияет на средние значения.

#### Расчёт средних с игнорированием null

**Процесс:**
```python
for criterion in available_criteria:
    # Фильтруем только ненулевые значения перед группировкой
    avg_by_week = df_copy[df_copy[criterion].notna()].groupby('week_label')[criterion].mean()

    # Результат: среднее считается только по звонкам, где критерий применим
```

**Пример:**
```
Звонок 1 (первичка): doctor_presentation = 8
Звонок 2 (вторичка): doctor_presentation = None
Звонок 3 (первичка): doctor_presentation = 10

Среднее = (8 + 10) / 2 = 9.0   # вторичка не учитывается!
```

#### `_get_criterion_display_name(criterion: str) -> str`

**Расширенный маппинг:**
```python
criterion_names = {
    # Первичка
    'greeting': 'Приветствие',
    'patient_name': 'Имя пациента',
    'needs_identification': 'Выявление потребности',
    # ... все 16 критериев

    # Вторичка
    'question_clarification': 'Уточнение вопроса',

    # Перезвон/Подтверждение
    'appeal': 'Апелляция',
    'objection_handling': 'Отработка возражений',
    'address_passport': 'Адрес и паспорт',

    # Другое
    'communication': 'Коммуникация',
    'problem_solving': 'Решение вопроса'
}
```

---

## Процесс обработки звонка

### Полный цикл от транскрипции до отчёта

```
┌─────────────────────────────────────────────────────────────┐
│  API: POST /api/call-analysis/analyze                       │
│  Input: {"client_id": "...", "note_id": 12345}              │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  1. Загрузка звонка из MongoDB                              │
│     - Проверка наличия транскрипции                         │
│     - Извлечение текста диалога                             │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  2. Классификация типа звонка                               │
│     CallAnalysisServiceNew.classify_call()                  │
│                                                             │
│     Промпт: classification_prompt.txt                       │
│     Модель: gpt-4o-mini                                     │
│     Выход: "первичка" / "вторичка" / "перезвон" /           │
│            "подтверждение" / "другое"                       │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  3. Загрузка типо-специфичного промпта                      │
│     CallAnalysisServiceNew._load_prompt_for_call_type()     │
│                                                             │
│     Маппинг:                                                │
│     "первичка" → initial_call.txt (16 критериев)            │
│     "вторичка" → secondary_call.txt (7 критериев)           │
│     "перезвон" → re_call.txt (8 критериев)                  │
│     "подтверждение" → confirmation_call.txt (8 критериев)   │
│     "другое" → other_call.txt (6 критериев)                 │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  4. AI анализ звонка                                        │
│     CallAnalysisServiceNew.analyze_call()                   │
│                                                             │
│     LangChain: PromptTemplate | Model | StrOutputParser     │
│     Модель: gpt-4o-mini (temperature=0.1)                   │
│     Выход: JSON с метриками и комментариями                 │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  5. Динамическое извлечение метрик                          │
│                                                             │
│     Для каждого ключа в JSON:                               │
│       Если есть поля "score" и "comment":                   │
│         metrics[ключ] = score                               │
│         comments[ключ] = comment                            │
│                                                             │
│     Результат: переменное количество метрик в зависимости   │
│                от типа звонка                               │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  6. Сохранение в MongoDB                                    │
│                                                             │
│     Collection: calls                                       │
│     Update:                                                 │
│       analysis_status: "success"                            │
│       analysis: {                                           │
│         metrics: {...},      # Только релевантные критерии  │
│         comments: {...},                                    │
│         call_type: "...",                                   │
│         overall_score: X.X,                                 │
│         recommendations: [...]                              │
│       }                                                     │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  7. Генерация отчётов (при запросе)                         │
│     CallReportServiceNew.generate_call_report()             │
│                                                             │
│     - Извлечение всех возможных критериев                   │
│     - Фильтрация null значений                              │
│     - Расчёт средних только по ненулевым значениям          │
│     - Группировка по неделям                                │
│     - Создание PDF/Excel                                    │
└─────────────────────────────────────────────────────────────┘
```

---

## Расчёт средних значений в отчётах

### Проблема до исправления

```
Пример данных:
Call 1 (первичка):  greeting=10, doctor_presentation=8, ... (16 критериев)
Call 2 (вторичка):  greeting=9, doctor_presentation=0, ...  (16 критериев, но 9 = null)
Call 3 (первичка):  greeting=8, doctor_presentation=7, ... (16 критериев)

Среднее по doctor_presentation = (8 + 0 + 7) / 3 = 5.0  ❌ НЕПРАВИЛЬНО
```

### Решение

```python
# Шаг 1: Извлечение с None для отсутствующих критериев
df['doctor_presentation'] = df['metrics'].apply(
    lambda x: x.get('doctor_presentation', None) if isinstance(x, dict) else None
)

# Результат:
# Call 1: doctor_presentation = 8
# Call 2: doctor_presentation = None  ✅ явно None, а не 0
# Call 3: doctor_presentation = 7

# Шаг 2: Фильтрация перед расчётом среднего
avg = df[df['doctor_presentation'].notna()]['doctor_presentation'].mean()

# Результат:
# avg = (8 + 7) / 2 = 7.5  ✅ ПРАВИЛЬНО (Call 2 исключён)
```

### Код в CallReportServiceNew

```python
# Извлечение всех возможных критериев
all_possible_criteria = [
    # Первичка (16)
    'greeting', 'patient_name', 'needs_identification', 'service_presentation',
    'clinic_presentation', 'doctor_presentation', 'patient_booking',
    'clinic_address', 'passport', 'price', 'expertise', 'next_step',
    'appointment', 'emotional_tone', 'speech', 'initiative',
    # Вторичка
    'question_clarification',
    # Перезвон/Подтверждение
    'appeal', 'objection_handling', 'address_passport',
    # Другое
    'communication', 'problem_solving'
]

# Создание колонок с None для отсутствующих критериев
for criterion in all_possible_criteria:
    df_copy[criterion] = df_copy['metrics'].apply(
        lambda x: x.get(criterion, None) if isinstance(x, dict) else None
    )

# Определение реально присутствующих критериев
available_criteria = [
    c for c in all_possible_criteria
    if c in df_copy.columns and df_copy[c].notna().any()
]

# Расчёт средних с фильтрацией null
for criterion in available_criteria:
    # Фильтруем ненулевые значения перед группировкой
    avg_by_week = df_copy[df_copy[criterion].notna()].groupby('week_label')[criterion].mean()
```

---

## Примеры работы

### Пример 1: Первичный звонок

**Транскрипция:**
```
Администратор: Добрый день, клиника "Улыбка", Анна слушает
Клиент: Здравствуйте, хочу узнать про имплантацию
Администратор: Отлично! Как вас зовут?
Клиент: Иван
...
```

**Процесс:**
1. **Классификация:** `classify_call()` → "первичка"
2. **Промпт:** Загружен `initial_call.txt`
3. **Анализ:** Оценка по 16 критериям
4. **Результат:**
```json
{
  "metrics": {
    "greeting": 10,
    "patient_name": 7,
    "needs_identification": 8,
    "service_presentation": 6,
    "clinic_presentation": 7,
    "doctor_presentation": 8,
    "patient_booking": 10,
    "clinic_address": 10,
    "passport": 10,
    "price": 6,
    "expertise": 10,
    "next_step": 10,
    "appointment": 10,
    "emotional_tone": 10,
    "speech": 10,
    "initiative": 8
  },
  "call_type": "первичка",
  "overall_score": 8.75,
  "recommendations": [...]
}
```

### Пример 2: Вторичный звонок

**Транскрипция:**
```
Администратор: Клиника "Улыбка", здравствуйте
Клиент: Здравствуйте, я у вас был на консультации, хочу уточнить стоимость
...
```

**Процесс:**
1. **Классификация:** `classify_call()` → "вторичка"
2. **Промпт:** Загружен `secondary_call.txt`
3. **Анализ:** Оценка по 7 критериям
4. **Результат:**
```json
{
  "metrics": {
    "greeting": 6,
    "patient_name": 5,
    "question_clarification": 10,
    "expertise": 10,
    "next_step": 10,
    "emotional_tone": 7,
    "speech": 10
  },
  "call_type": "вторичка",
  "overall_score": 8.29,
  "recommendations": [...]
}
```

**Важно:** Нет критериев `doctor_presentation`, `clinic_presentation` и др., которые неприменимы к вторичному звонку.

### Пример 3: Расчёт средних в отчёте

**Данные:**
```
Call 1 (первичка):   greeting=10, doctor_presentation=8, question_clarification=None
Call 2 (вторичка):   greeting=9,  doctor_presentation=None, question_clarification=10
Call 3 (первичка):   greeting=8,  doctor_presentation=7, question_clarification=None
Call 4 (подтверждение): greeting=10, doctor_presentation=None, question_clarification=None
```

**Расчёт средних:**
- **greeting:** (10 + 9 + 8 + 10) / 4 = 9.25 ✅ (все 4 звонка)
- **doctor_presentation:** (8 + 7) / 2 = 7.5 ✅ (только первички)
- **question_clarification:** 10 / 1 = 10.0 ✅ (только вторичка)

---

## Связанные файлы

### Основные компоненты

| Файл | Назначение |
|------|-----------|
| `app/services/call_analysis_service_new.py` | Сервис анализа звонков (классификация + анализ) |
| `app/services/call_report_service_new.py` | Сервис генерации отчётов с корректными средними |
| `app/routers/call_analysis.py` | API эндпоинт `/api/call-analysis/analyze` |
| `app/routers/call_reports.py` | API эндпоинты для генерации отчётов |

### Промпты

| Файл | Тип звонка | Критериев |
|------|-----------|-----------|
| `app/data/prompts/classification_prompt.txt` | Классификация | - |
| `app/data/prompts/initial_call.txt` | Первичка | 16 + 6 возражений |
| `app/data/prompts/secondary_call.txt` | Вторичка | 7 |
| `app/data/prompts/re_call.txt` | Перезвон | 8 |
| `app/data/prompts/confirmation_call.txt` | Подтверждение | 8 |
| `app/data/prompts/other_call.txt` | Другое | 6 |

### Тесты

| Файл | Назначение |
|------|-----------|
| `tests/test_full_conversion_check.py` | Тесты конверсий (обновлен для новой логики) |

---

## Конфигурация

### Переменные окружения

```bash
# OpenAI для анализа
OPENAI=sk-...

# Модель для анализа (по умолчанию gpt-4o-mini)
ANALYSIS_MODEL=gpt-4o-mini

# Temperature для более стабильных результатов (по умолчанию 0.1)
ANALYSIS_TEMPERATURE=0.1
```

### Параметры в коде

**CallAnalysisServiceNew:**
```python
def __init__(
    self,
    mongodb_service,
    model_name: str = "gpt-4o-mini",  # Модель
    temperature: float = 0.1          # Детерминированность
):
```

---

## Миграция и обратная совместимость

### Что изменилось в MongoDB

**Старая структура:**
```json
{
  "analysis": {
    "metrics": {
      "greeting": 10,
      "doctor_presentation": 0,  // 0 для неприменимых критериев
      ...
    }
  }
}
```

**Новая структура:**
```json
{
  "analysis": {
    "metrics": {
      "greeting": 10,
      // doctor_presentation отсутствует если неприменим
    },
    "call_type": "вторичка"
  }
}
```

### Обратная совместимость

Сервис `CallReportServiceNew` работает с обеими структурами:
- Если критерий отсутствует → `None`
- Если критерий = 0 в старых данных → будет учтён как 0 (но можно отфильтровать)

---

## Мониторинг и логирование

### Логи классификации

```python
logger.info(f"Call classified as: {call_type}")
```

**Пример лога:**
```
2025-11-18 10:30:45 INFO Call classified as: первичка
```

### Логи загрузки промптов

```python
logger.info(f"Loading prompt for call type: {call_type}")
logger.info(f"Prompt loaded from cache for type: {call_type}")
```

### Ошибки

```python
logger.error(f"Failed to load prompt file {prompt_file}: {e}")
logger.error(f"Error analyzing call {note_id}: {str(e)}")
```

---

## Производительность

### Кэширование промптов

Промпты загружаются один раз при первом использовании и кэшируются в памяти:

```python
self.prompt_templates_cache = {
    "первичка": PromptTemplate(...),
    "вторичка": PromptTemplate(...),
    # ... остальные
}
```

**Экономия:** Нет повторного чтения файлов с диска при каждом анализе.

### Параллельная обработка

Для массовой обработки звонков используется параллельный вызов `analyze_call()`:

```python
tasks = [service.analyze_call(transcription) for transcription in transcriptions]
results = await asyncio.gather(*tasks)
```

---

## Будущие улучшения

### Планируется

1. **A/B тестирование enhanced промптов**
   - Сравнить качество оценки regular vs enhanced промптов
   - Метрики: согласованность с человеческой оценкой, детальность комментариев

2. **Автоматическая калибровка весов критериев**
   - Использовать машинное обучение для определения оптимальных весов
   - Учитывать корреляцию критериев с конверсией

3. **Дополнительные типы звонков**
   - "Жалоба" (специфичные критерии работы с негативом)
   - "Отмена" (фокус на удержании клиента)

4. **Многоязычная поддержка**
   - Промпты на английском для интернациональных клиник

5. **Система подсказок для администраторов**
   - Real-time анализ звонка
   - Автоматические подсказки во время разговора

---

## FAQ

**Q: Что если AI неправильно классифицирует тип звонка?**
A: В MongoDB сохраняется поле `call_type` - можно вручную переопределить и запустить повторный анализ.

**Q: Можно ли использовать другую модель OpenAI?**
A: Да, в конструкторе `CallAnalysisServiceNew` передайте `model_name="gpt-4"`.

**Q: Как добавить новый критерий в существующий тип звонка?**
A: 1) Обновить промпт-файл, 2) Добавить критерий в `all_possible_criteria` в `call_report_service_new.py`, 3) Обновить `_get_criterion_display_name()`.

**Q: Почему используется temperature=0.1?**
A: Для максимальной детерминированности и согласованности оценок. При высокой температуре один звонок может получить разные оценки при повторном анализе.

**Q: Можно ли анализировать звонки на других языках?**
A: Да, OpenAI поддерживает множество языков, но промпты нужно адаптировать под культурные особенности и стандарты обслуживания.

---

## Контакты и поддержка

**Разработчик:** MedAI Team
**Версия:** 4.0
**Последнее обновление:** 18.11.2025

Для вопросов и предложений: см. `CLAUDE.md` и `CURRENT_ARCHITECTURE.md`
