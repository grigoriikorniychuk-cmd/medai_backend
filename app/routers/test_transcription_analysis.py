from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, status, Request
from fastapi.responses import FileResponse
import os
import uuid
import logging
from datetime import datetime

from app.settings.paths import AUDIO_DIR, TRANSCRIPTION_DIR, ANALYSIS_DIR
from app.settings.config import get_settings
from app.services.transcription_service import transcribe_and_save
from app.services.call_analysis_service_new import call_analysis_service

router = APIRouter()
logger = logging.getLogger(__name__)


def verify_api_key(request: Request, settings=Depends(get_settings)):
    api_key_header = request.headers.get("X-API-Key") or request.headers.get("x-api-key")
    expected = settings.SECURITY.API_KEY
    if not expected or api_key_header != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


async def _save_upload(file: UploadFile, dst_path: str):
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    try:
        with open(dst_path, "wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
    finally:
        await file.close()


@router.post("/api/test/transcribe-and-analyze")
async def transcribe_and_analyze(audio: UploadFile = File(...), _: None = Depends(verify_api_key)):
    try:
        # Валидация формата
        content_type = (audio.content_type or "").lower()
        filename = audio.filename or "uploaded.mp3"
        if not (content_type in {"audio/mpeg", "audio/mp3"} or filename.lower().endswith(".mp3")):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Поддерживаются только MP3 файлы")

        # Уникальные имена файлов
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        uid = uuid.uuid4().hex[:8]
        audio_filename = f"test_{ts}_{uid}.mp3"
        audio_path = os.path.join(AUDIO_DIR, audio_filename)

        # Сохранение загруженного файла
        await _save_upload(audio, audio_path)

        # Имя файла транскрипции
        transcript_filename = f"transcription_{ts}_{uid}.txt"
        transcript_path = os.path.join(TRANSCRIPTION_DIR, transcript_filename)

        # Транскрибация
        await transcribe_and_save(
            call_id="",
            audio_path=audio_path,
            output_path=transcript_path,
            num_speakers=2,
            diarize=True,
        )

        # Читаем транскрипцию для анализа
        try:
            with open(transcript_path, "r", encoding="utf-8") as f:
                dialogue = f.read()
        except FileNotFoundError:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Файл транскрипции не найден")

        # Анализ
        analysis_result = await call_analysis_service.analyze_call(dialogue)

        base_name = os.path.splitext(transcript_filename)[0]
        analysis_filename = f"{base_name}_analysis.txt"
        analysis_path = call_analysis_service.save_analysis_to_file(analysis_result, analysis_filename)

        # Ответ с ссылками для скачивания
        return {
            "success": True,
            "message": "Транскрибация и анализ выполнены",
            "data": {
                "transcription": {
                    "filename": transcript_filename,
                    "download_url": f"/api/transcriptions/{transcript_filename}/download",
                },
                "analysis": {
                    "filename": os.path.basename(analysis_path),
                    "download_url": f"/api/analysis/{os.path.basename(analysis_path)}/download",
                },
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка в эндпоинте тестовой транскрибации/анализа: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/api/analysis/{filename}/download")
async def download_analysis(filename: str):
    try:
        safe_name = os.path.basename(filename)
        file_path = os.path.join(ANALYSIS_DIR, safe_name)
        if not os.path.exists(file_path):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Файл {safe_name} не найден")

        headers = {"Content-Disposition": f'attachment; filename="{safe_name}"'}
        return FileResponse(path=file_path, filename=safe_name, media_type="text/plain", headers=headers)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при скачивании анализа: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Ошибка при скачивании анализа: {e}")
