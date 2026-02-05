# Гайд по системе отслеживания статусов API процессов для фронтенда

## Обзор системы

Система состоит из 5 основных процессов, выполняемых последовательно:
1. **Синхронизация звонков** из AmoCRM
2. **Транскрибация** звонков 
3. **Анализ звонков** (классификация и метрики)
4. **Анализ рекомендаций** (обобщение рекомендаций)
5. **Синхронизация PostgreSQL** (автоматически после анализа рекомендаций)

## API Эндпоинты

### Запуск процессов
```
POST /api/calls-parallel-bulk/sync-by-date-range    # 1. Синхронизация звонков
POST /api/calls/transcribe-by-date-range           # 2. Транскрибация 
POST /api/analyze-by-date-range                    # 3. Анализ звонков
POST /api/recommendations/analyze-by-date-range    # 4. Анализ рекомендаций
```

### Проверка статусов
```
GET /api/calls/transcribe-by-date-range-status              # Статус транскрибации
GET /api/analyze-by-date-range-status                       # Статус анализа звонков  
GET /api/recommendations/analyze-by-date-range-status       # Статус анализа рекомендаций
```

## Схема работы с UI состояниями

### Состояния кнопок
```javascript
const ProcessStates = {
  IDLE: 'idle',           // Готова к запуску
  RUNNING: 'running',     // Процесс выполняется
  COMPLETED: 'completed', // Процесс завершен
  ERROR: 'error',         // Ошибка выполнения
  DISABLED: 'disabled'    // Заблокирована (другой процесс идет)
};
```

### Логика блокировки кнопок
```javascript
// Правила блокировки кнопок во время выполнения процессов
const ButtonRules = {
  // Во время синхронизации звонков
  syncRunning: {
    sync: 'running',
    transcribe: 'disabled',
    analyze: 'disabled', 
    recommendations: 'disabled'
  },
  
  // Во время транскрибации
  transcribeRunning: {
    sync: 'disabled',
    transcribe: 'running',
    analyze: 'disabled',
    recommendations: 'disabled'
  },
  
  // Во время анализа звонков
  analyzeRunning: {
    sync: 'disabled', 
    transcribe: 'disabled',
    analyze: 'running',
    recommendations: 'disabled'
  },
  
  // Во время анализа рекомендаций
  recommendationsRunning: {
    sync: 'disabled',
    transcribe: 'disabled', 
    analyze: 'disabled',
    recommendations: 'running'
  }
};
```

## Реализация на фронтенде

### 1. Основной компонент управления процессами

