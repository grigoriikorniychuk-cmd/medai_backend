# MedAI Backend

FastAPI-приложение для обработки звонков клиник из AmoCRM: транскрибация через ElevenLabs, AI-анализ через OpenAI, отчёты и Telegram-бот.

## Стек

- **Python 3.12**, FastAPI, uvicorn
- **MongoDB** — основное хранилище (звонки, клиники, токены)
- **PostgreSQL** — метрики для DataLens
- **Docker Compose** — оркестрация сервисов
- **aiogram** — Telegram-бот
- **ElevenLabs API** — транскрибация с diarization
- **OpenAI API** — AI-анализ звонков

## Структура проекта

```
app/
├── routers/                          # API эндпоинты
│   ├── calls_events.py               # Синхронизация звонков через AmoCRM Events API
│   ├── calls.py                      # Транскрибация и скачивание аудио
│   ├── call_reports.py               # Генерация PDF/Excel отчётов
│   ├── clinics.py                    # Управление клиниками и лимитами
│   ├── classification_analysis.py    # AI-анализ звонков
│   ├── calls_parallel_bulk.py        # Массовая параллельная синхронизация
│   ├── work_schedules.py             # Графики работы администраторов
│   ├── postgres_sync.py              # Синхронизация MongoDB → PostgreSQL
│   ├── transcription.py              # Скачивание транскрипций
│   └── admin.py                      # Административные эндпоинты
├── services/                         # Бизнес-логика
│   ├── mongodb_service.py            # Работа с MongoDB
│   ├── transcription_service.py      # ElevenLabs интеграция
│   ├── amo_sync_service.py           # Синхронизация с AmoCRM
│   ├── call_analysis_service_new.py  # AI-анализ через OpenAI
│   ├── call_report_service_new.py    # Генерация отчётов
│   ├── clinic_limits_service.py      # Лимиты транскрибации (месячные + недельные)
│   └── generate_report.py            # Генерация PDF/Excel с гиперссылками
├── middleware/                       # Middleware
│   └── api_key_auth.py               # Аутентификация по API ключу
├── models/                           # Pydantic модели
├── settings/                         # Конфигурация
└── utils/                            # Утилиты

bot/                                  # Telegram-бот (aiogram)
├── handlers/                         # Обработчики команд
├── keyboards/                        # Клавиатуры
└── config/                           # Конфигурация бота

datalens/                             # Синхронизация MongoDB → PostgreSQL для DataLens
├── postgres_exporter.py              # Экспорт данных из MongoDB в PostgreSQL
└── __init__.py

scripts/                              # Утилитарные скрипты
├── auto_sync_all_clinics.py          # Ежедневная синхронизация всех клиник
├── daily_sync.py                     # Синхронизация одной клиники
├── reset_weekly_limits.py            # Ручной сброс недельных лимитов
└── recalculate_admins_jan5.py        # Пересчёт администраторов

tests/                                # Тесты
```

## Основной поток данных

```
AmoCRM Events API
  → POST /api/calls-events/export
  → detect_conversion_config()
  → enrich_calls_with_conversion()
  → MongoDB (коллекция calls)
  → POST /api/calls/transcribe
  → ElevenLabs API (транскрибация + diarization)
  → amo_sync_service (синхронизация заметок в AmoCRM)
  → POST /api/call-analysis/analyze
  → OpenAI API (анализ)
  → MongoDB (обновление результата)
  → postgres_sync / datalens/postgres_exporter.py
  → PostgreSQL (метрики для DataLens)
```

## Запуск

### Docker (продакшен)

```bash
docker-compose up -d
```

Сервисы:
| Сервис | Порт (хост) | Описание |
|--------|-------------|----------|
| api | 8001 | FastAPI приложение |
| mongodb | 27018 | MongoDB (внутри Docker — 27017) |
| postgres | 5432 | PostgreSQL (метрики для DataLens) |
| telegram-bot | — | Telegram-бот (polling) |
| pgadmin | 5050 | Веб-интерфейс для PostgreSQL |
| frontend | — | Сборка фронтенда (запускается один раз) |

### Локально

```bash
pip install -r requirements.txt
python run.py
```

## Переменные окружения (.env)

