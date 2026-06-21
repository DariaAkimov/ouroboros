"""
Вычислительные примитивы и оценочные модели (Части E, F, I методологии).

Содержит:
  * `build_features(tn)` — полный профиль признаков одного сотрудника (Часть D);
  * `population_frame()` — кэшированная матрица числовых признаков по всей
    популяции (для базовых линий, перцентилей, фильтров, кластеризации);
  * `filter_population`, `compute_baseline` (E.filter / E.aggregate / F);
  * `score_candidates` — многофакторный Fit/Readiness (Часть I) + резервный
    режим «только профиль»;
  * `compare_employees`, `analyze_evaluation_trend` (Q и Y раздельно, К4),
    `find_patterns` (correlate/cluster, гипотеза).

Все суждения «лучше/готов/выдающийся» считаются относительно когорты (Часть F).
Перцентиль, а не абсолют, для разнородных по масштабу метрик (импакт/опыт).
"""

import logging
import threading
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

import data_loader as dl
import ontology as onto
import parsers as P

log = logging.getLogger(__name__)

_POP_CACHE: Dict[tuple, pd.DataFrame] = {}
_POP_LOCK = threading.Lock()

# Наблюдаемый диапазон шкалы «опыт» для нормализации (К5) — берётся из данных,
# не зашит: пересчитывается в population_frame по факту.


# --- Признаки оценок (К2/К3/К4) ---------------------------------------------
def compute_eval_features(tn: int, ctx: Any = None) -> Dict[str, Any]:
    """Результативность по «оценки за 5 лет». Q и Y строго раздельно (К4)."""
    rows = dl.get_rows_for(dl.SHEET_EVALUATIONS, tn, ctx)
    out = {"result_share_B": None, "has_any_D": None, "result_stability": None,
           "result_trend_Y": None, "values_share_B": None, "n_eval_periods": 0,
           "last_result": None, "last_year": None, "_present": False}
    if rows.empty:
        return out
    out["_present"] = True
    q_rows = rows[rows["Квартал"].isin(["Q1", "Q2", "Q3", "Q4"])]
    y_rows = rows[rows["Квартал"] == "Y"].sort_values("Год")

    res_q = q_rows["Оценка за результат"].dropna().astype(str)
    out["n_eval_periods"] = int(len(res_q))
    if len(res_q):
        out["result_share_B"] = round((res_q == "B").mean(), 4)
        out["has_any_D"] = bool((res_q == "D").any())
        ords = res_q.map(lambda c: P.eval_to_ordinal(c, "result")).dropna()
        out["result_stability"] = round(float(ords.std(ddof=0)), 4) if len(ords) > 1 else 0.0
    val_q = q_rows["Оценка за ценности"].dropna().astype(str)
    if len(val_q):
        out["values_share_B"] = round((val_q == "B").mean(), 4)

    # Тренд по годовому ряду Y (наклон по ординалам).
    if len(y_rows) >= 2:
        yo = y_rows["Оценка за результат"].map(lambda c: P.eval_to_ordinal(c, "result"))
        yv = pd.to_numeric(yo, errors="coerce")
        yr = pd.to_numeric(y_rows["Год"], errors="coerce")
        valid = yv.notna() & yr.notna()
        if valid.sum() >= 2:
            slope = np.polyfit(yr[valid].values, yv[valid].values, 1)[0]
            out["result_trend_Y"] = round(float(slope), 4)
        last = y_rows.iloc[-1]
        out["last_result"] = last["Оценка за результат"]
        out["last_year"] = int(last["Год"]) if pd.notna(last["Год"]) else None
    elif len(res_q):
        out["last_result"] = res_q.iloc[-1]
    return out


# --- Признаки целей (К7) -----------------------------------------------------
def compute_goal_features(tn: int, ctx: Any = None) -> Dict[str, Any]:
    """Цели: тематический микс, измеримость КР, доли весов; валидация весов по
    категории (К7: ≈100% на тематическую категорию, ≈300% суммарно — НЕ ошибка)."""
    rows = dl.get_rows_for(dl.SHEET_GOALS, tn, ctx)
    out = {"n_goals": 0, "goal_theme_mix": {}, "kr_measurable_share": None,
           "goal_weight_shares": {}, "weights_valid_by_category": None,
           "weight_category_sums": {}, "_present": False}
    if rows.empty:
        return out
    out["_present"] = True
    rows = rows.copy()
    rows["cat"] = rows["Название цели"].map(lambda s: str(s).split(":")[0].strip() if pd.notna(s) else "—")
    distinct_goals = rows.drop_duplicates(subset=["Название цели"])
    out["n_goals"] = int(distinct_goals["Название цели"].nunique())
    out["goal_theme_mix"] = distinct_goals["cat"].value_counts().to_dict()

    # Измеримость КР: есть ли число/процент/«млн»/«дн» в описании или названии КР.
    def measurable(row):
        text = f"{row.get('Название Ключевого результата','')} {row.get('Описание Ключевого результата','')}"
        return bool(__import__("re").search(r"\d", str(text)))
    out["kr_measurable_share"] = round(rows.apply(measurable, axis=1).mean(), 4)

    # Веса: сумма по категории за квартал (К7). Без подмешивания Y.
    wq = dl._match_column(rows, "Вес цели Q1")
    if wq:
        cat_sums = rows.groupby("cat")[wq].sum().to_dict()
        out["weight_category_sums"] = {k: int(v) for k, v in cat_sums.items()}
        # Валидно, если каждая категория суммарно близка к 100 (терпимо 70–130).
        out["weights_valid_by_category"] = all(70 <= v <= 130 for v in cat_sums.values()) if cat_sums else None
        total = sum(cat_sums.values())
        if total:
            out["goal_weight_shares"] = {k: round(v / total, 4) for k, v in cat_sums.items()}
    return out


