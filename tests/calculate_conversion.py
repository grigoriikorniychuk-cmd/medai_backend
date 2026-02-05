import json
from datetime import datetime # Keep for potential future use or internal consistency if needed

# Типы звонков, для которых считаем конверсию, как в postgres_exporter.py
CALL_TYPES_FOR_CONVERSION = ["первичка", "вторичка", "перезвон"]

def calculate_conversion_from_json(file_path, start_date_str, end_date_str):
    """
    Calculates conversion percentage from a JSON dump of MongoDB calls,
    using 'created_date_for_filtering' (YYYY-MM-DD string) for date matching
    and filtering by specific call types.

    Conversion is defined as:
    (calls where metrics.conversion is true) / (calls where metrics.conversion exists)
    within the specified date range and for specified call types.
    """
    
    total_relevant_calls = 0
    total_converted_calls = 0
    calls_in_date_range_and_type = 0
    records_processed = 0

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Error: File not found at {file_path}")
        return
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from {file_path}. Ensure it's a valid JSON array.")
        return
    except Exception as e:
        print(f"An unexpected error occurred while reading the file: {e}")
        return

    if not isinstance(data, list):
        print("Error: JSON data is not in the expected format (a list of call records).")
        return

    for record in data:
        records_processed += 1
        if not isinstance(record, dict):
            continue

        call_date_str = record.get("created_date_for_filtering")
        if not call_date_str or not isinstance(call_date_str, str):
            # Skip records without the crucial date field or if it's not a string
            continue
            
        # Filter by date range (string comparison YYYY-MM-DD)
        if not (start_date_str <= call_date_str <= end_date_str):
            continue
        
        metrics_data = record.get("metrics", {})
        call_type = metrics_data.get("call_type_classification") # Читаем из metrics.call_type_classification
        
        if call_type not in CALL_TYPES_FOR_CONVERSION:
            continue
            
        calls_in_date_range_and_type += 1
        
        metrics = record.get("metrics")
        if isinstance(metrics, dict):
            if "conversion" in metrics: # Check if 'conversion' key exists
                total_relevant_calls += 1
                if metrics.get("conversion") is True:
                    total_converted_calls += 1
    
    conversion_percentage = 0.0
    if total_relevant_calls > 0:
        conversion_percentage = (total_converted_calls / total_relevant_calls) * 100

    print(f"--- Conversion Calculation Report (using 'created_date_for_filtering') ---")
    print(f"Processed file: {file_path}")
    print(f"Date range: {start_date_str} to {end_date_str} (inclusive)")
    print(f"Filtered for call types: {', '.join(CALL_TYPES_FOR_CONVERSION)}")
    print(f"Total records in JSON file: {records_processed}")
    print(f"Total calls matching date range and call types: {calls_in_date_range_and_type}")
    print(f"Total calls relevant for conversion (metrics.conversion exists): {total_relevant_calls}")
    print(f"Total calls converted (metrics.conversion is true): {total_converted_calls}")
    print(f"Conversion Percentage: {conversion_percentage:.2f}%")

if __name__ == "__main__":
    # --- CONFIGURATION ---
    file_to_process = "/Users/mpr0/Development/[Sandbox]/medai_final/medai_backend/medai.calls_backup.json"
    
    # Date range as requested (May 12 to May 31, 2025)
    start_period = "2025-05-12"
    end_period = "2025-05-31"
    # --- END CONFIGURATION ---
    
    calculate_conversion_from_json(file_to_process, start_period, end_period)