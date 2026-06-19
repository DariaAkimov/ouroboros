"""
Инструмент для надёжной отправки сообщений в группу «Топ 5 новостей каждый день».
Прямой HTTP-запрос к Telegram Bot API — без supervisor-пайплайна, минимум точек отказа.

Особенности:
- HTML-форматирование (жирный, курсив, ссылки)
- Автоматический чанкинг для длинных сообщений (>3800 символов)
- Fallback на plain text при ошибке HTML-парсинга
- Поддержка переменной окружения GROUP_CHAT_ID (по умолчанию -1003701969558)
"""

import logging
import os
from typing import Optional

import requests

from ouroboros.tools.registry import ToolContext, ToolEntry

log = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"
CHUNK_SIZE = 3800  # Telegram limit is 4096, leave margin


def _get_bot_token() -> Optional[str]:
    """Получает токен бота из переменных окружения."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        log.error("TELEGRAM_BOT_TOKEN не задан в переменных окружения")
        return None
    return token


def _get_chat_id() -> str:
    """Получает ID группы из переменных окружения или возвращает дефолтный."""
    return os.environ.get("GROUP_CHAT_ID", "-1003701969558")


def _send_single(text: str, token: str, chat_id: str, parse_mode: str = "HTML") -> dict:
    """Отправляет одно сообщение в Telegram. Возвращает JSON-ответ."""
    url = f"{TELEGRAM_API}/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": False,
    }
    resp = requests.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _chunk_text(text: str, max_size: int = CHUNK_SIZE) -> list:
    """
    Разбивает текст на чанки, стараясь резать по границам абзацев.
    Если абзац слишком длинный — режет по пробелам.
    """
    if len(text) <= max_size:
        return [text]

    chunks = []
    paragraphs = text.split("\n\n")
    current = ""

    for para in paragraphs:
        para_with_sep = para if not current else "\n\n" + para

        if len(current) + len(para_with_sep) <= max_size:
            current += para_with_sep
        else:
            if current:
                chunks.append(current)
            # Если один абзац больше чанка — режем по пробелам
            if len(para) > max_size:
                words = para.split(" ")
                sub_chunk = ""
                for word in words:
                    candidate = word if not sub_chunk else sub_chunk + " " + word
                    if len(candidate) <= max_size:
                        sub_chunk = candidate
                    else:
                        chunks.append(sub_chunk)
                        sub_chunk = word
                if sub_chunk:
                    current = sub_chunk
            else:
                current = para

    if current:
        chunks.append(current)

    return chunks


def send_to_group(text: str) -> str:
    """
    Отправляет сообщение в группу «Топ 5 новостей каждый день».

    Args:
        text: текст сообщения (может содержать HTML-теги:
              <a href='...'>, <b>, <i>, <u>, <s>, <code>, <pre>)

    Returns:
        str: статус отправки с message_id или сообщение об ошибке
    """
    token = _get_bot_token()
    if not token:
        return "Ошибка: TELEGRAM_BOT_TOKEN не задан"

    chat_id = _get_chat_id()

    if not text or not text.strip():
        return "Ошибка: текст сообщения пуст"

    try:
        # Пробуем отправить с HTML
        chunks = _chunk_text(text)
        message_ids = []

        for i, chunk in enumerate(chunks):
            try:
                result = _send_single(chunk, token, chat_id, parse_mode="HTML")
                msg_id = result.get("result", {}).get("message_id")
                if msg_id:
                    message_ids.append(str(msg_id))
                    log.info("Чанк %d/%d отправлен, message_id=%s", i + 1, len(chunks), msg_id)
            except requests.HTTPError as e:
                # HTML не распарсился — пробуем plain text
                if "can't parse entities" in str(e).lower():
                    log.warning("HTML не распарсился, отправляю plain text (чанк %d)", i + 1)
                    result = _send_single(chunk, token, chat_id, parse_mode="")
                    msg_id = result.get("result", {}).get("message_id")
                    if msg_id:
                        message_ids.append(str(msg_id))
                else:
                    raise

        if message_ids:
            return f"ok, message_ids={','.join(message_ids)}"
        else:
            return "Ошибка: сообщение отправлено, но message_id не получен"

    except requests.HTTPError as e:
        log.error("HTTP ошибка при отправке в Telegram: %s", e)
        try:
            err_detail = e.response.json().get("description", str(e))
        except Exception:
            err_detail = str(e)
        return f"⚠️ Ошибка отправки: {err_detail}"
    except requests.RequestException as e:
        log.error("Сетевая ошибка: %s", e)
        return f"⚠️ Сетевая ошибка: {str(e)}"
    except Exception as e:
        log.error("Неожиданная ошибка в send_to_group: %s", e)
        return f"⚠️ Ошибка: {str(e)}"


# ----- Хэндлер инструмента -----
def _send_to_group_handler(ctx: ToolContext, **kwargs) -> str:
    """
    Вызывается агентом при использовании инструмента `send_to_group`.
    """
    text = kwargs.get("text", "")

    if not text:
        return "Ошибка: не указан параметр 'text' (текст для отправки)"

    if not isinstance(text, str):
        return "Ошибка: 'text' должен быть строкой"

    return send_to_group(text)


# ----- Регистрация инструмента -----
def get_tools():
    """Возвращает список инструментов."""
    return [
        ToolEntry(
            name="send_to_group",
            schema={
                "name": "send_to_group",
                "description": (
                    "Отправляет сообщение в группу «Топ 5 новостей каждый день» напрямую "
                    "через Telegram Bot API. Поддерживает HTML-форматирование: "
                    "<a href='...'>ссылка</a>, <b>жирный</b>, <i>курсив</i>. "
                    "Автоматически разбивает длинные сообщения на части. "
                    "Используй этот инструмент КАЖДЫЙ раз после format_news, "
                    "чтобы доставить дайджест в группу."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": (
                                "Текст для отправки в группу. Может содержать HTML-теги. "
                                "Используй результат format_news как значение этого параметра."
                            )
                        }
                    },
                    "required": ["text"]
                }
            },
            handler=_send_to_group_handler,
            is_code_tool=False,
            timeout_sec=60,
        )
    ]
