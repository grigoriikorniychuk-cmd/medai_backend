# Архитектура MedAI Backend

## Активные эндпоинты

### Синхронизация звонков из AmoCRM
| Эндпоинт | Роутер | Описание |
|----------|--------|----------|
| `POST /api/calls-events/export` | `calls_events.py` | Основной метод синхронизации через Events API |
| `POST /api/calls-parallel-bulk/sync-by-date` | `calls_parallel_bulk.py` | Массовая параллельная синхронизация |

### Транскрибация
| Эндпоинт | Роутер | Описание |
|----------|--------|----------|
| `POST /api/calls/transcribe` | `calls.py` | Скачивание аудио + транскрибация через ElevenLabs |
| `GET /api/calls/download-audio/{call_id}` | `calls.py` | Скачивание аудиофайла |

### AI-анализ
| Эндпоинт | Роутер | Описание |
|----------|--------|----------|
| `POST /api/call-analysis/analyze` | `classification_analysis.py` | AI-анализ транскрипций через OpenAI |

### Отчёты
| Эндпоинт | Роутер | Описание |
|----------|--------|----------|
| `POST /api/call-reports/generate` | `call_reports.py` | Генерация PDF/Excel отчётов |
| `POST /api/admin-reports/generate` | `call_reports.py` | Отчёты по администраторам |

### Управление
| Эндпоинт | Роутер | Описание |
|----------|--------|----------|
| `GET /api/status` | `run.py` | Healthcheck (не требует API ключа) |
| `/api/clinics/*` | `clinics.py` | Управление клиниками и лимитами |
| `/api/work-schedules/*` | `work_schedules.py` | Графики работы администраторов |
| `POST /api/postgres/sync-now` | `postgres_sync.py` | Синхронизация MongoDB → PostgreSQL |

## Сервисы

### Основные
| Сервис | Описание |
|--------|----------|
| `mongodb_service.py` | Работа с MongoDB |
| `transcription_service.py` | ElevenLabs интеграция (STT + diarization) |
| `amo_sync_service.py` | Синхронизация транскрипций в AmoCRM как заметки |
| `call_analysis_service_new.py` | AI-анализ через OpenAI |
| `call_report_service_new.py` | Генерация PDF/Excel отчётов |
| `call_admin_report_service.py` | Отчёты по администраторам |
| `clinic_limits_service.py` | Лимиты транскрибации (ElevenLabs quota) |

### Вспомогательные
| Сервис | Описание |
|--------|----------|
| `amo_service.py` | Базовая работа с AmoCRM API, управление токенами |
| `postgres_service.py` | Экспорт метрик в PostgreSQL для DataLens |

## Middleware

| Middleware | Описание |
|-----------|----------|
| `api_key_auth.py` | Проверка `X-API-Key` заголовка. Пропускает `/docs`, `/api/status`, `OPTIONS` |

## Docker-сервисы

| Контейнер | Порт | Описание |
|-----------|------|----------|
| `medai-api` | 8001 | FastAPI-приложение |
| `medai-telegram-bot` | — | Telegram-бот (aiogram) |
| `medai-mongodb` | 27018 | MongoDB |
| `medai-postgres` | 5432 | PostgreSQL (метрики для DataLens) |
| `medai-pgadmin` | 5050 | pgAdmin |
| `medai-frontend` | — | Сборка фронтенда |

## Внешние сервисы

| Сервис | Назначение |
|--------|-----------|
| AmoCRM API | Синхронизация звонков, сделок, заметок |
| ElevenLabs API | Транскрибация аудио (Speech-to-Text) |
| OpenAI API | AI-анализ транскрипций |
| SOCKS5 прокси | Скачивание аудио с RT URLs |

## Основные процессы

```
1. Синхронизация:
   AmoCRM Events API → calls_events.py → detect_conversion_config()
   → enrich_calls_with_conversion() → MongoDB (calls)

2. Транскрибация:
   MongoDB (calls) → calls.py → download audio → ElevenLabs API
   → transcription_service.py → save file → amo_sync_service.py → AmoCRM Notes

3. Анализ:
   MongoDB (calls + transcription) → call_analysis_service_new.py
   → OpenAI API → save to MongoDB

4. Отчёты:
   MongoDB (calls) → call_report_service_new.py → PDF/Excel
```

## Коллекции MongoDB

### `calls` (основная)
```
note_id, lead_id, contact_id, client_id, phone, administrator
call_type: { direction, status }
created_date, created_date_for_filtering (YYYY-MM-DD)
metrics: { duration, conversion }
conversion_type
filename_audio, filename_transcription, transcription_status
amo_transcription_synced, amo_transcription_note_id, amo_transcription_synced_at
analysis_status, analysis: { ... }
```

### `clinics`
```
client_id, clinic_name, amocrm_subdomain
conversion_config: { pipeline_primary_id, status_primary_booked_id, ... }
limits: { monthly_transcription_quota, used_this_month, last_reset }
```

### `tokens` (AmoCRM OAuth)
```
client_id, access_token, refresh_token, expires_at
```

### `work_schedules`
```
client_id, administrator, schedule entries
```

### `administrators`
```
client_id, name, detected_from
```

## Cron-скрипты

| Скрипт | Описание |
|--------|----------|
| `scripts/auto_sync_all_clinics.py` | Ежедневная синхронизация всех клиник (sync → transcribe → analyze) с polling и Telegram-отчётом |
| `scripts/daily_sync.py` | Синхронизация одной клиники |
