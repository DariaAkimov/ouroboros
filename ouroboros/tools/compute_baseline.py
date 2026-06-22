"""
Тул ``compute_baseline`` — базовая линия (распределение) метрик по когорте.

Нужна для контекстуализации/нормализации: нельзя судить «лучше/хуже» без группы
сравнения (Часть F). Когорта задаётся cohort_tns ЛИБО filters. По каждой метрике —
n, mean, median, перцентили p10…p90, min, max. Обёртка над
``analysis.compute_baseline``.
"""

import logging

from ._common import envelope, ToolContext, ToolEntry

import analysis as A

log = logging.getLogger(__name__)


def handler(ctx: ToolContext, **kwargs) -> str:
    metrics = kwargs.get("metrics")
    if not metrics:
        return envelope(None, ok=False, data_gaps=["Не указан параметр 'metrics' (список метрик)."])
    if isinstance(metrics, str):
        metrics = [metrics]
    try:
        res = A.compute_baseline(metrics, cohort_tns=kwargs.get("cohort_tns"),
                                 filters=kwargs.get("filters"), ctx=ctx)
        gaps = ["Когорта мала (<5) — выводы о ранжировании ненадёжны."] if res["cohort_size"] < 5 else []
        return envelope(res, data_gaps=gaps)
    except Exception as e:  # pragma: no cover
        log.error("compute_baseline: %s", e)
        return f"⚠️ Не удалось вычислить базовую линию: {e}"


SCHEMA = {
    "name": "compute_baseline",
    "description": "Базовая линия (распределение) метрик по когорте — для контекстуализации/"
                   "нормализации (нельзя судить «лучше/хуже» без группы сравнения, Часть F). "
                   "Задаётся cohort_tns ЛИБО filters. По каждой метрике: n, mean, median, "
                   "p10/p25/p50/p75/p90, min, max.",
    "parameters": {"type": "object", "properties": {
        "metrics": {"type": "array", "items": {"type": "string"},
                    "description": "Список метрик (например ['impact_econ_total','sberq4_avg'])."},
        "cohort_tns": {"type": "array", "items": {"type": "integer"},
                       "description": "Явная когорта (табельные номера)."},
        "filters": {"type": "object", "description": "Альтернатива: критерии когорты (как в find_population)."}},
        "required": ["metrics"]},
}

TOOL = ToolEntry(name="compute_baseline", schema=SCHEMA, handler=handler,
                 is_code_tool=False, timeout_sec=30)
