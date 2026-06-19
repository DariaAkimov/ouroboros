"""
Инструмент для форматирования новостей и получения текущей даты.
"""

import logging
from datetime import datetime
from typing import List, Dict

from ouroboros.tools.registry import ToolContext, ToolEntry

log = logging.getLogger(__name__)


def get_date() -> str:
    """Возвращает текущую дату в формате 'день месяц год'."""
    months = {
        1: "января", 2: "февраля", 3: "марта", 4: "апреля",
        5: "мая", 6: "июня", 7: "июля", 8: "августа",
        9: "сентября", 10: "октября", 11: "ноября", 12: "декабря"
    }

    now = datetime.now()
    day = now.day
    month = months[now.month]
    year = now.year
    
    return f"{day} {month} {year}"


def format_news(news_array: List[Dict]) -> str:
    """
    Форматирует массив из 5 новостей в читаемый текст для отправки в телеграмм группу "Топ 5 новостей каждый день".

    Args:
        news_array: список из 5 словарей вида:
            {
                "title": "title text",
                "original": "https://...",
                "translation": "https://..." или ""
            }
    
    Returns:
        str: отформатированная строка с новостями
    """
    # Проверка на количество элементов
    if len(news_array) != 5:
        raise ValueError("Массив должен содержать ровно 5 элементов")
    
    # Эмодзи для каждого пункта
    emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
    
    result = []
    result.append(f"Новости | {get_date()}")
    result.append("")
    
    for i, item in enumerate(news_array):
        # Проверка структуры словаря
        if not all(key in item for key in ["title", "original", "translation"]):
            raise ValueError(f"Словарь {i+1} имеет неверную структуру")
        
        title = item["title"]
        original = item["original"]
        translation = item["translation"]
        
        # Формируем строку для каждого пункта
        line = f"{emojis[i]}\n{title}"
        result.append(line)
        
        # Добавляем ссылки
        link_parts = []
        if original:
            link_parts.append(f"<a href='{original}'>🔗 Оригинал</a>")
        if translation:
            link_parts.append(f"<a href='{translation}'>📄 Перевод</a>")

        if link_parts:
            result.append(" | ".join(link_parts))
                
        result.append("")  # Пустая строка между новостями
    
    return "\n".join(result)


# ----- Хэндлер инструмента (синхронный) -----
def _format_news_handler(ctx: ToolContext, **kwargs) -> str:
    """
    Вызывается агентом при использовании инструмента `format_news`.
    """
    news_array = kwargs.get("news_array")
    
    if not news_array:
        return "Ошибка: не указан параметр 'news_array' (массив новостей)."
    
    if not isinstance(news_array, list):
        return "Ошибка: 'news_array' должен быть списком."
    
    try:
        return format_news(news_array)
    except ValueError as e:
        return f"Ошибка форматирования: {str(e)}"
    except Exception as e:
        log.error("Ошибка в format_news: %s", e)
        return f"⚠️ Не удалось отформатировать новости: {str(e)}"


# ----- Хэндлер для получения даты -----
def _get_date_handler(ctx: ToolContext, **kwargs) -> str:
    """
    Вызывается агентом при использовании инструмента `get_current_date`.
    """
    return get_date()


# ----- Регистрация инструментов -----
def get_tools():
    """Возвращает список инструментов."""
    return [
        ToolEntry(
            name="format_news",
            schema={
                "name": "format_news",
                "description": (
                    "Форматирует массив из 5 новостей в читаемый текст для отправки в Telegram. "
                    "Каждая новость должна содержать заголовок, ссылку на оригинал и ссылку на перевод. "
                    "Возвращает отформатированный текст с эмодзи и датой."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "news_array": {
                            "type": "array",
                            "description": "Массив из 5 словарей с новостями. Каждый словарь должен содержать ключи: 'title' (строка), 'original' (строка URL), 'translation' (строка URL или пустая строка).",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "title": {"type": "string"},
                                    "original": {"type": "string"},
                                    "translation": {"type": "string"}
                                },
                                "required": ["title", "original", "translation"]
                            },
                            "minItems": 5,
                            "maxItems": 5
                        }
                    },
                    "required": ["news_array"],
                },
            },
            handler=_format_news_handler,
            is_code_tool=False,
            timeout_sec=30,
        ),
        ToolEntry(
            name="get_current_date",
            schema={
                "name": "get_current_date",
                "description": (
                    "Возвращает текущую дату в формате 'день месяц год' на русском языке. "
                    "Например: '15 июня 2026'."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
            handler=_get_date_handler,
            is_code_tool=False,
            timeout_sec=5,
        )
    ]