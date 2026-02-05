import logging
from typing import Dict, Any, Callable, Awaitable
from aiogram.types import Message
from aiogram.dispatcher.middlewares.base import BaseMiddleware

# Middleware для логирования всех входящих сообщений
class LoggingMiddleware(BaseMiddleware):
    """
    Middleware для логирования всех входящих сообщений
    """
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any]
    ) -> Any:
        user_id = getattr(event.from_user, "id", None)
        username = getattr(event.from_user, "username", None)
        text = event.text if hasattr(event, "text") and event.text else "[Нет текста]"
        message_id = getattr(event, "message_id", "Unknown")
        
        # Получаем состояние FSM, если оно есть
        state = data.get("state")
        current_state = "None"
        if state:
            current_state = await state.get_state() or "None"
        
        # Логируем информацию о входящем сообщении
        logging.info(f"📨 ВХОДЯЩЕЕ: ID {message_id} | От: {username} ({user_id}) | Текст: {text} | Состояние: {current_state}")
        
        try:
            # Вызываем следующий обработчик
            result = await handler(event, data)
            
            # Логируем успешную обработку
            logging.info(f"✅ ОБРАБОТАНО: ID {message_id}")
            return result
        except Exception as e:
            # Логируем ошибку обработки
            logging.error(f"❌ ОШИБКА при обработке сообщения {message_id}: {e}")
            # Пробрасываем исключение дальше
            raise

# Middleware для логирования FSM
class FSMLoggingMiddleware(BaseMiddleware):
    """
    Middleware для логирования состояний FSM
    """
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any]
    ) -> Any:
        # Получаем состояние из FSM
        state = data.get("state")
        if state:
            current_state = await state.get_state()
            state_data = await state.get_data()
            user_id = getattr(event.from_user, "id", None)
            
            # Логируем информацию о состоянии FSM
            logging.info(f"FSM для пользователя {user_id}: состояние {current_state}, данные: {state_data}")
        
        # Передаем управление следующему обработчику
        return await handler(event, data) 