FROM python:3.12-slim

# Установим рабочую директорию
WORKDIR /app

# Установим переменные окружения для Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ENVIRONMENT=production

# Установим зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    wget \
    ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Копируем requirements.txt для установки зависимостей
COPY requirements.txt .

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем файлы проекта
COPY . .

# Создаем необходимые директории
RUN mkdir -p app/data/audio app/data/transcriptions app/data/analysis app/data/reports

# Экспонируем порт для FastAPI
EXPOSE 8001

# Запускаем приложение через Uvicorn
CMD ["uvicorn", "run:app", "--host", "0.0.0.0", "--port", "8001"] 