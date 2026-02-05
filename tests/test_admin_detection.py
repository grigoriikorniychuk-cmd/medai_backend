"""
Тест определения администратора из транскрипций.

Использует РЕАЛЬНЫЕ транскрипции с продакшена (28 января 2026) и проверяет:
1. Валидацию: AI не должен возвращать имена НЕ из графика
2. Полноту: должно быть "Имя Фамилия", а не просто "Имя"
3. Уменьшительные имена: "Юля" → должно либо сопоставиться с "Юлия", либо null
4. Имена не из графика: "Валерия", "Марина", "Ира" → null

Запуск:
    pytest tests/test_admin_detection.py -v -s

    # Только юнит-тесты (без вызова OpenAI):
    pytest tests/test_admin_detection.py -v -s -k "unit"

    # Только интеграционные (с вызовом OpenAI):
    pytest tests/test_admin_detection.py -v -s -k "integration"
"""

import pytest
import pytest_asyncio
import json
import re
from unittest.mock import AsyncMock, patch, MagicMock

# Включаем auto mode для pytest-asyncio
pytestmark = pytest.mark.asyncio(loop_scope="function")

from app.services.admin_detection_service import (
    normalize_admin_name,
    _determine_by_ai_schedule,
)
from app.services.call_analysis_service_new import CallAnalysisService


# =============================================================================
# РЕАЛЬНЫЕ ДАННЫЕ С ПРОДАКШЕНА
# =============================================================================

# График клиники "newdental" (9476ab76) на 28 января 2026
NEWDENTAL_SCHEDULE = [
    {"first_name": "Юлия", "last_name": "Черкасова"},
    {"first_name": "Юлия", "last_name": "Гаршина"},
    {"first_name": "Евгения", "last_name": "Слугина"},
    {"first_name": "Анастасия", "last_name": "Саркисова"},
]

# График клиники "stomdv" (3306c1e4) на 28 января 2026
STOMDV_SCHEDULE = [
    {"first_name": "Милана", "last_name": "Гриценко"},
    {"first_name": "Алина", "last_name": "Клюянова"},
    {"first_name": "Мария", "last_name": "Спирина"},
    {"first_name": "Дарья", "last_name": "Крыжановская"},
    {"first_name": "Любовь", "last_name": "Потекина"},
]

# --- Транскрипции с КОСЯКАМИ (реальные с продакшена) ---

# БАГ: Записано как "Валерия" - имени нет в графике!
# Админ представляется как Валерия, но её нет в расписании → должно быть "Неизвестный администратор"
TRANSCRIPTION_VALERIYA = """Дата и время: 2026-01-28 18:21:18
Телефон: +79192530203, Статус: Разговор состоялся
Клиент: Любовь Валерьевна
Файл: lead_55123456_note_479758415.mp3
Длительность: 2:02

[00:01] Менеджер: Стоматологическая клиника Нью Дент, администратор Валерия, здравствуйте.
[00:05] Клиент (Любовь Валерьевна): Здравствуйте, я по поводу записи.
[00:08] Менеджер: Да, слушаю вас.
[00:10] Клиент (Любовь Валерьевна): У меня герпес высыпал, хотела перенести.
[00:15] Менеджер: Да, конечно. Давайте перенесем на другую дату. Вам удобно седьмого февраля в четырнадцать тридцать?
[00:25] Клиент (Любовь Валерьевна): Да, давайте.
[00:27] Менеджер: Записала. До свидания!"""

# БАГ: Записано как "Юлия" (без фамилии) - а в графике ДВЕ Юлии!
# Должно быть либо "Юлия Черкасова" / "Юлия Гаршина", либо "Неизвестный администратор"
TRANSCRIPTION_YULIYA_NO_LASTNAME = """Дата и время: 2026-01-28 18:20:42
Телефон: +79803544815, Статус: Разговор состоялся
Клиент: Наталья Вячеславовна Попова
Файл: lead_55367335_note_479759693.mp3
Длительность: 0:23

[00:02] Клиент (Наталья Вячеславовна Попова): Алло.
[00:02] Менеджер: Здравствуйте! Стоматологическая клиника, администратор Юля. Наблюдаю, что был пропущенный вызов от вас.
[00:09] Клиент (Наталья Вячеславовна Попова): Нет, нет, это случайно нажала.
[00:12] Менеджер: Угу. Хорошо, я вас поняла.
[00:14] Клиент (Наталья Вячеславовна Попова): Хорошо, спасибо.
[00:15] Менеджер: До свидания."""

