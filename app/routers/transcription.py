from bson import ObjectId
from fastapi import APIRouter, HTTPException, status, BackgroundTasks, Response
from fastapi.responses import FileResponse
from typing import Dict, Any, Optional, List
from datetime import datetime
import logging
import os
import re
import fnmatch
import aiofiles
import aiohttp
import traceback
from motor.motor_asyncio import AsyncIOMotorClient
from ..models.transcription import (
    TranscriptionRequest,
    TranscriptionResponse,
    DialogueLine,
    Dialogue,
    TranscriptionRecord,
)
from mlab_amo_async.amocrm_client import AsyncAmoCRMClient
from ..services.transcription_service import (
    transcribe_and_save,
    save_transcription_info,
    find_transcription_file,
)
from ..utils.helpers import cleanup_temp_file
from ..settings.auth import evenlabs
from ..settings.paths import AUDIO_DIR, TRANSCRIPTION_DIR


# Настраиваем логирование
logger = logging.getLogger(__name__)

# Создаем роутер для функций транскрибации
router = APIRouter(tags=["transcription"])

# Глобальные константы
MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "medai"

# Создаем директории, если они не существуют
os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(TRANSCRIPTION_DIR, exist_ok=True)


@router.post("/api/transcribe", response_model=TranscriptionResponse)
async def transcribe_audio(
    request: TranscriptionRequest, background_tasks: BackgroundTasks
):
    """
    Транскрибирует аудиофайл с записью звонка и сохраняет результат в текстовый файл.
    """
    try:
        # Проверяем существование файла
        audio_path = os.path.join(AUDIO_DIR, request.audio_filename)

        if not os.path.exists(audio_path):
            # Если точное имя файла не найдено, пробуем найти файл по ID заметки
            if request.note_id:
                # Ищем файл, содержащий ID заметки
                found = False
                for filename in os.listdir(AUDIO_DIR):
                    if f"note_{request.note_id}" in filename and filename.endswith(
                        ".mp3"
                    ):
                        audio_path = os.path.join(AUDIO_DIR, filename)
                        request.audio_filename = filename
                        found = True
                        logger.info(f"Найден файл по ID заметки: {audio_path}")
                        break

                if not found:
                    return TranscriptionResponse(
                        success=False,
                        message=f"Файл звонка для заметки {request.note_id} не найден в директории {AUDIO_DIR}",
                        data=None,
                    )
            else:
                return TranscriptionResponse(
                    success=False,
                    message=f"Файл {request.audio_filename} не найден в директории {AUDIO_DIR}",
                    data=None,
                )

        logger.info(f"Начало транскрибации файла: {audio_path}")

        # Генерируем имя файла для сохранения результата
        current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        phone_str = ""

        if request.phone:
            # Очищаем номер телефона от лишних символов для использования в имени файла
            phone_str = re.sub(r"[^\d]", "", request.phone)

        # Формируем имя файла
        if phone_str:
            output_filename = f"{phone_str}_{current_time}.txt"
        elif request.note_id:
            output_filename = f"note_{request.note_id}_{current_time}.txt"
        else:
            # Извлекаем ID заметки из имени файла, если возможно
            match = re.search(r"note_(\d+)", request.audio_filename)
            if match:
                note_id = match.group(1)
                output_filename = f"note_{note_id}_{current_time}.txt"
            else:
                output_filename = f"transcript_{current_time}.txt"

        output_path = os.path.join(TRANSCRIPTION_DIR, output_filename)

        # Запускаем транскрибацию в фоновом режиме, чтобы не блокировать ответ API
        background_tasks.add_task(
            transcribe_and_save,
            audio_path=audio_path,
            output_path=output_path,
            num_speakers=request.num_speakers,
            diarize=request.diarize,
            phone=request.phone,
            note_data={"note_id": request.note_id},
            administrator_id=(
                request.administrator_id
                if hasattr(request, "administrator_id")
                else None
            ),  # Добавляем administrator_id
        )

        return TranscriptionResponse(
            success=True,
            message=f"Транскрибация запущена. Результат будет сохранен в файл {output_filename}",
            data={
                "audio_filename": request.audio_filename,
                "transcription_filename": output_filename,
                "status": "processing",
            },
        )

    except Exception as e:
        logger.error(f"Ошибка при транскрибации: {str(e)}")
        return TranscriptionResponse(
            success=False, message=f"Ошибка при транскрибации: {str(e)}", data=None
        )


