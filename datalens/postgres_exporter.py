import logging
import os
import pymongo
import psycopg2
import psycopg2.extras # Для удобной вставки
from psycopg2 import sql
from psycopg2.extras import execute_values
from datetime import datetime, timedelta, date
import time
import argparse

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

MONGO_URI = os.getenv("MONGO_URI_EXPORTER", "mongodb://localhost:27017/")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME_EXPORTER", "medai")
MONGO_COLLECTION_NAME = os.getenv("MONGO_COLLECTION_NAME_EXPORTER", "calls")

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_DB = os.getenv("POSTGRES_DB", "medai_metrics")
POSTGRES_USER = os.getenv("POSTGRES_USER", "admin")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "P@sspass111")
CALL_CRITERIA_METRICS_TABLE = "call_criteria_metrics"
DAILY_SUMMARY_METRICS_TABLE = "daily_summary_metrics"
CALL_DETAILS_TABLE = "call_details"
RECOMMENDATION_ANALYSIS_TABLE = "recommendation_analysis"

# Общий список всех возможных критериев (может быть полезен для справки или будущих расширений)
ALL_POSSIBLE_CRITERIA_FIELDS = [
    "greeting", "patient_name", "needs_identification", "service_presentation",
    "clinic_presentation", "doctor_presentation", "patient_booking", "clinic_address",
    "passport", "price", "expertise", "next_step", "appointment",
    "emotional_tone", "speech", "initiative",
    # Дополнительные поля, которые могут встретиться
    "question_clarification", "appeal", "objection_handling", "address_passport"
]

# Маппинг типов звонков на их специфичные критерии и отображаемые имена
# Ключ: "сырое" имя поля из MongoDB, Значение: отображаемое имя для DataLens
CALL_TYPE_CRITERIA_MAPPING = {
    "первичка": {
        "greeting": "Приветствие", "patient_name": "Имя пациента",
        "needs_identification": "Выявление потребностей", "service_presentation": "Презентация услуги",
        "clinic_presentation": "Презентация клиники", "doctor_presentation": "Презентация врача",
        "appointment": "Запись", "price": "Цена",
        "expertise": "Экспертность", "next_step": "Следующий шаг",
        "patient_booking": "Запись на прием", "emotional_tone": "Эмоциональный окрас",
        "speech": "Речь", "initiative": "Инициатива",
        "clinic_address": "Адрес клиники", "passport": "Паспорт",
        "objection_handling": "Работа с возражениями"
    },
    "вторичка": {
        "greeting": "Приветствие", "patient_name": "Имя пациента",
        "question_clarification": "Уточнение вопроса", "expertise": "Экспертность",
        "next_step": "Следующий шаг", "patient_booking": "Запись на прием",
        "emotional_tone": "Эмоциональный окрас", "speech": "Речь",
        "initiative": "Инициатива", "objection_handling": "Работа с возражениями"
    },
    "перезвон": {
        "greeting": "Приветствие", "patient_name": "Имя пациента",
        "appeal": "Апелляция", "next_step": "Следующий шаг",
        "initiative": "Инициатива", "speech": "Речь",
        "clinic_address": "Адрес клиники", "passport": "Паспорт",
        "objection_handling": "Работа с возражениями"
    },
    "подтверждение": {
        "greeting": "Приветствие", "patient_name": "Имя пациента",
        "appeal": "Апелляция", "next_step": "Следующий шаг",
        "initiative": "Инициатива", "speech": "Речь",
        "clinic_address": "Адрес клиники", "passport": "Паспорт",
        "objection_handling": "Работа с возражениями"
    }
}

# Максимальная оценка для расчета FG% всегда равна 10
MAX_OVERALL_SCORE = 10

# Используется для обратной совместимости или если тип звонка не найден в маппинге
DEFAULT_CRITERIA_FIELDS_DISPLAY_NAMES = CALL_TYPE_CRITERIA_MAPPING.get("первичка")

