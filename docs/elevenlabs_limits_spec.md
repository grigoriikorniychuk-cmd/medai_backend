# Система лимитов использования ElevenLabs

## Обзор

Система управления месячных И НЕДЕЛЬНЫХ лимитов использования ElevenLabs API для транскрибации звонков по клиникам. **Все лимиты хранятся в МИНУТАХ** для простоты понимания.

## Тариф ElevenLabs PRO

| Параметр | Значение |
|----------|----------|
| Стоимость | $99/месяц |
| Минут STT в месяц | 18,000 минут (300 часов) |
| Лимит на клинику (месячный) | 3,000 минут (~50 часов) |
| Лимит на клинику (недельный) | 750 минут (~12.5 часов, 1/4 месячного) |

## Структура данных в MongoDB

**Коллекция `clinics`:**
```json
{
  "client_id": "string",
  "name": "Название клиники",
  "monthly_limit_minutes": 3000,
  "current_month_minutes": 150.5,
  "weekly_limit_minutes": 750,
  "current_week_minutes": 45.2,
  "last_reset_date": "2025-12-01T00:00:00",
  "last_week_reset_date": "2025-12-18T00:00:00",
  "updated_at": "2025-12-02T12:00:00"
}
```

## API Endpoints

### Для фронтенда — баланс всех клиник

```
GET /api/clinics/limits/all
```

**Ответ:**
```json
{
  "clinics": [
    {
      "client_id": "xxx",
      "name": "Клиника 1",
      "monthly_limit_minutes": 3000,
      "current_month_minutes": 150.5,
      "remaining_minutes": 2849.5,
      "usage_percent": 5.0
    }
  ],
  "total_limit_minutes": 18000,
  "total_used_minutes": 500.5,
  "total_remaining_minutes": 17499.5
}
```

### Лимиты конкретной клиники

```
GET /api/admin/clinics/{client_id}/limits
```

**Ответ:**
```json
{
  "client_id": "xxx",
  "clinic_name": "Клиника 1",
  "monthly_limit_minutes": 3000,
  "current_month_minutes": 150.5,
  "remaining_minutes": 2849.5,
  "usage_percent": 5.0,
  "last_reset_date": "2025-12-01T00:00:00"
}
```

### Обновить лимиты клиники

```
PUT /api/admin/clinics/{client_id}/limits?monthly_limit_minutes=3000&current_usage_minutes=0
```

### Сбросить счётчик на 0

```
POST /api/admin/clinics/{client_id}/limits/reset
```

### Баланс ElevenLabs

```
GET /api/admin/elevenlabs-balance
```

## Логика блокировки

При попытке транскрипции проверяется:
1. `current_month_minutes < monthly_limit_minutes` (месячный лимит)
2. `current_week_minutes < weekly_limit_minutes` (недельный лимит)
3. Если ЛЮБОЙ из лимитов превышен — транскрипция **блокируется**
4. Статус звонка: `transcription_status = "limit_exceeded"`

**Ответы при блокировке:**

Месячный лимит:
```
❌ Транскрипция заблокирована: клиника ClinicName 
превысила МЕСЯЧНЫЙ лимит (3050.5/3000 минут)
```

Недельный лимит:
```
❌ Транскрипция заблокирована: клиника ClinicName 
превысила НЕДЕЛЬНЫЙ лимит (780.5/750 минут). Лимит сбросится через неделю.
```

**Автосброс:**
- Месячный лимит: **НЕ** сбрасывается автоматически (только вручную через админку)
- Недельный лимит: **Автоматически** сбрасывается каждые 7 дней

## Пример использования на фронте

```javascript
// Получить баланс всех клиник
const response = await fetch('/api/clinics/limits/all');
const data = await response.json();

data.clinics.forEach(clinic => {
  console.log(`${clinic.name}: ${clinic.current_month_minutes}/${clinic.monthly_limit_minutes} мин (${clinic.usage_percent}%)`);
  
  // Прогресс-бар
  const progress = clinic.usage_percent;
  const color = progress > 90 ? 'red' : progress > 70 ? 'orange' : 'green';
});
```

## Миграция данных

Для перехода со старых полей на новые:

```javascript
// MongoDB миграция
db.clinics.updateMany(
  {},
  [
    {
      $set: {
        monthly_limit_minutes: 3000,  // 3000 минут на клинику
        current_month_minutes: 0      // Сброс счётчика
      }
    }
  ]
)
```

## Changelog

- **2025-12-25**: Добавлен недельный лимит (750 минут) для предотвращения быстрого расхода месячного лимита
- **2025-12-25**: Автосброс недельного лимита каждые 7 дней
- **2025-12-02**: Переход на учёт в МИНУТАХ вместо кредитов
- **2025-12-02**: Добавлен endpoint `/api/clinics/limits/all` для фронта
- **2025-12-02**: Добавлена блокировка транскрипции при превышении лимита