```bash
# API
API_KEY=...                    # Ключ для доступа к API (X-API-Key header)
API_BASE_URL=https://api.ai-osnova.ru/api  # Базовый URL API

# Внешние сервисы
EVENLABS=...                   # ElevenLabs API key
OPENAI=...                     # OpenAI API key
LANGCHAIN=...                  # LangChain API key (опционально)

# MongoDB (с авторизацией)
MONGO_ROOT_USERNAME=...        # Логин MongoDB
MONGO_ROOT_PASSWORD=...        # Пароль MongoDB
MONGODB_URI=mongodb://user:password@mongodb:27017/?authSource=admin
MONGODB_NAME=medai

# PostgreSQL
POSTGRES_USER=admin
POSTGRES_PASSWORD=...
POSTGRES_DB=medai_metrics

# Telegram
BOT_TOKEN=...                  # Токен Telegram-бота

# AmoCRM
CLIENT_ID=...                  # ID приложения AmoCRM

# Прокси (для скачивания аудио с RT)
PROXY_ENABLED=true
PROXY_HOST=...
PROXY_PORT=...
PROXY_USERNAME=...
PROXY_PASSWORD=...
PROXY_TYPE=socks5
PROXY_STRING=host:port:user:pass  # Альтернативный формат

# Frontend (Docker)
FRONTEND_BUILD_CONTEXT=/path/to/medai_frontend  # Путь к исходникам фронтенда
FRONTEND_PATH=/var/www/ai-osnova.ru/html         # Куда деплоить собранный HTML
```

## API-аутентификация

Все эндпоинты требуют заголовок `X-API-Key`, **кроме**:

| Префикс | Описание |
|---------|----------|
| `/api/status` | Статус API |
| `/docs`, `/redoc` | Swagger / ReDoc |
| `/api/calls/download/` | Скачивание аудио |
| `/api/transcriptions/` | Скачивание транскрипций |
| `/api/call/reports/` | Скачивание отчётов (PDF/Excel) |
| `/api/analysis/` | Скачивание файлов анализа |
| `/api/amocrm/note/` | Транскрипции по note_id |
| `/api/amocrm/contact/` | Файлы по контакту |
| `/api/amocrm/lead/` | Файлы по сделке |
| `/download_call_report/` | Скачивание отчётов (альт.) |

Исключения настраиваются в `app/middleware/api_key_auth.py`.

Swagger UI (`/docs`) имеет кнопку Authorize для ввода ключа.

## Лимиты транскрибации

Каждая клиника имеет месячный и недельный лимит в минутах аудио.

**Дефолтные значения:**
- Месячный лимит: **3000 минут** (~50 часов)
- Недельный лимит: **750 минут** (1/4 месячного)

**Автоматический сброс:**
- **Месячный** — 1-го числа каждого месяца (при первом обращении к лимитам)
- **Недельный** — каждый понедельник в 00:00

**Ручное управление через API:**
- `POST /api/admin/clinics/{client_id}/limits/reset` — сброс месячного счётчика
- `PUT /api/admin/clinics/{client_id}/limits` — изменение лимита
- `POST /api/admin/clinics/{client_id}/limits/add` — пополнение минут

Логика в `app/services/clinic_limits_service.py`.

## Основные коллекции MongoDB

- **calls** — звонки с метриками, транскрипциями и анализом
- **clinics** — клиники с настройками конверсий и лимитами
- **tokens** — OAuth-токены AmoCRM (redirect_url хранится здесь)
- **work_schedules** — графики работы администраторов
- **administrators** — администраторы клиник
- **transcriptions** — транскрипции звонков
- **call_analysis** — результаты AI-анализа
- **call_exports** — экспорт звонков
- **call_status** — статусы обработки

## Таблицы PostgreSQL (DataLens)

- **daily_summary_metrics** — ежедневные метрики (звонки, конверсии, оценки)
- **call_criteria_metrics** — оценки по критериям
- **call_details** — детали звонков с ссылками на транскрипции
- **recommendation_analysis** — результаты анализа рекомендаций

Синхронизация MongoDB → PostgreSQL:
- Автоматически: через `POST /api/postgres/sync-now`
- Скриптом: `python datalens/postgres_exporter.py --once`

## Деплой на новый сервер

1. Клонировать репо, переключиться на ветку `version_4.0`
2. Создать `.env` (см. раздел выше)
3. Запустить: `docker-compose up -d`
4. Восстановить дампы MongoDB и PostgreSQL
5. Настроить Nginx + SSL для проксирования на порт 8001
6. Обновить DNS

Подробный чеклист миграции: `docs/MIGRATION_CHECKLIST.md`

## Тесты

```bash
pytest
pytest tests/test_full_conversion_check.py -v
pytest -v -s  # с выводом
```

## Полезные команды

```bash
# Логи
docker-compose logs -f api
docker-compose logs -f telegram-bot

# Перезапуск
docker-compose restart api

# Полный перезапуск
docker-compose down && docker-compose up -d

# Проверка статуса
curl https://api.ai-osnova.ru/api/status
```