def get_mongo_connection():
    """Устанавливает соединение с MongoDB."""
    try:
        client = pymongo.MongoClient(MONGO_URI)
        client.admin.command('ping')
        db = client[MONGO_DB_NAME]
        calls_collection = db[MONGO_COLLECTION_NAME]
        logging.info(f"Successfully connected to MongoDB: {MONGO_URI}")
        return calls_collection, client
    except Exception as e:
        logging.error(f"Failed to connect to MongoDB: {e}")
        return None, None

def get_postgres_connection():
    """Устанавливает соединение с PostgreSQL, создавая БД, если она не существует."""
    conn_params = {
        "host": POSTGRES_HOST,
        "port": POSTGRES_PORT,
        "dbname": POSTGRES_DB,
        "user": POSTGRES_USER,
        "password": POSTGRES_PASSWORD
    }
    try:
        conn = psycopg2.connect(**conn_params)
        logging.info(f"Successfully connected to PostgreSQL DB: {conn_params['dbname']}")
        return conn
    except psycopg2.OperationalError as e:
        if f'database "{conn_params["dbname"]}" does not exist' in str(e):
            logging.warning(f"Database '{conn_params['dbname']}' does not exist. Attempting to create it.")
            try:
                temp_conn_params = conn_params.copy()
                temp_conn_params['dbname'] = 'postgres'
                conn_template = psycopg2.connect(**temp_conn_params)
                conn_template.autocommit = True
                with conn_template.cursor() as cur_template:
                    cur_template.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(conn_params['dbname'])))
                conn_template.close()
                logging.info(f"Database '{conn_params['dbname']}' created successfully.")
                conn = psycopg2.connect(**conn_params)
                logging.info(f"Successfully connected to newly created PostgreSQL DB: {conn_params['dbname']}")
                return conn
            except Exception as e_create:
                logging.error(f"Failed to create or connect to database '{conn_params['dbname']}': {e_create}")
                return None
        else:
            logging.error(f"Failed to connect to PostgreSQL: {e}")
            return None

def create_call_criteria_metrics_table(conn):
    """Создает таблицу для хранения метрик по критериям звонков."""
    try:
        with conn.cursor() as cursor:
            create_table_query = sql.SQL("""
            CREATE TABLE IF NOT EXISTS {table} (
                id SERIAL PRIMARY KEY,
                metric_date DATE NOT NULL,
                week_start_date DATE,
                client_id VARCHAR(255) NOT NULL,
                subdomain VARCHAR(255),
                administrator VARCHAR(255),
                call_direction VARCHAR(50),
                source VARCHAR(255),
                call_type VARCHAR(255),
                criterion_name VARCHAR(255) NOT NULL,
                total_score NUMERIC,
                scored_calls_count INTEGER,
                avg_score NUMERIC,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (metric_date, client_id, subdomain, administrator, call_direction, source, call_type, criterion_name)
            );
            """).format(table=sql.Identifier(CALL_CRITERIA_METRICS_TABLE))
            cursor.execute(create_table_query)
            indexes = {
                "idx_crit_metric_date": "metric_date",
                "idx_crit_client_id": "client_id",
                "idx_crit_call_type": "call_type",
                "idx_crit_criterion_name": "criterion_name"
            }
            for idx_name, col_name in indexes.items():
                cursor.execute(sql.SQL("CREATE INDEX IF NOT EXISTS {idx} ON {table} ({col});").format(
                    idx=sql.Identifier(idx_name),
                    table=sql.Identifier(CALL_CRITERIA_METRICS_TABLE),
                    col=sql.Identifier(col_name)
                ))
            conn.commit()
            logging.info(f"Table '{CALL_CRITERIA_METRICS_TABLE}' and its indexes are ready.")
    except Exception as e:
        logging.error(f"Error creating table '{CALL_CRITERIA_METRICS_TABLE}': {e}")
        conn.rollback()

