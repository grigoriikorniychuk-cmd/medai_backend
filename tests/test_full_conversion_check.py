"""
Комплексный тест проверки конверсий:
1. Получает все сделки, обновленные за дату из AmoCRM
2. Для каждой сделки получает звонки через контакт (get_call_links)
3. Фильтрует звонки по дате и удаляет дубли
4. Проверяет конверсию по 3 типам (Первичные, Вторичные, Подтверждение)
5. Сохраняет результаты в JSON
6. Выводит подробную статистику

Использование:
    python test_full_conversion_check.py <client_id> <date>

Пример:
    python test_full_conversion_check.py 4c640248-8904-412e-ae85-14dda10edd1b 2025-11-08
"""
import asyncio
import json
import sys
import os
import argparse
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient

# Добавляем путь к модулям
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mlab_amo_async.amocrm_client import AsyncAmoCRMClient

# === КОНФИГУРАЦИЯ ===
MONGO_URI = "mongodb://92.113.151.220:27018/"
DB_NAME = "medai"

# Глобальные переменные для конфигурации (будут заполнены автоматически)
PIPELINE_PRIMARY_ID = None
STATUS_PRIMARY_BOOKED_ID = None
PIPELINE_SECONDARY_ID = None
STATUS_SECONDARY_BOOKED_ID = None
CONFIRMATION_FIELD_ID = None
CONFIRMATION_VALUE_ID = None

DEBUG_LEAD_ID = None  # Отключаем диагностику конкретного лида


async def auto_detect_conversion_config(client):
    """Автоматически определяет конфигурацию конверсий через AmoCRM API"""
    global PIPELINE_PRIMARY_ID, STATUS_PRIMARY_BOOKED_ID
    global PIPELINE_SECONDARY_ID, STATUS_SECONDARY_BOOKED_ID
    global CONFIRMATION_FIELD_ID, CONFIRMATION_VALUE_ID

    print(f"\n🤖 Автодетекция конфигурации конверсий...")

    try:
        # Детектим воронки
        pipelines_resp, status = await client.leads.request("get", "leads/pipelines")
        if status == 200:
            pipelines = pipelines_resp.get("_embedded", {}).get("pipelines", [])

            for pipeline in pipelines:
                name = pipeline.get("name", "").lower()

                if "первичн" in name and not PIPELINE_PRIMARY_ID:
                    PIPELINE_PRIMARY_ID = pipeline["id"]
                    print(f"   ✅ Найдена PRIMARY воронка: '{pipeline.get('name')}' (id={PIPELINE_PRIMARY_ID})")

                    statuses = pipeline.get("_embedded", {}).get("statuses", [])
                    for st in statuses:
                        st_name = st.get("name", "").lower()
                        if "записал" in st_name or "записан" in st_name:
                            STATUS_PRIMARY_BOOKED_ID = st["id"]
                            print(f"      → Статус: '{st.get('name')}' (id={STATUS_PRIMARY_BOOKED_ID})")
                            break

                elif "вторичн" in name and not PIPELINE_SECONDARY_ID:
                    PIPELINE_SECONDARY_ID = pipeline["id"]
                    print(f"   ✅ Найдена SECONDARY воронка: '{pipeline.get('name')}' (id={PIPELINE_SECONDARY_ID})")

                    statuses = pipeline.get("_embedded", {}).get("statuses", [])
                    for st in statuses:
                        st_name = st.get("name", "").lower()
                        if "записал" in st_name or "записан" in st_name:
                            STATUS_SECONDARY_BOOKED_ID = st["id"]
                            print(f"      → Статус: '{st.get('name')}' (id={STATUS_SECONDARY_BOOKED_ID})")
                            break

        # Детектим кастомное поле "Подтверждение" (используем существующую функцию)
        field_id, enum_id = await get_confirmation_field_dynamic(client)
        if field_id and enum_id:
            CONFIRMATION_FIELD_ID = field_id
            CONFIRMATION_VALUE_ID = enum_id
            print(f"   ✅ Найдено поле Подтверждение: field_id={field_id}, enum_id={enum_id}")
        else:
            print(f"   ⚠️  Поле Подтверждение НЕ НАЙДЕНО (это нормально для некоторых клиник)")

        return True

    except Exception as e:
        print(f"❌ Ошибка при автодетекции: {e}")
        return False


