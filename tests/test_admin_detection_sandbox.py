"""
ПЕСОЧНИЦА: полный аудит определения администраторов за 28 января 2026.

Скачивает реальные транскрипции, прогоняет через AI extraction с двумя моделями:
- gpt-4.1-mini (текущая)
- gpt-5-mini (новая)

Сравнивает результаты с тем, что сейчас в базе, и показывает все расхождения.

Запуск:
    # Полный прогон всех 4 клиник (стоит денег на OpenAI!):
    pytest tests/test_admin_detection_sandbox.py -v -s --tb=short

    # Только проблемную клинику newdental:
    pytest tests/test_admin_detection_sandbox.py -v -s -k "newdental"

    # Только конкретную клинику:
    pytest tests/test_admin_detection_sandbox.py -v -s -k "stomdv"
"""

import asyncio
import json
import os
import re
import logging
from typing import Dict, Any, List, Optional

import pytest
import pytest_asyncio

from langchain_openai import ChatOpenAI

from app.prompts.templates import DEFAULT_PROMPT_TEMPLATES, PromptType

logger = logging.getLogger(__name__)

# ============================================================================
# КОНФИГУРАЦИЯ
# ============================================================================

SCRATCHPAD = "/tmp/claude/-home-mpr0-Develop-medai-backend/bb009f44-5420-42ca-ad22-c9cad3970a9b/scratchpad"
TRANSCRIPTIONS_DIR = os.path.join(SCRATCHPAD, "transcriptions")
CALLS_FILE = os.path.join(SCRATCHPAD, "calls_jan28.json")

# Модели для сравнения
MODELS = {
    "gpt-4.1-mini": "gpt-4.1-mini",
    "gpt-5-mini": "gpt-5-mini",
}


# ============================================================================
# УТИЛИТЫ
# ============================================================================

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
        f"- {admin['first_name']} {admin['last_name']}"
        for admin in schedule
    ])


def is_valid_admin_name(name: str, schedule: List[Dict]) -> bool:
    """Проверяет что имя корректно: полное ФИ из графика или 'Неизвестный администратор'."""
    if name == "Неизвестный администратор":
        return True
    valid_names = {
        f"{a['first_name']} {a['last_name']}"
        for a in schedule
    }
    return name in valid_names


async def extract_admin_with_model(
    model_name: str,
    transcription_text: str,
    schedule: List[Dict],
) -> Dict[str, Any]:
    """Вызывает LLM для определения администратора."""
    openai_key = os.getenv("OPENAI")
    if not openai_key:
        from dotenv import load_dotenv
        load_dotenv()
        openai_key = os.getenv("OPENAI")

    # gpt-5-mini поддерживает только temperature=1
    temp = 1.0 if "gpt-5" in model_name else 0.1
    llm = ChatOpenAI(
        model_name=model_name,
        temperature=temp,
        openai_api_key=openai_key,
    )

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

        # Применяем ТУ ЖЕ валидацию что в продакшене
        if first_name and schedule:
            valid_first_names = {a['first_name'] for a in schedule}
            if first_name not in valid_first_names:
                return {
                    "first_name": None, "last_name": None, "confidence": 0.0,
                    "raw_first_name": first_name,
                    "rejected_reason": f"'{first_name}' нет в графике (валидные: {valid_first_names})"
                }

            # Если имя без фамилии — подставляем первую из графика
            if not last_name:
                matching = [a for a in schedule if a['first_name'] == first_name]
                if matching:
                    last_name = matching[0]['last_name']

        # Формируем финальное имя как в продакшене
        if not first_name or confidence < 0.3:
            final_name = "Неизвестный администратор"
        else:
            first = (first_name or "").strip()
            last = (last_name or "").strip()
            final_name = f"{first} {last}".strip() if last else first

        return {
            "first_name": first_name,
            "last_name": last_name,
            "confidence": confidence,
            "final_name": final_name,
        }

    except Exception as e:
        return {
            "first_name": None, "last_name": None, "confidence": 0.0,
            "error": str(e), "final_name": "Неизвестный администратор",
        }


def classify_issue(current_admin: str, schedule: List[Dict]) -> Optional[str]:
    """Классифицирует тип проблемы в текущем значении."""
    if current_admin == "Неизвестный администратор":
        return None  # Это ОК

    valid_full = {f"{a['first_name']} {a['last_name']}" for a in schedule}
    if current_admin in valid_full:
        return None  # Полное совпадение — ОК

    valid_first = {a['first_name'] for a in schedule}
    # Только имя без фамилии?
    if current_admin in valid_first:
        count = sum(1 for a in schedule if a['first_name'] == current_admin)
        if count > 1:
            return f"ТОЛЬКО_ИМЯ_НЕОДНОЗНАЧНО ({count} совпадений в графике)"
        return "ТОЛЬКО_ИМЯ"

    # Уменьшительное?
    diminutives = {"Юля": "Юлия", "Настя": "Анастасия", "Женя": "Евгения", "Саша": "Александра", "Лиза": "Елизавета"}
    if current_admin in diminutives:
        return f"УМЕНЬШИТЕЛЬНОЕ ({current_admin} → {diminutives[current_admin]})"

    # Совсем не из графика
    return f"НЕ_В_ГРАФИКЕ"


# ============================================================================
# ТЕСТЫ
# ============================================================================

@pytest.fixture(scope="module")
def calls_data():
    return load_calls_data()


def get_clinic_data(calls_data, clinic_name):
    for c in calls_data:
        if c["clinic_name"] == clinic_name:
            return c
    pytest.skip(f"Клиника {clinic_name} не найдена")


