from fastapi import APIRouter, HTTPException, status, Request, BackgroundTasks, Response
from fastapi.responses import FileResponse
from typing import Dict, Any, Optional, List
from datetime import datetime
import logging
import os
import json
import time
import asyncio
import aiofiles
import aiohttp
import re
import ssl
import traceback
from motor.motor_asyncio import AsyncIOMotorClient

from ..models.amocrm import (
    LeadRequest,
    ContactRequest,
    LeadsByDateRequest,
    APIResponse,
    ContactResponse,
    CallResponse,
)
from mlab_amo_async.amocrm_client import AsyncAmoCRMClient
from ..utils.helpers import convert_date_to_timestamps, cleanup_temp_file
from ..settings.paths import AUDIO_DIR
from ..settings.amocrm import get_amocrm_config, get_amocrm_config_from_clinic, MONGODB_URI, MONGODB_NAME
from ..services.clinic_service import ClinicService


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/amocrm", tags=["amocrm"])

# Создаем директорию для аудио, если она не существует
os.makedirs(AUDIO_DIR, exist_ok=True)


# Вспомогательная функция для создания клиента AmoCRM
async def create_amocrm_client(client_id, client_secret="", subdomain="", redirect_url=""):
    """
    Создает и возвращает экземпляр клиента AsyncAmoCRMClient.
    
    Args:
        client_id: ID клиента (обязательный)
        client_secret: Секретный ключ (не обязательный при восстановлении из MongoDB)
        subdomain: Поддомен AmoCRM (не обязательный при восстановлении из MongoDB)
        redirect_url: URL для перенаправления (не обязательный при восстановлении из MongoDB)
        
    Returns:
        Экземпляр AsyncAmoCRMClient
    """
    return AsyncAmoCRMClient(
        client_id=client_id,
        client_secret=client_secret,
        subdomain=subdomain,
        redirect_url=redirect_url,
        mongo_uri=MONGODB_URI,
        db_name=MONGODB_NAME,
    )


@router.post("/leads/by-date", response_model=APIResponse)
async def get_leads_by_date(request: LeadsByDateRequest):
    """
    Получение списка сделок по дате создания.
    """
    client = None
    try:
        logger.info(
            f"Запрос сделок по дате: client_id={request.client_id}, date={request.date}"
        )

        # Находим клинику по client_id
        clinic_service = ClinicService()
        clinic = await clinic_service.find_clinic_by_client_id(request.client_id)

        if not clinic:
            return APIResponse(
                success=False,
                message=f"Клиника с client_id={request.client_id} не найдена",
                data=None,
            )

        # Преобразуем дату в timestamp начала и конца дня
        try:
            start_timestamp, end_timestamp = convert_date_to_timestamps(request.date)
            logger.info(f"Диапазон поиска: с {start_timestamp} по {end_timestamp}")
        except ValueError as e:
            return APIResponse(success=False, message=str(e), data=None)

        # Получаем конфигурацию AmoCRM из данных клиники
        amocrm_config = get_amocrm_config_from_clinic(clinic)

        # Создаем экземпляр клиента с данными из конфигурации
        client = AsyncAmoCRMClient(**amocrm_config)

        # Получаем все сделки с пагинацией
        all_leads = []
        page = 1

        while True:
            # Параметры фильтрации для AmoCRM
            filter_params = {
                "filter[created_at][from]": start_timestamp,
                "filter[created_at][to]": end_timestamp,
                "page": page,
                "limit": 250,  # Максимальное количество результатов на страницу
            }

            # Получаем сделки с фильтрацией по дате
            leads_response, status_code = await client.leads.request(
                "get", "leads", params=filter_params
            )

            # Проверяем успешность запроса
            if status_code != 200:
                logger.error(
                    f"Ошибка при запросе сделок (страница {page}): HTTP {status_code}"
                )
                break

            # Извлекаем сделки из ответа
            if "_embedded" in leads_response and "leads" in leads_response["_embedded"]:
                leads = leads_response["_embedded"]["leads"]
                all_leads.extend(leads)
                logger.info(f"Получено {len(leads)} сделок на странице {page}")

                # Проверяем, есть ли следующая страница
                if "_links" in leads_response and "next" in leads_response["_links"]:
                    page += 1
                else:
                    break
            else:
                break

        logger.info(f"Всего найдено {len(all_leads)} сделок за {request.date}")

        # Форматируем данные для ответа
        formatted_leads = []
        for lead in all_leads:
            # Форматируем данные о сделке для более читаемого вида
            created_at = lead.get("created_at")
            created_date = (
                datetime.fromtimestamp(created_at).strftime("%d.%m.%Y %H:%M:%S")
                if created_at
                else "Неизвестно"
            )

            # Базовая информация о сделке
            formatted_lead = {
                "id": lead.get("id"),
                "name": lead.get("name", "Без названия"),
                "created_at": created_at,
                "created_date": created_date,
                "pipeline_id": lead.get("pipeline_id"),
                "status_id": lead.get("status_id"),
                "responsible_user_id": lead.get("responsible_user_id"),
                "price": lead.get("price", 0),
            }

            formatted_leads.append(formatted_lead)

        return APIResponse(
            success=True,
            message=f"Найдено {len(all_leads)} сделок за {request.date}",
            data={
                "date": request.date,
                "total_leads": len(all_leads),
                "leads": formatted_leads,
            },
        )
    except Exception as e:
        error_msg = f"Ошибка при получении сделок по дате: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return APIResponse(success=False, message=error_msg, data=None)
    finally:
        if client:
            await client.close()


