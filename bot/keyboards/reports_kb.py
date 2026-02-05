from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

def make_date_range_keyboard() -> ReplyKeyboardMarkup:
    """
    Создает клавиатуру с предустановленными периодами для отчета
    """
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="Неделя"),
                KeyboardButton(text="Месяц"),
                KeyboardButton(text="Квартал")
            ],
            [KeyboardButton(text="Отмена")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    
    return keyboard

def make_report_confirm_keyboard() -> InlineKeyboardMarkup:
    """
    Создает инлайн-клавиатуру для подтверждения генерации отчета
    """
    buttons = [
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_report"),
            InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_report")
        ]
    ]
    
    return InlineKeyboardMarkup(inline_keyboard=buttons) 