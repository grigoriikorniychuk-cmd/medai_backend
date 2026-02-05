import os
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Пути, которые не требуют API ключа
EXCLUDED_PATHS = {
    "/docs",
    "/openapi.json",
    "/redoc",
    "/api/status",
}

# Префиксы путей для скачивания файлов (доступны без API ключа для прямых ссылок)
EXCLUDED_PREFIXES = (
    "/docs/",
    "/redoc/",
    # Скачивание транскрипций
    "/api/transcriptions/",
    "/api/amocrm/note/",
    # Скачивание аудио звонков
    "/api/calls/download/",
    "/api/amocrm/contact/",
    "/api/amocrm/lead/",
    # Скачивание отчетов (PDF, Excel)
    "/api/call/reports/",
    "/download_call_report/",
    # Скачивание файлов анализа
    "/api/analysis/",
)


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Middleware для проверки API ключа в заголовке X-API-Key"""

    async def dispatch(self, request: Request, call_next):
        # Пропускаем OPTIONS (CORS preflight)
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path

        # Пропускаем исключённые пути
        if path in EXCLUDED_PATHS or path.startswith(EXCLUDED_PREFIXES):
            return await call_next(request)

        # Проверяем API ключ
        expected_key = os.getenv("API_KEY")
        if not expected_key:
            # Если ключ не задан в env — пропускаем проверку (для обратной совместимости)
            logger.warning("API_KEY не задан в переменных окружения, проверка отключена")
            return await call_next(request)

        provided_key = request.headers.get("X-API-Key")
        if not provided_key or provided_key != expected_key:
            logger.warning(f"Отклонён запрос без валидного API ключа: {request.method} {path}")
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"},
            )

        return await call_next(request)
