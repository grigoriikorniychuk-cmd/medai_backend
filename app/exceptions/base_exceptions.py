"""
Базовые исключения для приложения MedAI.
Предоставляет стандартизированный механизм обработки ошибок.
"""

from typing import Any, Dict, Optional
from http import HTTPStatus


class MedAIException(Exception):
    """
    Базовый class для всех исключений в приложении MedAI.
    Все пользовательские исключения должны наследоваться от этого класса.
    """

    status_code: int = HTTPStatus.INTERNAL_SERVER_ERROR
    code: str = "medai_error"
    message: str = "Произошла внутренняя ошибка"

    def __init__(
        self,
        message: Optional[str] = None,
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        """
        Инициализирует исключение.

        Args:
            message: Сообщение об ошибке (если None, используется message по умолчанию)
            code: Код ошибки (если None, используется code по умолчанию)
            details: Дополнительные детали об ошибке
        """
        self.message = message or self.message
        self.code = code or self.code
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        """
        Преобразует except в словарь для ответа API.

        Returns:
            Словарь с информацией об ошибке
        """
        error_dict = {
            "success": False,
            "error": {
                "code": self.code,
                "message": self.message,
                "status_code": self.status_code,
            },
        }

        if self.details:
            error_dict["error"]["details"] = self.details

        return error_dict


class BadRequestError(MedAIException):
    """Ошибка связанная с неверными данными в запросе."""

    status_code = HTTPStatus.BAD_REQUEST
    code = "bad_request"
    message = "Неверные данные в запросе"


class NotFoundError(MedAIException):
    """Ошибка, когда запрашиваемый ресурс не найден."""

    status_code = HTTPStatus.NOT_FOUND
    code = "not_found"
    message = "Запрашиваемый ресурс не найден"


class UnauthorizedError(MedAIException):
    """Ошибка аутентификации."""

    status_code = HTTPStatus.UNAUTHORIZED
    code = "unauthorized"
    message = "Требуется аутентификация"


class ForbiddenError(MedAIException):
    """Ошибка доступа, когда у пользователя недостаточно прав."""

    status_code = HTTPStatus.FORBIDDEN
    code = "forbidden"
    message = "Недостаточно прав для выполнения операции"


class ValidationError(MedAIException):
    """Ошибка валидации данных."""

    status_code = HTTPStatus.BAD_REQUEST
    code = "validation_error"
    message = "Ошибка валидации данных"


class DatabaseError(MedAIException):
    """Ошибка с работе с базой данных."""

    status_code = HTTPStatus.INTERNAL_SERVER_ERROR
    code = "database_error"
    message = "Ошибка с работе с базой данных"


class ExternalServiceError(MedAIException):
    """Ошибка с работе с внешним сервисом."""

    status_code = HTTPStatus.BAD_GATEWAY
    code = "external_service_error"
    message = "Ошибка с взаимодействии с внешним сервисом"


class AmoCRMError(ExternalServiceError):
    """Ошибка с работе с AmoCRM."""

    code = "amocrm_error"
    message = "Ошибка с взаимодействии с AmoCRM"


class TranscriptionError(MedAIException):
    """Ошибка с транскрипции аудио."""

    status_code = HTTPStatus.INTERNAL_SERVER_ERROR
    code = "transcription_error"
    message = "Ошибка с транскрипции аудио"


class AnalysisError(MedAIException):
    """Ошибка с анализе звонка."""

    status_code = HTTPStatus.INTERNAL_SERVER_ERROR
    code = "analysis_error"
    message = "Ошибка с анализе звонка"


class FileNotFoundError(NotFoundError):
    """Ошибка, когда запрашиваемый файл не найден."""

    code = "file_not_found"
    message = "Запрашиваемый файл не найден"


class FileProcessingError(MedAIException):
    """Ошибка с обработке файла."""

    status_code = HTTPStatus.INTERNAL_SERVER_ERROR
    code = "file_processing_error"
    message = "Ошибка с обработке файла"


class ConfigurationError(MedAIException):
    """Ошибка конфигурации."""

    status_code = HTTPStatus.INTERNAL_SERVER_ERROR
    code = "configuration_error"
    message = "Ошибка конфигурации приложения"


class RateLimitError(MedAIException):
    """Ошибка превышения лимита запросов."""

    status_code = HTTPStatus.TOO_MANY_REQUESTS
    code = "rate_limit_error"
    message = "Превышен лимит запросов"