def create_daily_summary_metrics_table(conn):
    """Создает таблицу для хранения ежедневных сводных метрик."""
    try:
        with conn.cursor() as cursor:
            create_table_query = sql.SQL("""
            CREATE TABLE IF NOT EXISTS {table} (
                id SERIAL PRIMARY KEY,
                metric_date DATE NOT NULL,
                week_start_date DATE,
                client_id VARCHAR(255) NOT NULL,
                subdomain VARCHAR(255),
                administrator VARCHAR(255),
                call_direction VARCHAR(50),
                source VARCHAR(255),
                call_type VARCHAR(255),
                total_calls INTEGER,
                converted_calls INTEGER,
                conversion_rate NUMERIC,
                total_duration_seconds INTEGER,
                avg_duration_seconds NUMERIC,
                total_overall_score NUMERIC,
                scored_calls_count INTEGER,
                fg_percent NUMERIC,
                total_processing_speed_minutes NUMERIC,
                calls_with_processing_speed_count INTEGER,
                avg_processing_speed_minutes NUMERIC,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (metric_date, client_id, subdomain, administrator, call_direction, source, call_type)
            );
            """).format(table=sql.Identifier(DAILY_SUMMARY_METRICS_TABLE))
            cursor.execute(create_table_query)
            indexes = {
                "idx_sum_metric_date": "metric_date",
                "idx_sum_client_id": "client_id",
                "idx_sum_call_type": "call_type"
            }
            for idx_name, col_name in indexes.items():
                cursor.execute(sql.SQL("CREATE INDEX IF NOT EXISTS {idx} ON {table} ({col});").format(
                    idx=sql.Identifier(idx_name),
                    table=sql.Identifier(DAILY_SUMMARY_METRICS_TABLE),
                    col=sql.Identifier(col_name)
                ))
            conn.commit()
            logging.info(f"Table '{DAILY_SUMMARY_METRICS_TABLE}' and its indexes are ready.")
    except Exception as e:
        logging.error(f"Error creating table '{DAILY_SUMMARY_METRICS_TABLE}': {e}")
        conn.rollback()

def create_call_details_table(conn):
    """Создает таблицу call_details, если она не существует."""
    create_table_query = """
    CREATE TABLE IF NOT EXISTS call_details (
        call_mongo_id TEXT PRIMARY KEY,
        metric_date DATE,
        administrator TEXT,
        transcript_url TEXT,
        recording_url TEXT,
        recommendations_text TEXT,
        client_id TEXT,
        subdomain TEXT,
        call_id TEXT -- Если есть отдельный call_id, который тоже нужен
    );
    """
    try:
        with conn.cursor() as cur:
            cur.execute(create_table_query)
        conn.commit()
        logging.info("Таблица 'call_details' проверена/создана.")
    except Exception as e:
        logging.error(f"Ошибка при создании таблицы 'call_details': {e}")
        conn.rollback()

