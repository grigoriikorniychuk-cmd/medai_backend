"""
ПОЛНЫЙ АУДИТ: проверяет КАЖДУЮ транскрипцию за 28 января 2026 через gpt-5-mini.

Сравнивает результат AI с тем, что в базе. Показывает ВСЕ расхождения,
включая случаи когда в базе "правильное" имя, но AI считает иначе.

Запуск:
    # Конкретная клиника:
    pytest tests/test_admin_full_audit.py -v -s -k "newdental"
    pytest tests/test_admin_full_audit.py -v -s -k "stomdv"
    pytest tests/test_admin_full_audit.py -v -s -k "perfetto"
    pytest tests/test_admin_full_audit.py -v -s -k "iqdental"

    # Все клиники (долго, ~300 вызовов API):
    pytest tests/test_admin_full_audit.py -v -s
"""

import asyncio
import json
import os
import re
import logging
from typing import Dict, Any, List, Optional

import pytest
from langchain_openai import ChatOpenAI
from app.prompts.templates import DEFAULT_PROMPT_TEMPLATES, PromptType

logger = logging.getLogger(__name__)

SCRATCHPAD = "/tmp/claude/-home-mpr0-Develop-medai-backend/bb009f44-5420-42ca-ad22-c9cad3970a9b/scratchpad"
TRANSCRIPTIONS_DIR = os.path.join(SCRATCHPAD, "transcriptions")
CALLS_FILE = os.path.join(SCRATCHPAD, "calls_jan28.json")

MODEL = "gpt-5-mini"


def load_calls_data() -> List[Dict]:
    with open(CALLS_FILE, 'r', encoding='utf-8') as f:
        return json.loads(f.read())


def read_transcription(filename: str) -> Optional[str]:
    path = os.path.join(TRANSCRIPTIONS_DIR, filename)
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def format_admins_list(schedule: List[Dict]) -> str:
    return "\n".join([
        f"- {a['first_name']} {a['last_name']}"
        for a in schedule
    ])


async def extract_admin(
    llm,
    transcription_text: str,
    schedule: List[Dict],
) -> Dict[str, Any]:
    """Вызывает LLM + валидация + подстановка фамилии."""
    prompt_template = DEFAULT_PROMPT_TEMPLATES[PromptType.ADMIN_NAME_EXTRACTION]
    admins_formatted = format_admins_list(schedule)

    prompt_text = prompt_template.template.format(
        transcription=transcription_text,
        administrators_list=admins_formatted,
    )

    try:
        response = await llm.ainvoke(prompt_text)
        response_text = response.content if hasattr(response, 'content') else str(response)
        cleaned = re.sub(r'```json\s*|\s*```', '', response_text).strip()
        result = json.loads(cleaned)

        first_name = result.get('first_name')
        last_name = result.get('last_name')
        confidence = result.get('confidence', 0.0)

        # Валидация: имя должно быть из графика
        if first_name and schedule:
            valid_first_names = {a['first_name'] for a in schedule}
            if first_name not in valid_first_names:
                return {
                    "final_name": "Неизвестный администратор",
                    "reason": f"AI вернул '{first_name}' — нет в графике",
                    "confidence": confidence,
                }

            # Подстановка фамилии если нет
            if not last_name:
                matching = [a for a in schedule if a['first_name'] == first_name]
                if matching:
                    last_name = matching[0]['last_name']

        if not first_name or confidence < 0.3:
            return {
                "final_name": "Неизвестный администратор",
                "reason": f"AI: null/low confidence ({confidence})",
                "confidence": confidence,
            }

        first = (first_name or "").strip()
        last = (last_name or "").strip()
        final = f"{first} {last}".strip() if last else first

        return {
            "final_name": final,
            "reason": f"AI: {first_name} {last_name} (conf={confidence})",
            "confidence": confidence,
        }

    except Exception as e:
        return {
            "final_name": "ERROR",
            "reason": str(e)[:150],
            "confidence": 0.0,
        }


@pytest.fixture(scope="module")
def calls_data():
    return load_calls_data()


@pytest.fixture(scope="module")
def llm():
    from dotenv import load_dotenv
    load_dotenv()
    openai_key = os.getenv("OPENAI")
    return ChatOpenAI(
        model_name=MODEL,
        temperature=1.0,  # gpt-5-mini поддерживает только 1.0
        openai_api_key=openai_key,
    )


def get_clinic(calls_data, name):
    for c in calls_data:
        if c["clinic_name"] == name:
            return c
    pytest.skip(f"Клиника {name} не найдена")


