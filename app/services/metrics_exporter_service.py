"""
Сервис для экспорта пользовательских метрик из MongoDB в Prometheus.
Собирает данные из коллекций MongoDB и предоставляет их в формате метрик Prometheus.
"""
import time
import asyncio
import sys
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

# Обработка импорта prometheus_client с защитой от ошибок
try:
    import prometheus_client
    from prometheus_client import start_http_server, Gauge, Counter, Summary
    PROMETHEUS_AVAILABLE = True
except ImportError as e:
    print(f"ВНИМАНИЕ: Не удалось импортировать модуль prometheus_client: {e}")
    print(f"Пути Python: {sys.path}")
    PROMETHEUS_AVAILABLE = False
    # Создаем заглушки для классов Prometheus
    class DummyMetric:
        def __init__(self, *args, **kwargs):
            self._metrics = {}
            self._value = self
        def labels(self, **kwargs):
            return self
        def set(self, value):
            pass
        def observe(self, value):
            pass
        def inc(self, value=1):
            pass
        def clear(self):
            pass
    
    Gauge = Counter = Summary = DummyMetric
    def start_http_server(port):
        print(f"Заглушка: HTTP-сервер Prometheus на порту {port} не запущен")

from app.services.mongodb_service import MongoDBService
from app.utils.logging import ContextLogger

logger = ContextLogger("metrics_exporter")

