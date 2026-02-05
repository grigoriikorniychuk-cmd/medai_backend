import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardRemove, ReplyKeyboardMarkup, KeyboardButton

from bot.models.database import get_clinics_by_user_id, get_clinic_by_client_id, add_user_to_clinic
from bot.keyboards.main_kb import make_main_keyboard
from bot.states.states import AuthStates, ClinicRegistration
import aiohttp

# Создаем роутер для общих команд
router = Router(name="common_commands_router")

# Обработчик команды /start или кнопки "Главная"
@router.message(Command("start"))
@router.message(F.text == "🏠 Главная")
async def cmd_start(message: Message, state: FSMContext = None):
    """
    Обработчик команды /start или кнопки "Главная"
    Проверяет привязку пользователя к клинике через базу
    """
    if state:
        await state.clear()
    user_id = message.from_user.id
    username = message.from_user.username

    # Проверяем привязку пользователя к клинике
    user_clinics = await get_clinics_by_user_id(user_id)

    if user_clinics:
        greeting = (
            f"Добро пожаловать в бот MedAI для работы с звонками клиники, {username}!\n"
            f"Вы привязаны к клинике: {user_clinics[0]['name']}\n"
            "\n"
            "Бот позволяет:\n"
            "• Искать звонки по датам\n"
            "• Скачивать записи звонков\n"
            "• Делать транскрибацию звонков\n"
            "• Анализировать звонки с помощью ИИ\n"
            "• Создавать отчеты по звонкам\n"
        )
        main_keyboard = make_main_keyboard()
        await message.answer(greeting, reply_markup=main_keyboard)
    else:
        # Нет привязки — предлагаем авторизацию или регистрацию
        auth_reg_kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="Авторизация")]
            ],
            resize_keyboard=True
        )
        await message.answer(
            "У вас нет привязанных клиник.\n"
            "Если у вас уже есть зарегистрированная клиника в нашей системе, нажмите кнопку 'Авторизация' и введите client_id вашей клиники.",
            reply_markup=auth_reg_kb
        )
        await state.set_state(AuthStates.awaiting_client_id)

# Обработчик кнопки "Авторизация" (работает только если пользователь не привязан)
@router.message(F.text == "Авторизация")
async def button_authorization(message: Message, state: FSMContext):
    await message.answer(
        "Пожалуйста, введите client_id вашей клиники для авторизации:",
        reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Отмена")]], resize_keyboard=True)
    )
    await state.set_state(AuthStates.awaiting_client_id)

# Обработчик кнопки "Получить сделки"
@router.message(F.text == "📞 Получить сделки")
async def button_leads(message: Message, state: FSMContext):
    """
    Обработчик кнопки "Получить сделки"
    Перенаправляет на команду /leads
    """
    if state:
        await state.clear()
    # Импортируем обработчик из другого модуля
    from bot.handlers.leads import cmd_leads
    
    # Вызываем обработчик команды /leads
    await cmd_leads(message, state)

# Обработчик кнопки "Создать отчёт"
@router.message(F.text == "📊 Создать отчёт")
async def button_report(message: Message, state: FSMContext):
    """
    Обработчик кнопки "Создать отчёт"
    Перенаправляет на команду /report
    """
    # Импортируем обработчик из другого модуля
    from bot.handlers.reports import cmd_report
    if state:
        await state.clear()
    
    # Вызываем обработчик команды /report
    await cmd_report(message, state)

# Обработчик кнопки "Регистрация клиники"
@router.message(F.text == "📋 Регистрация клиники")
async def button_register_clinic(message: Message, state: FSMContext):
    await message.answer("Регистрация происходит через веб-интерфейс!")

# Обработчик кнопки "Профиль"
# @router.message(F.text == "👤 Профиль")
# async def button_profile(message: Message, state: FSMContext):
#     """
#     Обработчик кнопки "Профиль"
#     Перенаправляет на команду /profile
#     """
#     if state:
#         await state.clear()
#     # Вызываем обработчик команды /profile
#     await cmd_profile(message, state)

