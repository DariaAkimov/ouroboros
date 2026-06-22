"""
Тул ``resolve_person`` — разрешение человека по ФИО/табельному номеру в ``tn``.

При омонимах возвращает несколько кандидатов с дизамбигуаторами и
``needs_clarification=true`` — НЕ угадывает одного молча (Часть G, анти-галлюцинации).
Тонкая обёртка над ``resolve.resolve_person``.
"""

import logging

from ._common import envelope, ToolContext, ToolEntry

import resolve as R

log = logging.getLogger(__name__)


def handler(ctx: ToolContext, **kwargs) -> str:
    query = kwargs.get("query")
    if not query:
        return envelope(None, ok=False, data_gaps=["Не указан параметр 'query' (ФИО или табельный номер)."])
    try:
        res = R.resolve_person(query, ctx=ctx, block=kwargs.get("block"), role=kwargs.get("role"),
                               tb=kwargs.get("tb"), grade=kwargs.get("grade"))
        gaps = [] if res["found"] else [res["message"]]
        return envelope({"query": query, "found": res["found"], "resolved": res["resolved"],
                         "candidates": res["candidates"],
                         "applied_disambiguators": res.get("applied_disambiguators", {})},
                        needs_clarification=res["needs_clarification"], data_gaps=gaps,
                        extra={"message": res["message"]})
    except Exception as e:  # pragma: no cover
        log.error("resolve_person: %s", e)
        return f"⚠️ Не удалось разрешить человека: {e}"


SCHEMA = {
    "name": "resolve_person",
    "description": "Разрешает человека по ФИО (полному/частичному/фамилии) или табельному "
                   "номеру в табельный номер (tn). При омонимах возвращает несколько "
                   "кандидатов с дизамбигуаторами (блок/роль/грейд/ТБ) и "
                   "needs_clarification=true — НЕ угадывает одного молча. Если не найден — "
                   "сообщает об этом без выдуманного профиля.",
    "parameters": {"type": "object", "properties": {
        "query": {"type": "string", "description": "ФИО или табельный номер."},
        "block": {"type": "string", "description": "Уточнение: функциональный блок."},
        "role": {"type": "string", "description": "Уточнение: роль (подстрока)."},
        "tb": {"type": "string", "description": "Уточнение: ЦА/территориальный банк."},
        "grade": {"type": "integer", "description": "Уточнение: грейд."}},
        "required": ["query"]},
}

TOOL = ToolEntry(name="resolve_person", schema=SCHEMA, handler=handler,
                 is_code_tool=False, timeout_sec=10)