class TestFullAudit:

    @pytest.mark.asyncio
    async def test_newdental(self, calls_data, llm):
        await self._full_audit(calls_data, llm, "newdental")

    @pytest.mark.asyncio
    async def test_stomdv(self, calls_data, llm):
        await self._full_audit(calls_data, llm, "stomdv")

    @pytest.mark.asyncio
    async def test_perfettoclinic78(self, calls_data, llm):
        await self._full_audit(calls_data, llm, "perfettoclinic78")

    @pytest.mark.asyncio
    async def test_iqdentalclinic(self, calls_data, llm):
        await self._full_audit(calls_data, llm, "iqdentalclinic")

    async def _full_audit(self, calls_data, llm, clinic_name):
        clinic = get_clinic(calls_data, clinic_name)
        schedule = clinic["schedule"]
        files = clinic["files"]
        valid_full_names = {f"{a['first_name']} {a['last_name']}" for a in schedule}
        valid_full_names.add("Неизвестный администратор")

        print(f"\n{'='*110}")
        print(f"ПОЛНЫЙ АУДИТ: {clinic_name} ({clinic['clinic_id']})")
        print(f"Модель: {MODEL}")
        print(f"График: {format_admins_list(schedule)}")
        print(f"Всего звонков: {len(files)}")
        print(f"{'='*110}")

        semaphore = asyncio.Semaphore(5)
        results = []

        async def process_one(call):
            async with semaphore:
                text = read_transcription(call["fn"])
                if not text:
                    return {**call, "ai_result": {"final_name": "ФАЙЛ_НЕ_НАЙДЕН", "reason": "404"}}
                res = await extract_admin(llm, text, schedule)
                return {**call, "ai_result": res}

        tasks = [process_one(c) for c in files]
        results = await asyncio.gather(*tasks)

        # Классификация результатов
        match_count = 0
        mismatch_details = []
        db_wrong = []  # В базе некорректное значение
        ai_disagrees = []  # AI даёт другой ответ чем в базе

        for r in results:
            db_name = r["admin"]
            ai_name = r["ai_result"]["final_name"]

            if ai_name == "ФАЙЛ_НЕ_НАЙДЕН" or ai_name == "ERROR":
                mismatch_details.append(r)
                continue

            if db_name == ai_name:
                match_count += 1
            else:
                # Определяем тип расхождения
                db_valid = db_name in valid_full_names
                ai_valid = ai_name in valid_full_names

                r["db_valid"] = db_valid
                r["ai_valid"] = ai_valid

                if not db_valid:
                    db_wrong.append(r)
                else:
                    ai_disagrees.append(r)

        total = len(results)
        errors = [r for r in results if r["ai_result"]["final_name"] in ("ФАЙЛ_НЕ_НАЙДЕН", "ERROR")]

        print(f"\n{'─'*110}")
        print(f"СОВПАДЕНИЯ (база == AI): {match_count}/{total}")
        print(f"{'─'*110}")

        # 1. В базе некорректное значение
        if db_wrong:
            print(f"\n🔴 В БАЗЕ НЕКОРРЕКТНОЕ ЗНАЧЕНИЕ ({len(db_wrong)} шт):")
            print(f"{'Файл':<45} {'В базе (ОШИБКА)':<25} {'AI (gpt-5-mini)':<25} {'Пояснение'}")
            print(f"{'─'*110}")
            for r in db_wrong:
                print(f"{r['fn']:<45} {r['admin']:<25} {r['ai_result']['final_name']:<25} {r['ai_result'].get('reason','')}")

        # 2. AI даёт другой ответ (оба валидны — кто прав?)
        if ai_disagrees:
            print(f"\n🟡 AI ОПРЕДЕЛИЛ ДРУГОГО АДМИНИСТРАТОРА ({len(ai_disagrees)} шт):")
            print(f"{'Файл':<45} {'В базе':<25} {'AI (gpt-5-mini)':<25} {'Пояснение'}")
            print(f"{'─'*110}")
            for r in ai_disagrees:
                print(f"{r['fn']:<45} {r['admin']:<25} {r['ai_result']['final_name']:<25} {r['ai_result'].get('reason','')}")

        # 3. Ошибки
        if errors:
            print(f"\n⚠️  ОШИБКИ ({len(errors)} шт):")
            for r in errors:
                print(f"  {r['fn']}: {r['ai_result'].get('reason','')}")

        # Итоги
        print(f"\n{'='*110}")
        print(f"ИТОГО {clinic_name}:")
        print(f"  Совпадений:                    {match_count}/{total}")
        print(f"  В базе некорректное:           {len(db_wrong)}")
        print(f"  AI определил другого админа:   {len(ai_disagrees)}")
        print(f"  Ошибки/файл не найден:         {len(errors)}")
        print(f"{'='*110}")

        # Тест показывает всё, не фейлится
        if db_wrong or ai_disagrees:
            total_issues = len(db_wrong) + len(ai_disagrees)
            print(f"\n⚠️  ВНИМАНИЕ: {total_issues} расхождений требуют внимания!")
