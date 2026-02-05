import logging
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton, InputFile
from aiogram.fsm.context import FSMContext
import io

from bot.states.states import ReportGeneration
from bot.models.database import get_clinics_by_user_id
from bot.utils.api import generate_report, download_report, generate_excel_report
from bot.keyboards.reports_kb import make_report_confirm_keyboard, make_date_range_keyboard
from bot.keyboards.main_kb import make_main_keyboard

# Создаем роутер для работы с отчетами
router = Router(name="reports_router")

# Обработчик команды /report
@router.message(Command("report"))
async def cmd_report(message: Message, state: FSMContext):
    """
    Обработчик команды для генерации отчета по звонкам
    """
    # Получаем ID пользователя
    user_id = message.from_user.id
    
    # Проверяем, привязан ли пользователь к какой-либо клинике
    user_clinics = await get_clinics_by_user_id(user_id)
    
    if not user_clinics:
        await message.answer(
            "У вас нет привязанных клиник.\n"
            "Используйте команду /register для регистрации новой клиники."
        )
        return
    
    # Сохраняем client_id первой клиники (в будущем можно добавить выбор клиники)
    client_id = user_clinics[0]['client_id']
    await state.update_data(client_id=client_id, clinic_name=user_clinics[0]['name'])
    
    # Создаем клавиатуру для выбора периода
    keyboard = make_date_range_keyboard()
    
    await message.answer(
        "Выберите период для отчета или введите начальную дату (ДД.ММ.ГГГГ):",
        reply_markup=keyboard
    )
    
    # Устанавливаем состояние ожидания начальной даты
    await state.set_state(ReportGeneration.start_date)

# Обработчик для выбора предустановленного периода
@router.callback_query(F.data.startswith("period_"))
async def process_period_selection(callback: CallbackQuery, state: FSMContext):
    """
    Обработчик для выбора предустановленного периода
    """
    period = callback.data.split("_")[1]
    
    # Получаем текущую дату
    today = datetime.now()
    
    # Вычисляем даты в зависимости от выбранного периода
    if period == "week":
        # Неделя
        start_date = (today - timedelta(days=7)).strftime("%d.%m.%Y")
        end_date = today.strftime("%d.%m.%Y")
    elif period == "month":
        # Месяц
        start_date = (today - timedelta(days=30)).strftime("%d.%m.%Y")
        end_date = today.strftime("%d.%m.%Y")
    elif period == "quarter":
        # Квартал (3 месяца)
        start_date = (today - timedelta(days=90)).strftime("%d.%m.%Y")
        end_date = today.strftime("%d.%m.%Y")
    else:
        await callback.answer("Неизвестный период")
        return
    
    # Сохраняем даты в состоянии
    await state.update_data(start_date=start_date, end_date=end_date)
    
    # Переходим сразу к подтверждению
    await show_report_confirmation(callback.message, state)
    await callback.answer()

# Обработчик ввода начальной даты
@router.message(StateFilter(ReportGeneration.start_date))
async def process_start_date(message: Message, state: FSMContext):
    """
    Обработчик для ввода начальной даты
    """
    if not message.text:
        await message.answer("Пожалуйста, отправьте текстовое сообщение с датой в формате ДД.ММ.ГГГГ.")
        return
    
    date_text = message.text.strip()
    
    # Обработка предустановленных периодов
    today = datetime.now()
    
    if date_text == "Неделя":
        # Неделя
        start_date = (today - timedelta(days=7)).strftime("%d.%m.%Y")
        end_date = today.strftime("%d.%m.%Y")
        
        # Сохраняем даты в состоянии
        await state.update_data(start_date=start_date, end_date=end_date)
        
        # Переходим сразу к подтверждению
        await show_report_confirmation(message, state)
        return
    elif date_text == "Месяц":
        # Месяц
        start_date = (today - timedelta(days=30)).strftime("%d.%m.%Y")
        end_date = today.strftime("%d.%m.%Y")
        
        # Сохраняем даты в состоянии
        await state.update_data(start_date=start_date, end_date=end_date)
        
        # Переходим сразу к подтверждению
        await show_report_confirmation(message, state)
        return
    elif date_text == "Квартал":
        # Квартал (3 месяца)
        start_date = (today - timedelta(days=90)).strftime("%d.%m.%Y")
        end_date = today.strftime("%d.%m.%Y")
        
        # Сохраняем даты в состоянии
        await state.update_data(start_date=start_date, end_date=end_date)
        
        # Переходим сразу к подтверждению
        await show_report_confirmation(message, state)
        return
    
    # Проверяем формат даты
    try:
        # Пробуем распарсить введенную дату
        if len(date_text) == 10 and date_text[2] == '.' and date_text[5] == '.':
            # Формат ДД.ММ.ГГГГ
            date_obj = datetime.strptime(date_text, "%d.%m.%Y")
            formatted_date = date_obj.strftime("%d.%m.%Y")
        else:
            # Если формат не соответствует ожидаемому
            raise ValueError("Неверный формат даты")
    except ValueError:
        from bot.keyboards.main_kb import make_main_keyboard
        if date_text.lower() == "отмена":
            await state.clear()
            await message.answer("Операция отменена.", reply_markup=make_main_keyboard())
            return
        await message.answer(
            "Неверный формат даты. Пожалуйста, попробуйте снова с форматом ДД.ММ.ГГГГ.\n"
            "Для повторной попытки используйте команду /report",
            reply_markup=make_main_keyboard()
        )
        await state.clear()
        return
    
    # Сохраняем начальную дату в состоянии
    await state.update_data(start_date=formatted_date)
    
    # Запрашиваем конечную дату
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Отмена")]
        ],
        resize_keyboard=True
    )
    await message.answer("Введите конечную дату (ДД.ММ.ГГГГ):", reply_markup=keyboard)
    
    # Переходим к состоянию ожидания конечной даты
    await state.set_state(ReportGeneration.end_date)