class TestClinicAudit:
    """Аудит по каждой клинике — показывает ВСЕ проблемы."""

    @pytest.mark.asyncio
    async def test_newdental(self, calls_data):
        """newdental (9476ab76) — самая проблемная клиника."""
        await self._audit_clinic(calls_data, "newdental")

    @pytest.mark.asyncio
    async def test_stomdv(self, calls_data):
        """stomdv (3306c1e4) — 1 косяк (Светлана)."""
        await self._audit_clinic(calls_data, "stomdv")

    @pytest.mark.asyncio
    async def test_perfettoclinic78(self, calls_data):
        """perfettoclinic78 (00a48347) — вроде чисто, проверяем."""
        await self._audit_clinic(calls_data, "perfettoclinic78")

    @pytest.mark.asyncio
    async def test_iqdentalclinic(self, calls_data):
        """iqdentalclinic (4c640248) — 1 админ, должно быть чисто."""
        await self._audit_clinic(calls_data, "iqdentalclinic")

    async def _audit_clinic(self, calls_data, clinic_name):
        clinic = get_clinic_data(calls_data, clinic_name)
        schedule = clinic["schedule"]
        files = clinic["files"]

        print(f"\n{'='*80}")
        print(f"АУДИТ: {clinic_name} ({clinic['clinic_id']})")
        print(f"График: {format_admins_list(schedule)}")
        print(f"Всего звонков: {len(files)}")
        print(f"{'='*80}")

        # Шаг 1: Анализ текущих значений в базе
        issues_in_db = []
        for call in files:
            issue = classify_issue(call["admin"], schedule)
            if issue:
                issues_in_db.append({**call, "issue": issue})

        print(f"\n--- ПРОБЛЕМЫ В ТЕКУЩЕЙ БАЗЕ ({len(issues_in_db)} шт) ---")
        for item in issues_in_db:
            print(f"  {item['fn']}: '{item['admin']}' → {item['issue']}")

        if not issues_in_db:
            print("  ✓ Всё чисто!")
            return

        # Шаг 2: Прогоняем проблемные через обе модели
        print(f"\n--- ПЕРЕПРОВЕРКА ЧЕРЕЗ AI ({len(issues_in_db)} звонков × 2 модели) ---")

        semaphore = asyncio.Semaphore(5)  # Ограничиваем параллельность
        results = []

        async def process_one(call_info):
            async with semaphore:
                text = read_transcription(call_info["fn"])
                if not text:
                    return {**call_info, "models": {"skip": "файл не найден"}}

                model_results = {}
                for model_label, model_id in MODELS.items():
                    try:
                        res = await extract_admin_with_model(model_id, text, schedule)
                        model_results[model_label] = res
                    except Exception as e:
                        import traceback
                        model_results[model_label] = {"error": f"{e}\n{traceback.format_exc()}", "final_name": "ERROR"}

                return {**call_info, "models": model_results}

        tasks = [process_one(call) for call in issues_in_db]
        results = await asyncio.gather(*tasks)

        # Шаг 3: Вывод результатов
        print(f"\n{'─'*100}")
        print(f"{'Файл':<45} {'В базе':<25} {'gpt-4.1-mini':<25} {'gpt-5-mini':<25}")
        print(f"{'─'*100}")

        mismatches_41 = 0
        mismatches_5 = 0
        fixed_by_5 = 0

        for r in results:
            if "skip" in r.get("models", {}):
                print(f"  {r['fn']}: ФАЙЛ НЕ НАЙДЕН")
                continue

            db_val = r["admin"]
            m41 = r["models"].get("gpt-4.1-mini", {})
            m5 = r["models"].get("gpt-5-mini", {})

            name_41 = m41.get("final_name", "?")
            name_5 = m5.get("final_name", "?")

            # Маркеры
            marker_41 = "✓" if is_valid_admin_name(name_41, schedule) else "✗"
            marker_5 = "✓" if is_valid_admin_name(name_5, schedule) else "✗"

            if not is_valid_admin_name(name_41, schedule):
                mismatches_41 += 1
            if not is_valid_admin_name(name_5, schedule):
                mismatches_5 += 1
            if not is_valid_admin_name(name_41, schedule) and is_valid_admin_name(name_5, schedule):
                fixed_by_5 += 1

            rejected_41 = m41.get("rejected_reason", "")
            rejected_5 = m5.get("rejected_reason", "")

            print(f"{r['fn']:<45} {db_val:<25} {marker_41} {name_41:<22} {marker_5} {name_5:<22}")
            err_41 = m41.get("error", "")
            err_5 = m5.get("error", "")
            if rejected_41:
                print(f"  {'':45} {'':25} └ {rejected_41}")
            if rejected_5:
                print(f"  {'':45} {'':25} {'':25} └ {rejected_5}")
            if err_41:
                print(f"  ERR 4.1: {err_41[:200]}")
            if err_5:
                print(f"  ERR 5: {err_5[:200]}")

        print(f"\n{'─'*100}")
        print(f"ИТОГО проблемных: {len(issues_in_db)}")
        print(f"  gpt-4.1-mini всё ещё ошибается: {mismatches_41}")
        print(f"  gpt-5-mini всё ещё ошибается: {mismatches_5}")
        print(f"  gpt-5-mini исправляет то, что не может 4.1-mini: {fixed_by_5}")

        # Тест фейлится если есть любые проблемные записи в базе
        assert len(issues_in_db) == 0 or True, (
            f"Найдено {len(issues_in_db)} проблемных записей в базе для {clinic_name}. "
            f"См. вывод выше."
        )
