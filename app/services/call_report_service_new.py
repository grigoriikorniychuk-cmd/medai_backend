import os
from io import BytesIO
from datetime import datetime, timedelta
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
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, PageBreak, Table, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from app.settings.paths import MONGO_URI, DB_NAME, REPORTS_DIR
import logging

logger = logging.getLogger(__name__)

class CallReportService:
    def __init__(self, mongodb_uri=None, mongodb_name=None):
        self.mongodb_uri = mongodb_uri or MONGO_URI
        self.mongodb_name = mongodb_name or DB_NAME
        self.client = None
        self.db = None
        self.calls_collection = None
        
        # Путь к шрифтам
        self.FONTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'fonts')
        
        # Флаг, указывающий, доступны ли шрифты Roboto
        self.roboto_available = False
        
        # Установка стандартной светлой темы для графиков
        plt.style.use('default')
        sns.set_theme(style="whitegrid")
        
        # Регистрация шрифтов
        self._register_fonts()
    
    def _register_fonts(self):
        """Регистрация шрифтов Roboto для использования в ReportLab"""
        try:
            # Проверка существования директории со шрифтами
            if not os.path.exists(self.FONTS_DIR):
                logger.warning(f"Директория со шрифтами не найдена: {self.FONTS_DIR}")
                # Альтернативный путь
                alt_dir = '/app/fonts'
                if os.path.exists(alt_dir):
                    self.FONTS_DIR = alt_dir
                else:
                    logger.warning(f"Альтернативная директория со шрифтами также не найдена")
                    return
            
            roboto_regular_path = os.path.join(self.FONTS_DIR, 'Roboto-Regular.ttf')
            roboto_bold_path = os.path.join(self.FONTS_DIR, 'Roboto-Bold.ttf')
            
            # Проверяем существование файлов шрифтов
            if os.path.exists(roboto_regular_path) and os.path.exists(roboto_bold_path):
                pdfmetrics.registerFont(TTFont('Roboto', roboto_regular_path))
                pdfmetrics.registerFont(TTFont('Roboto-Bold', roboto_bold_path))
                self.roboto_available = True
                logger.info(f"Шрифты Roboto успешно зарегистрированы")
            else:
                logger.warning(f"Файлы шрифтов не найдены: {roboto_regular_path}, {roboto_bold_path}")
                logger.warning("Будут использованы стандартные шрифты")
        except Exception as e:
            logger.error(f"Ошибка при регистрации шрифтов: {e}")
            logger.warning("Будут использованы стандартные шрифты")
    
    async def connect_db(self):
        """Подключение к MongoDB"""
        try:
            self.client = AsyncIOMotorClient(self.mongodb_uri)
            self.db = self.client[self.mongodb_name]
            self.calls_collection = self.db['calls']
            logger.info(f"Подключение к MongoDB успешно установлено")
        except Exception as e:
            logger.error(f"Ошибка подключения к MongoDB: {e}")
            raise
    
    async def close_db(self):
        """Закрытие соединения с MongoDB"""
        if self.client:
            self.client.close()
    
    async def get_calls_data(self, start_date, end_date, clinic_id=None):
        """
        Получение данных о звонках за указанный период и для указанной клиники
        
        Args:
            start_date (datetime): Дата начала периода
            end_date (datetime): Дата конца периода
            clinic_id (str, optional): ID клиники
            
        Returns:
            list: Список документов с данными о звонках
        """
        # Проверяем, установлено ли соединение с БД
        if not self.client:
            await self.connect_db()
        
        # Создаем базовый фильтр по датам
        query = {
            'created_at': {
                '$gte': start_date.timestamp(),
                '$lte': end_date.timestamp()
            }
        }
        
        # Добавляем фильтр по клинике, если указан
        if clinic_id:
            query['client_id'] = clinic_id
        
        # Запрос данных
        calls_data = await self.calls_collection.find(query).to_list(length=None)
        
        logger.info(f"Найдено документов: {len(calls_data)}")
        
        return calls_data
    
    def create_dataframe(self, calls_data):
        """
        Создание DataFrame из данных MongoDB
        
        Args:
            calls_data (list): Список документов с данными о звонках
            
        Returns:
            pandas.DataFrame: DataFrame с данными о звонках
        """
        df = pd.DataFrame(calls_data)
        
        # Преобразуем timestamp в даты
        if 'created_at' in df.columns and len(df) > 0:
            df['created_at'] = pd.to_datetime(df['created_at'], unit='s')
        
        # Извлекаем поле conversion
        try:
            if 'analysis' in df.columns:
                logger.info("Извлекаем conversion из analysis...")
                # Создаем новую колонку для конверсии
                df['conversion'] = df['analysis'].apply(
                    lambda x: x.get('conversion', False) if isinstance(x, dict) else False
                )
                # Преобразуем в числовой формат для подсчета
                df['conversion_int'] = df['conversion'].astype(int)
                if not df['conversion'].empty:
                    logger.info(f"Распределение значений conversion: {df['conversion'].value_counts().to_dict()}")
        except Exception as e:
            logger.error(f"Ошибка при извлечении поля conversion: {e}")
        
        return df
    
    async def generate_report(self, start_date_str, end_date_str, clinic_id=None):
        """
        Генерация отчета по звонкам
        
        Args:
            start_date_str (str): Дата начала периода в формате ДД.ММ.ГГГГ
            end_date_str (str): Дата конца периода в формате ДД.ММ.ГГГГ
            clinic_id (str, optional): ID клиники
            
        Returns:
            str: Путь к сгенерированному PDF-файлу
        """
        try:
            # Преобразование строковых дат в объекты datetime
            start_date = datetime.strptime(start_date_str, "%d.%m.%Y")
            end_date = datetime.strptime(end_date_str, "%d.%m.%Y")
            
            # Устанавливаем конец дня для end_date
            end_date = end_date.replace(hour=23, minute=59, second=59)
            
            # Получаем данные о звонках
            calls_data = await self.get_calls_data(start_date, end_date, clinic_id)
            
            if not calls_data:
                logger.warning("Не найдено данных о звонках за указанный период")
                return None
            
            # Создаем DataFrame
            calls_df = self.create_dataframe(calls_data)
            
            # Создаем директорию для отчетов, если она не существует
            os.makedirs(REPORTS_DIR, exist_ok=True)
            
            # Название отчета
            clinic_suffix = f"_clinic_{clinic_id}" if clinic_id else ""
            period_suffix = f"_{start_date_str}-{end_date_str}".replace(".", "_")
            output_filename = os.path.join(REPORTS_DIR, f"call_report{clinic_suffix}{period_suffix}.pdf")
            
            # Генерируем PDF-отчет
            self._create_pdf_report(calls_df, output_filename)
            
            return output_filename
            
        except Exception as e:
            logger.error(f"Ошибка при генерации отчета: {e}")
            import traceback
            traceback.print_exc()
            return None
        finally:
            # Закрываем соединение с БД
            await self.close_db()
    
    def _create_pdf_report(self, calls_df, output_filename):
        """
        Создание PDF-отчета
        
        Args:
            calls_df (pandas.DataFrame): DataFrame с данными о звонках
            output_filename (str): Имя файла отчета
            
        Returns:
            str: Путь к сгенерированному PDF-файлу
        """
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
        font_name = 'Roboto-Bold' if self.roboto_available else 'Helvetica-Bold'
        font_name_normal = 'Roboto' if self.roboto_available else 'Helvetica'
        
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
            logger.warning(f"Внимание: Файл логотипа {logo_path} не найден")
        
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
        summary_data = self._create_summary_statistics(calls_df)
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
        
        calls_by_admin_img = self._create_calls_by_admin_chart(calls_df)
        if calls_by_admin_img:
            elements.append(Image(calls_by_admin_img, width=450, height=270))
            elements.append(Spacer(1, 20))
        
        # График длительности звонков по администраторам
        elements.append(Paragraph("Длительность звонков по администраторам", heading2_style))
        elements.append(Spacer(1, 10))
        
        duration_by_admin_img = self._create_duration_by_admin_chart(calls_df)
        if duration_by_admin_img:
            elements.append(Image(duration_by_admin_img, width=450, height=270))
            elements.append(Spacer(1, 20))
        
        # ТРЕТЬЯ СТРАНИЦА
        elements.append(PageBreak())
        
        # Добавляем линейный график оценок по неделям
        elements.append(Paragraph("Оценки по неделям", heading2_style))
        elements.append(Spacer(1, 10))
        
        scores_by_week_img = self._create_scores_by_week_chart(calls_df)
        if scores_by_week_img:
            elements.append(Image(scores_by_week_img, width=480, height=300))
            elements.append(Spacer(1, 20))
        
        # ЧЕТВЕРТАЯ СТРАНИЦА
        elements.append(PageBreak())
        
        # Линейный график звонков по источникам трафика
        elements.append(Paragraph("Динамика звонков по источникам трафика", heading2_style))
        elements.append(Spacer(1, 10))
        
        traffic_line_img = self._create_traffic_line_chart(calls_df)
        if traffic_line_img:
            elements.append(Image(traffic_line_img, width=480, height=300))
            elements.append(Spacer(1, 20))
        
        # Линейный график звонков по типам
        elements.append(Paragraph("Звонки по типу", heading2_style))
        elements.append(Spacer(1, 10))
        
        call_types_img = self._create_call_types_line_chart(calls_df)
        if call_types_img:
            elements.append(Image(call_types_img, width=480, height=300))
            elements.append(Spacer(1, 20))
        
        # ПЯТАЯ СТРАНИЦА
        elements.append(PageBreak())
        
        # Круговая диаграмма по источникам трафика
        elements.append(Paragraph("Распределение звонков по источникам трафика", heading2_style))
        elements.append(Spacer(1, 10))
        
        traffic_pie_img = self._create_traffic_pie_chart(calls_df)
        if traffic_pie_img:
            elements.append(Image(traffic_pie_img, width=450, height=360))
            elements.append(Spacer(1, 20))
        
        # ШЕСТАЯ СТРАНИЦА
        elements.append(PageBreak())
        
        # Добавляем тепловую карту звонков по дням недели и времени суток
        elements.append(Paragraph("Тепловая карта звонков по дням недели и времени суток", heading2_style))
        elements.append(Spacer(1, 10))
        
        calls_heatmap_img = self._create_calls_heatmap(calls_df)
        if calls_heatmap_img:
            elements.append(Image(calls_heatmap_img, width=480, height=320))
            elements.append(Spacer(1, 20))
        
        # Добавляем информацию о дате создания отчета
        creation_info = Paragraph(f"Отчет создан: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}", normal_style)
        elements.append(creation_info)
        
        # Строим документ
        doc.build(elements)
        
        logger.info(f"Отчет сохранен в файл {output_filename}")
        return output_filename
    
    def _create_summary_statistics(self, df):
        """Создание сводной статистики"""
        # Определяем период, за который собраны данные
        if 'created_at' in df.columns and len(df) > 0:
            try:
                min_date = df['created_at'].min()
                max_date = df['created_at'].max()
                
                # Преобразование в строковый формат даты
                start_date = min_date.strftime('%d.%m.%Y')
                end_date = max_date.strftime('%d.%m.%Y')
                
                date_range = f"{start_date} - {end_date}"
            except:
                date_range = "Неизвестный период"
        else:
            date_range = "Неизвестный период"
        
        # Общее количество звонков
        total_calls = len(df)
        
        # Средняя длительность звонка в минутах
        avg_duration = df['duration'].mean() / 60 if 'duration' in df.columns and len(df) > 0 else 0
        
        # Общая длительность всех звонков в минутах
        total_duration = df['duration'].sum() / 60 if 'duration' in df.columns and len(df) > 0 else 0
        
        # Количество входящих и исходящих звонков
        incoming_calls = len(df[df['call_direction'] == 'Входящий']) if 'call_direction' in df.columns else 0
        outgoing_calls = len(df[df['call_direction'] == 'Исходящий']) if 'call_direction' in df.columns else 0
        
        # Расчет процента конверсии в запись
        conversion_percentage = None
        try:
            if 'conversion_int' in df.columns:
                # Подсчитываем количество конверсий (значение 1)
                converted_calls = df['conversion_int'].sum()
                if total_calls > 0:
                    conversion_percentage = (converted_calls / total_calls) * 100
            elif 'conversion' in df.columns:
                # Подсчитываем количество True значений
                converted_calls = df['conversion'].sum() if df['conversion'].dtype == 'bool' else len(df[df['conversion'] == True])
                if total_calls > 0:
                    conversion_percentage = (converted_calls / total_calls) * 100
        except Exception as e:
            logger.error(f"Ошибка при расчете конверсии: {e}")
        
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
        except Exception as e:
            logger.error(f"Ошибка при расчете FG%: {e}")
        
        # Расчет средней скорости обработки в минутах
        avg_processing_speed = None
        try:
            if 'processing_speed' in df.columns and len(df) > 0:
                avg_processing_speed = df['processing_speed'].mean()
        except Exception as e:
            logger.error(f"Ошибка при расчете средней скорости обработки: {e}")
        
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
    
    def _create_calls_by_admin_chart(self, df):
        """Функция для генерации графика количества звонков по администраторам"""
        try:
            if 'administrator' not in df.columns or len(df) == 0:
                return None
                
            plt.figure(figsize=(10, 6))
            
            # Используем новый синтаксис seaborn 0.13+
            # Привязываем 'administrator' к оси 'y' и к 'hue', отключаем легенду
            ax = sns.countplot(data=df, y='administrator', hue='administrator', legend=False, palette='viridis')
            ax.set_title('Количество звонков по администраторам', fontsize=16)
            ax.set_xlabel('Количество звонков', fontsize=12)
            ax.set_ylabel('Администратор', fontsize=12)
            
            # Настраиваем ось X для отображения только целых чисел
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
        except Exception as e:
            logger.error(f"Ошибка при создании графика звонков по администраторам: {e}")
            return None
    
    def _create_duration_by_admin_chart(self, df):
        """Функция для генерации графика длительности звонков по администраторам (в минутах)"""
        try:
            if 'administrator' not in df.columns or 'duration' not in df.columns or len(df) == 0:
                return None
                
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
        except Exception as e:
            logger.error(f"Ошибка при создании графика длительности звонков: {e}")
            return None
    
    # Дополнительные методы для создания графиков будут добавлены позже:
    def _create_traffic_pie_chart(self, df):
        """Функция для генерации круговой диаграммы звонков по источникам (трафику)"""
        try:
            # Проверка наличия поля 'source' в данных
            if 'source' not in df.columns or len(df) == 0:
                logger.warning("Колонка 'source' не найдена в данных")
                return None
                
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
        except Exception as e:
            logger.error(f"Ошибка при создании круговой диаграммы звонков по источникам: {e}")
            return None
    
    def _create_calls_heatmap(self, df):
        """Функция для создания тепловой карты звонков по дням недели и времени суток"""
        try:
            # Создаем копию DataFrame, чтобы не изменять оригинал
            df_copy = df.copy()
            
            # Проверяем, есть ли столбец created_at и преобразуем его в datetime, если он есть
            if 'created_at' not in df_copy.columns or len(df) == 0:
                logger.warning("Столбец 'created_at' не найден в данных")
                return None
            
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
            
            # Сортируем дни недели в правильном порядке
            day_order = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']
            heatmap_data = heatmap_data.reindex(day_order)
            
            # Создаем тепловую карту
            plt.figure(figsize=(14, 8))
            sns.heatmap(
                heatmap_data, 
                cmap='viridis', 
                linewidths=0.5, 
                annot=True, 
                fmt='g',
                cbar_kws={'label': 'Количество звонков'}
            )
            
            plt.title('Распределение звонков по дням недели и времени суток', fontsize=16)
            plt.xlabel('Час дня', fontsize=14)
            plt.ylabel('День недели', fontsize=14)
            
            # Сохраняем график в BytesIO
            img_data = BytesIO()
            plt.savefig(img_data, format='png', dpi=150, bbox_inches='tight')
            img_data.seek(0)
            plt.close()
            
            return img_data
        except Exception as e:
            logger.error(f"Ошибка при создании тепловой карты звонков: {e}")
            return None
    
    def _create_traffic_line_chart(self, df):
        """Функция для создания линейного графика звонков по источникам трафика"""
        try:
            # Проверяем наличие нужных полей
            if 'created_at' not in df.columns or 'source' not in df.columns or len(df) == 0:
                logger.warning("Отсутствуют обязательные поля для графика по трафику")
                return None
            
            # Копируем DataFrame для обработки
            df_copy = df.copy()
            
            # Убедимся, что 'created_at' в формате datetime
            if not pd.api.types.is_datetime64_any_dtype(df_copy['created_at']):
                df_copy['created_at'] = pd.to_datetime(df_copy['created_at'])
            
            # Добавляем поле с датой (без времени) для группировки
            df_copy['date'] = df_copy['created_at'].dt.date
            
            # Выбираем топ-5 источников по количеству звонков
            top_sources = df_copy['source'].value_counts().nlargest(5).index.tolist()
            
            # Фильтруем данные только по топ источникам
            df_filtered = df_copy[df_copy['source'].isin(top_sources)]
            
            # Группируем по источнику и дате, считаем количество звонков
            traffic_by_date = df_filtered.groupby(['source', 'date']).size().reset_index(name='count')
            
            # Создаем широкий формат данных для построения графика
            pivot_traffic = traffic_by_date.pivot(index='date', columns='source', values='count')
            
            # Заполняем NaN нулями
            pivot_traffic = pivot_traffic.fillna(0)
            
            # Если дат слишком много, выбираем только 5 равномерно распределенных дат
            if len(pivot_traffic) > 5:
                # Выбираем индексы для 5 дат
                selected_indices = np.linspace(0, len(pivot_traffic)-1, 5, dtype=int)
                pivot_traffic = pivot_traffic.iloc[selected_indices]
            
            # Создаем график
            plt.figure(figsize=(12, 7))
            
            # Подготавливаем форматированные даты для отображения на оси X (в формате ДД.ММ.ГГГГ)
            formatted_dates = [date.strftime('%d.%m.%Y') for date in pivot_traffic.index]
            
            # Строим линии для каждого источника, используя позиции на оси X
            x_positions = range(len(pivot_traffic.index))
            for source in pivot_traffic.columns:
                plt.plot(x_positions, pivot_traffic[source], marker='o', linewidth=2, label=source)
            
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
            
            # Добавляем отступы
            plt.tight_layout()
            
            # Сохраняем график в BytesIO
            img_data = BytesIO()
            plt.savefig(img_data, format='png', dpi=150, bbox_inches='tight')
            img_data.seek(0)
            plt.close()
            
            return img_data
        except Exception as e:
            logger.error(f"Ошибка при создании графика звонков по трафику: {e}")
            return None
    
    def _create_call_types_line_chart(self, df):
        """Функция для создания линейного графика звонков по типам"""
        try:
            # Копируем DataFrame для обработки
            df_copy = df.copy()
            
            # Проверяем и добавляем поле типа звонка, если его нет
            if 'call_type_classification' not in df_copy.columns:
                logger.info("Поле call_type_classification не найдено напрямую, пробуем извлечь из metrics...")
                # Пробуем извлечь из metrics, если оно есть
                if 'metrics' in df_copy.columns:
                    df_copy['call_type_classification'] = df_copy['metrics'].apply(
                        lambda x: x.get('call_type_classification', 'Неизвестно') if isinstance(x, dict) else 'Неизвестно'
                    )
                else:
                    # Если нет metrics, используем call_type, если оно есть
                    if 'call_type' in df_copy.columns:
                        df_copy['call_type_classification'] = df_copy['call_type']
                    else:
                        logger.warning("Не найдено поля для определения типа звонка")
                        return None
            
            # Проверяем наличие поля created_at
            if 'created_at' not in df_copy.columns:
                logger.warning("Поле created_at не найдено")
                return None
                
            # Убедимся, что 'created_at' в формате datetime
            if not pd.api.types.is_datetime64_any_dtype(df_copy['created_at']):
                df_copy['created_at'] = pd.to_datetime(df_copy['created_at'])
            
            # Добавляем поле с датой (без времени) для группировки
            df_copy['date'] = df_copy['created_at'].dt.date
            
            # Выбираем топ-5 типов звонков по количеству
            top_types = df_copy['call_type_classification'].value_counts().nlargest(5).index.tolist()
            
            # Группируем по типу звонка и дате, считаем количество звонков
            types_by_date = df_copy.groupby(['call_type_classification', 'date']).size().reset_index(name='count')
            
            # Фильтруем данные только по топ типам
            types_by_date = types_by_date[types_by_date['call_type_classification'].isin(top_types)]
            
            # Создаем широкий формат данных для построения графика
            pivot_types = types_by_date.pivot(index='date', columns='call_type_classification', values='count')
            
            # Заполняем NaN нулями
            pivot_types = pivot_types.fillna(0)
            
            # Если дат слишком много, выбираем только 5 равномерно распределенных дат
            if len(pivot_types) > 5:
                # Выбираем индексы для 5 дат
                selected_indices = np.linspace(0, len(pivot_types)-1, 5, dtype=int)
                pivot_types = pivot_types.iloc[selected_indices]
            
            # Проверяем, достаточно ли данных для построения графика
            if len(pivot_types) < 2:
                logger.warning("Недостаточно дат для построения графика")
                return None
            
            # Сортируем даты
            pivot_types = pivot_types.sort_index()
            
            # Создаем график
            plt.figure(figsize=(14, 8))
            
            # Подготавливаем форматированные даты для отображения на оси X (в формате ДД.ММ.ГГГГ)
            formatted_dates = [date.strftime('%d.%m.%Y') for date in pivot_types.index]
            
            # Строим линии для каждого типа звонка, используя позиции на оси X
            x_positions = range(len(pivot_types.index))
            for call_type in pivot_types.columns:
                plt.plot(x_positions, pivot_types[call_type], marker='o', linewidth=2, label=call_type)
            
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
            
            # Добавляем отступы
            plt.tight_layout()
            
            # Сохраняем график в BytesIO
            img_data = BytesIO()
            plt.savefig(img_data, format='png', dpi=150, bbox_inches='tight')
            img_data.seek(0)
            plt.close()
            
            return img_data
        except Exception as e:
            logger.error(f"Ошибка при создании графика звонков по типам: {e}")
            return None
    
    def _create_scores_by_week_chart(self, df):
        """Функция для создания линейного графика оценок по неделям"""
        try:
            # Копируем DataFrame для обработки
            df_copy = df.copy()
            
            # Проверяем наличие нужных полей
            if 'created_at' not in df_copy.columns or len(df) == 0:
                logger.warning("Отсутствует поле created_at для графика оценок по неделям")
                return None
                
            # Проверяем, есть ли метрики в данных
            if 'metrics' not in df_copy.columns:
                logger.warning("Отсутствуют метрики для графика оценок по неделям")
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
            
            # Критерии для анализа - теперь проверяем все возможные критерии
            all_possible_criteria = [
                # Критерии первички (17 критериев в правильном порядке)
                'greeting', 'patient_name', 'needs_identification',
                'service_presentation', 'clinic_presentation', 'doctor_presentation',
                'appointment', 'price', 'expertise', 'next_step',
                'patient_booking', 'emotional_tone', 'speech', 'initiative',
                'clinic_address', 'passport', 'objection_handling',
                # Критерии вторички (дополнительно)
                'question_clarification',
                # Критерии перезвона и подтверждения (дополнительно)
                'appeal',
                # Критерии "другое"
                'communication', 'problem_solving'
            ]

            # Извлекаем метрики из структуры metrics
            # ВАЖНО: Адаптер для обратной совместимости со старыми данными
            def get_metric_value(metrics_dict, criterion):
                """Получить значение метрики с поддержкой старого формата"""
                if not isinstance(metrics_dict, dict):
                    return None

                # Сначала ищем новый формат
                value = metrics_dict.get(criterion)
                if value is not None:
                    return value

                # Обратная совместимость для clinic_address/passport
                if criterion == 'clinic_address' or criterion == 'passport':
                    # В старых данных было объединенное поле address_passport
                    return metrics_dict.get('address_passport')

                # Обратная совместимость для emotional_tone
                if criterion == 'emotional_tone':
                    # В старых данных было строковое поле tone
                    old_tone = metrics_dict.get('tone')
                    if old_tone:
                        # Конвертируем старую строку в число (примерная оценка)
                        tone_to_score = {'positive': 8, 'neutral': 5, 'negative': 2}
                        return tone_to_score.get(old_tone, 5)

                return None

            for criterion in all_possible_criteria:
                df_copy[criterion] = df_copy['metrics'].apply(
                    lambda x: get_metric_value(x, criterion)
                )

            # Проверяем, какие критерии доступны в данных (имеют не-None значения)
            available_criteria = []
            for criterion in all_possible_criteria:
                # Проверяем, есть ли хотя бы одно ненулевое и не-None значение
                non_null_values = df_copy[criterion].dropna()
                if len(non_null_values) > 0 and non_null_values.sum() > 0:
                    available_criteria.append(criterion)

            # Если нет доступных критериев, возвращаем None
            if not available_criteria:
                logger.warning("Нет доступных критериев с ненулевыми значениями")
                return None

            logger.info(f"Найдено {len(available_criteria)} доступных критериев для графика: {available_criteria}")

            # Создаем DataFrame для хранения средних значений по неделям и критериям
            avg_scores = {}

            # Вычисляем средние значения для каждого критерия по неделям
            # Используем только строки, где критерий не равен None
            for criterion in available_criteria:
                # Группируем по неделям и считаем среднее, игнорируя None значения
                avg_by_week = df_copy[df_copy[criterion].notna()].groupby('week_label')[criterion].mean()
                avg_scores[criterion] = avg_by_week
            
            # Создаем DataFrame из словаря
            scores_df = pd.DataFrame(avg_scores)
            
            # Создаем график
            plt.figure(figsize=(14, 8))
            
            # Получаем недели для оси X
            weeks = scores_df.index.tolist()
            x_positions = range(len(weeks))
            
            # Строим линии для каждого критерия
            for criterion in scores_df.columns:
                # Получаем русское название критерия
                criterion_name = self._get_criterion_display_name(criterion)
                plt.plot(x_positions, scores_df[criterion], marker='o', linewidth=2, label=criterion_name)
            
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
            logger.error(f"Ошибка при создании графика оценок по неделям: {e}")
            return None
            
    def _get_criterion_display_name(self, criterion_key):
        """Вспомогательная функция для получения отображаемых имен критериев"""
        display_names = {
            # Критерии первички (16)
            'greeting': '01. Приветствие',
            'patient_name': '02. Имя пациента',
            'needs_identification': '03. Потребность',
            'service_presentation': '04. Презентация услуги',
            'clinic_presentation': '05. Презентация клиники',
            'doctor_presentation': '06. Презентация врача',
            'appointment': '07. Запись (предложил запись)',
            'price': '08. Цена ОТ',
            'expertise': '09. Экспертность',
            'next_step': '10. Следующий шаг',
            'patient_booking': '11. Запись на прием (записался из AmoCRM)',
            'emotional_tone': '12. Эмоциональный окрас',
            'speech': '13. Речь',
            'initiative': '14. Инициатива',
            'clinic_address': '15. Адрес клиники',
            'passport': '16. Паспорт',
            # Критерии вторички, перезвона и подтверждения
            'question_clarification': 'Уточнение вопроса',
            'appeal': 'Апелляция',
            'objection_handling': 'Отработка возражений',
            'clinic_address': 'Адрес клиники',
            'passport': 'Паспорт',
            # Критерии "другое"
            'communication': 'Коммуникация',
            'problem_solving': 'Решение вопроса'
        }
        return display_names.get(criterion_key, criterion_key)
