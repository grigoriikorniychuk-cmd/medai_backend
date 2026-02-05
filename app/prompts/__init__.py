"""
Модуль управления промптами для системы MedAI.
Обеспечивает централизованный доступ к промптам и их шаблонам.
"""

from app.prompts.templates import (
    PromptTemplate,
    PromptType,
    LLMProvider,
    DEFAULT_PROMPT_TEMPLATES,
    CLASSIFICATION_PROMPT,
    METRICS_PROMPT,
    ANALYSIS_PROMPT,
    SUMMARY_PROMPT,
)
from app.prompts.manager import PromptManager, prompt_manager

__all__ = [
    "PromptTemplate",
    "PromptType",
    "LLMProvider",
    "PromptManager",
    "prompt_manager",
    "DEFAULT_PROMPT_TEMPLATES",
    "CLASSIFICATION_PROMPT",
    "METRICS_PROMPT",
    "ANALYSIS_PROMPT",
    "SUMMARY_PROMPT",
]