def process_and_insert_criteria_metrics(calls_collection, pg_conn, start_date, end_date):
    """Агрегирует и вставляет метрики по критериям."""
    logging.info("Starting processing of criteria metrics.")
    records_to_insert = []
    current_day = start_date
    while current_day <= end_date:
        target_date_str = current_day.strftime('%Y-%m-%d')
        week_start_date = current_day - timedelta(days=current_day.weekday())
        call_types_in_day = calls_collection.distinct("metrics.call_type_classification", {"created_date_for_filtering": target_date_str})
        logging.info(f"Processing date: {target_date_str}. Found call types: {call_types_in_day}")
        for call_type in call_types_in_day:
            if not call_type: continue
            criteria_map = CALL_TYPE_CRITERIA_MAPPING.get(call_type, DEFAULT_CRITERIA_FIELDS_DISPLAY_NAMES)

            # Получаем список всех валидных ключей для данного типа звонка
            all_valid_keys = list(criteria_map.keys())

            # Исправленный оригинальный конвейер
            pipeline = [
                {"$match": {
                    "created_date_for_filtering": target_date_str,
                    "metrics.call_type_classification": call_type,
                    "metrics": {"$exists": True, "$ne": None, "$type": "object"}, # Убедимся, что metrics существует и является объектом
                    "transcription_status": "success",  # Только успешные транскрипции
                    "recommendations": {"$exists": True, "$ne": None, "$ne": []}  # Исключаем пустые
                }},
                {"$project": {
                    "labels": {"client_id": "$client_id", "subdomain": "$subdomain", "administrator": "$administrator", "call_direction": "$call_direction", "source": "$source"},
                    "criteria_scores": {"$objectToArray": "$metrics"}  # Используем $metrics напрямую
                }},
                {"$unwind": "$criteria_scores"},
                # Фильтруем только те ключи из metrics, которые есть в нашем criteria_map и не являются call_type_classification или overall_score_max_10
                {"$match": {
                    "criteria_scores.k": {
                        "$in": all_valid_keys,  # ← ИЗМЕНЕНО: включаем старые ключи
                        "$nin": ["call_type_classification", "overall_score_max_10", "overall_score"] # Исключаем служебные поля из критериев
                    }
                }},
                {"$group": {
                    "_id": {"labels": "$labels", "criterion_key": "$criteria_scores.k"},
                    "total_score": {"$sum": "$criteria_scores.v"}, # Суммируем напрямую значения v
                    "scored_calls_count": {"$sum": 1}
                }}
            ]
            try:
                results = list(calls_collection.aggregate(pipeline))
                logging.info(f"Date: {target_date_str}, Call Type: {call_type}. Original aggregation results count: {len(results)}.")
                for r in results:
                    labels = r['_id']['labels']
                    key = r['_id']['criterion_key']
                    total = r.get('total_score', 0)
                    count = r.get('scored_calls_count', 0)
                    avg = total / count if count > 0 else None

                    # Получаем читаемое название критерия
                    display_name = criteria_map.get(key, key)

                    records_to_insert.append((current_day, week_start_date, labels.get('client_id'), labels.get('subdomain'), labels.get('administrator'), labels.get('call_direction'), labels.get('source'), call_type, display_name, total, count, avg))
            except Exception as e:
                logging.error(f"Error aggregating criteria for {target_date_str}, {call_type}: {e}")
        current_day += timedelta(days=1)
    logging.info(f"Найдено {len(records_to_insert)} записей для таблицы {CALL_CRITERIA_METRICS_TABLE} для вставки.")
    if records_to_insert:
        logging.info(f"Preparing to insert/update {len(records_to_insert)} criteria metric records into {CALL_CRITERIA_METRICS_TABLE}.")
        try:
            with pg_conn.cursor() as cursor:
                cols = [
                    "metric_date", "week_start_date", "client_id", "subdomain", 
                    "administrator", "call_direction", "source", "call_type", 
                    "criterion_name", "total_score", "scored_calls_count", "avg_score"
                ]
                conflict_columns = [
                    "metric_date", "client_id", "subdomain", "administrator", 
                    "call_direction", "source", "call_type", "criterion_name"
                ]
                update_columns = ["total_score", "scored_calls_count", "avg_score"]
                
                update_assignments = [sql.SQL("{col} = EXCLUDED.{col}").format(col=sql.Identifier(c)) for c in update_columns]
                
                query_template = sql.SQL("INSERT INTO {table} ({cols}) VALUES %s ON CONFLICT ({conflict_cols}) DO UPDATE SET {update_assignments_sql}")
                
                query = query_template.format(
                    table=sql.Identifier(CALL_CRITERIA_METRICS_TABLE),
                    cols=sql.SQL(', ').join(map(sql.Identifier, cols)),
                    conflict_cols=sql.SQL(', ').join(map(sql.Identifier, conflict_columns)),
                    update_assignments_sql=sql.SQL(', ').join(update_assignments)
                )
                
                execute_values(cursor, query, records_to_insert, page_size=200)
                pg_conn.commit()
                logging.info(f"Successfully inserted/updated {len(records_to_insert)} criteria metric records into {CALL_CRITERIA_METRICS_TABLE}.")
        except Exception as e:
            logging.error(f"Error inserting/updating criteria metrics into {CALL_CRITERIA_METRICS_TABLE}: {e}")
            pg_conn.rollback()

