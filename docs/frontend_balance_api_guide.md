# API Документация: Система управления балансом и лимитами

> ⚠️ **ВАЖНО: Обновлено 02.12.2025** — система теперь работает с **МИНУТАМИ** вместо кредитов!

## Обзор

Система управления балансом состоит из следующих эндпоинтов:

| Endpoint | Описание |
|----------|----------|
| `GET /api/clinics/limits/all` | 🆕 **Баланс ВСЕХ клиник** (рекомендуется для дашборда) |
| `GET /api/admin/clinics/{client_id}/limits` | Лимиты конкретной клиники |
| `PUT /api/admin/clinics/{client_id}/limits` | Обновить лимиты клиники |
| `POST /api/admin/clinics/{client_id}/limits/reset` | Сбросить счётчик на 0 |
| `GET /api/admin/elevenlabs-balance` | Общий баланс аккаунта ElevenLabs |

---

## 🆕 1. Баланс всех клиник (РЕКОМЕНДУЕТСЯ)

### Эндпоинт
```
GET /api/clinics/limits/all
```

### Описание
Возвращает баланс **в минутах** для всех клиник. Идеально для дашборда.

### Пример запроса
```javascript
const response = await fetch('https://api.mlab-electronics.ru/api/clinics/limits/all');
const data = await response.json();
```

### Ответ (200 OK)
```json
{
  "clinics": [
    {
      "client_id": "9476ab76-c2a6-4fef-b4f8-33e1284ef261",
      "name": "newdental",
      "monthly_limit_minutes": 3000,
      "current_month_minutes": 272.77,
      "remaining_minutes": 2727.23,
      "usage_percent": 9.09
    },
    {
      "client_id": "3306c1e4-6022-45e3-b7b7-45646a8a5db6",
      "name": "stomdv",
      "monthly_limit_minutes": 3000,
      "current_month_minutes": 104.37,
      "remaining_minutes": 2895.63,
      "usage_percent": 3.48
    }
  ],
  "total_limit_minutes": 18000,
  "total_used_minutes": 565.53,
  "total_remaining_minutes": 17434.47
}
```

### Поля ответа

| Поле | Тип | Описание |
|------|-----|----------|
| `clinics` | array | Массив клиник с балансом |
| `clinics[].monthly_limit_minutes` | number | Лимит клиники (3000 мин = 50 часов) |
| `clinics[].current_month_minutes` | number | Использовано минут в этом месяце |
| `clinics[].remaining_minutes` | number | Осталось минут |
| `clinics[].usage_percent` | number | Процент использования |
| `total_limit_minutes` | number | Общий лимит (18000 мин = 300 часов) |
| `total_used_minutes` | number | Общее использование всех клиник |
| `total_remaining_minutes` | number | Общий остаток |

### Пример React компонента

```tsx
function BalanceDashboard() {
  const [data, setData] = useState(null);

  useEffect(() => {
    fetch('/api/clinics/limits/all')
      .then(res => res.json())
      .then(setData);
  }, []);

  if (!data) return <div>Загрузка...</div>;

  return (
    <div>
      {/* Общая статистика */}
      <div className="total-stats">
        <h2>Общий баланс ElevenLabs</h2>
        <p>Использовано: {data.total_used_minutes.toFixed(1)} / {data.total_limit_minutes} мин</p>
        <p>Осталось: {data.total_remaining_minutes.toFixed(1)} мин</p>
      </div>

      {/* Таблица клиник */}
      <table>
        <thead>
          <tr>
            <th>Клиника</th>
            <th>Использовано</th>
            <th>Лимит</th>
            <th>Осталось</th>
            <th>%</th>
          </tr>
        </thead>
        <tbody>
          {data.clinics.map(clinic => (
            <tr key={clinic.client_id}>
              <td>{clinic.name}</td>
              <td>{clinic.current_month_minutes.toFixed(1)} мин</td>
              <td>{clinic.monthly_limit_minutes} мин</td>
              <td>{clinic.remaining_minutes.toFixed(1)} мин</td>
              <td>
                <ProgressBar 
                  value={clinic.usage_percent} 
                  color={getColor(clinic.usage_percent)}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Цвет прогресс-бара
function getColor(percent) {
  if (percent >= 90) return '#ef4444'; // красный
  if (percent >= 70) return '#f59e0b'; // оранжевый
  return '#22c55e'; // зелёный
}
```

### Форматирование минут в часы

```javascript
function formatMinutes(minutes) {
  const hours = Math.floor(minutes / 60);
  const mins = Math.round(minutes % 60);
  if (hours > 0) return `${hours}ч ${mins}м`;
  return `${mins} мин`;
}

// Примеры:
// 272.77 → "4ч 33м"
// 32.22 → "32 мин"
// 3000 → "50ч 0м"
```

