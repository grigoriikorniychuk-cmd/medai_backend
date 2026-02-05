from fastapi import APIRouter, HTTPException, status
from typing import Dict, Any
import logging
import asyncio
import subprocess
import os

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/postgres", tags=["PostgreSQL Sync"])

@router.post("/sync-now")
async def trigger_postgres_sync() -> Dict[str, Any]:
    """
    Принудительно запускает синхронизацию данных с PostgreSQL.
    Выполняет postgres_exporter в отдельном процессе.
    """
    try:
        logger.info("Запуск принудительной синхронизации с PostgreSQL...")
        
        # Путь к скрипту экспортера
        exporter_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "datalens", "postgres_exporter.py")
        
        # Запускаем экспортер в отдельном процессе
        process = await asyncio.create_subprocess_exec(
            "python3", exporter_path, "--once",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        # Ждем завершения с таймаутом
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300)  # 5 минут
            
            # Логируем stdout и stderr в любом случае для диагностики
            stdout_output = stdout.decode('utf-8', errors='ignore') if stdout else 'No stdout'
            stderr_output = stderr.decode('utf-8', errors='ignore') if stderr else 'No stderr'
            logger.info(f"Процесс синхронизации завершен с кодом {process.returncode}")
            logger.info(f"STDOUT: \n{stdout_output}")
            logger.error(f"STDERR: \n{stderr_output}")

            if process.returncode == 0:
                logger.info("Синхронизация с PostgreSQL успешно завершена (согласно коду возврата)")
                return {
                    "success": True,
                    "message": "Синхронизация с PostgreSQL успешно завершена",
                    "output": stdout_output[-1000:]
                }
            else:
                logger.error(f"Ошибка при синхронизации с PostgreSQL.")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Ошибка синхронизации: {stderr_output}"
                )
                
        except asyncio.TimeoutError:
            process.kill()
            logger.error("Таймаут при синхронизации с PostgreSQL")
            raise HTTPException(
                status_code=status.HTTP_408_REQUEST_TIMEOUT,
                detail="Таймаут при синхронизации с PostgreSQL"
            )
            
    except Exception as e:
        logger.error(f"Непредвиденная ошибка при синхронизации с PostgreSQL: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка синхронизации: {str(e)}"
        )

@router.post("/restart-exporter")
async def restart_postgres_exporter() -> Dict[str, Any]:
    """
    Перезапускает Docker контейнер postgres_exporter.
    Требует Docker и docker-compose на сервере.
    """
    try:
        logger.info("Перезапуск контейнера postgres_exporter...")
        
        # Останавливаем контейнер
        stop_process = await asyncio.create_subprocess_exec(
            "docker-compose", "stop", "postgres_metrics_exporter",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await stop_process.communicate()
        
        # Запускаем контейнер
        start_process = await asyncio.create_subprocess_exec(
            "docker-compose", "up", "-d", "postgres_metrics_exporter",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await start_process.communicate()
        
        if start_process.returncode == 0:
            logger.info("Контейнер postgres_exporter успешно перезапущен")
            return {
                "success": True,
                "message": "Контейнер postgres_exporter успешно перезапущен"
            }
        else:
            logger.error(f"Ошибка при перезапуске контейнера: {stderr.decode('utf-8') if stderr else 'Unknown error'}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Ошибка перезапуска: {stderr.decode('utf-8') if stderr else 'Unknown error'}"
            )
            
    except Exception as e:
        logger.error(f"Непредвиденная ошибка при перезапуске контейнера: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка перезапуска: {str(e)}"
        )