async def load_conversion_config_from_db(db, client_id, amo_client):
    """Загружает конфигурацию конверсий из MongoDB для клиники, если нет - детектит"""
    global PIPELINE_PRIMARY_ID, STATUS_PRIMARY_BOOKED_ID
    global PIPELINE_SECONDARY_ID, STATUS_SECONDARY_BOOKED_ID
    global CONFIRMATION_FIELD_ID, CONFIRMATION_VALUE_ID

    print(f"\n{'='*60}")
    print(f"🔧 Загрузка конфигурации конверсий из MongoDB")
    print(f"{'='*60}")

    clinic = await db.clinics.find_one({"client_id": client_id})
    if not clinic:
        print(f"❌ Клиника с client_id={client_id} не найдена в БД")
        return False

    conv_config = clinic.get("conversion_config", {})

    if not conv_config:
        print(f"⚠️  У клиники нет сохраненной конфигурации конверсий")
        print(f"   Запускаем автодетекцию...")
        # Запускаем автодетекцию
        success = await auto_detect_conversion_config(amo_client)
        if not success:
            print(f"❌ Автодетекция не удалась")
            return False
        return True

    # Извлекаем конфигурацию
    primary = conv_config.get("primary", {})
    secondary = conv_config.get("secondary", {})
    confirmation = conv_config.get("confirmation_field", {})

    PIPELINE_PRIMARY_ID = primary.get("pipeline_id")
    STATUS_PRIMARY_BOOKED_ID = primary.get("status_id")
    PIPELINE_SECONDARY_ID = secondary.get("pipeline_id")
    STATUS_SECONDARY_BOOKED_ID = secondary.get("status_id")
    CONFIRMATION_FIELD_ID = confirmation.get("field_id")
    CONFIRMATION_VALUE_ID = confirmation.get("enum_id")

    print(f"✅ Конфигурация загружена из БД:")
    print(f"   Primary: pipeline={PIPELINE_PRIMARY_ID}, status={STATUS_PRIMARY_BOOKED_ID}")
    print(f"   Secondary: pipeline={PIPELINE_SECONDARY_ID}, status={STATUS_SECONDARY_BOOKED_ID}")
    print(f"   Confirmation: field={CONFIRMATION_FIELD_ID}, enum={CONFIRMATION_VALUE_ID}")

    if conv_config.get("manually_overridden"):
        print(f"   ⚙️  Конфигурация переопределена вручную")
    elif conv_config.get("detected_at"):
        detected_at = conv_config.get("detected_at")
        print(f"   🤖 Автодетекция: {detected_at}")

    return True


async def get_all_call_events(client, target_date_str):
    """Получает все события звонков за дату через API events."""
    print(f"\n{'='*60}")
    print(f"📡 Получение событий звонков за {target_date_str}")
    print(f"{'='*60}")
    
    target_date = datetime.strptime(target_date_str, "%Y-%m-%d")
    start_timestamp = int(datetime.combine(target_date.date(), datetime.min.time()).timestamp())
    end_timestamp = int(datetime.combine(target_date.date(), datetime.max.time()).timestamp())
    
    print(f"Период: {target_date.strftime('%d.%m.%Y')} 00:00 - 23:59")
    
    # Определяем работающий эндпоинт
    api_paths = ["api/v4/events", "api/v2/events", "events"]
    api_path = None
    
    for path in api_paths:
        try:
            response, status = await client.contacts.request("get", path, params={"page": 1, "limit": 1})
            if status == 200:
                api_path = path
                print(f"✅ Используем эндпоинт: {path}")
                break
        except Exception:
            continue
    
    if not api_path:
        print("❌ Не удалось найти рабочий эндпоинт")
        return []
    
    all_events = []
    page = 1
    max_pages = 100
    
    while page <= max_pages:
        params = {
            "page": page,
            "limit": 250,
            "filter[type][]": ["incoming_call", "outgoing_call"],
            "filter[created_at][from]": start_timestamp,
            "filter[created_at][to]": end_timestamp
        }
        
        try:
            response, status = await client.contacts.request("get", api_path, params=params)
            
            if status != 200:
                break
            
            events = response.get("_embedded", {}).get("events", [])
            
            if not events:
                break
            
            all_events.extend(events)
            print(f"📄 Страница {page}: получено {len(events)} событий (всего: {len(all_events)})")
            
            links = response.get("_links", {})
            if "next" not in links:
                break
            
            page += 1
            await asyncio.sleep(0.2)
            
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            break
    
    print(f"\n✅ ВСЕГО получено событий: {len(all_events)}")
    return all_events


