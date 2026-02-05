from datetime import datetime
import os
import logging

logger = logging.getLogger(__name__)


def convert_date_to_timestamps(date_str: str) -> tuple[int, int]:
    """
    Преобразует дату в формате ДД.ММ.ГГГГ в unix timestamps начала и конца дня.
    """
    try:
        # Парсим дату
        date_obj = datetime.strptime(date_str, "%d.%m.%Y").date()

        # Получаем начало дня в timestamp (00:00:00)
        start_of_day = int(datetime.combine(date_obj, datetime.min.time()).timestamp())

        # Получаем конец дня в timestamp (23:59:59)
        end_of_day = int(datetime.combine(date_obj, datetime.max.time()).timestamp())

        return start_of_day, end_of_day
    except ValueError:
        raise ValueError(
            "Неверный формат даты. Используйте ДД.ММ.ГГГГ, например, 13.03.2025"
        )


def cleanup_temp_file(file_path: str):
    """
    Удаляет временный файл после отправки
    """
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"Временный файл удален: {file_path}")
    except Exception as e:
        logger.error(f"Ошибка с удалении временного файла {file_path}: {e}")
