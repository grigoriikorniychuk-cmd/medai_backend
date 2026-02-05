# Техническое задание на разработку Telegram бота для работы с клиниками и звонками

## 1. Общие сведения

### 1.1. Назначение

Создание Telegram бота для автоматизации процессов регистрации клиник, получения и анализа звонков из AmoCRM, с возможностью транскрибации звонков и формирования аналитических отчетов.

### 1.2. Технологический стек

- Python 3.x
- aiogram 3.x
- MongoDB
- Docker
- Интеграция с существующим бэкендом на FastAPI

## 2. Архитектура проекта

### 2.1. Структура проекта

```
bot/
├── __init__.py
├── __main__.py
├── config/
│   ├── __init__.py
│   └── config.py
├── handlers/
│   ├── __init__.py
│   ├── common.py
│   ├── registration.py
│   ├── leads.py
│   └── reports.py
├── keyboards/
│   ├── __init__.py
│   ├── registration_kb.py
│   ├── leads_kb.py
│   └── reports_kb.py
├── middlewares/
│   ├── __init__.py
│   └── logging.py
├── models/
│   ├── __init__.py
│   └── database.py
├── states/
│   ├── __init__.py
│   └── states.py
├── utils/
│   ├── __init__.py
│   ├── api.py
│   └── helpers.py
├── Dockerfile
├── requirements.txt
└── README.md
```

### 2.2. Модели базы данных

В MongoDB хранится информация в следующих коллекциях:

#### 2.2.1. Коллекция `clinics`

Хранит информацию о зарегистрированных клиниках и их настройках для AmoCRM.

```json
{
  "_id": "0f66c46a-b2a5-412b-9b56-f5b41bc02bbb",
  "name": "stomdv", // Название клиники
  "telegram_ids": 806652480, // ID пользователя(ей) Telegram, привязанных к клинике
  "amocrm_subdomain": "stomdv", // Поддомен AmoCRM
  "client_id": "906c06fb-1844-4892-9dc6-6a4e30129fdf", // ID клиента AmoCRM
  "client_secret": "sc9Il1nwJQxK5woYWll9wjq1hUWo4GilwEVubKOxv2N8laP0bz7wBzqTzDQIOJIh", // Секрет клиента AmoCRM
  "redirect_url": "https://mlab-electronics.ru", // URL перенаправления
  "auth_code": "def502007a0cb04835136fe29730d81640a7ec97c4857e40d84e4d6c5d75369cbc29ba4c66d585d741da206dfd71a3b7bc8022aefb8af88abbbaad565c5dfce95b1510414b97a2316161bc1bc85215e467403b903990930eb358ecb3d21a0620c240637105ff65d4a8372fe8e01cd993a52282ed9618fd21589f21341ccc9a133149c061662aaadda6359ed274e1b4d856f750c5ee23c24ae0e6f08c665e100c17557cb2eba5b7ce817face8664048bb789b45f785f9d9b3ce53404a048c71d2f5dfc924293ffa4081a163e8a3d37b482209ea57dab4b7a04842a2493993d81775fce90e58241b43301a0490c15927da43d09167af7cb788c3c7c754343a43945898db2ad7a61222f75d768f195e3cbde714890b76567ed6ce3cc67e9b3120bc526a3ee845dab511587e494819df7b48145ed896aa7d3d3c362f9c67c638461a8c2ddd46069491f0673cf0fd4ea7c890b24d75e38533071b28c35682ba38341ff81a453632773e019d38dd6d86a5a50322fe38b33e7298db89aff1ccc832274bc1af746eb8d8b7db1ab06dcd4b6de5eab13c0c6c91441ddbd2d8816a8b4d916366b26bcced60bfab913cd0da5eeeb453bc05e8e277e176f25a2c2fee248d7d46fa29ab34609506c24518219b94daf6bed65d6dee7dfe43071167e1f88a81b0dbd82c0b8f2956555ab5e063", // Код авторизации
  "amocrm_pipeline_id": "0", // ID воронки в AmoCRM
  "monthly_limit": 100, // Месячный лимит использований
  "current_month_usage": 0, // Текущее использование в этом месяце
  "last_reset_date": {
    // Дата последнего сброса счетчика
    "$date": "2025-05-01T04:57:58.016Z"
  },
  "created_at": {
    // Дата создания
    "$date": "2025-05-01T04:57:58.016Z"
  },
  "updated_at": {
    // Дата обновления
    "$date": "2025-05-01T04:57:58.016Z"
  },
  "administrator_ids": [] // Массив ID администраторов
}
```