# БАГ: Записано как "Юля" (уменьшительное) - нет точного совпадения в графике
TRANSCRIPTION_YULYA_DIMINUTIVE = """Дата и время: 2026-01-28 18:22:02
Телефон: +79005945880, Статус: Разговор состоялся
Клиент: Герецкий Кирилл Александрович
Файл: lead_55234567_note_479757317.mp3
Длительность: 6:07

[00:01] Менеджер: Клиника Нью Дент, Юля, здравствуйте!
[00:04] Клиент (Герецкий Кирилл Александрович): Здравствуйте, хотел записаться на удаление зуба мудрости.
[00:10] Менеджер: Консультация у нас бесплатная. Удаление от пяти тысяч рублей.
[00:20] Клиент (Герецкий Кирилл Александрович): Хорошо, на завтра можно?
[00:23] Менеджер: Да, завтра в четырнадцать тридцать к Бахтиярову Владиславу Сергеевичу. Улица Петра Смородина, дом пять А.
[00:35] Клиент (Герецкий Кирилл Александрович): Записал, спасибо.
[00:37] Менеджер: До свидания!"""

# БАГ: Записано как "Марина" - нет в графике!
TRANSCRIPTION_MARINA = """Дата и время: 2026-01-28 18:28:30
Телефон: +79803572502, Статус: Разговор состоялся
Клиент: Мария Николаевна Косилова
Файл: lead_35639621_note_479747893.mp3
Длительность: 0:48

[00:00] Менеджер: Стоматологическая клиника Нью Дент, администратор Марина, здравствуйте.
[00:05] Клиент (Мария Николаевна Косилова): Здравствуйте. Вы сегодня звонили по Косиловой Марии Николаевне и не дозвонились.
[00:15] Клиент (Мария Николаевна Косилова): Написали о переносе записи с третьего февраля.
[00:19] Менеджер: Сейчас минуту, уточню. Вам написал куратор клиники.
[00:29] Менеджер: Давайте я попрошу куратора связаться с вами напрямую.
[00:42] Клиент (Мария Николаевна Косилова): Да, хорошо.
[00:42] Менеджер: Сейчас куратор с вами свяжется. Спасибо.
[00:45] Клиент (Мария Николаевна Косилова): Хорошо, до свидания."""

# БАГ: Записано как "Наталья" - нет в графике!
TRANSCRIPTION_NATALYA = """Дата и время: 2026-01-28 18:32:57
Телефон: +79046816190, Статус: Разговор состоялся
Клиент: Анастасия Ермакова
Файл: lead_55345678_note_479743895.mp3
Длительность: 0:21

[00:01] Менеджер: Клиника Нью Дент, Наталья, здравствуйте!
[00:04] Клиент (Анастасия Ермакова): Здравствуйте, можно перезвонить через час?
[00:08] Менеджер: Да, конечно, перезвоним.
[00:12] Клиент (Анастасия Ермакова): Спасибо.
[00:14] Менеджер: До свидания."""

# БАГ: Записано как "Ира" - нет в графике!
TRANSCRIPTION_IRA = """Дата и время: 2026-01-28 18:34:30
Телефон: +79158575450, Статус: Разговор состоялся
Клиент: Евгений Ковырялов
Файл: lead_55456789_note_479737739.mp3
Длительность: 0:42

[00:01] Менеджер: Клиника Нью Дент, администратор Ира, здравствуйте!
[00:05] Менеджер: Звоню подтвердить запись. Завтра записаны к нам на прием в десять тридцать.
[00:15] Клиент (Евгений Ковырялов): Да, подтверждаю.
[00:18] Менеджер: Адрес: Петра Смородина, дом пять А.
[00:25] Клиент (Евгений Ковырялов): Хорошо, спасибо.
[00:28] Менеджер: До свидания!"""

