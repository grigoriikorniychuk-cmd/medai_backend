# Гайд по статусным эндпоинтам для фронтенда

## Все статусные эндпоинты

### 1. Статус транскрибации
```
GET /api/calls/transcribe-by-date-range-status?start_date_str=22.08.2025&end_date_str=22.08.2025&client_id={client_id}
```

### 2. Статус анализа звонков  
```
GET /api/analyze-by-date-range-status?start_date_str=22.08.2025&end_date_str=22.08.2025&client_id={client_id}
```

### 3. Статус анализа рекомендаций
```
GET /api/recommendations/analyze-by-date-range-status?start_date_str=22.08.2025&end_date_str=22.08.2025&client_id={client_id}
```

## Параметры (одинаковые для всех эндпоинтов)

- `start_date_str` - Начальная дата в формате `DD.MM.YYYY` или `YYYY-MM-DD`
- `end_date_str` - Конечная дата в формате `DD.MM.YYYY` или `YYYY-MM-DD` 
- `client_id` - ID клиента (обязательный параметр)

## Формат ответа

```json
{
  "overall_status": "completed",    // pending | processing | completed | partial
  "total_calls": 7,
  "status_breakdown": {
    "pending": 0,
    "processing": 0, 
    "success": 7,
    "failed": 0
  },
  "progress_percentage": 100.0
}
```

## Пример использования JavaScript

```javascript
async function checkTranscriptionStatus(clientId, startDate, endDate) {
  const url = `/api/calls/transcribe-by-date-range-status?start_date_str=${startDate}&end_date_str=${endDate}&client_id=${clientId}`;
  
  try {
    const response = await fetch(url);
    const status = await response.json();
    
    console.log(`Progress: ${status.progress_percentage}%`);
    console.log(`Status: ${status.overall_status}`);
    console.log(`Total calls: ${status.total_calls}`);
    
    return status;
  } catch (error) {
    console.error('Status check error:', error);
    return null;
  }
}

async function checkAnalysisStatus(clientId, startDate, endDate) {
  const url = `/api/analyze-by-date-range-status?start_date_str=${startDate}&end_date_str=${endDate}&client_id=${clientId}`;
  return await fetch(url).then(r => r.json());
}

async function checkRecommendationsStatus(clientId, startDate, endDate) {
  const url = `/api/recommendations/analyze-by-date-range-status?start_date_str=${startDate}&end_date_str=${endDate}&client_id=${clientId}`;
  return await fetch(url).then(r => r.json());
}
```

## Polling логика

```javascript
function startStatusPolling(processType, clientId, startDate, endDate) {
  const endpoints = {
    'transcribe': '/api/calls/transcribe-by-date-range-status',
    'analyze': '/api/analyze-by-date-range-status',
    'recommendations': '/api/recommendations/analyze-by-date-range-status'
  };
  
  const endpoint = endpoints[processType];
  const url = `${endpoint}?start_date_str=${startDate}&end_date_str=${endDate}&client_id=${clientId}`;
  
  const interval = setInterval(async () => {
    try {
      const response = await fetch(url);
      const status = await response.json();
      
      // Обновляем UI
      updateProgressBar(processType, status.progress_percentage);
      updateStatusText(processType, status.overall_status);
      
      // Останавливаем polling если процесс завершен
      if (status.overall_status === 'completed' || status.overall_status === 'partial') {
        clearInterval(interval);
        onProcessComplete(processType);
      }
    } catch (error) {
      console.error('Polling error:', error);
      clearInterval(interval);
    }
  }, 5000); // Проверяем каждые 5 секунд
  
  return interval;
}
```

## Обработка ошибок

- **422 Unprocessable Entity** - Неверный формат даты
- **400 Bad Request** - Отсутствует обязательный параметр  
- **500 Internal Server Error** - Ошибка сервера

```javascript
async function safeStatusCheck(url) {
  try {
    const response = await fetch(url);
    
    if (!response.ok) {
      if (response.status === 422) {
        throw new Error('Неверный формат даты. Используйте DD.MM.YYYY или YYYY-MM-DD');
      }
      throw new Error(`HTTP ${response.status}`);
    }
    
    return await response.json();
  } catch (error) {
    console.error('Status check failed:', error);
    return { overall_status: 'error', error: error.message };
  }
}
```
