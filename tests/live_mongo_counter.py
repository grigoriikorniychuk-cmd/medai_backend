import os
import pymongo

# Используем те же переменные окружения, что и экспортер
MONGO_URI = os.getenv("MONGO_URI_EXPORTER", "mongodb://localhost:27017/")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME_EXPORTER", "medai")
MONGO_COLLECTION_NAME = os.getenv("MONGO_COLLECTION_NAME_EXPORTER", "calls")

def count_live_records():
    """Подключается к MongoDB и считает количество записей, подходящих для экспорта."""
    client = None
    try:
        print(f"Подключаюсь к MongoDB: {MONGO_URI}...")
        client = pymongo.MongoClient(MONGO_URI)
        client.admin.command('ping') # Проверка соединения
        db = client[MONGO_DB_NAME]
        calls_collection = db[MONGO_COLLECTION_NAME]
        print(f"Успешно подключился к базе '{MONGO_DB_NAME}', коллекции '{MONGO_COLLECTION_NAME}'.")

        # Фильтр для подсчета - точно такой же, как в главном скрипте для определения диапазона дат
        query_filter = {"created_date_for_filtering": {"$exists": True, "$ne": None}}

        print("Выполняю подсчет записей с полем 'created_date_for_filtering'...")
        processable_records_count = calls_collection.count_documents(query_filter)

        print("\n--- Результат из 'живой' базы MongoDB ---")
        print(f"Найдено записей, подходящих для обработки: {processable_records_count}")

    except Exception as e:
        print(f"\nПроизошла ошибка: {e}")
    finally:
        if client:
            client.close()
            print("\nСоединение с MongoDB закрыто.")

if __name__ == "__main__":
    count_live_records()
