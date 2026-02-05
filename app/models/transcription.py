from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List
from datetime import datetime


class TranscriptionRequest(BaseModel):
    audio_filename: str = Field(
        ..., description="Имя файла в папке audio для транскрибации"
    )
    phone: Optional[str] = Field(
        None, description="Номер телефона для имени файла результата"
    )
    note_id: Optional[int] = Field(
        None, description="ID заметки для связи с записью звонка"
    )
    num_speakers: int = Field(2, description="Количество говорящих для распознавания")
    diarize: bool = Field(
        True, description="Включить диаризацию (разделение по говорящим)"
    )
    administrator_id: Optional[str] = Field(
        None, description="ID администратора для обновления лимитов"
    )


class TranscriptionResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


class DialogueLine(BaseModel):
    speaker: str
    text: str
    start_time: float = 0
    end_time: float = 0


class Dialogue(BaseModel):
    lines: List[DialogueLine]


class TranscriptionRecord(BaseModel):
    lead_id: Optional[int] = None
    contact_id: Optional[int] = None
    note_id: Optional[int] = None
    client_id: Optional[str] = None
    manager: Optional[str] = None
    phone: Optional[str] = None
    filename: str
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    duration: Optional[int] = None  # Длительность звонка в секундах
    duration_formatted: Optional[str] = None  # Длительность в формате "минуты:секунды"