def process_and_insert_summary_metrics(calls_collection, pg_conn, start_date, end_date):
    """Агрегирует, рассчитывает и вставляет сводные дневные метрики."""
    logging.info("Starting processing of daily summary metrics.")
    records_to_insert = []
    current_day = start_date
    while current_day <= end_date:
        target_date_str = current_day.strftime('%Y-%m-%d')
        week_start_date = current_day - timedelta(days=current_day.weekday())
        pipeline = [
            {"$match": {
                "created_date_for_filtering": target_date_str,
                "transcription_status": "success",  # Только успешные транскрипции
                "recommendations": {"$exists": True, "$ne": None, "$ne": []}  # Исключаем пустые
            }},
            {"$group": {
                "_id": {
                    "client_id": "$client_id", "subdomain": "$subdomain", "administrator": "$administrator",
                    "call_direction": "$call_direction", "source": "$source", "call_type": "$metrics.call_type_classification"
                },
                "total_calls": {"$sum": 1},
                "converted_calls": {"$sum": {"$cond": [{"$eq": ["$metrics.conversion", True]}, 1, 0]}},
                "total_duration_seconds": {"$sum": {"$ifNull": ["$duration", 0]}},
                "total_overall_score": {"$sum": {"$ifNull": ["$metrics.overall_score", 0]}},
                "scored_calls_count": {"$sum": {"$cond": [{"$ifNull": ["$metrics.overall_score", None]}, 1, 0]}},
                "total_processing_speed": {"$sum": {"$cond": [{"$and": [{"$ne": ["$processing_speed", None]}, {"$ne": ["$processing_speed", 0]}]}, "$processing_speed", 0]}},
                "calls_with_processing_speed_count": {"$sum": {"$cond": [{"$and": [{"$ne": ["$processing_speed", None]}, {"$ne": ["$processing_speed", 0]}]}, 1, 0]}}
            }}
        ]
        try:
            results = list(calls_collection.aggregate(pipeline))
            for r in results:
                labels = r['_id']
                call_type = labels.get('call_type')
                if not call_type: continue
                total_calls = r.get('total_calls', 0)
                converted_calls = r.get('converted_calls', 0)
                total_duration = r.get('total_duration_seconds', 0)
                total_score = r.get('total_overall_score', 0)
                scored_calls = r.get('scored_calls_count', 0)
                total_speed = r.get('total_processing_speed', 0)
                speed_calls = r.get('calls_with_processing_speed_count', 0)
                conversion_rate = converted_calls / total_calls if total_calls > 0 else None
                avg_duration = total_duration / total_calls if total_calls > 0 else None
                avg_score = total_score / scored_calls if scored_calls > 0 else None
                fg_percent = (avg_score / MAX_OVERALL_SCORE) * 100 if avg_score is not None else None
                avg_speed = total_speed / speed_calls if speed_calls > 0 else None
                records_to_insert.append((current_day, week_start_date, labels.get('client_id'), labels.get('subdomain'), labels.get('administrator'), labels.get('call_direction'), labels.get('source'), call_type, total_calls, converted_calls, conversion_rate, total_duration, avg_duration, total_score, scored_calls, fg_percent, total_speed, speed_calls, avg_speed))
        except Exception as e:
            logging.error(f"Error aggregating summary metrics for {target_date_str}: {e}")
        current_day += timedelta(days=1)
    logging.info(f"Найдено {len(records_to_insert)} записей для таблицы {DAILY_SUMMARY_METRICS_TABLE} для вставки.")
    if records_to_insert:
        logging.info(f"Inserting/updating {len(records_to_insert)} summary metric records.")
        try:
            with pg_conn.cursor() as cursor:
                cols = ["metric_date", "week_start_date", "client_id", "subdomain", "administrator", "call_direction", "source", "call_type", "total_calls", "converted_calls", "conversion_rate", "total_duration_seconds", "avg_duration_seconds", "total_overall_score", "scored_calls_count", "fg_percent", "total_processing_speed_minutes", "calls_with_processing_speed_count", "avg_processing_speed_minutes"]
                conflict = ["metric_date", "client_id", "subdomain", "administrator", "call_direction", "source", "call_type"]
                update_cols = [c for c in cols if c not in conflict and c not in ["id", "created_at", "week_start_date"]]
                update_assignments = [sql.SQL("{col} = EXCLUDED.{col}").format(col=sql.Identifier(c)) for c in update_cols]
                query = sql.SQL("INSERT INTO {table} ({cols}) VALUES %s ON CONFLICT ({conflict}) DO UPDATE SET {update}").format(
                    table=sql.Identifier(DAILY_SUMMARY_METRICS_TABLE),
                    cols=sql.SQL(', ').join(map(sql.Identifier, cols)),
                    conflict=sql.SQL(', ').join(map(sql.Identifier, conflict)),
                    update=sql.SQL(', ').join(update_assignments)
                )
                execute_values(cursor, query, records_to_insert, page_size=200)
                pg_conn.commit()
        except Exception as e:
            logging.error(f"Error inserting summary metrics: {e}")
            pg_conn.rollback()

