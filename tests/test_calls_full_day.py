# -*- coding: utf-8 -*-
"""
Тест: получить все звонки за день (через API событий) и ДОобогатить:
- lead_id (через contacts/{id}?with=leads)
- administrator / source (через сделку)

Запуск:
  python3 test_calls_full_day.py --client 4c640248-8904-412e-ae85-14dda10edd1b --date 01.10.2025 --contact 36450557

Если не указать --contact, покажет все события за день.
"""
import asyncio
import argparse
import json
import os
from datetime import datetime, time
from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorClient  # не обязателен, но может пригодиться

from app.routers.calls_events import get_calls_from_events, get_call_details, get_custom_field_value_by_name, convert_processing_speed_to_minutes  # type: ignore
from mlab_amo_async.amocrm_client import AsyncAmoCRMClient
from app.settings.paths import DB_NAME as DB_NAME_CFG
MONGO_URI = "mongodb://92.113.151.220:27018/"

def to_day_range(date_str: str) -> (int, int):
    dt = None
    # поддержим оба формата
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(date_str, fmt)
            break
        except ValueError:
            continue
    if dt is None:
        raise ValueError("Неверный формат даты. Используйте DD.MM.YYYY или YYYY-MM-DD")
    start = int(datetime.combine(dt.date(), time.min).timestamp())
    end = int(datetime.combine(dt.date(), time.max).timestamp())
    return start, end


def clean_phone(v: str) -> str:
    if not isinstance(v, str):
        return v
    # отрезаем хвосты вида ", Статус: ..."
    return v.split(", Статус")[0].strip()


async def ensure_enrichment(client: AsyncAmoCRMClient, rec: Dict[str, Any]) -> Dict[str, Any]:
    """Безопасное дообогащение lead_id + кастомные поля.
    - Если lead_id пуст и есть contact_id: подтянем контакта с with=leads, выберем последнюю сделку.
    - По lead_id запросим сделку и извлечём administrator/source/processing_speed.
    """
    contact_id = rec.get("contact_id")
    lead_id = rec.get("lead_id")

    # 1) Если нет lead_id, но есть contact_id — попробуем получить сделки контакта
    if not lead_id and contact_id:
        try:
            data, status = await client.contacts.request(
                "get", f"contacts/{contact_id}", params={"with": "leads"}
            )
            if status == 200 and isinstance(data, dict):
                leads = data.get("_embedded", {}).get("leads", [])
                # берём последнюю по updated_at/created_at
                def lead_ts(x):
                    return x.get("updated_at") or x.get("created_at") or 0
                if leads:
                    leads_sorted = sorted(leads, key=lead_ts, reverse=True)
                    rec["lead_id"] = leads_sorted[0].get("id")
        except Exception:
            pass

    # 2) Если есть lead_id — запросим сделку и обогатим кастомные поля
    lead_id = rec.get("lead_id")
    if lead_id:
        try:
            # базовый метод клиента
            lead_info = await client.get_lead(int(lead_id))
            if not lead_info or not isinstance(lead_info, dict):
                # попытка прямого запроса
                lead_info, _ = await client.leads.request("get", f"leads/{lead_id}")

            if isinstance(lead_info, dict):
                admin = get_custom_field_value_by_name(lead_info, "administrator")
                source = get_custom_field_value_by_name(lead_info, "source")
                speed_str = get_custom_field_value_by_name(lead_info, "processing_speed")
                if admin:
                    rec["administrator"] = admin
                if source:
                    rec["source"] = source
                if speed_str:
                    rec["processing_speed_str"] = speed_str
                    rec["processing_speed"] = convert_processing_speed_to_minutes(speed_str)
        except Exception:
            pass

    # 3) нормализуем телефон
    if rec.get("phone"):
        rec["phone"] = clean_phone(rec["phone"]) 

    return rec


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--client", required=True, help="client_id AmoCRM")
    parser.add_argument("--date", required=True, help="Дата (DD.MM.YYYY или YYYY-MM-DD)")
    parser.add_argument("--contact", type=int, default=None, help="Опционально фильтр по contact_id")
    parser.add_argument("--output", default=None, help="Путь к JSON файлу (по умолчанию: calls_<client>_<date>.json)")
    args = parser.parse_args()

    # Получим клинику как в test_enrichment_simple.py (напрямую из MongoDB)
    mongo_client = AsyncIOMotorClient(MONGO_URI)
    db = mongo_client[DB_NAME_CFG]
    clinic = await db.clinics.find_one({"client_id": args.client})
    if not clinic:
        print(f"Клиника не найдена по client_id={args.client}")
        mongo_client.close()
        return

    client = AsyncAmoCRMClient(
        client_id=clinic["client_id"],
        client_secret=clinic["client_secret"],
        subdomain=clinic["amocrm_subdomain"],
        redirect_url=clinic["redirect_url"],
        mongo_uri=MONGO_URI,
        db_name=DB_NAME_CFG,
    )

    start_ts, end_ts = to_day_range(args.date)

    try:
        events = await get_calls_from_events(client, start_ts, end_ts, max_pages=20)
        # Фильтр: только звонки указанного контакта (если задан)
        if args.contact is not None:
            events = [e for e in events if e.get("entity_type") == "contact" and e.get("entity_id") == args.contact]

        print(f"Найдено событий: {len(events)}")

        results: List[Dict[str, Any]] = []
        for ev in events:
            rec = await get_call_details(ev, client, administrator="Неизвестный", source="Неопределенный", client_id_str=args.client, subdomain_str=clinic["amocrm_subdomain"])  # базовые поля
            rec = await ensure_enrichment(client, rec)  # дообогащение
            results.append(rec)

        # Короткий отчёт
        enriched = sum(1 for r in results if r.get("lead_id"))
        admins = sum(1 for r in results if r.get("administrator") and r["administrator"] != "Неизвестный")
        sources = sum(1 for r in results if r.get("source") and r["source"] != "Неопределенный")

        print(f"Итого записей: {len(results)} | с lead_id: {enriched} | с administrator: {admins} | с source: {sources}")
        # Показать примеры
        for r in results[:10]:
            print({
                "note_id": r.get("note_id"),
                "contact_id": r.get("contact_id"),
                "lead_id": r.get("lead_id"),
                "administrator": r.get("administrator"),
                "source": r.get("source"),
                "duration": r.get("duration"),
                "phone": r.get("phone"),
            })

        # Экспорт в JSON
        safe_date = args.date.replace("/", "-").replace(".", "-")
        default_name = f"calls_{args.client}_{safe_date}.json"
        out_path = args.output or default_name
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n💾 Сохранено в файл: {out_path} (записей: {len(results)})")

    finally:
        await client.close()
        mongo_client.close()


if __name__ == "__main__":
    asyncio.run(main())
