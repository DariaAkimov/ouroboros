"""
Реестр агентских тулов HR-ИИ-агента (`get_tools`).

Паттерн регистрации повторяет ``tool_example.py``: каждый тул — ToolEntry с
schema (function-calling), синхронным хэндлером ``_handler(ctx, **kwargs) -> str``.
Хэндлеры НЕ пробрасывают исключения: на проблему возвращают понятную строку
на русском; неожиданные ошибки логируются и возвращаются как «⚠️ Не удалось …».

«Датовые» тулы возвращают JSON-строку (json.dumps, ensure_ascii=False) в общем
конверте §4: {ok, data, evidence, assumptions, data_gaps, needs_clarification,
scale_note}. Тривиальные тулы (get_current_date) — простую строку.

Тулы — тонкие обёртки над слоями data_loader / ontology / parsers / resolve /
analysis. Вся вычислительная логика — в этих слоях.
"""

import json
import logging
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

# Гарантируем, что соседние модули скилла импортируются независимо от того,
# как фреймворк загрузил этот файл (по имени или по пути).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Контракт фреймворка: в продуктиве — настоящий ouroboros; иначе локальный стаб.
try:  # pragma: no cover
    from ouroboros.tools.registry import ToolContext, ToolEntry
except ImportError:  # pragma: no cover
    from _framework import ToolContext, ToolEntry

import numpy as np

import analysis as A
import data_loader as dl
import parsers as P
import resolve as R

log = logging.getLogger(__name__)

_SCALE_NOTE = ("Значения справочников и пороги получены из данных в рантайме, "
               "не зашиты; популяция — выборка, в проде записей больше.")


# --- Сериализация (numpy/pandas → JSON) -------------------------------------
def _json_default(o: Any):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (np.ndarray,)):
        return o.tolist()
    if isinstance(o, datetime):
        return o.strftime("%Y-%m-%d")
    return str(o)


def _envelope(data: Any, evidence: Optional[List] = None, assumptions: Optional[List] = None,
              data_gaps: Optional[List] = None, needs_clarification: bool = False,
              ok: bool = True, extra: Optional[Dict] = None) -> str:
    obj = {
        "ok": ok,
        "data": data,
        "evidence": evidence or [],
        "assumptions": assumptions or [],
        "data_gaps": data_gaps or [],
        "needs_clarification": bool(needs_clarification),
        "scale_note": _SCALE_NOTE,
    }
    if extra:
        obj.update(extra)
    return json.dumps(obj, ensure_ascii=False, default=_json_default)


