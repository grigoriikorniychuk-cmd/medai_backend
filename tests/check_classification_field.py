import json
import os

def analyze_classification_field(filepath):
    """
    Analyzes a JSON dump to count records with 'created_date_for_filtering' 
    and 'metrics.call_type_classification'.
    """
    if not os.path.exists(filepath):
        print(f"Ошибка: Файл не найден по пути {filepath}")
        return

    total_records = 0
    records_with_date = 0
    records_with_classification = 0
    
    print(f"Анализирую файл: {filepath}...")

    with open(filepath, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
            total_records = len(data)
            for record in data:
                if isinstance(record, dict):
                    if record.get("created_date_for_filtering") is not None:
                        records_with_date += 1
                    # Проверяем вложенное поле
                    if record.get("metrics") and isinstance(record.get("metrics"), dict) and record["metrics"].get("call_type_classification") is not None:
                        records_with_classification += 1
        except json.JSONDecodeError:
            print("Ошибка: Не удалось декодировать основной JSON-массив в файле.")
            return

    print("\n--- Результаты анализа ---")
    print(f"Всего записей в файле: {total_records}")
    print(f"Записей с полем 'created_date_for_filtering': {records_with_date}")
    print(f"Записей с полем 'metrics.call_type_classification' (учитываются в 'total_calls'): {records_with_classification}")
    
    discrepancy = records_with_date - records_with_classification
    if discrepancy > 0:
        print(f"\nНайдено записей без классификации (были пропущены при расчете total_calls): {discrepancy}")
    else:
        print("\nВсе записи, подходящие для обработки, имеют поле классификации.")

if __name__ == "__main__":
    # Используем новый файл дампа, который вы упомянули
    json_file_path = '/Users/mpr0/Development/[Sandbox]/medai_final/medai_backend/medai.calls_backup.json'
    analyze_classification_field(json_file_path)
