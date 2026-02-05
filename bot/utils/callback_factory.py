import uuid
from typing import Dict, Any

# Кэш для хранения данных callback
callback_cache = {}

# Функция для создания и хранения callback данных
def create_callback_data(data_dict: Dict[str, Any]) -> str:
    """
    Создает уникальный ID для callback данных и сохраняет их в кэше
    
    Args:
        data_dict: Словарь с данными для callback
        
    Returns:
        Уникальный ID для доступа к данным
    """
    callback_id = str(uuid.uuid4())[:8]  # Короткий уникальный ID
    callback_cache[callback_id] = data_dict
    return callback_id

# Функция для получения данных из callback
def get_callback_data(callback_id: str) -> Dict[str, Any]:
    """
    Получает данные по ID callback
    
    Args:
        callback_id: ID callback данных
        
    Returns:
        Словарь с данными или None, если данные не найдены
    """
    return callback_cache.get(callback_id)

# Функция для удаления данных из кэша
def remove_callback_data(callback_id: str) -> None:
    """
    Удаляет данные из кэша по ID
    
    Args:
        callback_id: ID callback данных для удаления
    """
    if callback_id in callback_cache:
        del callback_cache[callback_id] 