@router.post("/api/amocrm/contact/call/{note_id}/download-and-transcribe")
async def download_and_transcribe_call(
    note_id: int,
    client_id: str,
    background_tasks: BackgroundTasks,
    num_speakers: int = 2,
    lead_id: Optional[int] = None,
    contact_id: Optional[int] = None,
    is_first_contact: bool = False,
    response: Response = None,
):
    """
    Скачивает запись звонка и запускает её транскрибацию.
    Использует реальные имена менеджера и клиента в транскрипции, если они доступны.
    Сохраняет информацию о транскрипции в MongoDB.
    Автоматически определяет администратора по ответственному в AmoCRM.
    """
    try:
        logger.info(
            f"Запрос на скачивание и транскрибацию звонка: client_id={client_id}, note_id={note_id}, contact_id={contact_id}, lead_id={lead_id}"
        )

        # Находим клинику по client_id
        from ..services.clinic_service import ClinicService

        clinic_service = ClinicService()

        # Получаем клинику
        clinic = await clinic_service.find_clinic_by_client_id(client_id)
        if not clinic:
            logger.warning(f"Клиника с client_id={client_id} не найдена")
            if response:
                response.status_code = status.HTTP_404_NOT_FOUND
            return {
                "success": False,
                "message": f"Клиника с client_id={client_id} не найдена",
                "data": None,
            }

        logger.info(f"Найдена клиника: {clinic['name']} (ID: {clinic['id']})")

        client = AsyncAmoCRMClient(
            client_id=client_id,
            client_secret="",
            subdomain="",
            redirect_url="",
            mongo_uri=MONGO_URI,
            db_name=DB_NAME,
        )

        # Сначала получаем заметку
        note = None
        phone = None
        client_name = None
        manager_name = None
        responsible_user_id = None
        administrator_id = None  # ID администратора будем определять автоматически

        # Если указан ID контакта, ищем заметку у этого контакта
        if contact_id:
            logger.info(f"Получаем заметки для контакта {contact_id}")
            notes = await client.get_contact_notes(contact_id)

            for n in notes:
                if n.get("id") == note_id:
                    note = n
                    logger.info(f"Найдена заметка {note_id} у контакта {contact_id}")

                    # Извлекаем номер телефона из заметки
                    params = n.get("params", {})
                    if params and "phone" in params:
                        phone = params["phone"]
                        logger.info(f"Найден номер телефона в заметке: {phone}")

                    # Получаем ID ответственного
                    responsible_user_id = n.get("responsible_user_id")
                    if responsible_user_id:
                        logger.info(
                            f"ID ответственного в AmoCRM: {responsible_user_id}"
                        )

                    break

            # Получаем данные контакта для имени клиента
            try:
                contact = await client.get_contact(contact_id)
                if contact:
                    # Получаем имя клиента
                    client_name = contact.get("name")
                    if not client_name:
                        # Проверяем поля first_name и last_name
                        first_name = contact.get("first_name", "")
                        last_name = contact.get("last_name", "")
                        if first_name or last_name:
                            client_name = f"{first_name} {last_name}".strip()

                    logger.info(f"Имя клиента: {client_name}")

                    # Если не нашли номер телефона в заметке, ищем в контакте
                    if not phone and "custom_fields_values" in contact:
                        for field in contact.get("custom_fields_values", []):
                            if (
                                field.get("field_code") == "PHONE"
                                and "values" in field
                                and field["values"]
                            ):
                                phone = field["values"][0].get("value")
                                logger.info(
                                    f"Найден номер телефона в контакте: {phone}"
                                )
                                break
            except Exception as e:
                logger.warning(f"Не удалось получить данные контакта: {e}")

        # Если заметка не найдена, ищем в API
        if not note:
            # Пробуем искать заметку среди всех контактов
            try:
                contacts_response, _ = await client.contacts.request(
                    "get", "contacts", params={"with": "leads", "limit": 50}
                )

                if (
                    "_embedded" in contacts_response
                    and "contacts" in contacts_response["_embedded"]
                ):
                    contacts = contacts_response["_embedded"]["contacts"]
                    logger.info(
                        f"Получено {len(contacts)} контактов для поиска заметки {note_id}"
                    )

                    # Ищем заметку среди контактов
                    for contact in contacts:
                        if note:
                            break

                        contact_id = contact.get("id")
                        notes = await client.get_contact_notes(contact_id)

                        for n in notes:
                            if n.get("id") == note_id:
                                note = n
                                logger.info(
                                    f"Найдена заметка {note_id} у контакта {contact_id}"
                                )

                                # Извлекаем номер телефона из заметки
                                params = n.get("params", {})
                                if params and "phone" in params:
                                    phone = params["phone"]
                                    logger.info(
                                        f"Найден номер телефона в заметке: {phone}"
                                    )

                                # Получаем ID ответственного
                                responsible_user_id = n.get("responsible_user_id")
                                if responsible_user_id:
                                    logger.info(
                                        f"ID ответственного: {responsible_user_id}"
                                    )

                                # Получаем имя клиента из контакта
                                client_name = contact.get("name")
                                if not client_name:
                                    # Проверяем поля first_name и last_name
                                    first_name = contact.get("first_name", "")
                                    last_name = contact.get("last_name", "")
                                    if first_name or last_name:
                                        client_name = (
                                            f"{first_name} {last_name}".strip()
                                        )

                                logger.info(f"Имя клиента: {client_name}")

                                break
            except Exception as e:
                logger.error(
                    f"Ошибка при поиске заметки {note_id} среди контактов: {e}"
                )

        # Если заметка не найдена, возвращаем ошибку
        if not note:
            logger.warning(f"Заметка с ID {note_id} не найдена")
            if response:
                response.status_code = status.HTTP_404_NOT_FOUND
            return {
                "success": False,
                "message": f"Заметка с ID {note_id} не найдена",
                "data": None,
            }

        # Получаем ссылку на запись звонка
        params = note.get("params", {})
        call_link = params.get("link")

        if not call_link:
            logger.warning(f"В заметке {note_id} нет ссылки на запись звонка")
            if response:
                response.status_code = status.HTTP_404_NOT_FOUND
            return {
                "success": False,
                "message": f"В заметке {note_id} нет ссылки на запись звонка",
                "data": None,
            }

        # Если есть ID ответственного, пытаемся получить его имя и найти связанного администратора
        if responsible_user_id:
            try:
                # Запрос к API AmoCRM для получения данных о пользователе
                user_response, status_code = await client.contacts.request(
                    "get", f"users/{responsible_user_id}"
                )

                if status_code == 200 and user_response:
                    # Получаем имя ответственного
                    manager_name = user_response.get("name")
                    logger.info(f"Имя ответственного: {manager_name}")

                    # Ищем администратора по amocrm_user_id и клинике
                    mongo_client = AsyncIOMotorClient(MONGO_URI)
                    db = mongo_client[DB_NAME]

                    admin = await db.administrators.find_one(
                        {
                            "amocrm_user_id": str(responsible_user_id),
                            "clinic_id": ObjectId(clinic["id"]),
                        }
                    )

                    if admin:
                        administrator_id = str(admin["_id"])
                        logger.info(
                            f"Найден администратор в системе: {administrator_id} ({admin.get('name', 'Без имени')})"
                        )
                    else:
                        logger.warning(
                            f"Администратор для ответственного {responsible_user_id} не найден в системе"
                        )

                        # Попробуем найти любого администратора для этой клиники
                        admin = await db.administrators.find_one(
                            {"clinic_id": ObjectId(clinic["id"])}
                        )

                        if admin:
                            administrator_id = str(admin["_id"])
                            logger.info(
                                f"Найден администратор по умолчанию: {administrator_id} ({admin.get('name', 'Без имени')})"
                            )
            except Exception as e:
                logger.warning(f"Не удалось получить данные ответственного: {e}")

        # Добавляем параметры аутентификации к ссылке
        account_id = note.get("account_id")
        user_id = note.get("created_by")

        if "userId" not in call_link and account_id and user_id:
            if "?" in call_link:
                call_link += f"&userId={user_id}&accountId={account_id}"
            else:
                call_link += f"?userId={user_id}&accountId={account_id}"

        logger.info(f"Ссылка на запись звонка: {call_link}")

        # Скачиваем звонок
        # Формируем имя файла в соответствии с вашим форматом
        if lead_id:
            file_name = f"lead_{lead_id}_note_{note_id}.mp3"
        else:
            file_name = f"contact_{contact_id}_note_{note_id}.mp3"

        file_path = os.path.join(AUDIO_DIR, file_name)

        # Создаем SSL-контекст с отключенной проверкой сертификата
        import ssl

        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        # Заголовки для имитации браузера
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "audio/webm,audio/ogg,audio/wav,audio/*;q=0.9,application/ogg;q=0.7,video/*;q=0.6,*/*;q=0.5",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://amocrm.mango-office.ru/",
            "Origin": "https://amocrm.mango-office.ru",
        }

        # Скачиваем файл
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        async with aiohttp.ClientSession(
            connector=connector, headers=headers
        ) as session:
            logger.info(f"Скачиваем файл по ссылке: {call_link}")
            download_success = False

            async with session.get(
                call_link, allow_redirects=True
            ) as download_response:
                status_code = download_response.status
                logger.info(f"Статус ответа: {status_code}")

                if status_code == 200:
                    data = await download_response.read()
                    data_size = len(data)

                    if data_size < 1000 or data.startswith(b"<!DOCTYPE"):
                        logger.error(
                            f"Получен неверный формат данных (HTML или слишком маленький размер): {data_size} байт"
                        )
                    else:
                        # Сохраняем файл
                        async with aiofiles.open(file_path, "wb") as f:
                            await f.write(data)

                        logger.info(f"Файл записи звонка сохранен: {file_path}")
                        download_success = True

        if not download_success:
            logger.error(f"Не удалось скачать запись звонка")
            if response:
                response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
            return {
                "success": False,
                "message": "Не удалось скачать запись звонка",
                "data": None,
            }

        # Запускаем транскрибацию в фоновом режиме
        logger.info(f"Запускаем транскрибацию файла: {file_path}")

        # Генерируем имя файла для сохранения результата
        current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        phone_str = ""

        if phone:
            # Очищаем номер телефона от лишних символов для использования в имени файла
            phone_str = re.sub(r"[^\d]", "", phone)

        # Формируем имя файла
        if phone_str:
            output_filename = f"{phone_str}_{current_time}.txt"
        else:
            output_filename = f"note_{note_id}_{current_time}.txt"

        output_path = os.path.join(TRANSCRIPTION_DIR, output_filename)

        # Логируем информацию об администраторе
        if administrator_id:
            logger.info(
                f"Запуск транскрибации с привязкой к администратору ID: {administrator_id}"
            )
        else:
            logger.warning("Администратор не определен, лимиты не будут обновлены")

        # Запускаем транскрибацию в фоновом режиме с использованием имен менеджера и клиента
        background_tasks.add_task(
            transcribe_and_save,
            audio_path=file_path,
            output_path=output_path,
            num_speakers=num_speakers,
            diarize=True,
            phone=phone,
            manager_name=manager_name,
            client_name=client_name,
            is_first_contact=is_first_contact,
            note_data={
                "note_id": note_id,
                "lead_id": lead_id,
                "contact_id": contact_id,
                "client_id": client_id,
            },
            administrator_id=administrator_id,  # Используем определенный ID администратора
        )

        return {
            "success": True,
            "message": "Звонок скачан, транскрибация запущена",
            "data": {
                "note_id": note_id,
                "audio_file": file_name,
                "transcription_file": output_filename,
                "phone": phone,
                "client_name": client_name,
                "manager_name": manager_name,
                "is_first_contact": is_first_contact,
                "status": "processing",
                "found_administrator_id": administrator_id,  # Добавляем для отладки
                "download_url": f"/api/amocrm/contact/call/{note_id}/download?client_id={client_id}"
                + (f"&contact_id={contact_id}" if contact_id else ""),
                "transcription_url": f"/api/transcriptions/{output_filename}/download",
            },
        }

    except Exception as e:
        error_msg = f"Ошибка при скачивании и транскрибации звонка: {str(e)}"
        logger.error(error_msg)

        # Полный стек-трейс для отладки
        logger.error(f"Стек-трейс:\n{traceback.format_exc()}")

        if response:
            response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return {"success": False, "message": error_msg, "data": None}
    finally:
        if "client" in locals():
            await client.close()


