from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext

from bot.states.states import ClinicRegistration, AuthStates
from bot.models.database import clinics_collection, create_clinic_with_user
from bot.config.config import API_URL
from bot.keyboards.main_kb import make_main_keyboard
from bot.utils.clinic_service import ClinicService

# Создаем роутер для регистрации
router = Router(name="registration_router")


# Обработчик команды /register
@router.message(Command("register"))
async def cmd_register(message: Message, state: FSMContext):
    """
    Обработчик команды для начала регистрации клиники.
    Временно отключен. Сообщает пользователю о регистрации через веб-интерфейс.
    """
    await message.answer("Регистрация происходит через веб-интерфейс!")

# Универсальная функция для проверки отмены
async def check_cancel(message, state):
    if message.text and message.text.lower() in ["отмена", "/cancel"]:
        await state.clear()
        await message.answer("Операция отменена. Вы в главном меню.", reply_markup=make_main_keyboard())
        return True
    return False

# Обработчик ввода названия клиники
@router.message(StateFilter(ClinicRegistration.name))
async def process_name(message: Message, state: FSMContext):
    if await check_cancel(message, state):
        return
    if not message.text:
        await message.answer("Пожалуйста, отправьте текстовое сообщение с названием клиники.", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Отмена")]], resize_keyboard=True))
        return
    await state.update_data(name=message.text)
    await message.answer("Введите поддомен AmoCRM:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Отмена")]], resize_keyboard=True))
    await state.set_state(ClinicRegistration.amocrm_subdomain)

# Обработчик ввода поддомена AmoCRM
@router.message(StateFilter(ClinicRegistration.amocrm_subdomain))
async def process_amocrm_subdomain(message: Message, state: FSMContext):
    if await check_cancel(message, state):
        return
    if not message.text:
        await message.answer("Пожалуйста, отправьте текстовое сообщение с поддоменом AmoCRM.", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Отмена")]], resize_keyboard=True))
        return
    await state.update_data(amocrm_subdomain=message.text)
    await message.answer("Введите client_id:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Отмена")]], resize_keyboard=True))
    await state.set_state(ClinicRegistration.client_id)

# Обработчик ввода client_id
@router.message(StateFilter(ClinicRegistration.client_id))
async def process_client_id(message: Message, state: FSMContext):
    if await check_cancel(message, state):
        return
    if not message.text:
        await message.answer("Пожалуйста, отправьте текстовое сообщение с client_id.", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Отмена")]], resize_keyboard=True))
        return
    await state.update_data(client_id=message.text)
    await message.answer("Введите client_secret:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Отмена")]], resize_keyboard=True))
    await state.set_state(ClinicRegistration.client_secret)

# Обработчик ввода client_secret
@router.message(StateFilter(ClinicRegistration.client_secret))
async def process_client_secret(message: Message, state: FSMContext):
    if await check_cancel(message, state):
        return
    if not message.text:
        await message.answer("Пожалуйста, отправьте текстовое сообщение с client_secret.", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Отмена")]], resize_keyboard=True))
        return
    await state.update_data(client_secret=message.text)
    await message.answer("Введите redirect_url:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Отмена")]], resize_keyboard=True))
    await state.set_state(ClinicRegistration.redirect_url)

# Обработчик ввода redirect_url
@router.message(StateFilter(ClinicRegistration.redirect_url))
async def process_redirect_url(message: Message, state: FSMContext):
    if await check_cancel(message, state):
        return
    if not message.text:
        await message.answer("Пожалуйста, отправьте текстовое сообщение с redirect_url.", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Отмена")]], resize_keyboard=True))
        return
    await state.update_data(redirect_url=message.text)
    await message.answer("Введите auth_code:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Отмена")]], resize_keyboard=True))
    await state.set_state(ClinicRegistration.auth_code)

