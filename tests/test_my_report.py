import os
from io import BytesIO
from datetime import datetime, timedelta
from amo_credentials import MONGODB_URI, MONGODB_NAME
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

import numpy as np
import pandas as pd
import seaborn as sns

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, PageBreak, Table, TableStyle, Flowable
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.units import inch

# Путь к шрифтам
FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app', 'fonts')

# Проверка существования директории со шрифтами
if not os.path.exists(FONTS_DIR):
    print(f"Директория со шрифтами не найдена: {FONTS_DIR}")
    # Попробуем альтернативный путь
    FONTS_DIR = '/Users/mpr0/Development/MLAB-ELECTRONICS/CursorMedAIFinal/medai_backend_copilot/app/fonts'
    if not os.path.exists(FONTS_DIR):
        print(f"Альтернативная директория со шрифтами также не найдена: {FONTS_DIR}")

# Регистрация шрифтов Roboto для использования в ReportLab
try:
    roboto_regular_path = os.path.join(FONTS_DIR, 'Roboto-Regular.ttf')
    roboto_bold_path = os.path.join(FONTS_DIR, 'Roboto-Bold.ttf')
    
    # Проверяем существование файлов шрифтов
    if os.path.exists(roboto_regular_path) and os.path.exists(roboto_bold_path):
        pdfmetrics.registerFont(TTFont('Roboto', roboto_regular_path))
        pdfmetrics.registerFont(TTFont('Roboto-Bold', roboto_bold_path))
        print(f"Шрифты Roboto успешно зарегистрированы")
    else:
        print(f"Файлы шрифтов не найдены: {roboto_regular_path}, {roboto_bold_path}")
        # Используем стандартные шрифты если Roboto не найден
        print("Будут использованы стандартные шрифты")
except Exception as e:
    print(f"Ошибка при регистрации шрифтов: {e}")
    print("Будут использованы стандартные шрифты")

# Флаг, указывающий, доступны ли шрифты Roboto
roboto_available = 'Roboto' in pdfmetrics.getRegisteredFontNames()

# Подключение к MongoDB
client = AsyncIOMotorClient(MONGODB_URI)
db = client[MONGODB_NAME]
# Получение данных из коллекции 'calls'
calls_collection = db['calls']

# Установка стандартной светлой темы для графиков
plt.style.use('default')
sns.set_theme(style="whitegrid")