@router.post("/leads/get", response_model=APIResponse)
async def get_lead(request: LeadRequest):
    """
    Получение сделки из AmoCRM по ID.
    Автоматически использует токены из MongoDB.
    """
    client = None
    try:
        logger.info(
            f"Запрос сделки из AmoCRM: client_id={request.client_id}, lead_id={request.lead_id}"
        )

        # Создаем экземпляр клиента
        client = await create_amocrm_client(client_id=request.client_id)

        # Получаем сделку
        lead = await client.get_lead(request.lead_id)

        logger.info(f"Успешно получена сделка #{request.lead_id}")

        return APIResponse(
            success=True,
            message=f"Сделка #{request.lead_id} успешно получена",
            data=lead,
        )
    except Exception as e:
        error_msg = f"Ошибка при получении сделки: {str(e)}"
        logger.error(error_msg)

        # Проверяем на ошибку авторизации
        if "UnAuthorizedException" in str(e):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Ошибка авторизации в AmoCRM. Токены устарели или отсутствуют.",
            )

        # Проверяем ошибку в поддомене
        if "invalid label" in str(e) or "subdomain" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ошибка в поддомене. Убедитесь, что subdomain сохранен в MongoDB.",
            )

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)
    finally:
        if client:
            await client.close()


@router.post("/lead/contact", response_model=APIResponse)
async def get_contact_from_lead(request: LeadRequest):
    """
    Получение контакта, привязанного к сделке.
    """
    client = None
    try:
        logger.info(
            f"Запрос контакта из сделки: client_id={request.client_id}, lead_id={request.lead_id}"
        )

        # Создаем экземпляр клиента
        client = await create_amocrm_client(client_id=request.client_id)

        # Получаем контакт из сделки
        contact = await client.get_contact_from_lead(request.lead_id)

        if not contact:
            return APIResponse(
                success=False,
                message=f"К сделке #{request.lead_id} не привязан ни один контакт",
                data=None,
            )

        logger.info(f"Успешно получен контакт из сделки #{request.lead_id}")

        return APIResponse(
            success=True,
            message=f"Контакт из сделки #{request.lead_id} успешно получен",
            data=contact,
        )
    except Exception as e:
        error_msg = f"Ошибка при получении контакта из сделки: {str(e)}"
        logger.error(error_msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)
    finally:
        if client:
            await client.close()


@router.post("/contact/call-link", response_model=APIResponse)
async def get_call_link(request: ContactRequest):
    """
    Получение ссылки на запись звонка из заметок контакта.
    """
    client = None
    try:
        logger.info(
            f"Запрос ссылки на звонок: client_id={request.client_id}, contact_id={request.contact_id}"
        )

        # Создаем экземпляр клиента
        client = await create_amocrm_client(client_id=request.client_id)

        # Проверяем существование контакта
        try:
            contact = await client.get_contact(request.contact_id)
            logger.info(f"Контакт #{request.contact_id} существует")
        except Exception as e:
            logger.error(f"Ошибка при получении контакта #{request.contact_id}: {e}")
            return APIResponse(
                success=False,
                message=f"Контакт #{request.contact_id} не найден или ошибка доступа",
                data=None,
            )

        # Получаем ссылку на запись звонка
        logger.info(f"Запрашиваем заметки для контакта #{request.contact_id}")
        call_link = await client.get_call_link(request.contact_id)

        if not call_link:
            logger.warning(
                f"Ссылка на запись звонка для контакта #{request.contact_id} не найдена"
            )
            return APIResponse(
                success=False,
                message=f"Ссылка на запись звонка для контакта #{request.contact_id} не найдена",
                data={"contact_id": request.contact_id, "has_call_link": False},
            )

        logger.info(
            f"Успешно получена ссылка на звонок для контакта #{request.contact_id}"
        )

        # Формируем URL для скачивания через наш API
        download_url = f"/api/amocrm/contact/{request.contact_id}/download-call?client_id={request.client_id}"

        return APIResponse(
            success=True,
            message=f"Ссылка на запись звонка для контакта #{request.contact_id} получена",
            data={
                "contact_id": request.contact_id,
                "call_link": call_link,
                "download_url": download_url,
                "has_call_link": True,
            },
        )
    except Exception as e:
        error_msg = f"Ошибка при получении ссылки на запись звонка: {str(e)}"
        logger.error(error_msg)
        return APIResponse(
            success=False,
            message=error_msg,
            data={"contact_id": request.contact_id, "has_call_link": False},
        )
    finally:
        if client:
            await client.close()


