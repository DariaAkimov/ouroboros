"""
Инструмент send_to_group — прямая отправка сообщений в Telegram группу через Bot API.

Обходит supervisor-пайплайн: HTTP POST напрямую к api.telegram.org.
Минимум точек отказа. Чанкинг, HTML-форматирование, fallback на plain text.
"""

from __future__ import annotations

import logging
import os
import re
from typing import List

import requests

from ouroboros.tools.registry import ToolContext, ToolEntry

log = logging.getLogger(__name__)

# Telegram message limit
TELEGRAM_MAX_LENGTH = 4096
# Safe chunk size with margin for HTML entities
CHUNK_SIZE = 3800


def _strip_html(text: str) -> str:
    """Remove HTML tags, leaving only plain text."""
    return re.sub(r"<[^>]+>", "", text)


def _send_chunk(bot_token: str, chat_id: str, text: str, parse_mode: str = "HTML") -> dict:
    """Send a single chunk to Telegram. Returns JSON response."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": False,
    }
    resp = requests.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


def send_to_group(text: str, chat_id: str | None = None) -> str:
    """
    Отправляет текст в Telegram-группу.

    Args:
        text: текст для отправки (может содержать HTML-теги)
        chat_id: ID чата (по умолчанию GROUP_CHAT_ID из env или -1003701969558)

    Returns:
        str: статус отправки с message_id
    """
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        return "❌ TELEGRAM_BOT_TOKEN не найден в переменных окружения"

    group_id = chat_id or os.environ.get("GROUP_CHAT_ID", "-1003701969558")

    # Разбиваем на чанки, если текст слишком длинный
    if len(text) <= TELEGRAM_MAX_LENGTH:
        chunks = [text]
    else:
        chunks = []
        remaining = text
        while remaining:
            if len(remaining) <= CHUNK_SIZE:
                chunks.append(remaining)
                break
            # Ищем ближайший перенос строки перед CHUNK_SIZE
            split_at = remaining.rfind("\n", 0, CHUNK_SIZE)
            if split_at == -1:
                split_at = CHUNK_SIZE
            chunks.append(remaining[:split_at])
            remaining = remaining[split_at:].lstrip("\n")

    message_ids = []
    for i, chunk in enumerate(chunks):
        try:
            # Пробуем HTML
            resp = _send_chunk(bot_token, group_id, chunk, parse_mode="HTML")
            if resp.get("ok"):
                msg_id = resp["result"]["message_id"]
                message_ids.append(msg_id)
                continue
        except Exception as e:
            log.warning("HTML send failed for chunk %d: %s", i, e)

        # Fallback: plain text
        try:
            plain = _strip_html(chunk)
            resp = _send_chunk(bot_token, group_id, plain, parse_mode="")
            if resp.get("ok"):
                msg_id = resp["result"]["message_id"]
                message_ids.append(msg_id)
                log.info("Chunk %d sent as plain text (message_id=%d)", i, msg_id)
            else:
                return f"❌ Telegram API error: {resp}"
        except Exception as e:
            return f"❌ Failed to send chunk {i}: {e}"

    return f"✅ Отправлено в чат {group_id}, message_ids = {message_ids}"


# ----- Хэндлер инструмента -----
def _send_to_group_handler(ctx: ToolContext, **kwargs) -> str:
    text = kwargs.get("text", "")
    if not text:
        return "❌ Не указан параметр 'text'"

    chat_id = kwargs.get("chat_id")
    try:
        return send_to_group(text=text, chat_id=chat_id)
    except Exception as e:
        log.error("send_to_group failed: %s", e)
        return f"❌ Ошибка отправки: {e}"


# ----- Регистрация -----
def get_tools():
    return [
        ToolEntry(
            name="send_to_group",
            schema={
                "name": "send_to_group",
                "description": (
                    "Отправить сообщение в Telegram-группу напрямую через Bot API. "
                    "Поддерживает HTML-форматирование (<a href='...'>, <b>, <i>), "
                    "автоматический чанкинг длинных сообщений и fallback на plain text при ошибке HTML. "
                    "Не зависит от supervisor-пайплайна."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "Текст сообщения (может содержать HTML-теги)",
                        },
                        "chat_id": {
                            "type": "string",
                            "description": "ID чата (по умолчанию -1003701969558 — группа «Топ 5 новостей каждый день»)",
                        },
                    },
                    "required": ["text"],
                },
            },
            handler=_send_to_group_handler,
            is_code_tool=False,
            timeout_sec=30,
        )
    ]