# БАГ: Записано как "Светлана" в stomdv - нет в графике!
# Причём "Светлана" - это и имя КЛИЕНТА тоже
TRANSCRIPTION_SVETLANA = """Дата и время: 2026-01-28 17:30:21
Телефон: +79214942728, Статус: Разговор состоялся
Клиент: Неизвестный контакт
Файл: lead_47583011_note_290198451.mp3
Длительность: 0:41

[00:00] Клиент (Неизвестный контакт): Алло!
[00:02] Менеджер: Алло, здравствуйте, это Светлана, это Стоматология для всех. Ранее с вами созванивались насчет чистки ребенку.
[00:11] Клиент (Неизвестный контакт): Угу!
[00:11] Менеджер: Хотели бы уточнить, готовы ли сейчас записаться к нашим детским специалистам?
[00:20] Клиент (Неизвестный контакт): Нет, мы пока не готовы, мы не в городе.
[00:24] Менеджер: Скажите, с вами тогда связаться в удобное вам время?
[00:31] Клиент (Неизвестный контакт): Да, я сама свяжусь, как мы только приедем.
[00:34] Менеджер: Хорошо, я вас поняла тогда, Светлана. Будем ждать вашего звонка. До свидания."""

# --- КОРРЕКТНЫЕ транскрипции (для контроля) ---

# Правильно: Евгения → Евгения Слугина
TRANSCRIPTION_EVGENIYA_OK = """Дата и время: 2026-01-28 18:24:20
Телефон: +79517913355, Статус: Разговор состоялся
Клиент: Владислав Дмитриевич Медведев
Файл: lead_55567890_note_479755151.mp3
Длительность: 0:45

[00:01] Менеджер: Клиника Нью Дент, Евгения, здравствуйте!
[00:04] Клиент (Владислав Дмитриевич Медведев): Здравствуйте, по поводу записи на консультацию.
[00:10] Менеджер: Да, слушаю. Вы хотели прийти на осмотр?
[00:15] Клиент (Владислав Дмитриевич Медведев): Да, но пока не могу подстроить график. Через две недели перезвоню.
[00:25] Менеджер: Хорошо, перезвоним через две недели. Всего доброго!"""

# Транскрипция БЕЗ имени администратора → должен быть "Неизвестный администратор"
TRANSCRIPTION_NO_NAME = """Дата и время: 2026-01-28 18:30:00
Телефон: +79001234567, Статус: Разговор состоялся
Клиент: Иванов Иван
Файл: lead_55678901_note_479750000.mp3
Длительность: 0:15

[00:01] Менеджер: Стоматологическая клиника, здравствуйте!
[00:04] Клиент (Иванов Иван): Здравствуйте, а вы работаете сегодня?
[00:07] Менеджер: Да, работаем до двадцати ноль ноль.
[00:10] Клиент (Иванов Иван): Спасибо.
[00:12] Менеджер: До свидания."""


# =============================================================================
# ЮНИТ-ТЕСТЫ: Проверка валидации (без вызова OpenAI)
# =============================================================================

class TestNormalizeAdminName:
    """Тест нормализации имён."""

    def test_unit_full_name(self):
        assert normalize_admin_name("Юлия", "Черкасова") == "Юлия Черкасова"

    def test_unit_only_first_name(self):
        """Если нет фамилии, возвращает только имя — это потенциальный баг."""
        result = normalize_admin_name("Юлия", "")
        assert result == "Юлия"  # Текущее поведение (возможно некорректное)

    def test_unit_empty_returns_unknown(self):
        assert normalize_admin_name("", "") == "Неизвестный администратор"

    def test_unit_strips_spaces(self):
        assert normalize_admin_name("  Юлия ", "  Черкасова  ") == "Юлия Черкасова"

    def test_unit_none_last_name(self):
        result = normalize_admin_name("Юлия", None)
        assert result == "Юлия"