# --- Признаки грейдов (К9) ---------------------------------------------------
def compute_grade_features(tn: int, ctx: Any = None) -> Dict[str, Any]:
    """Карьерная динамика по «изменения грейдов». Только повышения (К9).
    Отсутствие записей ≠ нулевой потенциал — помечается отдельно."""
    rows = dl.get_rows_for(dl.SHEET_GRADE_CHANGES, tn, ctx)
    out = {"has_grade_records": False, "n_promotions_window": None,
           "last_promotion_date": None, "promotion_velocity": None,
           "last_grade_to": None}
    if rows.empty:
        return out
    out["has_grade_records"] = True
    out["n_promotions_window"] = int(len(rows))
    dates = [dl.parse_date_any(d) for d in rows["Календарный день"]]
    dates = [d for d in dates if d]
    if dates:
        last = max(dates)
        first = min(dates)
        out["last_promotion_date"] = last.strftime("%Y-%m-%d")
        span_years = max((dl.ANALYSIS_NOW - first).days / 365.25, 0.5)
        out["promotion_velocity"] = round(len(rows) / span_years, 3)
    to_col = dl._match_column(rows, "Стал разряд сотрудника")
    if to_col is not None:
        vals = pd.to_numeric(rows[to_col], errors="coerce").dropna()
        if len(vals):
            out["last_grade_to"] = int(vals.max())
    return out


# --- Признаки компетенций (sberq) -------------------------------------------
def _numeric_cols(df: pd.DataFrame) -> List[str]:
    return [c for c in df.columns if c != "tn" and pd.api.types.is_numeric_dtype(df[c])]


def compute_competency_features(tn: int, ctx: Any = None) -> Dict[str, Any]:
    """sberq-фокусные + SberQ 4.0: общий средний, топ/боттом компетенции, средний 4.0."""
    out = {"comp_overall_mean": None, "comp_top_strengths": [], "comp_growth_zones": [],
           "sberq4_avg": None, "sberq4_competencies": {}, "_sberq_present": False,
           "_focus_present": False}
    foc = dl.get_rows_for(dl.SHEET_SBERQ_FOCUS, tn, ctx)
    if not foc.empty:
        out["_focus_present"] = True
        row = foc.iloc[0]
        cols = [c for c in foc.columns if c != "tn"]
        series = pd.to_numeric(row[cols], errors="coerce").dropna()
        if len(series):
            out["comp_overall_mean"] = round(float(series.mean()), 3)
            out["comp_top_strengths"] = [{"competency": k, "value": round(float(v), 2)}
                                         for k, v in series.sort_values(ascending=False).head(3).items()]
            out["comp_growth_zones"] = [{"competency": k, "value": round(float(v), 2)}
                                        for k, v in series.sort_values().head(3).items()]
    s4 = dl.get_rows_for(dl.SHEET_SBERQ_40, tn, ctx)
    if not s4.empty:
        out["_sberq_present"] = True
        row = s4.iloc[0]
        avg_col = dl._match_column(s4, "Средний балл")
        if avg_col is not None and pd.notna(row[avg_col]):
            out["sberq4_avg"] = round(float(row[avg_col]), 3)
        comp_cols = [c for c in s4.columns if c not in ("tn",) and c != avg_col]
        out["sberq4_competencies"] = {c: round(float(row[c]), 2) for c in comp_cols
                                      if pd.notna(row[c]) and isinstance(row[c], (int, float, np.number))}
    return out


# --- Признаки опыта (К5/A.5) -------------------------------------------------
def compute_experience_features(tn: int, ctx: Any = None) -> Dict[str, Any]:
    rows = dl.get_rows_for(dl.SHEET_EXPERIENCE, tn, ctx)
    out = {"exp_breadth": None, "exp_scale": None, "exp_reflection": None, "exp_wisdom": None,
           "_present": False}
    if rows.empty:
        return out
    out["_present"] = True
    row = rows.iloc[0]
    mapping = {"Широта контекстов": "exp_breadth", "Масштаб влияния": "exp_scale",
               "Извлеченные уроки, рефлексия": "exp_reflection",
               "Жизненный интеллект / практическая мудрость": "exp_wisdom"}
    for col, key in mapping.items():
        c = dl._match_column(rows, col)
        if c is not None and pd.notna(row[c]):
            out[key] = round(float(row[c]), 2)
    return out