@router.get("/contact/{contact_id}/download-call")
async def download_call(
    contact_id: int,
    client_id: str,
    background_tasks: BackgroundTasks,
    response: Response,
):
    """
    Скачивание записи звонка и возвращение файла пользователю. Реализация подходит для Ростеком телефонии.
    """
    client = None
    try:
        logger.info(
            f"Запрос на скачивание звонка: client_id={client_id}, contact_id={contact_id}"
        )

        # Создаем экземпляр клиента
        client = await create_amocrm_client(client_id=client_id)

        # Сначала проверяем существование ссылки на запись
        call_link = await client.get_call_link(contact_id)

        if not call_link:
            logger.warning(
                f"Ссылка на запись звонка для контакта #{contact_id} не найдена"
            )
            response.status_code = status.HTTP_404_NOT_FOUND
            return {
                "success": False,
                "message": f"Запись звонка для контакта #{contact_id} не найдена",
                "data": None,
            }

        # Скачиваем запись звонка
        logger.info(f"Скачиваем запись звонка по ссылке: {call_link}")
        file_path = await client.download_call_recording(contact_id, AUDIO_DIR)

        if not file_path or not os.path.exists(file_path):
            logger.error(
                f"Ошибка при скачивании записи звонка для контакта #{contact_id}"
            )
            response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
            return {
                "success": False,
                "message": f"Ошибка при скачивании записи звонка для контакта #{contact_id}",
                "data": {"call_link": call_link},  # Возвращаем ссылку для отладки
            }

        # Проверяем размер файла
        file_size = os.path.getsize(file_path)
        logger.info(f"Скачан файл размером {file_size} байт: {file_path}")

        if file_size == 0:
            logger.error(f"Скачан пустой файл (0 байт): {file_path}")
            response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
            return {
                "success": False,
                "message": f"Скачан пустой файл записи для контакта #{contact_id}",
                "data": {"call_link": call_link},
            }

        logger.info(f"Отправка файла пользователю: {file_path}")

        # Возвращаем файл пользователю
        return FileResponse(
            path=file_path, filename=f"{contact_id}_call.mp3", media_type="audio/mpeg"
        )
    except Exception as e:
        error_msg = f"Ошибка при скачивании записи звонка: {str(e)}"
        logger.error(error_msg)

        response.status_code = status.HTTP_400_BAD_REQUEST
        return {
            "success": False,
            "message": error_msg,
            "data": {"contact_id": contact_id},
        }
    finally:
        if client:
            await client.close()


