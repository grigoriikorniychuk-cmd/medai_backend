import os
import sys
import asyncio
import argparse
from datetime import datetime, timedelta

# Добавляем корневую директорию проекта в sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aiohttp
from motor.motor_asyncio import AsyncIOMotorClient
from app.settings.paths import DB_NAME as DB_NAME_CFG
from mlab_amo_async.amocrm_client import AsyncAmoCRMClient

# --- Конфигурация ---
MONGO_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8001/api") + "/amocrm"
TARGET_CLIENT_ID = "4cdd8fc0-c5fa-4c3c-a2a8-19b062f37fc9"  # Клиника Киров
TARGET_DATE_STR = "2025-10-17"

# Список конверсионных пар (воронка, статус, название)
# Каждая пара: (pipeline_id, status_id, описание)
# ✅ Конфигурация для клиники Киров
CONVERSION_PAIRS = [
    (6869034, 57882910, "Первичные -> Записались"),    # 'Первичные пациенты' -> 'Записались на услугу'
    (6888086, 58011926, "Вторичные -> Записались"),    # 'Вторичные пациенты' -> 'Записались на услугу'
]

# Кастомное поле для ручного подтверждения конверсии
# ✅ Для клиники Киров:
CONFIRMATION_FIELD_ID = 1054011      # Поле 'Подтверждение'
CONFIRMATION_VALUE_ID = 1144793      # Значение 'Подтвержден'

# --- Клиенты ---
mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client[DB_NAME_CFG]
calls_collection = db["calls"]

async def get_amo_client(client_id: str):
    """Создает и возвращает клиент AmoCRM."""
    client_data = await db.clinics.find_one({"client_id": client_id})
    if not client_data:
        print(f"Клиент с ID {client_id} не найден в базе.")
        return None

    return AsyncAmoCRMClient(
        client_id=client_data['client_id'],
        client_secret=client_data['client_secret'],
        subdomain=client_data['amocrm_subdomain'],
        redirect_url=client_data['redirect_url'],
        mongo_uri=MONGO_URI
    )

async def get_specific_field_info(amo_client: AsyncAmoCRMClient, field_id: int):
    """Получает детальную информацию о конкретном кастомном поле."""
    try:
        print("\n" + "="*60)
        print(f"--- [ДИАГНОСТИКА] Кастомное поле ID: {field_id} ---")
        
        field_data, status_code = await amo_client.leads.request("get", f"leads/custom_fields/{field_id}")
        
        if status_code == 200:
            field_name = field_data.get('name', 'Неизвестно')
            field_type = field_data.get('field_type', 'Неизвестно')
            
            print(f"\nПоле: '{field_name}' (ID: {field_id}, Тип: {field_type})")
            
            enums = field_data.get('enums', [])
            if enums:
                print("\nВозможные значения:")
                for enum in enums:
                    enum_id = enum.get('id')
                    enum_value = enum.get('value')
                    enum_marker = " 🎯 ЦЕЛЕВОЕ" if "подтвержден" in enum_value.lower() and "не" not in enum_value.lower() else ""
                    print(f"  - '{enum_value}' (ID: {enum_id}){enum_marker}")
            else:
                print("  (Нет предустановленных значений)")
        else:
            print(f"Ошибка: Статус {status_code}")
        
        print("="*60 + "\n")
        
    except Exception as e:
        print(f"Ошибка при запросе поля {field_id}: {e}")

async def get_pipelines_info(amo_client: AsyncAmoCRMClient):
    """Получает и выводит информацию о всех воронках и статусах клиники."""
    try:
        pipelines_data, status_code = await amo_client.leads.request("get", "leads/pipelines")
        
        if status_code != 200:
            print(f"Ошибка при получении воронок: Статус {status_code}")
            return

        print("\n--- [ДИАГНОСТИКА] Доступные воронки и статусы ---")
        
        print("\n" + "="*60)
        for pipeline in pipelines_data['_embedded']['pipelines']:
            print(f"\nВоронка: '{pipeline['name']}' (ID: {pipeline['id']})")
            for status in pipeline.get('_embedded', {}).get('statuses', []):
                # Ищем статус "Записались"
                marker = " 🎯 ИСКАТЬ" if "записал" in status['name'].lower() else ""
                print(f"  - Статус: '{status['name']}' (ID: {status['id']}){marker}")
        print("="*60 + "\n")
        print("💡 Найдите воронки 'Первичные' и 'Вторичные пациенты' + статусы 'Записались',")
        print("   затем добавьте их ID в CONVERSION_PAIRS в начале скрипта.\n")

    except Exception as e:
        print(f"Ошибка при запросе воронок: {e}")