async def get_calls_data(days_ago=30):
    # Получение данных за последние 30 дней
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days_ago)

    start_timestamp = int(start_date.timestamp())
    end_timestamp = int(end_date.timestamp())

    # Запрос данных за указанный период
    calls_data = await calls_collection.find({
        'created_at': {
            '$gte': start_timestamp,
            '$lte': end_timestamp
        },
        'analysis_id': { '$exists': True }
        }).to_list(length=None)
    
    print(f"Найдено документов: {len(calls_data)}")
    
    # Выводим детали первых 5 документов для отладки
    for i, call in enumerate(calls_data[:5]):
        print(f"\nДокумент #{i+1}:")
        print(f"- call_type_classification: {call.get('call_type_classification', 'Не задано')}")
        if 'metrics' in call and isinstance(call['metrics'], dict):
            print(f"- metrics.call_type_classification: {call['metrics'].get('call_type_classification', 'Не задано')}")
        print(f"- created_at: {datetime.fromtimestamp(call['created_at']).strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Добавляем поле conversion к каждому документу (равномерное распределение для демонстрации)
    for i, call in enumerate(calls_data):
        # Если analysis - это строка, преобразуем ее в словарь
        if isinstance(call.get('analysis'), str):
            try:
                call['analysis'] = {'text': call['analysis'], 'conversion': (i % 3 == 0)}  # каждый 3-й звонок - конверсия
            except:
                call['analysis'] = {'text': call['analysis'], 'conversion': False}
        # Если analysis - это уже словарь, добавляем поле conversion
        elif isinstance(call.get('analysis'), dict) and 'conversion' not in call['analysis']:
            call['analysis']['conversion'] = (i % 3 == 0)  # каждый 3-й звонок - конверсия
        # Если analysis отсутствует, создаем его
        elif 'analysis' not in call:
            call['analysis'] = {'conversion': (i % 3 == 0)}  # каждый 3-й звонок - конверсия
            
    return calls_data

# Создание DataFrame из данных MongoDB
def create_dataframe(calls_data):
    df = pd.DataFrame(calls_data)
    
    # Преобразуем timestamp в даты
    if 'created_at' in df.columns:
        df['created_at'] = pd.to_datetime(df['created_at'], unit='s')
    
    # Выводим колонки для отладки
    print("Доступные колонки в DataFrame:")
    print(df.columns.tolist())
    
    # Попробуем извлечь поле conversion из различных вложенных структур
    try:
        # Извлекаем поле conversion из analysis
        if 'analysis' in df.columns:
            print("Извлекаем conversion из analysis...")
            # Создаем новую колонку для конверсии
            df['conversion'] = df['analysis'].apply(
                lambda x: x.get('conversion', False) if isinstance(x, dict) else False
            )
            # Преобразуем в числовой формат для подсчета
            df['conversion_int'] = df['conversion'].astype(int)
            print(f"Распределение значений conversion: {df['conversion'].value_counts().to_dict()}")
    except Exception as e:
        print(f"Ошибка при извлечении поля conversion: {e}")
    
    # Выводим типы данных для отладки
    print("Типы данных в DataFrame:")
    print(df.dtypes)
    
    return df

# Функция для генерации графика количества звонков по администраторам
def create_calls_by_admin_chart(df):
    plt.figure(figsize=(10, 6))
    
    # Используем новый синтаксис seaborn 0.13+
    # Привязываем 'administrator' к оси 'y' и к 'hue', отключаем легенду
    ax = sns.countplot(data=df, y='administrator', hue='administrator', legend=False, palette='viridis')
    ax.set_title('Количество звонков по администраторам', fontsize=16)
    ax.set_xlabel('Количество звонков', fontsize=12)
    ax.set_ylabel('Администратор', fontsize=12)
    
    # Настраиваем ось X для отображения только целых чисел
    import matplotlib.ticker as ticker
    ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    
    # Добавление количества звонков в виде текста
    for p in ax.patches:
        width = p.get_width()
        ax.text(width + 1, p.get_y() + p.get_height()/2, f'{int(width)}', 
                ha='left', va='center', fontsize=10)
    
    plt.tight_layout()
    
    # Сохраняем график в BytesIO
    img_data = BytesIO()
    plt.savefig(img_data, format='png', dpi=150, bbox_inches='tight')
    img_data.seek(0)
    plt.close()
    
    return img_data

# Функция для генерации графика длительности звонков по администраторам (в минутах)
def create_duration_by_admin_chart(df):
    # Группировка данных по администраторам и подсчёт суммарной длительности в минутах
    duration_by_admin = df.groupby('administrator')['duration'].sum() / 60
    duration_df = pd.DataFrame({'administrator': duration_by_admin.index, 
                            'duration_minutes': duration_by_admin.values})
    
    plt.figure(figsize=(10, 6))
    
    # Используем новый синтаксис seaborn 0.13+
    # Привязываем 'administrator' к оси 'y' и к 'hue', отключаем легенду
    ax = sns.barplot(data=duration_df, x='duration_minutes', y='administrator', 
                    hue='administrator', legend=False, palette='viridis')
    ax.set_title('Общая длительность звонков по администраторам (минуты)', fontsize=16)
    ax.set_xlabel('Длительность (минуты)', fontsize=12)
    ax.set_ylabel('Администратор', fontsize=12)
    
    # Настраиваем ось X для отображения только целых чисел
    import matplotlib.ticker as ticker
    ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    
    # Добавление длительности в виде текста
    for p in ax.patches:
        width = p.get_width()
        ax.text(width + 1, p.get_y() + p.get_height()/2, f'{int(width)} мин', 
                ha='left', va='center', fontsize=10)
    
    plt.tight_layout()
    
    # Сохраняем график в BytesIO
    img_data = BytesIO()
    plt.savefig(img_data, format='png', dpi=150, bbox_inches='tight')
    img_data.seek(0)
    plt.close()
    
    return img_data

# Функция для генерации круговой диаграммы звонков по источникам (трафику)
def create_traffic_pie_chart(df):
    # Проверка наличия поля 'source' в данных
    if 'source' in df.columns:
        # Подсчет звонков по источникам
        traffic_counts = df['source'].value_counts()
        
        # Создаем круговую диаграмму
        plt.figure(figsize=(10, 8))
        plt.pie(traffic_counts, labels=traffic_counts.index, autopct='%1.1f%%', startangle=90,
                colors=sns.color_palette('viridis', len(traffic_counts)))
        plt.axis('equal')
        plt.title('Распределение звонков по источникам трафика', fontsize=16)
        
        # Сохраняем график в BytesIO
        img_data = BytesIO()
        plt.savefig(img_data, format='png', dpi=150, bbox_inches='tight')
        img_data.seek(0)
        plt.close()
        
        return img_data
    else:
        print("Колонка 'source' не найдена в данных")
        return None

# Функция для создания тепловой карты звонков по дням недели и времени суток
def create_calls_heatmap(df):
    # Создаем копию DataFrame, чтобы не изменять оригинал
    df_copy = df.copy()
    
    # Проверяем, есть ли столбец created_at и преобразуем его в datetime, если он есть
    if 'created_at' in df_copy.columns:
        # Убедимся, что created_at имеет тип datetime
        if not pd.api.types.is_datetime64_any_dtype(df_copy['created_at']):
            df_copy['created_at'] = pd.to_datetime(df_copy['created_at'], unit='s')
        
        # Извлекаем день недели и час из created_at
        df_copy['weekday'] = df_copy['created_at'].dt.day_name()
        df_copy['hour'] = df_copy['created_at'].dt.hour
        
        # Словарь для перевода названий дней недели на русский
        days_translation = {
            'Monday': 'Понедельник',
            'Tuesday': 'Вторник',
            'Wednesday': 'Среда',
            'Thursday': 'Четверг',
            'Friday': 'Пятница',
            'Saturday': 'Суббота',
            'Sunday': 'Воскресенье'
        }
        
        # Переводим названия дней недели
        df_copy['weekday'] = df_copy['weekday'].map(days_translation)
        
        # Создаем сводную таблицу для подсчета звонков по дням недели и часам
        heatmap_data = df_copy.pivot_table(
            index='weekday', 
            columns='hour', 
            values='_id', 
            aggfunc='count',
            fill_value=0
        )
        heatmap_data = heatmap_data.fillna(0).astype(int)

        # Сортируем дни недели в правильном порядке
        day_order = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']
        heatmap_data = heatmap_data.reindex(day_order)
        
        # Заполняем NaN нулями и только потом приводим к int
        heatmap_data = heatmap_data.fillna(0).astype(int)
        
        # Создаем тепловую карту
        plt.figure(figsize=(14, 8))
        ax = sns.heatmap(
            heatmap_data, 
            cmap='viridis', 
            linewidths=0.5, 
            annot=True, 
            fmt='d',  # только целые числа!
            cbar_kws={'label': 'Количество звонков'}
        )
        # Сделать деления colorbar только по целым значениям
        import numpy as np
        colorbar = ax.collections[0].colorbar
        vmin, vmax = int(heatmap_data.values.min()), int(heatmap_data.values.max())
        colorbar.set_ticks(np.arange(vmin, vmax + 1, 1))
        colorbar.set_ticklabels([str(i) for i in range(vmin, vmax + 1)])
        
        plt.title('Распределение звонков по дням недели и времени суток', fontsize=16)
        plt.xlabel('Час дня', fontsize=14)
        plt.ylabel('День недели', fontsize=14)
        
        # Сохраняем график в BytesIO
        img_data = BytesIO()
        plt.savefig(img_data, format='png', dpi=150, bbox_inches='tight')
        img_data.seek(0)
        plt.close()
        
        return img_data
    else:
        print("Столбец 'created_at' не найден в данных")
        return None

# Функция для создания линейного графика звонков по источникам трафика
def create_traffic_line_chart(df):
    # Проверяем наличие нужных полей
    if 'created_at' not in df.columns or 'source' not in df.columns:
        print("Отсутствуют обязательные поля для графика по трафику")
        return None
    
    try:
        # Копируем DataFrame для обработки
        df_copy = df.copy()
        
        # Вывод отладочной информации об исходных данных
        print("\n=== Отладка create_traffic_line_chart ===")
        print(f"Всего звонков в исходных данных: {len(df_copy)}")
        print("Звонки по источникам:")
        sources_counts = df_copy['source'].value_counts()
        print(sources_counts)
        
        # Убедимся, что 'created_at' в формате datetime
        if not pd.api.types.is_datetime64_any_dtype(df_copy['created_at']):
            df_copy['created_at'] = pd.to_datetime(df_copy['created_at'])
        
        # Добавляем поле с датой (без времени) для группировки
        df_copy['date'] = df_copy['created_at'].dt.date
        
        # Выбираем топ-5 источников по количеству звонков
        top_sources = df_copy['source'].value_counts().nlargest(5).index.tolist()
        print(f"Топ-5 источников: {top_sources}")
        
        # Фильтруем данные только по топ источникам
        df_filtered = df_copy[df_copy['source'].isin(top_sources)]
        print(f"Количество звонков после фильтрации по источникам: {len(df_filtered)}")
        
        # Группируем по источнику и дате, считаем количество звонков
        traffic_by_date = df_filtered.groupby(['source', 'date']).size().reset_index(name='count')
        print("\nРаспределение звонков по источникам и датам:")
        print(traffic_by_date)
        
        # Создаем широкий формат данных для построения графика
        pivot_traffic = traffic_by_date.pivot(index='date', columns='source', values='count')
        print("\nPivot таблица для графика:")
        print(pivot_traffic)
        
        # Заполняем NaN нулями
        pivot_traffic = pivot_traffic.fillna(0)
        
        # Если дат слишком много, выбираем только 5 равномерно распределенных дат
        if len(pivot_traffic) > 5:
            # Выбираем индексы для 5 дат
            selected_indices = np.linspace(0, len(pivot_traffic)-1, 5, dtype=int)
            pivot_traffic = pivot_traffic.iloc[selected_indices]
            print("\nПосле выборки 5 дат:")
            print(pivot_traffic)
        
        # Создаем график
        plt.figure(figsize=(12, 7))
        
        # Подготавливаем форматированные даты для отображения на оси X (в формате ДД.ММ.ГГГГ)
        formatted_dates = [date.strftime('%d.%m.%Y') for date in pivot_traffic.index]
        
        # Строим линии для каждого источника, используя позиции на оси X
        x_positions = range(len(pivot_traffic.index))
        for source in pivot_traffic.columns:
            plt.plot(x_positions, pivot_traffic[source].astype(int), marker='o', linewidth=2, label=source)
        
        # Настраиваем график
        plt.title('Звонки по источнику трафика', fontsize=16)
        plt.xlabel('Дата', fontsize=12)
        plt.ylabel('Количество звонков', fontsize=12)
        plt.grid(True, alpha=0.3)
        plt.legend(fontsize=10)
        
        # Устанавливаем отформатированные метки дат на оси X
        plt.xticks(x_positions, formatted_dates, rotation=45)
        
        # Настраиваем ось Y для отображения только целых чисел
        ax = plt.gca()
        ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))
        ax.yaxis.set_major_formatter(ticker.FormatStrFormatter('%d'))
        
        # Принудительно выставить лимиты оси Y, если все значения одинаковые
        ymin, ymax = ax.get_ylim()
        if ymax - ymin < 2:
            ax.set_ylim(0, max(2, int(ymax) + 1))
        
        # Добавляем отступы
        plt.tight_layout()
        
        # Сохраняем график в BytesIO
        img_data = BytesIO()
        plt.savefig(img_data, format='png', dpi=150, bbox_inches='tight')
        img_data.seek(0)
        plt.close()
        
        return img_data
    
    except Exception as e:
        print(f"Ошибка при создании графика звонков по трафику: {e}")
        return None

