"""
Калькулятор эффективности звонков на основе настраиваемых критериев.

Поддерживает:
- Разные типы звонков (первичка, вторичка, перезвон, подтверждение)
- Настраиваемые диапазоны для каждого критерия
- Одиночные значения и диапазоны (7-10, 10)
"""

import logging
from typing import Dict, Any, List, Tuple, Optional

logger = logging.getLogger(__name__)


# Маппинг критериев по типам звонков (какие критерии применяются к какому типу)
CRITERIA_BY_CALL_TYPE = {
    "первичка": [
        "greeting", "patient_name", "needs_identification", "service_presentation",
        "clinic_presentation", "doctor_presentation", "appointment", "price",
        "expertise", "next_step", "appointment_booking", "emotional_tone",
        "speech", "initiative", "clinic_address", "passport", "objection_handling"
    ],
    "вторичка": [
        "greeting", "patient_name", "question_clarification", "expertise",
        "next_step", "appointment_booking", "emotional_tone", "speech",
        "initiative", "objection_handling"
    ],
    "перезвон": [
        "greeting", "patient_name", "appeal", "next_step",
        "initiative", "speech", "clinic_address", "passport",
        "objection_handling"
    ],
    "подтверждение": [
        "greeting", "patient_name", "appeal", "next_step",
        "initiative", "speech", "clinic_address", "passport",
        "objection_handling"
    ]
}

# Русские названия критериев для отображения
CRITERIA_DISPLAY_NAMES = {
    "greeting": "Приветствие",
    "patient_name": "Имя пациента",
    "needs_identification": "Выявление потребностей",
    "service_presentation": "Презентация услуги",
    "clinic_presentation": "Презентация клиники",
    "doctor_presentation": "Презентация врача",
    "appointment": "Запись",
    "price": "Цена",
    "expertise": "Экспертность",
    "next_step": "Следующий шаг",
    "appointment_booking": "Запись на прием",
    "emotional_tone": "Эмоциональный окрас",
    "speech": "Речь",
    "initiative": "Инициатива",
    "clinic_address": "Адрес клиники",
    "passport": "Паспорт",
    "objection_handling": "Работа с возражениями",
    "appeal": "Апелляция",
    "question_clarification": "Уточнение вопроса"
}


def parse_range(range_str: Any) -> Tuple[float, float]:
    """
    Парсит строку диапазона или одиночное значение.
    
    Args:
        range_str: Строка вида "7-10", "10", [7.0, 10.0] или число
        
    Returns:
        Кортеж (min, max) значений диапазона
        
    Examples:
        >>> parse_range("7-10")
        (7.0, 10.0)
        >>> parse_range("10")
        (10.0, 10.0)
        >>> parse_range([5.0, 8.0])
        (5.0, 8.0)
    """
    # Если уже список/tuple
    if isinstance(range_str, (list, tuple)) and len(range_str) == 2:
        return (float(range_str[0]), float(range_str[1]))
    
    # Если число
    if isinstance(range_str, (int, float)):
        val = float(range_str)
        return (val, val)
    
    # Если строка
    if isinstance(range_str, str):
        range_str = range_str.strip()
        
        # Формат "7-10"
        if "-" in range_str:
            parts = range_str.split("-")
            try:
                min_val = float(parts[0].strip())
                max_val = float(parts[1].strip())
                return (min_val, max_val)
            except (ValueError, IndexError) as e:
                logger.warning(f"Не удалось распарсить диапазон '{range_str}': {e}. Используем (0, 10)")
                return (0.0, 10.0)
        
        # Одиночное значение "10"
        try:
            val = float(range_str)
            return (val, val)
        except ValueError as e:
            logger.warning(f"Не удалось распарсить значение '{range_str}': {e}. Используем (0, 10)")
            return (0.0, 10.0)
    
    # Fallback
    logger.warning(f"Неизвестный формат диапазона: {range_str}. Используем (0, 10)")
    return (0.0, 10.0)


def is_in_range(value: float, range_tuple: Tuple[float, float]) -> bool:
    """
    Проверяет, попадает ли значение в диапазон (включительно).
    
    Args:
        value: Проверяемое значение
        range_tuple: Кортеж (min, max)
        
    Returns:
        True если value >= min and value <= max
    """
    return range_tuple[0] <= value <= range_tuple[1]


