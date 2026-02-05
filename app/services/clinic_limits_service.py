# -*- coding: utf-8 -*-
"""
Сервис для управления лимитами использования ElevenLabs по клиникам.

Каждая клиника имеет месячный лимит в МИНУТАХ аудио.
ElevenLabs PRO: 300 часов = 18,000 минут на весь аккаунт.
При 6 клиниках: ~3,000 минут на клинику.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from .mongodb_service import mongodb_service

logger = logging.getLogger(__name__)

# Константы для ElevenLabs PRO тарифа
ELEVENLABS_PRO_TOTAL_MINUTES = 18000  # 300 часов
DEFAULT_CLINIC_LIMIT_MINUTES = 3000   # ~50 часов на клинику
DEFAULT_WEEKLY_LIMIT_MINUTES = 750    # 1/4 месячного лимита


async def check_and_reset_monthly_limit(client_id: str) -> Dict[str, Any]:
    """
    Получает информацию о лимитах клиники.
    Сбрасывает месячный лимит автоматически 1-го числа каждого месяца.
    Сбрасывает недельный лимит автоматически каждую неделю.
    
    Args:
        client_id: ID клиники
        
    Returns:
        Dict с информацией о клинике и лимитах (в минутах)
    """
    try:
        clinic = await mongodb_service.find_one("clinics", {"client_id": client_id})
        
        if not clinic:
            logger.error(f"Клиника {client_id} не найдена в базе данных")
            return None
        
        # Проверяем и сбрасываем недельный счётчик каждый понедельник в 00:00
        last_week_reset = clinic.get("last_week_reset_date")
        current_week_minutes = clinic.get("current_week_minutes", 0)
        
        if last_week_reset:
            if isinstance(last_week_reset, str):
                last_week_reset = datetime.fromisoformat(last_week_reset)
            
            now = datetime.now()
            
            # Находим последний понедельник 00:00
            # weekday(): 0 = понедельник, 6 = воскресенье
            days_since_monday = now.weekday()  # 0 если сегодня понедельник
            last_monday = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_since_monday)
            
            # Если последний сброс был до последнего понедельника - сбрасываем
            if last_week_reset < last_monday:
                # Сброс недельного счётчика
                await mongodb_service.update_one(
                    "clinics",
                    {"client_id": client_id},
                    {
                        "$set": {
                            "current_week_minutes": 0,
                            "last_week_reset_date": last_monday.isoformat()
                        }
                    }
                )
                logger.info(f"✅ Недельный лимит сброшен для клиники {clinic.get('name', client_id)} (последний понедельник: {last_monday})")
                current_week_minutes = 0
        
        # Проверяем и сбрасываем месячный счётчик 1-го числа каждого месяца
        last_reset_date = clinic.get("last_reset_date")
        current_usage = clinic.get("current_month_minutes", 0)

        now = datetime.now()
        first_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        need_monthly_reset = False
        if last_reset_date:
            if isinstance(last_reset_date, str):
                last_reset_date = datetime.fromisoformat(last_reset_date)
            if last_reset_date < first_of_month:
                need_monthly_reset = True
        else:
            need_monthly_reset = True

        if need_monthly_reset:
            await mongodb_service.update_one(
                "clinics",
                {"client_id": client_id},
                {
                    "$set": {
                        "current_month_minutes": 0,
                        "last_reset_date": first_of_month.isoformat()
                    }
                }
            )
            logger.info(f"✅ Месячный лимит сброшен для клиники {clinic.get('name', client_id)} (начало месяца: {first_of_month})")
            current_usage = 0
            last_reset_date = first_of_month
        monthly_limit = clinic.get("monthly_limit_minutes", DEFAULT_CLINIC_LIMIT_MINUTES)
        weekly_limit = clinic.get("weekly_limit_minutes", DEFAULT_WEEKLY_LIMIT_MINUTES)
        remaining = monthly_limit - current_usage
        weekly_remaining = weekly_limit - current_week_minutes
            
        return {
            "client_id": client_id,
            "clinic_name": clinic.get("name", "Неизвестно"),
            "monthly_limit_minutes": monthly_limit,
            "current_month_minutes": round(current_usage, 2),
            "remaining_minutes": round(remaining, 2),
            "usage_percent": round((current_usage / monthly_limit * 100), 1) if monthly_limit > 0 else 0,
            "weekly_limit_minutes": weekly_limit,
            "current_week_minutes": round(current_week_minutes, 2),
            "weekly_remaining_minutes": round(weekly_remaining, 2),
            "weekly_usage_percent": round((current_week_minutes / weekly_limit * 100), 1) if weekly_limit > 0 else 0,
            "last_reset_date": last_reset_date.isoformat() if isinstance(last_reset_date, datetime) else last_reset_date,
            "last_week_reset_date": clinic.get("last_week_reset_date")
        }
        
    except Exception as e:
        logger.error(f"Ошибка при проверке лимитов для клиники {client_id}: {e}", exc_info=True)
        return None


async def check_clinic_limit(client_id: str, estimated_minutes: float = 0) -> Dict[str, Any]:
    """
    Проверяет, не превышен ли месячный И недельный лимит клиники.
    
    Args:
        client_id: ID клиники
        estimated_minutes: Ожидаемое количество минут для транскрипции
        
    Returns:
        Dict с информацией о лимите:
        {
            "allowed": bool,
            "clinic_name": str,
            "monthly_limit": float,  # в минутах
            "current_usage": float,  # в минутах
            "remaining": float,      # в минутах
            "weekly_limit": float,
            "current_week_usage": float,
            "weekly_remaining": float,
            "estimated_minutes": float,
            "limit_type": str  # "monthly", "weekly" или None
        }
    """
    limit_info = await check_and_reset_monthly_limit(client_id)
    
    if not limit_info:
        return {
            "allowed": False,
            "error": f"Клиника {client_id} не найдена"
        }
    
    remaining_monthly = limit_info["remaining_minutes"]
    remaining_weekly = limit_info["weekly_remaining_minutes"]
    
    # Проверяем оба лимита
    allowed = remaining_monthly > 0 and remaining_weekly > 0
    limit_type = None
    
    # Определяем, какой лимит превышен
    if remaining_monthly <= 0:
        allowed = False
        limit_type = "monthly"
    elif remaining_weekly <= 0:
        allowed = False
        limit_type = "weekly"
    
    # Если указаны предполагаемые минуты, проверяем хватит ли
    if estimated_minutes > 0 and allowed:
        if remaining_monthly < estimated_minutes:
            allowed = False
            limit_type = "monthly"
        elif remaining_weekly < estimated_minutes:
            allowed = False
            limit_type = "weekly"
    
    return {
        "allowed": allowed,
        "clinic_name": limit_info["clinic_name"],
        "monthly_limit": limit_info["monthly_limit_minutes"],
        "current_usage": limit_info["current_month_minutes"],
        "remaining": remaining_monthly,
        "usage_percent": limit_info["usage_percent"],
        "weekly_limit": limit_info["weekly_limit_minutes"],
        "current_week_usage": limit_info["current_week_minutes"],
        "weekly_remaining": remaining_weekly,
        "weekly_usage_percent": limit_info["weekly_usage_percent"],
        "estimated_minutes": estimated_minutes,
        "will_exceed": not allowed,
        "limit_type": limit_type  # Какой лимит превышен: "monthly", "weekly" или None
    }


async def increment_clinic_usage(client_id: str, minutes_used: float) -> bool:
    """
    Увеличивает счетчик использования минут для клиники (месячный И недельный).
    
    Args:
        client_id: ID клиники
        minutes_used: Количество использованных минут
        
    Returns:
        bool: True если успешно обновлено, False при ошибке
    """
    try:
        result = await mongodb_service.update_one(
            "clinics",
            {"client_id": client_id},
            {
                "$inc": {
                    "current_month_minutes": minutes_used,
                    "current_week_minutes": minutes_used  # Увеличиваем оба счётчика
                },
                "$set": {"updated_at": datetime.now().isoformat()}
            }
        )
        
        if result:
            logger.info(f"Использование обновлено для клиники {client_id}: +{minutes_used:.2f} минут")
            
            # Получаем обновленную информацию для логирования
            clinic = await mongodb_service.find_one("clinics", {"client_id": client_id})
            if clinic:
                current_usage = clinic.get("current_month_minutes", 0)
                monthly_limit = clinic.get("monthly_limit_minutes", DEFAULT_CLINIC_LIMIT_MINUTES)
                current_week = clinic.get("current_week_minutes", 0)
                weekly_limit = clinic.get("weekly_limit_minutes", DEFAULT_WEEKLY_LIMIT_MINUTES)
                
                remaining = monthly_limit - current_usage
                weekly_remaining = weekly_limit - current_week
                percentage_used = (current_usage / monthly_limit * 100) if monthly_limit > 0 else 0
                weekly_percentage = (current_week / weekly_limit * 100) if weekly_limit > 0 else 0
                
                logger.info(
                    f"📊 Статистика клиники {clinic.get('name', client_id)}: "
                    f"Месяц: {current_usage:.1f}/{monthly_limit} минут ({percentage_used:.1f}%), "
                    f"Неделя: {current_week:.1f}/{weekly_limit} минут ({weekly_percentage:.1f}%)"
                )
                
                # Предупреждение если осталось мало (месячный)
                if percentage_used >= 90:
                    logger.warning(
                        f"⚠️ Клиника {clinic.get('name', client_id)} использовала {percentage_used:.1f}% МЕСЯЧНОГО лимита!"
                    )
                
                # Предупреждение если осталось мало (недельный)
                if weekly_percentage >= 90:
                    logger.warning(
                        f"⚠️ Клиника {clinic.get('name', client_id)} использовала {weekly_percentage:.1f}% НЕДЕЛЬНОГО лимита!"
                    )
            
            return True
        else:
            logger.warning(f"Не удалось обновить использование для клиники {client_id}")
            return False
            
    except Exception as e:
        logger.error(f"Ошибка при обновлении использования для клиники {client_id}: {e}", exc_info=True)
        return False


async def add_minutes_to_clinic(client_id: str, minutes_to_add: float) -> Dict[str, Any]:
    """
    Вручную пополняет лимит минут для клиники.
    
    Args:
        client_id: ID клиники
        minutes_to_add: Количество минут для добавления к лимиту
        
    Returns:
        Dict с обновленной информацией о лимитах
    """
    try:
        clinic = await mongodb_service.find_one("clinics", {"client_id": client_id})
        if not clinic:
            logger.error(f"Клиника {client_id} не найдена в базе данных")
            return {"success": False, "error": "Клиника не найдена"}
        
        current_limit = clinic.get("monthly_limit_minutes", DEFAULT_CLINIC_LIMIT_MINUTES)
        new_limit = current_limit + minutes_to_add
        
        result = await mongodb_service.update_one(
            "clinics",
            {"client_id": client_id},
            {
                "$set": {
                    "monthly_limit_minutes": new_limit,
                    "last_manual_topup": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat()
                }
            }
        )
        
        if result:
            current_usage = clinic.get("current_month_minutes", 0)
            logger.info(
                f"✅ Лимит клиники {clinic.get('name', client_id)} пополнен: "
                f"+{minutes_to_add} минут. Новый лимит: {new_limit} минут"
            )
            
            return {
                "success": True,
                "clinic_name": clinic.get("name", "Неизвестно"),
                "minutes_added": minutes_to_add,
                "previous_limit": current_limit,
                "new_limit": new_limit,
                "current_usage": current_usage,
                "remaining_minutes": new_limit - current_usage
            }
        else:
            logger.warning(f"Не удалось обновить лимит для клиники {client_id}")
            return {"success": False, "error": "Не удалось обновить лимит"}
            
    except Exception as e:
        logger.error(f"Ошибка при пополнении лимита для клиники {client_id}: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


def duration_to_minutes(duration_seconds: float) -> float:
    """
    Конвертирует секунды в минуты.
    
    Args:
        duration_seconds: Длительность аудио в секундах
        
    Returns:
        float: Длительность в минутах (округлённая до 2 знаков)
    """
    return round(duration_seconds / 60, 2)


async def get_elevenlabs_usage() -> Dict[str, Any]:
    """
    Получает реальную статистику использования из ElevenLabs API.
    
    Returns:
        Dict с информацией о текущем использовании и лимитах
    """
    try:
        from app.settings.auth import evenlabs
        
        client = evenlabs()
        if not client:
            return {"success": False, "error": "ElevenLabs клиент не инициализирован"}
        
        # Получаем информацию о подписке
        subscription = client.user.subscription.get()
        
        return {
            "success": True,
            "tier": subscription.tier,
            "character_count": subscription.character_count,  # Использовано кредитов
            "character_limit": subscription.character_limit,  # Лимит кредитов
            "remaining": subscription.character_limit - subscription.character_count,
            "usage_percent": round((subscription.character_count / subscription.character_limit) * 100, 2) if subscription.character_limit > 0 else 0
        }
        
    except Exception as e:
        logger.error(f"Ошибка при получении информации из ElevenLabs API: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


async def sync_with_elevenlabs() -> Dict[str, Any]:
    """
    Синхронизирует данные использования с ElevenLabs API.
    Обновляет общий счётчик использования в системе.
    
    Вызывать периодически (раз в день) или по запросу.
    
    Returns:
        Dict с результатами синхронизации
    """
    try:
        usage = await get_elevenlabs_usage()
        
        if not usage.get("success"):
            return usage
        
        # Сохраняем данные синхронизации в отдельную коллекцию
        sync_data = {
            "synced_at": datetime.now().isoformat(),
            "tier": usage["tier"],
            "elevenlabs_used": usage["character_count"],
            "elevenlabs_limit": usage["character_limit"],
            "elevenlabs_remaining": usage["remaining"],
            "usage_percent": usage["usage_percent"]
        }
        
        await mongodb_service.update_one(
            "system_settings",
            {"type": "elevenlabs_sync"},
            {"$set": sync_data},
            upsert=True
        )
        
        logger.info(
            f"✅ Синхронизация с ElevenLabs: использовано {usage['character_count']:,}/{usage['character_limit']:,} "
            f"({usage['usage_percent']}%), осталось {usage['remaining']:,} кредитов"
        )
        
        return {
            "success": True,
            **usage,
            "synced_at": sync_data["synced_at"]
        }
        
    except Exception as e:
        logger.error(f"Ошибка при синхронизации с ElevenLabs: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
