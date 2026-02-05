import re
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime
import os
import json
import time
import logging
import aiofiles
from motor.motor_asyncio import AsyncIOMotorClient
from ..settings import TRANSCRIPTION_DIR, AUDIO_DIR, MONGO_URI, DB_NAME, evenlabs


logger = logging.getLogger(__name__)


class SpeakerDetection:
    """
    Класс для определения ролей говорящих в диалоге.
    """

    # Фразы, типичные для менеджера
    MANAGER_PHRASES = [
        "клиника",
        "стоматология",
        "запись",
        "администратор",
        "как могу к вам обращаться",
        "врач",
        "прием",
        "доктор",
        "стоматологическая клиника",
        "приглашаем",
        "как вас зовут",
        "специалист",
        "услуги",
        "мы работаем",
        "рассрочка",
        "помочь",
        "подобрать",
        "предложить",
        "консультация",
        "спасибо за звонок",
        "всего доброго",
    ]

    # Фразы, типичные для клиента
    CLIENT_PHRASES = [
        "сколько стоит",
        "цена",
        "дорого",
        "у меня проблема",
        "больно",
        "болит зуб",
        "когда можно",
        "хочу",
        "у меня проблема",
        "подскажите",
        "я хотел",
        "мне нужно",
        "мне надо",
        "сколько будет",
        "как попасть",
        "как записаться",
        "хочу записаться",
    ]

    # Специальные маркеры сильного индикатора менеджера
    STRONG_MANAGER_MARKERS = [
        "администратор",
        "клиника",
        "стоматология",
        "я вас слушаю",
        "чем могу помочь",
        "стоматологическая клиника",
        "медицинский центр",
    ]

    # Специальные маркеры сильного индикатора клиента
    STRONG_CLIENT_MARKERS = [
        "хочу записаться",
        "меня беспокоит",
        "мне нужно",
        "у меня болит",
        "подскажите пожалуйста",
        "сколько будет стоить",
    ]

    @classmethod
    def detect_roles(
        cls, dialogue: List[Dict], manager_name=None, client_name=None
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Определяет, кто из говорящих является менеджером, а кто клиентом,
        используя эвристики и анализ текста.

        Args:
            dialogue: список словарей с репликами (speaker, text)
            manager_name: имя менеджера, если известно
            client_name: имя клиента, если известно

        Returns:
            (manager_speaker, client_speaker) - идентификаторы говорящих
        """
        # Инициализируем счетчики для разных говорящих
        speakers = {}

        # Начальный анализ - собираем данные по всем говорящим
        for line in dialogue:
            speaker = line["speaker"]
            text = line["text"].lower()

            # Инициализируем счетчики для нового говорящего
            if speaker not in speakers:
                speakers[speaker] = {
                    "manager_score": 0,
                    "client_score": 0,
                    "greeting_first": False,
                    "lines_count": 0,
                    "words_count": 0,
                }

            # Основные счетчики
            speakers[speaker]["lines_count"] += 1
            speakers[speaker]["words_count"] += len(text.split())

            # Анализ приветствия
            cls._analyze_greeting(speakers, speaker, text)

            # Анализ фраз
            cls._analyze_phrases(speakers, speaker, text)

            # Анализ особых маркеров
            cls._analyze_special_markers(speakers, speaker, text)

            # Анализ имен
            cls._analyze_names(speakers, speaker, text, manager_name, client_name)

        # Если у нас только один говорящий, не можем определить роли
        if len(speakers) < 2:
            return None, None

        # Вторичный анализ
        cls._analyze_dialogue_structure(speakers, dialogue)

        # Определяем роли на основе собранных данных
        speaker_items = list(speakers.items())
        speaker_items.sort(
            key=lambda x: x[1]["manager_score"] - x[1]["client_score"], reverse=True
        )

        # Логируем анализ для отладки
        logger.info(f"Результаты анализа ролей: {speaker_items}")

        # Первый говорящий с наибольшей разницей будет менеджером
        manager_speaker = speaker_items[0][0]

        # Если есть только один говорящий, клиента нет
        client_speaker = speaker_items[1][0] if len(speaker_items) >= 2 else None

        return manager_speaker, client_speaker

    @classmethod
    def _analyze_greeting(cls, speakers: Dict, speaker: str, text: str):
        """Анализирует приветствие в начале диалога"""
        if (
            "добрый день" in text
            or "здравствуйте" in text
            or "добрый" in text
            or "алло" in text
        ):
            if not any(s["greeting_first"] for s in speakers.values()):
                speakers[speaker]["greeting_first"] = True
                # Первое приветствие обычно от менеджера
                speakers[speaker]["manager_score"] += 3

    @classmethod
    def _analyze_phrases(cls, speakers: Dict, speaker: str, text: str):
        """Анализирует текст на предмет характерных фраз"""
        # Проверяем фразы менеджера
        for phrase in cls.MANAGER_PHRASES:
            if phrase in text:
                speakers[speaker]["manager_score"] += 1

        # Проверяем фразы клиента
        for phrase in cls.CLIENT_PHRASES:
            if phrase in text:
                speakers[speaker]["client_score"] += 1

    @classmethod
    def _analyze_special_markers(cls, speakers: Dict, speaker: str, text: str):
        """Анализирует специальные маркеры для идентификации ролей"""
        # Проверяем сильные индикаторы менеджера
        for marker in cls.STRONG_MANAGER_MARKERS:
            if marker in text:
                speakers[speaker]["manager_score"] += 5

        # Проверяем сильные индикаторы клиента
        for marker in cls.STRONG_CLIENT_MARKERS:
            if marker in text:
                speakers[speaker]["client_score"] += 5

        # Особые эвристики для распознавания ролей

        # 1. Представление клиники - явный признак менеджера
        if re.search(r"(это|здравствуйте|приветствую).*клиника", text) or re.search(
            r"клиника.*слушает", text
        ):
            speakers[speaker]["manager_score"] += 10

        # 2. Представление по имени - обычно это делает менеджер
        if (
            "меня зовут" in text
            or "меня" in text
            and any(
                name in text
                for name in ["мария", "елена", "ольга", "анна", "екатерина"]
            )
        ):
            speakers[speaker]["manager_score"] += 7

        # 3. Вопрос о имени клиента - явный признак менеджера
        if (
            "как ya могу к вам обращаться" in text
            or "как вас зовут" in text
            or "как могу обращаться" in text
        ):
            speakers[speaker]["manager_score"] += 8

        # 4. Проверка на типичные названия клиник
        if any(
            clinic in text
            for clinic in ["дентал", "смайл", "стома", "эли", "дент", "медикал"]
        ):
            speakers[speaker]["manager_score"] += 6

    @classmethod
    def _analyze_names(
        cls,
        speakers: Dict,
        speaker: str,
        text: str,
        manager_name: Optional[str],
        client_name: Optional[str],
    ):
        """Анализирует упоминания имен менеджера и клиента"""
        # Если говорящий упоминает имя менеджера
        if manager_name and manager_name.lower() in text:
            # Если говорящий говорит о себе в третьем лице
            if "администратор" in text or "меня зовут" in text:
                speakers[speaker]["manager_score"] += 8
            else:
                speakers[speaker]["client_score"] += 2

        # Если говорящий упоминает имя клиента
        if client_name and client_name.lower() in text:
            # Если говорящий обращается к клиенту по имени
            if "вас" in text or "вам" in text:
                speakers[speaker]["manager_score"] += 3
            else:
                speakers[speaker]["client_score"] += 5

    @classmethod
    def _analyze_dialogue_structure(cls, speakers: Dict, dialogue: List[Dict]):
        """Вторичный анализ, учитывающий структуру диалога в целом"""
        # Подсчитываем количество реплик и слов каждого говорящего
        total_lines = sum(s["lines_count"] for s in speakers.values())
        total_words = sum(s["words_count"] for s in speakers.values())

        # Обычно менеджер говорит больше
        for speaker, stats in speakers.items():
            words_ratio = stats["words_count"] / total_words

            # Если говорящий произнес больше 60% всех слов, это скорее менеджер
            if words_ratio > 0.6:
                stats["manager_score"] += 3

            # Если говорящий произнес меньше 30% всех слов, это скорее клиент
            if words_ratio < 0.3:
                stats["client_score"] += 2

        # Проверка на типичное начало разговора
        if dialogue:
            first_speaker = dialogue[0]["speaker"]
            # Обычно менеджер начинает разговор
            speakers[first_speaker]["manager_score"] += 2

        # Проверка на типичное завершение разговора
        if dialogue:
            last_speaker = dialogue[-1]["speaker"]
            last_text = dialogue[-1]["text"].lower()

            # Если последняя реплика содержит прощание, скорее всего это менеджер
            if (
                "всего доброго" in last_text
                or "до свидания" in last_text
                or "до свидан" in last_text
            ):
                speakers[last_speaker]["manager_score"] += 2


async def transcribe_and_save(
    call_id: str,  # Добавлен call_id
    audio_path: str,
    output_path: str,
    num_speakers: int = 2,
    diarize: bool = True,
    phone: Optional[str] = None,
    manager_name: Optional[str] = None,
    client_name: Optional[str] = None,
    is_first_contact: bool = False,
    note_data: Optional[Dict[str, Any]] = None,
    administrator_id: Optional[str] = None,
    call_duration: Optional[int] = None,  # Длительность звонка в секундах
):
    """
    Выполняет транскрибацию аудиофайла и сохраняет результат в текстовый файл.

    :param audio_path: Путь к аудиофайлу
    :param output_path: Путь для сохранения результата
    :param num_speakers: Количество говорящих
    :param diarize: Включить разделение по говорящим
    :param phone: Номер телефона клиента
    :param manager_name: Имя менеджера/ответственного
    :param client_name: Имя клиента
    :param is_first_contact: Флаг первичного обращения
    :param note_data: Дополнительные данные о заметке
    :param administrator_id: ID администратора для обновления лимитов
    :param call_duration: Длительность звонка в секундах
    
    :raises Exception: Если превышен месячный лимит клиники
    """
    try:
        logger.info(f"Начало фоновой транскрибации файла: {audio_path}")
        start_time = time.time()

        # ПРОВЕРКА ЛИМИТА КЛИНИКИ ПЕРЕД ТРАНСКРИБАЦИЕЙ
        if note_data and note_data.get("client_id"):
            from app.services.clinic_limits_service import check_clinic_limit, duration_to_minutes
            
            # Оцениваем стоимость транскрипции в минутах
            estimated_minutes = duration_to_minutes(call_duration) if call_duration else 0
            
            limit_check = await check_clinic_limit(note_data["client_id"], estimated_minutes)
            
            if not limit_check.get("allowed", True):
                limit_type = limit_check.get("limit_type", "monthly")
                
                if limit_type == "weekly":
                    error_msg = (
                        f"❌ Транскрипция заблокирована: клиника {limit_check.get('clinic_name')} "
                        f"превысила НЕДЕЛЬНЫЙ лимит ({limit_check.get('current_week_usage'):.1f}/{limit_check.get('weekly_limit')} минут). "
                        f"Лимит сбросится через неделю."
                    )
                else:
                    error_msg = (
                        f"❌ Транскрипция заблокирована: клиника {limit_check.get('clinic_name')} "
                        f"превысила МЕСЯЧНЫЙ лимит ({limit_check.get('current_usage'):.1f}/{limit_check.get('monthly_limit')} минут)"
                    )
                
                logger.error(error_msg)
                
                # Обновляем статус в MongoDB на limit_exceeded
                if call_id:
                    try:
                        mongo_client_temp = AsyncIOMotorClient(MONGO_URI)
                        db_temp = mongo_client_temp[DB_NAME]
                        await db_temp.calls.update_one(
                            {"_id": __import__('bson').ObjectId(call_id)},
                            {"$set": {
                                "transcription_status": "limit_exceeded",
                                "transcription_error": error_msg,
                                "updated_at": datetime.now()
                            }}
                        )
                    except Exception:
                        pass
                    finally:
                        if mongo_client_temp:
                            mongo_client_temp.close()
                
                raise Exception(error_msg)
            
            logger.info(
                f"✅ Лимит проверен для {limit_check.get('clinic_name')}: "
                f"Месяц: {limit_check.get('current_usage'):.1f}/{limit_check.get('monthly_limit')} минут, "
                f"Неделя: {limit_check.get('current_week_usage'):.1f}/{limit_check.get('weekly_limit')} минут"
            )

        # Инициализируем клиент EvenLabs
        client = evenlabs()

        # Открываем файл и отправляем его на транскрибацию
        with open(audio_path, "rb") as audio_file:
            response = client.speech_to_text.convert(
                file=audio_file,
                model_id="scribe_v1",
                diarize=diarize,
                num_speakers=num_speakers,
            )

        # Преобразуем ответ в словарь
        response_dict = response.dict()

        # Сохраняем полный ответ API для отладки
        debug_file_path = output_path + ".debug.json"
        with open(debug_file_path, "w", encoding="utf-8") as debug_file:
            json.dump(response_dict, debug_file, ensure_ascii=False, indent=2)
        logger.info(f"Сохранен отладочный файл с полным ответом API: {debug_file_path}")

        # Создаем нейтральные метки говорящих для начального анализа
        speaker_mapping = {}
        for i in range(num_speakers):
            # Нейтральные метки для начального распознавания
            neutral_name = f"Speaker {i+1}"
            speaker_mapping[f"speaker_{i}"] = neutral_name
            speaker_mapping[i] = neutral_name
            speaker_mapping[str(i)] = neutral_name

        # Получаем слова из ответа API
        words = response_dict.get("words", [])

        # Собираем слова в предложения, основываясь на паузах между словами
        sentences = []
        current_sentence = []
        current_speaker = None
        current_start = 0

        # Параметры для определения пауз между предложениями
        PAUSE_THRESHOLD = 0.7  # Порог паузы в секундах для разделения предложений
        MAX_SENTENCE_DURATION = (
            10.0  # Максимальная длительность одного предложения в секундах
        )

        for i, word in enumerate(words):
            # Пропускаем пробелы и паузы
            if word.get("type") == "spacing":
                continue

            # Получаем текущее слово
            word_text = word.get("text", "")
            word_start = word.get("start", 0)
            word_end = word.get("end", 0)
            word_speaker = word.get("speaker_id", "Unknown")

            # Определяем, является ли это начало новой реплики
            is_new_sentence = False

            # Если это первое слово
            if not current_sentence:
                is_new_sentence = True
                current_speaker = word_speaker
            else:
                # Если сменился говорящий
                if word_speaker != current_speaker:
                    is_new_sentence = True
                # Если длинная пауза между словами
                elif (
                    i > 0
                    and (word_start - words[i - 1].get("end", 0)) > PAUSE_THRESHOLD
                ):
                    is_new_sentence = True
                # Если предложение слишком длинное
                elif word_end - current_start > MAX_SENTENCE_DURATION:
                    is_new_sentence = True
                # Если в слове есть знак конца предложения и следующее слово начинается с большой буквы
                elif (
                    word_text.endswith(".")
                    or word_text.endswith("?")
                    or word_text.endswith("!")
                ) and i < len(words) - 1:
                    next_word = words[i + 1].get("text", "")
                    if next_word and next_word[0].isupper():
                        is_new_sentence = True

            # Если это новое предложение, сохраняем предыдущее и начинаем новое
            if is_new_sentence and current_sentence:
                # Формируем текст из слов
                text = " ".join([w.get("text", "") for w in current_sentence])
                # Время начала и конца предложения
                sentence_start_time = current_sentence[0].get("start", 0)
                sentence_end_time = current_sentence[-1].get("end", 0)
                # Определяем говорящего (берем наиболее частый speaker_id)
                speaker_counts = {}
                for w in current_sentence:
                    sp = w.get("speaker_id", "Unknown")
                    speaker_counts[sp] = speaker_counts.get(sp, 0) + 1
                most_common_speaker = max(speaker_counts.items(), key=lambda x: x[1])[0]

                # Добавляем предложение в список
                sentences.append(
                    {
                        "speaker_id": most_common_speaker,
                        "text": text,
                        "start_time": sentence_start_time,
                        "end_time": sentence_end_time,
                    }
                )

                # Начинаем новое предложение
                current_sentence = [word]
                current_speaker = word_speaker
                current_start = word_start
            else:
                # Продолжаем текущее предложение
                current_sentence.append(word)

        # Добавляем последнее предложение
        if current_sentence:
            text = " ".join([w.get("text", "") for w in current_sentence])
            sentence_start_time = current_sentence[0].get("start", 0)
            sentence_end_time = current_sentence[-1].get("end", 0)
            speaker_counts = {}
            for w in current_sentence:
                sp = w.get("speaker_id", "Unknown")
                speaker_counts[sp] = speaker_counts.get(sp, 0) + 1
            most_common_speaker = max(speaker_counts.items(), key=lambda x: x[1])[0]

            sentences.append(
                {
                    "speaker_id": most_common_speaker,
                    "text": text,
                    "start_time": sentence_start_time,
                    "end_time": sentence_end_time,
                }
            )

        # Обработка случая одного предложения и других специальных случаев...
        # (код из оригинальной функции для обработки различных особых случаев)

        # Если у нас всего одно предложение для 2+ спикеров, разделим его по очереди
        if len(sentences) == 1 and num_speakers >= 2:
            logger.warning(
                "Обнаружено только одно предложение для нескольких говорящих. Применяем эвристическое разделение."
            )
            text = sentences[0]["text"]
            # Разделяем по знакам препинания, затем объединяем в предполагаемые реплики
            parts = re.split(r"([.!?])\s+", text)
            new_sentences = []

            current_speaker_idx = 0
            current_text_parts = []
            current_start = sentences[0]["start_time"]
            total_duration = sentences[0]["end_time"] - sentences[0]["start_time"]
            part_duration = (
                total_duration / len(parts) if len(parts) > 0 else total_duration
            )

            for i, part in enumerate(parts):
                if not part:
                    continue

                # Добавляем часть к текущему предложению
                current_text_parts.append(part)

                # Если это знак препинания, завершаем предложение
                if part in [".", "!", "?"] or i == len(parts) - 1:
                    if current_text_parts:
                        combined_text = "".join(current_text_parts).strip()
                        if combined_text:
                            part_start = current_start
                            part_end = part_start + part_duration * len(
                                current_text_parts
                            )

                            new_sentences.append(
                                {
                                    "speaker_id": current_speaker_idx % num_speakers,
                                    "text": combined_text,
                                    "start_time": part_start,
                                    "end_time": part_end,
                                }
                            )

                            current_start = part_end
                            current_speaker_idx += 1
                            current_text_parts = []

            if new_sentences:
                sentences = new_sentences
                logger.info(
                    f"Разделили аудио на {len(sentences)} предложений с помощью эвристики"
                )

        # Финальная обработка предложений в диалог с нейтральными метками
        initial_dialogue = []
        for sentence in sentences:
            speaker_id = sentence["speaker_id"]
            # Используем нейтральные метки для начального анализа
            display_name = speaker_mapping.get(speaker_id, f"Speaker Unknown")

            initial_dialogue.append(
                {
                    "speaker": display_name,
                    "text": sentence["text"],
                    "start_time": sentence["start_time"],
                    "end_time": sentence["end_time"],
                    "original_speaker_id": speaker_id,
                }
            )

        # Применяем эвристики для определения ролей (менеджер и клиент)
        manager_speaker, client_speaker = SpeakerDetection.detect_roles(
            initial_dialogue, manager_name, client_name
        )

        logger.info(
            f"Определены роли: Менеджер = {manager_speaker}, Клиент = {client_speaker}"
        )

        # Создаем финальные метки для вывода
        # ВРЕМЕННО: убираем имя менеджера, чтобы AI использовал только график
        manager_display = "Менеджер"  # f"Менеджер{f' ({manager_name})' if manager_name else ''}"
        client_display = f"Клиент{f' ({client_name})' if client_name else ''}"

        # Переформатируем диалог с определенными ролями
        dialogue = []
        for line in initial_dialogue:
            original_speaker = line["speaker"]
            if original_speaker == manager_speaker:
                display_name = manager_display
            elif original_speaker == client_speaker:
                display_name = client_display
            else:
                display_name = f"Участник ({original_speaker})"

            dialogue.append(
                {
                    "speaker": display_name,
                    "text": line["text"],
                    "start_time": line["start_time"],
                    "end_time": line["end_time"],
                }
            )

        # Записываем диалог в файл
        with open(output_path, "w", encoding="utf-8") as file:
            # Добавляем заголовок с информацией о звонке
            file.write(f"Транскрипция звонка\n")
            file.write(
                f"Дата и время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"  # Исправлено: %M вместо кириллической М
            )

            if phone:
                file.write(f"Телефон: {phone}\n")

            if client_name:
                file.write(f"Клиент: {client_name}\n")

            # ВРЕМЕННО: закомментировано чтобы AI использовал только график
            # if manager_name:
            #     file.write(f"Менеджер: {manager_name}\n")

            if is_first_contact:
                file.write("Тип: Первичное обращение\n")

            file.write(f"Файл: {os.path.basename(audio_path)}\n")

            # Добавляем информацию о длительности
            # Приоритет: 1) call_duration из параметра 2) duration из API ответа
            # Если call_duration = 0 или None, но note_data содержит информацию - возьмем из MongoDB
            duration = call_duration if call_duration is not None and call_duration > 0 else response_dict.get("duration", 0)

            # Если duration всё ещё 0 и есть note_data с note_id - получаем из MongoDB
            if duration == 0 and note_data and note_data.get("note_id"):
                mongo_client_temp = None
                try:
                    # AsyncIOMotorClient и MONGO_URI, DB_NAME уже импортированы в начале файла
                    mongo_client_temp = AsyncIOMotorClient(MONGO_URI)
                    db_temp = mongo_client_temp[DB_NAME]
                    call_doc = await db_temp.calls.find_one({"note_id": note_data["note_id"]})
                    if call_doc:
                        # duration находится в КОРНЕ документа, а не в metrics!
                        duration = call_doc.get("duration", 0)
                except Exception:
                    pass  # Если не удалось получить из MongoDB, используем 0
                finally:
                    if mongo_client_temp:
                        mongo_client_temp.close()

            minutes = int(duration) // 60
            seconds = int(duration) % 60
            duration_formatted = f"{minutes}:{seconds:02d}"
            file.write(f"Длительность: {duration_formatted}\n\n")

            # Записываем диалог
            for line in dialogue:
                # Форматируем время в формате [MM:SS]
                start_min = int(line["start_time"]) // 60
                start_sec = int(line["start_time"]) % 60
                time_str = f"[{start_min:02d}:{start_sec:02d}]"

                file.write(f"{time_str} {line['speaker']}: {line['text']}\n\n")

        process_time = time.time() - start_time
        logger.info(
            f"Транскрипция завершена и сохранена в {output_path} (заняло {process_time:.2f} сек.)"
        )

        # Обновляем счётчик использования лимитов клиники (в минутах!)
        if note_data and note_data.get("client_id"):
            try:
                from app.services.clinic_limits_service import increment_clinic_usage, duration_to_minutes
                
                # Конвертируем duration в минуты
                minutes_used = duration_to_minutes(duration)
                
                # Увеличиваем счётчик использования
                await increment_clinic_usage(note_data["client_id"], minutes_used)
                logger.info(
                    f"Обновлён счётчик лимитов для клиники {note_data['client_id']}: "
                    f"+{minutes_used:.2f} минут (duration: {duration_formatted})"
                )
            except Exception as limit_error:
                logger.error(f"Ошибка при обновлении лимитов клиники: {limit_error}")

        # Обновляем статус транскрибации в MongoDB
        if call_id:
            try:
                from bson.objectid import ObjectId
                
                mongo_client = AsyncIOMotorClient(MONGO_URI)
                db = mongo_client[DB_NAME]
                
                # Базовое обновление статуса
                update_fields = {
                    "transcription_status": "success",
                    "updated_at": datetime.now()
                }
                
                # НОВАЯ ЛОГИКА: Определяем администратора через AI + график
                # Получаем client_id из базы данных calls
                try:
                    # Получаем данные звонка из базы
                    call_doc = await db.calls.find_one({"_id": ObjectId(call_id)})
                    
                    if call_doc and call_doc.get("client_id"):
                        client_id = call_doc["client_id"]
                        
                        # Читаем текст транскрипции из файла
                        transcription_text = ""
                        if os.path.exists(output_path):
                            async with aiofiles.open(output_path, 'r', encoding='utf-8') as f:
                                transcription_text = await f.read()
                        
                        if transcription_text:
                            from app.services.admin_detection_service import determine_administrator_for_call
                            from datetime import date
                            
                            # Получаем дату звонка из документа
                            call_date = datetime.now().date()
                            if call_doc.get("created_at"):
                                call_date = datetime.fromtimestamp(call_doc["created_at"]).date()
                            elif call_doc.get("created_date"):
                                # Парсим дату из строки формата "2026-01-05 16:37:52"
                                try:
                                    call_date = datetime.strptime(call_doc["created_date"], "%Y-%m-%d %H:%M:%S").date()
                                except:
                                    pass
                            
                            # Определяем администратора
                            administrator_name = await determine_administrator_for_call(
                                clinic_id=client_id,
                                call_date=call_date,
                                transcription_text=transcription_text,
                                responsible_user_id=call_doc.get("responsible_user_id"),
                                manager_name=manager_name,  # Передаём имя ответственного из AmoCRM
                            )
                            
                            # Добавляем в обновление
                            update_fields["administrator"] = administrator_name
                            logger.info(
                                f"Администратор определён для call_id {call_id}: {administrator_name}"
                            )
                        else:
                            logger.warning(f"Транскрипция пустая для call_id {call_id}")
                    else:
                        logger.warning(f"Не найден client_id для call_id {call_id}")
                        
                except Exception as admin_error:
                    logger.error(f"Ошибка при определении администратора: {admin_error}", exc_info=True)
                    # Продолжаем без обновления администратора
                
                # Обновляем документ
                await db.calls.update_one(
                    {"_id": ObjectId(call_id)},
                    {"$set": update_fields}
                )
                logger.info(f"Статус транскрибации обновлен на 'success' для call_id: {call_id}")
            except Exception as status_error:
                logger.error(f"Ошибка при обновлении статуса транскрибации: {status_error}")
            finally:
                if 'mongo_client' in locals():
                    mongo_client.close()

        # Сохраняем информацию о транскрипции в базу данных, если есть данные заметки
        if note_data:
            try:
                output_filename = os.path.basename(output_path)
                audio_filename = os.path.basename(audio_path)  # Получаем имя аудиофайла

                await save_transcription_info(
                    filename=output_filename,
                    note_id=note_data.get("note_id"),
                    lead_id=note_data.get("lead_id"),
                    contact_id=note_data.get("contact_id"),
                    client_id=note_data.get("client_id"),
                    manager=manager_name,
                    phone=phone,
                    filename_audio=audio_filename,
                    administrator_id=administrator_id,
                    duration=duration,                  # Передаем длительность в секундах
                    duration_formatted=duration_formatted,  # Передаем отформатированную длительность
                )
            except Exception as db_error:
                logger.error(
                    f"Ошибка при сохранении информации о транскрипции в базу данных: {db_error}"
                )

        # Запускаем синхронизацию с AmoCRM
        if call_id:
            try:
                from ..services.amo_sync_service import sync_transcription_to_amo

                logger.info(f"Запуск синхронизации транскрипции с AmoCRM для call_id: {call_id}")
                await sync_transcription_to_amo(call_id)
            except Exception as amo_error:
                logger.error(f"Ошибка при синхронизации транскрипции с AmoCRM для call_id {call_id}: {amo_error}")
        else:
            logger.warning("call_id не был предоставлен, синхронизация с AmoCRM пропущена.")

    except Exception as e:
        logger.error(f"Ошибка при фоновой транскрибации: {str(e)}")
        import traceback

        logger.error(f"Стек трейс: {traceback.format_exc()}")

        # Обновляем статус в MongoDB на failed
        try:
            from ..services.mongodb_service import mongodb_service
            from bson import ObjectId
            
            await mongodb_service.update_one(
                "calls",
                {"_id": ObjectId(call_id)},
                {
                    "$set": {
                        "transcription_status": "failed",
                        "transcription_error": str(e),
                        "administrator": "Неизвестный администратор",  # При failed транскрипции ставим Неизвестный
                        "updated_at": datetime.now()
                    }
                }
            )
            logger.info(f"Статус транскрибации обновлён на 'failed' для call_id: {call_id}, administrator установлен в 'Неизвестный администратор'")
        except Exception as update_error:
            logger.error(f"Не удалось обновить статус в MongoDB: {update_error}")

        # Записываем информацию об ошибке в файл результата
        try:
            with open(output_path, "w", encoding="utf-8") as file:
                file.write(f"Ошибка при транскрибации файла {audio_path}:\n\n{str(e)}")
        except:
            logger.error(
                f"Не удалось записать информацию об ошибке в файл {output_path}"
            )


async def save_transcription_info(
    filename: str,
    note_id: Optional[int] = None,
    lead_id: Optional[int] = None,
    contact_id: Optional[int] = None,
    client_id: Optional[str] = None,
    manager: Optional[str] = None,
    phone: Optional[str] = None,
    filename_audio: Optional[str] = None,
    administrator_id: Optional[str] = None,
    duration: Optional[int] = None,
    duration_formatted: Optional[str] = None,
):
    """
    Сохраняет информацию о транскрипции в MongoDB для последующего поиска.
    Предотвращает создание дубликатов.
    """
    try:
        mongo_client = AsyncIOMotorClient(MONGO_URI)
        db = mongo_client[DB_NAME]
        collection = db["transcriptions"]

        # Если не указана длительность звонка и есть note_id, пытаемся получить её из API
        if (duration is None or not duration_formatted) and note_id and client_id:
            try:
                from ..settings.amocrm import get_amocrm_config
                from mlab_amo_async.amocrm_client import AsyncAmoCRMClient
                
                # Получаем конфигурацию AmoCRM
                amocrm_config = get_amocrm_config()
                
                # Создаем клиент AmoCRM
                client = AsyncAmoCRMClient(
                    client_id=client_id,
                    client_secret=amocrm_config.get("client_secret", ""),
                    subdomain=amocrm_config.get("subdomain", ""),
                    redirect_url=amocrm_config.get("redirect_url", ""),
                    mongo_uri="mongodb://localhost:27017/",
                    db_name="medai",
                )
                
                # Получаем звонки контакта
                if contact_id:
                    calls_response = await client.contacts.request(
                        "get", f"contacts/{contact_id}/notes?filter[note_type]=10,11"
                    )
                    
                    if calls_response and "_embedded" in calls_response and "notes" in calls_response["_embedded"]:
                        notes = calls_response["_embedded"]["notes"]
                        
                        # Ищем заметку с нужным note_id
                        for note in notes:
                            if note.get("id") == note_id and "params" in note:
                                params = note.get("params", {})
                                if "duration" in params:
                                    duration = params.get("duration", 0)
                                    # Форматируем длительность в формат "минуты:секунды"
                                    minutes = duration // 60
                                    seconds = duration % 60
                                    duration_formatted = f"{minutes}:{seconds:02d}"
                                    logger.info(f"Получена длительность звонка из AmoCRM: {duration} сек. ({duration_formatted})")
                                    break
                
                # Закрываем соединение с AmoCRM
                await client.close()
                
            except Exception as e:
                logger.warning(f"Не удалось получить информацию о длительности звонка из AmoCRM: {str(e)}")

        # Проверяем, существует ли уже запись для этого файла
        existing_record = await collection.find_one({"filename": filename})

        if existing_record:
            # Обновляем существующую запись
            update_data = {
                "lead_id": lead_id,
                "contact_id": contact_id,
                "note_id": note_id,
                "client_id": client_id,
                "manager": manager,
                "phone": phone,
                "filename_audio": filename_audio,
                "updated_at": datetime.now().isoformat(),
            }
            
            # Добавляем длительность звонка, если она доступна
            if duration is not None:
                update_data["duration"] = duration
            if duration_formatted:
                update_data["duration_formatted"] = duration_formatted
                
            await collection.update_one(
                {"_id": existing_record["_id"]},
                {"$set": update_data},
            )
            logger.info(f"Обновлена информация о транскрипции: {filename}")
        else:
            # Создаем новую запись
            record = {
                "lead_id": lead_id,
                "contact_id": contact_id,
                "note_id": note_id,
                "client_id": client_id,
                "manager": manager,
                "phone": phone,
                "filename": filename,
                "filename_audio": filename_audio,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
            }
            
            # Добавляем длительность звонка, если она доступна
            if duration is not None:
                record["duration"] = duration
            if duration_formatted:
                record["duration_formatted"] = duration_formatted

            # Сохраняем в базу
            await collection.insert_one(record)
            logger.info(
                f"Сохранена информация о транскрипции в базу данных: {filename}"
            )

        return True
    except Exception as e:
        logger.error(
            f"Ошибка при сохранении информации о транскрипции в базу данных: {e}"
        )
        return False


async def find_transcription_file(
    note_id: Optional[int] = None,
    lead_id: Optional[int] = None,
    contact_id: Optional[int] = None,
    phone: Optional[str] = None,
):
    """
    Ищет файл транскрипции в базе данных по указанным параметрам.
    Возвращает имя файла, если найдено.
    """
    try:
        mongo_client = AsyncIOMotorClient(MONGO_URI)
        db = mongo_client[DB_NAME]
        collection = db["transcriptions"]

        # Создаем фильтр
        filter_query = {}
        if note_id:
            filter_query["note_id"] = note_id
        if lead_id:
            filter_query["lead_id"] = lead_id
        if contact_id:
            filter_query["contact_id"] = contact_id
        if phone:
            filter_query["phone"] = phone

        # Если фильтр пустой, возвращаем None
        if not filter_query:
            logger.warning("Не указаны параметры для поиска транскрипции")
            return None

        # Ищем запись
        record = await collection.find_one(filter_query, sort=[("created_at", -1)])

        if record and "filename" in record:
            logger.info(f"Найдена запись о транскрипции: {record['filename']}")
            return record["filename"]
        else:
            logger.warning(
                f"Запись о транскрипции не найдена для параметров: {filter_query}"
            )
            return None
    except Exception as e:
        logger.error(f"Ошибка при поиске записи о транскрипции: {e}")
        return None


import logging
import re
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
import json

logger = logging.getLogger(__name__)


class TranscriptionProcessor:
    """
    Класс для обработки транскрипций аудиозаписей разговоров и
    их преобразования в структурированный формат диалога.
    """

    def __init__(self, manager_display="Менеджер", client_display="Клиент"):
        self.manager_display = manager_display
        self.client_display = client_display

    def process_transcription(self, transcription_data: Dict) -> List[Dict]:
        """
        Основной метод обработки данных транскрипции

        Args:
            transcription_data: Данные транскрипции из JSON файла

        Returns:
            Структурированный диалог в виде списка реплик
        """
        if not transcription_data:
            return []

        words = transcription_data.get("words", [])
        if not words:
            return []

        # Определение числа говорящих
        speakers = self._identify_speakers(words)

        # Формирование предложений из слов
        sentences = self._form_sentences(words, len(speakers))

        # Преобразование предложений в диалог
        dialogue = self._sentences_to_dialogue(sentences, speakers)

        # Если диалог слишком короткий, пробуем эвристики разделения
        if len(dialogue) <= 1 and len(speakers) >= 2:
            dialogue = self._apply_heuristics(dialogue, len(speakers))

        return dialogue

    def _identify_speakers(self, words: List[Dict]) -> Dict[str, str]:
        """Определяет и возвращает идентификаторы говорящих"""
        speaker_ids = set()
        for word in words:
            if "speaker_id" in word:
                speaker_ids.add(word["speaker_id"])

        # Создаем словарь маппинга ID говорящих на отображаемые имена
        speaker_mapping = {}
        for i, speaker_id in enumerate(speaker_ids):
            if i == 0:
                speaker_mapping[speaker_id] = self.manager_display
            else:
                speaker_mapping[speaker_id] = self.client_display

        return speaker_mapping

    def _form_sentences(self, words: List[Dict], num_speakers: int) -> List[Dict]:
        """Формирует предложения из слов на основе пунктуации и пауз"""
        sentences = []
        current_sentence = []

        for word in words:
            # Пропускаем пробелы и паузы
            if word.get("type") == "spacing":
                continue

            current_sentence.append(word)

            # Завершаем предложение на знаках пунктуации или длинных паузах
            if self._is_sentence_end(word):
                if current_sentence:
                    sentence = self._create_sentence_from_words(current_sentence)
                    sentences.append(sentence)
                    current_sentence = []

        # Добавляем последнее предложение
        if current_sentence:
            sentence = self._create_sentence_from_words(current_sentence)
            sentences.append(sentence)

        return sentences

    def _is_sentence_end(self, word: Dict) -> bool:
        """Определяет, является ли слово окончанием предложения"""
        text = word.get("text", "")
        # Проверка на знаки препинания в конце
        if text and text[-1] in [".", "!", "?"]:
            return True

        # Длинная пауза после слова тоже может означать конец предложения
        pause_after = word.get("end_pause", 0)
        if pause_after > 1.0:  # Пауза больше 1 секунды
            return True

        return False

    def _create_sentence_from_words(self, words: List[Dict]) -> Dict:
        """Создает структуру предложения из списка слов"""
        if not words:
            return {}

        text = " ".join([w.get("text", "") for w in words])
        sentence_start_time = words[0].get("start", 0)
        sentence_end_time = words[-1].get("end", 0)

        # Определяем наиболее частого говорящего в предложении
        speaker_counts = {}
        for w in words:
            speaker_id = w.get("speaker_id", "Unknown")
            speaker_counts[speaker_id] = speaker_counts.get(speaker_id, 0) + 1

        most_common_speaker = max(speaker_counts.items(), key=lambda x: x[1])[0]

        return {
            "speaker_id": most_common_speaker,
            "text": text,
            "start_time": sentence_start_time,
            "end_time": sentence_end_time,
        }

    def _sentences_to_dialogue(
        self, sentences: List[Dict], speaker_mapping: Dict
    ) -> List[Dict]:
        """Преобразует предложения в структуру диалога"""
        dialogue = []

        for sentence in sentences:
            speaker_id = sentence["speaker_id"]
            # Используем маппинг для определения отображаемого имени спикера
            display_name = speaker_mapping.get(speaker_id, "Участник")

            dialogue.append(
                {
                    "speaker": display_name,
                    "text": sentence["text"],
                    "start_time": sentence["start_time"],
                    "end_time": sentence["end_time"],
                }
            )

        return dialogue

    def _apply_heuristics(self, dialogue: List[Dict], num_speakers: int) -> List[Dict]:
        """Применяет эвристики для разделения монолога на диалог"""
        if not dialogue:
            return []

        text = dialogue[0]["text"] if dialogue else ""

        # Пробуем разделить по вопросительным знакам (вопрос-ответ)
        qa_parts = self._split_by_questions(text)
        if len(qa_parts) > 1:
            return self._create_dialogue_from_parts(
                qa_parts,
                num_speakers,
                dialogue[0]["start_time"],
                dialogue[0]["end_time"],
            )

        # Если не получилось, пробуем по точкам и знакам препинания
        parts = self._split_by_punctuation(text)
        if len(parts) > 1:
            return self._create_dialogue_from_parts(
                parts, num_speakers, dialogue[0]["start_time"], dialogue[0]["end_time"]
            )

        return dialogue

    def _split_by_questions(self, text: str) -> List[str]:
        """Разделяет текст по вопросительным знакам"""
        parts = []
        qa_parts = text.split("?")

        for i, part in enumerate(qa_parts):
            if not part.strip():
                continue

            # Добавляем вопросительный знак обратно (кроме последней части)
            if i < len(qa_parts) - 1:
                part += "?"

            parts.append(part.strip())

        return parts

    def _split_by_punctuation(self, text: str) -> List[str]:
        """Разделяет текст по знакам препинания"""
        parts = re.split(r"([.!?])\s+", text)
        result = []

        current_part = ""
        for i, part in enumerate(parts):
            if not part:
                continue

            if part in [".", "!", "?"] or i == len(parts) - 1:
                current_part += part
                result.append(current_part.strip())
                current_part = ""
            else:
                current_part += part

        if current_part:
            result.append(current_part.strip())

        return result

    def _create_dialogue_from_parts(
        self, parts: List[str], num_speakers: int, start_time: float, end_time: float
    ) -> List[Dict]:
        """Создает диалог из частей текста, чередуя говорящих"""
        dialogue = []
        total_duration = end_time - start_time
        part_duration = total_duration / len(parts) if parts else total_duration

        for i, part in enumerate(parts):
            # Чередуем говорящих
            speaker = self.manager_display if i % 2 == 0 else self.client_display

            # Расчетное время для части
            part_start = start_time + i * part_duration
            part_end = part_start + part_duration

            dialogue.append(
                {
                    "speaker": speaker,
                    "text": part,
                    "start_time": part_start,
                    "end_time": part_end,
                }
            )

        return dialogue


class TranscriptionService:
    """
    Сервис для управления транскрипциями, чтения файлов и форматирования результатов
    """

    def __init__(self):
        self.processor = TranscriptionProcessor()

    def process_file(self, file_path: str) -> List[Dict]:
        """Обрабатывает файл транскрипции и возвращает структурированный диалог"""
        try:
            data = self._read_transcription_file(file_path)
            return self.processor.process_transcription(data)
        except Exception as e:
            logger.error(
                f"Ошибка при обработке файла транскрипции {file_path}: {str(e)}"
            )
            return []

    def _read_transcription_file(self, file_path: str) -> Dict:
        """Читает файл транскрипции в зависимости от формата"""
        path = Path(file_path)

        if not path.exists():
            logger.error(f"Файл {file_path} не найден")
            return {}

        if path.suffix == ".json":
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        else:
            # Для текстовых файлов или других форматов
            # можно добавить специфическую обработку
            logger.warning(f"Неподдерживаемый формат файла: {path.suffix}")
            return {}

    def format_dialogue_for_display(self, dialogue: List[Dict]) -> str:
        """Форматирует диалог для отображения в виде текста с временными метками"""
        result = []

        for item in dialogue:
            minutes = int(item["start_time"] // 60)
            seconds = int(item["start_time"] % 60)
            time_str = f"[{minutes:02d}:{seconds:02d}]"

            formatted_line = f"{time_str} {item['speaker']}: {item['text']}"
            result.append(formatted_line)

        return "\n\n".join(result)

    def format_dialogue_for_analysis(self, dialogue: List[Dict]) -> str:
        """Форматирует диалог для отправки на анализ (без временных меток)"""
        result = []

        for item in dialogue:
            formatted_line = f"{item['speaker']}: {item['text']}"
            result.append(formatted_line)

        return "\n\n".join(result)

    def _read_transcription_file(self, file_path: str) -> Dict:
        """Читает файл транскрипции в зависимости от формата"""
        path = Path(file_path)

        if not path.exists():
            logger.error(f"Файл {file_path} не найден")
            return {}

        if path.suffix == ".json":
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        else:
            # Для текстовых файлов или других форматов
            # можно добавить специфическую обработку
            logger.warning(f"Неподдерживаемый формат файла: {path.suffix}")
            return {}

    def format_dialogue_for_display(self, dialogue: List[Dict]) -> str:
        """Форматирует диалог для отображения в виде текста с временными метками"""
        result = []

        for item in dialogue:
            minutes = int(item["start_time"] // 60)
            seconds = int(item["start_time"] % 60)
            time_str = f"[{minutes:02d}:{seconds:02d}]"

            formatted_line = f"{time_str} {item['speaker']}: {item['text']}"
            result.append(formatted_line)

        return "\n\n".join(result)

    def format_dialogue_for_analysis(self, dialogue: List[Dict]) -> str:
        """Форматирует диалог для отправки на анализ (без временных меток)"""
        result = []

        for item in dialogue:
            formatted_line = f"{item['speaker']}: {item['text']}"
            result.append(formatted_line)

        return "\n\n".join(result)