### Цветовая индикация

| Использование | Цвет | CSS |
|---------------|------|-----|
| 0-70% | 🟢 Зелёный | `#22c55e` |
| 70-90% | 🟠 Оранжевый | `#f59e0b` |
| 90-100% | 🔴 Красный | `#ef4444` |
| >100% | ⛔ Заблокировано | `#dc2626` + текст |

---

## 2. Общий баланс ElevenLabs (для справки)

---

## 1. Получить общий баланс ElevenLabs

### Эндпоинт
```
GET /api/admin/elevenlabs-balance
```

### Описание
Возвращает информацию о балансе основного аккаунта ElevenLabs (общие кредиты для всех клиник).

### Заголовки
Не требуются (авторизация через внутренний API-ключ)

### Пример запроса
```javascript
const response = await fetch('https://api.mlab-electronics.ru/api/admin/elevenlabs-balance', {
  method: 'GET',
  headers: {
    'Content-Type': 'application/json'
  }
});
const balance = await response.json();
```

### Ответ (200 OK)
```json
{
  "tier": "creator",
  "character_count": 14335,
  "character_limit": 600879,
  "can_extend_character_limit": true,
  "next_character_count_reset_unix": 1761846762,
  "voice_limit": 30,
  "currency": "usd",
  "status": "active",
  "minutes_remaining": 21117.92,
  "tokens_remaining": 586544,
  "next_invoice": {
    "amount_due_cents": 2200,
    "next_payment_attempt_unix": 1761850362
  }
}
```

### Ключевые поля для отображения

| Поле | Тип | Описание |
|------|-----|----------|
| `character_limit` | number | **Реальный лимит аккаунта** (может быть > 500,000 из-за бонусов) |
| `character_count` | number | Использовано кредитов за текущий период |
| `tokens_remaining` | number | Осталось кредитов (добавлено бэкендом) |
| `minutes_remaining` | number | Осталось минут аудио (добавлено бэкендом) |
| `next_character_count_reset_unix` | number | Unix timestamp следующего сброса счётчика |
| `status` | string | Статус подписки: "active", "suspended" и т.д. |

### Формулы для UI

```javascript
// Процент использования
const percentageUsed = (data.character_count / data.character_limit * 100).toFixed(2);

// Часы и минуты
const hours = Math.floor(data.minutes_remaining / 60);
const minutes = Math.round(data.minutes_remaining % 60);

// Дата следующего сброса
const resetDate = new Date(data.next_character_count_reset_unix * 1000);
```

### Пример отображения в UI
```
┌─────────────────────────────────────┐
│ 💳 Общий баланс ElevenLabs          │
├─────────────────────────────────────┤
│ Лимит:        600,879 кредитов      │
│ Использовано: 14,335 кредитов       │
│ Осталось:     586,544 кредитов      │
│ Прогресс:     [████████░░] 2.4%     │
│                                     │
│ ⏱️  21,117 минут (~352 часа)        │
│ 🔄 Сброс: 01.11.2025                │
└─────────────────────────────────────┘
```

---

## 2. Получить лимиты конкретной клиники

### Эндпоинт
```
GET /api/admin/clinic-limits/{client_id}
```

### Описание
Возвращает информацию о лимитах транскрибации для конкретной клиники.

### Параметры URL

| Параметр | Тип | Обязательный | Описание |
|----------|-----|--------------|----------|
| `client_id` | string | Да | UUID клиники из AmoCRM |