async def get_confirmation_field_dynamic(client):
    """Возвращает (field_id, enum_id) подтверждения. Ищем enum со словом «подтвержд» (без «не») во всех полях, с пагинацией."""
    try:
        page = 1
        while True:
            data, status = await client.leads.request("get", "leads/custom_fields", params={"page": page, "limit": 250})
            if status != 200 or not isinstance(data, dict):
                break
            for fld in data.get("_embedded", {}).get("custom_fields", []):
                field_id = fld.get("id")
                for enum in fld.get("enums", []):
                    val = (enum.get("value") or "").lower()
                    if "подтвержд" in val and "не" not in val:
                        return field_id, enum.get("id")
            if "next" in (data.get("_links") or {}):
                page += 1
            else:
                break
        return None, None
    except Exception:
        return None, None
    try:
        data, status = await client.leads.request("get", f"leads/custom_fields/{CONFIRMATION_FIELD_ID}")
        pos = None
        neg = None
        if status == 200 and isinstance(data, dict):
            enums = data.get("enums", []) or data.get("_embedded", {}).get("enums", [])
            for enum in enums:
                val = (enum.get("value") or "").lower()
                if "подтвержден" in val and "не" not in val:
                    pos = enum.get("id")
                if "подтвержден" in val and "не" in val:
                    neg = enum.get("id")
        return pos, neg
    except Exception:
        return None, None


