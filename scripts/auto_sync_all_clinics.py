#!/usr/bin/env python3
"""
Автоматическая синхронизация, транскрибация и анализ звонков для ВСЕХ клиник.
Запускается ежедневно через cron.

ВАЖНО: ВСЕ эндпоинты работают АСИНХРОННО (добавляют задачи в background).
Скрипт использует статус-эндпоинты для polling и ожидания реального завершения.

Операции:
1. Синхронизация звонков из AmoCRM (асинхронная + polling через /export-results)
2. Транскрибация звонков (асинхронная + polling через /transcribe-by-date-range-status)
3. Анализ звонков (асинхронный + polling через /analyze-by-date-range-status)
4. [Еженедельно] Анализ рекомендаций

Использование:
    # Ежедневная синхронизация (сегодняшний день)
    python auto_sync_all_clinics.py
    
    # За конкретную дату
    python auto_sync_all_clinics.py --date 02.12.2025
    
    # За диапазон дат
    python auto_sync_all_clinics.py --start-date 01.12.2025 --end-date 02.12.2025
    
    # С недельным анализом рекомендаций
    python auto_sync_all_clinics.py --weekly-analysis
    
    # Только для конкретной клиники
    python auto_sync_all_clinics.py --client-id 4c640248-8904-412e-ae85-14dda10edd1b

Cron примеры:
    # Ежедневно в 21:00 по МСК (18:00 UTC) за сегодняшний день
    0 18 * * * cd /home/mpr0/Develop/medai_backend && /home/mpr0/Develop/medai_backend/venv/bin/python scripts/auto_sync_all_clinics.py >> logs/cron_daily.log 2>&1
    
    # Еженедельно по понедельникам в 7:00 (недельный анализ)
    0 7 * * 1 cd /home/mpr0/Develop/medai_backend && /home/mpr0/Develop/medai_backend/venv/bin/python scripts/auto_sync_all_clinics.py --weekly-analysis >> logs/cron_weekly.log 2>&1
"""

import os
import sys
import asyncio
import argparse
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
import json
from zoneinfo import ZoneInfo

import httpx
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

# Путь к корню проекта
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# Загрузка .env
load_dotenv(os.path.join(PROJECT_ROOT, '.env'))

# === КОНФИГУРАЦИЯ ===
MONGO_URI = os.getenv('MONGODB_URI', 'mongodb://92.113.151.220:27018/')
DB_NAME = os.getenv('MONGODB_NAME', 'medai')
# BASE_URL уже содержит /api (например https://api.mlab-electronics.ru/api)
# Поэтому пути эндпоинтов НЕ должны начинаться с /api
BASE_URL = os.getenv('API_BASE_URL', 'https://api.mlab-electronics.ru/api').rstrip('/')
TELEGRAM_BOT_TOKEN = os.getenv('BOT_TOKEN')
TELEGRAM_ADMIN_CHAT_ID = os.getenv('TELEGRAM_ADMIN_CHAT_ID')

# === ТАЙМАУТЫ И НАСТРОЙКИ POLLING ===
SYNC_TIMEOUT = 60  # 1 минута на запуск синхронизации (возвращает tasks_queued)
TRANSCRIBE_TRIGGER_TIMEOUT = 60  # 1 минута на запуск транскрибации
ANALYZE_TRIGGER_TIMEOUT = 60  # 1 минута на запуск анализа
RECOMMENDATIONS_TIMEOUT = 600  # 10 минут на рекомендации

# Polling настройки
POLL_INTERVAL = 20  # Интервал проверки статуса (секунды)
EXPORT_MAX_WAIT = 3600  # Максимум ждать экспорт (1 час) - newdental может обрабатывать 400+ звонков
TRANSCRIBE_MAX_WAIT = 7200  # Максимум ждать транскрибацию (2 часа)
ANALYZE_MAX_WAIT = 7200  # Максимум ждать анализ (2 часа)

# Пауза между операциями для разных клиник
PAUSE_BETWEEN_CLINICS = 10  # секунды