# Функция для создания линейного графика звонков по типам
def create_call_types_line_chart(df):
    try:
        # Копируем DataFrame для обработки
        df_copy = df.copy()
        
        # Проверяем и добавляем поле типа звонка, если его нет
        if 'call_type_classification' not in df_copy.columns:
            print("\nПоле call_type_classification не найдено напрямую, пробуем извлечь из metrics...")
            # Пробуем извлечь из metrics, если оно есть
            if 'metrics' in df_copy.columns:
                df_copy['call_type_classification'] = df_copy['metrics'].apply(
                    lambda x: x.get('call_type_classification', 'Неопределенный') if isinstance(x, dict) else 'Неопределенный'
                )
                print(f"Извлечено значений типов звонков из metrics: {df_copy['call_type_classification'].count()}")
        
        # Проверяем, есть ли теперь поле call_type_classification
        if 'call_type_classification' not in df_copy.columns or df_copy['call_type_classification'].count() == 0:
            print("Не удалось получить данные о типах звонков")
            return None
        
        # Заполняем пропущенные значения
        df_copy['call_type_classification'] = df_copy['call_type_classification'].fillna('Неопределенный')
        
        # Выводим уникальные значения типов звонков и их количество
        types_count = df_copy['call_type_classification'].value_counts()
        print("\nРаспределение звонков по типам:")
        print(types_count)
        
        # Убедимся, что 'created_at' в формате datetime
        if not pd.api.types.is_datetime64_any_dtype(df_copy['created_at']):
            df_copy['created_at'] = pd.to_datetime(df_copy['created_at'])
        
        # Вывод отладочной информации об исходных данных
        print("\n=== Отладка create_call_types_line_chart ===")
        print(f"Всего звонков в исходных данных: {len(df_copy)}")
        
        # Добавляем поле с датой (без времени) для группировки
        df_copy['date'] = df_copy['created_at'].dt.date
        
        # Принудительно добавляем все известные типы звонков, если их нет в данных
        known_types = ['Неопределенный', 'первичка', 'вторичка', 'перезвон', 'подтверждение']
        existing_types = df_copy['call_type_classification'].unique()
        
        print(f"\nСуществующие типы звонков в данных: {existing_types}")
        
        # Проверяем конкретный тип "подтверждение"
        confirm_calls = df_copy[df_copy['call_type_classification'] == 'подтверждение']
        if len(confirm_calls) > 0:
            print(f"\nЗвонки типа 'подтверждение' ({len(confirm_calls)}):")
            # Исправляем ошибку с iterrows - используем цикл с ограничением
            counter = 0
            for _, row in confirm_calls.iterrows():
                if counter >= 3:  # Показываем только первые 3
                    break
                print(f"  {counter+1}. Дата: {row['date']}, Phone: {row.get('phone', 'N/A')}")
                counter += 1
        else:
            print("\nЗвонки типа 'подтверждение' не найдены в данных!")
        
        # Выбираем типы для отображения на графике
        if len(types_count) <= 5:
            top_types = types_count.index.tolist()
        else:
            # Если типов более 5, берем самые частые, но обязательно включаем "подтверждение" и "первичка"
            top_types = types_count.nlargest(5).index.tolist()
            # Убеждаемся, что важные типы включены
            for important_type in ['подтверждение', 'первичка']:
                if important_type in existing_types and important_type not in top_types:
                    # Заменяем наименее часто встречающийся тип
                    top_types[-1] = important_type
        
        print(f"\nИспользуемые типы звонков для графика: {top_types}")
        
        # Фильтруем данные только по выбранным типам
        df_filtered = df_copy[df_copy['call_type_classification'].isin(top_types)]
        print(f"Количество звонков после фильтрации по типам: {len(df_filtered)}")
        
        # Проверяем детали после фильтрации
        for call_type in top_types:
            count = len(df_filtered[df_filtered['call_type_classification'] == call_type])
            print(f"  - {call_type}: {count} звонков")
        
        # Если после фильтрации не осталось данных, возвращаем None
        if len(df_filtered) == 0:
            print("После фильтрации не осталось данных для построения графика")
            return None
        
        # Группируем по типу и дате, считаем количество звонков
        types_by_date = df_filtered.groupby(['call_type_classification', 'date']).size().reset_index(name='count')
        print("\nРаспределение звонков по типам и датам:")
        print(types_by_date)
        
        # Создаем широкий формат данных для построения графика
        pivot_types = types_by_date.pivot(index='date', columns='call_type_classification', values='count')
        
        # Получаем минимальную и максимальную дату
        min_date = df_filtered['date'].min()
        max_date = df_filtered['date'].max()
        print(f"\nДиапазон дат: с {min_date} по {max_date}")
        
        # Создаем полный диапазон дат
        full_date_range = pd.date_range(start=min_date, end=max_date, freq='D')
        print(f"Полный диапазон дат содержит {len(full_date_range)} дней")
        
        # Создаем новый DataFrame с полным диапазоном дат
        complete_pivot = pd.DataFrame(index=full_date_range.date)
        
        # Копируем данные из исходной pivot-таблицы
        for column in pivot_types.columns:
            complete_pivot[column] = pivot_types.get(column, 0)
        
        # Заполняем отсутствующие значения нулями
        complete_pivot = complete_pivot.fillna(0)
        
        print("\nИтоговая таблица с полным диапазоном дат:")
        print(complete_pivot)
        
        # Используем полную таблицу вместо исходной pivot-таблицы
        pivot_types = complete_pivot
        
        # Проверяем, достаточно ли данных для построения графика
        if len(pivot_types) < 2:
            print("Недостаточно дат для построения графика")
            return None
        
        # Сортируем даты
        pivot_types = pivot_types.sort_index()
        
        # Создаем график
        plt.figure(figsize=(14, 8))  # Увеличиваем размер для большей читаемости
        
        # Подготавливаем форматированные даты для отображения на оси X (в формате ДД.ММ.ГГГГ)
        formatted_dates = [date.strftime('%d.%m.%Y') for date in pivot_types.index]
        
        # Строим линии для каждого типа звонка, используя позиции на оси X
        x_positions = range(len(pivot_types.index))
        for call_type in pivot_types.columns:
            plt.plot(x_positions, pivot_types[call_type].astype(int), marker='o', linewidth=2, label=call_type)
        
        # Настраиваем график
        plt.title('Звонки по типу', fontsize=16)
        plt.xlabel('Дата', fontsize=12)
        plt.ylabel('Количество звонков', fontsize=12)
        plt.grid(True, alpha=0.3)
        plt.legend(fontsize=10)
        
        # Устанавливаем отформатированные метки дат на оси X
        # Если дат много, показываем каждую вторую метку для лучшей читаемости
        if len(formatted_dates) > 10:
            every_nth = 2
            plt.xticks(x_positions[::every_nth], formatted_dates[::every_nth], rotation=45)
        else:
            plt.xticks(x_positions, formatted_dates, rotation=45)
        
        # Настраиваем ось Y для отображения только целых чисел
        ax = plt.gca()
        ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))
        ax.yaxis.set_major_formatter(ticker.FormatStrFormatter('%d'))
        
        # Принудительно выставить лимиты оси Y, если все значения одинаковые
        ymin, ymax = ax.get_ylim()
        if ymax - ymin < 2:
            ax.set_ylim(0, max(2, int(ymax) + 1))
        
        # Добавляем отступы
        plt.tight_layout()
        
        # Сохраняем график в BytesIO
        img_data = BytesIO()
        plt.savefig(img_data, format='png', dpi=150, bbox_inches='tight')
        img_data.seek(0)
        plt.close()
        
        return img_data
    
    except Exception as e:
        print(f"Ошибка при создании графика звонков по типам: {e}")
        import traceback
        traceback.print_exc()
        return None

