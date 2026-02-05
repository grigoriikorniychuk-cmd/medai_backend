import logging
import asyncio
from datetime import datetime
from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from bot.states.states import LeadsByDate
from bot.models.database import get_clinics_by_user_id
from bot.utils.api import (
    sync_calls_by_date, 
    get_calls_list, 
    download_call, 
    download_and_transcribe_call, 
    analyze_call, 
    download_transcription
)
from bot.keyboards.leads_kb import (
    make_date_keyboard, 
    make_leads_keyboard, 
    make_call_actions_keyboard
)
from bot.keyboards.main_kb import make_main_keyboard

# Создаем роутер для работы со звонками
router = Router(name="leads_router")

# Функция конвертации даты из формата ДД.ММ.ГГГГ в ГГГГ-ММ-ДД для API
def convert_date_format_for_api(date_str: str) -> str:
    """
    Конвертирует дату из формата ДД.ММ.ГГГГ в формат ГГГГ-ММ-ДД для API
    
    Args:
        date_str: Строка даты в формате ДД.ММ.ГГГГ
        
    Returns:
        Строка даты в формате ГГГГ-ММ-ДД
    """
    try:
        # Пробуем стандартный формат
        date_obj = datetime.strptime(date_str, "%d.%m.%Y")
        api_date = date_obj.strftime("%Y-%m-%d")
        logging.info(f"Успешно сконвертирована дата из {date_str} в {api_date}")
        return api_date
    except ValueError as e:
        logging.error(f"Ошибка при конвертации даты {date_str}: {str(e)}")
        
        # Попробуем другие форматы
        try:
            # Может быть дата уже в формате ГГГГ-ММ-ДД
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
            logging.info(f"Дата {date_str} уже в формате ГГГГ-ММ-ДД")
            return date_str
        except ValueError:
            pass
        
        # Попробуем еще другие возможные форматы
        for fmt in ["%Y.%m.%d", "%d-%m-%Y", "%m/%d/%Y"]:
            try:
                date_obj = datetime.strptime(date_str, fmt)
                api_date = date_obj.strftime("%Y-%m-%d")
                logging.info(f"Успешно сконвертирована дата из {date_str} в {api_date} с форматом {fmt}")
                return api_date
            except ValueError:
                continue
        
        # Если ничего не подошло, вернем исходную строку и залогируем ошибку
        logging.error(f"Не удалось сконвертировать дату {date_str} в формат ГГГГ-ММ-ДД. Используем как есть.")
        return date_str

