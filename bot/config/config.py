import os
from dotenv import load_dotenv


load_dotenv()

# Конфигурация бота
BOT_TOKEN = os.getenv("BOT_TOKEN")
print("-"*20,BOT_TOKEN)

# Настройки MongoDB
MONGO_URI = os.getenv("MONGODB_URI")
DB_NAME = os.getenv("MONGODB_NAME") 

# API URLs
API_BASE_URL = os.getenv("API_BASE_URL")
API_URL = f"{API_BASE_URL}/admin/clinics"
SYNC_LEADS_API_URL = f"{API_BASE_URL}/calls-parallel-bulk/sync-by-date"
CALLS_LIST_API_URL = f"{API_BASE_URL}/calls/list"
DOWNLOAD_TRANSCRIBE_CALL_API_URL = f"{API_BASE_URL}/calls/download-and-transcribe"
ANALYZE_CALL_API_URL = f"{API_BASE_URL}/call/analyze-call-new"
GENERATE_REPORT_API_URL = f"{API_BASE_URL}/reports/generate_call_report"
DOWNLOAD_REPORT_API_URL = f"{API_BASE_URL}/call/reports/{{file_name}}/download"
GENERATE_EXCEL_REPORT_API_URL = f"{API_BASE_URL}/reports/generate-excel?start_date={{start_date}}&end_date={{end_date}}&clinic_id={{clinic_id}}"