# --- Полный профиль признаков одного сотрудника (Часть D) -------------------
def build_features(tn: int, ctx: Any = None) -> Dict[str, Any]:
    """Собирает нормализованный профиль признаков по всем 12 листам + provenance.

    Возвращает {tn, identity, features{...}, evidence[...], data_gaps[...]}.
    Никогда не выдумывает: чего нет — помечается в data_gaps (Часть K).
    """
    prof_row = dl.get_profile_row(tn, ctx)
    data_gaps: List[str] = []
    evidence: List[Dict[str, Any]] = []
    if prof_row is None:
        return {"tn": tn, "found": False,
                "data_gaps": [f"Сотрудник {tn} отсутствует в профиле."], "evidence": [],
                "identity": {}, "features": {}}

    g = lambda f: prof_row.get(dl._match_column(dl.get_sheet(dl.SHEET_PROFILE, ctx), f))

    identity = {
        "tn": tn,
        "ФИО": g("ФИО"),
        "block": g("Функциональный блок"),
        "role": g("Роль"),
        "role_tier": onto.role_tier(g("Роль")),
        "role_family": onto.role_family(g("Роль")),
        "grade": int(g("Грейд")) if pd.notna(g("Грейд")) else None,
        "geo": g("ЦА\\ТБ\\ПЦП"),
        "is_ca": "ЦА" in str(g("ЦА\\ТБ\\ПЦП")),
        "work_mode": g("режим работы (офис, гибрид, удаленный)"),
        "пол": g("Пол"),  # только для агрегатной D&I / явного критерия (Часть L)
    }

    feats: Dict[str, Any] = {}
    # Стаж (C.1).
    feats["tenure_role_years"] = P.parse_tenure(g("Стаж в должности"))
    feats["tenure_sber_years"] = P.parse_tenure(g("Стаж в Сбере"))
    if feats["tenure_role_years"] and feats["tenure_sber_years"]:
        feats["role_to_sber_ratio"] = round(feats["tenure_role_years"] / feats["tenure_sber_years"], 3)
    else:
        feats["role_to_sber_ratio"] = None

    # Impact Ledger (C.2).
    impact = P.parse_impact_ledger(g("Ключевые достижения"))
    feats.update(impact["features"])
    for rec in impact["records"][:6]:
        evidence.append({"источник": "Ключевые достижения", "тип": rec["metric_type"],
                         "значение": rec.get("value"), "фрагмент": rec["raw_sentence"]})
    if impact["features"]["impact_n_records"] == 0:
        data_gaps.append("В «Ключевых достижениях» не извлечено количественных метрик (возможен качественный вклад).")

    # Награды (C.3).
    aw = P.parse_awards(g("Награды"))
    feats.update(aw["features"])
    for rec in aw["records"][:6]:
        evidence.append({"источник": "Награды", "награда": rec["type"], "дата": rec["date"], "тир": rec["tier"]})
    if aw["features"]["awards_count"] == 0:
        data_gaps.append("Награды не указаны (отсутствие наград ≠ отсутствие заслуг).")

    # Образование (C.4), курсы (C.5), языки (C.6), активности (C.7), наука/степени.
    feats.update(P.parse_education(g("Образование"))["features"])
    courses = P.parse_courses(g("Курсы"), dl.get_rows_for(dl.SHEET_TRAINING, tn, ctx))
    feats.update(courses["features"])
    feats.update(P.parse_languages(g("Знание языков"))["features"])
    feats.update(P.parse_activities(g("Корпоративные активности"))["features"])
    feats.update(P.parse_science(g("Научная деятельность"))["features"])
    feats.update(P.parse_degrees(g("Ученые степени"))["features"])
    interests = P.parse_interests(g("Интересы"))
    feats["interests_categories"] = interests["features"]["interests_categories"]  # мягкий прокси (Часть L)

    # Прошлый работодатель / сектор.
    feats["prior_employer"] = g("Место работы до Сбера")
    feats["prior_sector"] = onto.prior_sector(g("Место работы до Сбера"))
    feats["external_hire"] = bool(g("Место работы до Сбера")) and feats["prior_sector"] not in (None,)

    # Коэффициент нагрузки (Часть J) — контекст, не штраф.
    util = g("Коэффициент отработанного времени 2026")
    feats["utilization_2026"] = round(float(util), 4) if pd.notna(util) else None
    feats["utilization_band"] = _utilization_band(feats["utilization_2026"])

    # Компетенции, опыт, оценки, цели, грейды.
    comp = compute_competency_features(tn, ctx)
    feats.update({k: v for k, v in comp.items() if not k.startswith("_")})
    exp = compute_experience_features(tn, ctx)
    feats.update({k: v for k, v in exp.items() if not k.startswith("_")})
    ev = compute_eval_features(tn, ctx)
    feats.update({k: v for k, v in ev.items() if not k.startswith("_")})
    if ev["_present"] and (ev["result_share_B"] is not None):
        evidence.append({"источник": "оценки за 5 лет",
                         "доля_B_результат": ev["result_share_B"], "наличие_D": ev["has_any_D"],
                         "последняя_оценка": ev["last_result"], "тренд_Y": ev["result_trend_Y"]})
    goals = compute_goal_features(tn, ctx)
    feats.update({k: v for k, v in goals.items() if not k.startswith("_")})
    grades = compute_grade_features(tn, ctx)
    feats.update(grades)

    # HTML-выводы (C.8) — зоны роста для рекомендаций развития.
    vyv = dl.get_rows_for(dl.SHEET_CONCLUSIONS, tn, ctx)
    if not vyv.empty:
        hc = P.parse_html_conclusion(vyv.iloc[0].get("Итоговый вывод по паутинке"))
        feats["strengths_text"] = hc["strengths"]
        feats["growth_zones_text"] = hc["growth_zones"]
        if hc["growth_zones"]:
            evidence.append({"источник": "паутинка (выводы)", "зоны_роста": hc["growth_zones"]})

    # Пробелы данных по источникам (Часть K).
    if not comp["_sberq_present"]:
        data_gaps.append("Нет данных SberQ 4.0 (компетенции).")
    if not comp["_focus_present"]:
        data_gaps.append("Нет развёрнутой паутинки компетенций (sberq и фокусные).")
    if not ev["_present"]:
        data_gaps.append("Нет оценок за 5 лет.")
    if not exp["_present"]:
        data_gaps.append("Нет данных паутинки «опыт».")
    if not grades["has_grade_records"]:
        data_gaps.append("Нет записей о повышениях в грейде (≠ отсутствие роста; журнал неполон, A.10).")

    return {"tn": tn, "found": True, "identity": identity, "features": feats,
            "evidence": evidence, "data_gaps": data_gaps}


