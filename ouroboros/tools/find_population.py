"""
Тул ``find_population`` — когортный фильтр популяции по структурным критериям и
порогам признаков (масштабонезависимо).

Структурные критерии (block, tb, grade, role_family, prior_sector, has_degree,
language_min, gender …) и пороги ('<признак>_min'/'<признак>_max') передаются в
объекте filters. Пол помечается этическим флагом (Часть L). Тонкая обёртка над
``analysis.filter_population``.
"""

import logging

from ._common import envelope, ToolContext, ToolEntry

import analysis as A

log = logging.getLogger(__name__)


def handler(ctx: ToolContext, **kwargs) -> str:
    filters = kwargs.get("filters")
    if filters is None:
        # Допустить плоскую передачу критериев (без обёртки filters).
        filters = {k: v for k, v in kwargs.items() if k not in ("sections",)}
    if not isinstance(filters, dict):
        return envelope(None, ok=False, data_gaps=["Параметр 'filters' должен быть объектом."])
    try:
        res = A.filter_population(filters, ctx)
        assumptions = []
        if "block" in res["applied_filters"] and filters.get("block") not in (
                None, res["applied_filters"]["block"]):
            assumptions.append(f"Блок «{filters.get('block')}» сопоставлен с «{res['applied_filters']['block']}».")
        return envelope({"count": res["count"], "applied_filters": res["applied_filters"],
                         "results": res["results"]},
                        assumptions=assumptions + res.get("ethics_flags", []))
    except Exception as e:  # pragma: no cover
        log.error("find_population: %s", e)
        return f"⚠️ Не удалось отфильтровать популяцию: {e}"


SCHEMA = {
    "name": "find_population",
    "description": "Когортный фильтр популяции по структурным критериям и порогам признаков. "
                   "Масштабонезависимо. Структурные: block, tb, grade/grades, role_family, "
                   "role_contains, prior_sector, has_degree, external_hire, work_mode, "
                   "language_min (CEFR-ординал по англ.: A1=1…C2=6), gender (пол — только "
                   "как явный критерий, помечается этикой). Пороги: любые '<признак>_min' / "
                   "'<признак>_max', напр. impact_econ_min, tenure_role_min, "
                   "result_b_share_min, sberq4_min, awards_min. Возвращает {count, "
                   "applied_filters, results: [{tn, ФИО, блок, роль, грейд, значения_фильтра}]}.",
    "parameters": {"type": "object", "properties": {
        "filters": {"type": "object", "description": "Объект критериев и порогов (см. описание)."}},
        "required": ["filters"]},
}

TOOL = ToolEntry(name="find_population", schema=SCHEMA, handler=handler,
                 is_code_tool=False, timeout_sec=30)