# Обработчик команды /leads
@router.message(Command("leads"))
async def cmd_leads(message: Message, state: FSMContext):
    """
    Обработчик команды для получения звонков по дате
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
    await state.update_data(client_id=client_id)
    
    # Создаем клавиатуру с датами
    keyboard = make_date_keyboard()
    
    await message.answer(
        "Выберите дату для получения звонков или введите в формате ДД.ММ.ГГГГ:",
        reply_markup=keyboard
    )
    
    # Устанавливаем состояние ожидания даты
    await state.set_state(LeadsByDate.date)

# Обработчик ввода даты для получения звонков
@router.message(StateFilter(LeadsByDate.date))
async def process_date_input(message: Message, state: FSMContext):
    """
    Обработчик для ввода даты
    """
    # Обработка отмены
    if message.text and message.text.lower() in ["отмена", "/cancel"]:
        await state.clear()
        await message.answer("Операция отменена. Вы в главном меню.", reply_markup=make_main_keyboard())
        return
    if not message.text:
        await message.answer("Пожалуйста, отправьте текстовое сообщение с датой в формате ДД.ММ.ГГГГ.")
        return
    
    date_text = message.text.strip()
    
    # Извлекаем дату из сообщения, включая кнопки
    # Проверяем формат для кнопок "Сегодня", "Вчера", "Позавчера"
    if "Сегодня" in date_text or "Вчера" in date_text or "Позавчера" in date_text:
        # Извлекаем дату из скобок: "Сегодня (03.05.2025)" -> "03.05.2025"
        import re
        match = re.search(r'\((\d{2}\.\d{2}\.\d{4})\)', date_text)
        if match:
            formatted_date = match.group(1)
        else:
            await message.answer(
                "Не удалось извлечь дату из сообщения. Пожалуйста, введите дату в формате ДД.ММ.ГГГГ."
            )
            # Сбрасываем состояние, чтобы избежать зацикливания
            await state.clear()
            return
    else:
        # Если это не предустановленная кнопка, проверяем формат напрямую
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
            await message.answer(
                "Неверный формат даты. Пожалуйста, введите дату в формате ДД.ММ.ГГГГ или нажмите /cancel для отмены."
            )
            # Сбрасываем состояние, чтобы избежать зацикливания
            await state.clear()
            # Начинаем заново - повторно показываем клавиатуру выбора даты
            await cmd_leads(message, state)
            return
    
    # Загружаем данные из состояния
    data = await state.get_data()
    client_id = data.get("client_id")
    
    # Отправляем сообщение о начале синхронизации
    processing_message = await message.answer(
        f"⏳ Синхронизация звонков с AmoCRM для даты {formatted_date}...\n"
        "Это может занять некоторое время."
    )
    
    try:
        # Конвертируем дату в формат ГГГГ-ММ-ДД для API
        api_date_format = convert_date_format_for_api(formatted_date)
        logging.info(f"Конвертированная дата для API: {api_date_format}")
        
        # Синхронизируем звонки с AmoCRM
        sync_result = await sync_calls_by_date(api_date_format, client_id)
        
        # Проверяем ответ от API
        sync_successful = sync_result.get("success", False)
        sync_message = sync_result.get("message", "")

        # Проверяем, была ли синхронизация уже выполнена ранее
        already_synced = "уже была выполнена" in sync_message

        if not sync_successful and not already_synced:
            # Это настоящая ошибка синхронизации
            await processing_message.delete()
            await message.answer(
                f"❌ Ошибка при синхронизации звонков: {sync_message}\n\n"
                f"Дата: {formatted_date} (формат для API: {api_date_format})\n"
                f"Пожалуйста, попробуйте другую дату или повторите запрос позже."
            )
            logging.error(f"Ошибка при синхронизации звонков: {sync_message}, дата: {api_date_format}")
            return
        
        if already_synced:
            logging.info(f"Данные за {api_date_format} уже синхронизированы. Загружаем из базы данных.")
            # Удаляем сообщение о синхронизации и показываем новое
            await processing_message.edit_text(f"✅ Данные за {formatted_date} уже были синхронизированы. Загружаем звонки из базы...")
        else:
            # Если была успешная синхронизация, просто обновляем сообщение
            await processing_message.edit_text(f"✅ Синхронизация завершена! Загружаем звонки...")
        
        # Получаем список звонков из базы данных
        calls_result = await get_calls_list(
            client_id=client_id, 
            start_date=api_date_format,  # Используем конвертированный формат
            end_date=api_date_format     # Используем конвертированный формат
        )
        
        if not calls_result.get("success", False) or not calls_result.get("data", {}).get("calls", []):
            await processing_message.delete()
            await message.answer(
                f"ℹ️ Звонки на дату {formatted_date} не найдены.\n"
                "Возможно, в выбранную дату не было звонков."
            )
            await state.clear()
            return
        
        # Сохраняем результаты в состоянии
        calls = calls_result.get("data", {}).get("calls", [])
        await state.update_data(calls=calls, date=formatted_date)
        
        # Группируем звонки по lead_id
        leads = {}
        for call in calls:
            lead_id = call.get("lead_id")
            if lead_id:
                if lead_id not in leads:
                    leads[lead_id] = {
                        "id": lead_id,
                        "name": call.get("lead_name", f"Сделка #{lead_id}"),
                        "calls": []
                    }
                leads[lead_id]["calls"].append(call)
        
        # Сохраняем сделки в состоянии
        await state.update_data(leads=list(leads.values()))
        
        # Удаляем сообщение о процессе
        await processing_message.delete()
        
        # Отправляем сообщение с результатами синхронизации
        await message.answer(
            f"✅ Синхронизация завершена!\n"
            f"Найдено {len(calls)} звонков в {len(leads)} сделках.\n"
            f"Выберите сделку для просмотра звонков:"
        )
        
        # Создаем клавиатуру для выбора сделок
        keyboard = make_leads_keyboard(list(leads.values()))
        
        await message.answer(
            "Список сделок с звонками:", 
            reply_markup=keyboard
        )
        
    except Exception as e:
        logging.error(f"Ошибка при синхронизации звонков: {e}", exc_info=True)
        await processing_message.delete()
        await message.answer(
            f"❌ Произошла ошибка при обработке запроса: {str(e)}\n\n"
            f"Возможные причины:\n"
            f"1. Сервер временно недоступен\n"
            f"2. Проблема с форматом даты\n"
            f"3. Проблема с подключением к AmoCRM\n\n"
            f"Пожалуйста, попробуйте позже или выберите другую дату."
        )
        await state.clear()

# Обработчик для кнопок с выбором сделки
@router.callback_query(F.data.startswith("lead_"))
async def process_lead_selection(callback: CallbackQuery, state: FSMContext):
    """
    Обработчик для выбора сделки
    """
    lead_id = callback.data.split("_")[1]
    
    # Загружаем данные из состояния
    data = await state.get_data()
    leads = data.get("leads", [])
    
    # Находим выбранную сделку
    selected_lead = None
    for lead in leads:
        if str(lead["id"]) == lead_id:
            selected_lead = lead
            break
    
    if not selected_lead:
        await callback.answer("Сделка не найдена")
        return
    
    # Получаем звонки для этой сделки
    calls = selected_lead.get("calls", [])
    
    if not calls:
        await callback.answer("В этой сделке нет звонков")
        return
    
    # Сохраняем выбранную сделку и её звонки в состоянии
    await state.update_data(selected_lead=selected_lead, selected_lead_calls=calls)
    
    # Формируем сообщение со списком звонков
    calls_message = (
        f"📞 Звонки по сделке: {selected_lead['name']}\n\n"
    )
    
    for i, call in enumerate(calls, 1):
        direction = "📥" if call.get("call_direction") == "Входящий" else "📤"
        duration = call.get("duration_formatted", "0:00")
        phone = call.get("phone", "Нет номера")
        admin = call.get("administrator", "Не указан")
        
        calls_message += (
            f"{i}. {direction} {phone}\n"
            f"   Длительность: {duration}, Администратор: {admin}\n"
            f"   Дата: {call.get('created_date', 'Не указана')}\n\n"
        )
    
    # Создаем клавиатуру для действий с звонками - теперь функция поддерживает работу со списком звонков
    keyboard = make_call_actions_keyboard(calls)
    
    # Отправляем сообщение с клавиатурой
    await callback.message.answer(calls_message, reply_markup=keyboard)
    await callback.answer()

# Обработчик для скачивания звонка
@router.callback_query(F.data.startswith("download_call_"))
async def process_download_call(callback: CallbackQuery, state: FSMContext):
    """
    Обработчик для скачивания звонка
    """
    call_id = callback.data.split("_")[2]
    
    # Загружаем данные из состояния
    data = await state.get_data()
    calls = data.get("selected_lead_calls", [])
    
    # Находим выбранный звонок
    selected_call = None
    for call in calls:
        if str(call.get("_id")) == call_id:
            selected_call = call
            break
    
    if not selected_call:
        await callback.answer("Звонок не найден")
        return
    
    # Получаем URL для скачивания
    download_url = await download_call(call_id)
    
    # Создаем инлайн-клавиатуру с URL для скачивания
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 Скачать звонок", url=download_url)]
    ])
    
    # Отправляем сообщение с кнопкой для скачивания
    await callback.message.answer(
        f"Для скачивания звонка нажмите на кнопку ниже:",
        reply_markup=keyboard
    )
    await callback.answer()

# Обработчик для транскрибации звонка
@router.callback_query(F.data.startswith("transcribe_"))
async def process_transcribe_call(callback: CallbackQuery, state: FSMContext):
    """
    Обработчик для транскрибации звонка
    """
    call_id = callback.data.split("_")[1]
    
    # Загружаем данные из состояния
    data = await state.get_data()
    calls = data.get("selected_lead_calls", [])
    
    # Находим выбранный звонок
    selected_call = None
    for call in calls:
        if str(call.get("_id")) == call_id:
            selected_call = call
            break
    
    if not selected_call:
        await callback.answer("Звонок не найден")
        return
    
    # Проверяем, есть ли уже существующая транскрибация
    if selected_call.get("filename_transcription"):
        # Если файл транскрибации уже существует, сразу показываем ссылки
        transcription_file = selected_call.get("filename_transcription")
        download_url = await download_call(call_id)
        transcription_url = await download_transcription(transcription_file)
        
        # Создаем клавиатуру с обеими ссылками
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="📥 Скачать звонок", url=download_url),
                InlineKeyboardButton(text="📄 Скачать транскрибацию", url=transcription_url)
            ],
            [
                InlineKeyboardButton(text="🧠 Анализировать звонок", callback_data=f"analyze_{call_id}")
            ]
        ])
        
        await callback.message.answer(
            f"✅ Транскрибация для этого звонка уже существует!\n"
            f"Выберите действие:",
            reply_markup=keyboard
        )
        await callback.answer()
        return
    
    # Отправляем сообщение о начале транскрибации
    processing_message = await callback.message.answer("⏳ Начинаем транскрибацию звонка... Пожалуйста, подождите.")
    
    try:
        # Запускаем транскрибацию
        result = await download_and_transcribe_call(call_id)
        
        if not result.get("success", False):
            await processing_message.delete()
            await callback.message.answer(
                f"❌ Ошибка при транскрибации: {result.get('message', 'Неизвестная ошибка')}"
            )
            return
        
        # Получаем данные из ответа API
        api_data = result.get("data", {})
        
        # Проверяем наличие URL транскрибации в ответе
        transcription_url = api_data.get("transcription_url")
        
        if not transcription_url:
            await processing_message.delete()
            await callback.message.answer(
                "⌛ Транскрибация запущена успешно, но URL файла еще не доступен.\n"
                "Пожалуйста, проверьте позже. Обычно это занимает около 10 секунд."
            )
            return
        
        # Получаем полный URL для скачивания транскрипции
        transcription_download_url = await download_transcription(transcription_url)
        
        # Получаем URL для скачивания звонка
        call_download_url = await download_call(call_id)
        
        # Создаем клавиатуру для действий с транскрибацией и звонком
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="📄 Скачать транскрибацию", url=transcription_download_url)
            ],
            [
                InlineKeyboardButton(text="🧠 Анализировать звонок", callback_data=f"analyze_{call_id}")
            ]
        ])
        
        # Удаляем сообщение о загрузке
        await processing_message.delete()
        
        await callback.message.answer(
            f"✅ Транскрибация запущена успешно!\n"
            f"Выберите действие:",
            reply_markup=keyboard
        )
        
    except Exception as e:
        logging.error(f"Ошибка при транскрибации звонка: {e}", exc_info=True)
        await processing_message.delete()
        await callback.message.answer(
            f"❌ Произошла ошибка при транскрибации: {str(e)}"
        )
    
    await callback.answer()

# Обработчик для анализа звонка
@router.callback_query(F.data.startswith("analyze_"))
async def process_analyze_call(callback: CallbackQuery, state: FSMContext):
    """
    Обработчик для анализа звонка
    """
    call_id = callback.data.split("_")[1]
    await callback.message.answer("⏳ Начинаем анализ звонка с помощью ИИ...")
    try:
        result = await analyze_call(call_id)
        print("--------------------------", result)
        if not result.get("success", False):
            await callback.message.answer(
                f"❌ Ошибка при анализе: {result.get('message', 'Неизвестная ошибка')}"
            )
            return
        # Извлекаем данные из ответа API
        analysis_results = result.get("analysis_results", {})
        call_type_data = result.get("call_type", {})

        # Основные поля
        call_type = call_type_data.get("call_type", "Неизвестно")
        recommendations = analysis_results.get("recommendations", [])
        conversion = analysis_results.get("conversion", None)
        score = analysis_results.get("overall_score", None)
        tone = analysis_results.get("tone", None)
        satisfaction = analysis_results.get("customer_satisfaction", None)
        # Формируем сообщение
        analysis_message = (
            f"📊 Результаты анализа звонка:\n\n"
            f"🏷️ Тип звонка: {call_type}\n"
        )
        if conversion is not None:
            analysis_message += f"\n🔄 Конверсия: {'Да' if conversion else 'Нет'}"
        if score is not None:
            analysis_message += f"\n📈 Общая оценка: {score}/10"
        
        # Рекомендации
        if recommendations:
            analysis_message += "\n\n💡 Рекомендации:\n"
            for i, rec in enumerate(recommendations, 1):
                analysis_message += f"{i}. {rec}\n"
        # (опционально) ссылка на файл анализа
        # if analysis_id:
        #     analysis_message += f"\n[Файл анализа]({analysis_id})"
        await callback.message.answer(analysis_message)
    except Exception as e:
        logging.error(f"Ошибка при анализе звонка: {e}", exc_info=True)
        await callback.message.answer(
            f"❌ Произошла ошибка при анализе звонка: {str(e)}"
        )
    await callback.answer()

# Обработчик выбора звонка
@router.callback_query(F.data.startswith("call_"))
async def process_call_selection(callback: CallbackQuery, state: FSMContext):
    """
    Обработчик выбора звонка из списка
    """
    call_id = callback.data.split("_")[1]
    
    # Загружаем данные из состояния
    data = await state.get_data()
    calls = data.get("selected_lead_calls", [])
    
    # Находим выбранный звонок
    selected_call = None
    for call in calls:
        if str(call.get("_id")) == call_id:
            selected_call = call
            break
    
    if not selected_call:
        await callback.answer("Звонок не найден")
        return
    
    # Получаем клавиатуру для действий с звонком (один конкретный звонок)
    keyboard = make_call_actions_keyboard(selected_call)
    
    # Форматируем информацию о звонке
    try:
        created_at = selected_call.get("created_at", "")
        if created_at:
            # Пытаемся преобразовать в datetime
            call_date = datetime.fromisoformat(created_at).strftime("%d.%m.%Y %H:%M")
        else:
            call_date = selected_call.get("created_date", "Неизвестно")
    except (ValueError, TypeError):
        # Если не удалось преобразовать дату, используем строковое представление
        call_date = selected_call.get("created_date", "Неизвестно")
    
    call_status = selected_call.get("status", "Неизвестно")
    call_direction = "Исходящий" if selected_call.get("direction") == "outgoing" else "Входящий"
    call_duration = selected_call.get("duration", 0)
    call_minutes = call_duration // 60
    call_seconds = call_duration % 60
    
    # Форматируем и отправляем сообщение
    message_text = (
        f"📞 <b>Информация о звонке</b>\n\n"
        f"📅 <b>Дата:</b> {call_date}\n"
        f"🔄 <b>Направление:</b> {call_direction}\n"
        f"⏱ <b>Длительность:</b> {call_minutes} мин {call_seconds} сек\n"
        f"📊 <b>Статус:</b> {call_status}\n"
    )
    
    # Если есть транскрибация, добавляем информацию
    if selected_call.get("filename_transcription"):
        message_text += f"\n✅ <b>Звонок транскрибирован</b>"
    
    await callback.message.answer(message_text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()

# Обработчик для скачивания транскрибации
@router.callback_query(F.data.startswith("download_transcript_"))
async def process_download_transcript(callback: CallbackQuery, state: FSMContext):
    """
    Обработчик для скачивания транскрибации звонка
    """
    call_id = callback.data.split("_")[2]
    
    # Загружаем данные из состояния
    data = await state.get_data()
    calls = data.get("selected_lead_calls", [])
    
    # Находим выбранный звонок
    selected_call = None
    for call in calls:
        if str(call.get("_id")) == call_id:
            selected_call = call
            break
    
    if not selected_call:
        await callback.answer("Звонок не найден")
        return
    
    # Проверяем наличие файла транскрибации
    transcription_file = selected_call.get("filename_transcription")
    if not transcription_file:
        await callback.answer("Файл транскрибации не найден")
        return
    
    # Получаем URL для скачивания транскрибации
    download_url = await download_transcription(transcription_file)
    
    # Создаем инлайн-клавиатуру с URL для скачивания
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📄 Скачать транскрибацию", url=download_url)]
    ])
    
    # Отправляем сообщение с кнопкой для скачивания
    await callback.message.answer(
        f"Для скачивания транскрибации нажмите на кнопку ниже:",
        reply_markup=keyboard
    )
    await callback.answer()

# Обработчик для кнопки "Назад" к выбору даты
@router.callback_query(F.data == "back_to_date")
async def process_back_to_date(callback: CallbackQuery, state: FSMContext):
    """
    Обработчик для возврата к выбору даты
    """
    # Очищаем состояние, чтобы начать заново
    await state.clear()
    
    # Создаем клавиатуру с датами
    keyboard = make_date_keyboard()
    
    # Отправляем сообщение с клавиатурой
    await callback.message.answer(
        "Выберите дату для получения звонков или введите в формате ДД.ММ.ГГГГ:",
        reply_markup=keyboard
    )
    
    # Устанавливаем состояние ожидания даты
    await state.set_state(LeadsByDate.date)
    
    # Отвечаем на callback, чтобы убрать часы загрузки
    await callback.answer()

# Обработчик для кнопки "Назад" к выбору сделок
@router.callback_query(F.data == "back_to_leads")
async def process_back_to_leads(callback: CallbackQuery, state: FSMContext):
    """
    Обработчик для возврата к списку сделок
    """
    # Загружаем данные из состояния
    data = await state.get_data()
    leads = data.get("leads", [])
    
    if not leads:
        await callback.answer("Не найдены сделки. Начните заново.")
        await state.clear()
        return
    
    # Создаем клавиатуру для выбора сделок
    keyboard = make_leads_keyboard(leads)
    
    # Отправляем сообщение с клавиатурой
    await callback.message.answer(
        "Список сделок с звонками:", 
        reply_markup=keyboard
    )
    
    # Отвечаем на callback, чтобы убрать часы загрузки
    await callback.answer() 