"""
Тест для проверки расчёта средних баллов по критериям.

Сравниваем:
1. Расчёт в recommendation_analysis_service.py
2. Расчёт в generate_report.py (для PDF таблицы)
3. Данные в PostgreSQL (для DataLens)

Запуск:
    cd /home/mpr0/Develop/medai_backend
    source venv/bin/activate
    python tests/test_weekly_scores_calculation.py --client_id <CLIENT_ID> --start_date 2025-11-25 --end_date 2025-12-01
"""

import asyncio
import argparse
from datetime import date, datetime
from motor.motor_asyncio import AsyncIOMotorClient
import psycopg2
import os

# Настройки MongoDB
MONGO_URI = os.getenv("MONGO_URI", "mongodb://92.113.151.220:27018/")
MONGO_DB = "medai"

# Настройки PostgreSQL
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "92.113.151.220")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_DB = os.getenv("POSTGRES_DB", "medai_metrics")
POSTGRES_USER = os.getenv("POSTGRES_USER", "admin")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "P@sspass111")

# Список критериев для проверки
CRITERIA = [
    'greeting', 'patient_name', 'appeal', 'needs_identification',
    'service_presentation', 'clinic_presentation', 'doctor_presentation',
    'patient_booking', 'clinic_address', 'passport', 'next_step',
    'initiative', 'speech', 'expertise', 'price', 'emotional_tone'
]

CRITERIA_NAMES = {
    'greeting': 'Приветствие',
    'patient_name': 'Имя пациента',
    'appeal': 'Апелляция',
    'needs_identification': 'Выявление потребностей',
    'service_presentation': 'Презентация услуги',
    'clinic_presentation': 'Презентация клиники',
    'doctor_presentation': 'Презентация врача',
    'patient_booking': 'Запись на прием',
    'clinic_address': 'Адрес клиники',
    'passport': 'Паспорт',
    'next_step': 'Следующий шаг',
    'initiative': 'Инициатива',
    'speech': 'Речь',
    'expertise': 'Экспертность',
    'price': 'Цена',
    'emotional_tone': 'Эмоциональный тон'
}


async def calculate_from_mongodb(client_id: str, start_date: str, end_date: str) -> dict:
    """
    Расчёт средних баллов напрямую из MongoDB.
    Это то, что делает recommendation_analysis_service.py
    """
    client = AsyncIOMotorClient(MONGO_URI)
    db = client[MONGO_DB]
    calls = db.calls
    
    query = {
        "client_id": client_id,
        "created_date_for_filtering": {
            "$gte": start_date,
            "$lte": end_date
        }
    }
    
    cursor = calls.find(query, {"metrics": 1})
    
    criteria_values = {c: [] for c in CRITERIA}
    total_calls = 0
    calls_with_metrics = 0
    
    async for doc in cursor:
        total_calls += 1
        metrics = doc.get("metrics")
        if metrics and isinstance(metrics, dict):
            calls_with_metrics += 1
            for criterion in CRITERIA:
                value = metrics.get(criterion)
                if isinstance(value, (int, float)) and value >= 0:
                    criteria_values[criterion].append(value)
    
    client.close()
    
    # Вычисляем средние
    avg_scores = {}
    for criterion, values in criteria_values.items():
        if values:
            avg_scores[criterion] = round(sum(values) / len(values), 1)
    
    return {
        "source": "MongoDB (recommendation_analysis_service)",
        "total_calls": total_calls,
        "calls_with_metrics": calls_with_metrics,
        "avg_scores": avg_scores
    }


def calculate_from_postgres(client_id: str, start_date: str, end_date: str) -> dict:
    """
    Расчёт средних баллов из PostgreSQL.
    Это то, что видит DataLens.
    """
    try:
        conn = psycopg2.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            dbname=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD
        )
        
        cursor = conn.cursor()
        
        # Запрос средних по критериям за период
        query = """
            SELECT criterion_name, 
                   SUM(total_score) as total_score,
                   SUM(scored_calls_count) as total_count,
                   CASE WHEN SUM(scored_calls_count) > 0 
                        THEN ROUND(SUM(total_score) / SUM(scored_calls_count), 1)
                        ELSE 0 END as avg_score
            FROM call_criteria_metrics
            WHERE client_id = %s
              AND metric_date >= %s
              AND metric_date <= %s
            GROUP BY criterion_name
            ORDER BY criterion_name
        """
        
        cursor.execute(query, (client_id, start_date, end_date))
        rows = cursor.fetchall()
        
        avg_scores = {}
        for row in rows:
            criterion_name = row[0]
            avg_score = float(row[3]) if row[3] else 0
            avg_scores[criterion_name] = avg_score
        
        cursor.close()
        conn.close()
        
        return {
            "source": "PostgreSQL (DataLens)",
            "avg_scores": avg_scores
        }
    except Exception as e:
        return {
            "source": "PostgreSQL (DataLens)",
            "error": str(e),
            "avg_scores": {}
        }