def get_default_settings() -> Dict[str, Any]:
    """
    Возвращает настройки эффективности по умолчанию.
    
    Если у клиники нет настроек, используются эти значения.
    """
    return {
        "overall": {
            "effective_range": "7-10",
            "ineffective_range": "0-6"
        },
        "criteria": {
            "Приветствие": {"effective": "5-10", "ineffective": "0-4"},
            "Имя пациента": {"effective": "5-10", "ineffective": "0-4"},
            "Выявление потребностей": {"effective": "5-10", "ineffective": "0-4"},
            "Презентация услуги": {"effective": "5-10", "ineffective": "0-4"},
            "Презентация клиники": {"effective": "5-10", "ineffective": "0-4"},
            "Презентация врача": {"effective": "5-10", "ineffective": "0-4"},
            "Запись": {"effective": "5-10", "ineffective": "0-4"},
            "Цена": {"effective": "5-10", "ineffective": "0-4"},
            "Экспертность": {"effective": "5-10", "ineffective": "0-4"},
            "Следующий шаг": {"effective": "5-10", "ineffective": "0-4"},
            "Запись на прием": {"effective": "10", "ineffective": "0-9"},
            "Эмоциональный окрас": {"effective": "5-10", "ineffective": "0-4"},
            "Речь": {"effective": "5-10", "ineffective": "0-4"},
            "Инициатива": {"effective": "5-10", "ineffective": "0-4"},
            "Адрес клиники": {"effective": "5-10", "ineffective": "0-4"},
            "Паспорт": {"effective": "5-10", "ineffective": "0-4"},
            "Работа с возражениями": {"effective": "5-10", "ineffective": "0-4"},
            "Апелляция": {"effective": "5-10", "ineffective": "0-4"},
            "Уточнение вопроса": {"effective": "5-10", "ineffective": "0-4"}
        }
    }


def calculate_call_effectiveness(
    metrics: Dict[str, Any],
    call_type: str,
    clinic_settings: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Рассчитывает эффективность звонка на основе метрик и настроек клиники.
    
    Args:
        metrics: Метрики звонка (greeting, patient_name, etc.)
        call_type: Тип звонка (первичка, вторичка, перезвон, подтверждение)
        clinic_settings: Настройки критериев эффективности клиники
        
    Returns:
        Словарь с результатами:
        {
            "is_effective": bool,
            "matched_criteria": List[str],  # Русские названия
            "average_score": float,
            "effective_criteria_count": int,
            "total_criteria_count": int
        }
    """
    # Используем настройки клиники или дефолтные
    settings = clinic_settings or get_default_settings()
    
    # Нормализуем тип звонка
    call_type_lower = call_type.lower()
    
    # Получаем список критериев для данного типа звонка
    relevant_criteria = CRITERIA_BY_CALL_TYPE.get(call_type_lower, [])
    
    if not relevant_criteria:
        logger.warning(f"Неизвестный тип звонка: {call_type}. Используем критерии первички.")
        relevant_criteria = CRITERIA_BY_CALL_TYPE["первичка"]
    
    # Собираем оценки ТОЛЬКО по релевантным критериям
    scores = []
    criteria_scores = {}  # {criterion_name: score}
    
    for criterion_field in relevant_criteria:
        score = metrics.get(criterion_field)
        if score is not None and isinstance(score, (int, float)):
            scores.append(score)
            criteria_scores[criterion_field] = score
    
    # Рассчитываем средний балл
    avg_score = sum(scores) / len(scores) if scores else 0.0
    
    logger.info(f"Средний балл для {call_type}: {avg_score:.2f} (по {len(scores)} критериям)")
    
    # Определяем эффективность на основе общего среднего балла
    overall_settings = settings.get("overall", {})
    effective_range = parse_range(overall_settings.get("effective_range", "7-10"))
    
    is_effective = is_in_range(avg_score, effective_range)
    
    logger.info(f"Звонок {'ЭФФЕКТИВНЫЙ' if is_effective else 'НЕЭФФЕКТИВНЫЙ'} (порог: {effective_range})")
    
    # Формируем список критериев, которые попали в целевой диапазон
    matched_criteria = []
    target_mode = "effective" if is_effective else "ineffective"
    
    criteria_settings = settings.get("criteria", {})
    
    for criterion_field, score in criteria_scores.items():
        # Русское название критерия
        display_name = CRITERIA_DISPLAY_NAMES.get(criterion_field, criterion_field)
        
        # Настройки для этого критерия
        criterion_config = criteria_settings.get(display_name, {})
        
        if not criterion_config:
            # Если нет настроек для критерия, пропускаем
            continue
        
        # Диапазон для целевого режима
        target_range_str = criterion_config.get(target_mode, "0-10")
        target_range = parse_range(target_range_str)
        
        # Проверяем попадание
        if is_in_range(score, target_range):
            matched_criteria.append(display_name)
    
    logger.info(f"Критерии, попавшие в диапазон '{target_mode}': {matched_criteria}")
    
    return {
        "is_effective": is_effective,
        "matched_criteria": matched_criteria,
        "average_score": round(avg_score, 2),
        "effective_criteria_count": len(matched_criteria),
        "total_criteria_count": len(scores),
        "effectiveness_label": "Эффективный" if is_effective else "Неэффективный"
    }


# Для обратной совместимости
def calculate_effectiveness(
    metrics: Dict[str, Any],
    conversion: bool = False,
    call_type: str = "первичка",
    settings: Optional[Dict[str, Any]] = None
) -> Tuple[str, List[str]]:
    """
    УСТАРЕВШАЯ функция для обратной совместимости.
    
    Возвращает кортеж (статус, критерии) в старом формате.
    """
    result = calculate_call_effectiveness(metrics, call_type, settings)
    
    status = "эффективный" if result["is_effective"] else "неэффективный"
    criteria = result["matched_criteria"]
    
    return (status, criteria)