# Обработчик ввода конечной даты
@router.message(StateFilter(ReportGeneration.end_date))
async def process_end_date(message: Message, state: FSMContext):
    """
    Обработчик для ввода конечной даты
    """
    if not message.text:
        await message.answer("Пожалуйста, отправьте текстовое сообщение с датой в формате ДД.ММ.ГГГГ.")
        return
    
    date_text = message.text.strip()
    
    # Проверяем формат даты
    try:
        # Пробуем распарсить введенную дату
        if len(date_text) == 10 and date_text[2] == '.' and date_text[5] == '.':
            # Формат ДД.ММ.ГГГГ
            date_obj = datetime.strptime(date_text, "%d.%m.%Y")
            formatted_date = date_obj.strftime("%d.%m.%Y")
        else:
            # Если формат не соответствует ожидаемому
            raise ValueError("Неверный формат даты")
    except ValueError:
        from bot.keyboards.main_kb import make_main_keyboard
        await message.answer(
            "Неверный формат даты. Пожалуйста, попробуйте снова с форматом ДД.ММ.ГГГГ.\n"
            "Для повторной попытки используйте команду /report",
            reply_markup=make_main_keyboard()
        )
        await state.clear()
        return
    
    # Проверяем, что конечная дата не раньше начальной
    data = await state.get_data()
    start_date = data.get("start_date")
    
    start_date_obj = datetime.strptime(start_date, "%d.%m.%Y")
    end_date_obj = datetime.strptime(formatted_date, "%d.%m.%Y")
    
    if end_date_obj < start_date_obj:
        from bot.keyboards.main_kb import make_main_keyboard
        await message.answer(
            "Ошибка: конечная дата не может быть раньше начальной.\n"
            "Пожалуйста, попробуйте снова с помощью команды /report",
            reply_markup=make_main_keyboard()
        )
        await state.clear()
        return
    
    # Сохраняем конечную дату в состоянии
    await state.update_data(end_date=formatted_date)
    
    # Переходим к вопросу об ID администраторов (опционально)
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="-")],
            [KeyboardButton(text="Отмена")]
        ],
        resize_keyboard=True
    )
    await message.answer(
        "Введите ID администраторов через запятую (опционально).\n"
        "Если хотите включить всех администраторов, просто отправьте '-':",
        reply_markup=keyboard
    )
    
    # Переходим к состоянию ожидания ID администраторов
    await state.set_state(ReportGeneration.admin_ids)

# Обработчик ввода ID администраторов
@router.message(StateFilter(ReportGeneration.admin_ids))
async def process_admin_ids(message: Message, state: FSMContext):
    """
    Обработчик для ввода ID администраторов
    """
    if not message.text:
        await message.answer("Пожалуйста, отправьте текстовое сообщение с ID администраторов или '-'.")
        return
    
    admin_ids_text = message.text.strip()
    
    # Проверяем, не пустой ли ввод или не равен ли он "-"
    if admin_ids_text == "-" or admin_ids_text.lower() == "нет":
        # Пользователь не указал администраторов
        admin_ids = []
    else:
        # Разбиваем строку на список ID
        admin_ids = [aid.strip() for aid in admin_ids_text.split(",") if aid.strip()]
    
    # Сохраняем ID администраторов в состоянии
    await state.update_data(admin_ids=admin_ids)
    
    # Показываем подтверждение параметров отчета
    await show_report_confirmation(message, state)

# Функция для отображения подтверждения параметров отчета
async def show_report_confirmation(message: Message, state: FSMContext):
    """
    Отображает подтверждение параметров отчета и запрашивает подтверждение
    """
    # Получаем данные из состояния
    data = await state.get_data()
    start_date = data.get("start_date")
    end_date = data.get("end_date")
    admin_ids = data.get("admin_ids", [])
    clinic_name = data.get("clinic_name", "Не указано")
    
    # Формируем сообщение с подтверждением
    confirmation_message = (
        f"📊 Параметры отчета:\n\n"
        f"📅 Период: с {start_date} по {end_date}\n"
        f"🏥 Клиника: {clinic_name}\n"
    )
    
    if admin_ids:
        confirmation_message += f"👨‍⚕️ Администраторы: {', '.join(admin_ids)}\n"
    else:
        confirmation_message += "👨‍⚕️ Администраторы: все\n"
    
    confirmation_message += "\nПодтвердите генерацию отчета:"
    
    # Создаем клавиатуру для подтверждения
    keyboard = make_report_confirm_keyboard()
    
    await message.answer(confirmation_message, reply_markup=keyboard)
    
    # Переходим к состоянию ожидания подтверждения
    await state.set_state(ReportGeneration.confirmation)