def classify_criteria(avg_scores: dict) -> dict:
    """Классификация критериев по зонам"""
    classification = {
        'strong': [],    # 8-10
        'growth': [],    # 5-7
        'critical': []   # 0-4
    }
    
    for criterion, score in avg_scores.items():
        name = CRITERIA_NAMES.get(criterion, criterion)
        
        if score >= 8:
            classification['strong'].append((name, score))
        elif score >= 5:
            classification['growth'].append((name, score))
        else:
            classification['critical'].append((name, score))
    
    return classification


def print_comparison(mongo_result: dict, postgres_result: dict):
    """Выводит сравнение результатов"""
    print("\n" + "="*80)
    print("📊 СРАВНЕНИЕ РАСЧЁТОВ СРЕДНИХ БАЛЛОВ ПО КРИТЕРИЯМ")
    print("="*80)
    
    print(f"\n📁 MongoDB: {mongo_result['total_calls']} звонков, {mongo_result['calls_with_metrics']} с метриками")
    
    if "error" in postgres_result:
        print(f"\n⚠️ PostgreSQL: Ошибка - {postgres_result['error']}")
    
    print("\n" + "-"*80)
    print(f"{'Критерий':<25} {'MongoDB':<12} {'PostgreSQL':<12} {'Разница':<10} {'Статус'}")
    print("-"*80)
    
    mongo_scores = mongo_result['avg_scores']
    postgres_scores = postgres_result.get('avg_scores', {})
    
    discrepancies = []
    
    for criterion in CRITERIA:
        name = CRITERIA_NAMES.get(criterion, criterion)
        mongo_val = mongo_scores.get(criterion, '-')
        
        # Ищем в PostgreSQL по русскому названию
        postgres_val = postgres_scores.get(name, '-')
        
        if isinstance(mongo_val, (int, float)) and isinstance(postgres_val, (int, float)):
            diff = abs(mongo_val - postgres_val)
            status = "✅" if diff < 0.5 else "⚠️" if diff < 2 else "❌"
            if diff >= 0.5:
                discrepancies.append((name, mongo_val, postgres_val, diff))
            print(f"{name:<25} {mongo_val:<12.1f} {postgres_val:<12.1f} {diff:<10.1f} {status}")
        else:
            print(f"{name:<25} {str(mongo_val):<12} {str(postgres_val):<12} {'-':<10} ⚪")
    
    print("-"*80)
    
    # Классификация
    print("\n📋 КЛАССИФИКАЦИЯ ПО ЗОНАМ (на основе MongoDB):")
    classification = classify_criteria(mongo_scores)
    
    print("\n✅ СИЛЬНЫЕ СТОРОНЫ (8-10 баллов):")
    for name, score in sorted(classification['strong'], key=lambda x: x[1], reverse=True):
        print(f"   • {name}: {score}")
    
    print("\n⚠️ ЗОНЫ РОСТА (5-7 баллов):")
    for name, score in sorted(classification['growth'], key=lambda x: x[1], reverse=True):
        print(f"   • {name}: {score}")
    
    print("\n❌ КРИТИЧЕСКИЕ СЛАБЫЕ МЕСТА (0-4 балла):")
    for name, score in sorted(classification['critical'], key=lambda x: x[1]):
        print(f"   • {name}: {score}")
    
    # Итог
    print("\n" + "="*80)
    if discrepancies:
        print("⚠️ ОБНАРУЖЕНЫ РАСХОЖДЕНИЯ:")
        for name, m, p, d in discrepancies:
            print(f"   {name}: MongoDB={m}, PostgreSQL={p}, разница={d}")
        print("\nВозможные причины:")
        print("   1. PostgreSQL не синхронизирован (запустить /api/postgres/sync-now)")
        print("   2. Разные периоды данных")
        print("   3. Разные формулы расчёта в DataLens")
    else:
        print("✅ Данные MongoDB и PostgreSQL совпадают (разница < 0.5 балла)")
    print("="*80)


async def main():
    parser = argparse.ArgumentParser(description='Тест расчёта средних баллов')
    parser.add_argument('--client_id', required=True, help='ID клиники')
    parser.add_argument('--start_date', required=True, help='Начало периода (YYYY-MM-DD)')
    parser.add_argument('--end_date', required=True, help='Конец периода (YYYY-MM-DD)')
    
    args = parser.parse_args()
    
    print(f"\n🔍 Анализ для клиники: {args.client_id}")
    print(f"📅 Период: {args.start_date} — {args.end_date}")
    
    # Расчёт из MongoDB
    mongo_result = await calculate_from_mongodb(args.client_id, args.start_date, args.end_date)
    
    # Расчёт из PostgreSQL
    postgres_result = calculate_from_postgres(args.client_id, args.start_date, args.end_date)
    
    # Сравнение
    print_comparison(mongo_result, postgres_result)


if __name__ == "__main__":
    asyncio.run(main())
