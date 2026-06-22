"""
Тул ``analyze_evaluation_trend`` — динамика оценок сотрудника за 5 лет.

Квартальный (Q1–Q4) и годовой (Y) ряды РАЗДЕЛЬНО (К4). Ординал B=3, C=2, D=1;
направление (наклон), волатильность, последнее значение. Домены: результат {B,C,D},
ценности {B,C}. Обёртка над ``analysis.analyze_evaluation_trend``.
"""

import logging

from ._common import envelope, ToolContext, ToolEntry

import analysis as A

log = logging.getLogger(__name__)


def handler(ctx: ToolContext, **kwargs) -> str:
    tn = kwargs.get("tn")
    if tn is None:
        return envelope(None, ok=False, data_gaps=["Не указан параметр 'tn'."])
    try:
        res = A.analyze_evaluation_trend(int(tn), ctx)
        if not res.get("found"):
            return envelope(res, data_gaps=res.get("data_gaps", []))
        return envelope(res, data_gaps=["Q-ряд и Y-ряд не смешиваются (К4); домены: результат {B,C,D}, ценности {B,C}."])
    except Exception as e:  # pragma: no cover
        log.error("analyze_evaluation_trend: %s", e)
        return f"⚠️ Не удалось проанализировать тренд оценок: {e}"


SCHEMA = {
    "name": "analyze_evaluation_trend",
    "description": "Динамика оценок за 5 лет по сотруднику. Квартальный (Q1–Q4) и годовой (Y) "
                   "ряды РАЗДЕЛЬНО (К4). Ординал B=3,C=2,D=1; направление (наклон), "
                   "волатильность, последнее значение. Домены: результат {B,C,D}, ценности {B,C}.",
    "parameters": {"type": "object", "properties": {
        "tn": {"type": "integer", "description": "Табельный номер."}},
        "required": ["tn"]},
}

TOOL = ToolEntry(name="analyze_evaluation_trend", schema=SCHEMA, handler=handler,
                 is_code_tool=False, timeout_sec=15)