class MetricsExporterService:
    """
    Сервис для экспорта пользовательских метрик из MongoDB в Prometheus.
    Собирает данные из коллекций MongoDB и экспортирует их как метрики Prometheus.
    """
    
    def __init__(self, mongodb_service: MongoDBService, port: int = 9215):
        """
        Инициализирует сервис экспорта метрик.
        
        Args:
            mongodb_service: Сервис MongoDB для доступа к базе данных
            port: Порт, на котором будет запущен HTTP-сервер Prometheus
        """
        self.mongodb_service = mongodb_service
        self.port = port
        
        if not PROMETHEUS_AVAILABLE:
            logger.warning("Prometheus client не доступен. Метрики не будут собираться.")
            return
        
        # Метрики для оценки менеджеров
        self.manager_score_gauge = Gauge(
            'manager_overall_score', 
            'Средняя оценка менеджера', 
            ['clinic_id', 'manager_id', 'manager_name']
        )
        
        # Метрики для анализа звонков
        self.calls_total_counter = Counter(
            'calls_total', 
            'Общее количество проанализированных звонков', 
            ['clinic_id', 'direction', 'category']
        )
        
        # Коэффициент конверсии
        self.conversion_rate_gauge = Gauge(
            'call_conversion_rate', 
            'Коэффициент конверсии звонков', 
            ['clinic_id']
        )
        
        # Продолжительность звонков
        self.call_duration_summary = Summary(
            'call_duration_seconds', 
            'Продолжительность звонков в секундах', 
            ['clinic_id', 'direction']
        )
        
        # Детальные метрики для воронки конверсии
        self.conversion_funnel_gauge = Gauge(
            'conversion_funnel',
            'Количество звонков на разных этапах воронки конверсии',
            ['clinic_id', 'stage', 'direction']
        )
        
        # Метрики по источникам трафика
        self.traffic_source_counter = Counter(
            'traffic_source_calls',
            'Количество звонков по источникам трафика',
            ['clinic_id', 'source', 'converted']
        )
        
        # Метрики по дням недели и времени
        self.calls_by_day_counter = Counter(
            'calls_by_day',
            'Количество звонков по дням недели',
            ['clinic_id', 'day_of_week', 'direction']
        )
        
        # Метрики по категориям и тегам
        self.call_categories_counter = Counter(
            'call_categories',
            'Количество звонков по категориям и тегам',
            ['clinic_id', 'category_name', 'tag']
        )
        
        # Метрики по оценкам качества обслуживания
        self.quality_metrics_gauge = Gauge(
            'quality_metrics',
            'Показатели качества обслуживания',
            ['clinic_id', 'metric_name', 'manager_id']
        )
        
        # Метрики по клиникам (для справочника)
        self.clinic_info_gauge = Gauge(
            'clinic_info',
            'Информация о клиниках',
            ['clinic_id', 'clinic_name', 'region']
        )
        
        logger.info(f"Метрики будут доступны на порту {port}")
    
    def start_server(self):
        """Запускает HTTP-сервер для предоставления метрик."""
        if not PROMETHEUS_AVAILABLE:
            logger.warning("Prometheus client не доступен. HTTP-сервер не будет запущен.")
            return
            
        start_http_server(self.port)
        logger.info(f"HTTP-сервер Prometheus запущен на порту {self.port}")
    
    async def collect_metrics_job(self, interval_seconds: int = 60):
        """
        Запускает периодический сбор метрик.
        
        Args:
            interval_seconds: Интервал между сборами метрик в секундах
        """
        if not PROMETHEUS_AVAILABLE:
            logger.warning("Prometheus client не доступен. Метрики не будут собираться.")
            return
            
        logger.info(f"Запущен процесс сбора метрик с интервалом {interval_seconds} сек")
        while True:
            try:
                await self.collect_metrics()
                logger.info("Метрики успешно собраны")
            except Exception as e:
                logger.error(f"Ошибка при сборе метрик: {str(e)}")
            
            await asyncio.sleep(interval_seconds)
    
    async def collect_metrics(self):
        """Собирает метрики из MongoDB."""
        if not PROMETHEUS_AVAILABLE:
            return
        
        # Получаем данные из коллекции call_analytics
        try:
            await self._collect_manager_score_metrics()
            await self._collect_call_category_metrics()
            await self._collect_conversion_metrics()
            await self._collect_call_duration_metrics()
            
            # Собираем дополнительные метрики для богатого дашборда
            await self._collect_conversion_funnel_metrics()
            await self._collect_traffic_source_metrics()
            await self._collect_calls_by_day_metrics()
            await self._collect_call_categories_metrics()
            await self._collect_quality_metrics()
            await self._collect_clinic_info_metrics()
            
        except AttributeError as e:
            logger.error(f"Ошибка в методах MongoDB: {e}")
            logger.error("Проверьте, что в сервисе MongoDB реализованы необходимые методы")
        except Exception as e:
            logger.error(f"Ошибка при сборе метрик: {e}")
    
    async def _collect_manager_score_metrics(self):
        """Собирает метрики оценок менеджеров."""
        try:
            # Альтернативный способ получения данных, если метод aggregate отсутствует
            if not hasattr(self.mongodb_service, 'aggregate'):
                logger.warning("Метод aggregate не найден в MongoDBService. Используем альтернативный метод.")
                
                # Если вместо aggregate используется find_many
                documents = await self.mongodb_service.find_many(
                    "call_analytics", 
                    {}, 
                    limit=1000
                )
                
                # Ручная агрегация
                manager_scores = {}
                for doc in documents:
                    clinic_id = doc.get("clinic_id", "unknown")
                    manager_id = doc.get("administrator_id", "unknown")
                    manager_name = doc.get("administrator_name", "Неизвестный")
                    score = doc.get("metrics", {}).get("overall_score", 0)
                    
                    key = (clinic_id, manager_id, manager_name)
                    if key not in manager_scores:
                        manager_scores[key] = {"total": 0, "count": 0}
                    
                    manager_scores[key]["total"] += score
                    manager_scores[key]["count"] += 1
                
                # Устанавливаем метрики
                for (clinic_id, manager_id, manager_name), data in manager_scores.items():
                    avg_score = data["total"] / max(data["count"], 1)
                    self.manager_score_gauge.labels(
                        clinic_id=clinic_id,
                        manager_id=manager_id,
                        manager_name=manager_name
                    ).set(avg_score)
                
                return
            
            # Агрегационный запрос для получения средней оценки по менеджерам
            pipeline = [
                {
                    "$group": {
                        "_id": {
                            "clinic_id": "$clinic_id",
                            "administrator_id": "$administrator_id",
                            "administrator_name": "$administrator_name"
                        },
                        "avg_score": {"$avg": "$metrics.overall_score"}
                    }
                }
            ]
            
            results = await self.mongodb_service.aggregate("call_analytics", pipeline)
            
            # Обновляем метрики
            for result in results:
                clinic_id = result["_id"]["clinic_id"]
                manager_id = result["_id"]["administrator_id"]
                manager_name = result["_id"]["administrator_name"]
                avg_score = result["avg_score"]
                
                self.manager_score_gauge.labels(
                    clinic_id=clinic_id,
                    manager_id=manager_id,
                    manager_name=manager_name
                ).set(avg_score)
        except Exception as e:
            logger.error(f"Ошибка при сборе метрик оценок менеджеров: {e}")
    
    async def _collect_call_category_metrics(self):
        """Собирает метрики по категориям звонков."""
        try:
            # Альтернативный способ, если метод aggregate отсутствует
            if not hasattr(self.mongodb_service, 'aggregate'):
                logger.warning("Метод aggregate не найден в MongoDBService. Используем альтернативный метод.")
                
                documents = await self.mongodb_service.find_many(
                    "call_analytics", 
                    {}, 
                    limit=1000
                )
                
                # Ручная агрегация
                call_counts = {}
                for doc in documents:
                    clinic_id = doc.get("clinic_id", "unknown")
                    direction = doc.get("call_type", {}).get("direction", "unknown")
                    category = doc.get("call_type", {}).get("category", "unknown")
                    
                    key = (clinic_id, direction, category)
                    call_counts[key] = call_counts.get(key, 0) + 1
                
                # Сбрасываем предыдущие значения
                try:
                    self.calls_total_counter._metrics.clear()
                except:
                    pass
                
                # Устанавливаем метрики
                for (clinic_id, direction, category), count in call_counts.items():
                    try:
                        self.calls_total_counter.labels(
                            clinic_id=clinic_id,
                            direction=direction,
                            category=category
                        )._value.set(count)
                    except:
                        pass
                
                return
            
            # Агрегационный запрос для подсчета звонков по категориям
            pipeline = [
                {
                    "$group": {
                        "_id": {
                            "clinic_id": "$clinic_id",
                            "direction": "$call_type.direction",
                            "category": "$call_type.category"
                        },
                        "count": {"$sum": 1}
                    }
                }
            ]
            
            results = await self.mongodb_service.aggregate("call_analytics", pipeline)
            
            # Сбрасываем предыдущие значения
            try:
                self.calls_total_counter._metrics.clear()
            except:
                pass
            
            # Обновляем метрики
            for result in results:
                clinic_id = result["_id"]["clinic_id"]
                direction = result["_id"]["direction"]
                category = result["_id"]["category"]
                count = result["count"]
                
                # Добавляем значение к счетчику
                try:
                    self.calls_total_counter.labels(
                        clinic_id=clinic_id,
                        direction=direction,
                        category=category
                    )._value.set(count)
                except:
                    pass
        except Exception as e:
            logger.error(f"Ошибка при сборе метрик по категориям звонков: {e}")
    
    async def _collect_conversion_metrics(self):
        """Собирает метрики по конверсии звонков."""
        try:
            # Получаем данные за последние 30 дней
            thirty_days_ago = datetime.now() - timedelta(days=30)
            
            # Альтернативный способ, если метод aggregate отсутствует
            if not hasattr(self.mongodb_service, 'aggregate'):
                logger.warning("Метод aggregate не найден в MongoDBService. Используем альтернативный метод.")
                
                documents = await self.mongodb_service.find_many(
                    "call_analytics", 
                    {"timestamp": {"$gte": thirty_days_ago}, "call_type.direction": "incoming"}, 
                    limit=1000
                )
                
                # Ручная агрегация
                conversion_stats = {}
                for doc in documents:
                    clinic_id = doc.get("clinic_id", "unknown")
                    conversion = doc.get("conversion", False)
                    
                    if clinic_id not in conversion_stats:
                        conversion_stats[clinic_id] = {"total": 0, "converted": 0}
                    
                    conversion_stats[clinic_id]["total"] += 1
                    if conversion:
                        conversion_stats[clinic_id]["converted"] += 1
                
                # Устанавливаем метрики
                for clinic_id, stats in conversion_stats.items():
                    conversion_rate = stats["converted"] / max(stats["total"], 1)
                    self.conversion_rate_gauge.labels(clinic_id=clinic_id).set(conversion_rate)
                
                return
            
            # Агрегационный запрос для расчета конверсии по клиникам
            pipeline = [
                {
                    "$match": {
                        "timestamp": {"$gte": thirty_days_ago},
                        "call_type.direction": "incoming"  # Только входящие звонки
                    }
                },
                {
                    "$group": {
                        "_id": {"clinic_id": "$clinic_id"},
                        "total_calls": {"$sum": 1},
                        "converted_calls": {
                            "$sum": {"$cond": [{"$eq": ["$conversion", True]}, 1, 0]}
                        }
                    }
                },
                {
                    "$project": {
                        "clinic_id": "$_id.clinic_id",
                        "conversion_rate": {
                            "$cond": [
                                {"$eq": ["$total_calls", 0]},
                                0,
                                {"$divide": ["$converted_calls", "$total_calls"]}
                            ]
                        }
                    }
                }
            ]
            
            results = await self.mongodb_service.aggregate("call_analytics", pipeline)
            
            # Обновляем метрики
            for result in results:
                clinic_id = result["clinic_id"]
                conversion_rate = result["conversion_rate"]
                
                self.conversion_rate_gauge.labels(clinic_id=clinic_id).set(conversion_rate)
        except Exception as e:
            logger.error(f"Ошибка при сборе метрик по конверсии звонков: {e}")
    
    async def _collect_call_duration_metrics(self):
        """Собирает метрики по продолжительности звонков."""
        try:
            # Получаем данные за последние 30 дней
            thirty_days_ago = datetime.now() - timedelta(days=30)
            
            # Получаем записи с известной продолжительностью
            query = {
                "timestamp": {"$gte": thirty_days_ago},
                "call_type.duration": {"$exists": True, "$ne": None}
            }
            
            docs = await self.mongodb_service.find_many("call_analytics", query, limit=1000)
            
            # Сбрасываем предыдущие метрики
            try:
                self.call_duration_summary._metrics.clear()
            except:
                pass
            
            # Обновляем метрики
            for doc in docs:
                clinic_id = doc.get("clinic_id", "unknown")
                direction = doc.get("call_type", {}).get("direction", "unknown")
                duration = doc.get("call_type", {}).get("duration", 0)
                
                # Пропускаем некорректные данные
                if duration <= 0:
                    continue
                    
                # Обновляем метрику
                try:
                    self.call_duration_summary.labels(
                        clinic_id=clinic_id,
                        direction=direction
                    ).observe(duration)
                except:
                    pass
        except Exception as e:
            logger.error(f"Ошибка при сборе метрик по продолжительности звонков: {e}")
    
    async def _collect_conversion_funnel_metrics(self):
        """Собирает метрики для воронки конверсии."""
        try:
            # Получаем данные за последние 30 дней
            thirty_days_ago = datetime.now() - timedelta(days=30)
            
            # Определяем стадии воронки
            stages = ["total", "qualified", "converted"]
            
            # Если метод aggregate недоступен, используем альтернативный подход
            if not hasattr(self.mongodb_service, 'aggregate'):
                documents = await self.mongodb_service.find_many(
                    "call_analytics", 
                    {"timestamp": {"$gte": thirty_days_ago}}, 
                    limit=1000
                )
                
                # Ручная агрегация
                funnel_data = {}
                for doc in documents:
                    clinic_id = doc.get("clinic_id", "unknown")
                    direction = doc.get("call_type", {}).get("direction", "unknown")
                    is_qualified = doc.get("metrics", {}).get("overall_score", 0) >= 3
                    is_converted = doc.get("conversion", False)
                    
                    key = (clinic_id, direction)
                    if key not in funnel_data:
                        funnel_data[key] = {"total": 0, "qualified": 0, "converted": 0}
                    
                    funnel_data[key]["total"] += 1
                    if is_qualified:
                        funnel_data[key]["qualified"] += 1
                    if is_converted:
                        funnel_data[key]["converted"] += 1
                
                # Устанавливаем метрики
                for (clinic_id, direction), data in funnel_data.items():
                    for stage, count in data.items():
                        self.conversion_funnel_gauge.labels(
                            clinic_id=clinic_id,
                            stage=stage,
                            direction=direction
                        ).set(count)
                
                return
            
            # Если aggregate доступен, используем его
            # Для каждой клиники и направления звонка
            pipeline = [
                {
                    "$match": {
                        "timestamp": {"$gte": thirty_days_ago}
                    }
                },
                {
                    "$group": {
                        "_id": {
                            "clinic_id": "$clinic_id",
                            "direction": "$call_type.direction"
                        },
                        "total": {"$sum": 1},
                        "qualified": {
                            "$sum": {
                                "$cond": [
                                    {"$gte": ["$metrics.overall_score", 3]},
                                    1,
                                    0
                                ]
                            }
                        },
                        "converted": {
                            "$sum": {
                                "$cond": [{"$eq": ["$conversion", True]}, 1, 0]
                            }
                        }
                    }
                }
            ]
            
            results = await self.mongodb_service.aggregate("call_analytics", pipeline)
            
            # Обновляем метрики
            for result in results:
                clinic_id = result["_id"]["clinic_id"]
                direction = result["_id"]["direction"]
                
                for stage in stages:
                    self.conversion_funnel_gauge.labels(
                        clinic_id=clinic_id,
                        stage=stage,
                        direction=direction
                    ).set(result[stage])
                    
        except Exception as e:
            logger.error(f"Ошибка при сборе метрик воронки конверсии: {e}")
    
    async def _collect_traffic_source_metrics(self):
        """Собирает метрики по источникам трафика."""
        try:
            # Получаем данные за последние 30 дней
            thirty_days_ago = datetime.now() - timedelta(days=30)
            
            # Если метод aggregate недоступен, используем альтернативный подход
            if not hasattr(self.mongodb_service, 'aggregate'):
                documents = await self.mongodb_service.find_many(
                    "call_analytics", 
                    {"timestamp": {"$gte": thirty_days_ago}}, 
                    limit=1000
                )
                
                # Ручная агрегация
                source_data = {}
                for doc in documents:
                    clinic_id = doc.get("clinic_id", "unknown")
                    source = doc.get("client", {}).get("source", "Неизвестно")
                    is_converted = doc.get("conversion", False)
                    
                    key = (clinic_id, source, str(is_converted))
                    source_data[key] = source_data.get(key, 0) + 1
                
                # Устанавливаем метрики
                for (clinic_id, source, converted), count in source_data.items():
                    self.traffic_source_counter.labels(
                        clinic_id=clinic_id,
                        source=source,
                        converted=converted
                    )._value.set(count)
                
                return
            
            # Если aggregate доступен, используем его
            pipeline = [
                {
                    "$match": {
                        "timestamp": {"$gte": thirty_days_ago}
                    }
                },
                {
                    "$group": {
                        "_id": {
                            "clinic_id": "$clinic_id",
                            "source": {"$ifNull": ["$client.source", "Неизвестно"]},
                            "converted": "$conversion"
                        },
                        "count": {"$sum": 1}
                    }
                }
            ]
            
            results = await self.mongodb_service.aggregate("call_analytics", pipeline)
            
            # Сбрасываем предыдущие значения
            try:
                self.traffic_source_counter._metrics.clear()
            except:
                pass
            
            # Обновляем метрики
            for result in results:
                clinic_id = result["_id"]["clinic_id"]
                source = result["_id"]["source"]
                converted = str(result["_id"]["converted"])
                count = result["count"]
                
                try:
                    self.traffic_source_counter.labels(
                        clinic_id=clinic_id,
                        source=source,
                        converted=converted
                    )._value.set(count)
                except:
                    pass
                    
        except Exception as e:
            logger.error(f"Ошибка при сборе метрик источников трафика: {e}")
    
    async def _collect_calls_by_day_metrics(self):
        """Собирает метрики по дням недели."""
        try:
            # Получаем данные за последние 30 дней
            thirty_days_ago = datetime.now() - timedelta(days=30)
            
            # Если метод aggregate недоступен, используем альтернативный подход
            if not hasattr(self.mongodb_service, 'aggregate'):
                documents = await self.mongodb_service.find_many(
                    "call_analytics", 
                    {"timestamp": {"$gte": thirty_days_ago}}, 
                    limit=1000
                )
                
                # Ручная агрегация
                day_data = {}
                days_of_week = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
                
                for doc in documents:
                    clinic_id = doc.get("clinic_id", "unknown")
                    direction = doc.get("call_type", {}).get("direction", "unknown")
                    timestamp = doc.get("timestamp")
                    
                    # Если timestamp есть и это datetime
                    if timestamp and isinstance(timestamp, datetime):
                        day_index = timestamp.weekday()  # 0 = понедельник
                        day_name = days_of_week[day_index]
                        
                        key = (clinic_id, day_name, direction)
                        day_data[key] = day_data.get(key, 0) + 1
                
                # Устанавливаем метрики
                for (clinic_id, day_name, direction), count in day_data.items():
                    self.calls_by_day_counter.labels(
                        clinic_id=clinic_id,
                        day_of_week=day_name,
                        direction=direction
                    )._value.set(count)
                
                return
            
            # Если aggregate доступен, используем его
            pipeline = [
                {
                    "$match": {
                        "timestamp": {"$gte": thirty_days_ago}
                    }
                },
                {
                    "$project": {
                        "clinic_id": 1,
                        "direction": "$call_type.direction",
                        "day_of_week": {"$dayOfWeek": "$timestamp"}  # 1 = воскресенье, 7 = суббота
                    }
                },
                {
                    "$group": {
                        "_id": {
                            "clinic_id": "$clinic_id",
                            "day_of_week": "$day_of_week",
                            "direction": "$direction"
                        },
                        "count": {"$sum": 1}
                    }
                }
            ]
            
            results = await self.mongodb_service.aggregate("call_analytics", pipeline)
            
            # Сбрасываем предыдущие значения
            try:
                self.calls_by_day_counter._metrics.clear()
            except:
                pass
            
            # Преобразование числового дня недели в название
            days_map = {
                1: "Воскресенье", 
                2: "Понедельник", 
                3: "Вторник", 
                4: "Среда", 
                5: "Четверг", 
                6: "Пятница", 
                7: "Суббота"
            }
            
            # Обновляем метрики
            for result in results:
                clinic_id = result["_id"]["clinic_id"]
                day_num = result["_id"]["day_of_week"]
                day_name = days_map.get(day_num, f"День {day_num}")
                direction = result["_id"]["direction"]
                count = result["count"]
                
                try:
                    self.calls_by_day_counter.labels(
                        clinic_id=clinic_id,
                        day_of_week=day_name,
                        direction=direction
                    )._value.set(count)
                except:
                    pass
                    
        except Exception as e:
            logger.error(f"Ошибка при сборе метрик по дням недели: {e}")
    
    async def _collect_call_categories_metrics(self):
        """Собирает метрики по категориям и тегам звонков."""
        try:
            # Получаем данные за последние 30 дней
            thirty_days_ago = datetime.now() - timedelta(days=30)
            
            # Если метод aggregate недоступен, используем альтернативный подход
            if not hasattr(self.mongodb_service, 'aggregate'):
                documents = await self.mongodb_service.find_many(
                    "call_analytics", 
                    {"timestamp": {"$gte": thirty_days_ago}}, 
                    limit=1000
                )
                
                # Ручная агрегация
                category_data = {}
                
                for doc in documents:
                    clinic_id = doc.get("clinic_id", "unknown")
                    category_name = doc.get("call_type", {}).get("category_name", "Неизвестно")
                    
                    # Получаем теги из документа (если есть)
                    tags = doc.get("tags", [])
                    if not tags:
                        tags = ["Без тегов"]
                    
                    for tag in tags:
                        key = (clinic_id, category_name, tag)
                        category_data[key] = category_data.get(key, 0) + 1
                
                # Устанавливаем метрики
                for (clinic_id, category_name, tag), count in category_data.items():
                    self.call_categories_counter.labels(
                        clinic_id=clinic_id,
                        category_name=category_name,
                        tag=tag
                    )._value.set(count)
                
                return
            
            # Если aggregate доступен, используем его (упрощенная версия без тегов)
            pipeline = [
                {
                    "$match": {
                        "timestamp": {"$gte": thirty_days_ago}
                    }
                },
                {
                    "$group": {
                        "_id": {
                            "clinic_id": "$clinic_id",
                            "category_name": "$call_type.category_name"
                        },
                        "count": {"$sum": 1}
                    }
                }
            ]
            
            results = await self.mongodb_service.aggregate("call_analytics", pipeline)
            
            # Сбрасываем предыдущие значения
            try:
                self.call_categories_counter._metrics.clear()
            except:
                pass
            
            # Обновляем метрики
            for result in results:
                clinic_id = result["_id"]["clinic_id"]
                category_name = result["_id"]["category_name"] or "Неизвестно"
                count = result["count"]
                
                try:
                    self.call_categories_counter.labels(
                        clinic_id=clinic_id,
                        category_name=category_name,
                        tag="Все"
                    )._value.set(count)
                except:
                    pass
                    
        except Exception as e:
            logger.error(f"Ошибка при сборе метрик по категориям звонков: {e}")
    
    async def _collect_quality_metrics(self):
        """Собирает метрики качества обслуживания."""
        try:
            # Получаем данные за последние 30 дней
            thirty_days_ago = datetime.now() - timedelta(days=30)
            
            # Метрики качества, которые мы будем собирать
            quality_metric_fields = [
                "greeting", "identification", "consultation", 
                "objection_handling", "closing"
            ]
            
            # Если метод aggregate недоступен, используем альтернативный подход
            if not hasattr(self.mongodb_service, 'aggregate'):
                documents = await self.mongodb_service.find_many(
                    "call_analytics", 
                    {"timestamp": {"$gte": thirty_days_ago}}, 
                    limit=1000
                )
                
                # Ручная агрегация
                quality_data = {}
                
                for doc in documents:
                    clinic_id = doc.get("clinic_id", "unknown")
                    manager_id = doc.get("administrator_id", "unknown")
                    metrics = doc.get("metrics", {})
                    
                    for metric_name in quality_metric_fields:
                        metric_value = metrics.get(metric_name, 0)
                        key = (clinic_id, metric_name, manager_id)
                        
                        if key not in quality_data:
                            quality_data[key] = {"sum": 0, "count": 0}
                        
                        quality_data[key]["sum"] += metric_value
                        quality_data[key]["count"] += 1
                
                # Устанавливаем метрики
                for (clinic_id, metric_name, manager_id), data in quality_data.items():
                    avg_value = data["sum"] / max(data["count"], 1)
                    self.quality_metrics_gauge.labels(
                        clinic_id=clinic_id,
                        metric_name=metric_name,
                        manager_id=manager_id
                    ).set(avg_value)
                
                return
            
            # Если aggregate доступен, используем его
            for metric_name in quality_metric_fields:
                pipeline = [
                    {
                        "$match": {
                            "timestamp": {"$gte": thirty_days_ago}
                        }
                    },
                    {
                        "$group": {
                            "_id": {
                                "clinic_id": "$clinic_id",
                                "manager_id": "$administrator_id"
                            },
                            "avg_value": {"$avg": f"$metrics.{metric_name}"}
                        }
                    }
                ]
                
                results = await self.mongodb_service.aggregate("call_analytics", pipeline)
                
                # Обновляем метрики
                for result in results:
                    clinic_id = result["_id"]["clinic_id"]
                    manager_id = result["_id"]["manager_id"]
                    avg_value = result["avg_value"] or 0
                    
                    self.quality_metrics_gauge.labels(
                        clinic_id=clinic_id,
                        metric_name=metric_name,
                        manager_id=manager_id
                    ).set(avg_value)
                    
        except Exception as e:
            logger.error(f"Ошибка при сборе метрик качества обслуживания: {e}")
    
    async def _collect_clinic_info_metrics(self):
        """Собирает информацию о клиниках."""
        try:
            # Данный метод предполагает, что у вас есть коллекция clinics с информацией о клиниках
            # Если у вас нет такой коллекции, мы можем использовать данные из call_analytics
            
            # Сначала проверим наличие коллекции clinics
            has_clinics = False
            try:
                # Пробуем найти хотя бы одну клинику
                clinic = await self.mongodb_service.find_one("clinics", {})
                has_clinics = clinic is not None
            except:
                has_clinics = False
            
            if has_clinics:
                # Если у вас есть коллекция clinics, используем её
                clinics = await self.mongodb_service.find_many("clinics", {}, limit=100)
                
                for clinic in clinics:
                    clinic_id = str(clinic.get("_id", "unknown"))
                    clinic_name = clinic.get("name", "Неизвестная клиника")
                    region = clinic.get("region", "Неизвестный регион")
                    
                    self.clinic_info_gauge.labels(
                        clinic_id=clinic_id,
                        clinic_name=clinic_name,
                        region=region
                    ).set(1)  # Просто устанавливаем 1, чтобы показать, что клиника существует
            else:
                # Если у вас нет коллекции clinics, соберем информацию из call_analytics
                # Получаем уникальные clinic_id
                if hasattr(self.mongodb_service, 'aggregate'):
                    pipeline = [
                        {
                            "$group": {
                                "_id": "$clinic_id"
                            }
                        }
                    ]
                    
                    results = await self.mongodb_service.aggregate("call_analytics", pipeline)
                    
                    for result in results:
                        clinic_id = result["_id"]
                        if not clinic_id:
                            continue
                        
                        self.clinic_info_gauge.labels(
                            clinic_id=clinic_id,
                            clinic_name=f"Клиника {clinic_id}",
                            region="Неизвестный регион"
                        ).set(1)
                else:
                    # Если aggregate недоступен, используем другой подход
                    documents = await self.mongodb_service.find_many("call_analytics", {}, limit=1000)
                    
                    clinic_ids = set()
                    for doc in documents:
                        clinic_id = doc.get("clinic_id")
                        if clinic_id:
                            clinic_ids.add(clinic_id)
                    
                    for clinic_id in clinic_ids:
                        self.clinic_info_gauge.labels(
                            clinic_id=clinic_id,
                            clinic_name=f"Клиника {clinic_id}",
                            region="Неизвестный регион"
                        ).set(1)
                    
        except Exception as e:
            logger.error(f"Ошибка при сборе информации о клиниках: {e}")

# Создаем функцию для запуска сервиса
async def start_metrics_exporter(mongodb_service: MongoDBService, port: int = 9215):
    """
    Запускает сервис экспорта метрик.
    
    Args:
        mongodb_service: Сервис MongoDB для доступа к базе данных
        port: Порт, на котором будет запущен HTTP-сервер Prometheus
    """
    if not PROMETHEUS_AVAILABLE:
        logger.warning("Prometheus client не доступен. Сервис экспорта метрик не будет запущен.")
        logger.warning("Установите пакет: pip install prometheus-client")
        return None
        
    exporter = MetricsExporterService(mongodb_service, port)
    exporter.start_server()
    
    # Запускаем периодический сбор метрик
    asyncio.create_task(exporter.collect_metrics_job())
    
    logger.info("Сервис экспорта метрик успешно запущен")
    return exporter