@router.get("/api/amocrm/note/{note_id}/transcript/download")
async def download_note_transcript(
    note_id: int,
    client_id: str,
    lead_id: Optional[int] = None,
    contact_id: Optional[int] = None,
    response: Response = None,
):
    """
    Скачивание файла транскрипции звонка по ID заметки.
    Ищет файл транскрипции в базе данных и возвращает его пользователю.
    """
    try:
        logger.info(
            f"Запрос на скачивание транскрипции: note_id={note_id}, client_id={client_id}, lead_id={lead_id}, contact_id={contact_id}"
        )

        if not os.path.exists(TRANSCRIPTION_DIR):
            logger.error(f"Директория транскрипций не найдена: {TRANSCRIPTION_DIR}")
            if response:
                response.status_code = status.HTTP_404_NOT_FOUND
            return {
                "success": False,
                "message": "Директория транскрипций не найдена",
                "data": None,
            }

        # Сначала ищем файл в базе данных
        transcript_filename = await find_transcription_file(
            note_id=note_id, lead_id=lead_id, contact_id=contact_id
        )

        # Если не нашли в базе, ищем в файловой системе
        if not transcript_filename:
            logger.info(
                f"Файл транскрипции не найден в базе данных, ищем в файловой системе"
            )

            # Формируем шаблоны имен файлов для поиска
            note_id_str = str(note_id)
            file_patterns = [f"note_{note_id_str}_*.txt"]

            # Если указан contact_id, получаем телефон контакта
            phone = None
            if contact_id:
                try:
                    # Создаем экземпляр клиента AmoCRM
                    client = AsyncAmoCRMClient(
                        client_id=client_id,
                        client_secret="",
                        subdomain="",
                        redirect_url="",
                        mongo_uri=MONGO_URI,
                        db_name=DB_NAME,
                    )

                    # Получаем контакт для извлечения номера телефона
                    contact = await client.get_contact(contact_id)

                    if contact and "custom_fields_values" in contact:
                        # Ищем поле телефона
                        for field in contact.get("custom_fields_values", []):
                            if (
                                field.get("field_code") == "PHONE"
                                and "values" in field
                                and field["values"]
                            ):
                                phone = field["values"][0].get("value")
                                if phone:
                                    logger.info(
                                        f"Извлечен номер телефона контакта: {phone}"
                                    )
                                    # Очищаем телефон от нецифровых символов для поиска файла
                                    phone_clean = re.sub(r"[^\d]", "", phone)
                                    file_patterns.append(f"{phone_clean}_*.txt")
                                    break
                except Exception as e:
                    logger.error(f"Ошибка при получении данных контакта: {e}")
                finally:
                    if "client" in locals():
                        await client.close()

            # Ищем файл по шаблонам
            for pattern in file_patterns:
                found = False
                for filename in os.listdir(TRANSCRIPTION_DIR):
                    if fnmatch.fnmatch(filename, pattern):
                        transcript_filename = filename
                        found = True
                        logger.info(
                            f"Найден файл транскрипции по шаблону {pattern}: {filename}"
                        )
                        break
                if found:
                    break

        # Если файл найден, возвращаем его
        if transcript_filename:
            file_path = os.path.join(TRANSCRIPTION_DIR, transcript_filename)

            # Проверяем размер файла
            file_size = os.path.getsize(file_path)
            logger.info(f"Размер файла транскрипции: {file_size} байт")

            if file_size == 0:
                logger.error(f"Файл транскрипции пуст: {file_path}")
                if response:
                    response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
                return {
                    "success": False,
                    "message": "Файл транскрипции пуст",
                    "data": None,
                }

            logger.info(f"Отправка файла транскрипции пользователю: {file_path}")

            # Сохраняем информацию в базу данных (если она не была там ранее)
            if not await find_transcription_file(note_id=note_id):
                await save_transcription_info(
                    filename=transcript_filename,
                    note_id=note_id,
                    lead_id=lead_id,
                    contact_id=contact_id,
                    client_id=client_id,
                )

            # Возвращаем файл пользователю с удобным именем
            download_filename = f"transcript_note_{note_id}.txt"
            if lead_id:
                download_filename = f"transcript_lead_{lead_id}_note_{note_id}.txt"
            elif contact_id:
                download_filename = (
                    f"transcript_contact_{contact_id}_note_{note_id}.txt"
                )

            return FileResponse(
                path=file_path, filename=download_filename, media_type="text/plain"
            )

        # Если файл не найден
        logger.warning(f"Файл транскрипции для заметки {note_id} не найден")
        if response:
            response.status_code = status.HTTP_404_NOT_FOUND
        return {
            "success": False,
            "message": f"Файл транскрипции для заметки {note_id} не найден",
            "data": None,
        }

    except Exception as e:
        error_msg = f"Ошибка при скачивании файла транскрипции: {str(e)}"
        logger.error(error_msg)

        # Полный стек-трейс для отладки
        logger.error(f"Стек-трейс:\n{traceback.format_exc()}")

        if response:
            response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return {"success": False, "message": error_msg, "data": None}


