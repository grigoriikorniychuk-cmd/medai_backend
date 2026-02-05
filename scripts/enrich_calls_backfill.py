# -*- coding: utf-8 -*-
"""
Backfill-скрипт: дообогащение записей звонков в MongoDB по заданным клиникам.
- По каждому client_id: пройти все документы в коллекции `calls` и заполнить недостающие поля
  `lead_id`, `administrator`, `source`, `processing_speed`, `processing_speed_str`.
- Логика обогащения совпадает с `test_calls_full_day.py` (ensure_enrichment):
  1) Если нет lead_id, но есть contact_id — `GET contacts/{id}?with=leads` и выбираем последнюю сделку
  2) По lead_id — `GET leads/{id}` и вытаскиваем кастомные поля `administrator`, `source`, `processing_speed`

Запуск (пример):
  python3 scripts/enrich_calls_backfill.py \
      --clients 4c640248-8904-412e-ae85-14dda10edd1b,500655e7-f5b7-49e2-bd8f-5907f68e5578 \
      --concurrency 6 \
      --limit 0 \
      --dry-run

Примечание:
- По умолчанию «штамп» обогащения (enriched_at, enriched_by) не добавляется. Включить можно флагом --stamp.
- Для чтения параметров amoCRM используем коллекцию `clinics`.
"""

import asyncio
import argparse
from datetime import datetime
from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorClient
from mlab_amo_async.amocrm_client import AsyncAmoCRMClient

import sys
from pathlib import Path

# Добавляем корень проекта в sys.path, чтобы импортировать пакет `app`,
# когда скрипт запускается из подкаталога `scripts/`.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.routers.calls_events import (
    get_custom_field_value_by_name,
    convert_processing_speed_to_minutes,
)
from app.settings.paths import DB_NAME as DB_NAME_CFG

MONGO_URI = "mongodb://92.113.151.220:27018/"


async def ensure_enrichment(client: AsyncAmoCRMClient, rec: Dict[str, Any]) -> Dict[str, Any]:
    """Дообогащение lead_id и кастомных полей сделки (administrator/source/processing_speed)."""
    contact_id = rec.get("contact_id")
    lead_id = rec.get("lead_id")

    # 1) Всегда пробуем определить актуальный lead_id через контакт (перезаписываем даже если он уже есть)
    if contact_id:
        try:
            data, status = await client.contacts.request(
                "get", f"contacts/{contact_id}", params={"with": "leads"}
            )
            if status == 200 and isinstance(data, dict):
                leads = data.get("_embedded", {}).get("leads", [])
                def lead_ts(x):
                    return x.get("updated_at") or x.get("created_at") or 0
                if leads:
                    leads_sorted = sorted(leads, key=lead_ts, reverse=True)
                    rec["lead_id"] = leads_sorted[0].get("id")
        except Exception:
            pass

    # 2) Обогащение из сделки
    lead_id = rec.get("lead_id")
    if lead_id:
        try:
            lead_info = await client.get_lead(int(lead_id))
            if not lead_info or not isinstance(lead_info, dict):
                lead_info, _ = await client.leads.request("get", f"leads/{lead_id}")

            if isinstance(lead_info, dict):
                # Название сделки
                ln = lead_info.get("name")
                if ln:
                    rec["lead_name"] = ln
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

    return rec


def needs_enrichment(doc: Dict[str, Any]) -> bool:
    """Определить, требуется ли дообогащение документа."""
    if not doc.get("lead_id"):
        return True
    if not doc.get("administrator") or doc.get("administrator") == "Неизвестный":
        return True
    if not doc.get("source") or doc.get("source") == "Неопределенный":
        return True
    if ("processing_speed" not in doc) or ("processing_speed_str" not in doc):
        return True
    return False