#### 2.2.2. Коллекция `tokens`

Хранит токены доступа к API AmoCRM.

```json
{
  "_id": {
    "$oid": "6812d52692c795b61790294d"
  },
  "client_id": "906c06fb-1844-4892-9dc6-6a4e30129fdf", // ID клиента AmoCRM
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiIsImp0aSI6IjU0MzQ3MWYyODRhNGEyMTZlMjg4NjAxNzgzMDYyOTg4Zjc3Njk1ZWFhMmE5YTU5ZWU3MjhhZjQ2NjEzZjQyNTYyODEyZDU1Yjg4ZmMyMGQ0In0.eyJhdWQiOiI3YjUzYzU1My1kODlkLTRiYmUtOTU0MC0yNDQ0MTczM2Q2NWEiLCJqdGkiOiI1NDM0NzFmMjg0YTRhMjE2ZTI4ODYwMTc4MzA2Mjk4OGY3NzY5NWVhYTJhOWE1OWVlNzI4YWY0NjYxM2Y0MjU2MjgxMmQ1NWI4OGZjMjBkNCIsImlhdCI6MTc0NTkxNDU0NCwibmJmIjoxNzQ1OTE0NTQ0LCJleHAiOjE3NDYwMDA0NjYsInN1YiI6IjgyMjI2OTgiLCJncmFudF90eXBlIjoiIiwiYWNjb3VudF9pZCI6MzAxODk0OTAsImJhc2VfZG9tYWluIjoiYW1vY3JtLnJ1IiwidmVyc2lvbiI6Miwic2NvcGVzIjpbInB1c2hfbm90aWZpY2F0aW9ucyIsImZpbGVzIiwiY3JtIiwiZmlsZXNfZGVsZXRlIiwibm90aWZpY2F0aW9ucyJdLCJoYXNoX3V1aWQiOm51bGwsImFwaV9kb21haW4iOiJhcGktYi5hbW9jcm0ucnUifQ.CjiEey-5ROJN9HQNdypHBZs-Kzg11DGMWOyCA9lK_9FClngBBm2wFtg9--eyfxl-iQas0SDzAinnu62Q0e9cAfQcJio-hmGcHLuFfZTsQStduQsmoiOd3m8x6ZTtL2vxhfHLoP19ja7qZzk8lfFPDxtYgUd0jaEiun_Of_r6k_poyMCYr8sele7NueXp6OoR-U9rnObN8MCT-fV3Ggx5SZfc8cgTWznVd1oh_WnRmSWIbBGIHlSr_NBdVJeZS3ONCeVuXKtjtExkvjIFiXKS60FY0gQzrQlM8d3mYT1VVP6LHk4PfZA-wK5UvmV7xsfh9-e6WzZUvKcsiTQEQGJyjw", // Токен доступа
  "refresh_token": "def50200f7056b548fde0765f7f287fa0f524a3f1c4e9008d800f1196217a0e0dc4afa4ea6e4398d1dc3f3ef17c8248e7c78af54bb6912258d6ce6896eeea840c6da95cd3fb59fc29c7d9012c861c250047ac3ab2d15359ff614b83a0b3e24a5739b3a846a43303cb725e408fc0fdea881e4f5b5ea0a3316a748330558261fcf55e57b1ecfef6f46bc241c948092dbd8b6997c99fee9dd813cc6b09f1b1f6b350def02ef78d5318ffb0d4607724b57dfe4391c713a366662317db604d3f63a3ccb2a4ab7c3762f167e64c527c0abaede863759bbd334446c229fda33835ecaffb271ae392d4879aab1a438e60b704aca176e9bbf69ddad734e64497b88548d01fe6ad98e69d7f74c49b0bdb146392b222f12c7973ffbdd606acbda82529ebb2b724c3fbe1a8ccb571533ebffd830578c29b7cd608a5f2b547c6f4a867589cf3b2e8738289ad4d73610d12e930ee08235dc7e9a5b2d6f8f183305326d01a8e76f81c863b9407d57a68ce0f43c01dcc41d17c2392fdbcb72d53effb3497f6fcffbc53fcdbbca509831a1007188e53da2e47f45043b04ec5c786367a629272531b0b014279db6b976112e74ad6f5efa2056bb52adba342a319865bb7ecee5a4c163f41026b0204d5c07abb0f240e3a7d4a74162dc602c74df001f44cc5c1755bd3d98281a345c717c4b098e8c8b62", // Токен обновления
  "subdomain": "stomdv", // Поддомен AmoCRM
  "updated_at": {
    // Дата обновления токенов
    "$date": "2025-05-01T04:57:58.021Z"
  }
}
```