@router.get("/api/transcriptions/{filename}/download")
async def download_transcription(filename: str):
    """
    Скачивание файла транскрипции.
    """
    try:
        file_path = os.path.join(TRANSCRIPTION_DIR, filename)

        if not os.path.exists(file_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Файл {filename} не найден",
            )

        # Получаем имя файла для скачивания (убираем временные метки, если они есть)
        download_filename = filename

        # Проверяем шаблоны имен файлов и создаем более удобное имя для скачивания
        phone_match = re.match(r"^(\d+)_\d{8}_\d{6}\.txt$", filename)
        note_match = re.match(r"^note_(\d+)_\d{8}_\d{6}\.txt$", filename)

        if phone_match:
            download_filename = f"transcription_{phone_match.group(1)}.txt"
        elif note_match:
            download_filename = f"transcription_note_{note_match.group(1)}.txt"

        # Используем FileResponse с явно указанными заголовками для загрузки
        headers = {"Content-Disposition": f'attachment; filename="{download_filename}"'}

        return FileResponse(
            path=file_path,
            filename=download_filename,
            media_type="text/plain",
            headers=headers,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при скачивании транскрипции: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка при скачивании транскрипции: {str(e)}",
        )


@router.get("/api/transcriptions")
async def get_all_transcriptions():
    """
    Получение списка всех доступных транскрипций.
    """
    try:
        if not os.path.exists(TRANSCRIPTION_DIR):
            return {
                "success": True,
                "message": "Директория с транскрипциями не найдена",
                "data": {"transcriptions": []},
            }

        # Получаем список файлов транскрипций
        transcription_files = []
        for filename in os.listdir(TRANSCRIPTION_DIR):
            if filename.endswith(".txt"):
                file_path = os.path.join(TRANSCRIPTION_DIR, filename)

                # Получаем размер файла и дату изменения
                file_stats = os.stat(file_path)

                # Пытаемся извлечь номер телефона и ID заметки из имени файла
                phone_match = re.match(r"^(\d+)_\d{8}_\d{6}\.txt$", filename)
                note_match = re.match(r"^note_(\d+)_\d{8}_\d{6}\.txt$", filename)

                phone = phone_match.group(1) if phone_match else None
                note_id = note_match.group(1) if note_match else None

                # Получаем первые 100 символов текста для предпросмотра
                preview_text = ""
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        preview_text = f.read(500)
                        if len(preview_text) == 500:
                            preview_text += "..."
                except Exception as e:
                    logger.warning(
                        f"Не удалось прочитать предпросмотр файла {filename}: {e}"
                    )

                transcription_files.append(
                    {
                        "filename": filename,
                        "size": file_stats.st_size,
                        "created_at": datetime.fromtimestamp(
                            file_stats.st_ctime
                        ).strftime("%Y-%m-%d %H:%M:%S"),
                        "phone": phone,
                        "note_id": note_id,
                        "preview": preview_text,
                        "download_url": f"/api/transcriptions/{filename}/download",
                    }
                )

        # Сортируем по дате создания (сначала новые)
        transcription_files.sort(key=lambda x: x["created_at"], reverse=True)

        return {
            "success": True,
            "message": f"Найдено {len(transcription_files)} транскрипций",
            "data": {"transcriptions": transcription_files},
        }

    except Exception as e:
        logger.error(f"Ошибка при получении списка транскрипций: {str(e)}")
        return {
            "success": False,
            "message": f"Ошибка при получении списка транскрипций: {str(e)}",
            "data": None,
        }