class TestExtractAdministratorNameValidation:
    """
    Тестирует валидацию в extract_administrator_name.
    Мокаем LLM, проверяем что валидация отрабатывает.
    """

    @pytest.fixture
    def service(self):
        """Создаёт CallAnalysisService с замоканным LLM."""
        with patch('app.services.call_analysis_service_new.get_langchain_token') as mock_llm:
            mock_llm.return_value = MagicMock()
            svc = CallAnalysisService()
            return svc

    @pytest.mark.asyncio
    async def test_unit_name_not_in_schedule_rejected(self, service):
        """AI вернул имя не из графика → должно быть null."""
        mock_response = MagicMock()
        mock_response.content = json.dumps({
            "first_name": "Валерия",
            "last_name": None,
            "confidence": 0.9
        })
        service.llm.ainvoke = AsyncMock(return_value=mock_response)

        result = await service.extract_administrator_name(
            transcription_text=TRANSCRIPTION_VALERIYA,
            administrators_list=NEWDENTAL_SCHEDULE,
        )
        assert result["first_name"] is None, (
            f"Имя 'Валерия' НЕТ в графике, но прошло валидацию! result={result}"
        )

    @pytest.mark.asyncio
    async def test_unit_diminutive_name_rejected(self, service):
        """AI вернул уменьшительное 'Юля' вместо 'Юлия' → должно быть null."""
        mock_response = MagicMock()
        mock_response.content = json.dumps({
            "first_name": "Юля",
            "last_name": None,
            "confidence": 0.8
        })
        service.llm.ainvoke = AsyncMock(return_value=mock_response)

        result = await service.extract_administrator_name(
            transcription_text=TRANSCRIPTION_YULYA_DIMINUTIVE,
            administrators_list=NEWDENTAL_SCHEDULE,
        )
        assert result["first_name"] is None, (
            f"Уменьшительное 'Юля' не должно проходить валидацию! result={result}"
        )

    @pytest.mark.asyncio
    async def test_unit_marina_not_in_schedule_rejected(self, service):
        """'Марина' нет в графике → null."""
        mock_response = MagicMock()
        mock_response.content = json.dumps({
            "first_name": "Марина",
            "last_name": None,
            "confidence": 0.95
        })
        service.llm.ainvoke = AsyncMock(return_value=mock_response)

        result = await service.extract_administrator_name(
            transcription_text=TRANSCRIPTION_MARINA,
            administrators_list=NEWDENTAL_SCHEDULE,
        )
        assert result["first_name"] is None, (
            f"'Марина' НЕТ в графике, но прошла валидацию! result={result}"
        )

    @pytest.mark.asyncio
    async def test_unit_ira_not_in_schedule_rejected(self, service):
        """'Ира' нет в графике → null."""
        mock_response = MagicMock()
        mock_response.content = json.dumps({
            "first_name": "Ира",
            "last_name": None,
            "confidence": 0.9
        })
        service.llm.ainvoke = AsyncMock(return_value=mock_response)

        result = await service.extract_administrator_name(
            transcription_text=TRANSCRIPTION_IRA,
            administrators_list=NEWDENTAL_SCHEDULE,
        )
        assert result["first_name"] is None, (
            f"'Ира' НЕТ в графике, но прошла валидацию! result={result}"
        )

    @pytest.mark.asyncio
    async def test_unit_valid_name_passes(self, service):
        """Корректное имя из графика проходит валидацию."""
        mock_response = MagicMock()
        mock_response.content = json.dumps({
            "first_name": "Евгения",
            "last_name": "Слугина",
            "confidence": 0.95
        })
        service.llm.ainvoke = AsyncMock(return_value=mock_response)

        result = await service.extract_administrator_name(
            transcription_text=TRANSCRIPTION_EVGENIYA_OK,
            administrators_list=NEWDENTAL_SCHEDULE,
        )
        assert result["first_name"] == "Евгения"
        assert result["last_name"] == "Слугина"

    @pytest.mark.asyncio
    async def test_unit_first_name_match_no_lastname_gets_first_from_schedule(self, service):
        """
        AI вернул first_name='Юлия' без фамилии.
        В графике ДВЕ Юлии → подставляется фамилия первой Юлии из графика.
        """
        mock_response = MagicMock()
        mock_response.content = json.dumps({
            "first_name": "Юлия",
            "last_name": None,
            "confidence": 0.85
        })
        service.llm.ainvoke = AsyncMock(return_value=mock_response)

        result = await service.extract_administrator_name(
            transcription_text=TRANSCRIPTION_YULIYA_NO_LASTNAME,
            administrators_list=NEWDENTAL_SCHEDULE,
        )

        assert result["first_name"] == "Юлия"
        assert result["last_name"] == "Черкасова", (
            f"Без фамилии должна подставиться первая Юлия из графика (Черкасова). result={result}"
        )


