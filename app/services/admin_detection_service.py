"""
Сервис для определения администратора звонка.
Интегрирует AI extraction + график работы.
"""

import logging
import re
from datetime import datetime, date
from typing import Optional, Dict, Any
from motor.motor_asyncio import AsyncIOMotorClient

from app.settings.paths import MONGO_URI, DB_NAME
from app.services.schedule_service import ScheduleService
from app.services.call_analysis_service_new import CallAnalysisService

logger = logging.getLogger(__name__)


def normalize_admin_name(first_name: str, last_name: str = "") -> str:
    """
    Нормализует имя администратора:
    - Убирает пробелы в начале и конце
    - Заменяет множественные пробелы на один
    - Формирует "Имя Фамилия"
    """
    first = first_name.strip() if first_name else ""
    last = last_name.strip() if last_name else ""
    
    if first and last:
        full_name = f"{first} {last}"
    elif first:
        full_name = first
    elif last:
        full_name = last
    else:
        return "Неизвестный администратор"
    
    # Убираем множественные пробелы
    full_name = re.sub(r'\s+', ' ', full_name).strip()
    
    return full_name


async def determine_administrator_for_call(
    clinic_id: str,
    call_date: date,
    transcription_text: Optional[str] = None,
    responsible_user_id: Optional[int] = None,
    manager_name: Optional[str] = None,
) -> str:
    """
    Определяет администратора для звонка используя метод клиники (amocrm или ai_schedule).
    
    Args:
        clinic_id: ID клиники
        call_date: Дата звонка
        transcription_text: Текст транскрипции (если есть)
        responsible_user_id: ID ответственного из AmoCRM (для fallback)
        manager_name: Имя ответственного из AmoCRM (для сопоставления с графиком)
        
    Returns:
        str: Имя администратора (имя + фамилия) или "Неизвестный администратор"
    """
    try:
        client = AsyncIOMotorClient(MONGO_URI)
        db = client[DB_NAME]
        
        # Ищем клинику по client_id (это UUID который передается везде как clinic_id)
        clinic = await db.clinics.find_one({"client_id": clinic_id})
        
        if not clinic:
            logger.error(f"Клиника с client_id={clinic_id} не найдена")
            return "Неизвестный администратор"
        
        detection_method = clinic.get("admin_detection_method", "amocrm")
        
        logger.info(
            f"Определение администратора для клиники {clinic.get('name')} "
            f"методом '{detection_method}'"
        )
        
        # Метод 1: AI + График
        if detection_method == "ai_schedule":
            admin_name = await _determine_by_ai_schedule(
                clinic_id, call_date, transcription_text, db, manager_name
            )
            
            if admin_name:
                logger.info(f"Администратор определён через AI+график: {admin_name}")
                return admin_name
            
            # Для метода ai_schedule НЕ делаем fallback к amoCRM
            # Если график не заполнен или не удалось определить - возвращаем "Неизвестный"
            logger.warning(
                f"Не удалось определить администратора через график для клиники {clinic_id}. "
                f"График не заполнен или данных недостаточно."
            )
            return "Неизвестный администратор"
        
        # Метод 2: AmoCRM (только если метод = "amocrm")
        if responsible_user_id:
            admin_name = await _determine_by_amocrm(
                clinic_id, responsible_user_id, db, clinic["_id"]
            )
            
            if admin_name:
                logger.info(f"Администратор определён через AmoCRM: {admin_name}")
                return admin_name
        
        # Если ничего не помогло
        logger.warning(
            f"Не удалось определить администратора для клиники {clinic_id}, "
            f"дата {call_date}"
        )
        return "Неизвестный администратор"
        
    except Exception as e:
        logger.error(f"Ошибка при определении администратора: {e}")
        return "Неизвестный администратор"
    finally:
        client.close()