@router.get("/api/transcriptions/search")
async def search_transcriptions(
    query: Optional[str] = None,
    phone: Optional[str] = None,
    note_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    """
    Поиск транскрипций по различным параметрам.
    """
    try:
        if not os.path.exists(TRANSCRIPTION_DIR):
            return {
                "success": True,
                "message": "Директория с транскрипциями не найдена",
                "data": {"transcriptions": []},
            }

        # Получаем список файлов транскрипций
        transcription_files = []
        for filename in os.listdir(TRANSCRIPTION_DIR):
            if filename.endswith(".txt"):
                file_path = os.path.join(TRANSCRIPTION_DIR, filename)

                # Получаем размер файла и дату изменения
                file_stats = os.stat(file_path)
                created_at = datetime.fromtimestamp(file_stats.st_ctime)

                # Фильтрация по дате
                if date_from:
                    date_from_obj = datetime.strptime(date_from, "%Y-%m-%d")
                    if created_at < date_from_obj:
                        continue

                if date_to:
                    date_to_obj = datetime.strptime(date_to, "%Y-%m-%d")
                    if created_at > date_to_obj:
                        continue

                # Фильтрация по имени файла
                if phone and phone not in filename:
                    continue

                if note_id and f"note_{note_id}" not in filename:
                    continue

                # Фильтрация по содержимому файла (если указан query)
                content_match = True
                if query:
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            content = f.read()
                            if query.lower() not in content.lower():
                                content_match = False
                    except Exception as e:
                        logger.warning(
                            f"Не удалось прочитать содержимое файла {filename}: {e}"
                        )
                        content_match = False

                if not content_match:
                    continue

                # Получаем первые 500 символов текста для предпросмотра
                preview_text = ""
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        preview_text = f.read(500)
                        if len(preview_text) == 500:
                            preview_text += "..."
                except Exception as e:
                    logger.warning(
                        f"Не удалось прочитать предпросмотр файла {filename}: {e}"
                    )

                transcription_files.append(
                    {
                        "filename": filename,
                        "size": file_stats.st_size,
                        "created_at": created_at.strftime("%Y-%m-%d %H:%M:%S"),
                        "preview": preview_text,
                        "download_url": f"/api/transcriptions/{filename}/download",
                    }
                )

        # Сортируем по дате создания (сначала новые)
        transcription_files.sort(key=lambda x: x["created_at"], reverse=True)

        return {
            "success": True,
            "message": f"Найдено {len(transcription_files)} транскрипций",
            "data": {"transcriptions": transcription_files},
        }

    except Exception as e:
        logger.error(f"Ошибка при поиске транскрипций: {str(e)}")
        return {
            "success": False,
            "message": f"Ошибка при поиске транскрипций: {str(e)}",
            "data": None,
        }