def process_and_insert_call_details(calls_collection, pg_conn, start_date, end_date):
    """Извлекает детали звонков из MongoDB и вставляет их в PostgreSQL."""
    logging.info(f"Начинается обработка деталей звонков за период с {start_date.strftime('%Y-%m-%d')} по {end_date.strftime('%Y-%m-%d')}")

    records_to_insert = []
    current_date = start_date
    while current_date <= end_date:
        target_date_str = current_date.strftime("%Y-%m-%d")
        logging.info(f"Обработка деталей звонков для даты: {target_date_str}")

        query = {
            "created_date_for_filtering": target_date_str,
            "filename_transcription": {"$exists": True, "$ne": None, "$ne": ""},
            "call_link": {"$exists": True, "$ne": None, "$ne": ""},
            "recommendations": {"$exists": True, "$ne": None, "$ne": []},  # Исключаем пустые массивы
            "transcription_status": "success"  # Только успешные транскрипции
        }
        
        projection = {
            "_id": 1,
            "created_date_for_filtering": 1,
            "administrator": 1,
            "filename_transcription": 1,
            "call_link": 1,
            "recommendations": 1,
            "client_id": 1,
            "subdomain": 1,
            "call_id": 1,
            "metrics.call_type_classification": 1,
            "efficiency": 1  # Добавляем поле эффективности
        }

        try:
            retrieved_calls = list(calls_collection.find(query, projection))
            logging.info(f"Найдено {len(retrieved_calls)} звонков с деталями для {target_date_str}.")
        except Exception as e:
            logging.error(f"Ошибка при запросе деталей звонков из MongoDB для {target_date_str}: {e}")
            current_date += timedelta(days=1)
            continue

        for call in retrieved_calls:
            try:
                mongo_id_str = str(call.get("_id"))
                metric_dt = datetime.strptime(call.get("created_date_for_filtering"), "%Y-%m-%d").date()
                admin = call.get("administrator", "Не указан")
                
                filename_transcription = call.get("filename_transcription")
                transcript_url = f"https://api.mlab-electronics.ru/api/transcriptions/{filename_transcription}/download" if filename_transcription else None
                
                recording_url = call.get("call_link")
                
                recommendations_list = call.get("recommendations", [])
                recommendations_text = "\n".join(recommendations_list) if recommendations_list else None

                client_id = call.get("client_id")
                subdomain = call.get("subdomain")
                call_id_field = call.get("call_id")
                
                # Извлекаем call_type из metrics
                metrics = call.get("metrics", {})
                call_type = metrics.get("call_type_classification") if isinstance(metrics, dict) else None
                
                # Для типа "другое" без рекомендаций ставим прочерк
                if call_type == "другое" and not recommendations_text:
                    recommendations_text = "-"
                
                # Извлекаем эффективность
                efficiency = call.get("efficiency", {})
                is_effective = efficiency.get("is_effective") if isinstance(efficiency, dict) else None
                matched_criteria_list = efficiency.get("matched_criteria", [])
                matched_criteria_str = ", ".join(matched_criteria_list) if matched_criteria_list else None

                records_to_insert.append((
                    mongo_id_str, metric_dt, admin, transcript_url, 
                    recording_url, recommendations_text, client_id, subdomain, call_id_field, call_type,
                    is_effective, matched_criteria_str  # Добавляем поля эффективности
                ))
            except Exception as e:
                logging.error(f"Ошибка при обработке звонка {call.get('_id')}: {e}. Пропускаем.")
                continue
        
        current_date += timedelta(days=1)

    logging.info(f"Найдено {len(records_to_insert)} записей для таблицы {CALL_DETAILS_TABLE} для вставки.")
    if not records_to_insert:
        logging.info("Нет деталей звонков для вставки.")
        return

    insert_query = """
    INSERT INTO call_details (
        call_mongo_id, metric_date, administrator, transcript_url, 
        recording_url, recommendations_text, client_id, subdomain, call_id, call_type,
        is_effective, matched_criteria
    ) VALUES %s
    ON CONFLICT (call_mongo_id) DO UPDATE SET
        metric_date = EXCLUDED.metric_date,
        administrator = EXCLUDED.administrator,
        transcript_url = EXCLUDED.transcript_url,
        recording_url = EXCLUDED.recording_url,
        recommendations_text = EXCLUDED.recommendations_text,
        client_id = EXCLUDED.client_id,
        subdomain = EXCLUDED.subdomain,
        call_id = EXCLUDED.call_id,
        call_type = EXCLUDED.call_type,
        is_effective = EXCLUDED.is_effective,
        matched_criteria = EXCLUDED.matched_criteria;
    """
    try:
        with pg_conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur, insert_query, records_to_insert,
                template=None, page_size=100
            )
        pg_conn.commit()
        logging.info(f"Успешно вставлено/обновлено {len(records_to_insert)} записей в 'call_details'.")
    except Exception as e:
        logging.error(f"Ошибка при вставке деталей звонков в PostgreSQL: {e}")
        pg_conn.rollback()



