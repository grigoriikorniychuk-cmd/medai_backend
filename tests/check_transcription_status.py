"""
Проверка статуса транскрибации для звонков определённых сделок.
"""
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime

MONGO_URI = "mongodb://92.113.151.220:27018/"
DB_NAME = "medai"
LEAD_IDS = [23367001, 23364033]  # Сделки с конверсией, у которых нет транскрипций

async def check_calls():
    mongo_client = AsyncIOMotorClient(MONGO_URI)
    db = mongo_client[DB_NAME]
    calls_collection = db.calls
    
    print(f"\n{'='*80}")
    print(f"🔍 ПРОВЕРКА ЗВОНКОВ ПО СДЕЛКАМ")
    print(f"{'='*80}\n")
    
    for lead_id in LEAD_IDS:
        print(f"📌 Сделка: {lead_id}")
        print(f"{'-'*80}")
        
        # Ищем все звонки по этой сделке
        calls = await calls_collection.find({"lead_id": lead_id}).to_list(length=100)
        
        if not calls:
            print(f"  ❌ Звонков не найдено\n")
            continue
        
        print(f"  Найдено звонков: {len(calls)}\n")
        
        for idx, call in enumerate(calls, 1):
            print(f"  Звонок #{idx}:")
            print(f"    • _id: {call.get('_id')}")
            print(f"    • note_id: {call.get('note_id')}")
            print(f"    • call_link: {'✅ Есть' if call.get('call_link') else '❌ Нет'}")
            print(f"    • duration: {call.get('duration', 0)} сек")
            print(f"    • phone: {call.get('phone', 'Неизвестно')}")
            print(f"    • created_date: {call.get('created_date')}")
            
            # Проверяем статус транскрибации
            filename_trans = call.get('filename_transcription')
            trans_status = call.get('transcription_status', 'не установлен')
            filename_audio = call.get('filename_audio')
            
            print(f"    • filename_audio: {filename_audio if filename_audio else '❌ Нет'}")
            print(f"    • filename_transcription: {filename_trans if filename_trans else '❌ Нет'}")
            print(f"    • transcription_status: {trans_status}")
            
            # Проверяем наличие синхронизации с AmoCRM
            amo_synced = call.get('amo_transcription_synced', False)
            amo_note_id = call.get('amo_transcription_note_id')
            print(f"    • amo_transcription_synced: {amo_synced}")
            print(f"    • amo_transcription_note_id: {amo_note_id if amo_note_id else '❌ Нет'}")
            
            # Анализ
            print(f"    • Анализ:")
            if not call.get('call_link'):
                print(f"      ⚠️ Нет ссылки на запись - транскрибация невозможна")
            elif not filename_trans:
                print(f"      ⚠️ Транскрибация не выполнена")
            elif trans_status == 'processing':
                print(f"      🔄 Транскрибация в процессе")
            elif trans_status == 'failed':
                trans_error = call.get('transcription_error', 'Ошибка не указана')
                print(f"      ❌ Транскрибация провалилась: {trans_error}")
            elif trans_status == 'success':
                print(f"      ✅ Транскрибация успешна")
                if not amo_synced:
                    print(f"      ⚠️ Не синхронизирована с AmoCRM")
            print()
        
        print(f"{'-'*80}\n")
    
    print(f"\n{'='*80}")
    print(f"💡 РЕКОМЕНДАЦИИ")
    print(f"{'='*80}\n")
    print(f"1. Если нет call_link - звонок не может быть транскрибирован")
    print(f"2. Если filename_transcription пустое - нужно запустить транскрибацию")
    print(f"3. Если status=failed - проверить ошибку и переделать")
    print(f"4. Если status=success но нет синхронизации - запустить sync_transcription_to_amo")
    print(f"\n{'='*80}\n")
    
    mongo_client.close()

if __name__ == "__main__":
    asyncio.run(check_calls())
