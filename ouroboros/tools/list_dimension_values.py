"""
Тул ``list_dimension_values`` — масштабонезависимое обнаружение справочников.

Возвращает фактические значения измерения (блок/ТБ/роль/грейд/пол/…) и их частоты
ИЗ ДАННЫХ, а не из зашитых перечней. Тонкая обёртка над ``data_loader.distinct_values``.
"""

import logging

from ._common import envelope, ToolContext, ToolEntry

import data_loader as dl

log = logging.getLogger(__name__)

# Дружелюбные алиасы измерений → (фактическое поле, лист). Не источник истины о
# значениях: сами значения всегда берутся из данных distinct_values().
_DIMENSION_MAP = {
    "блок": ("Функциональный блок", dl.SHEET_PROFILE),
    "функциональный блок": ("Функциональный блок", dl.SHEET_PROFILE),
    "тб": ("ЦА\\ТБ\\ПЦП", dl.SHEET_PROFILE),
    "ца/тб": ("ЦА\\ТБ\\ПЦП", dl.SHEET_PROFILE),
    "география": ("ЦА\\ТБ\\ПЦП", dl.SHEET_PROFILE),
    "роль": ("Роль", dl.SHEET_PROFILE),
    "грейд": ("Грейд", dl.SHEET_PROFILE),
    "режим работы": ("режим работы (офис, гибрид, удаленный)", dl.SHEET_PROFILE),
    "режим": ("режим работы (офис, гибрид, удаленный)", dl.SHEET_PROFILE),
    "пол": ("Пол", dl.SHEET_PROFILE),
    "работодатель_до_сбера": ("Место работы до Сбера", dl.SHEET_PROFILE),
    "работодатель до сбера": ("Место работы до Сбера", dl.SHEET_PROFILE),
}


def handler(ctx: ToolContext, **kwargs) -> str:
    dim = kwargs.get("dimension")
    if not dim:
        return envelope(None, ok=False,
                        data_gaps=["Не указан параметр 'dimension'."])
    try:
        key = dl.normalize_header(dim).lower()
        if key in _DIMENSION_MAP:
            field, sheet = _DIMENSION_MAP[key]
        else:
            field, sheet = dim, kwargs.get("sheet", dl.SHEET_PROFILE)
        values = dl.distinct_values(field, sheet=sheet, ctx=ctx)
        items = [{"value": k, "count": v} for k, v in values.items()]
        return envelope({"dimension": dim, "field": field, "sheet": sheet,
                         "values": items, "total": sum(values.values()),
                         "distinct": len(items)})
    except KeyError as e:
        return envelope(None, ok=False, data_gaps=[str(e)])
    except Exception as e:  # pragma: no cover
        log.error("list_dimension_values: %s", e)
        return f"⚠️ Не удалось получить значения справочника: {e}"


SCHEMA = {
    "name": "list_dimension_values",
    "description": "Масштабонезависимое обнаружение справочников: возвращает фактические "
                   "значения измерения и их частоты ИЗ ДАННЫХ (не из зашитых перечней). "
                   "Вызывайте ВМЕСТО опоры на память о блоках/ролях/ТБ. "
                   "dimension ∈ {блок, ТБ, роль, грейд, режим работы, пол, "
                   "работодатель_до_Сбера, …} или точное имя поля.",
    "parameters": {"type": "object", "properties": {
        "dimension": {"type": "string", "description": "Измерение/поле справочника."},
        "sheet": {"type": "string", "description": "Лист (по умолчанию «профиль»)."}},
        "required": ["dimension"]},
}

TOOL = ToolEntry(name="list_dimension_values", schema=SCHEMA, handler=handler,
                 is_code_tool=False, timeout_sec=10)