@router.post("/lead/calls", response_model=APIResponse)
async def get_lead_calls(request: LeadRequest):
    """
    Получение списка всех звонков сделки с их ссылками.
    """
    client = None
    try:
        logger.info(
            f"Запрос списка звонков сделки: client_id={request.client_id}, lead_id={request.lead_id}"
        )

        # Создаем экземпляр клиента
        client = await create_amocrm_client(client_id=request.client_id)

        # Проверяем существование сделки
        try:
            lead = await client.get_lead(request.lead_id)
            logger.info(f"Сделка #{request.lead_id} существует")
        except Exception as e:
            logger.error(f"Ошибка при получении сделки #{request.lead_id}: {e}")
            return APIResponse(
                success=False,
                message=f"Сделка #{request.lead_id} не найдена или ошибка доступа",
                data=None,
            )

        # Получаем типы всех заметок сделки
        note_types = await client.get_all_notes_types(request.lead_id, "leads")
        logger.info(f"Типы заметок сделки #{request.lead_id}: {note_types}")

        # Получаем ссылки на записи звонков
        logger.info(f"Запрашиваем заметки для сделки #{request.lead_id}")
        call_links = await client.get_call_links_from_lead(request.lead_id)

        if not call_links:
            logger.warning(
                f"Ссылки на записи звонков для сделки #{request.lead_id} не найдены"
            )
            return APIResponse(
                success=False,
                message=f"Ссылки на записи звонков для сделки #{request.lead_id} не найдены",
                data={
                    "lead_id": request.lead_id,
                    "has_call_link": False,
                    "note_types": note_types,
                },
            )

        logger.info(
            f"Успешно получены {len(call_links)} ссылок на звонки для сделки #{request.lead_id}"
        )

        # Формируем ответ со ссылками на все звонки
        calls_data = []
        for link_info in call_links:
            # Формируем URL для скачивания для этой конкретной заметки
            download_url = f"/api/amocrm/lead/{request.lead_id}/note/{link_info['note_id']}/download?client_id={request.client_id}"

            # Добавляем метаданные о звонке
            note = link_info.get("note", {})
            params = note.get("params", {})
            created_at = note.get("created_at")
            created_date = (
                datetime.fromtimestamp(created_at).strftime("%Y-%m-%d %H:%M:%S")
                if created_at
                else "Неизвестно"
            )

            # Определяем тип звонка (входящий/исходящий)
            note_type = note.get("note_type")
            call_direction = "Неизвестно"
            if isinstance(note_type, int):
                call_direction = (
                    "Входящий"
                    if note_type == 10
                    else "Исходящий" if note_type == 11 else "Неизвестно"
                )
            elif isinstance(note_type, str):
                call_direction = (
                    "Входящий"
                    if "in" in note_type.lower()
                    else "Исходящий" if "out" in note_type.lower() else "Неизвестно"
                )

            # Рассчитываем длительность в формате минуты:секунды
            duration = params.get("duration", 0)
            duration_formatted = ""
            if duration:
                minutes = duration // 60
                seconds = duration % 60
                duration_formatted = f"{minutes}:{seconds:02d}"

            # Добавляем в список звонков
            calls_data.append(
                {
                    "note_id": link_info["note_id"],
                    "call_link": link_info["call_link"],
                    "download_url": download_url,
                    "created_at": created_at,
                    "created_date": created_date,
                    "direction": call_direction,
                    "duration": duration,
                    "duration_formatted": duration_formatted,
                    "phone": params.get("phone", "Неизвестно"),
                    "note_type": note_type,
                }
            )

        # Сортируем звонки по дате (сначала новые)
        calls_data.sort(key=lambda call: call.get("created_at", 0), reverse=True)

        return APIResponse(
            success=True,
            message=f"Ссылки на записи звонков для сделки #{request.lead_id} получены",
            data={
                "lead_id": request.lead_id,
                "has_call_link": True,
                "calls": calls_data,
                "total_calls": len(calls_data),
                "note_types": note_types,
            },
        )
    except Exception as e:
        error_msg = f"Ошибка при получении ссылок на записи звонков: {str(e)}"
        logger.error(error_msg)
        logger.error(f"Стек-трейс: {traceback.format_exc()}")
        return APIResponse(
            success=False,
            message=error_msg,
            data={"lead_id": request.lead_id, "has_call_link": False},
        )
    finally:
        if client:
            await client.close()


@router.get("/lead/{lead_id}/note/{note_id}/download")
async def download_lead_note_call(
    lead_id: int,
    note_id: int,
    client_id: str,
    background_tasks: BackgroundTasks = None,
    response: Response = None,
):
    """
    Скачивание записи звонка по ID заметки сделки.
    """
    client = None
    try:
        logger.info(
            f"Запрос на скачивание звонка из заметки сделки: client_id={client_id}, lead_id={lead_id}, note_id={note_id}"
        )

        # Создаем экземпляр клиента
        client = await create_amocrm_client(client_id=client_id)

        # Скачиваем запись звонка
        logger.info(f"Скачиваем запись звонка для заметки {note_id} сделки {lead_id}")
        file_path = await client.download_call_recording_from_lead(
            lead_id, AUDIO_DIR, note_id=note_id
        )

        if not file_path or not os.path.exists(file_path):
            logger.error(
                f"Ошибка при скачивании записи звонка для заметки {note_id} сделки {lead_id}"
            )
            if response:
                response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
            return {
                "success": False,
                "message": f"Ошибка при скачивании записи звонка из заметки {note_id} сделки {lead_id}",
                "data": None,
            }

        # Проверяем размер файла
        file_size = os.path.getsize(file_path)
        logger.info(f"Скачан файл размером {file_size} байт: {file_path}")

        if file_size == 0:
            logger.error(f"Скачан пустой файл (0 байт): {file_path}")
            if response:
                response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
            return {
                "success": False,
                "message": f"Скачан пустой файл записи для заметки {note_id} сделки {lead_id}",
                "data": None,
            }

        logger.info(f"Отправка файла пользователю: {file_path}")

        # Добавляем задачу на удаление файла после отправки
        if background_tasks:
            background_tasks.add_task(cleanup_temp_file, file_path)

        # Возвращаем файл пользователю
        return FileResponse(
            path=file_path,
            filename=f"lead_{lead_id}_note_{note_id}.mp3",
            media_type="audio/mpeg",
        )
    except Exception as e:
        error_msg = f"Ошибка при скачивании записи звонка: {str(e)}"
        logger.error(error_msg)
        logger.error(f"Стек-трейс: {traceback.format_exc()}")

        if response:
            response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return {"success": False, "message": error_msg, "data": None}
    finally:
        if client:
            await client.close()