```javascript
class ProcessController {
  constructor() {
    this.processes = {
      sync: { status: 'idle', progress: 0 },
      transcribe: { status: 'idle', progress: 0 },
      analyze: { status: 'idle', progress: 0 }, 
      recommendations: { status: 'idle', progress: 0 }
    };
    
    this.activeProcess = null;
    this.pollingIntervals = {};
  }

  // Запуск синхронизации звонков
  async startSyncProcess(clientId, startDate, endDate) {
    if (this.activeProcess) return false;
    
    this.setProcessStatus('sync', 'running');
    this.activeProcess = 'sync';
    
    try {
      const response = await fetch('/api/calls-parallel-bulk/sync-by-date-range', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          client_id: clientId,
          start_date_str: startDate,
          end_date_str: endDate
        })
      });
      
      if (response.ok) {
        this.setProcessStatus('sync', 'completed');
        this.activeProcess = null;
        return true;
      } else {
        throw new Error('Sync failed');
      }
    } catch (error) {
      this.setProcessStatus('sync', 'error');
      this.activeProcess = null;
      console.error('Sync error:', error);
      return false;
    }
  }

  // Запуск транскрибации с отслеживанием статуса
  async startTranscriptionProcess(clientId, startDate, endDate) {
    if (this.activeProcess) return false;
    
    this.setProcessStatus('transcribe', 'running');
    this.activeProcess = 'transcribe';
    
    try {
      // 1. Запускаем транскрибацию
      const response = await fetch('/api/calls/transcribe-by-date-range', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          client_id: clientId,
          start_date: startDate,
          end_date: endDate
        })
      });
      
      if (!response.ok) {
        throw new Error('Transcription start failed');
      }
      
      // 2. Начинаем отслеживание статуса
      this.startStatusPolling('transcribe', clientId, startDate, endDate);
      return true;
      
    } catch (error) {
      this.setProcessStatus('transcribe', 'error');
      this.activeProcess = null;
      console.error('Transcription error:', error);
      return false;
    }
  }

  // Запуск анализа звонков с отслеживанием статуса
  async startAnalysisProcess(clientId, startDate, endDate) {
    if (this.activeProcess) return false;
    
    this.setProcessStatus('analyze', 'running');
    this.activeProcess = 'analyze';
    
    try {
      // 1. Запускаем анализ
      const response = await fetch('/api/analyze-by-date-range', {
        method: 'POST', 
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          start_date_str: startDate,
          end_date_str: endDate,
          client_id: clientId
        })
      });
      
      if (!response.ok) {
        throw new Error('Analysis start failed');
      }
      
      // 2. Начинаем отслеживание статуса
      this.startStatusPolling('analyze', clientId, startDate, endDate);
      return true;
      
    } catch (error) {
      this.setProcessStatus('analyze', 'error');
      this.activeProcess = null;
      console.error('Analysis error:', error);
      return false;
    }
  }

  // Запуск анализа рекомендаций с отслеживанием статуса
  async startRecommendationsProcess(clientId, startDate, endDate) {
    if (this.activeProcess) return false;
    
    this.setProcessStatus('recommendations', 'running');
    this.activeProcess = 'recommendations';
    
    try {
      // 1. Запускаем анализ рекомендаций
      const response = await fetch('/api/recommendations/analyze-by-date-range', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          client_id: clientId,
          start_date_str: startDate,
          end_date_str: endDate
        })
      });
      
      if (!response.ok) {
        throw new Error('Recommendations analysis start failed');
      }
      
      // 2. Начинаем отслеживание статуса
      this.startStatusPolling('recommendations', clientId, startDate, endDate);
      return true;
      
    } catch (error) {
      this.setProcessStatus('recommendations', 'error');
      this.activeProcess = null;
      console.error('Recommendations error:', error);
      return false;
    }
  }

  // Отслеживание статуса процесса
  startStatusPolling(processType, clientId, startDate, endDate) {
    const statusEndpoints = {
      transcribe: '/api/calls/transcribe-by-date-range-status',
      analyze: '/api/analyze-by-date-range-status', 
      recommendations: '/api/recommendations/analyze-by-date-range-status'
    };
    
    const endpoint = statusEndpoints[processType];
    if (!endpoint) return;
    
    // Очищаем предыдущий интервал если есть
    if (this.pollingIntervals[processType]) {
      clearInterval(this.pollingIntervals[processType]);
    }
    
    // Запускаем опрос статуса каждые 5 секунд
    this.pollingIntervals[processType] = setInterval(async () => {
      try {
        const params = new URLSearchParams({
          start_date: startDate,
          end_date: endDate,
          client_id: clientId
        });
        
        const response = await fetch(`${endpoint}?${params}`);
        const statusData = await response.json();
        
        // Обновляем прогресс
        this.updateProgress(processType, statusData.progress_percentage || 0);
        
        // Проверяем завершение
        if (statusData.overall_status === 'completed') {
          this.setProcessStatus(processType, 'completed');
          this.activeProcess = null;
          clearInterval(this.pollingIntervals[processType]);
          delete this.pollingIntervals[processType];
        } else if (statusData.overall_status === 'partial' && statusData.progress_percentage === 100) {
          // Частичное завершение тоже считаем успехом
          this.setProcessStatus(processType, 'completed');
          this.activeProcess = null;
          clearInterval(this.pollingIntervals[processType]);
          delete this.pollingIntervals[processType];
        }
        
      } catch (error) {
        console.error(`Status polling error for ${processType}:`, error);
        // При ошибке опроса не останавливаем процесс, продолжаем попытки
      }
    }, 5000); // Опрос каждые 5 секунд
  }

  // Установка статуса процесса
  setProcessStatus(processType, status) {
    this.processes[processType].status = status;
    this.updateUI();
  }
  
  // Обновление прогресса
  updateProgress(processType, progress) {
    this.processes[processType].progress = progress;
    this.updateUI();
  }

  // Обновление UI
  updateUI() {
    // Обновляем состояние кнопок
    const buttons = {
      sync: document.getElementById('sync-btn'),
      transcribe: document.getElementById('transcribe-btn'), 
      analyze: document.getElementById('analyze-btn'),
      recommendations: document.getElementById('recommendations-btn')
    };
    
    Object.keys(buttons).forEach(processType => {
      const button = buttons[processType];
      const process = this.processes[processType];
      
      // Определяем состояние кнопки
      let buttonState = process.status;
      if (this.activeProcess && this.activeProcess !== processType) {
        buttonState = 'disabled';
      }
      
      // Обновляем UI кнопки
      this.updateButtonState(button, buttonState, process.progress);
    });
  }

  // Обновление состояния кнопки
  updateButtonState(button, state, progress = 0) {
    if (!button) return;
    
    // Удаляем все классы состояний
    button.classList.remove('idle', 'running', 'completed', 'error', 'disabled');
    
    // Добавляем текущий класс состояния
    button.classList.add(state);
    
    // Обновляем текст кнопки и состояние
    switch (state) {
      case 'idle':
        button.disabled = false;
        button.textContent = this.getButtonText(button.id, 'idle');
        break;
        
      case 'running':
        button.disabled = true;
        button.textContent = `${this.getButtonText(button.id, 'running')} (${progress}%)`;
        break;
        
      case 'completed':
        button.disabled = false;
        button.textContent = this.getButtonText(button.id, 'completed');
        break;
        
      case 'error':
        button.disabled = false;
        button.textContent = this.getButtonText(button.id, 'error');
        break;
        
      case 'disabled':
        button.disabled = true;
        button.textContent = this.getButtonText(button.id, 'disabled');
        break;
    }
  }

  // Получение текста для кнопки в зависимости от состояния
  getButtonText(buttonId, state) {
    const texts = {
      'sync-btn': {
        idle: 'Синхронизировать звонки',
        running: 'Синхронизация...',
        completed: 'Звонки синхронизированы ✓',
        error: 'Ошибка синхронизации ✗',
        disabled: 'Синхронизация (заблокирована)'
      },
      'transcribe-btn': {
        idle: 'Транскрибировать',
        running: 'Транскрибация...',
        completed: 'Транскрибация завершена ✓',
        error: 'Ошибка транскрибации ✗',
        disabled: 'Транскрибация (заблокирована)'
      },
      'analyze-btn': {
        idle: 'Анализировать звонки',
        running: 'Анализ звонков...',
        completed: 'Анализ завершен ✓',
        error: 'Ошибка анализа ✗',
        disabled: 'Анализ (заблокирован)'
      },
      'recommendations-btn': {
        idle: 'Анализировать рекомендации',
        running: 'Анализ рекомендаций...',
        completed: 'Анализ рекомендаций завершен ✓',
        error: 'Ошибка анализа рекомендаций ✗',
        disabled: 'Анализ рекомендаций (заблокирован)'
      }
    };
    
    return texts[buttonId]?.[state] || 'Неизвестное состояние';
  }

  // Остановка всех процессов опроса при закрытии страницы
  destroy() {
    Object.values(this.pollingIntervals).forEach(interval => {
      clearInterval(interval);
    });
    this.pollingIntervals = {};
  }
}
```