# Обработчик ввода auth_code
@router.message(StateFilter(ClinicRegistration.auth_code))
async def process_auth_code(message: Message, state: FSMContext):
    if await check_cancel(message, state):
        return
    if not message.text:
        await message.answer("Пожалуйста, отправьте текстовое сообщение с auth_code.", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Отмена")]], resize_keyboard=True))
        return
    await state.update_data(auth_code=message.text)
    await message.answer("Введите amocrm_pipeline_id (число):", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Отмена")]], resize_keyboard=True))
    await state.set_state(ClinicRegistration.amocrm_pipeline_id)

# Обработчик ввода amocrm_pipeline_id
@router.message(StateFilter(ClinicRegistration.amocrm_pipeline_id))
async def process_amocrm_pipeline_id(message: Message, state: FSMContext):
    if await check_cancel(message, state):
        return
    if not message.text:
        await message.answer("Пожалуйста, отправьте число для amocrm_pipeline_id.", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Отмена")]], resize_keyboard=True))
        return
    if not message.text.isdigit():
        await message.answer("Ошибка! Введите число для amocrm_pipeline_id:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Отмена")]], resize_keyboard=True))
        return
    await state.update_data(amocrm_pipeline_id=int(message.text))
    await message.answer("Введите месячный лимит (число):", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Отмена")]], resize_keyboard=True))
    await state.set_state(ClinicRegistration.monthly_limit)

# Обработчик ввода monthly_limit
@router.message(StateFilter(ClinicRegistration.monthly_limit))
async def process_monthly_limit(message: Message, state: FSMContext):
    if await check_cancel(message, state):
        return
    if not message.text:
        await message.answer("Пожалуйста, отправьте число для месячного лимита.", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Отмена")]], resize_keyboard=True))
        return
    if not message.text.isdigit():
        await message.answer("Ошибка! Введите число для месячного лимита:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Отмена")]], resize_keyboard=True))
        return
    await state.update_data(monthly_limit=int(message.text))
    data = await state.get_data()
    confirmation_message = (
        "Пожалуйста, проверьте данные:\n\n"
        f"Название клиники: {data['name']}\n"
        f"Поддомен AmoCRM: {data['amocrm_subdomain']}\n"
        f"Client ID: {data['client_id']}\n"
        f"Client Secret: {data['client_secret']}\n"
        f"Redirect URL: {data['redirect_url']}\n"
        f"Auth Code: {data['auth_code']}\n"
        f"AmoCRM Pipeline ID: {data['amocrm_pipeline_id']}\n"
        f"Месячный лимит: {data['monthly_limit']}\n\n"
        "Данные верны? (да/нет)"
    )
    keyboard = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Да"), KeyboardButton(text="Нет")], [KeyboardButton(text="Отмена")]], resize_keyboard=True, one_time_keyboard=True)
    await message.answer(confirmation_message, reply_markup=keyboard)
    await state.set_state(ClinicRegistration.confirmation)

# Обработчик для ответов при подтверждении
@router.message(StateFilter(ClinicRegistration.confirmation))
async def process_confirmation(message: Message, state: FSMContext):
    if await check_cancel(message, state):
        return
    if not message.text:
        await message.answer("Пожалуйста, ответьте 'Да' или 'Нет'.", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Да"), KeyboardButton(text="Нет")], [KeyboardButton(text="Отмена")]], resize_keyboard=True, one_time_keyboard=True))
        return
    text_lower = message.text.lower()
    if text_lower == "да":
        data = await state.get_data()
        clinic_data = {
            "name": data["name"],
            "amocrm_subdomain": data["amocrm_subdomain"],
            "client_id": data["client_id"],
            "client_secret": data["client_secret"],
            "redirect_url": data["redirect_url"],
            "auth_code": data["auth_code"],
            "amocrm_pipeline_id": data["amocrm_pipeline_id"],
            "monthly_limit": data["monthly_limit"]
        }
        user_id = message.from_user.id
        try:
            clinic_service = ClinicService()
            # Добавляем telegram_id пользователя в данные
            clinic_data["telegram_ids"] = [user_id]
            result = await clinic_service.register_clinic(clinic_data)
            if result and result.get("clinic_id"):
                await state.clear()
                await message.answer(
                    "Клиника успешно зарегистрирована и вы к ней привязаны! Теперь вы можете пользоваться всеми функциями бота.",
                    reply_markup=make_main_keyboard()
                )
            else:
                await message.answer("Ошибка при регистрации: не удалось создать клинику в базе данных.")
        except Exception as e:
            await message.answer(f"Ошибка при регистрации: {str(e)}\nПроверьте корректность данных AmoCRM (client_id, client_secret, auth_code и др.)")
    elif text_lower == "нет":
        await message.answer(
            "Регистрация отменена. Используйте /register для повторного начала процесса.",
            reply_markup=make_main_keyboard()
        )
        await state.clear()
    else:
        await message.answer("Пожалуйста, ответьте 'Да' или 'Нет'.", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Да"), KeyboardButton(text="Нет")], [KeyboardButton(text="Отмена")]], resize_keyboard=True, one_time_keyboard=True)) 