@router.post("/lead/{lead_id}/download-call")
async def download_call_from_lead(
    lead_id: int,
    client_id: str,
    note_id: Optional[int] = None,
    background_tasks: BackgroundTasks = None,
    response: Response = None,
):
    """
    Скачивание записи звонка из сделки и возвращение файла.
    Если note_id не указан, скачивается последняя запись.
    """
    client = None
    try:
        logger.info(
            f"Запрос на скачивание звонка из сделки: client_id={client_id}, lead_id={lead_id}, note_id={note_id}"
        )

        # Создаем экземпляр клиента
        client = await create_amocrm_client(client_id=client_id)

        # Скачиваем запись звонка из сделки
        file_path = await client.download_call_recording_from_lead(
            lead_id, AUDIO_DIR, note_id=note_id
        )

        if not file_path or not os.path.exists(file_path):
            logger.error(f"Ошибка при скачивании записи звонка для сделки #{lead_id}")
            if response:
                response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
            return {
                "success": False,
                "message": f"Ошибка при скачивании записи звонка для сделки #{lead_id}",
                "data": None,
            }

        logger.info(f"Отправка файла пользователю: {file_path}")

        # Добавляем задачу на удаление файла после отправки
        if background_tasks:
            background_tasks.add_task(cleanup_temp_file, file_path)

        # Возвращаем файл пользователю
        return FileResponse(
            path=file_path,
            filename=os.path.basename(file_path),
            media_type="audio/mpeg",
        )
    except Exception as e:
        error_msg = f"Ошибка при скачивании записи звонка: {str(e)}"
        logger.error(error_msg, exc_info=True)

        if response:
            response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return {"success": False, "message": error_msg, "data": None}
    finally:
        if client:
            await client.close()


@router.post("/contact/calls", response_model=APIResponse)
async def get_contact_calls(request: ContactRequest):
    """
    Получение списка всех звонков контакта с их ссылками.
    Включает расширенную информацию о звонках и проверку ссылок. Подходит для Ростелеком телефонии.
    """
    client = None
    try:
        logger.info(
            f"Запрос списка звонков контакта: client_id={request.client_id}, contact_id={request.contact_id}"
        )

        # Создаем экземпляр клиента
        client = await create_amocrm_client(client_id=request.client_id)

        # Получаем контакт для получения связанных сделок
        contact = await client.get_contact(request.contact_id)

        # Проверяем, есть ли у контакта заметки напрямую
        call_links = await client.get_call_links(request.contact_id)

        # Если нет заметок напрямую, пробуем найти связанные сделки
        if not call_links:
            logger.info(
                f"У контакта {request.contact_id} нет заметок напрямую, ищем связанные сделки"
            )

            # Для поиска сделок нужно использовать API
            leads_response, _ = await client.contacts.request(
                "get", f"contacts/{request.contact_id}/leads"
            )

            if (
                leads_response
                and "_embedded" in leads_response
                and "leads" in leads_response["_embedded"]
            ):
                leads = leads_response["_embedded"]["leads"]
                logger.info(
                    f"Найдено {len(leads)} связанных сделок для контакта {request.contact_id}"
                )

                # Получаем все звонки из всех связанных сделок
                all_lead_call_links = []
                for lead in leads:
                    lead_id = lead["id"]
                    logger.info(f"Ищем звонки в сделке {lead_id}")

                    lead_call_links = await client.get_call_links_from_lead(lead_id)
                    if lead_call_links:
                        # Добавляем информацию о сделке в запись о звонках
                        for link in lead_call_links:
                            link["lead_id"] = lead_id
                            link["lead_name"] = lead.get("name", "Сделка без названия")

                        all_lead_call_links.extend(lead_call_links)

                # Если нашли звонки в сделках, используем их
                if all_lead_call_links:
                    logger.info(
                        f"Найдено {len(all_lead_call_links)} звонков в связанных сделках"
                    )
                    call_links = all_lead_call_links

        # Если не нашли звонки ни в контакте, ни в связанных сделках
        if not call_links:
            logger.warning(
                f"Не найдено звонков ни в контакте {request.contact_id}, ни в связанных сделках"
            )
            return APIResponse(
                success=False,
                message=f"Звонки для контакта #{request.contact_id} не найдены",
                data={
                    "contact_id": request.contact_id,
                    "message": "Попробуйте получить звонки напрямую из сделки",
                },
            )

        # Формируем список звонков
        calls = []
        for link_info in call_links:
            note = link_info.get("note", {})
            note_id = link_info.get("note_id")
            params = note.get("params", {})
            created_at = note.get("created_at")
            created_date = (
                datetime.fromtimestamp(created_at).strftime("%Y-%m-%d %H:%M:%S")
                if created_at
                else "Неизвестно"
            )
            lead_id = link_info.get("lead_id")

            # Определяем тип звонка (входящий/исходящий)
            note_type = note.get("note_type")
            call_direction = "Неизвестно"
            if isinstance(note_type, int):
                call_direction = (
                    "Входящий"
                    if note_type == 10
                    else "Исходящий" if note_type == 11 else "Неизвестно"
                )
            elif isinstance(note_type, str):
                call_direction = (
                    "Входящий"
                    if "in" in note_type.lower()
                    else "Исходящий" if "out" in note_type.lower() else "Неизвестно"
                )

            # Рассчитываем длительность в формате минуты:секунды
            duration = params.get("duration", 0)
            duration_formatted = ""
            if duration:
                minutes = duration // 60
                seconds = duration % 60
                duration_formatted = f"{minutes}:{seconds:02d}"

            # Формируем URL для скачивания
            download_url = None
            if lead_id:
                download_url = f"/api/amocrm/lead/{lead_id}/note/{note_id}/download?client_id={request.client_id}"
            else:
                download_url = f"/api/amocrm/contact/call/{note_id}/download?client_id={request.client_id}"

            # Добавляем в список звонков
            calls.append(
                {
                    "id": note_id,
                    "created_at": created_at,
                    "created_date": created_date,
                    "direction": call_direction,
                    "phone": params.get("phone", "Неизвестно"),
                    "duration": duration,
                    "duration_formatted": duration_formatted,
                    "result": params.get("call_result", "Неизвестно"),
                    "call_link": link_info["call_link"],
                    "has_recording": bool(link_info["call_link"]),
                    "download_url": download_url,
                    "note_id": note_id,
                    "lead_id": lead_id,
                    "lead_name": link_info.get("lead_name"),
                }
            )

        # Сортируем звонки по дате (сначала новые)
        calls.sort(key=lambda call: call.get("created_at", 0), reverse=True)

        logger.info(f"Найдено {len(calls)} звонков для контакта #{request.contact_id}")

        return APIResponse(
            success=True,
            message=f"Получен список звонков контакта #{request.contact_id}",
            data={
                "contact_id": request.contact_id,
                "total_calls": len(calls),
                "calls": calls,
            },
        )
    except Exception as e:
        error_msg = f"Ошибка при получении списка звонков: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return APIResponse(success=False, message=error_msg, data=None)
    finally:
        if client:
            await client.close()


