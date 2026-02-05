import csv
from datetime import datetime

def calculate_conversion_from_postgres_csv(file_path, start_date_str, end_date_str):
    """
    Calculates conversion percentage from a CSV export of the call_criteria_metrics table.
    Assumes columns: 'day', 'criterion_name', 'total_score', 'scored_calls_count'.
    """
    sum_total_score = 0
    sum_scored_calls_count = 0
    records_processed = 0
    conversion_records_in_range = 0

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            if not all(col in reader.fieldnames for col in ['metric_date', 'criterion_name', 'total_score', 'scored_calls_count']):
                print(f"Error: CSV file {file_path} is missing one or more required columns: 'metric_date', 'criterion_name', 'total_score', 'scored_calls_count'.")
                print(f"Available columns: {reader.fieldnames}")
                return

            for row in reader:
                records_processed += 1
                try:
                    criterion_name = row.get('criterion_name')
                    day_str = row.get('metric_date') # Используем metric_date
                    
                    if criterion_name == 'Конверсия':
                        # Date filtering (string comparison for YYYY-MM-DD format)
                        if day_str and (start_date_str <= day_str <= end_date_str):
                            conversion_records_in_range += 1
                            total_score = int(row.get('total_score', 0))
                            scored_calls_count = int(row.get('scored_calls_count', 0))
                            
                            sum_total_score += total_score
                            sum_scored_calls_count += scored_calls_count
                except ValueError as ve:
                    print(f"Warning: Skipping row due to data conversion error: {row} - {ve}")
                except Exception as e:
                    print(f"Warning: Skipping row due to unexpected error: {row} - {e}")
    
    except FileNotFoundError:
        print(f"Error: File not found at {file_path}")
        return
    except Exception as e:
        print(f"An unexpected error occurred while reading the CSV file: {e}")
        return

    conversion_percentage = 0.0
    if sum_scored_calls_count > 0:
        conversion_percentage = (sum_total_score / sum_scored_calls_count) * 100

    print(f"--- Conversion Calculation Report (from PostgreSQL CSV export) ---")
    print(f"Processed CSV file: {file_path}")
    print(f"Date range: {start_date_str} to {end_date_str} (inclusive)")
    print(f"Target criterion: 'Конверсия'")
    print(f"Total rows in CSV: {records_processed}")
    print(f"'Конверсия' records found within date range: {conversion_records_in_range}")
    print(f"Sum of 'total_score' (converted): {sum_total_score}")
    print(f"Sum of 'scored_calls_count' (relevant): {sum_scored_calls_count}")
    print(f"Calculated Conversion Percentage: {conversion_percentage:.2f}%")

if __name__ == "__main__":
    # --- CONFIGURATION ---
    # Path to your CSV export from PostgreSQL
    csv_file_to_process = "/Users/mpr0/Development/[Sandbox]/medai_final/medai_backend/call_criteria_metrics.csv"
    
    # Date range (May 12 to May 31, 2025)
    start_period = "2025-05-12"
    end_period = "2025-05-31"
    # --- END CONFIGURATION ---
    
    calculate_conversion_from_postgres_csv(csv_file_to_process, start_period, end_period)
