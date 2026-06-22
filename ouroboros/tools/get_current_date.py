"""
Тул ``get_current_date`` — текущая дата на русском.

Тривиальный тул (не «датовый»): возвращает простую строку, а не конверт §4.
Полезен для расчёта свежести наград/курсов/повышений.
"""

from datetime import datetime

from ._common import ToolContext, ToolEntry

_MONTHS = {1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня",
           7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября", 12: "декабря"}


def handler(ctx: ToolContext, **kwargs) -> str:
    now = datetime.now()
    return f"{now.day} {_MONTHS[now.month]} {now.year}"


SCHEMA = {
    "name": "get_current_date",
    "description": "Возвращает текущую дату на русском (например «20 июня 2026»). "
                   "Полезно для расчёта свежести наград/курсов/повышений.",
    "parameters": {"type": "object", "properties": {}, "required": []},
}

TOOL = ToolEntry(name="get_current_date", schema=SCHEMA, handler=handler,
                 is_code_tool=False, timeout_sec=5)