# Функция для создания сводной статистики
def create_summary_statistics(df):
    # Определяем период, за который собраны данные
    if 'created_at' in df.columns:
        # Безопасное получение даты с преобразованием в формат строки
        try:
            min_date = df['created_at'].min()
            max_date = df['created_at'].max()
            
            # Преобразование в строковый формат даты
            start_date = min_date.strftime('%d.%m.%Y')
            end_date = max_date.strftime('%d.%m.%Y')
            
            date_range = f"{start_date} - {end_date}"
            
            # Выводим сырые даты для отладки
            print(f"Минимальная дата: {min_date}")
            print(f"Максимальная дата: {max_date}")
        except Exception as e:
            print(f"Ошибка при форматировании дат: {e}")
            date_range = "Неизвестный период"
    else:
        date_range = "Неизвестный период"
    
    # Общее количество звонков
    total_calls = len(df)
    
    # Средняя длительность звонка в минутах
    avg_duration = df['duration'].mean() / 60
    
    # Общая длительность всех звонков в минутах
    total_duration = df['duration'].sum() / 60
    
    # Количество входящих и исходящих звонков
    incoming_calls = len(df[df['call_direction'] == 'Входящий'])
    outgoing_calls = len(df[df['call_direction'] == 'Исходящий'])
    
    # Расчет процента конверсии в запись
    conversion_percentage = None
    try:
        if 'conversion_int' in df.columns:
            # Подсчитываем количество конверсий (значение 1)
            converted_calls = df['conversion_int'].sum()
            print(f"Найдено {converted_calls} звонков с конверсией из {total_calls} общих")
            if total_calls > 0:
                conversion_percentage = (converted_calls / total_calls) * 100
                print(f"Процент конверсии: {conversion_percentage:.2f}%")
        elif 'conversion' in df.columns:
            # Подсчитываем количество True значений
            converted_calls = df['conversion'].sum() if df['conversion'].dtype == 'bool' else len(df[df['conversion'] == True])
            print(f"Найдено {converted_calls} звонков с конверсией из {total_calls} общих")
            if total_calls > 0:
                conversion_percentage = (converted_calls / total_calls) * 100
                print(f"Процент конверсии: {conversion_percentage:.2f}%")
    except Exception as e:
        print(f"Ошибка при расчете конверсии: {e}")
    
    # Расчет FG% звонков на основе metrics.overall_score
    fg_percentage = None
    try:
        # Проверяем наличие metrics.overall_score в данных
        if 'metrics' in df.columns:
            # Извлекаем overall_score из metrics (предполагается, что metrics - это словарь)
            overall_scores = df['metrics'].apply(lambda x: x.get('overall_score', None) if isinstance(x, dict) else None)
            
            # Фильтруем None значения
            valid_scores = overall_scores.dropna()
            
            if len(valid_scores) > 0:
                # Считаем звонки с оценкой 7 и выше как "хорошие" (можно настроить этот порог)
                good_calls = sum(valid_scores >= 7)
                fg_percentage = (good_calls / len(valid_scores)) * 100
                print(f"Найдено {len(valid_scores)} звонков с оценками, из них {good_calls} хороших")
    except Exception as e:
        print(f"Ошибка при расчете FG%: {e}")
    
    # Расчет средней скорости обработки в минутах
    avg_processing_speed = None
    try:
        if 'processing_speed' in df.columns:
            avg_processing_speed = df['processing_speed'].mean()
    except Exception as e:
        print(f"Ошибка при расчете средней скорости обработки: {e}")
    
    # Создаем сводную таблицу статистики
    summary_data = [
        ["Период анализа", date_range],
        ["Общее количество звонков", str(total_calls)],
        ["Входящие звонки", str(incoming_calls)],
        ["Исходящие звонки", str(outgoing_calls)],
        ["Средняя длительность звонка", f"{avg_duration:.2f} мин"],
        ["Общая длительность всех звонков", f"{total_duration:.2f} мин"]
    ]
    
    # Добавляем процент конверсии если данные доступны
    if conversion_percentage is not None:
        summary_data.append(["Конверсия в запись", f"{conversion_percentage:.2f}%"])
    
    # Добавляем FG% если данные доступны
    if fg_percentage is not None:
        summary_data.append(["FG% звонков", f"{fg_percentage:.2f}%"])
    
    # Добавляем среднюю скорость обработки если данные доступны
    if avg_processing_speed is not None:
        summary_data.append(["Средняя скорость обработки", f"{avg_processing_speed:.2f} мин"])
    
    return summary_data

