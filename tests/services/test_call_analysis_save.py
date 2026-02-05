import os
import pytest
import tempfile
import shutil
from datetime import datetime
from app.services.call_analysis_service import CallAnalysisService
from app.models.call_analysis import (
    CallCategoryEnum,
    CallDirectionEnum,
    ToneEnum,
    SatisfactionEnum,
)


@pytest.fixture
def analysis_result():
    """Тестовый результат анализа звонка"""
    return {
        "call_type": {
            "category": CallCategoryEnum.NEW_CLIENT,
            "category_name": "Первичное обращение (новый клиент)",
            "direction": CallDirectionEnum.INCOMING,
        },
        "metrics": {
            # Актуальные метрики из prompts.txt
            "greeting": 8,                   # Приветствие
            "patient_name": 7,               # Имя пациента
            "need_identification": 9,        # Потребность
            "service_presentation": 8,       # Презентация услуги
            "clinic_presentation": 6,        # Презентация клиники
            "doctor_presentation": 7,        # Презентация врача
            "patient_registration": 8,       # Запись пациента
            "clinic_address": 6,             # Адрес клиники
            "passport": 7,                   # Паспорт
            "price_from": 9,                 # Цена "от"
            "expertise": 8,                  # Экспертность
            "next_step": 7,                  # Следующий шаг
            "appointment": 9,                # Запись на прием
            "emotional_coloring": 8,         # Эмоциональный окрас
            "speech": 7,                     # Речь
            "initiative": 8,                 # Инициатива
            "tone": ToneEnum.POSITIVE,       # Тональность
            "customer_satisfaction": SatisfactionEnum.HIGH,  # Удовлетворенность клиента
            "overall_score": 7.5,            # Общая оценка
        },
        "analysis_text": """### 1. ПРИВЕТСТВИЕ (0-10 баллов)
**Оценка: 5/10**
- Администратор поздоровался, но не представился.

### 2. ИМЯ ПАЦИЕНТА (0-10 баллов)
**Оценка: 4/10**
- Администратор не уточнил имя клиента.

### 3. ПОТРЕБНОСТЬ (0-10 баллов)
**Оценка: 6/10**
- Администратор задал минимальное количество вопросов.

### 4. ПРЕЗЕНТАЦИЯ УСЛУГИ (0-10 баллов)
**Оценка: 5/10**
- Администратор рассказал об услуге минимально.

### 5. ПРЕЗЕНТАЦИЯ КЛИНИКИ (0-10 баллов)
**Оценка: 4/10**
- Преимущества клиники не были освещены.

### 6. ПРЕЗЕНТАЦИЯ ВРАЧА (0-10 баллов)
**Оценка: 5/10**
- Квалификация врача упомянута вскользь.

### 7. ЗАПИСЬ ПАЦИЕНТА (0-10 баллов)
**Оценка: 6/10**
- Администратор предложил несколько вариантов записи.

### 8. АДРЕС КЛИНИКИ (0-10 баллов)
**Оценка: 4/10**
- Адрес назван без пояснений.

### 9. ПАСПОРТ (0-10 баллов)
**Оценка: 5/10**
- Администратор кратко упомянул о необходимости паспорта.

### 10. ЦЕНА "ОТ" (0-10 баллов)
**Оценка: 6/10**
- Цена названа, но без пояснений.

### 11. ЭКСПЕРТНОСТЬ (0-10 баллов)
**Оценка: 5/10**
- Администратор продемонстрировал средний уровень знаний.

### 12. СЛЕДУЮЩИЙ ШАГ (0-10 баллов)
**Оценка: 4/10**
- Дальнейшие действия не были четко обозначены.

### 13. ЗАПИСЬ НА ПРИЕМ (0-10 баллов)
**Оценка: 6/10**
- Клиент записан, но без подтверждения деталей.

### 14. ЭМОЦИОНАЛЬНЫЙ ОКРАС (0-10 баллов)
**Оценка: 5/10**
- Тон разговора был нейтральным.

### 15. РЕЧЬ (0-10 баллов)
**Оценка: 5/10**
- Речь администратора требует улучшения.

### 16. ИНИЦИАТИВА (0-10 баллов)
**Оценка: 5/10**
- Администратор не всегда контролировал беседу.

### 17. КОНВЕРСИЯ
**Оценка: Нет**
- Клиент не записался на прием.

### 18. ОЦЕНКА ТОНАЛЬНОСТИ РАЗГОВОРА
**Оценка: "нейтральная"**
- Тон разговора был нейтральным.

### 19. ОЦЕНКА УДОВЛЕТВОРЕННОСТИ КЛИЕНТА
**Оценка: "средняя"**
- Клиент получил ответы на вопросы, но не был полностью удовлетворен.

### 20. ОБЩАЯ ОЦЕНКА (0-10 баллов)
**Оценка: 5/10**
- В целом работа администратора требует улучшения.

### РЕКОМЕНДАЦИИ ПО УЛУЧШЕНИЮ:
1. Администратору следует представляться в начале разговора.
2. Необходимо больше внимания уделять выявлению потребностей клиента.
3. Следует более четко завершать разговор, резюмируя его результаты.""",
        "transcription_text": "Текст диалога для тестирования",
        "conversion": False,
        "meta_info": {
            "note_id": 12345,
            "contact_id": 67890,
            "lead_id": 54321,
        },
        "timestamp": datetime.now(),
    }