class TestDetermineByAiScheduleValidation:
    """
    Тест полного пайплайна _determine_by_ai_schedule.
    Мокаем LLM, проверяем финальный результат.
    """

    @pytest.fixture
    def mock_db(self):
        return MagicMock()

    @pytest.mark.asyncio
    async def test_unit_name_not_in_schedule_returns_unknown(self, mock_db):
        """
        Когда AI вернёт имя не из графика, финальный результат должен быть None
        (что превращается в 'Неизвестный администратор' в determine_administrator_for_call).
        """
        mock_response = MagicMock()
        mock_response.content = json.dumps({
            "first_name": "Валерия", "last_name": None, "confidence": 0.9
        })

        with patch('app.services.admin_detection_service.ScheduleService') as MockSchedule, \
             patch('app.services.admin_detection_service.CallAnalysisService') as MockAnalysis:

            MockSchedule.return_value.get_schedule_for_date = AsyncMock(
                return_value=NEWDENTAL_SCHEDULE
            )
            mock_svc = MockAnalysis.return_value
            mock_svc.extract_administrator_name = AsyncMock(
                return_value={"first_name": None, "last_name": None, "confidence": 0.0}
            )

            from datetime import date
            result = await _determine_by_ai_schedule(
                clinic_id="9476ab76-c2a6-4fef-b4f8-33e1284ef261",
                call_date=date(2026, 1, 28),
                transcription_text=TRANSCRIPTION_VALERIYA,
                db=mock_db,
            )
            assert result is None, (
                f"Должен быть None (→ Неизвестный), но получили: {result}"
            )

    @pytest.mark.asyncio
    async def test_unit_single_admin_returns_without_ai(self, mock_db):
        """Один админ в графике → возвращаем без AI."""
        single_schedule = [{"first_name": "Александра", "last_name": "Темнюк"}]

        with patch('app.services.admin_detection_service.ScheduleService') as MockSchedule:
            MockSchedule.return_value.get_schedule_for_date = AsyncMock(
                return_value=single_schedule
            )

            from datetime import date
            result = await _determine_by_ai_schedule(
                clinic_id="4c640248-8904-412e-ae85-14dda10edd1b",
                call_date=date(2026, 1, 28),
                transcription_text="любой текст",
                db=mock_db,
            )
            assert result == "Александра Темнюк"

    @pytest.mark.asyncio
    async def test_unit_empty_schedule_returns_none(self, mock_db):
        """Пустой график → None."""
        with patch('app.services.admin_detection_service.ScheduleService') as MockSchedule:
            MockSchedule.return_value.get_schedule_for_date = AsyncMock(
                return_value=[]
            )

            from datetime import date
            result = await _determine_by_ai_schedule(
                clinic_id="9476ab76-c2a6-4fef-b4f8-33e1284ef261",
                call_date=date(2026, 1, 28),
                transcription_text=TRANSCRIPTION_VALERIYA,
                db=mock_db,
            )
            assert result is None

    @pytest.mark.asyncio
    async def test_unit_no_transcription_with_multiple_admins_returns_none(self, mock_db):
        """Несколько админов, но нет транскрипции → None."""
        with patch('app.services.admin_detection_service.ScheduleService') as MockSchedule:
            MockSchedule.return_value.get_schedule_for_date = AsyncMock(
                return_value=NEWDENTAL_SCHEDULE
            )

            from datetime import date
            result = await _determine_by_ai_schedule(
                clinic_id="9476ab76-c2a6-4fef-b4f8-33e1284ef261",
                call_date=date(2026, 1, 28),
                transcription_text=None,
                db=mock_db,
            )
            assert result is None


# =============================================================================
# ИНТЕГРАЦИОННЫЕ ТЕСТЫ: Реальный вызов OpenAI
# =============================================================================

