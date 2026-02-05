import os
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Определяем базовую директорию проекта
# (app - директория с кодом приложения)
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Корневая директория проекта (на уровень выше app)
ROOT_DIR = os.path.dirname(APP_DIR)

# Директория для хранения данных
DATA_DIR = os.path.join(APP_DIR, "data")

# Директории для хранения различных типов данных
AUDIO_DIR = os.path.join(DATA_DIR, "audio")
TRANSCRIPTION_DIR = os.path.join(DATA_DIR, "transcription")
ANALYSIS_DIR = os.path.join(DATA_DIR, "analysis")
REPORTS_DIR = os.path.join(DATA_DIR, "reports")

# MongoDB конфигурация с использованием переменных окружения
MONGO_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("MONGODB_NAME", "medai")

# Директория для внешних аудиофайлов (вне приложения)
# EXTERNAL_AUDIO_DIR = os.path.join(ROOT_DIR, "audio")

# Создаем директории, если они не существуют
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(TRANSCRIPTION_DIR, exist_ok=True)
os.makedirs(ANALYSIS_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)
# os.makedirs(EXTERNAL_AUDIO_DIR, exist_ok=True)


# Удобная функция для логирования путей
def print_paths():
    print(f"Директория приложения: {APP_DIR}")
    print(f"Корневая директория: {ROOT_DIR}")
    print(f"Данные: {DATA_DIR}")
    print(f"Аудиофайлы: {AUDIO_DIR}")
    print(f"Транскрипции: {TRANSCRIPTION_DIR}")
    print(f"Анализы: {ANALYSIS_DIR}")
    print(f"Отчеты: {REPORTS_DIR}")
    # print(f"Внешние аудиофайлы: {EXTERNAL_AUDIO_DIR}")
    print(f"MongoDB URI: {MONGO_URI}")
    print(f"MongoDB Database: {DB_NAME}")
