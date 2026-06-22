"""
Тул ``score_candidates`` — ГЛАВНЫЙ тул. Ранжирует кандидатов под целевую роль по
многоисточниковой модели Fit/Readiness (Часть I).

Разрешает роль/блок, собирает лонг-лист, при отсутствии паутинок/оценок у кандидата
переходит в режим «только профиль». Возвращает шорт-лист с пофакторной разбивкой и
доказательствами на каждого (tn, конкретные достижения/баллы) и уровнем готовности.
Обёртка над ``analysis.score_candidates``.
"""

import logging

from ._common import envelope, ToolContext, ToolEntry

import analysis as A

log = logging.getLogger(__name__)


def handler(ctx: ToolContext, **kwargs) -> str:
    role_query = kwargs.get("role_query")
    if not role_query and not kwargs.get("cohort_tns") and not kwargs.get("filters"):
        return envelope(None, ok=False,
                        data_gaps=["Укажите 'role_query' (целевая роль/семейство) либо когорту/фильтры."])
    try:
        res = A.score_candidates(role_query=role_query, block=kwargs.get("block"),
                                 cohort_tns=kwargs.get("cohort_tns"), filters=kwargs.get("filters"),
                                 top_n=int(kwargs.get("top_n", 10)),
                                 weights_override=kwargs.get("weights_override"), ctx=ctx)
        evidence = [{"tn": c["tn"], "ФИО": c["ФИО"], "fit": c["fit_score"],
                     "доказательства": c["доказательства"]} for c in res["shortlist"]]
        return envelope({"target_role": res.get("target_role"),
                         "resolved_block": res.get("resolved_block"),
                         "resolved_role_family": res.get("resolved_role_family"),
                         "weights": res.get("weights"), "long_list_size": res.get("long_list_size"),
                         "shortlist": res["shortlist"]},
                        evidence=evidence, assumptions=res.get("assumptions", []),
                        data_gaps=res.get("data_gaps", []),
                        needs_clarification=res.get("needs_clarification", False))
    except Exception as e:  # pragma: no cover
        log.error("score_candidates: %s", e)
        return f"⚠️ Не удалось выполнить скоринг кандидатов: {e}"


SCHEMA = {
    "name": "score_candidates",
    "description": "ГЛАВНЫЙ тул. Ранжирует кандидатов под целевую роль/семейство по "
                   "многоисточниковой модели Fit/Readiness (Часть I): компетенции (SberQ 4.0), "
                   "доказанный вклад (Impact Ledger, перцентиль в когорте), устойчивость "
                   "результата (доля B, отсутствие D, тренд по Y), карьерная динамика, "
                   "развитие (курсы AI/лидерство), опыт, образование, вовлечённость. Веса — "
                   "пресет по семейству. Разрешает роль/блок, собирает лонг-лист, при "
                   "отсутствии паутинок/оценок у кандидата переходит в режим «только профиль». "
                   "Возвращает шорт-лист с пофакторной разбивкой и доказательствами на каждого "
                   "(tn, конкретные достижения/баллы), уровень готовности, assumptions, data_gaps.",
    "parameters": {"type": "object", "properties": {
        "role_query": {"type": "string", "description": "Целевая роль/семейство (любым языком)."},
        "block": {"type": "string", "description": "Функциональный блок (необязательно)."},
        "cohort_tns": {"type": "array", "items": {"type": "integer"},
                       "description": "Явный лонг-лист кандидатов (необязательно)."},
        "filters": {"type": "object", "description": "Критерии лонг-листа (как в find_population)."},
        "top_n": {"type": "integer", "description": "Размер шорт-листа (по умолчанию 10)."},
        "weights_override": {"type": "object",
                             "description": "Переопределение весов факторов (необязательно)."}},
        "required": ["role_query"]},
}

TOOL = ToolEntry(name="score_candidates", schema=SCHEMA, handler=handler,
                 is_code_tool=False, timeout_sec=60)