@pytest.mark.integration
class TestAdminDetectionIntegration:
    """
    Интеграционные тесты — реально вызывают OpenAI.
    Проверяют, что промпт + валидация вместе дают корректный результат.

    Запуск: pytest tests/test_admin_detection.py -v -s -k "integration"
    """

    @pytest.fixture
    def service(self):
        """Реальный CallAnalysisService (с реальным LLM)."""
        return CallAnalysisService()

    @pytest.mark.asyncio
    async def test_integration_valeriya_not_in_schedule(self, service):
        """
        Транскрипция с 'Валерия' + график без Валерии.
        Ожидание: null (Валерии нет в графике).
        """
        result = await service.extract_administrator_name(
            transcription_text=TRANSCRIPTION_VALERIYA,
            administrators_list=NEWDENTAL_SCHEDULE,
        )
        assert result["first_name"] is None, (
            f"'Валерия' НЕТ в графике → должно быть null, но AI вернул: {result}"
        )

    @pytest.mark.asyncio
    async def test_integration_marina_not_in_schedule(self, service):
        """
        Транскрипция с 'Марина' + график без Марины.
        Ожидание: null.
        """
        result = await service.extract_administrator_name(
            transcription_text=TRANSCRIPTION_MARINA,
            administrators_list=NEWDENTAL_SCHEDULE,
        )
        assert result["first_name"] is None, (
            f"'Марина' НЕТ в графике → должно быть null, но AI вернул: {result}"
        )

    @pytest.mark.asyncio
    async def test_integration_natalya_not_in_schedule(self, service):
        """'Наталья' нет в графике → null."""
        result = await service.extract_administrator_name(
            transcription_text=TRANSCRIPTION_NATALYA,
            administrators_list=NEWDENTAL_SCHEDULE,
        )
        assert result["first_name"] is None, (
            f"'Наталья' НЕТ в графике → должно быть null, но AI вернул: {result}"
        )

    @pytest.mark.asyncio
    async def test_integration_ira_not_in_schedule(self, service):
        """'Ира' нет в графике → null."""
        result = await service.extract_administrator_name(
            transcription_text=TRANSCRIPTION_IRA,
            administrators_list=NEWDENTAL_SCHEDULE,
        )
        assert result["first_name"] is None, (
            f"'Ира' НЕТ в графике → должно быть null, но AI вернул: {result}"
        )

    @pytest.mark.asyncio
    async def test_integration_svetlana_not_in_schedule(self, service):
        """
        'Светлана' (stomdv) нет в графике.
        Хитрый случай: Светлана — и админ, и имя клиента.
        """
        result = await service.extract_administrator_name(
            transcription_text=TRANSCRIPTION_SVETLANA,
            administrators_list=STOMDV_SCHEDULE,
        )
        assert result["first_name"] is None, (
            f"'Светлана' НЕТ в графике stomdv → должно быть null, но AI вернул: {result}"
        )

    @pytest.mark.asyncio
    async def test_integration_evgeniya_correct(self, service):
        """
        'Евгения' в графике (Евгения Слугина).
        Единственная Евгения → должна сопоставиться корректно.
        """
        result = await service.extract_administrator_name(
            transcription_text=TRANSCRIPTION_EVGENIYA_OK,
            administrators_list=NEWDENTAL_SCHEDULE,
        )
        assert result["first_name"] == "Евгения", (
            f"Евгения ЕСТЬ в графике, должна определиться. result={result}"
        )
        assert result["last_name"] == "Слугина", (
            f"Фамилия должна быть 'Слугина'. result={result}"
        )

    @pytest.mark.asyncio
    async def test_integration_no_name_in_transcription(self, service):
        """Транскрипция без имени администратора → null."""
        result = await service.extract_administrator_name(
            transcription_text=TRANSCRIPTION_NO_NAME,
            administrators_list=NEWDENTAL_SCHEDULE,
        )
        assert result["first_name"] is None, (
            f"Нет имени в транскрипции → null, но AI вернул: {result}"
        )

    @pytest.mark.asyncio
    async def test_integration_yuliya_should_have_lastname(self, service):
        """
        В транскрипции 'Юля', в графике 2 Юлии (Черкасова, Гаршина).
        AI должен либо определить конкретную Юлию, либо вернуть null.
        НЕ должен вернуть просто 'Юлия' без фамилии.
        """
        result = await service.extract_administrator_name(
            transcription_text=TRANSCRIPTION_YULIYA_NO_LASTNAME,
            administrators_list=NEWDENTAL_SCHEDULE,
        )

        if result["first_name"] == "Юлия":
            # Если AI определил Юлию — фамилия ОБЯЗАНА быть
            assert result.get("last_name") in ("Черкасова", "Гаршина"), (
                f"AI вернул 'Юлия' без корректной фамилии! "
                f"В графике 2 Юлии, нужна фамилия. result={result}"
            )
        else:
            # null тоже допустим — нельзя определить какая Юлия
            assert result["first_name"] is None, (
                f"Неожиданный результат: {result}"
            )