### Пример запроса
```javascript
const clientId = '3306c1e4-6022-45e3-b7b7-45646a8a5db6';
const response = await fetch(`https://api.mlab-electronics.ru/api/admin/clinic-limits/${clientId}`, {
  method: 'GET',
  headers: {
    'Content-Type': 'application/json'
  }
});
const limits = await response.json();
```

### Ответ (200 OK)
```json
{
  "success": true,
  "clinic_name": "Стоматология 'Для всех'",
  "monthly_limit": 85000,
  "current_usage": 5247,
  "remaining_credits": 79753,
  "remaining_minutes": 2871.45,
  "percentage_used": 6.17
}
```

### Поля ответа

| Поле | Тип | Описание |
|------|-----|----------|
| `success` | boolean | Успешность запроса |
| `clinic_name` | string | Название клиники |
| `monthly_limit` | number | Месячный лимит в кредитах (пополняется вручную) |
| `current_usage` | number | Использовано кредитов с момента последнего пополнения |
| `remaining_credits` | number | Осталось кредитов |
| `remaining_minutes` | number | Осталось минут аудио |
| `percentage_used` | number | Процент использования (0-100) |

### Обработка ошибок

**404 Not Found** - клиника не найдена:
```json
{
  "detail": "Клиника {client_id} не найдена"
}
```

**500 Internal Server Error** - ошибка сервера:
```json
{
  "detail": "Ошибка при получении лимитов: ..."
}
```

### Пример отображения в UI
```
┌─────────────────────────────────────┐
│ 🏥 Стоматология "Для всех"          │
├─────────────────────────────────────┤
│ Лимит:        85,000 кредитов       │
│ Использовано: 5,247 кредитов        │
│ Осталось:     79,753 кредитов       │
│ Прогресс:     [█░░░░░░░░░] 6.17%    │
│                                     │
│ ⏱️  2,871 минут (~47 часов)         │
│                                     │
│ [+ Пополнить баланс]                │
└─────────────────────────────────────┘
```

### Рекомендации по UI

**Цветовая индикация остатка:**
```javascript
function getStatusColor(percentageUsed) {
  if (percentageUsed < 50) return 'green';   // Много осталось
  if (percentageUsed < 80) return 'yellow';  // Внимание
  if (percentageUsed < 95) return 'orange';  // Скоро закончится
  return 'red';                               // Критично мало
}
```

**Предупреждения:**
- При `percentage_used >= 80%` показывать предупреждение
- При `percentage_used >= 95%` показывать критическое предупреждение
- При `remaining_credits <= 0` блокировать транскрибацию

---

## 3. Пополнить токены клиники (только админ)

### Эндпоинт
```
POST /api/admin/clinic-limits/{client_id}/add-tokens
```

### Описание
Вручную пополняет лимит транскрибации для клиники. Минуты автоматически конвертируются в кредиты по формуле: **27.78 кредитов/минуту**.

### Параметры URL

| Параметр | Тип | Обязательный | Описание |
|----------|-----|--------------|----------|
| `client_id` | string | Да | UUID клиники из AmoCRM |

### Тело запроса
```json
{
  "minutes": 1000
}
```

### Поля тела

| Поле | Тип | Обязательный | Ограничения | Описание |
|------|-----|--------------|-------------|----------|
| `minutes` | integer | Да | >= 1 | Количество минут для пополнения |

### Пример запроса
```javascript
const clientId = '3306c1e4-6022-45e3-b7b7-45646a8a5db6';
const minutesToAdd = 1000;

const response = await fetch(`https://api.mlab-electronics.ru/api/admin/clinic-limits/${clientId}/add-tokens`, {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({ minutes: minutesToAdd })
});

const result = await response.json();
```

### Ответ (200 OK)
```json
{
  "success": true,
  "message": "Лимит клиники 'Стоматология \"Для всех\"' успешно пополнен на 1000 минут",
  "data": {
    "clinic_name": "Стоматология 'Для всех'",
    "minutes_added": 1000,
    "credits_added": 27780,
    "previous_limit": 85000,
    "new_limit": 112780,
    "current_usage": 5247,
    "remaining_credits": 107533,
    "remaining_minutes": 3871.21
  }
}
```

### Поля ответа

| Поле | Тип | Описание |
|------|-----|----------|
| `success` | boolean | Успешность операции |
| `message` | string | Сообщение о результате |
| `data.clinic_name` | string | Название клиники |
| `data.minutes_added` | number | Добавлено минут |
| `data.credits_added` | number | Добавлено кредитов |
| `data.previous_limit` | number | Предыдущий лимит |
| `data.new_limit` | number | Новый лимит после пополнения |
| `data.current_usage` | number | Текущее использование (не изменилось) |
| `data.remaining_credits` | number | Остаток после пополнения |
| `data.remaining_minutes` | number | Остаток в минутах |

### Обработка ошибок

**400 Bad Request** - ошибка валидации:
```json
{
  "detail": [
    {
      "loc": ["body", "minutes"],
      "msg": "ensure this value is greater than or equal to 1",
      "type": "value_error.number.not_ge"
    }
  ]
}
```

**400 Bad Request** - не удалось пополнить:
```json
{
  "detail": "Клиника не найдена"
}
```

**500 Internal Server Error**:
```json
{
  "detail": "Ошибка при пополнении лимита: ..."
}
```

### UI для админа

**Форма пополнения:**
```html
<div class="topup-form">
  <h3>Пополнить баланс клиники</h3>
  
  <label for="minutes">Количество минут:</label>
  <input type="number" id="minutes" min="1" placeholder="1000">
  
  <p class="conversion-hint">
    = <span id="credits-preview">0</span> кредитов
  </p>
  
  <button onclick="topUpClinic()">Пополнить</button>
</div>

<script>
// Автоматический пересчет
document.getElementById('minutes').addEventListener('input', (e) => {
  const minutes = parseInt(e.target.value) || 0;
  const credits = Math.round(minutes * 27.78);
  document.getElementById('credits-preview').textContent = credits.toLocaleString();
});