#### 2.2.3. Коллекция `administrators`

Хранит информацию об администраторах клиник.

```json
{
  "_id": "44a84022-1530-42d9-9b34-742e5a72eefc",
  "clinic_id": "67f0ef0cf4949b466e297b94", // ID клиники
  "name": "Администратор по умолчанию", // Имя администратора
  "amocrm_user_id": "default_admin", // ID пользователя в AmoCRM
  "email": null, // Email администратора
  "monthly_limit": null, // Индивидуальный месячный лимит
  "current_month_usage": 0, // Текущее использование в этом месяце
  "created_at": "2025-04-29T11:31:44.493929", // Дата создания
  "updated_at": "2025-04-29T11:31:44.493929" // Дата обновления
}
```

#### 2.2.4. Коллекция `calls`

Хранит информацию о звонках и результатах их анализа.

**Базовая структура звонка**:

```json
{
  "_id": {
    "$oid": "680d508de3b778a70ce02212"
  },
  "note_id": 521214589, // ID заметки в AmoCRM
  "lead_id": 51461945, // ID сделки в AmoCRM
  "lead_name": "Новая сделка (+79825969581)", // Название сделки
  "client_id": "7b53c553-d89d-4bbe-9540-24441733d65a", // ID клиента
  "subdomain": "vladleneliz", // Поддомен AmoCRM
  "contact_id": 69058197, // ID контакта в AmoCRM
  "contact_name": "Рахимова Алия Айратовна", // Имя контакта
  "administrator": "Янина Е.П.", // Имя администратора
  "source": "Звонок", // Источник
  "processing_speed": 5, // Скорость обработки
  "processing_speed_str": "5-10 мин", // Строковое представление скорости обработки
  "call_direction": "Входящий", // Направление звонка
  "duration": 26, // Длительность в секундах
  "duration_formatted": "0:26", // Форматированная длительность
  "phone": "+79825969581", // Номер телефона
  "call_link": "https://vladleneliz.amocrm.ru/api/v4/contacts/69058197/notes/521214589?page=1&limit=100&userId=8223928&accountId=30189490&download=true", // Ссылка на запись звонка
  "created_at": 1745388070, // Timestamp создания
  "created_date": "2025-04-23 09:01:10", // Форматированная дата создания
  "recorded_at": {
    // Дата записи в базу
    "$date": "2025-04-27T00:30:53.487Z"
  },
  "amocrm_user_id": 8223928 // ID пользователя AmoCRM
}
```

**Расширенная структура после транскрибации и анализа**:

```json
{
  "_id": {
    "$oid": "680d5095e3b778a70ce02219"
  },
  "note_id": 521197165,
  "lead_id": 51458063,
  "lead_name": "Новая сделка (+79505168020)",
  "client_id": "7b53c553-d89d-4bbe-9540-24441733d65a",
  "subdomain": "vladleneliz",
  "contact_id": 69056549,
  "contact_name": "Коваленко Владимир Владимирович",
  "administrator": "Янина Е.П.",
  "source": "Звонок",
  "processing_speed": 5,
  "processing_speed_str": "5-10 мин",
  "call_direction": "Входящий",
  "duration": 25,
  "duration_formatted": "0:25",
  "phone": "+79505168020",
  "call_link": "https://api.cloudpbx.rt.ru:443/amo/widget/get_temp_record_url/?session_id=SDij-w3jpbdxIpCHO&account_id=30189490&userId=8222698&accountId=30189490&download=true",
  "created_at": 1745319051,
  "created_date": "2025-04-22 13:50:51",
  "recorded_at": {
    "$date": "2025-04-27T00:31:01.803Z"
  },
  "amocrm_user_id": 8223928,
  "filename_audio": "lead_51458063_note_521197165.mp3", // Имя файла аудиозаписи
  "filename_transcription": "79505168020_20250427_003123.txt", // Имя файла транскрипции
  "transcription_status": "processing", // Статус транскрибации
  "updated_at": {
    // Дата обновления
    "$date": "2025-04-27T01:15:04.404Z"
  },
  "analysis": "79505168020_20250427_003123_analysis.txt", // Имя файла с анализом
  "analysis_id": "680d5ae8e3b778a70ce0221f", // ID анализа
  "analyzed_at": {
    // Дата анализа
    "$date": "2025-04-27T01:15:04.404Z"
  },
  "call_category": "Запись на приём", // Категория звонка
  "metrics": {
    // Метрики анализа
    "greeting": 6,
    "needs_identification": 5,
    "solution_proposal": 5,
    "objection_handling": 5,
    "call_closing": 2,
    "tone": "neutral",
    "customer_satisfaction": "medium",
    "overall_score": 2
  },
  "recommendations": [
    // Рекомендации по улучшению
    "Уделить больше внимания выяснению потребностей клиента, задавая уточняющие вопросы.",
    "Включить в разговор презентацию услуг клиники и врачей, чтобы повысить доверие клиента.",
    "Предоставить клиенту информацию о ценах и адресе клиники, а также предложить несколько вариантов времени для записи."
  ]
}
```

#### 2.2.5. Связи между коллекциями

- **clinics** и **tokens** связаны через поле `client_id`
- **clinics** и **administrators** связаны через поле `clinic_id` в коллекции administrators и идентификаторы в массиве `administrator_ids` в коллекции clinics
- **calls** связаны с **clinics** через поле `client_id`
- Пользователи Telegram привязываются к клиникам через поле `telegram_ids` в коллекции clinics

## 3. Основной функционал

### 3.1. Команды бота

- `/start` - Начало работы с ботом, приветствие
- `/help` - Справка по работе с ботом
- `/register` - Регистрация новой клиники
- `/cancel` - Отмена текущей операции
- `/leads` - Получение списка сделок
- `/report` - Создание отчета по звонкам

### 3.2. Регистрация клиники

#### 3.2.1. Процесс регистрации

1. Пользователь вводит команду `/register`
2. Бот запрашивает:
   - Название клиники
   - AmoCRM поддомен
   - Client ID
   - Client Secret
   - Redirect URL
   - Auth Code
   - AmoCRM Pipeline ID
   - Месячный лимит звонков
3. Данные отправляются на эндпоинт `/api/admin/clinics`
4. Telegram ID пользователя привязывается к клинике в базе данных
5. Пользователь получает подтверждение об успешной регистрации

#### 3.2.2. Используемые методы API

- POST `/api/admin/clinics` - Регистрация клиники
- POST `/api/admin/clinics/{clinic_id}/refresh-token` - Автоматическое обновление токенов

### 3.3. Работа со сделками

#### 3.3.1. Получение сделок

1. Пользователь вводит команду `/leads`
2. Бот предлагает выбрать дату или ввести её вручную
3. Выполняется синхронизация с AmoCRM через эндпоинт `/api/calls/sync-by-date`
4. Пользователю отображаются сделки с карточками, содержащими информацию:
   - Название сделки
   - Дата создания
   - Ответственный
   - Кнопки для работы со звонками

#### 3.3.2. Работа со звонками

1. Пользователь может:
   - Посмотреть список звонков для сделки (через коллекцию calls)
   - Скачать запись звонка
   - Запустить транскрибацию звонка
   - Скачать транскрибацию звонка
   - Провести анализ звонка через LLM
   - Просмотреть результаты анализа

#### 3.3.3. Используемые методы API

- POST `/api/calls/sync-by-date` - Синхронизация звонков с AmoCRM
- GET `/api/calls/list` - Получение списка звонков
- GET `/api/calls/download/{call_id}` - Скачивание аудиофайла звонка
- POST `/api/calls/download-and-transcribe/{call_id}` - Транскрибация звонка
- GET `/api/transcriptions/{filename}/download` - Скачивание транскрибации
- POST `/api/call/analyze-call-new/{call_id}` - Анализ звонка через LLM