async def check_lead_for_conversion(amo_client: AsyncAmoCRMClient, lead_id: int, call_date: datetime) -> tuple[bool, str]:
    """Проверяет: перешла ли сделка в конверсионный статус В ДЕНЬ звонка или ПОСЛЕ,
    либо имеет кастомное поле 'Подтверждение' = 'Подтвержден'.
    
    Returns:
        tuple[bool, str]: (есть_конверсия, описание_типа_конверсии)
    """
    try:
        # Получаем информацию о сделке
        lead = await amo_client.get_lead(lead_id)
        
        if not lead:
            print(f"Сделка {lead_id} не найдена в AmoCRM.")
            return False, ""

        # Начало дня звонка (00:00:00) в timestamp
        call_date_start_ts = int(call_date.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        
        # ПЕРВАЯ ПРОВЕРКА: Кастомное поле "Подтверждение" через события
        # Получаем доступ к API событий
        api_paths = ["api/v4/events", "api/v2/events", "events"]
        api_path = None
        
        for path in api_paths:
            try:
                response, status = await amo_client.contacts.request("get", path, params={"page": 1, "limit": 1})
                if status == 200:
                    api_path = path
                    break
            except Exception:
                continue
        
        if api_path:
            try:
                # Ищем события изменения кастомного поля "Подтверждение"
                params = {
                    "filter[entity]": "lead",
                    "filter[entity_id]": lead_id,
                    "filter[type]": "custom_field_value_changed",
                    "limit": 250
                }
                
                events_data, status_code = await amo_client.contacts.request("get", api_path, params=params)
                
                if status_code == 200 and events_data:
                    events = events_data.get('_embedded', {}).get('events', [])
                    
                    for event in events:
                        if event.get('type') == 'custom_field_value_changed':
                            event_created_at = event.get('created_at', 0)
                            
                            # ВАЖНО: Событие должно быть В ДЕНЬ звонка или ПОСЛЕ
                            if event_created_at < call_date_start_ts:
                                continue
                            
                            value_after = event.get('value_after', [])
                            
                            # Проверяем изменение поля "Подтверждение"
                            for field_change in value_after:
                                if isinstance(field_change, dict):
                                    custom_field = field_change.get('custom_field_values', {})
                                    
                                    # Проверяем ID поля и значение
                                    if custom_field.get('field_id') == CONFIRMATION_FIELD_ID:
                                        enum_values = custom_field.get('enum_values', [])
                                        for enum_val in enum_values:
                                            if enum_val.get('enum_id') == CONFIRMATION_VALUE_ID:
                                                event_date_str = datetime.fromtimestamp(event_created_at).strftime('%Y-%m-%d %H:%M')
                                                print(f"✓ Найдена конверсия для сделки {lead_id}: Подтверждение -> Подтвержден")
                                                print(f"  Событие: {event_date_str}, Поле: {CONFIRMATION_FIELD_ID}, Значение: {CONFIRMATION_VALUE_ID}")
                                                return True, "Подтверждение -> Подтвержден"
            except Exception as e:
                # Если не удалось получить события, это не критично
                pass

        # ВТОРАЯ ПРОВЕРКА: Статусы в воронках
        current_pipeline_id = lead.get("pipeline_id")
        
        # Проверяем, что сделка в одной из целевых воронок
        valid_pipeline_ids = [p_id for p_id, _, _ in CONVERSION_PAIRS]
        if current_pipeline_id not in valid_pipeline_ids:
            return False, ""
        
        # Используем тот же api_path для проверки статусов
        if api_path:
            try:
                params = {
                    "filter[entity]": "lead",
                    "filter[entity_id]": lead_id,
                    "filter[type]": "lead_status_changed",
                    "limit": 250
                }
                
                events_data, status_code = await amo_client.contacts.request("get", api_path, params=params)
                
                if status_code == 200 and events_data:
                    events = events_data.get('_embedded', {}).get('events', [])
                    
                    # Проверяем все события смены статуса
                    for event in events:
                        if event.get('type') == 'lead_status_changed':
                            event_created_at = event.get('created_at', 0)
                            
                            # ВАЖНО: Событие должно быть В ДЕНЬ звонка или ПОСЛЕ
                            if event_created_at < call_date_start_ts:
                                continue
                            
                            value_after = event.get('value_after', [])
                            
                            # Проверяем, если сделка перешла в один из конверсионных статусов
                            for status_change in value_after:
                                if isinstance(status_change, dict):
                                    new_status_id = status_change.get('lead_status', {}).get('id')
                                    new_pipeline_id = status_change.get('lead_status', {}).get('pipeline_id')
                                    
                                    # Проверяем все конверсионные пары
                                    for pipeline_id, status_id, description in CONVERSION_PAIRS:
                                        if new_pipeline_id == pipeline_id and new_status_id == status_id:
                                            event_date_str = datetime.fromtimestamp(event_created_at).strftime('%Y-%m-%d %H:%M')
                                            print(f"✓ Найдена конверсия для сделки {lead_id}: {description}")
                                            print(f"  Событие: {event_date_str}, Воронка: {pipeline_id}, Статус: {status_id}")
                                            return True, description
            except Exception as e:
                # Если не удалось получить события, это не критично
                pass
        
        return False, ""

    except Exception as e:
        print(f"Ошибка при проверке сделки {lead_id}: {e}")
        return False, ""

async def main(args):
    """Основная функция скрипта."""
    print(f"Запуск скрипта для клиента: {args.client_id} за дату: {args.date}")
    if args.dry_run:
        print("--- РЕЖИМ СУХОГО ЗАПУСКА (только чтение) ---")
    
    # Создаем клиент AmoCRM
    amo_client = await get_amo_client(args.client_id)
    if not amo_client:
        return
    
    # Выводим конфигурацию
    print("\n" + "="*60)
    print("Настроенные типы конверсий:")
    print(f"\n1. Кастомное поле 'Подтверждение' (ID: {CONFIRMATION_FIELD_ID})")
    print(f"   Значение 'Подтвержден' (ID: {CONFIRMATION_VALUE_ID})")
    print(f"\n2. Статусы в воронках:")
    for pipeline_id, status_id, description in CONVERSION_PAIRS:
        print(f"   • {description}: Воронка {pipeline_id} -> Статус {status_id}")
    print("="*60 + "\n")

    # Формируем фильтр по дате
    target_date = datetime.strptime(args.date, "%Y-%m-%d")
    query = {
        "client_id": args.client_id,
        "created_date_for_filtering": target_date.strftime("%Y-%m-%d"),
        "lead_id": {"$exists": True, "$ne": None}
    }

    calls_to_process = await calls_collection.find(query).to_list(length=None)
    total_calls = len(calls_to_process)
    print(f"Найдено {total_calls} звонков для обработки.")

    real_conversions = 0
    updated_count = 0
    converted_lead_ids = []
    conversion_types = {}  # lead_id -> описание типа конверсии
    not_converted_lead_ids = []

    # Фильтруем звонки, чтобы обрабатывать только те, у которых есть lead_id
    calls_with_leads = [call for call in calls_to_process if call.get('lead_id')]
    
    # Проверяем каждую сделку
    results = []
    for call in calls_with_leads:
        is_conversion, conv_type = await check_lead_for_conversion(amo_client, call.get('lead_id'), target_date)
        results.append((is_conversion, conv_type))

    for i, (is_conversion, conv_type) in enumerate(results):
        call = calls_with_leads[i]
        lead_id = call.get('lead_id')

        if is_conversion:
            real_conversions += 1
            converted_lead_ids.append(lead_id)
            conversion_types[lead_id] = conv_type
        else:
            not_converted_lead_ids.append(lead_id)

        if call.get("metrics", {}).get("conversion") != is_conversion:
            update_payload = {'metrics.conversion': is_conversion}
            if not args.dry_run:
                await calls_collection.update_one(
                    {"_id": call['_id']},
                    {"$set": update_payload}
                )
                print(f"ОБНОВЛЕНА ЗАПИСЬ: {call['_id']} -> {update_payload}")
            else:
                print(f"[Dry Run] Требуется обновление для {call['_id']}: {update_payload}")
            updated_count += 1

    print("\n" + "="*60)
    print("--- ИТОГОВАЯ СТАТИСТИКА ---")
    print(f"Всего звонков за {args.date}: {total_calls}")
    print(f"Реальных конверсий (по статусу в AmoCRM): {real_conversions}")
    
    if converted_lead_ids:
        print(f"\n✓ СДЕЛКИ С КОНВЕРСИЕЙ ({len(set(converted_lead_ids))})")
        
        # Группируем по типам конверсии
        types_groups = {}  # тип -> список lead_id
        for lid in converted_lead_ids:
            ctype = conversion_types.get(lid, "Неизвестный тип")
            if ctype not in types_groups:
                types_groups[ctype] = []
            types_groups[ctype].append(lid)
        
        # Выводим по группам
        for ctype, lead_ids in sorted(types_groups.items()):
            print(f"\n  {ctype}: {len(lead_ids)} шт.")
            print(f"  ID: {sorted(list(set(lead_ids)))}")
    
    if not_converted_lead_ids:
        print(f"\n✗ СДЕЛКИ БЕЗ КОНВЕРСИИ ({len(set(not_converted_lead_ids))})")
        print(f"  ID: {sorted(list(set(not_converted_lead_ids)))}")
    
    print(f"\nОбновлено записей в MongoDB: {updated_count}")
    print("="*60)
    
    # Закрываем клиент AmoCRM
    await amo_client.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Скрипт для проверки и обновления статуса конверсии звонков.")
    parser.add_argument("--client_id", type=str, default=TARGET_CLIENT_ID, help="ID клиента для обработки.")
    parser.add_argument("--date", type=str, default=TARGET_DATE_STR, help="Дата для обработки в формате YYYY-MM-DD.")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Запустить в режиме 'только чтение' без записи в БД.")
    parser.add_argument("--force-write", dest='dry_run', action="store_false", help="Принудительно включить режим записи в БД.")

    cli_args = parser.parse_args()
    asyncio.run(main(cli_args))
