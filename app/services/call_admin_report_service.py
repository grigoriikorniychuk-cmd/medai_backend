import os
from io import BytesIO
import asyncio
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import seaborn as sns
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, PageBreak, Table, TableStyle, Flowable
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.units import inch

from .mongodb_service import mongodb_service
from ..settings.paths import DATA_DIR
import logging

# Получаем логгер
logger = logging.getLogger(__name__)

# Настройка тёмной темы для seaborn
plt.style.use('dark_background')
sns.set_theme(style="darkgrid")

# Определяем класс для создания темного фона страницы в PDF
class DarkBackground(Flowable):
    """Создает темный фон для страницы PDF"""
    
    def __init__(self, width=None, height=None):
        Flowable.__init__(self)
        self.width = width or A4[0]
        self.height = height or A4[1]
        
    def wrap(self, availWidth, availHeight):
        return (self.width, self.height)
    
    def draw(self):
        self.canv.saveState()
        self.canv.setFillColor(colors.Color(0.15, 0.15, 0.15))  # Темно-серый цвет
        self.canv.rect(0, 0, self.width, self.height, fill=1, stroke=0)
        self.canv.restoreState()

class CallAdminReportService:
    """Сервис для создания отчетов по администраторам звонков"""
    
    def __init__(self):
        """Инициализация сервиса"""
        # Создаем директории для отчетов если их нет
        self.reports_dir = os.path.join(DATA_DIR, "admin_reports")
        self.temp_dir = os.path.join(self.reports_dir, "temp")
        os.makedirs(self.reports_dir, exist_ok=True)
        os.makedirs(self.temp_dir, exist_ok=True)
        
        # Регистрируем шрифты
        self._register_fonts()
    
    def _register_fonts(self):
        """Регистрирует шрифты с поддержкой кириллицы для PDF-отчётов"""
        try:
            # Пути к шрифтам
            font_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts"
            )

            # Проверяем и регистрируем шрифты
            dejavu_sans_path = os.path.join(font_dir, "DejaVuSans.ttf")
            dejavu_sans_bold_path = os.path.join(font_dir, "DejaVuSans-Bold.ttf")

            if not os.path.exists(dejavu_sans_path) or not os.path.exists(
                dejavu_sans_bold_path
            ):
                logger.warning(f"Шрифты не найдены в {font_dir}")
                return "Helvetica", "Helvetica-Bold"

            # Регистрируем шрифты
            pdfmetrics.registerFont(TTFont("DejaVuSans", dejavu_sans_path))
            pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", dejavu_sans_bold_path))
            pdfmetrics.registerFontFamily(
                "DejaVuSans", normal="DejaVuSans", bold="DejaVuSans-Bold"
            )

            logger.info("Шрифты DejaVu Sans успешно зарегистрированы")
            return "DejaVuSans", "DejaVuSans-Bold"

        except Exception as e:
            logger.error(f"Ошибка при регистрации шрифтов: {e}")
            return "Helvetica", "Helvetica-Bold"
    
    async def get_calls_data(self, days_ago=30):
        """Получение данных о звонках из MongoDB"""
        try:
            # Получение даты для фильтрации (например, последние 30 дней)
            start_date = datetime.now() - timedelta(days=days_ago)
            
            # Используем db напрямую из mongodb_service
            calls_collection = mongodb_service.db["calls"]
            
            # Пробуем фильтровать по recorded_at
            calls = await calls_collection.find(
                {"recorded_at": {"$gte": start_date.isoformat()}}
            ).to_list(length=None)
            
            if not calls:
                # Если нет данных, пробуем фильтровать по created_at (timestamp)
                timestamp = int(start_date.timestamp())
                calls = await calls_collection.find(
                    {"created_at": {"$gte": timestamp}}
                ).to_list(length=None)
                
            if not calls:
                # Если всё ещё нет данных, получаем все записи
                calls = await calls_collection.find().to_list(length=None)
                logger.info("Получение всех данных без фильтрации по дате")
            else:
                logger.info(f"Получены данные за последние {days_ago} дней")
        
            return calls
        except Exception as e:
            logger.error(f"Ошибка при получении данных из MongoDB: {e}")
            return []
    
    def create_dataframe(self, calls_data):
        """Создание DataFrame из данных MongoDB"""
        df = pd.DataFrame(calls_data)
        
        # Преобразуем recorded_at и created_at в datetime
        if 'recorded_at' in df.columns:
            df['recorded_at'] = pd.to_datetime(df['recorded_at'])
        if 'created_at' in df.columns and df['created_at'].dtype == 'O':
            df['created_at'] = pd.to_numeric(df['created_at'], errors='coerce')
            df['created_at'] = pd.to_datetime(df['created_at'], unit='s')
        
        return df
    
    def create_calls_by_admin_chart(self, df):
        """Генерация графика количества звонков по администраторам"""
        plt.figure(figsize=(10, 6))
        
        # Используем новый синтаксис seaborn 0.13+
        ax = sns.countplot(data=df, y='administrator', hue='administrator', legend=False, palette='viridis')
        ax.set_title('Количество звонков по администраторам', fontsize=16, color='white')
        ax.set_xlabel('Количество звонков', fontsize=12, color='white')
        ax.set_ylabel('Администратор', fontsize=12, color='white')
        
        # Добавление количества звонков в виде текста
        for p in ax.patches:
            width = p.get_width()
            ax.text(width + 1, p.get_y() + p.get_height()/2, f'{width:.0f}', 
                    ha='left', va='center', color='white', fontsize=10)
        
        # Настройка темной темы для графика
        ax.set_facecolor('#1a1a1a')  # Темный фон для графика
        ax.figure.set_facecolor('#1a1a1a')  # Темный фон для фигуры
        plt.tight_layout()
        
        # Сохраняем график в BytesIO
        img_data = BytesIO()
        plt.savefig(img_data, format='png', dpi=150, bbox_inches='tight', facecolor='#1a1a1a')
        img_data.seek(0)
        plt.close()
        
        return img_data
    
    def create_duration_by_admin_chart(self, df):
        """Генерация графика длительности звонков по администраторам (в минутах)"""
        # Группировка данных по администраторам и подсчёт суммарной длительности в минутах
        duration_by_admin = df.groupby('administrator')['duration'].sum() / 60
        duration_df = pd.DataFrame({'administrator': duration_by_admin.index, 
                                   'duration_minutes': duration_by_admin.values})
        
        plt.figure(figsize=(10, 6))
        
        # Используем новый синтаксис seaborn 0.13+
        ax = sns.barplot(data=duration_df, x='duration_minutes', y='administrator', 
                        hue='administrator', legend=False, palette='magma')
        ax.set_title('Общая длительность звонков по администраторам (минуты)', fontsize=16, color='white')
        ax.set_xlabel('Длительность (минуты)', fontsize=12, color='white')
        ax.set_ylabel('Администратор', fontsize=12, color='white')
        
        # Добавление длительности в виде текста
        for p in ax.patches:
            width = p.get_width()
            ax.text(width + 1, p.get_y() + p.get_height()/2, f'{width:.1f} мин', 
                    ha='left', va='center', color='white', fontsize=10)
        
        # Настройка темной темы для графика
        ax.set_facecolor('#1a1a1a')  # Темный фон для графика
        ax.figure.set_facecolor('#1a1a1a')  # Темный фон для фигуры
        plt.tight_layout()
        
        # Сохраняем график в BytesIO
        img_data = BytesIO()
        plt.savefig(img_data, format='png', dpi=150, bbox_inches='tight', facecolor='#1a1a1a')
        img_data.seek(0)
        plt.close()
        
        return img_data
    
    def create_calls_heatmap(self, df):
        """Создание тепловой карты звонков по дням недели и часам"""
        # Проверка наличия данных о времени звонков
        if 'recorded_at' not in df.columns and 'created_at' not in df.columns:
            logger.warning("Отсутствуют данные о времени звонков для создания тепловой карты")
            return None
            
        # Используем recorded_at если есть, иначе created_at
        time_column = 'recorded_at' if 'recorded_at' in df.columns else 'created_at'
        
        # Словарь для перевода дней недели на русский
        weekday_ru = {
            'Monday': 'Понедельник',
            'Tuesday': 'Вторник',
            'Wednesday': 'Среда',
            'Thursday': 'Четверг',
            'Friday': 'Пятница',
            'Saturday': 'Суббота',
            'Sunday': 'Воскресенье'
        }
        
        # Извлекаем день недели и час
        df['weekday_en'] = df[time_column].dt.day_name()
        df['weekday'] = df['weekday_en'].map(weekday_ru)
        df['hour'] = df[time_column].dt.hour
        
        # Создаем сводную таблицу для подсчета звонков
        heatmap_data = df.pivot_table(
            index='weekday', 
            columns='hour',
            values='_id',  # или любое другое поле, которое точно существует в данных
            aggfunc='count',
            fill_value=0
        )
        
        # Упорядочиваем дни недели
        weekday_order_ru = [weekday_ru[day] for day in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']]
        try:
            heatmap_data = heatmap_data.reindex(weekday_order_ru)
        except KeyError as e:
            # Если в данных мало дней, некоторые могут отсутствовать
            logger.warning(f"Некоторые дни недели отсутствуют в данных: {e}")
        
        # Форматируем заголовки часов (добавляем ведущие нули)
        hour_labels = [f"{h:02d}:00" for h in range(24)]
        
        # Создаем тепловую карту
        plt.figure(figsize=(12, 7))
        ax = sns.heatmap(
            heatmap_data,
            cmap='viridis',
            annot=True,
            fmt='g',
            linewidths=.5,
            cbar_kws={'label': 'Количество звонков'}
        )
        
        # Настройка осей и заголовка
        ax.set_title('Распределение звонков по дням недели и часам', fontsize=16, color='white')
        ax.set_xlabel('Час дня', fontsize=12, color='white')
        ax.set_ylabel('День недели', fontsize=12, color='white')
        
        # Настраиваем метки часов, если есть все 24 часа в данных
        if len(ax.get_xticklabels()) == 24:
            ax.set_xticklabels(hour_labels, rotation=45)
        
        # Настройка темной темы
        ax.set_facecolor('#1a1a1a')
        ax.figure.set_facecolor('#1a1a1a')
        
        # Настраиваем цвет меток
        for text in ax.texts:
            text.set_color('black')  # Цвет текста значений внутри ячеек
        
        # Настройка цвета текста осей
        plt.setp(ax.get_xticklabels(), color='white')
        plt.setp(ax.get_yticklabels(), color='white')
        
        # Настройка цвета подписи цветовой шкалы
        cbar = ax.collections[0].colorbar
        cbar.ax.yaxis.label.set_color('white')
        plt.setp(plt.getp(cbar.ax, 'yticklabels'), color='white')
        
        plt.tight_layout()
        
        # Сохраняем график в BytesIO
        img_data = BytesIO()
        plt.savefig(img_data, format='png', dpi=150, bbox_inches='tight', facecolor='#1a1a1a')
        img_data.seek(0)
        plt.close()
        
        return img_data
    
    def create_traffic_pie_chart(self, df):
        """Генерация круговой диаграммы звонков по источникам (трафику)"""
        # Подсчет звонков по источникам
        if 'source' not in df.columns:
            logger.warning("Колонка 'source' отсутствует в данных, использую 'Unknown'")
            df['source'] = 'Unknown'
            
        traffic_counts = df['source'].value_counts()
        
        # Создаем список подписей без процентов и без значений в скобках
        labels = [str(idx) for idx in traffic_counts.index]
        
        plt.figure(figsize=(10, 8))
        plt.pie(traffic_counts, labels=labels, 
                autopct='%1.1f%%',  # Оставляем проценты внутри диаграммы
                startangle=90, textprops={'color': 'white'}, 
                colors=sns.color_palette('viridis', len(traffic_counts)))
        plt.axis('equal')
        
        # Убираем титул из диаграммы, так как он дублируется в PDF
        # plt.title('Распределение звонков по источникам трафика', fontsize=16, color='white')
        
        # Настройка темной темы для графика
        plt.gcf().set_facecolor('#1a1a1a')  # Темный фон для фигуры
        
        # Сохраняем график в BytesIO
        img_data = BytesIO()
        plt.savefig(img_data, format='png', dpi=150, bbox_inches='tight', facecolor='#1a1a1a')
        img_data.seek(0)
        plt.close()
        
        return img_data
    
    def create_calls_trend_chart(self, df):
        """Создание графика трендов звонков по дням"""
        # Проверка наличия данных о времени звонков
        if 'recorded_at' not in df.columns and 'created_at' not in df.columns:
            logger.warning("Отсутствуют данные о времени звонков для создания графика трендов")
            return None
            
        # Используем recorded_at если есть, иначе created_at
        time_column = 'recorded_at' if 'recorded_at' in df.columns else 'created_at'
        
        # Создаем копию dataframe с датой без времени для группировки
        df = df.copy()
        df['date'] = df[time_column].dt.date
        
        # Группируем данные по дате и подсчитываем количество звонков
        calls_by_date = df.groupby('date').size().reset_index(name='count')
        calls_by_date['date'] = pd.to_datetime(calls_by_date['date'])
        calls_by_date = calls_by_date.sort_values('date')
        
        # Определяем тип визуализации в зависимости от количества дней
        num_days = len(calls_by_date)
        
        plt.figure(figsize=(12, 7))
        
        # Для малого количества дней используем столбчатую диаграмму
        if num_days <= 5:
            ax = sns.barplot(data=calls_by_date, x='date', y='count', color='#1f77b4')
            plt.title('Количество звонков по дням', fontsize=16, color='white')
        else:
            # Для большего количества дней используем линейный график
            ax = sns.lineplot(data=calls_by_date, x='date', y='count', marker='o', color='#1f77b4')
            
            # Если данных достаточно, добавляем скользящее среднее для выявления тренда
            if num_days >= 7:
                window_size = min(7, num_days // 2)  # Размер окна не более 7 и не больше половины набора данных
                calls_by_date['rolling_avg'] = calls_by_date['count'].rolling(window=window_size, center=True).mean()
                sns.lineplot(data=calls_by_date, x='date', y='rolling_avg', color='#ff7f0e', 
                             label=f'Скользящее среднее ({window_size} дней)')
                
            plt.title('Тренд количества звонков по дням', fontsize=16, color='white')
            plt.legend(loc='upper left', facecolor='#1a1a1a', edgecolor='gray', framealpha=0.9, fontsize=12)
        
        # Настройка осей
        ax.set_xlabel('Дата', fontsize=12, color='white')
        ax.set_ylabel('Количество звонков', fontsize=12, color='white')
        
        # Настройка формата дат на оси X в зависимости от диапазона
        if num_days <= 14:
            date_format = '%d.%m'
            ax.xaxis.set_major_formatter(mdates.DateFormatter(date_format))
            plt.xticks(rotation=45)
        else:
            ax.xaxis.set_major_locator(mdates.AutoDateLocator())
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m'))
            plt.xticks(rotation=45)
            
        # Настройка темной темы
        ax.set_facecolor('#1a1a1a')
        ax.figure.set_facecolor('#1a1a1a')
        plt.grid(True, alpha=0.3)
        
        # Настройка цвета меток
        plt.setp(ax.get_xticklabels(), color='white')
        plt.setp(ax.get_yticklabels(), color='white')
        
        plt.tight_layout()
        
        # Сохраняем график в BytesIO
        img_data = BytesIO()
        plt.savefig(img_data, format='png', dpi=150, bbox_inches='tight', facecolor='#1a1a1a')
        img_data.seek(0)
        plt.close()
        
        return img_data
    
    def create_summary_statistics(self, df):
        """Создание сводной статистики"""
        # Определяем период, за который собраны данные
        date_range = "Неизвестный период"
        if 'created_at' in df.columns:
            try:
                min_date = df['created_at'].min()
                max_date = df['created_at'].max()
                
                logger.info(f"Даты: min_date={min_date}, max_date={max_date}, типы: {type(min_date)}, {type(max_date)}")
                
                # Проверка и преобразование типа данных
                if hasattr(min_date, 'strftime'):
                    start_date = min_date.strftime('%d.%m.%Y')
                    end_date = max_date.strftime('%d.%m.%Y')
                else:
                    start_date = pd.to_datetime(min_date).strftime('%d.%m.%Y')
                    end_date = pd.to_datetime(max_date).strftime('%d.%m.%Y')
                    
                date_range = f"{start_date} - {end_date}"
            except Exception as e:
                logger.error(f"Ошибка при форматировании дат: {e}")
                import traceback
                logger.error(traceback.format_exc())
        
        # Общее количество звонков
        total_calls = len(df)
        
        # Средняя длительность звонка в минутах (при наличии данных)
        avg_duration = df['duration'].mean() / 60 if 'duration' in df.columns else 0
        
        # Общая длительность всех звонков в минутах
        total_duration = df['duration'].sum() / 60 if 'duration' in df.columns else 0
        
        # Количество уникальных администраторов
        admin_count = df['administrator'].nunique() if 'administrator' in df.columns else 0
        
        # Логгируем значения
        logger.info(f"Статистика: total_calls={total_calls}, avg_duration={avg_duration} ({type(avg_duration)}), "
                    f"total_duration={total_duration} ({type(total_duration)}), admin_count={admin_count}")
        
        return {
            'date_range': date_range,
            'total_calls': total_calls,
            'avg_duration': round(avg_duration, 2),
            'total_duration': round(total_duration, 2),
            'admin_count': admin_count
        }
    
    def create_pdf_report(self, calls_df, output_filename="call_admin_report.pdf"):
        """Создание PDF-отчета"""
        # Проверяем наличие директории для отчетов
        report_path = os.path.join(self.reports_dir, output_filename)
        
        # Создаем документ с SimpleDocTemplate
        doc = SimpleDocTemplate(
            report_path,
            pagesize=A4,
            rightMargin=inch/2,
            leftMargin=inch/2,
            topMargin=inch/2,
            bottomMargin=inch/2
        )
        
        # Определяем функцию для рисования фона на каждой странице
        def on_page(canvas, doc):
            # Сохраняем состояние канваса
            canvas.saveState()
            
            # Рисуем темный фон
            canvas.setFillColor(colors.Color(0.15, 0.15, 0.15))  # Темно-серый цвет
            canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
            
            # Восстанавливаем состояние канваса
            canvas.restoreState()
        
        # Создаем стили для текста
        styles = getSampleStyleSheet()
        
        # Создаем свои стили для темной темы
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Title'],
            fontName='DejaVuSans-Bold',
            fontSize=20,
            textColor=colors.whitesmoke,
            spaceAfter=20,
            alignment=1  # По центру
        )
        
        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontName='DejaVuSans-Bold',
            fontSize=16,
            textColor=colors.whitesmoke,
            spaceAfter=10
        )
        
        normal_style = ParagraphStyle(
            'CustomNormal',
            parent=styles['Normal'],
            fontName='DejaVuSans',
            fontSize=12,
            textColor=colors.whitesmoke,
            spaceAfter=6
        )
        
        # Создаем элементы для отчета
        elements = []
        
        # Добавляем заголовок
        elements.append(Paragraph("Отчет по звонкам администраторов", title_style))
        elements.append(Spacer(1, 20))
        
        # Генерируем сводную статистику
        summary_stats = self.create_summary_statistics(calls_df)
        
        # Логгируем типы данных в summary_stats
        logger.info(f"Типы данных в summary_stats: date_range={type(summary_stats['date_range'])}, "
                   f"total_calls={type(summary_stats['total_calls'])}, "
                   f"avg_duration={type(summary_stats['avg_duration'])}, "
                   f"total_duration={type(summary_stats['total_duration'])}, "
                   f"admin_count={type(summary_stats['admin_count'])}")
        
        # Создаем таблицу со сводной статистикой
        elements.append(Paragraph("Сводная статистика", heading_style))
        
        # Данные для таблицы
        data = [
            ["Период", summary_stats['date_range']],
            ["Всего звонков", str(summary_stats['total_calls'])],
            ["Количество администраторов", str(summary_stats['admin_count'])],
            ["Средняя длительность звонка", f"{float(summary_stats['avg_duration']):.2f} мин"],
            ["Общая длительность звонков", f"{float(summary_stats['total_duration']):.2f} мин"]
        ]
        
        # Логгируем данные таблицы
        logger.info(f"Данные таблицы: {data}")
        
        # Создаем таблицу
        summary_table = Table(data, colWidths=[3*inch, 3*inch])
        
        # Стиль таблицы
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.Color(0.2, 0.2, 0.2)),
            ('BACKGROUND', (1, 0), (1, -1), colors.Color(0.25, 0.25, 0.25)),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), 'DejaVuSans'),
            ('FONTSIZE', (0, 0), (-1, -1), 12),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.Color(0.3, 0.3, 0.3))
        ]))
        
        elements.append(summary_table)
        elements.append(Spacer(1, 20))
        
        # Генерируем графики
        elements.append(Paragraph("Звонки по администраторам", heading_style))
        elements.append(Spacer(1, 10))
        
        # График количества звонков по администраторам
        calls_chart = self.create_calls_by_admin_chart(calls_df)
        elements.append(Image(calls_chart, width=6*inch, height=4*inch))
        elements.append(Spacer(1, 20))
        
        # График длительности звонков по администраторам
        elements.append(Paragraph("Длительность звонков по администраторам", heading_style))
        elements.append(Spacer(1, 10))
        
        duration_chart = self.create_duration_by_admin_chart(calls_df)
        elements.append(Image(duration_chart, width=6*inch, height=4*inch))
        elements.append(Spacer(1, 20))
        
        # Добавляем график тренда звонков по дням
        elements.append(Paragraph("Тренд количества звонков по дням", heading_style))
        elements.append(Spacer(1, 10))
        
        # Создаем график тренда
        trend_chart = self.create_calls_trend_chart(calls_df)
        
        # Добавляем график, если он успешно создан
        if trend_chart:
            elements.append(Image(trend_chart, width=7*inch, height=3.5*inch))
            elements.append(Spacer(1, 20))
        else:
            elements.append(Paragraph("Недостаточно данных для построения графика тренда", normal_style))
            elements.append(Spacer(1, 20))
        
        # Добавляем тепловую карту распределения звонков
        elements.append(Paragraph("Распределение звонков по дням недели и часам", heading_style))
        elements.append(Spacer(1, 10))
        
        # Создаем тепловую карту
        heatmap_chart = self.create_calls_heatmap(calls_df)
        
        # Добавляем тепловую карту, если она успешно создана
        if heatmap_chart:
            elements.append(Image(heatmap_chart, width=7*inch, height=5*inch))
            elements.append(Spacer(1, 20))
        else:
            elements.append(Paragraph("Недостаточно данных для построения тепловой карты", normal_style))
            elements.append(Spacer(1, 20))
        
        # График распределения звонков по источникам
        elements.append(Paragraph("Распределение звонков по источникам трафика", heading_style))
        elements.append(Spacer(1, 10))
        
        traffic_chart = self.create_traffic_pie_chart(calls_df)
        elements.append(Image(traffic_chart, width=5*inch, height=5*inch))
        
        # Создаем PDF отчет
        doc.build(elements, onFirstPage=on_page, onLaterPages=on_page)
        
        return report_path
    
    async def generate_report(self, days_ago=30, output_filename="call_admin_report.pdf"):
        """Основная функция для генерации отчета"""
        try:
            # Получаем данные из MongoDB
            calls_data = await self.get_calls_data(days_ago)
            
            if not calls_data:
                logger.error("Не удалось получить данные о звонках из MongoDB")
                return None
            
            # Создаем DataFrame из данных
            calls_df = self.create_dataframe(calls_data)
            
            # Создаем PDF отчет
            report_path = self.create_pdf_report(calls_df, output_filename)
            
            logger.info(f"Отчет успешно создан и сохранен: {report_path}")
            return report_path
        
        except Exception as e:
            logger.error(f"Ошибка при генерации отчета: {e}")
            return None
    
    def cleanup(self):
        """Очистка временных файлов"""
        try:
            for file in os.listdir(self.temp_dir):
                file_path = os.path.join(self.temp_dir, file)
                if os.path.isfile(file_path):
                    os.unlink(file_path)
            logger.info("Временные файлы очищены")
        except Exception as e:
            logger.error(f"Ошибка при очистке временных файлов: {e}")


# Создаем экземпляр сервиса
call_admin_report_service = CallAdminReportService() 