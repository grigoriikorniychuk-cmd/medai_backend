"""
Контроллер для анализа звонков.
Предоставляет интерфейс для взаимодействия API с логикой анализа звонков.
"""

from typing import Dict, Any, List, Optional
from fastapi import Depends, HTTPException, status

from app.models.call_analysis import (
    CallAnalysisRequest,
    CallAnalysisResponse,
    CallAnalysisModel,
    CallAnalysisSummary,
    CallMetricsAggregate,
    MetricsFilter,
)
# from app.services.call_analysis_service import CallAnalysisService
from app.services.call_analysis_service_new import CallAnalysisService
from app.repositories.call_analysis_repository import CallAnalysisRepository
from app.utils.logging import ContextLogger

# Настройка логирования
logger = ContextLogger("call_analysis_controller")


class CallAnalysisController:
    """
    Контроллер для управления анализом звонков.
    Обрабатывает запросы API, делегируя бизнес-логику сервисам.
    """

    def __init__(
        self,
        call_analysis_service: CallAnalysisService,
        call_analysis_repository: CallAnalysisRepository,
    ):
        """
        Инициализирует контроллер анализа звонков.

        Args:
            call_analysis_service: Сервис для анализа звонков
            call_analysis_repository: Репозиторий для работы с данными анализа звонков
        """
        self.call_analysis_service = call_analysis_service
        self.call_analysis_repository = call_analysis_repository

    async def create_call_analysis(
        self, request: CallAnalysisRequest
    ) -> CallAnalysisResponse:
        """
        Создает анализ звонка на основе запроса.

        Args:
            request: Запрос на создание анализа звонка

        Returns:
            Ответ с результатами анализа

        Raises:
            HTTPException: Если возникла ошибка с анализе звонка
        """
        try:
            logger.info(
                "Получен запрос на создание анализа звонка",
                clinic_id=request.clinic_id,
                admin_id=request.administrator_id,
            )

            result = await self.call_analysis_service.create_call_analysis(request)
            if not result.success:
                logger.error("Ошибка с создании анализа звонка", error=result.message)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=result.message
                )

            logger.info(
                "Анализ звонка успешно создан", analysis_id=result.data.get("id")
            )
            return result
        except HTTPException:
            # Пробрасываем HTTPException дальше для корректной обработки FastAPI
            raise
        except Exception as e:
            logger.error(
                "Непредвиденная ошибка с создании анализа звонка", exc_info=True
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Внутренняя ошибка сервера: {str(e)}",
            )

    async def get_call_analysis_by_id(self, analysis_id: str) -> CallAnalysisModel:
        """
        Получает анализ звонка по ID.

        Args:
            analysis_id: Идентификатор анализа звонка

        Returns:
            Модель анализа звонка

        Raises:
            HTTPException: Если анализ звонка не найден или возникла ошибка
        """
        try:
            logger.info(
                "Получен запрос на получение анализа звонка", analysis_id=analysis_id
            )

            analysis = await self.call_analysis_repository.find_by_id(analysis_id)
            if not analysis:
                logger.warning("Анализ звонка не найден", analysis_id=analysis_id)
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Анализ звонка с ID {analysis_id} не найден",
                )

            logger.info("Анализ звонка успешно получен", analysis_id=analysis_id)
            return analysis
        except HTTPException:
            # Пробрасываем HTTPException дальше для корректной обработки FastAPI
            raise
        except Exception as e:
            logger.error(
                "Непредвиденная ошибка с получении анализа звонка",
                analysis_id=analysis_id,
                exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Внутренняя ошибка сервера: {str(e)}",
            )

    async def get_call_analysis_by_note_id(self, note_id: int) -> CallAnalysisModel:
        """
        Получает анализ звонка по ID заметки AmoCRM.

        Args:
            note_id: Идентификатор заметки AmoCRM

        Returns:
            Модель анализа звонка

        Raises:
            HTTPException: Если анализ звонка не найден или возникла ошибка
        """
        try:
            logger.info(
                "Получен запрос на получение анализа звонка по ID заметки",
                note_id=note_id,
            )

            analysis = await self.call_analysis_repository.find_by_note_id(note_id)
            if not analysis:
                logger.warning("Анализ звонка не найден по ID заметки", note_id=note_id)
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Анализ звонка для заметки с ID {note_id} не найден",
                )

            logger.info("Анализ звонка успешно получен по ID заметки", note_id=note_id)
            return analysis
        except HTTPException:
            # Пробрасываем HTTPException дальше для корректной обработки FastAPI
            raise
        except Exception as e:
            logger.error(
                "Непредвиденная ошибка с получении анализа звонка по ID заметки",
                note_id=note_id,
                exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Внутренняя ошибка сервера: {str(e)}",
            )

    async def get_call_analysis_summary(
        self,
        start_date: str,
        end_date: str,
        clinic_id: Optional[str] = None,
        administrator_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[CallAnalysisSummary]:
        """
        Получает сводку по анализу звонков за указанный период.

        Args:
            start_date: Начальная дата в формате YYYY-MM-DD
            end_date: Конечная дата в формате YYYY-MM-DD
            clinic_id: Идентификатор клиники (опционально)
            administrator_id: Идентификатор администратора (опционально)
            limit: Максимальное количество результатов
            offset: Смещение для пагинации

        Returns:
            Список моделей CallAnalysisSummary

        Raises:
            HTTPException: Если возникла ошибка с получении данных
        """
        try:
            logger.info(
                "Получен запрос на получение сводки по анализу звонков",
                start_date=start_date,
                end_date=end_date,
                clinic_id=clinic_id,
                administrator_id=administrator_id,
            )

            result = await self.call_analysis_repository.get_call_analysis_summary(
                start_date=start_date,
                end_date=end_date,
                clinic_id=clinic_id,
                administrator_id=administrator_id,
                limit=limit,
                skip=offset,
            )

            logger.info(
                f"Успешно получено {len(result)} записей сводки по анализу звонков"
            )
            return result
        except Exception as e:
            logger.error(
                "Непредвиденная ошибка с получении сводки по анализу звонков",
                exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Внутренняя ошибка сервера: {str(e)}",
            )

    async def get_metrics_aggregate(
        self, metrics_filter: MetricsFilter
    ) -> CallMetricsAggregate:
        """
        Получает агрегированные метрики по звонкам за указанный период.

        Args:
            metrics_filter: Фильтр для получения метрик

        Returns:
            Агрегированные метрики CallMetricsAggregate

        Raises:
            HTTPException: Если возникла ошибка с получении данных
        """
        try:
            logger.info(
                "Получен запрос на получение агрегированных метрик по звонкам",
                start_date=metrics_filter.start_date,
                end_date=metrics_filter.end_date,
                clinic_id=metrics_filter.clinic_id,
            )

            result = await self.call_analysis_repository.get_metrics_aggregate(
                start_date=metrics_filter.start_date,
                end_date=metrics_filter.end_date,
                clinic_id=metrics_filter.clinic_id,
                administrator_ids=metrics_filter.administrator_ids,
            )

            logger.info("Успешно получены агрегированные метрики по звонкам")
            return result
        except Exception as e:
            logger.error(
                "Непредвиденная ошибка с получении агрегированных метрик по звонкам",
                exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Внутренняя ошибка сервера: {str(e)}",
            )

    async def update_traffic_sources(
        self, amocrm_config: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        Обновляет информацию об источниках трафика для всех записей с неизвестным источником.

        Args:
            amocrm_config: Конфигурация AmoCRM для доступа к API

        Returns:
            Словарь с результатами обновления

        Raises:
            HTTPException: Если возникла ошибка с обновлении данных
        """
        try:
            logger.info("Получен запрос на обновление источников трафика")

            updated_count = (
                await self.call_analysis_service.update_traffic_sources_in_analytics(
                    amocrm_config=amocrm_config
                )
            )

            logger.info(
                f"Успешно обновлено {updated_count} записей с источниками трафика"
            )
            return {
                "success": True,
                "updated_count": updated_count,
                "message": f"Успешно обновлено {updated_count} записей с источниками трафика",
            }
        except Exception as e:
            logger.error(
                "Непредвиденная ошибка с обновлении источников трафика", exc_info=True
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Внутренняя ошибка сервера: {str(e)}",
            )


# Функция для создания экземпляра контроллера с зависимостями для использования в FastAPI
def get_call_analysis_controller():
    """
    Создает экземпляр контроллера анализа звонков.
    
    Returns:
        Экземпляр контроллера CallAnalysisController
    """
    from app.services.call_analysis_service_new import call_analysis_service, call_analysis_repository
    
    return CallAnalysisController(
        call_analysis_service=call_analysis_service,
        call_analysis_repository=call_analysis_repository
    )
