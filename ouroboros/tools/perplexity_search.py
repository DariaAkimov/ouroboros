"""
Инструмент для выполнения поисковых запросов через Perplexity API.
Требует установки: pip install langchain-perplexity
И наличия переменной окружения: PERPLEXITY_API_KEY
"""
"""
Инструмент для выполнения поисковых запросов через Perplexity API.
"""

import json
import logging
import os
from typing import Optional

from langchain_perplexity import ChatPerplexity

from ouroboros.tools.registry import ToolContext, ToolEntry

log = logging.getLogger(__name__)

DEFAULT_MAX_RETRIES = 3
RETRY_DELAY_SEC = 25


def _get_perplexity_client() -> ChatPerplexity:
    """Создаёт клиента Perplexity."""
    api_key = os.environ.get("PERPLEXITY_API_KEY", "")
    if not api_key:
        raise ValueError("PERPLEXITY_API_KEY not set")
    return ChatPerplexity(
        model="sonar-pro",
        temperature=0.0,
        max_retries=1,
        api_key=api_key,
    )


def _fetch_sync(query: str, max_retries: int = DEFAULT_MAX_RETRIES) -> str:
    """
    Синхронная обёртка для асинхронного запроса.
    """
    client = _get_perplexity_client()
    
    messages = [
        {
            "role": "system",
            "content": (
                "Provide concrete numbers and facts. If unavailable, estimate based on related information. "
                "The response must be in plain text only without tables."
            ),
        },
        {"role": "user", "content": query},
    ]
    
    for attempt in range(max_retries):
        try:
            log.info("Perplexity request (attempt %d/%d): %s", attempt + 1, max_retries, query[:100])
            
            # Синхронный вызов вместо асинхронного
            response = client.invoke(messages)  # <-- invoke, не ainvoke
            
            log.info("Request successful: %s...", query[:100])
            return response.content
            
        except Exception as e:
            log.warning("Error (attempt %d/%d): %s", attempt + 1, max_retries, e)
            if attempt < max_retries - 1:
                import time
                log.info("Waiting %d seconds...", RETRY_DELAY_SEC)
                time.sleep(RETRY_DELAY_SEC)
            else:
                log.error("All retries exhausted for: %s", query)
                return f"⚠️ Perplexity search failed: {str(e)}"
    
    return "⚠️ Perplexity search failed."


# ----- Хэндлер инструмента (синхронный) -----
def _perplexity_search_handler(ctx: ToolContext, **kwargs) -> str:  # <-- без async
    """
    Вызывается агентом при использовании инструмента `perplexity_search`.
    """
    query = kwargs.get("query")
    if not query or not isinstance(query, str):
        return "Ошибка: не указан параметр 'query' (строка с поисковым запросом)."
    
    max_retries = kwargs.get("max_retries", DEFAULT_MAX_RETRIES)
    if not isinstance(max_retries, int) or max_retries < 1:
        max_retries = DEFAULT_MAX_RETRIES
    
    return _fetch_sync(query, max_retries)


# ----- Регистрация инструмента -----
def get_tools():
    """Возвращает список инструментов."""
    return [
        ToolEntry(
            name="perplexity_search",
            schema={
                "name": "perplexity_search",
                "description": (
                    "Выполняет поисковый запрос через Perplexity AI. "
                    "Возвращает развёрнутый ответ с фактами и числами в виде plain text. "
                    "Используй когда нужна актуальная информация из интернета. Всегда, когда используешь этот инструмент, пиши *найдено при помощи Perplexity*"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Поисковый запрос. Должен быть чётким.",
                        },
                        "max_retries": {
                            "type": "integer",
                            "description": "Количество повторных попыток (по умолчанию 3).",
                            "default": 3,
                        },
                    },
                    "required": ["query"],
                },
            },
            handler=_perplexity_search_handler,  # <-- синхронный хэндлер
            is_code_tool=False,
            timeout_sec=90,
        )
    ]