async def check_conversion_for_lead(client, lead_id, call_date, confirmation_value_id, *, diagnostic=False):
    """Определяет конверсию сделки по событиям /events в день звонка."""
    try:
        date_start = int(datetime.combine(call_date.date(), datetime.min.time()).timestamp())
        date_end = int(datetime.combine(call_date.date(), datetime.max.time()).timestamp())

        # 1. Находим рабочий эндпоинт /events один раз и кэшируем
        if not hasattr(check_conversion_for_lead, "_events_api"):
            paths = ["api/v4/events", "api/v2/events", "events"]
            chosen = None
            for p in paths:
                try:
                    _, st = await client.contacts.request("get", p, params={"page": 1, "limit": 1})
                    if st == 200:
                        chosen = p
                        break
                except Exception:
                    continue
            check_conversion_for_lead._events_api = chosen or paths[-1]
        api_path = check_conversion_for_lead._events_api

        async def fetch_events(event_type=None):
            """Загружает все страницы событий за день звонка. Если event_type указан, добавляет фильтр по типу."""
            result = []
            page = 1
            while True:
                params = {
                    "filter[entity]": "lead",
                    "filter[entity_id]": lead_id,
                    "filter[created_at][from]": date_start,
                    "filter[created_at][to]": date_end,
                    "page": page,
                    "limit": 250,
                }
                if event_type:
                    params["filter[type]"] = event_type
                try:
                    resp, st = await client.contacts.request("get", api_path, params=params)
                except Exception:
                    break
                if st != 200:
                    break
                batch = resp.get("_embedded", {}).get("events", [])
                if not batch:
                    break
                result.extend(batch)
                if "next" in resp.get("_links", {}):
                    page += 1
                else:
                    break
            return result

        status_events = await fetch_events("lead_status_changed")
        all_events_for_day = await fetch_events()
        cf_events = [
            ev for ev in all_events_for_day
            if isinstance(ev.get("type"), str)
            and ev["type"].startswith("custom_field_")
            and ev["type"].endswith("_value_changed")
        ]

        if diagnostic:
            print(f"\n🔍 Диагностика Lead {lead_id}: statuses={len(status_events)}, cf={len(cf_events)}")
            if cf_events:
                print("      👉 Пример события custom_field_value_changed:")
                import pprint, json
                pprint.pprint(cf_events[0])

        # 2. Проверяем кастомное поле Подтверждение (только если поле задано)
        # ВАЖНО: Пропускаем всю проверку если CONFIRMATION_FIELD_ID = None
        if CONFIRMATION_FIELD_ID is not None:
            for ev in cf_events:
                value_after = ev.get("value_after")
                if isinstance(value_after, dict):
                    items = [value_after]
                else:
                    items = value_after or []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    # Вариант 1: структура с обёрткой custom_field_values
                    if "custom_field_values" in item:
                        cfv = item.get("custom_field_values", {})
                        if cfv.get("field_id") == CONFIRMATION_FIELD_ID:
                            for enum_val in cfv.get("enum_values", []):
                                if enum_val.get("enum_id") == confirmation_value_id:
                                    return True, "Подтверждение -> Подтвержден"
                    # Вариант 1.1: вложенный объект custom_field_value
                    if "custom_field_value" in item and isinstance(item.get("custom_field_value"), dict):
                        cfv = item.get("custom_field_value", {})
                        if cfv.get("field_id") == CONFIRMATION_FIELD_ID:
                            enum_ok = cfv.get("enum_id") == confirmation_value_id
                            text = (cfv.get("text") or "").lower()
                            text_ok = ("подтвержд" in text) and ("не" not in text)
                            if enum_ok or text_ok:
                                return True, "Подтверждение -> Подтвержден"
                    # Вариант 2: плоская структура field_id / enum_id
                    if item.get("field_id") == CONFIRMATION_FIELD_ID:
                        enum_id = item.get("enum_id") or item.get("value")
                        if enum_id == confirmation_value_id:
                            return True, "Подтверждение -> Подтвержден"

        # 2.1. Резерв: по состоянию сделки, если нет событий (только если поле задано)
        # ВАЖНО: Пропускаем эту проверку если CONFIRMATION_FIELD_ID = None
        if CONFIRMATION_FIELD_ID is not None:
            try:
                lead_snapshot = await client.get_lead(lead_id)
            except Exception:
                lead_snapshot = None
            if lead_snapshot:
                lu = lead_snapshot.get("updated_at") or 0
                if date_start <= lu <= date_end:
                    for cf in (lead_snapshot.get("custom_fields_values") or []):
                        fid = cf.get("field_id")
                        if fid == CONFIRMATION_FIELD_ID:
                            for v in cf.get("values", []):
                                enum_id = v.get("enum_id")
                                text = (v.get("value") or "").lower()
                                if enum_id == confirmation_value_id or ("подтвержд" in text and "не" not in text):
                                    return True, "Подтверждение -> Подтвержден"

        # 3. Проверяем смену статуса на "Записались" в нужных воронках
        for ev in status_events:
            for item in ev.get("value_after", []):
                ls = item.get("lead_status", {})
                pid = ls.get("pipeline_id")
                sid = ls.get("id")
                if pid == PIPELINE_PRIMARY_ID and sid == STATUS_PRIMARY_BOOKED_ID:
                    return True, "Первичные -> Записались"
                if pid == PIPELINE_SECONDARY_ID and sid == STATUS_SECONDARY_BOOKED_ID:
                    return True, "Вторичные -> Записались"

        return False, ""
    except Exception as e:
        if diagnostic:
            print(f"   ❌ Ошибка: {e}")
        return False, ""
        
        date_start = int(datetime.combine(call_date.date(), datetime.min.time()).timestamp())
        date_end = int(datetime.combine(call_date.date(), datetime.max.time()).timestamp())
        
        # Пагинация для notes
        all_notes = []
        page = 1
        while True:
            notes_response, status = await client.leads.request(
                "get", f"leads/{lead_id}/notes", params={"page": page, "limit": 250}
            )
            if status != 200:
                break
            notes_batch = notes_response.get("_embedded", {}).get("notes", [])
            if not notes_batch:
                break
            all_notes.extend(notes_batch)
            links = notes_response.get("_links", {})
            if "next" not in links:
                break
            page += 1
        
        if diagnostic:
            print(f"\n🔍 Диагностика Lead ID: {lead_id}")
            print(f"   Всего событий (notes): {len(all_notes)}")
        
        # Фильтруем события строго по дню звонка
        filtered_notes = [n for n in all_notes if date_start <= n.get("created_at", 0) <= date_end]
        
        if diagnostic:
            print(f"   События за {call_date.strftime('%Y-%m-%d')}: {len(filtered_notes)}")
            if filtered_notes:
                types = {}
                for n in filtered_notes:
                    nt = n.get("note_type")
                    types[nt] = types.get(nt, 0) + 1
                print(f"   Типы событий: {types}")
                # Покажем первые 3 события С ПОЛНОЙ СТРУКТУРОЙ
                for i, note in enumerate(filtered_notes[:3]):
                    ts = datetime.fromtimestamp(note.get("created_at", 0)).strftime("%Y-%m-%d %H:%M")
                    nt = note.get('note_type')
                    print(f"   [{i+1}] Тип: {nt} @ {ts}")
                    if nt in ('lead_status_changed', 'lead_custom_field_value_changed', 'common'):
                        params = note.get('params', {})
                        print(f"       params: {params}")
            else:
                print(f"   ⚠️ Нет событий за {call_date.strftime('%Y-%m-%d')}")
                # Покажем ближайшие события ДО и ПОСЛЕ
                before = [n for n in all_notes if n.get('created_at', 0) < date_start]
                after = [n for n in all_notes if n.get('created_at', 0) > date_end]
                if before:
                    last_before = max(before, key=lambda x: x.get('created_at', 0))
                    ts = datetime.fromtimestamp(last_before.get('created_at', 0)).strftime('%Y-%m-%d %H:%M')
                    print(f"   📌 Последнее событие ДО: {last_before.get('note_type')} @ {ts}")
                if after:
                    first_after = min(after, key=lambda x: x.get('created_at', 0))
                    ts = datetime.fromtimestamp(first_after.get('created_at', 0)).strftime('%Y-%m-%d %H:%M')
                    print(f"   📌 Первое событие ПОСЛЕ: {first_after.get('note_type')} @ {ts}")
        
        for note in filtered_notes:
            nt = note.get("note_type")
            p = note.get("params", {})
            
            if nt == "lead_custom_field_value_changed":
                if p.get("field_id") == CONFIRMATION_FIELD_ID:
                    new_val = p.get("new_value", {})
                    if new_val.get("enum_id") == confirmation_value_id:
                        return True, "Подтверждение -> Подтвержден"
            
            if nt == "lead_status_changed":
                new_pipeline_id = p.get("new_pipeline_id")
                new_status_id = p.get("new_status_id")
                if new_pipeline_id == PIPELINE_PRIMARY_ID and new_status_id == STATUS_PRIMARY_BOOKED_ID:
                    return True, "Первичные -> Записались"
                if new_pipeline_id == PIPELINE_SECONDARY_ID and new_status_id == STATUS_SECONDARY_BOOKED_ID:
                    return True, "Вторичные -> Записались"
        
        return False, ""
    except Exception as e:
        if diagnostic:
            print(f"   ❌ Ошибка: {e}")
        return False, ""


