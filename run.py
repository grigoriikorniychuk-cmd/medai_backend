from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
import logging
import os
import asyncio
from app.middleware.api_key_auth import APIKeyMiddleware
from app.routers import (
    admin,
    amocrm,
    transcription,
    call_reports,
    calls,
    calls_parallel,
    calls_parallel_bulk,
    calls_events,  # Новый роутер для получения звонков через API событий
    report_new,
    classification_analysis,
    test_transcription_analysis,
    clinics,
    postgres_sync,
    work_schedules,  # Роутер для управления графиками
)
from app.settings import (
    print_paths,
    DEFAULT_API_SETTINGS,
    LOGGING_CONFIG,
    VERSION,
    # EXTERNAL_AUDIO_DIR,
)
# from app.services.mongodb_service import mongodb_service
# from app.services.metrics_exporter_service import start_metrics_exporter  # Временно отключено

# Выводим информацию о путях при запуске
print_paths()

# Настройка логирования
log_level_name = LOGGING_CONFIG["level"]
log_level = getattr(logging, log_level_name) if hasattr(logging, log_level_name) else logging.INFO
logging.basicConfig(
    level=log_level, format=LOGGING_CONFIG["format"]
)
logger = logging.getLogger(__name__)

# Отключаем DEBUG сообщения от MongoDB
motor_logger = logging.getLogger("motor")
motor_logger.setLevel(logging.WARNING)

# Создаем FastAPI приложение с настройками из централизованного модуля
app = FastAPI(**DEFAULT_API_SETTINGS)

# API Key middleware (проверяется ДО CORS, добавляется ПОСЛЕ — Starlette выполняет middleware в обратном порядке)
app.add_middleware(APIKeyMiddleware)

# Добавляем CORS middleware для фронтенда
origins = ["*"]  # В продакшене замените на конкретные домены
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Создаем простой перехватчик событий для логирования
@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(f"Запрос: {request.method} {request.url.path}")
    response = await call_next(request)
    logger.info(f"Ответ: {response.status_code}")
    return response

# Создаем директорию для внешних аудио, если она не существует
# os.makedirs(EXTERNAL_AUDIO_DIR, exist_ok=True)

# Событие при запуске приложения
@app.on_event("startup")
async def startup_event():
    logger.info("Инициализация приложения...")
    # Экспортер метрик временно отключен
    # # Запускаем экспортер метрик
    # try:
    #     await start_metrics_exporter(mongodb_service, port=9215)
    #     logger.info("Экспортер метрик успешно запущен на порту 9215")
    # except Exception as e:
    #     logger.error(f"Ошибка при запуске экспортера метрик: {str(e)}")
    #     logger.error("Приложение запущено без экспорта метрик")

# Подключаем роутеры к приложению
app.include_router(admin.router)
app.include_router(amocrm.router)
app.include_router(transcription.router)
app.include_router(call_reports.router)
app.include_router(calls.router)
app.include_router(calls_parallel.router)
app.include_router(calls_parallel_bulk.router)
app.include_router(calls_events.router)  # Новый роутер для получения звонков через API событий
app.include_router(report_new.router)
app.include_router(classification_analysis.router)
app.include_router(test_transcription_analysis.router)
app.include_router(clinics.router)
app.include_router(postgres_sync.router)
app.include_router(work_schedules.router)  # Роутер для графиков работы

# Эндпоинт для проверки статуса API
@app.get("/api/status")
async def get_status():
    return {
        "success": True,
        "message": "API работает нормально",
        "data": {"version": VERSION},
    }


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    openapi_schema["components"]["securitySchemes"] = {
        "APIKeyHeader": {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
        }
    }
    openapi_schema["security"] = [{"APIKeyHeader": []}]
    app.openapi_schema = openapi_schema
    return openapi_schema

app.openapi = custom_openapi


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("run:app", host="127.0.0.1", port=8001, reload=True)