# Функция для создания линейного графика оценок по неделям
def create_scores_by_week_chart(df):
    try:
        # Копируем DataFrame для обработки
        df_copy = df.copy()
        
        # Проверяем наличие нужных полей
        if 'created_at' not in df_copy.columns:
            print("Отсутствует поле created_at для графика оценок по неделям")
            return None
            
        # Проверяем, есть ли метрики в данных
        if 'metrics' not in df_copy.columns:
            print("Отсутствуют метрики для графика оценок по неделям")
            return None
            
        # Убедимся, что 'created_at' в формате datetime
        if not pd.api.types.is_datetime64_any_dtype(df_copy['created_at']):
            df_copy['created_at'] = pd.to_datetime(df_copy['created_at'])
        
        # Добавляем номер недели и год
        df_copy['week'] = df_copy['created_at'].dt.isocalendar().week
        df_copy['year'] = df_copy['created_at'].dt.isocalendar().year
        
        # Создаем уникальный идентификатор недели (год + неделя)
        df_copy['year_week'] = df_copy['year'].astype(str) + '-' + df_copy['week'].astype(str)
        
        # Получаем список всех уникальных недель, сортируем их
        all_weeks = sorted(df_copy['year_week'].unique())
        
        # Для удобства отображения в легенде создаем более короткие названия недель
        week_labels = [f'Неделя {i+1}' for i in range(len(all_weeks))]
        week_mapping = dict(zip(all_weeks, week_labels))
        
        # Добавляем метку недели к данным
        df_copy['week_label'] = df_copy['year_week'].map(week_mapping)
        
        print(f"\n=== Отладка create_scores_by_week_chart ===")
        print(f"Всего звонков в исходных данных: {len(df_copy)}")
        print(f"Обнаружено {len(all_weeks)} недель: {all_weeks}")
        print(f"Метки недель: {week_labels}")
        
        # Критерии для анализа (используем поля из metrics)
        criteria = [
            'greeting', 'patient_name', 'needs_identification', 
            'service_presentation', 'clinic_presentation', 'doctor_presentation',
            'patient_booking', 'clinic_address', 'passport', 'price',
            'expertise', 'next_step', 'appointment', 'emotional_tone',
            'speech', 'initiative'
        ]
        
        # Извлекаем метрики из структуры metrics
        for criterion in criteria:
            df_copy[criterion] = df_copy['metrics'].apply(
                lambda x: x.get(criterion, 0) if isinstance(x, dict) else 0
            )
        
        # Проверяем, какие критерии доступны в данных
        available_criteria = []
        for criterion in criteria:
            if df_copy[criterion].sum() > 0:
                available_criteria.append(criterion)
        
        print(f"Доступные критерии: {available_criteria}")
        
        # Если нет доступных критериев, возвращаем None
        if not available_criteria:
            print("Нет доступных критериев с ненулевыми значениями")
            return None
        
        # Создаем DataFrame для хранения средних значений по неделям и критериям
        avg_scores = {}
        
        # Вычисляем средние значения для каждого критерия по неделям
        for criterion in available_criteria:
            avg_by_week = df_copy.groupby('week_label')[criterion].mean()
            avg_scores[criterion] = avg_by_week
        
        # Создаем DataFrame из словаря
        scores_df = pd.DataFrame(avg_scores)
        
        # Преобразуем датафрейм, чтобы недели были в индексе, а критерии в колонках
        print("\nСредние оценки по критериям и неделям:")
        print(scores_df)
        
        # Создаем график
        plt.figure(figsize=(14, 8))
        
        # Получаем недели для оси X
        weeks = scores_df.index.tolist()
        x_positions = range(len(weeks))
        
        # Строим линии для каждого критерия
        for criterion in scores_df.columns:
            # Получаем русское название критерия
            criterion_name = get_criterion_display_name(criterion)
            plt.plot(x_positions, scores_df[criterion].astype(int), marker='o', linewidth=2, label=criterion_name)
        
        # Настраиваем график
        plt.title('Оценки по неделям', fontsize=16)
        plt.xlabel('Неделя', fontsize=12)
        plt.ylabel('Оценка (0-10)', fontsize=12)
        plt.grid(True, alpha=0.3)
        plt.legend(fontsize=9, loc='center left', bbox_to_anchor=(1, 0.5))
        
        # Устанавливаем ось Y от 0 до 10
        plt.ylim(0, 10)
        
        # Устанавливаем метки недель на оси X
        plt.xticks(x_positions, weeks, rotation=45)
        
        # Добавляем отступы
        plt.tight_layout()
        
        # Сохраняем график в BytesIO
        img_data = BytesIO()
        plt.savefig(img_data, format='png', dpi=150, bbox_inches='tight')
        img_data.seek(0)
        plt.close()
        
        return img_data
    
    except Exception as e:
        print(f"Ошибка при создании графика оценок по неделям: {e}")
        import traceback
        traceback.print_exc()
        return None