async def enrich_event_with_lead_id(client, event):
    """Обогащает событие lead_id через контакт, выбирая сделку, обновлённую в день звонка."""
    entity_type = event.get("entity_type")
    entity_id = event.get("entity_id")
    
    if entity_type == "lead":
        return entity_id
    
    if entity_type == "contact" and entity_id:
        try:
            contact_info, status = await client.contacts.request(
                "get", f"contacts/{entity_id}", params={"with": "leads"}
            )
            
            leads = []
            if status == 200 and contact_info:
                leads = contact_info.get("_embedded", {}).get("leads", [])

            if not leads:
                try:
                    links_resp, links_status = await client.contacts.request(
                        "get", f"contacts/{entity_id}/links", params={"limit": 250}
                    )
                    if links_status == 200 and isinstance(links_resp, dict):
                        links = links_resp.get("_embedded", {}).get("links", [])
                        link_lead_ids = []
                        for link in links:
                            to_entity = link.get("to_entity") or link.get("to_entity_type")
                            to_id = link.get("to_entity_id") or link.get("to_entity")
                            if to_entity in ("lead", "leads"):
                                if isinstance(to_id, int):
                                    link_lead_ids.append(to_id)
                                elif isinstance(to_id, str) and to_id.isdigit():
                                    link_lead_ids.append(int(to_id))
                        if link_lead_ids:
                            return link_lead_ids[0]
                except Exception:
                    pass

            if not leads:
                try:
                    leads_resp, leads_status = await client.leads.request(
                        "get",
                        "leads",
                        params={
                            "filter[contacts][id][]": entity_id,
                            "order[updated_at]": "desc",
                            "limit": 250,
                        },
                    )
                    if leads_status == 200 and isinstance(leads_resp, dict):
                        leads = leads_resp.get("_embedded", {}).get("leads", [])
                except Exception:
                    pass

            if not leads:
                return None
            
            # Предпочитаем сделку, обновлённую в день звонка
            ev_ts = event.get("created_at") or 0
            from datetime import datetime
            ev_day = datetime.utcfromtimestamp(ev_ts).date()
            day_start = int(datetime.combine(ev_day, datetime.min.time()).timestamp())
            day_end = int(datetime.combine(ev_day, datetime.max.time()).timestamp())

            def lead_sort_key(l):
                return (l.get("updated_at") or 0, l.get("created_at") or 0)

            same_day = [l for l in leads if day_start <= (l.get("updated_at") or 0) <= day_end]
            if same_day:
                same_day.sort(key=lead_sort_key, reverse=True)
                return same_day[0].get("id")

            # Иначе — ближайшая по updated_at к времени звонка
            def abs_diff(l):
                return abs((l.get("updated_at") or 0) - ev_ts)
            leads_sorted = sorted(leads, key=abs_diff)
            return leads_sorted[0].get("id") if leads_sorted else None
        except Exception:
            pass
    
    return None


