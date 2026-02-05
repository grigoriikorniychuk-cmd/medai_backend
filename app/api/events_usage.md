# Использование эндпоинта для получения событий из AmoCRM

## Общая информация
Эндпоинт `/api/admin/amocrm/events` позволяет получать события из AmoCRM, включая звонки и сообщения чата.
Эндпоинт использует API v4 events AmoCRM для получения данных.

## Параметры запроса
```json
{
    "client_id": "YOUR_CLIENT_ID",
    "event_type": "outgoing_call",
    "start_date": "01.05.2025",
    "end_date": "15.05.2025",
    "limit": 50
}
```

### Описание параметров:
- `client_id` (обязательный) - Client ID из интеграции AmoCRM
- `event_type` (необязательный, по умолчанию `"all"`) - Тип события для фильтрации:
  - `"outgoing_call"` - Исходящие звонки
  - `"incoming_call"` - Входящие звонки
  - `"incoming_chat_message"` - Входящие сообщения чата
  - `"all"` - Все типы событий
- `start_date` (необязательный) - Дата начала в формате ДД.ММ.ГГГГ или ГГГГ-ММ-ДД
- `end_date` (необязательный) - Дата окончания в формате ДД.ММ.ГГГГ или ГГГГ-ММ-ДД
- `limit` (необязательный, по умолчанию 50) - Количество событий для получения (макс. 250)

## Пример запроса
```bash
curl -X POST "http://localhost:8000/api/admin/amocrm/events" \
  -H "Content-Type: application/json" \
  -d '{
    "client_id": "YOUR_CLIENT_ID",
    "event_type": "outgoing_call",
    "start_date": "01.05.2025",
    "end_date": "05.05.2025",
    "limit": 20
  }'
```

## Пример ответа
```json
{
  "success": true,
  "message": "Получено 5 событий типа outgoing_call",
  "data": {
    "total": 5,
    "events": [
      {
        "id": "01j5zf0b5rgwza6edvtgyk08j",
        "type": "outgoing_call",
        "entity_id": "37788205",
        "entity_type": "lead",
        "created_at": 1724411555,
        "created_date": "23.06.2025 12:45:55",
        "value_after": {
          "duration": 180,
          "phone": "+79991234567",
          "link": "https://example.com/call_recording.mp3",
          "status": "success",
          "call_status": "answered"
        },
        "value_before": null,
        "call_info": {
          "duration": 180,
          "duration_formatted": "3:00",
          "phone": "+79991234567",
          "link": "https://example.com/call_recording.mp3",
          "status": "success",
          "call_result": null,
          "call_status": "answered"
        }
      },
      // Другие события...
    ],
    "_links": {
      "self": {
        "href": "https://subdomain.amocrm.ru/api/v4/events"
      }
    },
    "_page": {
      "limit": 20,
      "total": 5
    }
  }
}
```

## Важные замечания
1. Для работы эндпоинта требуются корректно настроенные токены AmoCRM.
2. Вы можете получить записи звонков через поле `link` внутри `call_info`.
3. События сортируются по дате в обратном порядке (сначала новые).
4. Для пагинации используйте параметры из полей `_links` и `_page`.