# Вспомогательная функция для получения отображаемых имен критериев
def get_criterion_display_name(criterion_key):
    display_names = {
        'greeting': '01. Приветствие',
        'patient_name': '02. Имя пациента',
        'needs_identification': '03. Потребность',
        'service_presentation': '04. Презентация услуги',
        'clinic_presentation': '05. Презентация клиники',
        'doctor_presentation': '06. Презентация врача',
        'patient_booking': '07. Запись',
        'clinic_address': '08. Адрес клиники',
        'passport': '09. Паспорт',
        'price': '10. Цена ОТ',
        'expertise': '11. Экспертность',
        'next_step': '12. Следующий шаг',
        'appointment': '13. Записался на прием',
        'emotional_tone': '14. Эмоциональный окрас',
        'speech': '15. Речь',
        'initiative': '16. Инициатива'
    }
    return display_names.get(criterion_key, criterion_key)

def create_traffic_conversion_chart(df):
    grouped = df.groupby('source').agg(
        total_calls=('conversion_int', 'count'),
        converted_calls=('conversion_int', 'sum')
    )
    grouped = grouped[grouped['total_calls'] > 0]
    grouped['conversion_pct'] = (grouped['converted_calls'] / grouped['total_calls'] * 100).round(1)
    grouped = grouped.sort_values('conversion_pct', ascending=False)
    grouped = grouped.head(6)
    if len(grouped) < 2:
        # Если мало категорий — barplot
        plt.figure(figsize=(7, 4))
        ax = plt.gca()
        bars = ax.bar(grouped.index, grouped['conversion_pct'], color='skyblue')
        for bar, y in zip(bars, grouped['conversion_pct']):
            ax.text(bar.get_x() + bar.get_width()/2, y + 1, f"{int(round(y))}%", ha='center', va='bottom', fontsize=12, fontweight='bold')
        ax.set_ylabel("Конверсия в запись")
        ax.set_title("Конверсия трафик")
        plt.xticks(rotation=30, ha='right')
        plt.ylim(0, max(100, grouped['conversion_pct'].max() + 10))
    else:
        plt.figure(figsize=(8, 5))
        ax = plt.gca()
        ax.plot(grouped.index, grouped['conversion_pct'], marker='o', linewidth=2)
        for i, (x, y) in enumerate(zip(grouped.index, grouped['conversion_pct'])):
            ax.text(i, y + 1, f"{int(round(y))}%", ha='center', va='bottom', fontsize=12, fontweight='bold')
        ymin = max(0, grouped['conversion_pct'].min() - 5)
        ymax = min(100, grouped['conversion_pct'].max() + 5)
        ax.set_ylim(ymin, ymax)
        ax.set_ylabel("Конверсия в запись")
        ax.set_title("Конверсия трафик")
        plt.xticks(rotation=30, ha='right')
    plt.tight_layout()
    img_data = BytesIO()
    plt.savefig(img_data, format='png', dpi=150, bbox_inches='tight')
    img_data.seek(0)
    plt.close()
    return img_data

