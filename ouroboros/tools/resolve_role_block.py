"""
Тул ``resolve_role_block`` — сопоставление роли/блока/англоназвания должности с
фактическими сущностями данных.

Реализует протокол «нет совпадения»: для отсутствующего блока (например «Финансы»)
НЕ подменяет молча — возвращает notes/alternatives и needs_clarification, фиксирует
допущение в assumptions. Тонкая обёртка над ``resolve.resolve_role_block``.
"""

import logging

from ._common import envelope, ToolContext, ToolEntry

import resolve as R

log = logging.getLogger(__name__)


def handler(ctx: ToolContext, **kwargs) -> str:
    role_query = kwargs.get("role_query")
    block_query = kwargs.get("block_query") or kwargs.get("block")
    if not role_query and not block_query:
        return envelope(None, ok=False,
                        data_gaps=["Укажите 'role_query' и/или 'block_query'."])
    try:
        rb = R.resolve_role_block(role_query=role_query, block_query=block_query, ctx=ctx)
        return envelope({"resolved_block": rb["resolved_block"],
                         "resolved_role_family": rb["resolved_role_family"],
                         "candidate_roles": rb["candidate_roles"],
                         "alternatives": rb["alternatives"],
                         "actual_blocks": rb["actual_blocks"]},
                        assumptions=rb["assumptions"] + rb["notes"],
                        needs_clarification=rb["needs_clarification"])
    except Exception as e:  # pragma: no cover
        log.error("resolve_role_block: %s", e)
        return f"⚠️ Не удалось разрешить роль/блок: {e}"


SCHEMA = {
    "name": "resolve_role_block",
    "description": "Сопоставляет роль/блок/англоязычное название должности (chief data "
                   "scientist, CISO, CFO…) с фактическими сущностями данных. Реализует "
                   "протокол «нет совпадения»: для отсутствующего блока (например «Финансы») "
                   "НЕ подменяет молча — возвращает notes/alternatives и "
                   "needs_clarification, фиксирует допущение в assumptions.",
    "parameters": {"type": "object", "properties": {
        "role_query": {"type": "string", "description": "Целевая роль/должность (любым языком)."},
        "block_query": {"type": "string", "description": "Функциональный блок (формулировка запроса)."}},
        "required": []},
}

TOOL = ToolEntry(name="resolve_role_block", schema=SCHEMA, handler=handler,
                 is_code_tool=False, timeout_sec=10)