def create_recommendation_analysis_table(pg_conn):
    """Создает таблицу для хранения результатов анализа рекомендаций, если она не существует."""
    create_table_query = sql.SQL("""
    CREATE TABLE IF NOT EXISTS {} (
        id SERIAL PRIMARY KEY,
        client_id VARCHAR(255) NOT NULL,
        start_date DATE NOT NULL,
        end_date DATE NOT NULL,
        period_type VARCHAR(20) DEFAULT 'weekly',
        summary_points TEXT[],
        overall_summary TEXT,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(client_id, start_date, end_date, period_type)
    );
    """).format(sql.Identifier(RECOMMENDATION_ANALYSIS_TABLE))
    try:
        with pg_conn.cursor() as cur:
            cur.execute(create_table_query)
        pg_conn.commit()
        logging.info(f"Таблица '{RECOMMENDATION_ANALYSIS_TABLE}' проверена/создана.")
    except Exception as e:
        logging.error(f"Ошибка при создании таблицы '{RECOMMENDATION_ANALYSIS_TABLE}': {e}")
        pg_conn.rollback()

def process_and_insert_recommendation_analysis(mongo_db, pg_conn):
    """Извлекает обобщенные рекомендации из MongoDB и вставляет их в PostgreSQL."""
    analysis_collection = mongo_db.recommendation_analysis_results
    
    try:
        results = list(analysis_collection.find({}))
        logging.info(f"Найдено {len(results)} записей для таблицы '{RECOMMENDATION_ANALYSIS_TABLE}' в MongoDB.")
    except Exception as e:
        logging.error(f"Ошибка при запросе данных из MongoDB для '{RECOMMENDATION_ANALYSIS_TABLE}': {e}")
        return

    if not results:
        logging.info(f"Нет данных для '{RECOMMENDATION_ANALYSIS_TABLE}'. Пропускаем.")
        return

    records_to_insert = []
    for res in results:
        analysis_data = res.get('analysis_data', {})
        # Определяем period_type: если есть в документе - используем, иначе 'weekly'
        period_type = res.get('period_type', 'weekly')
        records_to_insert.append((
            res.get('client_id'),
            res.get('start_date'),
            res.get('end_date'),
            period_type,
            analysis_data.get('summary_points', []),
            analysis_data.get('overall_summary', ''),
            res.get('created_at')
        ))

    logging.info(f"Подготовлено {len(records_to_insert)} записей для вставки в '{RECOMMENDATION_ANALYSIS_TABLE}'.")

    if not records_to_insert:
        return

    try:
        insert_query = sql.SQL("""
        INSERT INTO {} (client_id, start_date, end_date, period_type, summary_points, overall_summary, created_at)
        VALUES %s
        ON CONFLICT (client_id, start_date, end_date, period_type) DO UPDATE SET
            summary_points = EXCLUDED.summary_points,
            overall_summary = EXCLUDED.overall_summary,
            created_at = EXCLUDED.created_at;
        """).format(sql.Identifier(RECOMMENDATION_ANALYSIS_TABLE))

        with pg_conn.cursor() as cur:
            execute_values(cur, insert_query, records_to_insert, page_size=100)
        pg_conn.commit()
        logging.info(f"Успешно вставлено/обновлено {len(records_to_insert)} записей в '{RECOMMENDATION_ANALYSIS_TABLE}'.")

    except Exception as e:
        logging.error(f"Ошибка при обработке и вставке аналитики рекомендаций: {e}")
        pg_conn.rollback()