async def _determine_by_ai_schedule(
    clinic_id: str,
    call_date: date,
    transcription_text: Optional[str],
    db,
    manager_name: Optional[str] = None,
) -> Optional[str]:
    """
    Определяет администратора через AI + график работы.
    
    ПРАВИЛЬНЫЙ ПОДХОД (по ТЗ):
    1. Получить список администраторов из графика на дату звонка
    2. Если график не заполнен → вернуть None (Неизвестный администратор)
    3. Если 1 админ в графике → вернуть его (без AI)
    4. Если несколько → передать список в AI вместе с транскрипцией, AI сам выберет
    5. Если AI не может определить, но manager_name совпадает с кем-то из графика → используем manager_name
    
    Returns:
        Optional[str]: "Имя Фамилия" или None если график не заполнен
    """
    try:
        schedule_service = ScheduleService()
        
        # Получаем список администраторов из графика
        administrators_list = await schedule_service.get_schedule_for_date(
            clinic_id=clinic_id,
            call_date=call_date
        )
        
        # Если график не заполнен → возвращаем None
        if not administrators_list:
            logger.warning(
                f"График не заполнен для клиники {clinic_id} на дату {call_date}. "
                f"Возвращаем 'Неизвестный администратор'."
            )
            return None
        
        # Если один администратор в графике → возвращаем его без AI
        if len(administrators_list) == 1:
            admin = administrators_list[0]
            full_name = normalize_admin_name(admin['first_name'], admin['last_name'])
            logger.info(
                f"В графике один администратор на {call_date}: {full_name}. "
                f"Возвращаем без AI."
            )
            return full_name
        
        # Несколько администраторов → используем AI для выбора
        if not transcription_text:
            logger.warning(
                f"Несколько администраторов в графике ({len(administrators_list)}), "
                f"но транскрипция отсутствует. Не можем определить."
            )
            return None
        
        logger.info(
            f"Несколько администраторов в графике ({len(administrators_list)}). "
            f"Используем AI для определения из транскрипции."
        )
        
        # Передаём транскрипцию + список админов в AI
        analysis_service = CallAnalysisService()
        extraction_result = await analysis_service.extract_administrator_name(
            transcription_text=transcription_text,
            administrators_list=administrators_list
        )
        
        first_name = extraction_result.get("first_name")
        last_name = extraction_result.get("last_name")
        confidence = extraction_result.get("confidence", 0.0)
        
        # Если AI не смог определить (confidence низкий или имя None)
        # Порог 0.3 - если AI хоть немного уверен, скорее всего он прав
        if not first_name or confidence < 0.3:
            logger.warning(
                f"AI не смог определить администратора "
                f"(first_name={first_name}, confidence={confidence})"
            )
            
            # FALLBACK: Пытаемся сопоставить manager_name из AmoCRM с графиком
            if manager_name and administrators_list:
                logger.info(f"Пытаемся сопоставить manager_name '{manager_name}' с графиком...")
                for admin in administrators_list:
                    admin_full_name = normalize_admin_name(admin['first_name'], admin['last_name'])
                    # Проверяем точное совпадение или частичное (по фамилии)
                    if (manager_name.lower() == admin_full_name.lower() or 
                        admin['last_name'].strip().lower() in manager_name.lower()):
                        logger.info(
                            f"✅ Найдено совпадение manager_name с графиком: {admin_full_name}"
                        )
                        return admin_full_name
                logger.warning(f"manager_name '{manager_name}' не совпал ни с кем из графика")
            
            # Если AI не смог и manager_name не помог → возвращаем None (Неизвестный администратор)
            return None
        
        # AI вернул имя → формируем полное имя
        full_name = normalize_admin_name(first_name, last_name)
        
        logger.info(
            f"AI определил администратора: {full_name} "
            f"(confidence: {confidence})"
        )
        
        return full_name
        
    except Exception as e:
        logger.error(f"Ошибка в _determine_by_ai_schedule: {e}")
        return None


async def _determine_by_amocrm(
    clinic_client_id: str,  # client_id клиники (UUID)
    responsible_user_id: int,
    db,
    clinic_db_id: str,  # _id клиники из базы
) -> Optional[str]:
    """
    Определяет администратора через AmoCRM (старый метод).
    
    Returns:
        Optional[str]: Имя администратора или None
    """
    try:
        # Ищем администратора по amocrm_user_id и clinic_id (_id клиники в базе)
        admin = await db.administrators.find_one({
            "amocrm_user_id": str(responsible_user_id),
            "clinic_id": clinic_db_id,
        })
        
        if admin:
            return admin.get("name", "Неизвестный администратор")
        
        # Если не нашли конкретного, берём любого администратора клиники
        admin = await db.administrators.find_one({
            "clinic_id": clinic_db_id
        })
        
        if admin:
            logger.info(
                f"Администратор не найден по responsible_user_id, "
                f"используем первого доступного: {admin.get('name')}"
            )
            return admin.get("name", "Неизвестный администратор")
        
        return None
        
    except Exception as e:
        logger.error(f"Ошибка в _determine_by_amocrm: {e}")
        return None
