from datetime import datetime, timedelta
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from typing import List, Dict, Any, Union

def make_date_keyboard() -> ReplyKeyboardMarkup:
    """
    Создает клавиатуру с датами для выбора
    """
    # Создаем текущую дату
    now = datetime.now()
    
    # Создаем кнопки с датами (сегодня, вчера, позавчера)
    today = now.strftime("%d.%m.%Y")
    yesterday = (now - timedelta(days=1)).strftime("%d.%m.%Y")
    before_yesterday = (now - timedelta(days=2)).strftime("%d.%m.%Y")
    
    # Создаем клавиатуру с датами
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=f"Сегодня ({today})")],
            [KeyboardButton(text=f"Вчера ({yesterday})")],
            [KeyboardButton(text=f"Позавчера ({before_yesterday})")],
            [KeyboardButton(text="Отмена")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    
    return keyboard

def make_leads_keyboard(leads: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    """
    Создает инлайн-клавиатуру для выбора сделки
    """
    buttons = []
    
    # Добавляем кнопки для каждой сделки
    for lead in leads:
        lead_id = lead.get("id")
        name = lead.get("name", f"Сделка #{lead_id}")
        calls_count = len(lead.get("calls", []))
        
        button_text = f"{name} ({calls_count} звонк{'ов' if calls_count != 1 else ''})"
        buttons.append([InlineKeyboardButton(text=button_text, callback_data=f"lead_{lead_id}")])
    
    # Добавляем кнопку возврата
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_date")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def make_call_actions_keyboard(call_data: Union[dict, list]) -> InlineKeyboardMarkup:
    """
    Создает инлайн-клавиатуру для действий с конкретным звонком или списком звонков
    
    Args:
        call_data: Словарь с данными о звонке или список звонков
        
    Returns:
        InlineKeyboardMarkup: Клавиатура с действиями
    """
    buttons = []
    
    # Проверяем, получили ли мы список звонков или один звонок
    if isinstance(call_data, list):
        # Если это список звонков, создаем кнопки для каждого звонка
        for call in call_data:
            call_id = str(call.get("_id"))
            call_date = call.get("created_date", "Неизвестно")
            call_direction = "📥" if call.get("call_direction") == "Входящий" else "📤"
            phone = call.get("phone", "Неизвестно")
            
            button_text = f"{call_direction} {phone} ({call_date})"
            buttons.append([InlineKeyboardButton(text=button_text, callback_data=f"call_{call_id}")])
        
        # Добавляем кнопку возврата
        buttons.append([InlineKeyboardButton(text="⬅️ Назад к сделкам", callback_data="back_to_leads")])
    else:
        # Это один звонок, создаем кнопки действий
        call = call_data
        call_id = str(call.get("_id"))
        transcription_exists = bool(call.get("filename_transcription"))
        
        # Кнопка скачивания звонка
        # buttons.append([
        #     InlineKeyboardButton(text="📥 Скачать звонок", callback_data=f"download_call_{call_id}")
        # ])
        
        # Если транскрибация уже существует, добавляем кнопку для скачивания
        if transcription_exists:
            buttons.append([
                InlineKeyboardButton(text="📄 Скачать транскрибацию", callback_data=f"download_transcript_{call_id}")
            ])
            buttons.append([
                InlineKeyboardButton(text="🧠 Анализировать звонок", callback_data=f"analyze_{call_id}")
            ])
        else:
            # Если транскрибации нет, добавляем кнопку для запуска
            buttons.append([
                InlineKeyboardButton(text="🎙 Транскрибировать звонок", callback_data=f"transcribe_{call_id}")
            ])
        
        # Кнопка возврата к списку звонков
        buttons.append([
            InlineKeyboardButton(text="⬅️ Назад к списку", callback_data="back_to_leads")
        ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons) 