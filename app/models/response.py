from typing import Any, Dict, Optional, Union
from pydantic import BaseModel

class BaseResponse(BaseModel):
    """Базовый класс для ответов API."""

    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None 