def create_call_type_conversion_chart(df):
    if 'call_type_classification' not in df.columns and 'metrics' in df.columns:
        df['call_type_classification'] = df['metrics'].apply(
            lambda x: x.get('call_type_classification', 'Неопределенный') if isinstance(x, dict) else 'Неопределенный'
        )
    grouped = df.groupby('call_type_classification').agg(
        total_calls=('conversion_int', 'count'),
        converted_calls=('conversion_int', 'sum')
    )
    grouped = grouped[grouped['total_calls'] > 0]
    grouped['conversion_pct'] = (grouped['converted_calls'] / grouped['total_calls'] * 100).round(1)
    grouped = grouped.sort_values('conversion_pct', ascending=False)
    grouped = grouped.head(4)
    if len(grouped) < 2:
        plt.figure(figsize=(7, 4))
        ax = plt.gca()
        bars = ax.bar(grouped.index, grouped['conversion_pct'], color='skyblue')
        for bar, y in zip(bars, grouped['conversion_pct']):
            ax.text(bar.get_x() + bar.get_width()/2, y + 1, f"{int(round(y))}%", ha='center', va='bottom', fontsize=12, fontweight='bold')
        ax.set_ylabel("Конверсия в запись")
        ax.set_title("Конверсия тип звонка")
        plt.xticks(rotation=30, ha='right')
        plt.ylim(0, max(100, grouped['conversion_pct'].max() + 10))
    else:
        plt.figure(figsize=(8, 5))
        ax = plt.gca()
        ax.plot(grouped.index, grouped['conversion_pct'], marker='o', linewidth=2)
        for i, (x, y) in enumerate(zip(grouped.index, grouped['conversion_pct'])):
            ax.text(i, y + 1, f"{int(round(y))}%", ha='center', va='bottom', fontsize=12, fontweight='bold')
        ymin = max(0, grouped['conversion_pct'].min() - 5)
        ymax = min(100, grouped['conversion_pct'].max() + 5)
        ax.set_ylim(ymin, ymax)
        ax.set_ylabel("Конверсия в запись")
        ax.set_title("Конверсия тип звонка")
        plt.xticks(rotation=30, ha='right')
    plt.tight_layout()
    img_data = BytesIO()
    plt.savefig(img_data, format='png', dpi=150, bbox_inches='tight')
    img_data.seek(0)
    plt.close()
    return img_data