### 2. HTML разметка с кнопками

```html
<div class="process-control-panel">
  <h3>Обработка данных клиники</h3>
  
  <div class="date-range-inputs">
    <label>
      Дата начала:
      <input type="date" id="start-date" required>
    </label>
    <label>
      Дата окончания:
      <input type="date" id="end-date" required>
    </label>
    <label>
      Client ID:
      <input type="text" id="client-id" required>
    </label>
  </div>
  
  <div class="process-buttons">
    <button id="sync-btn" class="process-btn idle">
      Синхронизировать звонки
    </button>
    
    <button id="transcribe-btn" class="process-btn idle">
      Транскрибировать
    </button>
    
    <button id="analyze-btn" class="process-btn idle">
      Анализировать звонки
    </button>
    
    <button id="recommendations-btn" class="process-btn idle">
      Анализировать рекомендации
    </button>
  </div>
  
  <div class="process-status">
    <div id="status-display"></div>
  </div>
</div>
```

### 3. CSS стили для кнопок

```css
.process-control-panel {
  max-width: 800px;
  margin: 20px auto;
  padding: 20px;
  border: 1px solid #ddd;
  border-radius: 8px;
}

.date-range-inputs {
  display: flex;
  gap: 15px;
  margin-bottom: 20px;
  flex-wrap: wrap;
}

.date-range-inputs label {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.date-range-inputs input {
  padding: 8px;
  border: 1px solid #ccc;
  border-radius: 4px;
}

.process-buttons {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 20px;
}

.process-btn {
  padding: 12px 20px;
  border: none;
  border-radius: 6px;
  font-size: 16px;
  cursor: pointer;
  transition: all 0.3s ease;
  position: relative;
  overflow: hidden;
}

/* Состояние готовности */
.process-btn.idle {
  background-color: #007bff;
  color: white;
}

.process-btn.idle:hover {
  background-color: #0056b3;
}

/* Состояние выполнения */
.process-btn.running {
  background-color: #ffc107;
  color: #212529;
  cursor: not-allowed;
  animation: pulse 2s infinite;
}

/* Состояние завершения */
.process-btn.completed {
  background-color: #28a745;
  color: white;
}

/* Состояние ошибки */
.process-btn.error {
  background-color: #dc3545;
  color: white;
}

/* Заблокированное состояние */
.process-btn.disabled {
  background-color: #6c757d;
  color: #fff;
  cursor: not-allowed;
  opacity: 0.6;
}

@keyframes pulse {
  0% {
    opacity: 1;
  }
  50% {
    opacity: 0.7;
  }
  100% {
    opacity: 1;
  }
}

.process-status {
  padding: 15px;
  background-color: #f8f9fa;
  border-radius: 6px;
  border-left: 4px solid #007bff;
}
```

