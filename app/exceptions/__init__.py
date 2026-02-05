"""
Обработчики исключений для FastAPI.
Содержит middleware и обработчики для конвертации исключений MedAI в HTTP-ответы.
"""

from fastapi import Request, FastAPI
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.exceptions.base_exceptions import MedAIException


def register_exception_handlers(app: FastAPI) -> None:
    """
    Регистрирует обработчики исключений для FastAPI приложения.

    Args:
        app: Экземпляр FastAPI приложения
    """

    @app.exception_handler(MedAIException)
    async def medai_exception_handler(request: Request, exc: MedAIException):
        """
        Обработчик для пользовательских исключений MedAI.
        Преобразует исключения в стандартизированный JSON-ответ.

        Args:
            request: Объект запроса FastAPI
            exc: Экземпляр исключения MedAI

        Returns:
            JSONResponse с деталями ошибки
        """
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        """
        Обработчик для HTTP-исключений Starlette.
        Преобразует HTTP-исключения в стандартизированный JSON-ответ.

        Args:
            request: Объект запроса FastAPI
            exc: Экземпляр HTTP-исключения

        Returns:
            JSONResponse с деталями ошибки
        """
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "error": {
                    "code": f"http_error_{exc.status_code}",
                    "message": str(exc.detail),
                    "status_code": exc.status_code,
                },
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ):
        """
        Обработчик для ошибок валидации запросов.
        Преобразует ошибки валидации в стандартизированный JSON-ответ.

        Args:
            request: Объект запроса FastAPI
            exc: Экземпляр ошибки валидации

        Returns:
            JSONResponse с деталями ошибки валидации
        """
        # Получаем список ошибок валидации из исключения
        validation_errors = []
        for error in exc.errors():
            validation_errors.append(
                {"loc": error["loc"], "msg": error["msg"], "type": error["type"]}
            )

        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "error": {
                    "code": "validation_error",
                    "message": "Ошибка валидации данных",
                    "status_code": 422,
                    "details": {"errors": validation_errors},
                },
            },
        )