def aggregate_and_store_metrics():
    """Координирует процесс агрегации и сохранения метрик."""
    calls_collection, mongo_client = get_mongo_connection()
    pg_conn = get_postgres_connection()
    if calls_collection is None or pg_conn is None:
        logging.error("Aborting due to connection failure.")
        if mongo_client: mongo_client.close()
        if pg_conn: pg_conn.close()
        return
    create_call_criteria_metrics_table(pg_conn)
    create_daily_summary_metrics_table(pg_conn)
    create_call_details_table(pg_conn)
    create_recommendation_analysis_table(pg_conn)
    try:
        date_range_pipeline = [
            {"$match": {"created_date_for_filtering": {"$exists": True, "$ne": None}}},
            {"$group": {"_id": None, "min_date": {"$min": "$created_date_for_filtering"}, "max_date": {"$max": "$created_date_for_filtering"}}}
        ]
        date_range_result = list(calls_collection.aggregate(date_range_pipeline))
        if not date_range_result or not date_range_result[0].get('min_date'):
            logging.warning("Could not determine date range from MongoDB. No data to process.")
            return
        start_date = datetime.strptime(date_range_result[0]['min_date'], '%Y-%m-%d').date()
        end_date = datetime.strptime(date_range_result[0]['max_date'], '%Y-%m-%d').date()
        logging.info(f"Determined data processing range: {start_date} to {end_date}")
        process_and_insert_summary_metrics(calls_collection, pg_conn, start_date, end_date)
        process_and_insert_criteria_metrics(calls_collection, pg_conn, start_date, end_date)
        process_and_insert_call_details(calls_collection, pg_conn, start_date, end_date)
        # Для анализа рекомендаций нам нужна вся база, а не диапазон дат
        mongo_db = mongo_client[MONGO_DB_NAME]
        process_and_insert_recommendation_analysis(mongo_db, pg_conn)
    except Exception as e:
        logging.error(f"An error occurred during the main processing loop: {e}")
    finally:
        if pg_conn: pg_conn.close(); logging.info("PostgreSQL connection closed.")
        if mongo_client: mongo_client.close(); logging.info("MongoDB connection closed.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PostgreSQL Metrics Exporter")
    parser.add_argument('--once', action='store_true', help='Run the export process once and exit.')
    args = parser.parse_args()

    if args.once:
        logging.info("PostgreSQL exporter running once.")
        aggregate_and_store_metrics()
        logging.info("PostgreSQL exporter finished its run.")
    else:
        logging.warning("Exporter must be run with the --once flag. Exiting.")