# Обработчик команды /profile
# @router.message(Command("profile"))
# async def cmd_profile(message: Message, state: FSMContext = None):
#     """
#     Обработчик команды /profile
#     """
#     if state:
#         await state.clear()
#     user_id = message.from_user.id
    
#     # Находим все клиники пользователя
#     user_clinics = await get_clinics_by_user_id(user_id)
    
#     if not user_clinics:
#         await message.answer(
#             "У вас нет привязанных клиник.\n"
#             "Используйте команду /register для регистрации новой клиники.",
#             reply_markup=make_main_keyboard()
#         )
#         return
    
#     response = "Ваш профиль:\n\n"
#     response += f"Telegram ID: {user_id}\n"
#     response += f"Username: @{message.from_user.username}\n\n"
#     response += "Привязанные клиники:\n"
    
#     for i, clinic in enumerate(user_clinics, 1):
#         response += f"{i}. {clinic['name']}\n"
    
#     await message.answer(response, reply_markup=make_main_keyboard())

# Обработчик команды /cancel для выхода из любого состояния
@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    """
    Глобальный обработчик /cancel для сброса любого состояния и возврата в главное меню
    """
    await state.clear()
    await message.answer("Операция отменена. Вы в главном меню.", reply_markup=make_main_keyboard())

# Универсальный обработчик текстовой команды "отмена" для любого состояния
@router.message(lambda m: m.text and m.text.lower() == "отмена")
async def text_cancel_handler(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Операция отменена. Вы в главном меню.", reply_markup=make_main_keyboard())

# Обработчик состояния AuthStates.awaiting_client_id
@router.message(AuthStates.awaiting_client_id)
async def process_client_id_auth(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text.lower() in ["отмена", "/cancel"]:
        await state.clear()
        await message.answer("Операция отменена. Вы в главном меню.", reply_markup=make_main_keyboard())
        return
    client_id = text
    user_id = message.from_user.id
    clinic = await get_clinic_by_client_id(client_id)
    if clinic:
        await add_user_to_clinic(client_id, user_id)
        await state.clear()
        await message.answer(
            f"Вы успешно привязаны к клинике: {clinic['name']}!\nТеперь вы можете пользоваться всеми функциями бота.",
            reply_markup=make_main_keyboard()
        )
    else:
        await message.answer(
            "Клиника с таким client_id не найдена. Проверьте правильность ввода или зарегистрируйте новую клинику.",
            reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📋 Регистрация клиники")], [KeyboardButton(text="Отмена")]], resize_keyboard=True)
        )

# Обработчик неизвестных сообщений (должен идти в самом конце)
@router.message()
async def process_unknown_message(message: Message, state: FSMContext):
    # Не отвечаем на 'отмена' и '/cancel', чтобы не дублировать сообщения после сброса FSM
    if message.text and message.text.lower() in ["отмена", "/cancel"]:
        return
    """
    Обработчик всех остальных сообщений, которые не попали под другие фильтры
    """
    current_state = await state.get_state()
    user_id = message.from_user.id
    username = message.from_user.username
    text = message.text if message.text else "[Нет текста]"
    
    # Отладка: подробная информация о необработанном сообщении
    # logging.info(f"ОТЛАДКА - Необработанное сообщение: ID: {message.message_id}")
    # logging.info(f"ОТЛАДКА - От: {username} (ID: {user_id})")
    # logging.info(f"ОТЛАДКА - Текст: {text}")
    # logging.info(f"ОТЛАДКА - Состояние FSM: {current_state}")
    # logging.info(f"ОТЛАДКА - Тип сообщения: {type(message)}")
    
    if current_state:
        await message.answer(
            f"Извините, но я не ожидал такого сообщения в текущем состоянии.\n"
            f"Текущее состояние: {current_state}\n"
            f"Ваше сообщение: {text}\n"
            f"Тип сообщения: {type(message)}\n"
            "Вы можете отменить текущую операцию командой /cancel",
            reply_markup=make_main_keyboard()
        )
    else:
        await message.answer(
            "Я не понимаю, что вы хотите сделать.\n"
            "Используйте кнопки ниже для взаимодействия с ботом.",
            reply_markup=make_main_keyboard()
        ) 