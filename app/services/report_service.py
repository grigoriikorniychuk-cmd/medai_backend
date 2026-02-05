import matplotlib

matplotlib.use("Agg")  # Для работы без GUI
import matplotlib.pyplot as plt
import numpy as np
import os
import tempfile
import shutil
from datetime import datetime, timedelta
import logging
from motor.motor_asyncio import AsyncIOMotorClient
from bson.objectid import ObjectId
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image,
)
from reportlab.lib.units import inch, cm

from ..settings.paths import DATA_DIR

# Настройка логирования
logger = logging.getLogger(__name__)

# Константы для подключения к MongoDB
MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "medai"


class ReportService:
    def __init__(self):
        self.mongo_client = AsyncIOMotorClient(MONGO_URI)
        self.db = self.mongo_client[DB_NAME]

        # Создаем временную директорию для файлов
        self.temp_dir = os.path.join(
            DATA_DIR, "reports", "temp", datetime.now().strftime("%Y%m%d_%H%M%S")
        )
        os.makedirs(self.temp_dir, exist_ok=True)

        # Директория для постоянного хранения отчетов
        self.reports_dir = os.path.join(DATA_DIR, "reports")
        os.makedirs(self.reports_dir, exist_ok=True)

    async def get_call_metrics(
        self, start_date, end_date, administrator_ids=None, clinic_id=None
    ):
        """Получает метрики звонков из базы данных"""
        # Преобразуем строковые даты в объекты datetime
        try:
            start = datetime.strptime(start_date, "%d.%m.%Y")
            end = datetime.strptime(end_date, "%d.%m.%Y")
            end = end + timedelta(days=1) - timedelta(seconds=1)  # Конец дня

            # Переводим в строковый формат для запроса в MongoDB
            start_str = start.strftime("%Y-%m-%d")
            end_str = end.strftime("%Y-%m-%d")

            # Фильтр для запроса
            query = {"date": {"$gte": start_str, "$lte": end_str}}

            if administrator_ids:
                query["administrator_id"] = {"$in": administrator_ids}

            if clinic_id:
                query["clinic_id"] = clinic_id

            # Получаем данные из MongoDB
            metrics = await self.db.call_metrics.find(query).to_list(length=None)

            return metrics
        except Exception as e:
            logger.error(f"Ошибка с получении метрик звонков: {e}")
            return []

    async def generate_test_data(
        self,
        num_administrators=3,
        calls_per_admin=10,
        start_date="01.03.2025",
        end_date="26.03.2025",
        administrator_ids=None,
        clinic_id=None,
    ):
        """Генерирует тестовые данные для отчетов"""
        try:
            # Преобразуем строковые даты в объекты datetime
            start = datetime.strptime(start_date, "%d.%m.%Y")
            end = datetime.strptime(end_date, "%d.%m.%Y")
            days = (end - start).days + 1

            # Используем предоставленные ID администраторов или создаем новые
            if administrator_ids:
                admins = [
                    {
                        "id": admin_id,
                        "name": f"Администратор {['Мария', 'Екатерина', 'Маргарита'][i % 3]}",
                    }
                    for i, admin_id in enumerate(administrator_ids)
                ]
                num_administrators = len(administrator_ids)
            else:
                admins = [
                    {
                        "id": f"admin_{i}",
                        "name": f"Администратор {['Мария', 'Екатерина', 'Маргарита'][i % 3]}",
                    }
                    for i in range(num_administrators)
                ]

            # Генерируем данные для каждого администратора
            all_metrics = []

            import random

            for admin in admins:
                for _ in range(calls_per_admin):
                    # Случайная дата в указанном диапазоне
                    random_day = random.randint(0, days - 1)
                    call_date = (start + timedelta(days=random_day)).strftime(
                        "%Y-%m-%d"
                    )

                    # Генерируем случайные метрики
                    greeting = random.randint(5, 10)
                    needs = random.randint(5, 10)
                    solution = random.randint(5, 10)
                    objection = random.randint(4, 10)
                    closing = random.randint(5, 10)
                    overall = (greeting + needs + solution + objection + closing) / 5

                    # Тональность и удовлетворенность
                    tone_options = ["positive", "neutral", "negative"]
                    tone_weights = [0.7, 0.2, 0.1]  # Больше положительных оценок
                    tone = random.choices(tone_options, weights=tone_weights)[0]

                    satisfaction_options = ["high", "medium", "low"]
                    satisfaction_weights = [0.6, 0.3, 0.1]  # Больше высоких оценок
                    satisfaction = random.choices(
                        satisfaction_options, weights=satisfaction_weights
                    )[0]

                    # Тип звонка
                    call_type = random.randint(1, 8)

                    # Создаем запись
                    metric = {
                        "administrator_id": admin["id"],
                        "administrator_name": admin["name"],
                        "date": call_date,
                        "call_id": f"call_{len(all_metrics) + 1}",
                        "clinic_id": clinic_id
                        or "818579a1-fc67-4a0f-a543-56f6eb828606",
                        "metrics": {
                            "greeting": greeting,
                            "needs_identification": needs,
                            "solution_proposal": solution,
                            "objection_handling": objection,
                            "call_closing": closing,
                            "tone": tone,
                            "customer_satisfaction": satisfaction,
                            "overall_score": overall,
                        },
                        "comments": "Тестовые данные",
                        "recommendations": [
                            "Улучшить презентацию услуг",
                            "Активнее выявлять потребности клиента",
                        ],
                        "call_classification": call_type,
                        "created_at": datetime.now().isoformat(),
                    }

                    all_metrics.append(metric)

            # Сохраняем все метрики в базу данных
            if all_metrics:
                # Если указаны конкретные администраторы, удаляем только их данные
                if administrator_ids:
                    await self.db.call_metrics.delete_many(
                        {"administrator_id": {"$in": administrator_ids}}
                    )
                else:
                    await self.db.call_metrics.delete_many({})  # Удаляем все записи

                await self.db.call_metrics.insert_many(all_metrics)

            return {
                "success": True,
                "message": f"Создано {len(all_metrics)} тестовых записей оценок звонков",
                "data": {
                    "administrators": [admin["name"] for admin in admins],
                    "total_calls": len(all_metrics),
                    "date_range": f"{start_date} - {end_date}",
                },
            }
        except Exception as e:
            logger.error(f"Ошибка с генерации тестовых данных: {e}")
            return {
                "success": False,
                "message": f"Ошибка с генерации тестовых данных: {e}",
                "data": None,
            }

    def group_metrics_by_administrator(self, metrics_data):
        """Группирует метрики по администраторам"""
        admins = {}

        for metric in metrics_data:
            admin_id = metric["administrator_id"]
            admin_name = metric["administrator_name"]

            if admin_id not in admins:
                admins[admin_id] = {
                    "name": admin_name,
                    "metrics": [],
                    "average_scores": {
                        "greeting": 0,
                        "needs_identification": 0,
                        "solution_proposal": 0,
                        "objection_handling": 0,
                        "call_closing": 0,
                        "overall_score": 0,
                    },
                    "tone_stats": {"positive": 0, "neutral": 0, "negative": 0},
                    "satisfaction_stats": {"high": 0, "medium": 0, "low": 0},
                    "call_types": {i: 0 for i in range(1, 9)},
                }

            admins[admin_id]["metrics"].append(metric)

        # Рассчитываем средние значения для каждого администратора
        for admin_id, admin_data in admins.items():
            metrics_list = admin_data["metrics"]
            count = len(metrics_list)

            if count > 0:
                # Рассчитываем средние оценки
                for metric_key in admin_data["average_scores"].keys():
                    admin_data["average_scores"][metric_key] = (
                        sum(m["metrics"].get(metric_key, 0) for m in metrics_list)
                        / count
                    )

                # Считаем статистику по тональности
                for m in metrics_list:
                    tone = m["metrics"].get("tone", "neutral")
                    admin_data["tone_stats"][tone] += 1

                    satisfaction = m["metrics"].get("customer_satisfaction", "medium")
                    admin_data["satisfaction_stats"][satisfaction] += 1

                    call_type = m.get("call_classification", 8)
                    admin_data["call_types"][call_type] += 1

        return admins

    def generate_charts(self, metrics_data):
        """Генерирует графики на основе метрик звонков"""
        # Группируем данные по администраторам
        grouped_data = self.group_metrics_by_administrator(metrics_data)

        chart_paths = []

        # 1. Создаем график сравнения средних оценок администраторов
        chart_path = self._create_admin_comparison_chart(grouped_data)
        chart_paths.append(chart_path)

        # 2. Создаем график тональности звонков
        chart_path = self._create_tone_chart(grouped_data)
        chart_paths.append(chart_path)

        # 3. Создаем график удовлетворенности клиентов
        chart_path = self._create_satisfaction_chart(grouped_data)
        chart_paths.append(chart_path)

        # 4. Создаем график типов звонков
        chart_path = self._create_call_types_chart(grouped_data)
        chart_paths.append(chart_path)

        # 5. Для каждого администратора создаем индивидуальный график метрик
        for admin_id, admin_data in grouped_data.items():
            chart_path = self._create_admin_metrics_chart(admin_id, admin_data)
            chart_paths.append(chart_path)

        return chart_paths, grouped_data

    def _create_admin_comparison_chart(self, grouped_data):
        """Создает график сравнения администраторов"""
        # Настраиваем фигуру
        plt.figure(figsize=(10, 6))

        admin_names = []
        overall_scores = []

        for admin_id, admin_data in grouped_data.items():
            admin_names.append(admin_data["name"])
            overall_scores.append(admin_data["average_scores"]["overall_score"])

        # Создаем столбчатую диаграмму
        bars = plt.bar(admin_names, overall_scores, color="skyblue")
        plt.axhline(y=7, color="r", linestyle="-", alpha=0.3)  # Линия целевого значения

        # Добавляем значения над столбцами
        for bar in bars:
            height = bar.get_height()
            plt.text(
                bar.get_x() + bar.get_width() / 2.0,
                height + 0.1,
                f"{height:.1f}",
                ha="center",
                va="bottom",
            )

        plt.title("Сравнение общих оценок администраторов")
        plt.xlabel("Администратор")
        plt.ylabel("Средняя общая оценка (0-10)")
        plt.ylim(0, 10)
        plt.tight_layout()

        # Сохраняем график
        chart_path = os.path.join(self.temp_dir, "admin_comparison.png")
        plt.savefig(chart_path, dpi=150)
        plt.close()

        return chart_path

    def _create_tone_chart(self, grouped_data):
        """Создает график тональности звонков"""
        plt.figure(figsize=(10, 6))

        admin_names = []
        positive_pcts = []
        neutral_pcts = []
        negative_pcts = []

        for admin_id, admin_data in grouped_data.items():
            admin_names.append(admin_data["name"])

            total = sum(admin_data["tone_stats"].values())
            if total > 0:
                positive_pcts.append(admin_data["tone_stats"]["positive"] / total * 100)
                neutral_pcts.append(admin_data["tone_stats"]["neutral"] / total * 100)
                negative_pcts.append(admin_data["tone_stats"]["negative"] / total * 100)
            else:
                positive_pcts.append(0)
                neutral_pcts.append(0)
                negative_pcts.append(0)

        # Создаем столбчатую диаграмму
        x = np.arange(len(admin_names))
        width = 0.25

        plt.bar(x - width, positive_pcts, width, label="Позитивная", color="green")
        plt.bar(x, neutral_pcts, width, label="Нейтральная", color="gray")
        plt.bar(x + width, negative_pcts, width, label="Негативная", color="red")

        plt.title("Распределение тональности звонков по администраторам")
        plt.xlabel("Администратор")
        plt.ylabel("Процент звонков")
        plt.xticks(x, admin_names)
        plt.legend()
        plt.tight_layout()

        # Сохраняем график
        chart_path = os.path.join(self.temp_dir, "tone_chart.png")
        plt.savefig(chart_path, dpi=150)
        plt.close()

        return chart_path

    def _create_satisfaction_chart(self, grouped_data):
        """Создает график удовлетворенности клиентов"""
        plt.figure(figsize=(10, 6))

        admin_names = []
        high_pcts = []
        medium_pcts = []
        low_pcts = []

        for admin_id, admin_data in grouped_data.items():
            admin_names.append(admin_data["name"])

            total = sum(admin_data["satisfaction_stats"].values())
            if total > 0:
                high_pcts.append(admin_data["satisfaction_stats"]["high"] / total * 100)
                medium_pcts.append(
                    admin_data["satisfaction_stats"]["medium"] / total * 100
                )
                low_pcts.append(admin_data["satisfaction_stats"]["low"] / total * 100)
            else:
                high_pcts.append(0)
                medium_pcts.append(0)
                low_pcts.append(0)

        # Создаем столбчатую диаграмму
        x = np.arange(len(admin_names))
        width = 0.25

        plt.bar(x - width, high_pcts, width, label="Высокая", color="green")
        plt.bar(x, medium_pcts, width, label="Средняя", color="yellow")
        plt.bar(x + width, low_pcts, width, label="Низкая", color="red")

        plt.title("Удовлетворенность клиентов по администраторам")
        plt.xlabel("Администратор")
        plt.ylabel("Процент звонков")
        plt.xticks(x, admin_names)
        plt.legend()
        plt.tight_layout()

        # Сохраняем график
        chart_path = os.path.join(self.temp_dir, "satisfaction_chart.png")
        plt.savefig(chart_path, dpi=150)
        plt.close()

        return chart_path

    def _create_call_types_chart(self, grouped_data):
        """Создает график типов звонков"""
        # Объединяем данные по типам звонков от всех администраторов
        call_types = {i: 0 for i in range(1, 9)}

        for admin_id, admin_data in grouped_data.items():
            for call_type, count in admin_data["call_types"].items():
                call_types[call_type] += count

        # Названия типов звонков
        type_names = {
            1: "Первичное обращение",
            2: "Запись на приём",
            3: "Запрос информации",
            4: "Проблема/жалоба",
            5: "Изменение/отмена",
            6: "Повторная консультация",
            7: "Запрос результатов",
            8: "Другое",
        }

        # Создаем круговую диаграмму
        plt.figure(figsize=(10, 7))

        # Фильтруем только типы с ненулевым количеством
        labels = [type_names[t] for t in call_types.keys() if call_types[t] > 0]
        sizes = [count for count in call_types.values() if count > 0]

        plt.pie(sizes, labels=labels, autopct="%1.1f%%", startangle=90)
        plt.axis("equal")  # Круговая диаграмма выглядит лучше если оси равны
        plt.title("Распределение типов звонков")
        plt.tight_layout()

        # Сохраняем график
        chart_path = os.path.join(self.temp_dir, "call_types_chart.png")
        plt.savefig(chart_path, dpi=150)
        plt.close()

        return chart_path

    def _create_admin_metrics_chart(self, admin_id, admin_data):
        """Создает график метрик для конкретного администратора"""
        # Создаем радарный график для метрик
        categories = [
            "Приветствие",
            "Выявление потребностей",
            "Предложение решения",
            "Работа с возражениями",
            "Завершение разговора",
        ]

        values = [
            admin_data["average_scores"]["greeting"],
            admin_data["average_scores"]["needs_identification"],
            admin_data["average_scores"]["solution_proposal"],
            admin_data["average_scores"]["objection_handling"],
            admin_data["average_scores"]["call_closing"],
        ]

        # Замыкаем круг, добавляя первую точку в конец
        values += values[:1]
        categories += categories[:1]

        # Углы для каждой категории на радарном графике
        angles = np.linspace(0, 2 * np.pi, len(categories) - 1, endpoint=False)
        angles = np.concatenate((angles, [angles[0]]))

        # Создаем радарный график
        fig = plt.figure(figsize=(8, 8))
        ax = fig.add_subplot(111, polar=True)

        # Рисуем график
        ax.fill(angles, values, color="skyblue", alpha=0.25)
        ax.plot(angles, values, color="blue", linewidth=2)

        # Добавляем категории
        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(categories[:-1])

        # Настройка графика
        ax.set_yticklabels([])
        ax.set_ylim(0, 10)

        # Добавляем концентрические круги и числовые метки
        for i in range(1, 11):
            ax.text(np.pi / 2, i, str(i), ha="center", va="bottom", color="gray")

        plt.title(f'Метрики администратора {admin_data["name"]}')
        plt.tight_layout()

        # Сохраняем график
        chart_path = os.path.join(self.temp_dir, f"admin_{admin_id}_metrics.png")
        plt.savefig(chart_path, dpi=150)
        plt.close()

        return chart_path

    def generate_pdf_report(
        self, metrics_data, charts, grouped_data, report_type="full"
    ):
        """Генерирует PDF-отчет с использованием ReportLab"""
        try:
            # Путь для сохранения PDF-отчета
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            pdf_filename = f"call_analysis_report_{timestamp}.pdf"
            pdf_path = os.path.join(self.reports_dir, pdf_filename)

            # Настройка шрифтов для поддержки кириллицы
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont

            # Директория со шрифтами и ресурсами
            font_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts"
            )
            resources_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources"
            )
            os.makedirs(font_dir, exist_ok=True)
            os.makedirs(resources_dir, exist_ok=True)

            # Путь к логотипу
            logo_path = os.path.join(resources_dir, "logo.png")

            # Пути к TTF шрифтам с поддержкой кириллицы
            dejavu_sans_path = os.path.join(font_dir, "DejaVuSans.ttf")
            dejavu_sans_bold_path = os.path.join(font_dir, "DejaVuSans-Bold.ttf")

            # Автоматическая загрузка шрифтов, если они отсутствуют
            if not os.path.exists(dejavu_sans_path) or not os.path.exists(
                dejavu_sans_bold_path
            ):
                logger.info(
                    "Шрифты DejaVu Sans не найдены, использую стандартные шрифты"
                )
                # Используем стандартные шрифты ReportLab с ограниченной поддержкой кириллицы
                font_normal = "Helvetica"
                font_bold = "Helvetica-Bold"
            else:
                # Регистрация шрифтов DejaVu Sans
                pdfmetrics.registerFont(TTFont("DejaVuSans", dejavu_sans_path))
                pdfmetrics.registerFont(
                    TTFont("DejaVuSans-Bold", dejavu_sans_bold_path)
                )
                pdfmetrics.registerFontFamily(
                    "DejaVuSans", normal="DejaVuSans", bold="DejaVuSans-Bold"
                )
                font_normal = "DejaVuSans"
                font_bold = "DejaVuSans-Bold"
                logger.info("Шрифты DejaVu Sans успешно зарегистрированы")

            # Создаем документ
            doc = SimpleDocTemplate(
                pdf_path,
                pagesize=A4,
                rightMargin=2 * cm,
                leftMargin=2 * cm,
                topMargin=2 * cm,
                bottomMargin=2 * cm,
            )

            # Список элементов документа
            elements = []

            # Создаем кастомные стили с поддержкой кириллицы
            styles = getSampleStyleSheet()

            title_style = ParagraphStyle(
                "CustomTitle",
                parent=styles["Title"],
                fontName=font_bold,
                fontSize=20,
                alignment=1,  # По центру
                spaceAfter=0.5 * cm,
            )

            subtitle_style = ParagraphStyle(
                "CustomSubtitle",
                parent=styles["Title"],
                fontName=font_bold,
                fontSize=16,
                alignment=1,  # По центру
                spaceAfter=1 * cm,
            )

            heading_style = ParagraphStyle(
                "CustomHeading1",
                parent=styles["Heading1"],
                fontName=font_bold,
                fontSize=16,
            )

            subheading_style = ParagraphStyle(
                "CustomHeading2",
                parent=styles["Heading2"],
                fontName=font_bold,
                fontSize=14,
            )

            normal_style = ParagraphStyle(
                "CustomNormal",
                parent=styles["Normal"],
                fontName=font_normal,
                fontSize=12,
            )

            # Создаем заголовок отчета
            start_date = metrics_data[0]["date"] if metrics_data else "N/A"
            end_date = metrics_data[-1]["date"] if metrics_data else "N/A"

            # Добавляем логотип
            if os.path.exists(logo_path):
                logo = Image(logo_path, width=5 * cm, height=5 * cm)
                elements.append(logo)
                elements.append(Spacer(1, 0.5 * cm))

            # Создаем заголовок с указанием дат
            elements.append(Paragraph("ОТЧЕТ", title_style))
            elements.append(Paragraph(f"по оценке качества звонков", subtitle_style))
            elements.append(
                Paragraph(f"за период {start_date} — {end_date}", subtitle_style)
            )
            elements.append(Spacer(1, 0.5 * cm))

            elements.append(
                Paragraph(
                    f"Количество оцененных звонков: {len(metrics_data)}", normal_style
                )
            )
            elements.append(Spacer(1, 1 * cm))

            # Добавляем общую информацию
            elements.append(Paragraph("Общая информация", heading_style))
            elements.append(Spacer(1, 0.5 * cm))

            # Таблица с общей информацией (убираем слово "Администратор" из таблицы)
            data = [
                ["Имя", "Кол-во звонков", "Ср. оценка", "Поз. звонки", "Высокая удовл."]
            ]

            for admin_id, admin_data in grouped_data.items():
                call_count = len(admin_data["metrics"])
                avg_score = round(admin_data["average_scores"]["overall_score"], 1)

                total_calls = sum(admin_data["tone_stats"].values())
                positive_pct = (
                    f"{admin_data['tone_stats']['positive'] / total_calls * 100:.1f}%"
                    if total_calls > 0
                    else "0%"
                )

                total_satisfaction = sum(admin_data["satisfaction_stats"].values())
                high_satisfaction_pct = (
                    f"{admin_data['satisfaction_stats']['high'] / total_satisfaction * 100:.1f}%"
                    if total_satisfaction > 0
                    else "0%"
                )

                # Сокращаем "Администратор" из имени, если оно там есть
                name = admin_data["name"].replace("Администратор ", "")

                data.append(
                    [
                        name,
                        str(call_count),
                        str(avg_score),
                        positive_pct,
                        high_satisfaction_pct,
                    ]
                )

            # Настройка ширины столбцов для таблицы
            col_widths = [3 * cm, 3 * cm, 3 * cm, 3 * cm, 4 * cm]
            table = Table(data, colWidths=col_widths)

            # Стиль таблицы (уменьшаем шрифт в заголовках)
            table_style = TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                    ("FONTNAME", (0, 0), (-1, 0), font_bold),
                    ("FONTSIZE", (0, 0), (-1, 0), 10),  # Уменьшен шрифт заголовков
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 10),
                    ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
                    ("TEXTCOLOR", (0, 1), (-1, -1), colors.black),
                    ("ALIGN", (0, 1), (-1, -1), "CENTER"),
                    ("FONTNAME", (0, 1), (-1, -1), font_normal),
                    ("GRID", (0, 0), (-1, -1), 1, colors.black),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )

            table.setStyle(table_style)
            elements.append(table)
            elements.append(Spacer(1, 1 * cm))

            # Добавляем графики
            elements.append(Paragraph("Сравнительный анализ", heading_style))
            elements.append(Spacer(1, 0.5 * cm))

            for i, chart_path in enumerate(charts):
                if os.path.exists(chart_path) and "admin_" not in chart_path:
                    img = Image(chart_path, width=16 * cm, height=10 * cm)
                    elements.append(img)
                    elements.append(Spacer(1, 1 * cm))

            # Если отчет полный или индивидуальный, добавляем детальную информацию по каждому администратору
            if report_type in ["full", "individual"]:
                elements.append(Paragraph("Детальный анализ", heading_style))
                elements.append(Spacer(1, 0.5 * cm))

                for admin_id, admin_data in grouped_data.items():
                    # Убираем "Администратор" из имени
                    name = admin_data["name"].replace("Администратор ", "")
                    elements.append(Paragraph(f"{name}", subheading_style))
                    elements.append(Spacer(1, 0.3 * cm))

                    # Таблица с детальными метриками
                    detail_data = [
                        ["Метрика", "Средняя оценка"],
                        [
                            "Приветствие",
                            f"{admin_data['average_scores']['greeting']:.1f}",
                        ],
                        [
                            "Выявление потребностей",
                            f"{admin_data['average_scores']['needs_identification']:.1f}",
                        ],
                        [
                            "Предложение решения",
                            f"{admin_data['average_scores']['solution_proposal']:.1f}",
                        ],
                        [
                            "Работа с возражениями",
                            f"{admin_data['average_scores']['objection_handling']:.1f}",
                        ],
                        [
                            "Завершение разговора",
                            f"{admin_data['average_scores']['call_closing']:.1f}",
                        ],
                        [
                            "Общая оценка",
                            f"{admin_data['average_scores']['overall_score']:.1f}",
                        ],
                    ]

                    detail_table = Table(detail_data, colWidths=[8 * cm, 5 * cm])

                    detail_table_style = TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                            ("FONTNAME", (0, 0), (-1, 0), font_bold),
                            (
                                "FONTSIZE",
                                (0, 0),
                                (-1, 0),
                                10,
                            ),  # Уменьшаем шрифт заголовков
                            ("BOTTOMPADDING", (0, 0), (-1, 0), 10),
                            ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
                            ("TEXTCOLOR", (0, 1), (-1, -1), colors.black),
                            ("ALIGN", (0, 1), (-1, -1), "LEFT"),
                            ("ALIGN", (1, 1), (1, -1), "CENTER"),
                            ("FONTNAME", (0, 1), (-1, -1), font_normal),
                            ("GRID", (0, 0), (-1, -1), 1, colors.black),
                            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ]
                    )

                    detail_table.setStyle(detail_table_style)
                    elements.append(detail_table)
                    elements.append(Spacer(1, 0.5 * cm))

                    # Добавляем индивидуальный график метрик администратора
                    admin_chart_path = os.path.join(
                        self.temp_dir, f"admin_{admin_id}_metrics.png"
                    )
                    if os.path.exists(admin_chart_path):
                        img = Image(admin_chart_path, width=12 * cm, height=12 * cm)
                        elements.append(img)
                        elements.append(Spacer(1, 1 * cm))

            # Строим PDF-документ
            doc.build(elements)

            return pdf_path

        except Exception as e:
            logger.error(f"Ошибка с генерации PDF-отчета: {e}")
            import traceback

            logger.error(f"Стек-трейс: {traceback.format_exc()}")
            raise

    def cleanup(self):
        """Удаляет временные файлы"""
        try:
            if os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
                logger.info(f"Временная директория удалена: {self.temp_dir}")
        except Exception as e:
            logger.error(f"Ошибка с удалении временной директории: {e}")