### 3.4. Работа с отчетами

#### 3.4.1. Генерация отчетов

1. Пользователь вводит команду `/report`
2. Бот предлагает указать:
   - Начальную дату (DD.MM.YYYY)
   - Конечную дату (DD.MM.YYYY)
   - ID клиники (опционально)
   - ID администраторов (опционально, через запятую)
3. Отправляется запрос на генерацию отчета
4. После генерации пользователь получает уведомление и кнопку для скачивания отчета

#### 3.4.2. Используемые методы API

- POST `/api/reports/generate_call_report` - Генерация отчета
- GET `/api/call/reports/{filename}/download` - Скачивание отчета

## 4. Конечные состояния (FSM)

### 4.1. Регистрация клиники

```python
class ClinicRegistration(StatesGroup):
    name = State()                  # Название клиники
    amocrm_subdomain = State()      # Поддомен AmoCRM
    client_id = State()             # Client ID
    client_secret = State()         # Client Secret
    redirect_url = State()          # Redirect URL
    auth_code = State()             # Auth Code
    amocrm_pipeline_id = State()    # AmoCRM Pipeline ID
    monthly_limit = State()         # Месячный лимит
    confirmation = State()          # Подтверждение
```

### 4.2. Получение сделок

```python
class LeadsRequest(StatesGroup):
    date = State()                  # Дата для поиска сделок
    lead_selection = State()        # Выбор сделки из списка
```

### 4.3. Генерация отчета

```python
class ReportGeneration(StatesGroup):
    start_date = State()            # Начальная дата
    end_date = State()              # Конечная дата
    clinic_id = State()             # ID клиники (опционально)
    admin_ids = State()             # ID администраторов (опционально)
    confirmation = State()          # Подтверждение
```

## 5. Взаимодействие с API

### 5.1. Модуль utils/api.py

Должен содержать функции для взаимодействия с API бэкенда:

```python
async def register_clinic(data: dict) -> dict:
    """Регистрация новой клиники"""
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{API_URL}/api/admin/clinics", json=data) as response:
            return await response.json()

async def refresh_token(clinic_id: str, client_secret: str = None, redirect_url: str = None) -> dict:
    """Обновление токена клиники"""
    params = {}
    if client_secret:
        params["client_secret"] = client_secret
    if redirect_url:
        params["redirect_url"] = redirect_url

    async with aiohttp.ClientSession() as session:
        async with session.post(f"{API_URL}/api/admin/clinics/{clinic_id}/refresh-token", params=params) as response:
            return await response.json()

async def sync_calls_by_date(date: str, client_id: str) -> dict:
    """Синхронизация звонков по дате"""
    params = {"date": date, "client_id": client_id}
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{API_URL}/api/calls/sync-by-date", params=params) as response:
            return await response.json()

async def get_calls_list(client_id: str, start_date: str = None, end_date: str = None, limit: int = 50, skip: int = 0) -> dict:
    """Получение списка звонков"""
    params = {"limit": limit, "skip": skip}
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date

    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_URL}/api/calls/list", params=params) as response:
            return await response.json()

async def download_call(call_id: str) -> str:
    """Получение URL для скачивания звонка"""
    return f"{API_URL}/api/calls/download/{call_id}"

async def download_and_transcribe_call(call_id: str, num_speakers: int = 2) -> dict:
    """Скачивание и транскрибация звонка"""
    params = {"num_speakers": num_speakers}
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{API_URL}/api/calls/download-and-transcribe/{call_id}", params=params) as response:
            return await response.json()

async def download_transcription(filename: str) -> str:
    """Получение URL для скачивания транскрибации"""
    return f"{API_URL}/api/transcriptions/{filename}/download"

async def analyze_call(call_id: str) -> dict:
    """Анализ звонка через LLM"""
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{API_URL}/api/call/analyze-call-new/{call_id}") as response:
            return await response.json()

async def generate_report(report_data: dict) -> dict:
    """Генерация отчета"""
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{API_URL}/api/reports/generate_call_report", json=report_data) as response:
            return await response.json()

async def download_report(filename: str) -> str:
    """Получение URL для скачивания отчета"""
    return f"{API_URL}/api/call/reports/{filename}/download"
```