# --- 1. get_current_date -----------------------------------------------------
_MONTHS = {1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня",
           7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября", 12: "декабря"}


def _get_current_date_handler(ctx: ToolContext, **kwargs) -> str:
    now = datetime.now()
    return f"{now.day} {_MONTHS[now.month]} {now.year}"


# --- 2. list_dimension_values ------------------------------------------------
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


def _list_dimension_values_handler(ctx: ToolContext, **kwargs) -> str:
    dim = kwargs.get("dimension")
    if not dim:
        return _envelope(None, ok=False,
                         data_gaps=["Не указан параметр 'dimension'."])
    try:
        key = dl.normalize_header(dim).lower()
        if key in _DIMENSION_MAP:
            field, sheet = _DIMENSION_MAP[key]
        else:
            field, sheet = dim, kwargs.get("sheet", dl.SHEET_PROFILE)
        values = dl.distinct_values(field, sheet=sheet, ctx=ctx)
        items = [{"value": k, "count": v} for k, v in values.items()]
        return _envelope({"dimension": dim, "field": field, "sheet": sheet,
                          "values": items, "total": sum(values.values()),
                          "distinct": len(items)})
    except KeyError as e:
        return _envelope(None, ok=False, data_gaps=[str(e)])
    except Exception as e:  # pragma: no cover
        log.error("list_dimension_values: %s", e)
        return f"⚠️ Не удалось получить значения справочника: {e}"


# --- 3. resolve_person -------------------------------------------------------
def _resolve_person_handler(ctx: ToolContext, **kwargs) -> str:
    query = kwargs.get("query")
    if not query:
        return _envelope(None, ok=False, data_gaps=["Не указан параметр 'query' (ФИО или табельный номер)."])
    try:
        res = R.resolve_person(query, ctx=ctx, block=kwargs.get("block"), role=kwargs.get("role"),
                               tb=kwargs.get("tb"), grade=kwargs.get("grade"))
        gaps = [] if res["found"] else [res["message"]]
        return _envelope({"query": query, "found": res["found"], "resolved": res["resolved"],
                          "candidates": res["candidates"],
                          "applied_disambiguators": res.get("applied_disambiguators", {})},
                         needs_clarification=res["needs_clarification"], data_gaps=gaps,
                         extra={"message": res["message"]})
    except Exception as e:  # pragma: no cover
        log.error("resolve_person: %s", e)
        return f"⚠️ Не удалось разрешить человека: {e}"


# --- 4. get_employee_profile -------------------------------------------------
def _get_employee_profile_handler(ctx: ToolContext, **kwargs) -> str:
    tn = kwargs.get("tn")
    if tn is None:
        return _envelope(None, ok=False,
                         data_gaps=["Не указан параметр 'tn' (табельный номер). Сначала используйте resolve_person."])
    try:
        tn = int(tn)
    except (ValueError, TypeError):
        return _envelope(None, ok=False, data_gaps=[f"Некорректный табельный номер: {tn!r}."])
    try:
        bf = A.build_features(tn, ctx)
        if not bf["found"]:
            return _envelope({"tn": tn, "found": False}, ok=True,
                             data_gaps=bf["data_gaps"],
                             extra={"message": f"Профиль {tn} не найден."})
        feats = bf["features"]
        sections = kwargs.get("sections")
        if sections:
            feats = {k: v for k, v in feats.items() if any(s in k for s in sections)}
        return _envelope({"tn": tn, "identity": bf["identity"], "features": feats},
                         evidence=bf["evidence"], data_gaps=bf["data_gaps"])
    except Exception as e:  # pragma: no cover
        log.error("get_employee_profile: %s", e)
        return f"⚠️ Не удалось собрать профиль: {e}"


# --- 5. resolve_role_block ---------------------------------------------------
def _resolve_role_block_handler(ctx: ToolContext, **kwargs) -> str:
    role_query = kwargs.get("role_query")
    block_query = kwargs.get("block_query") or kwargs.get("block")
    if not role_query and not block_query:
        return _envelope(None, ok=False,
                         data_gaps=["Укажите 'role_query' и/или 'block_query'."])
    try:
        rb = R.resolve_role_block(role_query=role_query, block_query=block_query, ctx=ctx)
        return _envelope({"resolved_block": rb["resolved_block"],
                          "resolved_role_family": rb["resolved_role_family"],
                          "candidate_roles": rb["candidate_roles"],
                          "alternatives": rb["alternatives"],
                          "actual_blocks": rb["actual_blocks"]},
                         assumptions=rb["assumptions"] + rb["notes"],
                         needs_clarification=rb["needs_clarification"])
    except Exception as e:  # pragma: no cover
        log.error("resolve_role_block: %s", e)
        return f"⚠️ Не удалось разрешить роль/блок: {e}"


# --- 6. find_population ------------------------------------------------------
def _find_population_handler(ctx: ToolContext, **kwargs) -> str:
    filters = kwargs.get("filters")
    if filters is None:
        # Допустить плоскую передачу критериев (без обёртки filters).
        filters = {k: v for k, v in kwargs.items() if k not in ("sections",)}
    if not isinstance(filters, dict):
        return _envelope(None, ok=False, data_gaps=["Параметр 'filters' должен быть объектом."])
    try:
        res = A.filter_population(filters, ctx)
        assumptions = []
        if "block" in res["applied_filters"] and filters.get("block") not in (
                None, res["applied_filters"]["block"]):
            assumptions.append(f"Блок «{filters.get('block')}» сопоставлен с «{res['applied_filters']['block']}».")
        return _envelope({"count": res["count"], "applied_filters": res["applied_filters"],
                          "results": res["results"]},
                         assumptions=assumptions + res.get("ethics_flags", []))
    except Exception as e:  # pragma: no cover
        log.error("find_population: %s", e)
        return f"⚠️ Не удалось отфильтровать популяцию: {e}"


# --- 7. compute_baseline -----------------------------------------------------
def _compute_baseline_handler(ctx: ToolContext, **kwargs) -> str:
    metrics = kwargs.get("metrics")
    if not metrics:
        return _envelope(None, ok=False, data_gaps=["Не указан параметр 'metrics' (список метрик)."])
    if isinstance(metrics, str):
        metrics = [metrics]
    try:
        res = A.compute_baseline(metrics, cohort_tns=kwargs.get("cohort_tns"),
                                 filters=kwargs.get("filters"), ctx=ctx)
        gaps = ["Когорта мала (<5) — выводы о ранжировании ненадёжны."] if res["cohort_size"] < 5 else []
        return _envelope(res, data_gaps=gaps)
    except Exception as e:  # pragma: no cover
        log.error("compute_baseline: %s", e)
        return f"⚠️ Не удалось вычислить базовую линию: {e}"


# --- 8. score_candidates -----------------------------------------------------
def _score_candidates_handler(ctx: ToolContext, **kwargs) -> str:
    role_query = kwargs.get("role_query")
    if not role_query and not kwargs.get("cohort_tns") and not kwargs.get("filters"):
        return _envelope(None, ok=False,
                         data_gaps=["Укажите 'role_query' (целевая роль/семейство) либо когорту/фильтры."])
    try:
        res = A.score_candidates(role_query=role_query, block=kwargs.get("block"),
                                 cohort_tns=kwargs.get("cohort_tns"), filters=kwargs.get("filters"),
                                 top_n=int(kwargs.get("top_n", 10)),
                                 weights_override=kwargs.get("weights_override"), ctx=ctx)
        evidence = [{"tn": c["tn"], "ФИО": c["ФИО"], "fit": c["fit_score"],
                     "доказательства": c["доказательства"]} for c in res["shortlist"]]
        return _envelope({"target_role": res.get("target_role"),
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


# --- 9. extract_impact -------------------------------------------------------
def _extract_impact_handler(ctx: ToolContext, **kwargs) -> str:
    tn = kwargs.get("tn")
    tns = kwargs.get("tns")
    if tn is None and not tns:
        return _envelope(None, ok=False, data_gaps=["Укажите 'tn' или 'tns'."])
    targets = [int(tn)] if tn is not None else [int(t) for t in tns]
    try:
        out = []
        evidence = []
        prof = dl.get_sheet(dl.SHEET_PROFILE, ctx).set_index("tn")
        for t in targets:
            if t not in prof.index:
                out.append({"tn": t, "found": False})
                continue
            ledger = P.parse_impact_ledger(prof.loc[t, "Ключевые достижения"])
            out.append({"tn": t, "found": True, "features": ledger["features"],
                        "records": ledger["records"]})
            for rec in ledger["records"][:5]:
                evidence.append({"tn": t, "тип": rec["metric_type"], "значение": rec.get("value"),
                                 "фрагмент": rec["raw_sentence"]})
        gaps = ["Числа в достижениях — самоописания, не аудированные KPI (A.14.4)."]
        return _envelope({"employees": out}, evidence=evidence, data_gaps=gaps)
    except Exception as e:  # pragma: no cover
        log.error("extract_impact: %s", e)
        return f"⚠️ Не удалось извлечь Impact Ledger: {e}"


# --- 10. compare_employees ---------------------------------------------------
def _compare_employees_handler(ctx: ToolContext, **kwargs) -> str:
    tns = kwargs.get("tns")
    if not tns or not isinstance(tns, list) or len(tns) < 2:
        return _envelope(None, ok=False, data_gaps=["Укажите 'tns' — список из ≥2 табельных номеров."])
    try:
        res = A.compare_employees([int(t) for t in tns], dimensions=kwargs.get("dimensions"), ctx=ctx)
        return _envelope(res)
    except Exception as e:  # pragma: no cover
        log.error("compare_employees: %s", e)
        return f"⚠️ Не удалось сравнить сотрудников: {e}"


# --- 11. analyze_evaluation_trend -------------------------------------------
def _analyze_evaluation_trend_handler(ctx: ToolContext, **kwargs) -> str:
    tn = kwargs.get("tn")
    if tn is None:
        return _envelope(None, ok=False, data_gaps=["Не указан параметр 'tn'."])
    try:
        res = A.analyze_evaluation_trend(int(tn), ctx)
        if not res.get("found"):
            return _envelope(res, data_gaps=res.get("data_gaps", []))
        return _envelope(res, data_gaps=["Q-ряд и Y-ряд не смешиваются (К4); домены: результат {B,C,D}, ценности {B,C}."])
    except Exception as e:  # pragma: no cover
        log.error("analyze_evaluation_trend: %s", e)
        return f"⚠️ Не удалось проанализировать тренд оценок: {e}"


# --- 12. find_patterns -------------------------------------------------------
def _find_patterns_handler(ctx: ToolContext, **kwargs) -> str:
    method = kwargs.get("method", "correlate")
    try:
        res = A.find_patterns(method=method, variables=kwargs.get("variables"),
                              scope_filters=kwargs.get("scope_filters"),
                              n_clusters=int(kwargs.get("n_clusters", 4)), ctx=ctx)
        return _envelope(res, data_gaps=["Разведочный результат — гипотеза, требует проверки человеком (H.2)."])
    except Exception as e:  # pragma: no cover
        log.error("find_patterns: %s", e)
        return f"⚠️ Не удалось выполнить разведочный анализ: {e}"


# ============================================================================
def get_tools() -> List[ToolEntry]:
    """Возвращает список агентских тулов HR-агента."""
    return [
        ToolEntry(
            name="get_current_date",
            schema={"name": "get_current_date",
                    "description": "Возвращает текущую дату на русском (например «20 июня 2026»). "
                                   "Полезно для расчёта свежести наград/курсов/повышений.",
                    "parameters": {"type": "object", "properties": {}, "required": []}},
            handler=_get_current_date_handler, is_code_tool=False, timeout_sec=5),

        ToolEntry(
            name="list_dimension_values",
            schema={"name": "list_dimension_values",
                    "description": "Масштабонезависимое обнаружение справочников: возвращает фактические "
                                   "значения измерения и их частоты ИЗ ДАННЫХ (не из зашитых перечней). "
                                   "Вызывайте ВМЕСТО опоры на память о блоках/ролях/ТБ. "
                                   "dimension ∈ {блок, ТБ, роль, грейд, режим работы, пол, "
                                   "работодатель_до_Сбера, …} или точное имя поля.",
                    "parameters": {"type": "object", "properties": {
                        "dimension": {"type": "string", "description": "Измерение/поле справочника."},
                        "sheet": {"type": "string", "description": "Лист (по умолчанию «профиль»)."}},
                        "required": ["dimension"]}},
            handler=_list_dimension_values_handler, is_code_tool=False, timeout_sec=10),

        ToolEntry(
            name="resolve_person",
            schema={"name": "resolve_person",
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
                        "required": ["query"]}},
            handler=_resolve_person_handler, is_code_tool=False, timeout_sec=10),

        ToolEntry(
            name="get_employee_profile",
            schema={"name": "get_employee_profile",
                    "description": "Собирает нормализованный профиль одного сотрудника по всем 12 листам + "
                                   "производные признаки (стаж-float, сводка Impact Ledger, тиры наград, "
                                   "компетенции SberQ 4.0, последняя оценка и тренд, история грейдов, языки, "
                                   "образование, цели). Возвращает данные + evidence (сырые достижения/оценки) "
                                   "+ data_gaps. Принимает tn (получите через resolve_person).",
                    "parameters": {"type": "object", "properties": {
                        "tn": {"type": "integer", "description": "Табельный номер сотрудника."},
                        "sections": {"type": "array", "items": {"type": "string"},
                                     "description": "Необязательно: подстроки имён признаков для частичной выборки "
                                                    "(например ['impact','award','tenure'])."}},
                        "required": ["tn"]}},
            handler=_get_employee_profile_handler, is_code_tool=False, timeout_sec=20),

        ToolEntry(
            name="resolve_role_block",
            schema={"name": "resolve_role_block",
                    "description": "Сопоставляет роль/блок/англоязычное название должности (chief data "
                                   "scientist, CISO, CFO…) с фактическими сущностями данных. Реализует "
                                   "протокол «нет совпадения»: для отсутствующего блока (например «Финансы») "
                                   "НЕ подменяет молча — возвращает notes/alternatives и "
                                   "needs_clarification, фиксирует допущение в assumptions.",
                    "parameters": {"type": "object", "properties": {
                        "role_query": {"type": "string", "description": "Целевая роль/должность (любым языком)."},
                        "block_query": {"type": "string", "description": "Функциональный блок (формулировка запроса)."}},
                        "required": []}},
            handler=_resolve_role_block_handler, is_code_tool=False, timeout_sec=10),

        ToolEntry(
            name="find_population",
            schema={"name": "find_population",
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
                        "required": ["filters"]}},
            handler=_find_population_handler, is_code_tool=False, timeout_sec=30),

        ToolEntry(
            name="compute_baseline",
            schema={"name": "compute_baseline",
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
                        "required": ["metrics"]}},
            handler=_compute_baseline_handler, is_code_tool=False, timeout_sec=30),

        ToolEntry(
            name="score_candidates",
            schema={"name": "score_candidates",
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
                        "required": ["role_query"]}},
            handler=_score_candidates_handler, is_code_tool=False, timeout_sec=60),

        ToolEntry(
            name="extract_impact",
            schema={"name": "extract_impact",
                    "description": "Impact Ledger (Часть C.2) по одному tn или когорте: структурированные "
                                   "количественные результаты из «Ключевых достижений» (эконом-эффект млн ₽/год, "
                                   "размер команды, SLA %, сокращение цикла, число инициатив, предотвращённые "
                                   "потери, релизы, рост в п.п./%) + СЫРЫЕ фрагменты для цитирования. "
                                   "Числа — самоописания, не аудит.",
                    "parameters": {"type": "object", "properties": {
                        "tn": {"type": "integer", "description": "Один табельный номер."},
                        "tns": {"type": "array", "items": {"type": "integer"}, "description": "Когорта табельных номеров."}},
                        "required": []}},
            handler=_extract_impact_handler, is_code_tool=False, timeout_sec=30),

        ToolEntry(
            name="compare_employees",
            schema={"name": "compare_employees",
                    "description": "Сравнивает нескольких сотрудников по выбранным измерениям и показывает, "
                                   "кто в чём лидирует, с конкретными значениями. По умолчанию измерения: "
                                   "импакт, компетенции, доля B, награды, стаж, курсы, скорость роста.",
                    "parameters": {"type": "object", "properties": {
                        "tns": {"type": "array", "items": {"type": "integer"},
                                "description": "Список ≥2 табельных номеров."},
                        "dimensions": {"type": "array", "items": {"type": "string"},
                                       "description": "Имена признаков для сравнения (необязательно)."}},
                        "required": ["tns"]}},
            handler=_compare_employees_handler, is_code_tool=False, timeout_sec=30),

        ToolEntry(
            name="analyze_evaluation_trend",
            schema={"name": "analyze_evaluation_trend",
                    "description": "Динамика оценок за 5 лет по сотруднику. Квартальный (Q1–Q4) и годовой (Y) "
                                   "ряды РАЗДЕЛЬНО (К4). Ординал B=3,C=2,D=1; направление (наклон), "
                                   "волатильность, последнее значение. Домены: результат {B,C,D}, ценности {B,C}.",
                    "parameters": {"type": "object", "properties": {
                        "tn": {"type": "integer", "description": "Табельный номер."}},
                        "required": ["tn"]}},
            handler=_analyze_evaluation_trend_handler, is_code_tool=False, timeout_sec=15),

        ToolEntry(
            name="find_patterns",
            schema={"name": "find_patterns",
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
                        "required": ["method"]}},
            handler=_find_patterns_handler, is_code_tool=False, timeout_sec=60),
    ]