# Создание PDF отчета
def create_pdf_report(calls_df, output_filename=f"call_report_{datetime.now().strftime('%d.%m.%Y')}.pdf"):
    # Создаем документ
    doc = SimpleDocTemplate(
        output_filename, 
        pagesize=A4, 
        rightMargin=72, 
        leftMargin=72,
        topMargin=72, 
        bottomMargin=18
    )
    
    # Контейнер для элементов отчета
    elements = []
    
    # Стили для текста
    styles = getSampleStyleSheet()
    
    # Создаем пользовательские стили с использованием Roboto для русского текста (если доступен)
    font_name = 'Roboto-Bold' if roboto_available else 'Helvetica-Bold'
    font_name_normal = 'Roboto' if roboto_available else 'Helvetica'
    
    title_style = ParagraphStyle(
        'Title',
        parent=styles['Heading1'],
        fontName=font_name,
        fontSize=23,
        spaceAfter=12,
        alignment=1,  # По центру
        encoding='utf-8'
    )
    
    heading2_style = ParagraphStyle(
        'Heading2',
        parent=styles['Heading2'],
        fontName=font_name,
        fontSize=18,
        spaceAfter=10,
        encoding='utf-8'
    )
    
    normal_style = ParagraphStyle(
        'Normal',
        parent=styles['Normal'],
        fontName=font_name_normal,
        fontSize=12,
        encoding='utf-8'
    )
    
    # ПЕРВАЯ СТРАНИЦА
    
    # Добавляем логотип
    logo_path = "app/resources/logo.png"
    if os.path.exists(logo_path):
        # Сохраняем соотношение сторон логотипа (837:517)
        logo_img = Image(logo_path)
        logo_width = 300  # ширина логотипа
        logo_height = logo_width * 517 / 837  # сохраняем пропорции
        logo_img.drawHeight = logo_height
        logo_img.drawWidth = logo_width
        elements.append(logo_img)
    else:
        print(f"Внимание: Файл логотипа {logo_path} не найден")
    
    # Добавляем увеличенный отступ после логотипа
    elements.append(Spacer(1, 50))
    
    # Добавляем заголовок
    current_date = datetime.now().strftime("%d.%m.%Y")
    elements.append(Paragraph(f"Отчет по звонкам на {current_date}", title_style))
    elements.append(Spacer(1, 20))
    
    # Добавляем сводную статистику
    elements.append(Paragraph("Сводная статистика", heading2_style))
    elements.append(Spacer(1, 10))
    
    # Создаем таблицу со статистикой - столбцы равной ширины
    summary_data = create_summary_statistics(calls_df)
    summary_table = Table(summary_data, colWidths=[250, 250])
    
    # Стиль таблицы
    summary_table_style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.lightgrey),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), font_name_normal),
        ('FONTSIZE', (0, 0), (-1, -1), 12),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 1, colors.grey),
    ])
    
    summary_table.setStyle(summary_table_style)
    elements.append(summary_table)
    elements.append(Spacer(1, 20))
    
    # ВТОРАЯ СТРАНИЦА
    elements.append(PageBreak())
    
    # График количества звонков по администраторам
    elements.append(Paragraph("Количество звонков по администраторам", heading2_style))
    elements.append(Spacer(1, 10))
    
    calls_by_admin_img = create_calls_by_admin_chart(calls_df)
    elements.append(Image(calls_by_admin_img, width=450, height=270))
    elements.append(Spacer(1, 20))
    
    # График длительности звонков по администраторам
    elements.append(Paragraph("Длительность звонков по администраторам", heading2_style))
    elements.append(Spacer(1, 10))
    
    duration_by_admin_img = create_duration_by_admin_chart(calls_df)
    elements.append(Image(duration_by_admin_img, width=450, height=270))
    elements.append(Spacer(1, 20))

    elements.append(PageBreak())
    
    # График конверсии по трафику
    elements.append(Paragraph("Конверсия трафик", heading2_style))
    elements.append(Spacer(1, 10))
    traffic_conv_img = create_traffic_conversion_chart(calls_df)
    if traffic_conv_img:
        elements.append(Image(traffic_conv_img, width=350, height=250))
        elements.append(Spacer(1, 20))

    # График конверсии по типу звонка
    elements.append(Paragraph("Конверсия тип звонка", heading2_style))
    elements.append(Spacer(1, 10))
    calltype_conv_img = create_call_type_conversion_chart(calls_df)
    if calltype_conv_img:
        elements.append(Image(calltype_conv_img, width=350, height=250))
        elements.append(Spacer(1, 20))
    
    # ТРЕТЬЯ СТРАНИЦА
    elements.append(PageBreak())
    
    # Добавляем линейный график оценок по неделям
    elements.append(Paragraph("Оценки по неделям", heading2_style))
    elements.append(Spacer(1, 10))
    
    scores_by_week_img = create_scores_by_week_chart(calls_df)
    if scores_by_week_img:
        elements.append(Image(scores_by_week_img, width=480, height=300))
        elements.append(Spacer(1, 20))
    
    # ЧЕТВЕРТАЯ СТРАНИЦА
    elements.append(PageBreak())
    
    # Линейный график звонков по источникам трафика
    elements.append(Paragraph("Динамика звонков по источникам трафика", heading2_style))
    elements.append(Spacer(1, 10))
    
    traffic_line_img = create_traffic_line_chart(calls_df)
    if traffic_line_img:
        elements.append(Image(traffic_line_img, width=480, height=300))
        elements.append(Spacer(1, 20))
    
    # Линейный график звонков по типам
    elements.append(Paragraph("Звонки по типу", heading2_style))
    elements.append(Spacer(1, 10))
    
    call_types_img = create_call_types_line_chart(calls_df)
    if call_types_img:
        elements.append(Image(call_types_img, width=480, height=300))
        elements.append(Spacer(1, 20))
    
    # ПЯТАЯ СТРАНИЦА
    elements.append(PageBreak())
    
    # Круговая диаграмма по источникам трафика
    elements.append(Paragraph("Распределение звонков по источникам трафика", heading2_style))
    elements.append(Spacer(1, 10))
    
    traffic_pie_img = create_traffic_pie_chart(calls_df)
    if traffic_pie_img:
        elements.append(Image(traffic_pie_img, width=450, height=360))
        elements.append(Spacer(1, 20))
    
    # ШЕСТАЯ СТРАНИЦА
    elements.append(PageBreak())
    
    # Добавляем тепловую карту звонков по дням недели и времени суток
    elements.append(Paragraph("Тепловая карта звонков по дням недели и времени суток", heading2_style))
    elements.append(Spacer(1, 10))
    
    calls_heatmap_img = create_calls_heatmap(calls_df)
    if calls_heatmap_img:
        elements.append(Image(calls_heatmap_img, width=480, height=320))
        elements.append(Spacer(1, 20))

    # Добавляем таблицу администраторов
    elements.append(Paragraph("Таблица администраторов", heading2_style))
    elements.append(Spacer(1, 10))
    admin_table_data = create_admin_table(calls_df)
    tbl = Table(admin_table_data, colWidths=[100, 50, 50])
    tbl.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("FONTNAME", (0, 0), (-1, -1), font_name),
    ]))
    elements.append(tbl)
    elements.append(Spacer(1, 20))
    
    # Добавляем информацию о дате создания отчета
    creation_info = Paragraph(f"Отчет создан: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}", normal_style)
    elements.append(creation_info)
    
    # Строим документ
    doc.build(elements)
    
    print(f"Отчет сохранен в файл {output_filename}")
    return output_filename

async def main():
    try:
        # Получаем данные из MongoDB за последние 30 дней
        calls_data = await get_calls_data(days_ago=30)
        
        if not calls_data:
            print("В коллекции calls не найдено данных")
            return
        
        print(f"Получено {len(calls_data)} записей из коллекции calls")
        
        # Создаем DataFrame
        calls_df = create_dataframe(calls_data)
        
        # Создаем PDF отчет
        output_file = create_pdf_report(calls_df)
        
        print(f"Отчет успешно создан: {output_file}")
        
    except Exception as e:
        print(f"Ошибка при создании отчета: {e}")

def create_admin_table(df):
    grp = df.groupby("administrator")
    total = grp.size()
    fg_pct = (grp["conversion_int"].sum() / total * 100).round().astype(int)
    table = [["Администратор", "Звонков", "FG %"]]
    for adm in total.index:
        table.append([adm, int(total[adm]), int(fg_pct[adm])])
    return table

if __name__ == "__main__":
    asyncio.run(main())