## 6. Обработка ошибок

### 6.1. Общие требования

- Все запросы к API должны быть обёрнуты в try-except блоки
- При возникновении ошибок должны выводиться понятные пользователю сообщения
- Автоматическое обновление токенов при получении ошибок авторизации в AmoCRM
- Логирование всех ошибок в консоль и в файл

### 6.2. Обработчик ошибок aiogram

```python
@dp.errors_handler()
async def errors_handler(update, exception):
    """
    Обработка необработанных исключений
    """
    # Логирование ошибок
    # Отправка уведомления пользователю
    # Возможный сброс состояния FSM
```

## 7. Клавиатуры и интерфейс

### 7.1. Основная клавиатура

- "Зарегистрировать клинику" (если нет привязанных клиник)
- "Получить сделки"
- "Создать отчет"
- "Помощь"

### 7.2. Клавиатуры для lead_card (сделки)

- "Показать звонки"
- "Скрыть звонки"
- "Транскрибировать" (для каждого звонка)
- "Скачать запись" (для каждого звонка)
- "Скачать транскрибацию" (если есть)
- "Анализировать звонок" (если есть транскрибация)

### 7.3. Клавиатуры для отчетов

- "Подтвердить параметры"
- "Отмена"
- "Скачать отчет" (после генерации)

## 8. Docker-интеграция

### 8.1. Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "-m", "bot"]
```

### 8.2. requirements.txt

```
aiogram>=3.0.0
python-dotenv>=1.0.0
aiohttp>=3.8.0
motor>=3.1.1
pymongo>=4.3.3
aiofiles>=23.1.0
```

### 8.3. docker-compose.yml (дополнение к существующему)

```yaml
services:
  telegram-bot:
    build:
      context: ./bot
      dockerfile: Dockerfile
    container_name: medai-telegram-bot
    restart: unless-stopped
    environment:
      - BOT_TOKEN=
      - API_URL=http://backend:8000
      - MONGODB_URL=mongodb://mongo:27017/medai
    depends_on:
      - backend
      - mongo
```

## 9. Обработка пользовательских запросов

### 9.1. Авторизация пользователей

- Пользователи идентифицируются по Telegram ID
- Для использования функций бота пользователь должен быть привязан к клинике
- Если Telegram ID привязан к нескольким клиникам, предлагается выбор клиники

### 9.2. Ограничения доступа

- Функции работы со сделками и отчетами доступны только авторизованным пользователям
- Лимиты на количество запросов транскрибации в месяц (согласно monthly_limit клиники)

## 10. Интеграционное тестирование

### 10.1. Тестовые сценарии

- Регистрация клиники
- Получение сделок по дате
- Скачивание и транскрибация звонка
- Генерация и скачивание отчета

### 10.2. Инструменты для тестирования

- Имитация взаимодействия с Telegram API
- Mocking ответов от бэкенд API
- Тестовые данные для проверки функциональности

## 11. Документация

### 11.1. Инструкция по установке

- Настройка переменных окружения
- Запуск через Docker
- Запуск вручную

### 11.2. Руководство пользователя

- Описание всех команд
- Примеры использования
- Ответы на часто задаваемые вопросы

## 12. Требования к коду

### 12.1. Стиль кодирования

- Соответствие PEP 8
- Типизация с использованием type hints
- Документирование функций и классов

### 12.2. Организация кода

- Модульность
- Разделение ответственности
- Эффективное использование FSM aiogram 3.x

## 13. Сроки и этапы реализации

1. Настройка базовой структуры проекта
2. Реализация регистрации клиник
3. Реализация работы со сделками и звонками
4. Реализация генерации отчетов
5. Интеграционное тестирование
6. Документация и оптимизация

## 14. Приоритеты разработки

1. Основной функционал: регистрация, получение сделок, транскрибация
2. Пользовательский интерфейс (клавиатуры, сообщения)
3. Обработка ошибок и надежность
4. Оптимизация и документация

---

Данное техническое задание предоставляет комплексное описание функционала и структуры Telegram бота для работы с клиниками и звонками, интегрированного с существующим бэкендом на FastAPI и MongoDB.