@pytest.fixture
def temp_dir():
    """Создает временную директорию для тестирования"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


def test_save_analysis_to_file(analysis_result, temp_dir, monkeypatch):
    """Тест сохранения анализа в файл"""
    # Переопределяем ANALYSIS_DIR для тестирования
    monkeypatch.setattr("app.services.call_analysis_service.ANALYSIS_DIR", temp_dir)

    # Создаем экземпляр сервиса
    service = CallAnalysisService()

    # Сохраняем анализ в файл
    file_path = service.save_analysis_to_file(analysis_result, "test_analysis.txt")

    # Проверяем, что файл создан
    assert os.path.exists(file_path)

    # Читаем файл
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Проверяем содержимое файла - основные метрики в начале файла
    assert "МЕТРИКИ ОЦЕНКИ ЗВОНКА:" in content
    assert "Приветствие: 8/10" in content
    assert "Имя пациента: 7/10" in content
    assert "Потребность: 9/10" in content
    assert "Презентация услуги: 8/10" in content
    assert "Презентация клиники: 6/10" in content
    assert "Презентация врача: 7/10" in content
    assert "Запись пациента: 8/10" in content
    assert "Адрес клиники: 6/10" in content
    assert "Паспорт: 7/10" in content
    assert "Цена \"от\": 9/10" in content
    assert "Экспертность: 8/10" in content
    assert "Следующий шаг: 7/10" in content
    assert "Запись на прием: 9/10" in content
    assert "Эмоциональный окрас: 8/10" in content
    assert "Речь: 7/10" in content
    assert "Инициатива: 8/10" in content
    assert "Тональность: Позитивная" in content
    assert "Удовлетворенность клиента: Высокая" in content
    assert "Общая оценка: 7.5/10" in content
    assert "КОНВЕРСИЯ: Нет" in content

    # Проверяем, что нет дублирования секций
    assert content.count("### ПРИВЕТСТВИЕ") <= 1

    # Проверяем, что метрики в анализе звонка обновлены в соответствии с metrics
    assert "**Оценка: 8/10**" in content  # Приветствие (было 5/10)
    assert "**Оценка: 7/10**" in content  # Имя пациента (было 4/10)
    assert "**Оценка: 9/10**" in content  # Потребность (было 6/10)
    assert "**Оценка: 8/10**" in content  # Презентация услуги (было 5/10)
    assert "**Оценка: 6/10**" in content  # Презентация клиники (было 4/10)
    assert "**Оценка: 7/10**" in content  # Презентация врача (было 5/10)
    assert "**Оценка: 8/10**" in content  # Запись пациента (было 6/10)
    assert "**Оценка: 6/10**" in content  # Адрес клиники (было 4/10)
    assert "**Оценка: 7/10**" in content  # Паспорт (было 5/10)
    assert "**Оценка: 9/10**" in content  # Цена "от" (было 6/10)
    assert "**Оценка: 8/10**" in content  # Экспертность (было 5/10)
    assert "**Оценка: 7/10**" in content  # Следующий шаг (было 4/10)
    assert "**Оценка: 9/10**" in content  # Запись на прием (было 6/10)
    assert "**Оценка: 8/10**" in content  # Эмоциональный окрас (было 5/10)
    assert "**Оценка: 7/10**" in content  # Речь (было 5/10)
    assert "**Оценка: 8/10**" in content  # Инициатива (было 5/10)
    assert "**Оценка: позитивная**" in content  # Тональность (была "нейтральная")
    assert "**Оценка: высокая**" in content  # Удовлетворенность (была "средняя")
    assert "**Оценка: 7.5/10**" in content  # Общая оценка (была 5/10)
    assert "**Оценка: Нет**" in content  # Конверсия (не изменилась)


def test_ensure_metrics_in_analysis_text(analysis_result):
    """Тест обновления метрик в тексте анализа"""
    # Создаем экземпляр сервиса
    service = CallAnalysisService()

    # Обновляем метрики в тексте анализа
    updated_text = service._ensure_metrics_in_analysis_text(
        analysis_result["analysis_text"], analysis_result["metrics"]
    )

    # Проверяем, что метрики обновлены
    assert "**Оценка: 8/10**" in updated_text  # Приветствие (было 5/10)
    assert "**Оценка: 7/10**" in updated_text  # Имя пациента (было 4/10)
    assert "**Оценка: 9/10**" in updated_text  # Потребность (было 6/10)
    assert "**Оценка: 8/10**" in updated_text  # Презентация услуги (было 5/10)
    assert "**Оценка: 6/10**" in updated_text  # Презентация клиники (было 4/10)
    assert "**Оценка: 7/10**" in updated_text  # Презентация врача (было 5/10)
    assert "**Оценка: 8/10**" in updated_text  # Запись пациента (было 6/10)
    assert "**Оценка: 6/10**" in updated_text  # Адрес клиники (было 4/10)
    assert "**Оценка: 7/10**" in updated_text  # Паспорт (было 5/10)
    assert "**Оценка: 9/10**" in updated_text  # Цена "от" (было 6/10)
    assert "**Оценка: 8/10**" in updated_text  # Экспертность (было 5/10)
    assert "**Оценка: 7/10**" in updated_text  # Следующий шаг (было 4/10)
    assert "**Оценка: 9/10**" in updated_text  # Запись на прием (было 6/10)
    assert "**Оценка: 8/10**" in updated_text  # Эмоциональный окрас (было 5/10)
    assert "**Оценка: 7/10**" in updated_text  # Речь (было 5/10)
    assert "**Оценка: 8/10**" in updated_text  # Инициатива (было 5/10)
    assert "**Оценка: позитивная**" in updated_text  # Тональность (была "нейтральная")
    assert "**Оценка: высокая**" in updated_text  # Удовлетворенность (была "средняя")
    assert "**Оценка: 7.5/10**" in updated_text  # Общая оценка (была 5/10)
    assert "**Оценка: Нет**" in updated_text  # Конверсия (не изменилась)

    # Проверяем, что нет дублирования секций
    assert updated_text.count("### ПРИВЕТСТВИЕ") <= 1 