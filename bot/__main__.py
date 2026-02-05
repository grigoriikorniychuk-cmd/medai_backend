import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramAPIError

from bot.config.config import BOT_TOKEN
from bot.models.database import create_indexes
from bot.middlewares.logging import LoggingMiddleware, FSMLoggingMiddleware
from bot.handlers import common, registration, leads, reports

# Настройка логирования
def setup_logging():
    logging.basicConfig(
        level=logging.WARNING,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # Основной логгер
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)
    
    # Логгер для aiogram
    aiogram_logger = logging.getLogger("aiogram")
    aiogram_logger.setLevel(logging.WARNING)
    
    # Логгер для FSM
    fsm_logger = logging.getLogger("aiogram.fsm")
    fsm_logger.setLevel(logging.DEBUG)
    
    # Отключаем DEBUG сообщения от MongoDB
    motor_logger = logging.getLogger("motor")
    motor_logger.setLevel(logging.WARNING)
    
    return logger

# Обработчик необработанных исключений
async def errors_handler(event, data):
    """
    Обработчик ошибок для aiogram 3.x
    
    Args:
        event: Событие, в котором произошла ошибка
        data: Словарь с данными об ошибке
    """
    exception = data.get("exception", None)
    if not exception:
        return
    
    update = data.get("update", None)
    if not update:
        return
    
    error_str = str(exception)
    
    message = None
    if hasattr(update, "message"):
        message = update.message
    elif hasattr(update, "callback_query") and update.callback_query:
        message = update.callback_query.message
    
    # Определяем информацию о сообщении, вызвавшем ошибку
    message_id = getattr(message, "message_id", "Unknown") if message else "Unknown"
    user_id = getattr(message.from_user, "id", "Unknown") if message and hasattr(message, "from_user") else "Unknown"
    text = getattr(message, "text", "[No text]") if message else "[No text]"
    
    # Логируем подробную информацию об ошибке
    logging.error(f"❌ НЕОБРАБОТАННОЕ ИСКЛЮЧЕНИЕ: {error_str}")
    logging.error(f"Сообщение ID: {message_id}, Пользователь: {user_id}, Текст: {text}")
    logging.error(f"Полное исключение: {exception}", exc_info=True)
    
    # Отправляем сообщение пользователю, если возможно
    if message:
        try:
            await message.answer(
                "Произошла внутренняя ошибка при обработке вашего запроса.\n"
                "Администраторы уведомлены. Пожалуйста, попробуйте позже или используйте /cancel для сброса текущей операции."
            )
        except Exception as send_error:
            logging.error(f"Не удалось отправить сообщение об ошибке пользователю: {send_error}")

# Главная функция
async def main():
    # Настраиваем логирование
    logger = setup_logging()
    logger.info("Запуск бота с расширенным логированием")
    
    # Создаем хранилище состояний
    storage = MemoryStorage()
    
    # Создаем экземпляр бота
    bot = Bot(token=BOT_TOKEN)
    
    # Создаем диспетчер
    dp = Dispatcher(storage=storage)
    
    # Регистрируем обработчик ошибок
    dp.errors.register(errors_handler)
    
    # Регистрируем middleware
    dp.message.middleware(LoggingMiddleware())
    dp.callback_query.middleware(LoggingMiddleware())
    
    # Регистрируем роутеры
    dp.include_router(registration.router)  # Обработчики FSM регистрации
    dp.include_router(leads.router)         # Обработчики для работы со звонками
    dp.include_router(reports.router)       # Обработчики для работы с отчетами
    dp.include_router(common.router)        # Общие команды и неизвестные сообщения
    
    # Создаем индексы в MongoDB
    try:
        await create_indexes()
        logger.info("MongoDB индексы созданы успешно")
    except Exception as e:
        logger.error(f"Ошибка при создании индексов MongoDB: {e}")
    
    # Запускаем бота
    logger.info("Запуск бота в режиме long polling")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот остановлен!")
    except Exception as e:
        logging.error(f"Критическая ошибка: {e}", exc_info=True)