# Директория для логов
LOG_DIR = os.path.join(PROJECT_ROOT, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

# Настройка логирования
log_file = os.path.join(LOG_DIR, f'auto_sync_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


@dataclass
class ClinicResult:
    """Результат обработки клиники"""
    client_id: str
    clinic_name: str
    subdomain: str
    
    # Статусы операций
    sync_success: bool = False
    sync_error: Optional[str] = None
    sync_stats: Dict[str, Any] = field(default_factory=dict)
    
    transcribe_success: bool = False
    transcribe_error: Optional[str] = None
    transcribe_stats: Dict[str, Any] = field(default_factory=dict)
    
    analyze_success: bool = False
    analyze_error: Optional[str] = None
    analyze_stats: Dict[str, Any] = field(default_factory=dict)
    
    recommendations_success: bool = False
    recommendations_error: Optional[str] = None
    recommendations_stats: Dict[str, Any] = field(default_factory=dict)

    monthly_analysis_success: bool = False
    monthly_analysis_error: Optional[str] = None
    monthly_analysis_stats: Dict[str, Any] = field(default_factory=dict)

    # Лимиты
    limits_warning: Optional[str] = None

    def has_errors(self) -> bool:
        return any([self.sync_error, self.transcribe_error, self.analyze_error, self.recommendations_error, self.monthly_analysis_error])
    
    def has_limits_warning(self) -> bool:
        return self.limits_warning is not None


@dataclass  
class SyncReport:
    """Общий отчёт о синхронизации"""
    start_time: datetime
    end_time: Optional[datetime] = None
    date_range: str = ""
    weekly_analysis: bool = False
    monthly_analysis: bool = False
    
    clinic_results: List[ClinicResult] = field(default_factory=list)
    
    # PostgreSQL синхронизация
    postgres_success: bool = False
    postgres_error: Optional[str] = None
    postgres_stats: Dict[str, Any] = field(default_factory=dict)
    
    def total_clinics(self) -> int:
        return len(self.clinic_results)
    
    def success_count(self) -> int:
        return sum(1 for r in self.clinic_results if not r.has_errors())
    
    def error_count(self) -> int:
        return sum(1 for r in self.clinic_results if r.has_errors())
    
    def limits_warnings_count(self) -> int:
        return sum(1 for r in self.clinic_results if r.has_limits_warning())


class APIClient:
    """HTTP клиент для работы с API"""
    
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')
        self._client: Optional[httpx.AsyncClient] = None
    
    async def __aenter__(self):
        headers = {}
        api_key = os.getenv("API_KEY")
        if api_key:
            headers["X-API-Key"] = api_key
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(300.0), headers=headers)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            await self._client.aclose()
    
    async def post(self, endpoint: str, params: Dict = None, json_body: Dict = None, timeout: float = 300) -> Dict:
        """POST запрос"""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        try:
            response = await self._client.post(
                url, 
                params=params, 
                json=json_body or {},
                timeout=timeout
            )
            response.raise_for_status()
            return response.json()
        except httpx.TimeoutException:
            raise Exception(f"Таймаут {timeout}s для {endpoint}")
        except httpx.HTTPStatusError as e:
            error_text = e.response.text[:300] if e.response.text else str(e)
            raise Exception(f"HTTP {e.response.status_code}: {error_text}")
        except Exception as e:
            raise Exception(f"{type(e).__name__}: {str(e)[:200]}")
    
    async def get(self, endpoint: str, params: Dict = None, timeout: float = 60) -> Dict:
        """GET запрос"""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        try:
            response = await self._client.get(url, params=params, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except httpx.TimeoutException:
            raise Exception(f"Таймаут {timeout}s для {endpoint}")
        except httpx.HTTPStatusError as e:
            error_text = e.response.text[:300] if e.response.text else str(e)
            raise Exception(f"HTTP {e.response.status_code}: {error_text}")
        except Exception as e:
            raise Exception(f"{type(e).__name__}: {str(e)[:200]}")
    
    async def wait_for_completion(
        self, 
        status_endpoint: str, 
        params: Dict,
        max_wait: int = 3600,
        poll_interval: int = 10,
        operation_name: str = "операция"
    ) -> Dict:
        """
        Polling статус-эндпоинта до завершения операции.
        
        Возвращает финальный статус или выбрасывает исключение при таймауте.
        """
        start_time = datetime.now()
        last_progress = -1
        
        while True:
            elapsed = (datetime.now() - start_time).total_seconds()
            
            if elapsed > max_wait:
                raise Exception(f"Таймаут ожидания: {max_wait}s")
            
            try:
                status = await self.get(status_endpoint, params=params)
            except Exception as e:
                logger.warning(f"Ошибка проверки статуса {operation_name}: {e}")
                await asyncio.sleep(poll_interval)
                continue
            
            overall_status = status.get("overall_status", "unknown")
            progress = status.get("progress_percentage", 0)
            total = status.get("total_calls", 0)
            breakdown = status.get("status_breakdown", {})
            
            # Логируем прогресс только при изменении
            if progress != last_progress:
                logger.info(
                    f"   {operation_name}: {progress:.0f}% "
                    f"(success={breakdown.get('success', 0)}, "
                    f"processing={breakdown.get('processing', 0)}, "
                    f"pending={breakdown.get('pending', 0)}, "
                    f"failed={breakdown.get('failed', 0)})"
                )
                last_progress = progress
            
            # Проверяем завершение
            if overall_status in ("completed", "partial"):
                return status
            
            # Если нет звонков для обработки
            if total == 0:
                logger.info(f"   {operation_name}: нет звонков для обработки")
                return status
            
            await asyncio.sleep(poll_interval)


async def send_telegram_report(report: SyncReport) -> bool:
    """Отправляет отчёт в Telegram"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_ADMIN_CHAT_ID:
        logger.warning("Telegram не настроен (BOT_TOKEN или TELEGRAM_ADMIN_CHAT_ID не заданы)")
        return False
    
    duration = (report.end_time - report.start_time).total_seconds() if report.end_time else 0
    status_emoji = "✅" if report.error_count() == 0 else "⚠️" if report.error_count() < report.total_clinics() else "❌"
    
    text = f"""
{status_emoji} <b>Отчёт автосинхронизации</b>

📅 <b>Период:</b> {report.date_range}
⏱ <b>Время выполнения:</b> {int(duration // 60)}м {int(duration % 60)}с
{"🔄 <b>Недельный анализ:</b> Да" if report.weekly_analysis else ""}

📊 <b>Статистика:</b>
• Всего клиник: {report.total_clinics()}
• Успешно: {report.success_count()}
• С ошибками: {report.error_count()}
• Предупреждения о лимитах: {report.limits_warnings_count()}
• PostgreSQL: {"✅" if report.postgres_success else "❌"}
"""
    
    # Детали по каждой клинике
    for result in report.clinic_results:
        clinic_status = "✅" if not result.has_errors() else "❌"
        text += f"\n{clinic_status} <b>{result.clinic_name or result.subdomain}</b>"
        
        if result.sync_stats:
            calls = result.sync_stats.get('total_calls', 0)
            text += f"\n   📞 Синхр: {calls} звонков"
        
        if result.transcribe_stats:
            success = result.transcribe_stats.get('success', 0)
            failed = result.transcribe_stats.get('failed', 0)
            text += f"\n   🎤 Транскр: {success} ✓, {failed} ✗"
            
        if result.analyze_stats:
            success = result.analyze_stats.get('success', 0)
            failed = result.analyze_stats.get('failed', 0)
            text += f"\n   🧠 Анализ: {success} ✓, {failed} ✗"
        
        if result.recommendations_stats and report.weekly_analysis:
            text += f"\n   📋 Рекомендации: ✅"
        
        if result.limits_warning:
            text += f"\n   ⚠️ {result.limits_warning}"
        
        if result.has_errors():
            errors = []
            if result.sync_error:
                errors.append(f"Синхр: {result.sync_error[:50]}")
            if result.transcribe_error:
                errors.append(f"Транскр: {result.transcribe_error[:50]}")
            if result.analyze_error:
                errors.append(f"Анализ: {result.analyze_error[:50]}")
            if result.recommendations_error:
                errors.append(f"Рекомендации: {result.recommendations_error[:50]}")
            text += f"\n   ❌ {'; '.join(errors)}"
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": TELEGRAM_ADMIN_CHAT_ID,
                    "text": text,
                    "parse_mode": "HTML"
                }
            )
            if response.status_code == 200:
                logger.info("Отчёт отправлен в Telegram")
                return True
            else:
                logger.error(f"Ошибка отправки в Telegram: {response.text}")
                return False
    except Exception as e:
        logger.error(f"Ошибка отправки в Telegram: {e}")
        return False


async def get_active_clinics() -> List[Dict[str, Any]]:
    """Получает список всех клиник из MongoDB"""
    client = AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]
    
    # Клиники которые должны обрабатываться ПЕРВЫМИ (для тестирования)
    PRIORITY_CLINICS = [
        "be735efe-2f45-4262-9df1-289db57a71b5",  # dentalfamily21
        "4cd12564-1e62-4ac2-8189-5cd85d5ef2ab",  # bellamus8
    ]
    
    try:
        clinics = await db.clinics.find(
            {},
            {"client_id": 1, "clinic_name": 1, "amocrm_subdomain": 1, "_id": 0}
        ).to_list(length=100)
        
        logger.info(f"Найдено {len(clinics)} клиник в базе")
        
        # Сортируем: приоритетные клиники первыми
        def sort_key(clinic):
            cid = clinic.get("client_id", "")
            if cid in PRIORITY_CLINICS:
                return (0, PRIORITY_CLINICS.index(cid))  # Приоритетные первыми, в заданном порядке
            return (1, cid)  # Остальные после, по алфавиту
        
        clinics.sort(key=sort_key)
        
        # Логируем порядок обработки
        priority_names = [c.get("amocrm_subdomain", c.get("client_id", "")[:8]) 
                         for c in clinics if c.get("client_id") in PRIORITY_CLINICS]
        if priority_names:
            logger.info(f"🔝 Приоритетные клиники (первыми): {', '.join(priority_names)}")
        
        return clinics
    finally:
        client.close()


async def check_clinic_limits(client_id: str) -> Optional[str]:
    """Проверяет лимиты клиники (ElevenLabs минуты)"""
    mongo_client = AsyncIOMotorClient(MONGO_URI)
    db = mongo_client[DB_NAME]
    
    try:
        clinic = await db.clinics.find_one(
            {"client_id": client_id},
            {"elevenlabs_limits": 1, "clinic_name": 1}
        )
        
        if not clinic or "elevenlabs_limits" not in clinic:
            return None
        
        limits = clinic["elevenlabs_limits"]
        remaining = limits.get("remaining_minutes", 0)
        total = limits.get("total_minutes", 0)
        
        if total > 0 and remaining < total * 0.2:
            return f"Осталось {remaining:.0f}/{total:.0f} минут ({remaining/total*100:.0f}%)"
        
        return None
    finally:
        mongo_client.close()


async def sync_clinic(
    api: APIClient,
    client_id: str,
    start_date: str,
    end_date: str,
    run_weekly_analysis: bool = False,
    run_monthly_analysis: bool = False
) -> ClinicResult:
    """Синхронизирует одну клинику с полным ожиданием завершения операций"""
    
    # Получаем информацию о клинике
    mongo_client = AsyncIOMotorClient(MONGO_URI)
    db = mongo_client[DB_NAME]
    clinic_doc = await db.clinics.find_one(
        {"client_id": client_id},
        {"clinic_name": 1, "amocrm_subdomain": 1}
    )
    mongo_client.close()
    
    result = ClinicResult(
        client_id=client_id,
        clinic_name=clinic_doc.get("clinic_name", "") if clinic_doc else "",
        subdomain=clinic_doc.get("amocrm_subdomain", "") if clinic_doc else ""
    )
    
    logger.info(f"\n{'='*60}")
    logger.info(f"🏥 Клиника: {result.clinic_name or result.subdomain} ({client_id[:8]}...)")
    logger.info(f"{'='*60}")
    
    # 1. Проверяем лимиты
    result.limits_warning = await check_clinic_limits(client_id)
    if result.limits_warning:
        logger.warning(f"⚠️ Лимиты: {result.limits_warning}")
    
    # ========== 2. СИНХРОНИЗАЦИЯ ЗВОНКОВ (асинхронная + polling) ==========
    logger.info("📥 [1/4] Синхронизация звонков из AmoCRM...")
    try:
        # Запускаем экспорт (это добавляет задачи в background и возвращает tasks_queued)
        sync_response = await api.post(
            '/calls-events/export',
            json_body={
                "client_id": client_id,
                "start_date": start_date,
                "end_date": end_date
            },
            timeout=SYNC_TIMEOUT
        )
        
        tasks_queued = sync_response.get("tasks_queued", 0)
        total_found = sync_response.get("total_found", 0)
        logger.info(f"   Найдено событий: {total_found}, поставлено задач: {tasks_queued}")
        
        if tasks_queued > 0 or total_found > 0:
            # Ждём завершения экспорта через polling /export-results
            logger.info(f"   Ожидание завершения экспорта (max {EXPORT_MAX_WAIT}с)...")
            
            export_start = datetime.now()
            last_status_logged = None
            
            while (datetime.now() - export_start).total_seconds() < EXPORT_MAX_WAIT:
                await asyncio.sleep(POLL_INTERVAL)
                
                try:
                    export_result = await api.get(
                        '/calls-events/export-results',
                        params={
                            "client_id": client_id,
                            "start_date": start_date,
                            "end_date": end_date
                        }
                    )
                    
                    if export_result.get("success"):
                        stats = export_result.get("statistics", {})
                        saved_count = stats.get("saved_to_db", 0)
                        total_found_stats = stats.get("total_found", 0)
                        filtered_count = stats.get("filtered_duplicates", 0) + stats.get("filtered_short_calls", 0) + stats.get("filtered_zero_duration", 0)
                        
                        result.sync_success = True
                        result.sync_stats = {
                            "total_found": total_found_stats,
                            "saved": saved_count,
                            "filtered": filtered_count
                        }
                        logger.info(f"✅ Синхронизация завершена: найдено {total_found_stats}, сохранено {saved_count}, отфильтровано {filtered_count}")
                        break
                    else:
                        # Статистика есть но success=false - логируем и продолжаем
                        status_msg = export_result.get("message", "неизвестный статус")
                        if status_msg != last_status_logged:
                            logger.info(f"   Статус экспорта: {status_msg}")
                            last_status_logged = status_msg
                        
                except Exception as e:
                    error_str = str(e)
                    # 404 означает что статистика ещё не сохранена - это нормально, продолжаем ждать
                    if "404" in error_str:
                        if last_status_logged != "waiting":
                            logger.info(f"   Ожидание сохранения статистики...")
                            last_status_logged = "waiting"
                    else:
                        logger.warning(f"   Ошибка проверки статуса экспорта: {e}")
            
            if not result.sync_success:
                raise Exception(f"Таймаут ожидания экспорта ({EXPORT_MAX_WAIT}с)")
        else:
            # Нет задач для выполнения
            result.sync_success = True
            result.sync_stats = {"total_found": 0, "saved": 0, "message": "Нет звонков для экспорта"}
            logger.info(f"✅ Синхронизация: нет звонков для экспорта")
            
    except Exception as e:
        result.sync_error = str(e)
        logger.error(f"❌ Синхронизация: {e}")
        # Если синхронизация не удалась, нет смысла продолжать
        return result
    
    # Небольшая пауза после синхронизации
    await asyncio.sleep(2)
    
    # ========== 3. ТРАНСКРИБАЦИЯ (асинхронная + polling) ==========
    logger.info("🎤 [2/4] Запуск транскрибации звонков...")
    try:
        # Запускаем транскрибацию (это добавляет задачи в background)
        transcribe_response = await api.post(
            '/calls/transcribe-by-date-range',
            params={
                "start_date_str": start_date,
                "end_date_str": end_date,
                "client_id": client_id
            },
            timeout=TRANSCRIBE_TRIGGER_TIMEOUT
        )
        
        tasks_queued = transcribe_response.get("tasks_queued", 0)
        logger.info(f"   Поставлено задач на транскрибацию: {tasks_queued}")
        
        if tasks_queued > 0:
            # Ждём завершения транскрибации через polling
            logger.info("   Ожидание завершения транскрибации...")
            
            final_status = await api.wait_for_completion(
                status_endpoint='/calls/transcribe-by-date-range-status',
                params={
                    "start_date_str": start_date,
                    "end_date_str": end_date,
                    "client_id": client_id
                },
                max_wait=TRANSCRIBE_MAX_WAIT,
                poll_interval=POLL_INTERVAL,
                operation_name="Транскрибация"
            )
            
            breakdown = final_status.get("status_breakdown", {})
            result.transcribe_success = True
            result.transcribe_stats = {
                "total": final_status.get("total_calls", 0),
                "success": breakdown.get("success", 0),
                "failed": breakdown.get("failed", 0),
                "pending": breakdown.get("pending", 0)
            }
            logger.info(f"✅ Транскрибация завершена: {result.transcribe_stats}")
        else:
            result.transcribe_success = True
            result.transcribe_stats = {"total": 0, "success": 0, "message": "Нет звонков для транскрибации"}
            logger.info("✅ Транскрибация: нет новых звонков")
            
    except Exception as e:
        result.transcribe_error = str(e)
        logger.error(f"❌ Транскрибация: {e}")
    
    # Пауза перед анализом
    await asyncio.sleep(3)
    
    # ========== 4. АНАЛИЗ ЗВОНКОВ (асинхронный + polling) ==========
    logger.info("🧠 [3/4] Запуск анализа звонков...")
    try:
        # Запускаем анализ
        analyze_response = await api.post(
            '/analyze-by-date-range',
            params={
                "start_date_str": start_date,
                "end_date_str": end_date,
                "client_id": client_id,
                "skip_processed": "true"
            },
            timeout=ANALYZE_TRIGGER_TIMEOUT
        )
        
        tasks_queued = analyze_response.get("tasks_queued", 0)
        logger.info(f"   Поставлено задач на анализ: {tasks_queued}")
        
        if tasks_queued > 0:
            # Ждём завершения анализа через polling
            logger.info("   Ожидание завершения анализа...")
            
            final_status = await api.wait_for_completion(
                status_endpoint='/analyze-by-date-range-status',
                params={
                    "start_date_str": start_date,
                    "end_date_str": end_date,
                    "client_id": client_id
                },
                max_wait=ANALYZE_MAX_WAIT,
                poll_interval=POLL_INTERVAL,
                operation_name="Анализ"
            )
            
            breakdown = final_status.get("status_breakdown", {})
            result.analyze_success = True
            result.analyze_stats = {
                "total": final_status.get("total_calls", 0),
                "success": breakdown.get("success", 0),
                "failed": breakdown.get("failed", 0),
                "pending": breakdown.get("pending", 0)
            }
            logger.info(f"✅ Анализ завершён: {result.analyze_stats}")
        else:
            result.analyze_success = True
            result.analyze_stats = {"total": 0, "success": 0, "message": "Нет звонков для анализа"}
            logger.info("✅ Анализ: нет новых звонков")
            
    except Exception as e:
        result.analyze_error = str(e)
        logger.error(f"❌ Анализ: {e}")
    
    # ========== 5. НЕДЕЛЬНЫЙ АНАЛИЗ РЕКОМЕНДАЦИЙ ==========
    if run_weekly_analysis:
        await asyncio.sleep(2)
        logger.info("📋 [4/4] Недельный анализ рекомендаций...")
        try:
            # Для недельного анализа берём последнюю полную неделю (пн-вс)
            # ВАЖНО: используем московское время, т.к. cron запускается в 01:00 MSK (22:00 UTC)
            MSK = ZoneInfo("Europe/Moscow")
            today = datetime.now(MSK)
            days_since_monday = today.weekday()
            last_monday = today - timedelta(days=days_since_monday + 7)
            last_sunday = last_monday + timedelta(days=6)
            
            week_start = last_monday.strftime("%d.%m.%Y")
            week_end = last_sunday.strftime("%d.%m.%Y")
            
            logger.info(f"   Период: {week_start} - {week_end}")
            
            recommendations_response = await api.post(
                '/recommendations/analyze-by-date-range',
                params={
                    "start_date_str": week_start,
                    "end_date_str": week_end,
                    "client_id": client_id,
                    "force_refresh": "false"
                },
                timeout=RECOMMENDATIONS_TIMEOUT
            )
            result.recommendations_success = True
            result.recommendations_stats = {
                "period": f"{week_start} - {week_end}",
                "status": recommendations_response.get("status", "completed")
            }
            logger.info(f"✅ Рекомендации: {result.recommendations_stats}")
        except Exception as e:
            result.recommendations_error = str(e)
            logger.error(f"❌ Рекомендации: {e}")
    else:
        logger.info("⏭️ [4/4] Недельный анализ рекомендаций: пропущен")

    # ========== 6. МЕСЯЧНЫЙ АНАЛИЗ РЕКОМЕНДАЦИЙ ==========
    if run_monthly_analysis:
        await asyncio.sleep(2)
        logger.info("📋 [5/5] Месячный анализ рекомендаций...")
        try:
            MSK = ZoneInfo("Europe/Moscow")
            now_msk = datetime.now(MSK)
            # Анализируем прошлый месяц
            if now_msk.month == 1:
                prev_year = now_msk.year - 1
                prev_month = 12
            else:
                prev_year = now_msk.year
                prev_month = now_msk.month - 1

            logger.info(f"   Период: {prev_month:02d}/{prev_year}")

            monthly_response = await api.post(
                '/recommendations/analyze-monthly',
                params={
                    "client_id": client_id,
                    "year": prev_year,
                    "month": prev_month,
                    "force_refresh": "false"
                },
                timeout=RECOMMENDATIONS_TIMEOUT
            )
            result.monthly_analysis_success = True
            result.monthly_analysis_stats = {
                "period": f"{prev_month:02d}/{prev_year}",
                "status": monthly_response.get("status", "completed")
            }
            logger.info(f"✅ Месячный анализ: {result.monthly_analysis_stats}")
        except Exception as e:
            result.monthly_analysis_error = str(e)
            logger.error(f"❌ Месячный анализ: {e}")
    else:
        logger.info("⏭️ [5/5] Месячный анализ рекомендаций: пропущен")

    return result


async def run_sync(
    start_date: str,
    end_date: str,
    client_id: Optional[str] = None,
    weekly_analysis: bool = False,
    monthly_analysis: bool = False
) -> SyncReport:
    """Запускает синхронизацию для всех или одной клиники"""
    
    report = SyncReport(
        start_time=datetime.now(),
        date_range=f"{start_date} - {end_date}" if start_date != end_date else start_date,
        weekly_analysis=weekly_analysis,
        monthly_analysis=monthly_analysis
    )
    
    logger.info(f"\n{'='*60}")
    logger.info(f"🚀 ЗАПУСК АВТОСИНХРОНИЗАЦИИ")
    logger.info(f"{'='*60}")
    logger.info(f"📅 Период: {report.date_range}")
    logger.info(f"📋 Недельный анализ: {'Да' if weekly_analysis else 'Нет'}")
    logger.info(f"📋 Месячный анализ: {'Да' if monthly_analysis else 'Нет'}")
    logger.info(f"🌐 API: {BASE_URL}")
    logger.info(f"⏱ Polling интервал: {POLL_INTERVAL}с")
    logger.info(f"⏱ Макс. ожидание транскрибации: {TRANSCRIBE_MAX_WAIT}с")
    logger.info(f"⏱ Макс. ожидание анализа: {ANALYZE_MAX_WAIT}с")
    
    # Получаем список клиник
    if client_id:
        clinics = [{"client_id": client_id}]
        logger.info(f"🏥 Клиника: {client_id}")
    else:
        clinics = await get_active_clinics()
        logger.info(f"🏥 Клиник для обработки: {len(clinics)}")
    
    # Используем один HTTP клиент для всех запросов
    async with APIClient(BASE_URL) as api:
        # Обрабатываем каждую клинику ПОСЛЕДОВАТЕЛЬНО с паузами
        for i, clinic in enumerate(clinics, 1):
            cid = clinic["client_id"]
            logger.info(f"\n{'#'*60}")
            logger.info(f"# [{i}/{len(clinics)}] Начинаем обработку клиники")
            logger.info(f"{'#'*60}")
            
            try:
                result = await sync_clinic(
                    api=api,
                    client_id=cid,
                    start_date=start_date,
                    end_date=end_date,
                    run_weekly_analysis=weekly_analysis,
                    run_monthly_analysis=monthly_analysis
                )
                report.clinic_results.append(result)
                
                # Статус по клинике
                if result.has_errors():
                    logger.warning(f"⚠️ Клиника {result.clinic_name or cid[:8]} обработана с ошибками")
                else:
                    logger.info(f"✅ Клиника {result.clinic_name or cid[:8]} обработана успешно")
                    
            except Exception as e:
                logger.error(f"💥 Критическая ошибка для клиники {cid}: {e}")
                report.clinic_results.append(ClinicResult(
                    client_id=cid,
                    clinic_name=clinic.get("clinic_name", ""),
                    subdomain=clinic.get("amocrm_subdomain", ""),
                    sync_error=f"Критическая ошибка: {str(e)}"
                ))
            
            # Пауза между клиниками (кроме последней)
            if i < len(clinics):
                logger.info(f"⏳ Пауза {PAUSE_BETWEEN_CLINICS}с перед следующей клиникой...")
                await asyncio.sleep(PAUSE_BETWEEN_CLINICS)
        
        # ========== СИНХРОНИЗАЦИЯ PostgreSQL ==========
        logger.info(f"\n{'='*60}")
        logger.info("🐘 Синхронизация PostgreSQL (для DataLens)...")
        try:
            postgres_response = await api.post(
                '/postgres/sync-now',
                timeout=SYNC_TIMEOUT
            )
            report.postgres_success = True
            report.postgres_stats = {
                "status": postgres_response.get("status", "completed"),
                "message": postgres_response.get("message", "")
            }
            logger.info(f"✅ PostgreSQL: {report.postgres_stats}")
        except Exception as e:
            report.postgres_error = str(e)
            logger.error(f"❌ PostgreSQL: {e}")
    
    report.end_time = datetime.now()
    
    # ========== ИТОГОВАЯ СТАТИСТИКА ==========
    duration = (report.end_time - report.start_time).total_seconds()
    logger.info(f"\n{'='*60}")
    logger.info(f"📊 ИТОГИ СИНХРОНИЗАЦИИ")
    logger.info(f"{'='*60}")
    logger.info(f"✅ Успешно: {report.success_count()}/{report.total_clinics()} клиник")
    logger.info(f"❌ С ошибками: {report.error_count()}/{report.total_clinics()} клиник")
    logger.info(f"⚠️ Предупреждения о лимитах: {report.limits_warnings_count()}")
    logger.info(f"🐘 PostgreSQL: {'✅' if report.postgres_success else '❌ ' + (report.postgres_error or 'ошибка')}")
    logger.info(f"⏱ Общее время выполнения: {int(duration // 60)}м {int(duration % 60)}с")
    
    # Детальная статистика по клиникам
    logger.info(f"\n📋 Детали по клиникам:")
    for r in report.clinic_results:
        status = "✅" if not r.has_errors() else "❌"
        sync_calls = r.sync_stats.get('total_calls', 0)
        trans_success = r.transcribe_stats.get('success', 0)
        analyze_success = r.analyze_stats.get('success', 0)
        logger.info(
            f"   {status} {r.clinic_name or r.subdomain}: "
            f"sync={sync_calls}, transcribe={trans_success}, analyze={analyze_success}"
        )
    
    # Отправляем отчёт в Telegram
    await send_telegram_report(report)
    
    # Сохраняем отчёт в JSON
    report_file = os.path.join(LOG_DIR, f'report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json')
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump({
            "start_time": report.start_time.isoformat(),
            "end_time": report.end_time.isoformat(),
            "duration_seconds": duration,
            "date_range": report.date_range,
            "weekly_analysis": report.weekly_analysis,
            "monthly_analysis": report.monthly_analysis,
            "total_clinics": report.total_clinics(),
            "success_count": report.success_count(),
            "error_count": report.error_count(),
            "postgres_success": report.postgres_success,
            "postgres_error": report.postgres_error,
            "postgres_stats": report.postgres_stats,
            "clinics": [
                {
                    "client_id": r.client_id,
                    "clinic_name": r.clinic_name,
                    "subdomain": r.subdomain,
                    "sync_success": r.sync_success,
                    "sync_error": r.sync_error,
                    "sync_stats": r.sync_stats,
                    "transcribe_success": r.transcribe_success,
                    "transcribe_error": r.transcribe_error,
                    "transcribe_stats": r.transcribe_stats,
                    "analyze_success": r.analyze_success,
                    "analyze_error": r.analyze_error,
                    "analyze_stats": r.analyze_stats,
                    "recommendations_success": r.recommendations_success,
                    "recommendations_error": r.recommendations_error,
                    "recommendations_stats": r.recommendations_stats,
                    "monthly_analysis_success": r.monthly_analysis_success,
                    "monthly_analysis_error": r.monthly_analysis_error,
                    "monthly_analysis_stats": r.monthly_analysis_stats,
                    "limits_warning": r.limits_warning
                }
                for r in report.clinic_results
            ]
        }, f, ensure_ascii=False, indent=2)
    logger.info(f"📄 Отчёт сохранён: {report_file}")
    
    return report


def main():
    parser = argparse.ArgumentParser(
        description="Автоматическая синхронизация звонков для всех клиник",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  # Синхронизация за вчера (по умолчанию)
  python auto_sync_all_clinics.py
  
  # За конкретную дату
  python auto_sync_all_clinics.py --date 02.12.2025
  
  # За диапазон дат
  python auto_sync_all_clinics.py --start-date 01.12.2025 --end-date 02.12.2025
  
  # С недельным анализом рекомендаций
  python auto_sync_all_clinics.py --weekly-analysis

  # С месячным анализом рекомендаций (за прошлый месяц)
  python auto_sync_all_clinics.py --monthly-analysis

  # Только для одной клиники
  python auto_sync_all_clinics.py --client-id 4c640248-8904-412e-ae85-14dda10edd1b
        """
    )
    
    parser.add_argument('--date', type=str, help='Дата в формате DD.MM.YYYY')
    parser.add_argument('--start-date', type=str, help='Начало диапазона DD.MM.YYYY')
    parser.add_argument('--end-date', type=str, help='Конец диапазона DD.MM.YYYY')
    parser.add_argument('--client-id', type=str, help='ID конкретной клиники')
    parser.add_argument('--weekly-analysis', action='store_true', help='Запустить недельный анализ рекомендаций')
    parser.add_argument('--monthly-analysis', action='store_true', help='Запустить месячный анализ рекомендаций (за прошлый месяц)')
    
    args = parser.parse_args()
    
    # Московский часовой пояс
    MSK = ZoneInfo("Europe/Moscow")
    
    # Определяем даты
    if args.date:
        start_date = end_date = args.date
    elif args.start_date and args.end_date:
        start_date = args.start_date
        end_date = args.end_date
    else:
        # По умолчанию - СЕГОДНЯШНИЙ день по МОСКОВСКОМУ времени
        now_msk = datetime.now(MSK)
        start_date = end_date = now_msk.strftime("%d.%m.%Y")
    
    logger.info(f"📆 Дата запуска: {datetime.now(MSK).strftime('%Y-%m-%d %H:%M:%S %Z')}")
    logger.info(f"📆 Период синхронизации: {start_date} - {end_date}")
    
    # Запускаем
    try:
        report = asyncio.run(run_sync(
            start_date=start_date,
            end_date=end_date,
            client_id=args.client_id,
            weekly_analysis=args.weekly_analysis,
            monthly_analysis=args.monthly_analysis
        ))
        
        # Код выхода: 0 если всё успешно, 1 если были ошибки
        exit_code = 0 if report.error_count() == 0 else 1
        logger.info(f"\n🏁 Завершение с кодом: {exit_code}")
        sys.exit(exit_code)
        
    except KeyboardInterrupt:
        logger.info("\n⛔ Прервано пользователем (Ctrl+C)")
        sys.exit(130)
    except Exception as e:
        logger.critical(f"\n💥 Критическая ошибка: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