async def get_all_calls_from_events(client, target_date_str):
    """Получает все звонки через события и обогащает lead_id."""
    print(f"\n{'='*60}")
    print(f"📞 Сбор и обогащение звонков")
    print(f"{'='*60}")
    
    # Получаем события
    events = await get_all_call_events(client, target_date_str)
    
    if not events:
        return []
    
    print(f"\n🔍 Обогащение {len(events)} событий...")
    
    enriched_calls = []
    processed = 0
    
    for event in events:
        lead_id = await enrich_event_with_lead_id(client, event)
        
        enriched_calls.append({
            'event_id': event.get('id'),
            'entity_type': event.get('entity_type'),
            'entity_id': event.get('entity_id'),
            'lead_id': lead_id,
            'created_at': event.get('created_at'),
            'type': event.get('type')
        })
        
        processed += 1
        if processed % 20 == 0:
            print(f"Обработано: {processed}/{len(events)}")
    
    with_lead = sum(1 for c in enriched_calls if c['lead_id'])
    print(f"\n✅ Обогащено: {len(enriched_calls)} событий")
    print(f"📊 С lead_id: {with_lead}/{len(enriched_calls)} ({with_lead/len(enriched_calls)*100:.1f}%)")
    
    return enriched_calls


async def get_leads_with_confirmation_events(client, call_date, field_id, enum_id):
    date_start = int(datetime.combine(call_date.date(), datetime.min.time()).timestamp())
    date_end = int(datetime.combine(call_date.date(), datetime.max.time()).timestamp())
    paths = ["api/v4/events", "api/v2/events", "events"]
    chosen = None
    for p in paths:
        try:
            _, st = await client.contacts.request("get", p, params={"page": 1, "limit": 1})
            if st == 200:
                chosen = p
                break
        except Exception:
            continue
    api_path = chosen or paths[-1]
    page = 1
    result = set()
    while True:
        params = {
            "filter[entity]": "lead",
            "filter[created_at][from]": date_start,
            "filter[created_at][to]": date_end,
            "page": page,
            "limit": 250,
        }
        try:
            resp, st = await client.contacts.request("get", api_path, params=params)
        except Exception:
            break
        if st != 200:
            break
        batch = resp.get("_embedded", {}).get("events", [])
        if not batch:
            break
        for ev in batch:
            t = ev.get("type") or ""
            if isinstance(t, str) and t.startswith("custom_field_") and t.endswith("_value_changed"):
                va = ev.get("value_after")
                items = [va] if isinstance(va, dict) else (va or [])
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    if "custom_field_value" in item and isinstance(item.get("custom_field_value"), dict):
                        cfv = item.get("custom_field_value")
                        if cfv.get("field_id") == field_id:
                            enum_ok = cfv.get("enum_id") == enum_id
                            text = (cfv.get("text") or "").lower()
                            text_ok = ("подтвержд" in text) and ("не" not in text)
                            if enum_ok or text_ok:
                                eid = ev.get("entity_id")
                                if eid:
                                    result.add(eid)
                    elif item.get("field_id") == field_id:
                        e = item.get("enum_id") or item.get("value")
                        if e == enum_id:
                            eid = ev.get("entity_id")
                            if eid:
                                result.add(eid)
        if "next" in resp.get("_links", {}):
            page += 1
        else:
            break
    return result


def format_call_for_db(call_event, client_id, subdomain, clinic_name):
    """Преобразует событие звонка из AmoCRM в формат записи БД."""
    now = datetime.now()
    created_dt = datetime.fromtimestamp(call_event.get('created_at', 0))
    
    return {
        "event_id": call_event.get('event_id'),
        "lead_id": call_event.get('lead_id'),
        "lead_name": f"Lead {call_event.get('lead_id', 'Unknown')}",
        "contact_id": call_event.get('entity_id') if call_event.get('entity_type') == 'contact' else None,
        "contact_name": "Из события",
        "client_id": client_id,
        "subdomain": subdomain,
        "call_direction": "Входящий" if call_event.get('type') == 'incoming_call' else "Исходящий",
        "created_at": call_event.get('created_at'),
        "created_date": created_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "created_date_for_filtering": created_dt.strftime("%Y-%m-%d"),
        "recorded_at": now.isoformat(),
        "metrics": {
            "conversion": False  # По умолчанию
        }
    }


def enrich_calls_with_conversion(calls, converted_leads, conversion_types, client_id, subdomain, clinic_name):
    """Обогащает звонки из events данными о конверсии и форматирует для БД."""
    print(f"\n{'='*60}")
    print(f"🔄 Форматирование и обогащение звонков")
    print(f"{'='*60}")
    
    enriched_calls = []
    converted_count = 0
    now = datetime.now()
    
    for call_event in calls:
        # Форматируем в структуру БД
        call_doc = format_call_for_db(call_event, client_id, subdomain, clinic_name)
        
        lead_id = call_event.get('lead_id')
        
        # Если есть конверсия - обогащаем
        if lead_id and lead_id in converted_leads:
            call_doc["metrics"]["conversion"] = True
            call_doc["conversion_type"] = conversion_types.get(lead_id, "Unknown")
            call_doc["conversion_enriched_at"] = now.isoformat()
            call_doc["conversion_enriched_by"] = "conversion_check_v1"
            converted_count += 1
        
        enriched_calls.append(call_doc)
    
    print(f"✅ Всего звонков из events: {len(enriched_calls)}")
    print(f"✅ Звонков с конверсией: {converted_count}")
    print(f"📊 Процент конверсии: {(converted_count/len(enriched_calls)*100):.1f}%" if enriched_calls else "0%")
    
    return enriched_calls


 