@router.get("/contact/call/{note_id}/download")
async def download_call_by_note_id(
    note_id: int,
    client_id: str,
    contact_id: Optional[int] = None,
    response: Response = None,
):
    """
    Скачивание записи звонка по ID заметки.
    Использует упрощенный подход для получения ссылки на запись.
    """
    client = None
    try:
        logger.info(
            f"Запрос на скачивание звонка по ID заметки: client_id={client_id}, note_id={note_id}, contact_id={contact_id}"
        )

        # Создаем экземпляр клиента
        client = await create_amocrm_client(client_id=client_id)

        # Получаем заметку напрямую из API
        note = await client.get_note_by_id(note_id)

        if not note:
            # Если не нашли заметку напрямую, и указан контакт, попробуем найти в заметках контакта
            if contact_id:
                logger.info(f"Ищем заметку в контакте {contact_id}")
                notes = await client.get_contact_notes(contact_id)

                for n in notes:
                    if n.get("id") == note_id:
                        note = n
                        logger.info(
                            f"Найдена заметка {note_id} в контакте {contact_id}"
                        )
                        break

        # Если и в контакте не нашли, возможно заметка в сделке, ищем среди всех сделок контакта
        if not note and contact_id:
            logger.info(f"Ищем связанные сделки для контакта {contact_id}")

            # Получаем список связанных сделок
            leads_response, _ = await client.contacts.request(
                "get", f"contacts/{contact_id}/leads"
            )

            if (
                leads_response
                and "_embedded" in leads_response
                and "leads" in leads_response["_embedded"]
            ):
                leads = leads_response["_embedded"]["leads"]
                logger.info(
                    f"Найдено {len(leads)} связанных сделок для контакта {contact_id}"
                )

                # Ищем заметку в каждой сделке
                for lead in leads:
                    lead_id = lead.get("id")
                    logger.info(f"Проверяем заметки в сделке {lead_id}")

                    lead_notes = await client.get_lead_notes(lead_id)
                    for n in lead_notes:
                        if n.get("id") == note_id:
                            note = n
                            logger.info(f"Найдена заметка {note_id} в сделке {lead_id}")
                            break

                    if note:
                        break

        # Если и в сделках не нашли, пробуем поиск по всем сущностям
        if not note:
            logger.info(f"Пробуем найти заметку {note_id} среди всех сущностей")

            # Поиск осуществляем через API без указания сущности
            search_path = "notes"
            search_params = {"filter[id]": note_id}

            search_response, search_status = await client.contacts.request(
                "get", search_path, params=search_params
            )

            if (
                search_status == 200
                and "_embedded" in search_response
                and "notes" in search_response["_embedded"]
            ):
                notes = search_response["_embedded"]["notes"]
                if notes:
                    note = notes[0]
                    logger.info(f"Найдена заметка {note_id} через общий поиск")

        # Если заметку так и не нашли, пробуем прямой запрос к конкретной заметке
        if not note:
            logger.warning(
                f"Заметка {note_id} не найдена через API поиска, пробуем прямой запрос"
            )

            try:
                # Пробуем прямой запрос к API заметок
                note_response, status_code = await client.contacts.request(
                    "get", f"notes/{note_id}"
                )

                if status_code == 200:
                    note = note_response
                    logger.info(f"Найдена заметка {note_id} через прямой запрос")
            except Exception as e:
                logger.error(f"Ошибка при прямом запросе заметки {note_id}: {e}")

        if not note:
            logger.warning(f"Заметка {note_id} не найдена ни одним способом")
            if response:
                response.status_code = status.HTTP_404_NOT_FOUND
            return {
                "success": False,
                "message": f"Заметка {note_id} не найдена",
                "data": None,
            }

        logger.info(
            f"Структура найденной заметки {note_id}: {json.dumps(note, indent=2, ensure_ascii=False)}"
        )

        # Извлекаем данные для аутентификации и ссылку
        account_id = note.get("account_id")
        user_id = note.get("created_by")

        # Получаем ссылку на запись звонка
        params = note.get("params", {})
        call_link = None

        # 1. Прямая проверка наличия ссылки в параметрах
        if params and "link" in params and params["link"]:
            call_link = params["link"]
            logger.info(
                f"Найдена ссылка на запись звонка в parameters.link: {call_link}"
            )

        # 2. Для телефонии uiscom/calltouch ссылка может быть в других полях
        if not call_link and params:
            # Может быть в telephone.link
            telephone = params.get("telephone", {})
            if isinstance(telephone, dict) and telephone.get("link"):
                call_link = telephone.get("link")
                logger.info(f"Найдена ссылка в parameters.telephone.link: {call_link}")

        # 3. Для comagic/voximplant может быть другое поле
        if not call_link and params:
            # Проверяем все поля на наличие ссылок
            for key, value in params.items():
                if isinstance(value, str) and (
                    value.startswith("http")
                    and (
                        ".mp3" in value
                        or "media.comagic.ru" in value
                        or "voximplant" in value
                    )
                ):
                    call_link = value
                    logger.info(f"Найдена ссылка в parameters.{key}: {call_link}")
                    break

        # 4. Использование рекурсивного поиска ссылок
        if not call_link:
            call_link = client._find_link_in_dict(note, max_depth=5)
            if call_link:
                logger.info(f"Найдена ссылка в структуре заметки: {call_link}")

        if not call_link:
            logger.warning(f"В заметке {note_id} нет ссылки на запись звонка")
            if response:
                response.status_code = status.HTTP_404_NOT_FOUND
            return {
                "success": False,
                "message": f"В заметке {note_id} нет ссылки на запись звонка",
                "data": None,
            }

        # Добавляем параметры аутентификации к ссылке
        if (
            account_id
            and user_id
            and "userId" not in call_link
            and "accountId" not in call_link
        ):
            separator = "&" if "?" in call_link else "?"
            call_link += f"{separator}userId={user_id}&accountId={account_id}"
            logger.info(
                f"Добавлены параметры аутентификации: userId={user_id}, accountId={account_id}"
            )

        # Добавляем параметр download, если его нет
        if "download=" not in call_link:
            separator = "&" if "?" in call_link else "?"
            call_link += f"{separator}download=true"

        # Добавляем временную метку для предотвращения кеширования
        call_link += f"&_ts={int(time.time())}"

        logger.info(f"Итоговая ссылка на запись звонка: {call_link}")

        # Создаем директорию для файлов, если она не существует
        os.makedirs(AUDIO_DIR, exist_ok=True)

        # Формируем путь для сохранения файла
        file_path = os.path.join(AUDIO_DIR, f"call_{note_id}.mp3")

        # Создаем SSL-контекст с отключенной проверкой сертификата
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

        # Скачиваем файл с повторными попытками
        max_retries = 3
        for attempt in range(max_retries):
            try:
                logger.info(f"Попытка {attempt+1}/{max_retries} скачать файл")

                connector = aiohttp.TCPConnector(ssl=ssl_context)
                async with aiohttp.ClientSession(
                    connector=connector, headers=headers, cookie_jar=aiohttp.CookieJar()
                ) as session:
                    # Первый запрос для получения cookies
                    async with session.get(
                        "https://amocrm.mango-office.ru/"
                    ) as init_response:
                        logger.info(
                            f"Инициализация сессии: HTTP {init_response.status}"
                        )

                    # Скачиваем файл
                    async with session.get(
                        call_link, allow_redirects=True
                    ) as download_response:
                        status_code = download_response.status
                        logger.info(f"Статус ответа: {status_code}")

                        if status_code == 200:
                            data = await download_response.read()
                            data_size = len(data)

                            logger.info(f"Получено {data_size} байт данных")

                            # Проверяем, не получили ли мы HTML вместо аудио
                            content_type = download_response.headers.get(
                                "Content-Type", ""
                            )
                            if content_type.startswith("text/html") or (
                                data_size < 10000 and data.startswith(b"<!DOCTYPE")
                            ):
                                logger.error(
                                    f"Получен HTML вместо аудио. Это может означать ошибку авторизации"
                                )

                                # Сохраняем HTML для отладки
                                html_path = os.path.join(
                                    AUDIO_DIR, f"{note_id}_error_{attempt}.html"
                                )
                                async with aiofiles.open(html_path, "wb") as f:
                                    await f.write(data)

                                logger.error(
                                    f"HTML-ответ сохранен для отладки: {html_path}"
                                )

                                # Если это последняя попытка, возвращаем ошибку
                                if attempt == max_retries - 1:
                                    if response:
                                        response.status_code = (
                                            status.HTTP_500_INTERNAL_SERVER_ERROR
                                        )
                                    return {
                                        "success": False,
                                        "message": "Получен HTML вместо аудио. Возможно, требуется аутентификация или запись недоступна.",
                                        "data": {
                                            "note_id": note_id,
                                            "call_link": call_link,
                                            "content_type": content_type,
                                            "data_size": data_size,
                                            "error_html": html_path,
                                        },
                                    }

                                # Если это не последняя попытка, пробуем еще раз
                                await asyncio.sleep(
                                    1 * (attempt + 1)
                                )  # Экспоненциальная задержка
                                continue

                            # Сохраняем файл
                            async with aiofiles.open(file_path, "wb") as f:
                                await f.write(data)

                            logger.info(f"Файл записи звонка сохранен: {file_path}")

                            # Проверяем размер файла
                            if os.path.getsize(file_path) == 0:
                                logger.error(f"Скачан пустой файл (0 байт)")

                                # Если это последняя попытка, возвращаем ошибку
                                if attempt == max_retries - 1:
                                    if response:
                                        response.status_code = (
                                            status.HTTP_500_INTERNAL_SERVER_ERROR
                                        )
                                    return {
                                        "success": False,
                                        "message": "Скачан пустой файл (0 байт)",
                                        "data": {"call_link": call_link},
                                    }

                                # Если это не последняя попытка, пробуем еще раз
                                await asyncio.sleep(1 * (attempt + 1))
                                continue

                            # Возвращаем файл пользователю
                            return FileResponse(
                                path=file_path,
                                filename=f"call_{note_id}.mp3",
                                media_type="audio/mpeg",
                            )
                        elif status_code in (301, 302, 303, 307, 308):
                            # Обрабатываем редиректы вручную
                            redirect_url = download_response.headers.get("Location")
                            logger.info(f"Получен редирект на: {redirect_url}")

                            if redirect_url:
                                call_link = redirect_url
                                continue
                        else:
                            # В случае ошибки пытаемся прочитать тело ответа для отладки
                            try:
                                error_content = await download_response.text()
                                error_excerpt = (
                                    error_content[:500] + "..."
                                    if len(error_content) > 500
                                    else error_content
                                )
                            except:
                                error_excerpt = "Не удалось прочитать содержимое ответа"

                            error_msg = (
                                f"Ошибка при скачивании файла: HTTP {status_code}"
                            )
                            logger.error(f"{error_msg}\nОтвет: {error_excerpt}")

                            # Если это последняя попытка, возвращаем ошибку
                            if attempt == max_retries - 1:
                                if response:
                                    response.status_code = (
                                        status.HTTP_500_INTERNAL_SERVER_ERROR
                                    )
                                return {
                                    "success": False,
                                    "message": error_msg,
                                    "data": {
                                        "call_link": call_link,
                                        "status": status_code,
                                        "response_excerpt": error_excerpt,
                                    },
                                }

                            # Если это не последняя попытка, пробуем еще раз
                            await asyncio.sleep(1 * (attempt + 1))
            except Exception as e:
                logger.error(f"Ошибка при попытке {attempt+1}: {e}")
                logger.error(f"Стек-трейс: {traceback.format_exc()}")

                # Если это последняя попытка, возвращаем ошибку
                if attempt == max_retries - 1:
                    if response:
                        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
                    return {
                        "success": False,
                        "message": f"Ошибка при скачивании записи звонка: {str(e)}",
                        "data": None,
                    }

                # Если это не последняя попытка, пробуем еще раз
                await asyncio.sleep(1 * (attempt + 1))

        # Если дошли сюда, значит все попытки не удались
        logger.error(f"Все попытки скачивания не удались для заметки {note_id}")
        if response:
            response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return {
            "success": False,
            "message": f"Не удалось скачать запись звонка для заметки {note_id} после {max_retries} попыток",
            "data": None,
        }
    except Exception as e:
        error_msg = f"Ошибка при скачивании записи звонка: {str(e)}"
        logger.error(error_msg)

        # Полный стек-трейс для отладки
        logger.error(f"Стек-трейс:\n{traceback.format_exc()}")

        if response:
            response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return {"success": False, "message": error_msg, "data": None}
    finally:
        if client:
            await client.close()
