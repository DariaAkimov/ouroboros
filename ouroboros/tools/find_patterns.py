"""
Тул ``find_patterns`` — разведочный анализ для «дай неожиданный инсайт»/сегментации.

method=correlate — значимые корреляции (|r|≥0.3) между признаками («не причинность»).
method=cluster — KMeans-архетипы по нормированным признакам (фиксированный seed).
РЕЗУЛЬТАТ ВСЕГДА помечен как гипотеза, требующая проверки человеком (H.2). Обёртка над
``analysis.find_patterns``.
"""

import logging

from ._common import envelope, ToolContext, ToolEntry

import analysis as A

log = logging.getLogger(__name__)


def handler(ctx: ToolContext, **kwargs) -> str:
    method = kwargs.get("method", "correlate")
    try:
        res = A.find_patterns(method=method, variables=kwargs.get("variables"),
                              scope_filters=kwargs.get("scope_filters"),
                              n_clusters=int(kwargs.get("n_clusters", 4)), ctx=ctx)
        return envelope(res, data_gaps=["Разведочный результат — гипотеза, требует проверки человеком (H.2)."])
    except Exception as e:  # pragma: no cover
        log.error("find_patterns: %s", e)
        return f"⚠️ Не удалось выполнить разведочный анализ: {e}"


SCHEMA = {
    "name": "find_patterns",
    "description": "Разведочный анализ для «дай неожиданный инсайт»/сегментации. "
                   "method=correlate — значимые корреляции (|r|≥0.3) между признаками "
                   "(с оговоркой «не причинность»). method=cluster — KMeans-архетипы по "
                   "нормированным признакам (фиксированный seed). РЕЗУЛЬТАТ ВСЕГДА помечен как "
                   "гипотеза, требующая проверки человеком.",
    "parameters": {"type": "object", "properties": {
        "method": {"type": "string", "enum": ["correlate", "cluster"],
                   "description": "Метод разведки."},
        "variables": {"type": "array", "items": {"type": "string"},
                      "description": "Признаки для анализа (необязательно)."},
        "scope_filters": {"type": "object", "description": "Ограничить выборку (как в find_population)."},
        "n_clusters": {"type": "integer", "description": "Число кластеров (для cluster, по умолчанию 4)."}},
        "required": ["method"]},
}

TOOL = ToolEntry(name="find_patterns", schema=SCHEMA, handler=handler,
                 is_code_tool=False, timeout_sec=60)
