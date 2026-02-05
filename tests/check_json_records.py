import json
import os

def analyze_json_dump(filepath):
    """
    Analyzes a JSON dump file to count total records and records with a specific key.
    The file is expected to contain one JSON object per line.
    """
    if not os.path.exists(filepath):
        print(f"Ошибка: Файл не найден по пути {filepath}")
        return

    total_records = 0
    records_with_date_field = 0
    
    print(f"Анализирую файл: {filepath}...")

    with open(filepath, 'r', encoding='utf-8') as f:
        # Пытаемся прочитать весь файл как один JSON-массив
        try:
            data = json.load(f)
            if not isinstance(data, list):
                print("Ошибка: JSON в файле не является списком объектов.")
                return
            
            total_records = len(data)
            for record in data:
                if isinstance(record, dict) and record.get("created_date_for_filtering") is not None:
                    records_with_date_field += 1

        except json.JSONDecodeError:
            # Если это не сработало, пробуем читать построчно
            f.seek(0)
            total_records = 0
            records_with_date_field = 0
            for line in f:
                if not line.strip():
                    continue
                total_records += 1
                try:
                    record = json.loads(line)
                    if record.get("created_date_for_filtering") is not None:
                        records_with_date_field += 1
                except json.JSONDecodeError:
                    print(f"Предупреждение: Не удалось декодировать JSON в строке {total_records}. Пропускаю.")
                    continue

    print("\n--- Результаты анализа ---")
    print(f"Всего записей в файле: {total_records}")
    print(f"Записей с полем 'created_date_for_filtering': {records_with_date_field}")
    
    discrepancy = total_records - records_with_date_field
    if discrepancy > 0:
        print(f"Записей без 'created_date_for_filtering' (были пропущены экспортером): {discrepancy}")
    else:
        print("Все записи содержат необходимое поле 'created_date_for_filtering'.")

if __name__ == "__main__":
    json_file_path = '/Users/mpr0/Development/[Sandbox]/medai_final/medai_backend/medai.calls_backup.json'
    analyze_json_dump(json_file_path)