def _utilization_band(u: Optional[float]) -> Optional[str]:
    if u is None:
        return None
    if u >= 0.97:
        return "высокая загрузка (≥0.97)"
    if u >= 0.90:
        return "типичная (0.90–0.97)"
    return "пониженная отработка (<0.90; причины нейтральны: отпуск/декрет/обучение/частичная занятость)"


# --- Матрица признаков всей популяции (для базовых линий/перцентилей/кластеров) ---
_NUMERIC_POP_FIELDS = [
    "tenure_role_years", "tenure_sber_years", "role_to_sber_ratio",
    "impact_econ_total", "impact_econ_max", "impact_max_team", "impact_n_initiatives",
    "impact_loss_prevented_total", "impact_cycle_best_ratio", "impact_breadth", "impact_sla_max",
    "comp_overall_mean", "sberq4_avg", "exp_breadth", "exp_scale", "exp_reflection", "exp_wisdom",
    "result_share_B", "result_trend_Y", "values_share_B",
    "awards_count", "awards_prestige_score", "courses_count", "courses_ai_count",
    "courses_leadership_count", "english_cefr_ordinal", "lang_count",
    "n_promotions_window", "promotion_velocity", "utilization_2026",
    "activities_count", "engagement_breadth",
]
_CATEG_POP_FIELDS = ["block", "role", "role_tier", "role_family", "grade", "geo", "is_ca",
                     "work_mode", "пол", "prior_sector", "external_hire", "has_degree",
                     "has_publications", "edu_is_stem", "edu_tier", "edu_mba_like",
                     "courses_external_elite", "has_strategy_facilitation", "has_any_D",
                     "multilingual", "has_strategic_language"]


def population_frame(ctx: Any = None) -> pd.DataFrame:
    """Кэшированная матрица признаков по всей популяции (индекс = tn).

    Считается из данных, без зашитых констант (масштабонезависимо)."""
    path = dl.resolve_xlsx_path(ctx)
    import os
    key = (os.path.abspath(path), os.path.getmtime(path) if os.path.exists(path) else 0)
    with _POP_LOCK:
        if key in _POP_CACHE:
            return _POP_CACHE[key]
    rows = []
    for tn in dl.all_tns(ctx):
        bf = build_features(tn, ctx)
        rec = {"tn": tn}
        feats = bf["features"]
        ident = bf["identity"]
        for f in _NUMERIC_POP_FIELDS:
            rec[f] = feats.get(f)
        for f in _CATEG_POP_FIELDS:
            rec[f] = ident.get(f, feats.get(f))
        rows.append(rec)
    frame = pd.DataFrame(rows).set_index("tn")
    with _POP_LOCK:
        _POP_CACHE[key] = frame
    return frame


def clear_pop_cache() -> None:
    with _POP_LOCK:
        _POP_CACHE.clear()