async def main(client_id, target_date_str):
    """Основная функция теста."""
    print(f"\n{'='*60}")
    print(f"🧪 КОМПЛЕКСНЫЙ ТЕСТ КОНВЕРСИЙ")
    print(f"{'='*60}")
    print(f"Клиника: {client_id}")
    print(f"Дата: {target_date_str}")

    # Генерируем имена файлов
    date_clean = target_date_str.replace("-", "_")
    client_short = client_id[:8]
    output_file = f"test_results_{client_short}_{date_clean}.json"
    output_enriched = f"enriched_calls_{client_short}_{date_clean}.json"

    print(f"Результаты сохранятся в: {output_file}")

    # Подключаемся к MongoDB
    mongo_client = AsyncIOMotorClient(MONGO_URI)
    db = mongo_client[DB_NAME]

    # Находим клинику
    clinic = await db.clinics.find_one({"client_id": client_id})

    if not clinic:
        print(f"❌ Клиника не найдена")
        mongo_client.close()
        return

    print(f"✅ Клиника: {clinic.get('clinic_name', 'Неизвестно')}")

    # Создаем клиент AmoCRM (нужен для автодетекции)
    amo_client = AsyncAmoCRMClient(
        client_id=clinic["client_id"],
        client_secret=clinic["client_secret"],
        subdomain=clinic["amocrm_subdomain"],
        redirect_url=clinic["redirect_url"],
        mongo_uri=MONGO_URI,
        db_name=DB_NAME
    )

    # Загружаем конфигурацию конверсий из БД (или детектим если нет)
    config_loaded = await load_conversion_config_from_db(db, client_id, amo_client)
    if not config_loaded:
        print("❌ Не удалось загрузить конфигурацию")
        await amo_client.close()
        mongo_client.close()
        return
    
    try:
        # Шаг 1: Получаем все звонки через события и обогащаем
        calls = await get_all_calls_from_events(amo_client, target_date_str)
        
        if not calls:
            print("❌ Не найдено звонков")
            return

        call_date = datetime.strptime(target_date_str, "%Y-%m-%d")
        
        # Шаг 2: Проверяем конверсию
        print(f"\n{'='*60}")
        print(f"✅ Проверка конверсий")
        print(f"{'='*60}")
        
        converted_leads = {}
        conversion_types = {}
        not_converted_leads = []
        
        # Уникальные lead_id
        unique_leads = {}
        for call in calls:
            lead_id = call["lead_id"]
            if lead_id:
                unique_leads[lead_id] = call
        
        print(f"🔍 Уникальных сделок для проверки: {len(unique_leads)}")
        print("Конфигурация статусов:")
        print(f"  Первичные: pipeline={PIPELINE_PRIMARY_ID}, status={STATUS_PRIMARY_BOOKED_ID}")
        print(f"  Вторичные: pipeline={PIPELINE_SECONDARY_ID}, status={STATUS_SECONDARY_BOOKED_ID}")

        # Динамически определяем поле/enum подтверждения
        field_id_dyn, enum_id_dyn = await get_confirmation_field_dynamic(amo_client)
        if field_id_dyn and enum_id_dyn:
            global CONFIRMATION_FIELD_ID, CONFIRMATION_VALUE_ID
            CONFIRMATION_FIELD_ID = field_id_dyn
            CONFIRMATION_VALUE_ID = enum_id_dyn
            confirmation_field_id = field_id_dyn
            pos_use = enum_id_dyn
        else:
            confirmation_field_id = CONFIRMATION_FIELD_ID
            pos_use = CONFIRMATION_VALUE_ID

        print("Кастомное поле Подтверждение:")
        print(f"  field_id={confirmation_field_id}, enum_confirmed={pos_use}")

        # Расширяем набор сделок: добавляем те, у которых в этот день было событие подтверждения
        try:
            leads_with_cf = await get_leads_with_confirmation_events(amo_client, call_date, confirmation_field_id, pos_use)
        except Exception:
            leads_with_cf = set()
        added = 0
        for lid in leads_with_cf:
            if lid not in unique_leads:
                unique_leads[lid] = {"lead_id": lid}
                added += 1
        if added:
            print(f"➕ Добавлено сделок по событиям подтверждения без звонков: {added}")

        # Диагностика конкретного лида после определения pos_use
        if DEBUG_LEAD_ID and DEBUG_LEAD_ID not in unique_leads:
            print(f"⚠️ Лид {DEBUG_LEAD_ID} не попал в выборку звонков. Запускаю диагностику по нему...")
            _ok, _type = await check_conversion_for_lead(amo_client, DEBUG_LEAD_ID, call_date, pos_use, diagnostic=True)
            if _ok:
                print(f"✅ Диагностика: по лиду {DEBUG_LEAD_ID} конверсия обнаружена: {_type} (в отчёт попадёт через общий проход)")
        
        for idx, (lead_id, call) in enumerate(unique_leads.items(), 1):
            has_conversion, conv_type = await check_conversion_for_lead(
                amo_client, lead_id, call_date, pos_use, diagnostic=(idx <= 5)
            )
            
            if has_conversion:
                converted_leads[lead_id] = call
                conversion_types[lead_id] = conv_type
            else:
                not_converted_leads.append(lead_id)
            
            if idx % 10 == 0:
                print(f"Проверено: {idx}/{len(unique_leads)}")
        
        # Шаг 3: Формируем статистику
        print(f"\n{'='*60}")
        print(f"📊 ИТОГОВАЯ СТАТИСТИКА")
        print(f"{'='*60}")
        print(f"Всего звонков: {len(calls)}")
        print(f"Уникальных сделок: {len(unique_leads)}")
        print(f"Реальных конверсий (по статусу в AmoCRM): {len(converted_leads)}")
        
        # Группируем по типам
        types_groups = {}
        for lead_id, conv_type in conversion_types.items():
            if conv_type not in types_groups:
                types_groups[conv_type] = []
            types_groups[conv_type].append(lead_id)
        
        if converted_leads:
            print(f"\n✓ СДЕЛКИ С КОНВЕРСИЕЙ ({len(converted_leads)})")
            for conv_type, lead_ids in sorted(types_groups.items()):
                print(f"\n  {conv_type}: {len(lead_ids)} шт.")
                print(f"  ID: {sorted(lead_ids)}")
        
        if not_converted_leads:
            print(f"\n✗ СДЕЛКИ БЕЗ КОНВЕРСИИ ({len(not_converted_leads)})")
            print(f"  ID: {sorted(not_converted_leads)}")
        
        # Шаг 4: Сохраняем в JSON
        results = {
            "test_date": target_date_str,
            "client_id": client_id,
            "clinic_name": clinic.get("clinic_name", "Неизвестно"),
            "timestamp": datetime.now().isoformat(),
            "stats": {
                "total_calls": len(calls),
                "unique_leads": len(unique_leads),
                "conversions": len(converted_leads),
                "no_conversion": len(not_converted_leads)
            },
            "calls": calls,
            "converted_leads": {str(k): {"type": conversion_types[k]} for k in converted_leads.keys()},
            "not_converted_leads": sorted(not_converted_leads),
            "conversion_by_type": {k: sorted(v) for k, v in types_groups.items()}
        }


        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        print(f"\n💾 Результаты сохранены в: {output_file}")

        # Шаг 5: Форматируем звонки из events в формат БД и обогащаем конверсией
        enriched_calls = enrich_calls_with_conversion(
            calls,
            converted_leads,
            conversion_types,
            client_id,
            clinic.get('amocrm_subdomain', 'unknown'),
            clinic.get('clinic_name', 'Неизвестно')
        )

        # Сохраняем обогащённые звонки в JSON
        with open(output_enriched, "w", encoding="utf-8") as f:
            json.dump(enriched_calls, f, ensure_ascii=False, indent=2, default=str)

        print(f"\n💾 Обогащённые звонки сохранены в: {output_enriched}")
        print(f"{'='*60}\n")
        
    finally:
        await amo_client.close()
        mongo_client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Тест проверки конверсий для клиники",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  python test_full_conversion_check.py 4c640248-8904-412e-ae85-14dda10edd1b 2025-11-08
  python test_full_conversion_check.py 4cdd8fc0-c5fa-4c3c-a2a8-19b062f37fc9 2025-10-21
        """
    )
    parser.add_argument("client_id", help="UUID клиники (client_id)")
    parser.add_argument("date", help="Дата для проверки в формате YYYY-MM-DD")

    args = parser.parse_args()

    # Валидация даты
    try:
        datetime.strptime(args.date, "%Y-%m-%d")
    except ValueError:
        print(f"❌ Неверный формат даты: {args.date}. Используйте YYYY-MM-DD")
        sys.exit(1)

    asyncio.run(main(args.client_id, args.date))