async def process_doc(
    db, client: AsyncAmoCRMClient, calls_collection, doc: Dict[str, Any], *, dry_run: bool, stamp: bool
) -> Dict[str, Any]:
    original: Dict[str, Any] = {
        "lead_id": doc.get("lead_id"),
        "lead_name": doc.get("lead_name"),
        "administrator": doc.get("administrator"),
        "source": doc.get("source"),
        "processing_speed": doc.get("processing_speed"),
        "processing_speed_str": doc.get("processing_speed_str"),
    }

    rec: Dict[str, Any] = {
        "contact_id": doc.get("contact_id"),
        "lead_id": doc.get("lead_id"),
    }

    rec = await ensure_enrichment(client, rec)

    updates: Dict[str, Any] = {}
    for key in ("lead_id", "lead_name", "administrator", "source", "processing_speed", "processing_speed_str"):
        new_val = rec.get(key)
        if new_val is not None and new_val != original.get(key):
            updates[key] = new_val

    if updates:
        if stamp:
            updates["enriched_by"] = "backfill_v1"
            updates["enriched_at"] = datetime.utcnow()
        if dry_run:
            return {"_id": str(doc.get("_id")), "changes": updates}
        else:
            await calls_collection.update_one({"_id": doc["_id"]}, {"$set": updates})
            return {"_id": str(doc.get("_id")), "updated": True, "changes": updates}

    return {"_id": str(doc.get("_id")), "updated": False}


async def process_client(
    mongo: AsyncIOMotorClient,
    client_id_str: str,
    *,
    concurrency: int,
    limit: int,
    dry_run: bool,
    stamp: bool,
) -> None:
    db = mongo[DB_NAME_CFG]

    clinic = await db.clinics.find_one({"client_id": client_id_str})
    if not clinic:
        print(f"❌ Клиника не найдена: {client_id_str}")
        return

    amo = AsyncAmoCRMClient(
        client_id=clinic["client_id"],
        client_secret=clinic["client_secret"],
        subdomain=clinic["amocrm_subdomain"],
        redirect_url=clinic["redirect_url"],
        mongo_uri=MONGO_URI,
        db_name=DB_NAME_CFG,
    )

    calls = db.calls

    # Обрабатываем все документы клиента (за все даты), чтобы перезаписать lead_id и заполнить lead_name/поля сделки
    query = {"client_id": client_id_str}

    cursor = calls.find(query, projection={
        "_id": 1,
        "contact_id": 1,
        "lead_id": 1,
        "lead_name": 1,
        "administrator": 1,
        "source": 1,
        "processing_speed": 1,
        "processing_speed_str": 1,
        "created_date_for_filtering": 1,
    })

    if limit and limit > 0:
        cursor = cursor.limit(limit)

    sem = asyncio.Semaphore(max(1, concurrency))

    async def _bound(doc):
        async with sem:
            return await process_doc(db, amo, calls, doc, dry_run=dry_run, stamp=stamp)

    processed = 0
    updated = 0
    try:
        tasks: List[asyncio.Task] = []
        async for doc in cursor:
            tasks.append(asyncio.create_task(_bound(doc)))
        for coro in asyncio.as_completed(tasks):
            res = await coro
            processed += 1
            if res.get("changes"):
                updated += 1
            # Короткий прогресс
            if processed % 100 == 0:
                print(f"{client_id_str}: обработано {processed}, обновлено {updated}")
    finally:
        await amo.close()

    print(f"✅ Клиент {client_id_str}: всего обработано {processed}, обновлено {updated}")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--clients", required=True, help="Список client_id через запятую")
    parser.add_argument("--concurrency", type=int, default=6, help="Параллелизм запросов к AmoCRM")
    parser.add_argument("--limit", type=int, default=0, help="Ограничить количество документов на клиента (0 = без лимита)")
    parser.add_argument("--dry-run", action="store_true", help="Только показать изменения без записи")
    parser.add_argument("--stamp", action="store_true", help="Добавлять enriched_by/enriched_at в обновлённые документы")
    args = parser.parse_args()

    clients: List[str] = [c.strip() for c in args.clients.split(",") if c.strip()]

    mongo = AsyncIOMotorClient(MONGO_URI)
    try:
        for cid in clients:
            await process_client(
                mongo,
                cid,
                concurrency=args.concurrency,
                limit=args.limit,
                dry_run=bool(args.dry_run),
                stamp=bool(args.stamp),
            )
    finally:
        mongo.close()


if __name__ == "__main__":
    asyncio.run(main())