# Обработчик для подтверждения генерации отчета
@router.callback_query(F.data == "confirm_report")
async def process_report_confirmation(callback: CallbackQuery, state: FSMContext):
    """
    Обработчик для подтверждения генерации отчета
    """
    # Получаем данные из состояния
    data = await state.get_data()
    start_date = data.get("start_date")
    end_date = data.get("end_date")
    client_id = data.get("client_id")
    admin_ids = data.get("admin_ids", [])
    
    # Подготавливаем данные для API
    report_data = {
        "start_date": start_date,
        "end_date": end_date,
        "clinic_id": client_id
    }
    
    if admin_ids:
        report_data["administrator_ids"] = admin_ids
    
    # Отправляем сообщение о начале генерации
    await callback.message.answer("⏳ Начинаем генерацию отчета...")
    
    try:
        # Запускаем генерацию отчета
        result = await generate_report(report_data)
        
        # Новый формат ответа от API на основе report_new.py
        if "status" in result and result["status"] == "success":
            # Получаем имя файла отчета
            filename = result.get("filename")
            
            # Получаем URL для скачивания отчета
            download_url = await download_report(filename)
            
            # Проверяем, что URL получен успешно
            if not download_url:
                await callback.message.answer("❌ Ошибка: не удалось получить ссылку на отчет. Попробуйте позже.")
                await state.clear()
                await callback.message.answer("Вернитесь в главное меню:", reply_markup=make_main_keyboard())
                return
            
            # Получаем байты Excel через generate_excel_report (теперь получаем имя файла)
            excel_filename = await generate_excel_report(report_data)
            excel_download_url = await download_report(excel_filename) if excel_filename else None

            # Формируем клавиатуру
            buttons = [InlineKeyboardButton(text="📥 Скачать PDF", url=download_url)]
            if excel_download_url:
                buttons.append(InlineKeyboardButton(text="📊 Скачать Excel", url=excel_download_url))
            keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons])

            await callback.message.answer(
                f"✅ Отчет успешно сгенерирован!\n"
                f"Период: с {start_date} по {end_date}\n"
                f"Нажмите на кнопку ниже, чтобы скачать отчет:",
                reply_markup=keyboard
            )
            
        # Сохраняем поддержку старого формата ответа
        elif "success" in result and result.get("success", False):
            # Получаем имя файла отчета
            filename = result.get("filename")
            if not filename:
                # Если filename не найден, ищем в data
                filename = result.get("data", {}).get("filename")
                
            if not filename:
                await callback.message.answer("❌ Ошибка: не получено имя файла отчета")
                await state.clear()
                await callback.message.answer("Вернитесь в главное меню:", reply_markup=make_main_keyboard())
                return
            
            # Получаем URL для скачивания отчета
            download_url = await download_report(filename)
            
            # Проверяем, что URL получен успешно
            if not download_url:
                await callback.message.answer("❌ Ошибка: не удалось получить ссылку на отчет. Попробуйте позже.")
                await state.clear()
                await callback.message.answer("Вернитесь в главное меню:", reply_markup=make_main_keyboard())
                return
            
            # Создаем клавиатуру для скачивания
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📥 Скачать отчет", url=download_url)]
            ])
            
            await callback.message.answer(
                f"✅ Отчет успешно сгенерирован!\n"
                f"Период: с {start_date} по {end_date}\n"
                f"Нажмите на кнопку ниже, чтобы скачать отчет:",
                reply_markup=keyboard
            )
        else:
            error_msg = result.get("message", "Неизвестная ошибка") or result.get("detail", "Неизвестная ошибка")
            await callback.message.answer(f"❌ Ошибка при генерации отчета: {error_msg}")
        
        # Сбрасываем состояние
        await state.clear()
        await callback.message.answer("Вернитесь в главное меню:", reply_markup=make_main_keyboard())
        
    except Exception as e:
        logging.error(f"Ошибка при генерации отчета: {e}", exc_info=True)
        await callback.message.answer(
            f"❌ Произошла ошибка при генерации отчета: {str(e)}"
        )
        await state.clear()
        await callback.message.answer("Вернитесь в главное меню:", reply_markup=make_main_keyboard())
    
    await callback.answer()

# Обработчик для отмены генерации отчета
@router.callback_query(F.data == "cancel_report")
async def process_report_cancellation(callback: CallbackQuery, state: FSMContext):
    """
    Обработчик для отмены генерации отчета
    """
    from bot.keyboards.main_kb import make_main_keyboard
    await callback.message.answer(
        "❌ Генерация отчета отменена.",
        reply_markup=make_main_keyboard()
    )
    await state.clear()
    await callback.answer() 