async function topUpClinic() {
  const minutes = parseInt(document.getElementById('minutes').value);
  
  if (!minutes || minutes < 1) {
    alert('Введите корректное количество минут');
    return;
  }
  
  try {
    const response = await fetch(`/api/admin/clinic-limits/${currentClientId}/add-tokens`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ minutes })
    });
    
    const result = await response.json();
    
    if (result.success) {
      alert(result.message);
      // Обновить отображение лимитов
      await refreshClinicLimits();
    } else {
      alert('Ошибка: ' + result.message);
    }
  } catch (error) {
    alert('Ошибка при пополнении: ' + error.message);
  }
}
</script>
```

---

## 4. Полный пример интеграции

### React компонент для отображения баланса

```jsx
import React, { useState, useEffect } from 'react';

function ClinicBalance({ clientId }) {
  const [balance, setBalance] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchBalance();
  }, [clientId]);

  async function fetchBalance() {
    try {
      setLoading(true);
      const response = await fetch(`/api/admin/clinic-limits/${clientId}`);
      
      if (!response.ok) {
        throw new Error('Не удалось загрузить данные');
      }
      
      const data = await response.json();
      setBalance(data);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  function getStatusColor() {
    if (!balance) return 'gray';
    const percentage = balance.percentage_used;
    if (percentage < 50) return '#4CAF50'; // green
    if (percentage < 80) return '#FFC107'; // yellow
    if (percentage < 95) return '#FF9800'; // orange
    return '#F44336'; // red
  }

  if (loading) return <div>Загрузка...</div>;
  if (error) return <div className="error">{error}</div>;
  if (!balance) return null;

  return (
    <div className="clinic-balance-card">
      <h3>{balance.clinic_name}</h3>
      
      <div className="balance-stats">
        <div className="stat">
          <span className="label">Лимит:</span>
          <span className="value">{balance.monthly_limit.toLocaleString()} кредитов</span>
        </div>
        
        <div className="stat">
          <span className="label">Использовано:</span>
          <span className="value">{balance.current_usage.toLocaleString()} кредитов</span>
        </div>
        
        <div className="stat">
          <span className="label">Осталось:</span>
          <span className="value" style={{ color: getStatusColor() }}>
            {balance.remaining_credits.toLocaleString()} кредитов
          </span>
        </div>
      </div>
      
      <div className="progress-bar">
        <div 
          className="progress-fill" 
          style={{ 
            width: `${balance.percentage_used}%`,
            backgroundColor: getStatusColor()
          }}
        />
      </div>
      
      <p className="time-remaining">
        ⏱️ Осталось: {Math.round(balance.remaining_minutes)} минут
      </p>
      
      {balance.percentage_used >= 80 && (
        <div className="warning">
          ⚠️ Лимит скоро закончится! Пополните баланс.
        </div>
      )}
      
      <button onClick={fetchBalance} className="refresh-btn">
        🔄 Обновить
      </button>
    </div>
  );
}

export default ClinicBalance;
```

---

## 5. Важные замечания

### Формула конвертации
**27.78 кредитов/минуту** = **0.463 кредитов/секунду**

Эта формула основана на официальном тарифе ElevenLabs PRO:
- 500,000 кредитов = 18,000 минут (300 часов)
- Проверено экспериментально: 9 кредитов за 19.5 секунд = 0.462 кредитов/сек

### Система лимитов
- **Автосброс отключен** - лимиты НЕ сбрасываются раз в 30 дней
- **Только ручное пополнение** через эндпоинт `/add-tokens`
- **Каждая клиника** имеет свой независимый лимит
- **По умолчанию**: 85,000 кредитов на клинику (~3000 минут)

### Мониторинг
- Проверяйте баланс клиники перед запуском массовой транскрибации
- Отображайте предупреждения при низком остатке
- Логируйте все пополнения для аудита

### Безопасность
- Эндпоинт пополнения должен быть доступен **только админам**
- Рекомендуется добавить дополнительную авторизацию
- Логировать все операции пополнения

---

## 6. Changelog эндпоинтов

### Версия 2025-10-02
- ✅ **Исправлено**: `/api/admin/elevenlabs-balance` теперь возвращает реальный `character_limit` из API (не перезаписывает на 500,000)
- ✅ **Добавлено**: `/api/admin/clinic-limits/{client_id}` - получение лимитов клиники
- ✅ **Добавлено**: `/api/admin/clinic-limits/{client_id}/add-tokens` - ручное пополнение
- ✅ **Изменено**: Автосброс лимитов раз в 30 дней отключен

---

## Контакты технической поддержки

При возникновении проблем с интеграцией обращайтесь к команде бэкенда.
