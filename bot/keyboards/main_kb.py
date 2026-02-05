from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def make_main_keyboard() -> ReplyKeyboardMarkup:
    """
    Создает главную клавиатуру бота
    """
    # Определяем кнопки
    buttons = [
        [KeyboardButton(text="🏠 Главная")],
        [KeyboardButton(text="📞 Получить сделки"), KeyboardButton(text="📊 Создать отчёт")],
        # [KeyboardButton(text="📋 Регистрация клиники")]
    ]
    
    # Создаем клавиатуру с кнопками
    keyboard = ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True,  # Уменьшает размер клавиатуры
        persistent=True        # Клавиатура всегда видна
    )
    
    return keyboard 