# --- E.filter : когортный фильтр --------------------------------------------
def filter_population(filters: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """Отбор популяции по структурным критериям и порогам признаков.

    Поддерживаемые ключи: block, tb/geo, grade/grades, role_family, role_contains,
    prior_sector, has_degree, language_min (CEFR ординал по англ.), mode/work_mode,
    gender (пол; с флагом этики), external_hire, и пороги *_min/*_max по любому
    числовому полю матрицы (например impact_econ_min, tenure_role_min, result_b_min).
    """
    frame = population_frame(ctx).copy()
    applied: Dict[str, Any] = {}
    ethics_flags: List[str] = []
    mask = pd.Series(True, index=frame.index)

    def res_block(val):
        rb = None
        canon = onto.match_block_synonym(val)
        actual = list(dl.distinct_values("Функциональный блок", ctx=ctx).keys())
        if canon in actual:
            return canon
        hit = next((b for b in actual if onto._norm(val) in onto._norm(b)), None)
        return hit or val

    for k, v in (filters or {}).items():
        if v is None:
            continue
        if k == "block":
            rb = res_block(v)
            mask &= frame["block"] == rb
            applied["block"] = rb
        elif k in ("tb", "geo"):
            mask &= frame["geo"].map(lambda x: onto._norm(v) in onto._norm(x))
            applied[k] = v
        elif k == "grade":
            mask &= frame["grade"] == int(v)
            applied["grade"] = int(v)
        elif k == "grades":
            grades = [int(x) for x in v]
            mask &= frame["grade"].isin(grades)
            applied["grades"] = grades
        elif k == "role_family":
            mask &= frame["role_family"] == v
            applied["role_family"] = v
        elif k == "role_contains":
            mask &= frame["role"].map(lambda x: onto._norm(v) in onto._norm(x))
            applied["role_contains"] = v
        elif k == "prior_sector":
            mask &= frame["prior_sector"].map(lambda x: onto._norm(v) in onto._norm(x) if x else False)
            applied["prior_sector"] = v
        elif k == "has_degree":
            mask &= frame["has_degree"] == bool(v)
            applied["has_degree"] = bool(v)
        elif k == "external_hire":
            mask &= frame["external_hire"] == bool(v)
            applied["external_hire"] = bool(v)
        elif k in ("mode", "work_mode"):
            mask &= frame["work_mode"].map(lambda x: onto._norm(v) in onto._norm(x))
            applied["work_mode"] = v
        elif k == "language_min":
            mask &= frame["english_cefr_ordinal"].fillna(-1) >= int(v)
            applied["language_min"] = int(v)
        elif k == "gender":
            mask &= frame["пол"].map(lambda x: onto._norm(v) == onto._norm(x))
            applied["gender"] = v
            ethics_flags.append("Пол использован как явный критерий запроса (Часть L): "
                                "допустимо только при явном легитимном требовании; без вторичного использования.")
        elif k.endswith("_min"):
            field = _resolve_threshold_field(k[:-4], frame)
            if field:
                mask &= frame[field].fillna(-np.inf) >= float(v)
                applied[k] = float(v)
        elif k.endswith("_max"):
            field = _resolve_threshold_field(k[:-4], frame)
            if field:
                mask &= frame[field].fillna(np.inf) <= float(v)
                applied[k] = float(v)
        elif k in frame.columns:
            mask &= frame[k] == v
            applied[k] = v

    sub = frame[mask]
    prof = dl.get_sheet(dl.SHEET_PROFILE, ctx).set_index("tn")
    results = []
    for tn in sub.index:
        row = sub.loc[tn]
        results.append({
            "tn": int(tn), "ФИО": prof.loc[tn, "ФИО"] if tn in prof.index else None,
            "блок": row["block"], "роль": row["role"], "грейд": _safe_int(row["grade"]),
            "тир": row["role_tier"], "семейство": row["role_family"],
            "значения_фильтра": {k: _safe_val(row.get(_resolve_threshold_field(
                k.replace("_min", "").replace("_max", ""), frame) or k))
                for k in applied if k.endswith(("_min", "_max"))},
        })
    return {"count": len(results), "applied_filters": applied, "results": results,
            "ethics_flags": ethics_flags}


_THRESHOLD_ALIASES = {
    "impact_econ": "impact_econ_total", "tenure_role": "tenure_role_years",
    "tenure_sber": "tenure_sber_years", "result_b_share": "result_share_B",
    "result_b": "result_share_B", "team": "impact_max_team", "awards": "awards_count",
    "prestige": "awards_prestige_score", "sberq4": "sberq4_avg", "comp": "comp_overall_mean",
    "utilization": "utilization_2026", "promotions": "n_promotions_window",
}


def _resolve_threshold_field(name: str, frame: pd.DataFrame) -> Optional[str]:
    if name in frame.columns:
        return name
    if name in _THRESHOLD_ALIASES and _THRESHOLD_ALIASES[name] in frame.columns:
        return _THRESHOLD_ALIASES[name]
    return None


def _safe_int(v):
    return int(v) if pd.notna(v) else None


def _safe_val(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return round(float(v), 4)
    return v


# --- E.aggregate / F : базовая линия ----------------------------------------
def compute_baseline(metrics: List[str], cohort_tns: Optional[List[int]] = None,
                     filters: Optional[Dict[str, Any]] = None, ctx: Any = None) -> Dict[str, Any]:
    """Статистики распределения метрик по когорте (для контекстуализации/нормализации)."""
    frame = population_frame(ctx)
    if cohort_tns is not None:
        cohort = frame.loc[[t for t in cohort_tns if t in frame.index]]
    elif filters:
        ftns = [r["tn"] for r in filter_population(filters, ctx)["results"]]
        cohort = frame.loc[[t for t in ftns if t in frame.index]]
    else:
        cohort = frame
    stats = {}
    for m in metrics:
        field = _resolve_threshold_field(m, frame) or m
        if field not in cohort.columns:
            stats[m] = {"error": "поле не найдено"}
            continue
        s = pd.to_numeric(cohort[field], errors="coerce").dropna()
        if s.empty:
            stats[m] = {"n": 0}
            continue
        stats[m] = {"n": int(s.size), "mean": round(float(s.mean()), 3),
                    "median": round(float(s.median()), 3),
                    "p10": round(float(s.quantile(.1)), 3), "p25": round(float(s.quantile(.25)), 3),
                    "p50": round(float(s.quantile(.5)), 3), "p75": round(float(s.quantile(.75)), 3),
                    "p90": round(float(s.quantile(.9)), 3),
                    "min": round(float(s.min()), 3), "max": round(float(s.max()), 3)}
    return {"cohort_size": int(len(cohort)), "metrics": stats}


# --- Часть I: многофакторный Fit / Readiness --------------------------------
# Пресеты весов факторов по функциональному семейству (калибруются HR).
_FIT_DEFAULT_WEIGHTS = {
    "competency": 0.22, "impact": 0.24, "result_stability": 0.16, "career": 0.10,
    "development": 0.08, "experience": 0.10, "education": 0.05, "engagement": 0.05,
}
_FAMILY_EMPHASIS = {
    "data/AI": {"impact": +0.04, "development": +0.04, "competency": +0.02, "education": +0.02,
                "career": -0.04, "engagement": -0.04, "result_stability": -0.04},
    "риски": {"impact": +0.03, "result_stability": +0.03, "education": +0.02,
              "engagement": -0.04, "development": -0.02, "career": -0.02},
    "кибербезопасность": {"impact": +0.03, "development": +0.03, "competency": +0.02,
                          "engagement": -0.04, "career": -0.04},
    "КИБ": {"impact": +0.05, "engagement": -0.03, "development": -0.02},
}


def _fit_weights(family: Optional[str]) -> Dict[str, float]:
    w = dict(_FIT_DEFAULT_WEIGHTS)
    for k, dv in _FAMILY_EMPHASIS.get(family or "", {}).items():
        w[k] = max(0.0, w[k] + dv)
    total = sum(w.values())
    return {k: v / total for k, v in w.items()}


def _impact_composite(feats: Dict[str, Any], family: Optional[str]) -> float:
    """Композит импакта (сырой, для перцентиля) с акцентом по семейству."""
    parts = {
        "econ": (feats.get("impact_econ_total") or 0.0),
        "team": (feats.get("impact_max_team") or 0.0),
        "init": (feats.get("impact_n_initiatives") or 0.0),
        "loss": (feats.get("impact_loss_prevented_total") or 0.0),
        "cycle": (feats.get("impact_cycle_best_ratio") or 0.0) * 100,
        "breadth": (feats.get("impact_breadth") or 0.0) * 20,
    }
    w = {"econ": 0.30, "team": 0.20, "init": 0.15, "loss": 0.15, "cycle": 0.10, "breadth": 0.10}
    if family == "data/AI":
        w = {"econ": 0.22, "team": 0.18, "init": 0.25, "loss": 0.05, "cycle": 0.18, "breadth": 0.12}
    elif family == "риски":
        w = {"econ": 0.18, "team": 0.15, "init": 0.12, "loss": 0.35, "cycle": 0.10, "breadth": 0.10}
    elif family == "КИБ":
        w = {"econ": 0.35, "team": 0.18, "init": 0.12, "loss": 0.12, "cycle": 0.13, "breadth": 0.10}
    # Нормируем компоненты грубо (econ/team большие) — используем как сырой композит,
    # перцентиль возьмём по популяции далее, так что масштаб не критичен.
    return sum(parts[k] * w[k] for k in w)


def score_candidates(role_query: Optional[str] = None, block: Optional[str] = None,
                     cohort_tns: Optional[List[int]] = None, filters: Optional[Dict[str, Any]] = None,
                     top_n: int = 10, weights_override: Optional[Dict[str, float]] = None,
                     ctx: Any = None) -> Dict[str, Any]:
    """Ранжирует кандидатов под целевую роль по модели Fit/Readiness (Часть I).

    Конвейер: разрешить роль/блок → собрать лонг-лист (на тир ниже) → факторы →
    взвесить → готовность. Резервный режим «только профиль» при отсутствии
    паутинок/оценок у кандидата.
    """
    import resolve as R
    assumptions: List[str] = []
    data_gaps_global: List[str] = []
    rb = R.resolve_role_block(role_query=role_query, block_query=block, ctx=ctx)
    assumptions.extend(rb.get("assumptions", []))
    assumptions.extend(rb.get("notes", []))
    family = rb.get("resolved_role_family")
    resolved_block = rb.get("resolved_block")

    frame = population_frame(ctx)

    # Сборка лонг-листа.
    if cohort_tns is not None:
        long_list = [t for t in cohort_tns if t in frame.index]
        assumptions.append("Когорта задана явно вызывающей стороной.")
    elif filters:
        long_list = [r["tn"] for r in filter_population(filters, ctx)["results"]]
    else:
        sub = frame
        if resolved_block:
            sub = sub[sub["block"] == resolved_block]
        if family:
            fam_sub = sub[sub["role_family"] == family]
            if not fam_sub.empty:
                sub = fam_sub
        # На тир ниже якорных ролей (если определены тиры в когорте) — мягко:
        long_list = list(sub.index)

    if not long_list:
        return {"ok": True, "shortlist": [], "assumptions": assumptions,
                "data_gaps": ["Лонг-лист пуст: под заданную роль/блок кандидатов не найдено."],
                "resolution": rb, "needs_clarification": rb.get("needs_clarification", False)}

    weights = weights_override or _fit_weights(family)

    # Перцентили считаем ВНУТРИ лонг-листа (когорта, Часть F).
    cohort = frame.loc[long_list]
    impact_composites = {}
    for tn in long_list:
        bf = build_features(int(tn), ctx)
        impact_composites[tn] = _impact_composite(bf["features"], family)
    comp_pop = list(pd.to_numeric(cohort["sberq4_avg"], errors="coerce").dropna().values)
    exp_cols = ["exp_breadth", "exp_scale", "exp_reflection", "exp_wisdom"]
    exp_pop = list(pd.to_numeric(cohort[exp_cols].mean(axis=1), errors="coerce").dropna().values)
    resb_pop = list(pd.to_numeric(cohort["result_share_B"], errors="coerce").dropna().values)
    vel_pop = list(pd.to_numeric(cohort["promotion_velocity"], errors="coerce").dropna().values)
    imp_pop = list(impact_composites.values())

    scored = []
    for tn in long_list:
        bf = build_features(int(tn), ctx)
        f = bf["features"]
        ident = bf["identity"]
        factors: Dict[str, Any] = {}
        ev: List[str] = []
        gaps = list(bf["data_gaps"])
        mode = "full"

        # Компетенции.
        if f.get("sberq4_avg") is not None:
            factors["competency"] = P.percentile_rank(f["sberq4_avg"], comp_pop) or 0.5
            ev.append(f"SberQ 4.0 средний {f['sberq4_avg']}")
        else:
            factors["competency"] = None
            mode = "profile_only"

        # Импакт.
        factors["impact"] = P.percentile_rank(impact_composites[tn], imp_pop) or 0.5
        if f.get("impact_econ_total"):
            ev.append(f"эконом-эффект {f['impact_econ_total']} млн ₽/год")
        if f.get("impact_max_team"):
            ev.append(f"команда до {f['impact_max_team']} чел.")
        if f.get("impact_n_initiatives"):
            ev.append(f"{f['impact_n_initiatives']} инициатив в пром.")

        # Устойчивость результата.
        if f.get("result_share_B") is not None:
            base = P.percentile_rank(f["result_share_B"], resb_pop) or 0.5
            if f.get("has_any_D"):
                base *= 0.7
                ev.append("есть оценка D (требует контекста)")
            if f.get("result_trend_Y") and f["result_trend_Y"] > 0:
                base = min(1.0, base + 0.05)
            factors["result_stability"] = round(base, 4)
            ev.append(f"доля B по результату {f['result_share_B']}")
        else:
            factors["result_stability"] = None
            mode = "profile_only"

        # Карьерная динамика (нейтрально при отсутствии записей, К9).
        if f.get("promotion_velocity") is not None and vel_pop:
            factors["career"] = P.percentile_rank(f["promotion_velocity"], vel_pop) or 0.5
            ev.append(f"скорость роста {f['promotion_velocity']} повыш./год")
        else:
            factors["career"] = 0.5
            gaps.append("Нет записей о повышениях — карьерная динамика учтена нейтрально (А.10).")

        # Развитие под роль.
        dev = 0.0
        if family in ("data/AI", "технологии") and f.get("courses_ai_count"):
            dev += min(0.6, 0.2 * f["courses_ai_count"])
        if f.get("courses_leadership_count"):
            dev += min(0.3, 0.1 * f["courses_leadership_count"])
        if f.get("courses_external_elite"):
            dev += 0.2
        factors["development"] = round(min(1.0, dev), 4)

        # Опыт (нормированный перцентилем, К5).
        exp_mean = np.nanmean([f.get(c) for c in exp_cols if f.get(c) is not None]) if any(
            f.get(c) is not None for c in exp_cols) else None
        factors["experience"] = P.percentile_rank(exp_mean, exp_pop) if exp_mean is not None else 0.5

        # Образование/экспертиза (вспомогательный сигнал).
        edu = 0.0
        if f.get("edu_is_stem"):
            edu += 0.4
        if f.get("has_degree"):
            edu += 0.3
        if f.get("has_publications"):
            edu += 0.3
        factors["education"] = round(min(1.0, edu), 4)

        # Вовлечённость/лидерская видимость.
        eng = 0.0
        if f.get("has_strategy_facilitation"):
            eng += 0.5
            ev.append("фасилитация стратегии/комитеты")
        eng += min(0.5, 0.1 * (f.get("engagement_breadth") or 0))
        factors["engagement"] = round(min(1.0, eng), 4)

        # Резервный режим «только профиль»: заменить отсутствующие компетенции/результат
        # профильными прокси (импакт/награды/образование/опыт/курсы).
        if mode == "profile_only":
            proxy = np.mean([factors["impact"], factors["education"],
                             P.percentile_rank(f.get("awards_prestige_score"),
                                               list(pd.to_numeric(cohort["awards_prestige_score"],
                                                                   errors="coerce").dropna().values)) or 0.5,
                             factors["experience"], factors["development"]])
            if factors["competency"] is None:
                factors["competency"] = round(float(proxy), 4)
            if factors["result_stability"] is None:
                factors["result_stability"] = round(float(proxy), 4)
            gaps.append("Режим «только профиль»: нет паутинок/оценок — Fit оценён по ограниченному "
                        "набору источников; для полноты нужны паутинка/оценки.")

        fit = round(sum(weights[k] * float(factors[k]) for k in weights), 4)
        scored.append({
            "tn": int(tn), "ФИО": ident.get("ФИО"), "роль": ident.get("role"),
            "блок": ident.get("block"), "грейд": ident.get("grade"),
            "тир_роли": ident.get("role_tier"), "семейство": ident.get("role_family"),
            "fit_score": fit, "readiness": _readiness(fit, factors, gaps),
            "режим": mode, "factor_breakdown": {k: factors[k] for k in weights},
            "доказательства": ev[:8], "data_gaps": gaps,
            "зоны_роста": f.get("growth_zones_text"),
            "_confidence": "средняя" if mode == "profile_only" else "высокая",
        })

    scored.sort(key=lambda x: x["fit_score"], reverse=True)
    return {"ok": True, "target_role": role_query, "resolved_block": resolved_block,
            "resolved_role_family": family, "weights": {k: round(v, 3) for k, v in weights.items()},
            "long_list_size": len(long_list), "shortlist": scored[:top_n],
            "assumptions": assumptions, "data_gaps": data_gaps_global,
            "needs_clarification": rb.get("needs_clarification", False), "resolution": rb}


def _readiness(fit: float, factors: Dict[str, Any], gaps: List[str]) -> str:
    """Классификация готовности по агрегированному Fit + зоны риска."""
    if fit >= 0.72 and (factors.get("result_stability") or 0) >= 0.4:
        return "Ready Now"
    if fit >= 0.58:
        return "Ready 1–2 года"
    if fit >= 0.42:
        return "Ready 2–3 года"
    return "Не готов (по доступным данным)"


# --- E.compare ---------------------------------------------------------------
def compare_employees(tns: List[int], dimensions: Optional[List[str]] = None,
                      ctx: Any = None) -> Dict[str, Any]:
    """Сравнение нескольких сотрудников по выбранным измерениям; кто в чём лидирует."""
    dims = dimensions or ["impact_econ_total", "impact_max_team", "sberq4_avg", "comp_overall_mean",
                          "result_share_B", "awards_prestige_score", "tenure_role_years",
                          "courses_count", "promotion_velocity"]
    rows = {}
    for tn in tns:
        bf = build_features(int(tn), ctx)
        rec = {"ФИО": bf["identity"].get("ФИО"), "роль": bf["identity"].get("role"),
               "блок": bf["identity"].get("block")}
        for d in dims:
            rec[d] = bf["features"].get(d)
        rows[int(tn)] = rec
    # Лидер по каждому измерению.
    leaders = {}
    for d in dims:
        best_tn, best_v = None, None
        for tn, rec in rows.items():
            v = rec.get(d)
            if v is None or (isinstance(v, float) and np.isnan(v)):
                continue
            if best_v is None or v > best_v:
                best_tn, best_v = tn, v
        if best_tn is not None:
            leaders[d] = {"tn": best_tn, "значение": _safe_val(best_v)}
    return {"employees": rows, "dimensions": dims, "leaders": leaders}


# --- E.trend : динамика оценок (Q и Y раздельно, К4) ------------------------
def analyze_evaluation_trend(tn: int, ctx: Any = None) -> Dict[str, Any]:
    """Динамика оценок за 5 лет: Q-ряд и Y-ряд РАЗДЕЛЬНО (К4)."""
    rows = dl.get_rows_for(dl.SHEET_EVALUATIONS, tn, ctx)
    if rows.empty:
        return {"tn": tn, "found": False, "data_gaps": ["Нет оценок за 5 лет."]}
    rows = rows.copy()
    rows["Год"] = pd.to_numeric(rows["Год"], errors="coerce")
    y_rows = rows[rows["Квартал"] == "Y"].sort_values("Год")
    q_rows = rows[rows["Квартал"].isin(["Q1", "Q2", "Q3", "Q4"])].sort_values(["Год", "Квартал"])

    def serialize(df):
        return [{"год": int(r["Год"]) if pd.notna(r["Год"]) else None, "квартал": r["Квартал"],
                 "результат": r["Оценка за результат"], "ценности": r["Оценка за ценности"],
                 "результат_код": P.eval_to_ordinal(r["Оценка за результат"], "result")}
                for _, r in df.iterrows()]

    def slope(df):
        o = df["Оценка за результат"].map(lambda c: P.eval_to_ordinal(c, "result"))
        yv = pd.to_numeric(o, errors="coerce")
        yr = pd.to_numeric(df["Год"], errors="coerce")
        valid = yv.notna() & yr.notna()
        if valid.sum() < 2:
            return None
        return round(float(np.polyfit(yr[valid].values, yv[valid].values, 1)[0]), 4)

    y_codes = y_rows["Оценка за результат"].map(lambda c: P.eval_to_ordinal(c, "result")).dropna()
    return {
        "tn": tn, "found": True,
        "годовой_ряд_Y": {"series": serialize(y_rows), "наклон": slope(y_rows),
                          "волатильность": round(float(y_codes.std(ddof=0)), 4) if len(y_codes) > 1 else 0.0,
                          "последнее": y_rows.iloc[-1]["Оценка за результат"] if not y_rows.empty else None},
        "квартальный_ряд_Q": {"series": serialize(q_rows), "наклон": slope(q_rows)},
        "примечание": "Годовой (Y) и квартальный (Q) ряды не смешиваются (К4).",
    }


# --- E.correlate / E.cluster : разведка (гипотезы) --------------------------
def find_patterns(method: str = "correlate", variables: Optional[List[str]] = None,
                  scope_filters: Optional[Dict[str, Any]] = None, n_clusters: int = 4,
                  ctx: Any = None) -> Dict[str, Any]:
    """Разведочный анализ: correlate (r между парами) или cluster (KMeans, seed).

    Результат ВСЕГДА помечается как гипотеза, требующая проверки (H.2)."""
    frame = population_frame(ctx)
    if scope_filters:
        tns = [r["tn"] for r in filter_population(scope_filters, ctx)["results"]]
        frame = frame.loc[[t for t in tns if t in frame.index]]
    numeric = [c for c in (variables or _NUMERIC_POP_FIELDS) if c in frame.columns]
    data = frame[numeric].apply(pd.to_numeric, errors="coerce")

    hypothesis_note = ("РЕЗУЛЬТАТ — ГИПОТЕЗА, требует проверки человеком. "
                       "Корреляция ≠ причинность; кластеры — описательные архетипы.")

    if method == "correlate":
        pairs = []
        cols = [c for c in numeric if data[c].notna().sum() >= 5]
        for i in range(len(cols)):
            for j in range(i + 1, len(cols)):
                a, b = data[cols[i]], data[cols[j]]
                valid = a.notna() & b.notna()
                if valid.sum() < 10 or a[valid].std() == 0 or b[valid].std() == 0:
                    continue
                r = float(np.corrcoef(a[valid], b[valid])[0, 1])
                if abs(r) >= 0.3:
                    pairs.append({"x": cols[i], "y": cols[j], "r": round(r, 3), "n": int(valid.sum())})
        pairs.sort(key=lambda p: abs(p["r"]), reverse=True)
        return {"method": "correlate", "scope_size": int(len(frame)),
                "значимые_связи": pairs[:20], "примечание": hypothesis_note}

    if method == "cluster":
        from sklearn.preprocessing import StandardScaler
        from sklearn.cluster import KMeans
        cols = [c for c in numeric if data[c].notna().sum() >= len(data) * 0.5]
        mat = data[cols].fillna(data[cols].median())
        if len(mat) < n_clusters:
            return {"method": "cluster", "error": "Недостаточно данных для кластеризации.",
                    "примечание": hypothesis_note}
        X = StandardScaler().fit_transform(mat.values)
        km = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        labels = km.fit_predict(X)
        clusters = []
        for c in range(n_clusters):
            idx = mat.index[labels == c]
            prof = {col: round(float(mat.loc[idx, col].mean()), 2) for col in cols}
            clusters.append({"cluster": int(c), "size": int(len(idx)),
                             "tns_примеры": [int(t) for t in list(idx)[:5]],
                             "средние_признаки": prof})
        return {"method": "cluster", "scope_size": int(len(frame)), "n_clusters": n_clusters,
                "features_used": cols, "clusters": clusters, "примечание": hypothesis_note}

    return {"error": f"Неизвестный метод '{method}'. Доступно: correlate, cluster."}
