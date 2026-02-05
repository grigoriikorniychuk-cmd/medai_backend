#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для поиска дублирующихся звонков в базе данных
"""
import json
from collections import defaultdict
from datetime import datetime

def find_duplicate_calls(json_file_path):
    """Находит дублирующиеся звонки по времени, контакту и длительности"""
    
    with open(json_file_path, 'r', encoding='utf-8') as f:
        calls = json.load(f)
    
    print(f"Загружено звонков: {len(calls)}")
    
    # Группируем звонки по ключевым параметрам
    call_groups = defaultdict(list)
    
    for call in calls:
        # Создаем ключ для группировки
        key = (
            call.get('contact_id'),           # ID контакта  
            call.get('duration'),             # Длительность звонка
        )
        
        call_groups[key].append({
            '_id': call.get('_id', {}).get('$oid'),
            'note_id': call.get('note_id'),
            'lead_id': call.get('lead_id'),
            'contact_name': call.get('contact_name'),
            'created_date': call.get('created_date'),
            'phone': call.get('phone'),
            'duration_formatted': call.get('duration_formatted'),
            'call_direction': call.get('call_direction'),
            'transcription_status': call.get('transcription_status'),
            'filename_transcription': call.get('filename_transcription')
        })
    
    # Находим группы с дубликатами
    duplicates = []
    total_duplicates = 0
    transcribed_duplicates = 0
    
    for key, group in call_groups.items():
        if len(group) > 1:
            duplicates.append({
                'key': key,
                'count': len(group),
                'calls': group
            })
            total_duplicates += len(group) - 1  # Считаем лишние записи
            
            # Считаем дубликаты с транскрибацией
            transcribed_in_group = sum(1 for call in group if call.get('transcription_status') == 'success')
            if transcribed_in_group > 1:
                transcribed_duplicates += transcribed_in_group - 1
    
    # Сортируем по количеству дубликатов
    duplicates.sort(key=lambda x: x['count'], reverse=True)
    
    print(f"\n=== РЕЗУЛЬТАТЫ АНАЛИЗА ===")
    print(f"Всего уникальных групп звонков: {len(call_groups)}")
    print(f"Групп с дубликатами: {len(duplicates)}")
    print(f"Общее количество дублирующихся записей: {total_duplicates}")
    print(f"Дубликатов с транскрибацией: {transcribed_duplicates}")
    print(f"Уникальных звонков должно быть: {len(calls) - total_duplicates}")
    
    # Показываем примеры дубликатов
    print(f"\n=== ПРИМЕРЫ ДУБЛИКАТОВ ===")
    for i, dup in enumerate(duplicates[:10]):  # Показываем первые 10
        contact_id, duration = dup['key']
        print(f"\n{i+1}. Группа дубликатов ({dup['count']} записей):")
        print(f"   Контакт ID: {contact_id}")  
        print(f"   Длительность: {duration}с")
        
        for j, call in enumerate(dup['calls']):
            transcription_mark = "✅" if call.get('transcription_status') == 'success' else "❌"
            print(f"     {j+1}. _id={call['_id']}, note_id={call['note_id']}, lead_id={call['lead_id']} {transcription_mark}")
            if call.get('filename_transcription'):
                print(f"        Транскрибация: {call['filename_transcription']}")
    
    # Анализ по типам дубликатов
    print(f"\n=== АНАЛИЗ ПРИЧИН ДУБЛИРОВАНИЯ ===")
    
    # Группируем по note_id
    note_ids = defaultdict(list)
    for call in calls:
        note_ids[call.get('note_id')].append(call)
    
    duplicate_note_ids = [note_id for note_id, group in note_ids.items() if len(group) > 1]
    print(f"Дублирующихся note_id: {len(duplicate_note_ids)}")
    
    # Группируем по lead_id  
    lead_ids = defaultdict(list)
    for call in calls:
        lead_ids[call.get('lead_id')].append(call)
    
    multiple_calls_per_lead = [lead_id for lead_id, group in lead_ids.items() if len(group) > 1]
    print(f"Сделок с несколькими звонками: {len(multiple_calls_per_lead)}")
    
    return duplicates, total_duplicates

def suggest_deduplication_strategy(duplicates):
    """Предлагает стратегию дедупликации"""
    print(f"\n=== СТРАТЕГИЯ ДЕДУПЛИКАЦИИ ===")
    
    print("1. КРИТЕРИИ ДЛЯ ОПРЕДЕЛЕНИЯ ДУБЛИКАТОВ:")
    print("   - Одинаковые contact_id + duration")
    print("   - Это гарантирует, что это один и тот же звонок по контакту и длительности")
    
    print("\n2. ЛОГИКА ВЫБОРА ЗАПИСИ ДЛЯ СОХРАНЕНИЯ:")
    print("   - Приоритет #1: Запись с транскрибацией (transcription_status='success')")
    print("   - Приоритет #2: Запись с анализом (analyze_status='success')")  
    print("   - Приоритет #3: Самая поздняя запись (по _id)")
    
    print("\n3. МЕСТА ДЛЯ ВНЕДРЕНИЯ ДЕДУПЛИКАЦИИ:")
    print("   A) При синхронизации из AmoCRM (до записи в MongoDB)")
    print("   B) После синхронизации (очистка существующих дубликатов)")
    print("   C) Перед транскрибацией (фильтрация задач)")
    
    print("\n4. РЕКОМЕНДУЕМЫЕ ИЗМЕНЕНИЯ:")
    print("   - Добавить проверку дубликатов в calls_parallel_bulk.py")
    print("   - Создать уникальный индекс в MongoDB по (contact_id, duration)")
    print("   - Добавить валидацию в transcribe-by-date-range")

if __name__ == "__main__":
    json_file = "/Users/mpr0/Development/[Sandbox]/medai_final/medai_backend/medai.calls(Atmo).json"
    
    try:
        duplicates, total_count = find_duplicate_calls(json_file)
        suggest_deduplication_strategy(duplicates)
        
    except FileNotFoundError:
        print(f"Файл не найден: {json_file}")
    except json.JSONDecodeError as e:
        print(f"Ошибка парсинга JSON: {e}")
    except Exception as e:
        print(f"Ошибка: {e}")