### 4. Инициализация и обработчики событий

```javascript
// Инициализация контроллера процессов
const processController = new ProcessController();

// Обработчики для кнопок
document.addEventListener('DOMContentLoaded', () => {
  const syncBtn = document.getElementById('sync-btn');
  const transcribeBtn = document.getElementById('transcribe-btn');
  const analyzeBtn = document.getElementById('analyze-btn');
  const recommendationsBtn = document.getElementById('recommendations-btn');
  
  // Получение значений из полей
  const getFormData = () => {
    return {
      clientId: document.getElementById('client-id').value,
      startDate: document.getElementById('start-date').value,
      endDate: document.getElementById('end-date').value
    };
  };
  
  // Валидация данных формы
  const validateForm = (data) => {
    if (!data.clientId || !data.startDate || !data.endDate) {
      alert('Пожалуйста, заполните все поля');
      return false;
    }
    return true;
  };
  
  // Обработчик синхронизации
  syncBtn.addEventListener('click', async () => {
    const data = getFormData();
    if (!validateForm(data)) return;
    
    await processController.startSyncProcess(data.clientId, data.startDate, data.endDate);
  });
  
  // Обработчик транскрибации
  transcribeBtn.addEventListener('click', async () => {
    const data = getFormData();
    if (!validateForm(data)) return;
    
    await processController.startTranscriptionProcess(data.clientId, data.startDate, data.endDate);
  });
  
  // Обработчик анализа звонков
  analyzeBtn.addEventListener('click', async () => {
    const data = getFormData();
    if (!validateForm(data)) return;
    
    await processController.startAnalysisProcess(data.clientId, data.startDate, data.endDate);
  });
  
  // Обработчик анализа рекомендаций
  recommendationsBtn.addEventListener('click', async () => {
    const data = getFormData();
    if (!validateForm(data)) return;
    
    await processController.startRecommendationsProcess(data.clientId, data.startDate, data.endDate);
  });
});

// Очистка при выходе со страницы
window.addEventListener('beforeunload', () => {
  processController.destroy();
});
```

## Рекомендуемая последовательность выполнения процессов

1. **Синхронизация звонков** → Загружает новые звонки из AmoCRM
2. **Транскрибация** → Создает текстовые версии звонков  
3. **Анализ звонков** → Анализирует качество и создает рекомендации
4. **Анализ рекомендаций** → Обобщает рекомендации в отчет
5. **Синхронизация PostgreSQL** → Выполняется автоматически после п.4

## Возможные статусы процессов

### Статусы ответов от status эндпоинтов:
- `pending` - процесс не запущен или ожидает выполнения
- `processing` - процесс выполняется  
- `completed` - процесс полностью завершен
- `partial` - процесс завершен частично (некоторые задачи выполнены)

### Дополнительная информация в ответах:
```json
{
  "overall_status": "processing",
  "total_calls": 150,
  "status_breakdown": {
    "pending": 50,
    "processing": 10, 
    "success": 85,
    "failed": 5
  },
  "progress_percentage": 56.67
}
```

## Обработка ошибок

```javascript
// Пример обработки ошибок
const handleProcessError = (processType, error) => {
  console.error(`Error in ${processType}:`, error);
  
  // Показать уведомление пользователю
  showNotification(`Ошибка в процессе ${processType}: ${error.message}`, 'error');
  
  // Сбросить состояние процесса
  processController.setProcessStatus(processType, 'error');
  processController.activeProcess = null;
  
  // Остановить опрос статуса
  if (processController.pollingIntervals[processType]) {
    clearInterval(processController.pollingIntervals[processType]);
    delete processController.pollingIntervals[processType];
  }
};

// Функция показа уведомлений
const showNotification = (message, type = 'info') => {
  // Реализация зависит от используемой библиотеки уведомлений
  // Например, для toast уведомлений
  console.log(`[${type.toUpperCase()}] ${message}`);
};
```

## Дополнительные рекомендации

1. **Сохранение состояния**: Рассмотрите сохранение состояния процессов в localStorage для восстановления при перезагрузке страницы

2. **Уведомления**: Добавьте push-уведомления или звуковые сигналы о завершении длительных процессов

3. **Логирование**: Ведите лог выполнения процессов для диагностики проблем

4. **Таймауты**: Установите разумные таймауты для процессов и статусных запросов

5. **Кэширование**: Кэшируйте результаты статусных запросов для снижения нагрузки на API

6. **Прогресс-бар**: Добавьте визуальные индикаторы прогресса выполнения процессов
