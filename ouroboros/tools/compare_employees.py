"""
Тул ``compare_employees`` — сравнение нескольких сотрудников по измерениям.

Показывает, кто в чём лидирует, с конкретными значениями. По умолчанию измерения:
импакт, компетенции, доля B, награды, стаж, курсы, скорость роста. Обёртка над
``analysis.compare_employees``.
"""

import logging

from ._common import envelope, ToolContext, ToolEntry

import analysis as A

log = logging.getLogger(__name__)


def handler(ctx: ToolContext, **kwargs) -> str:
    tns = kwargs.get("tns")
    if not tns or not isinstance(tns, list) or len(tns) < 2:
        return envelope(None, ok=False, data_gaps=["Укажите 'tns' — список из ≥2 табельных номеров."])
    try:
        res = A.compare_employees([int(t) for t in tns], dimensions=kwargs.get("dimensions"), ctx=ctx)
        return envelope(res)
    except Exception as e:  # pragma: no cover
        log.error("compare_employees: %s", e)
        return f"⚠️ Не удалось сравнить сотрудников: {e}"


SCHEMA = {
    "name": "compare_employees",
    "description": "Сравнивает нескольких сотрудников по выбранным измерениям и показывает, "
                   "кто в чём лидирует, с конкретными значениями. По умолчанию измерения: "
                   "импакт, компетенции, доля B, награды, стаж, курсы, скорость роста.",
    "parameters": {"type": "object", "properties": {
        "tns": {"type": "array", "items": {"type": "integer"},
                "description": "Список ≥2 табельных номеров."},
        "dimensions": {"type": "array", "items": {"type": "string"},
                       "description": "Имена признаков для сравнения (необязательно)."}},
        "required": ["tns"]},
}

TOOL = ToolEntry(name="compare_employees", schema=SCHEMA, handler=handler,
                 is_code_tool=False, timeout_sec=30)
