"""
Слой извлечения признаков из текста (Часть C методологии + каталог D).

Все парсеры устойчивы к пропускам, словоформам и разделителям (перевод строки,
пробелы, `;`). Каждый возвращает структурированные записи И/ИЛИ производные
признаки. Числа из «Ключевых достижений» — самоописания (A.14.4): извлекаем
число, трактуем как сигнал, цитируем сырой фрагмент (доказуемость, Часть K).
"""

import re
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

import ontology as onto
from data_loader import parse_date_any, ANALYSIS_NOW


def _isna(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and np.isnan(v):
        return True
    s = str(v).strip().lower()
    return s in ("", "nan", "nat", "none")


def _lines(text: Any) -> List[str]:
    """Разбивает многострочное текстовое поле на непустые строки."""
    if _isna(text):
        return []
    parts = re.split(r"[\n;]+", str(text))
    return [p.strip() for p in parts if p.strip()]


# --- C.1 Парсер стажа --------------------------------------------------------
_YEAR_RE = re.compile(r"(\d+)\s*(?:год(?:а)?|лет)", re.IGNORECASE)
_MONTH_RE = re.compile(r"(\d+)\s*месяц(?:а|ев)?", re.IGNORECASE)


def parse_tenure(text: Any) -> Optional[float]:
    """«N лет M месяцев» (любые словоформы) → годы (float). Части могут отсутствовать."""
    if _isna(text):
        return None
    s = str(text).replace("\xa0", " ")
    years = 0.0
    found = False
    m = _YEAR_RE.search(s)
    if m:
        years += int(m.group(1))
        found = True
    m = _MONTH_RE.search(s)
    if m:
        years += int(m.group(1)) / 12.0
        found = True
    if not found:
        # Иногда только число — трактуем как годы.
        m = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*", s)
        if m:
            return float(m.group(1).replace(",", "."))
        return None
    return round(years, 3)


# --- C.2 Impact Ledger -------------------------------------------------------
# Шаблоны извлечения количественных результатов из «Ключевых достижений».
_IMPACT_PATTERNS = [
    # (metric_type, unit, direction, regex с группой числа)
    ("econ_effect", "млн_руб_год", "рост",
     re.compile(r"экономическ\w*\s+эффект\w*\D{0,30}?(\d[\d\s.,]*)\s*млн", re.IGNORECASE)),
    ("loss_prevented", "млн_руб", "рост",
     re.compile(r"предотвращ\w*\s+потер\w*\D{0,30}?(\d[\d\s.,]*)\s*млн", re.IGNORECASE)),
    ("team_size", "чел", None,
     re.compile(r"команд\w*\s+численность\w*\D{0,12}?(\d[\d\s]*)\s*человек", re.IGNORECASE)),
    ("sla", "%", None,
     re.compile(r"SLA\D{0,20}?(\d[\d.,]*)\s*%", re.IGNORECASE)),
    ("n_initiatives", "шт", None,
     re.compile(r"выведено\D{0,12}?(\d[\d\s]*)\s*инициатив", re.IGNORECASE)),
    ("releases", "шт", None,
     re.compile(r"подготовлен\w*\D{0,12}?(\d[\d\s]*)\s*(?:продуктов\w*\s+)?релиз", re.IGNORECASE)),
    ("growth_pp", "п.п.", "рост",
     re.compile(r"на\s+(\d[\d.,]*)\s*п\.?\s*п\.?", re.IGNORECASE)),
    ("growth_pct", "%", "рост",
     re.compile(r"(?:вырос\w*|увеличен\w*|повышен\w*)\D{0,18}?на\s+(\d[\d.,]*)\s*%", re.IGNORECASE)),
]
_CYCLE_RE = re.compile(r"с\s+(\d[\d\s]*)\s+до\s+(\d[\d\s]*)\s+дн", re.IGNORECASE)


def _to_number(s: str) -> Optional[float]:
    s = s.replace("\xa0", "").replace(" ", "").replace(",", ".")
    s = re.sub(r"\.(?=\d{3}\b)", "", s)  # 1.000 как разделитель тысяч — убрать
    try:
        return float(s)
    except ValueError:
        return None


def parse_impact_ledger(text: Any) -> Dict[str, Any]:
    """Извлекает количественные результаты из «Ключевые достижения» (C.2).

    Возвращает {records:[{metric_type,value,unit,direction,raw_sentence}], features:{...}}.
    Несколько записей на сотрудника; сырые фразы сохраняются для цитирования (Часть K).
    """
    records: List[Dict[str, Any]] = []
    if _isna(text):
        return {"records": [], "features": _empty_impact_features()}
    # Дробим на клаузы по переводу строки и `;` (НЕ по точке — иначе ломаются
    # десятичные числа вроде SLA 98.1%). Каждая клауза — кандидат на raw_sentence.
    sentences: List[str] = []
    for line in str(text).split("\n"):
        sentences.extend(line.split(";"))
    for sent in sentences:
        s = sent.strip()
        if not s:
            continue
        for mtype, unit, direction, rx in _IMPACT_PATTERNS:
            for m in rx.finditer(s):
                val = _to_number(m.group(1))
                if val is None:
                    continue
                records.append({"metric_type": mtype, "value": val, "unit": unit,
                                "direction": direction, "raw_sentence": s})
        for m in _CYCLE_RE.finditer(s):
            x, y = _to_number(m.group(1)), _to_number(m.group(2))
            if x is not None and y is not None:
                records.append({"metric_type": "cycle_reduction", "value": x - y, "unit": "дней",
                                "from": x, "to": y, "direction": "снижение", "raw_sentence": s})
    return {"records": records, "features": _impact_features(records)}


def _empty_impact_features() -> Dict[str, Any]:
    return {"impact_econ_total": 0.0, "impact_econ_max": 0.0, "impact_max_team": 0,
            "impact_loss_prevented_total": 0.0, "impact_n_initiatives": 0,
            "impact_has_sla99": False, "impact_sla_max": None,
            "impact_cycle_best_reduction": 0.0, "impact_cycle_best_ratio": 0.0,
            "impact_n_releases": 0, "impact_breadth": 0, "impact_n_records": 0}


def _impact_features(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    def vals(t):
        return [r["value"] for r in records if r["metric_type"] == t and r.get("value") is not None]
    econ = vals("econ_effect")
    team = vals("team_size")
    loss = vals("loss_prevented")
    inits = vals("n_initiatives")
    sla = vals("sla")
    releases = vals("releases")
    cycles = [r for r in records if r["metric_type"] == "cycle_reduction"]
    cycle_red = [c["value"] for c in cycles]
    cycle_ratio = [round(1 - c["to"] / c["from"], 3) for c in cycles if c.get("from")]
    types = {r["metric_type"] for r in records}
    return {
        "impact_econ_total": round(sum(econ), 2),
        "impact_econ_max": round(max(econ), 2) if econ else 0.0,
        "impact_max_team": int(max(team)) if team else 0,
        "impact_loss_prevented_total": round(sum(loss), 2),
        "impact_n_initiatives": int(sum(inits)) if inits else 0,
        "impact_has_sla99": any(v >= 99 for v in sla),
        "impact_sla_max": round(max(sla), 2) if sla else None,
        "impact_cycle_best_reduction": round(max(cycle_red), 1) if cycle_red else 0.0,
        "impact_cycle_best_ratio": max(cycle_ratio) if cycle_ratio else 0.0,
        "impact_n_releases": int(sum(releases)) if releases else 0,
        "impact_breadth": len(types),
        "impact_n_records": len(records),
    }


# --- C.3 Парсер наград -------------------------------------------------------
def parse_awards(text: Any) -> Dict[str, Any]:
    """Строки `Тип: YYYY-MM-DD` → записи + признаки престижа (B.5)."""
    records: List[Dict[str, Any]] = []
    for line in _lines(text):
        if ":" in line:
            atype, _, date_s = line.rpartition(":")
            atype = atype.strip()
            dt = parse_date_any(date_s.strip())
        else:
            atype, dt = line.strip(), None
        tier, weight = onto.award_tier(atype)
        records.append({"type": atype, "date": dt.strftime("%Y-%m-%d") if dt else None,
                        "tier": tier, "weight": weight,
                        "year": dt.year if dt else None})
    years = [r["year"] for r in records if r["year"]]
    return {"records": records, "features": {
        "awards_count": len(records),
        "awards_prestige_score": round(sum(r["weight"] for r in records), 2),
        "awards_top_tier": any(r["tier"] == "Президентский" for r in records),
        "last_award_year": max(years) if years else None,
    }}


# --- C.4 Парсер образования --------------------------------------------------
def parse_education(text: Any) -> Dict[str, Any]:
    """`ВУЗ,Специальность: ГОД` → записи + признаки (B.7)."""
    records: List[Dict[str, Any]] = []
    for line in _lines(text):
        year = None
        body = line
        if ":" in line:
            body, _, year_s = line.rpartition(":")
            dt = parse_date_any(year_s.strip())
            year = dt.year if dt else None
        vuz, spec = body, None
        if "," in body:
            vuz, _, spec = body.partition(",")
        vuz, spec = vuz.strip(), (spec.strip() if spec else None)
        records.append({"vuz": vuz, "spec": spec, "year": year,
                        "tier": onto.vuz_tier(vuz), "kind": onto.spec_kind(spec)})
    kinds = [r["kind"] for r in records]
    return {"records": records, "features": {
        "edu_degrees_count": len(records),
        "edu_is_stem": "STEM" in kinds,
        "edu_tier": next((r["tier"] for r in records if r["tier"]), None),
        "edu_has_second_higher": len(records) >= 2,
        "edu_mba_like": any(r["spec"] and "mba" in r["spec"].lower() for r in records)
                        or any(r["kind"] == "менеджмент/экономика" for r in records),
    }}


# --- C.5 Парсер курсов (два источника, К10) ---------------------------------
def _parse_course_line(line: str, source: str) -> Optional[Dict[str, Any]]:
    if not line.strip():
        return None
    year = None
    body = line
    if ":" in line:
        body, _, year_s = line.rpartition(":")
        dt = parse_date_any(year_s.strip())
        year = dt.year if dt else None
    body = body.strip()
    provider = None
    title = body
    # «Провайдер, Название» — провайдер до первой запятой, если распознан.
    if "," in body:
        cand_prov, _, rest = body.partition(",")
        if onto.course_provider_kind(cand_prov):
            provider = cand_prov.strip()
            title = rest.strip()
    full = f"{provider} {title}" if provider else title
    return {"title": title, "provider": provider, "year": year, "source": source,
            "provider_kind": onto.course_provider_kind(full),
            "theme": onto.course_theme(full)}


def parse_courses(profile_courses: Any, training_rows: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
    """Сливает профиль.«Курсы» (кураторская выжимка) и «обучение за 2 года» (журнал).

    Дедупликация по нормализованному названию (+год). Источник помечается.
    """
    records: List[Dict[str, Any]] = []
    for line in _lines(profile_courses):
        rec = _parse_course_line(line, "профиль")
        if rec:
            records.append(rec)
    if training_rows is not None and not training_rows.empty:
        for _, row in training_rows.iterrows():
            title = row.get("название курса")
            if _isna(title):
                continue
            dt = parse_date_any(row.get("дата завершения"))
            full = str(title)
            records.append({"title": str(title).strip(), "provider": None,
                            "year": dt.year if dt else None, "source": "обучение за 2 года",
                            "provider_kind": onto.course_provider_kind(full),
                            "theme": onto.course_theme(full),
                            "completed": dt.strftime("%Y-%m-%d") if dt else None})
    # Дедупликация по (нормализованное название, год); приоритет — запись с провайдером.
    seen: Dict[tuple, Dict[str, Any]] = {}
    for rec in records:
        key = (onto._norm(rec["title"]), rec.get("year"))
        if key not in seen:
            seen[key] = rec
        else:
            if rec.get("provider") and not seen[key].get("provider"):
                seen[key]["provider"] = rec["provider"]
                seen[key]["provider_kind"] = rec.get("provider_kind") or seen[key].get("provider_kind")
    deduped = list(seen.values())
    years = [r["year"] for r in deduped if r.get("year")]
    return {"records": deduped, "features": {
        "courses_count": len(deduped),
        "courses_ai_count": sum(1 for r in deduped if r.get("theme") == "AI/ML и данные"),
        "courses_leadership_count": sum(1 for r in deduped
                                        if r.get("theme") == "Лидерство/управление изменениями"),
        "courses_external_elite": any(r.get("provider_kind") == "элитный внешний" for r in deduped),
        "last_course_year": max(years) if years else None,
        "courses_themes": sorted({r["theme"] for r in deduped if r.get("theme")}),
    }}


# --- C.6 Парсер языков -------------------------------------------------------
def parse_languages(text: Any) -> Dict[str, Any]:
    """`Язык: Уровень / Подпись` → записи + признаки (B.9)."""
    records: List[Dict[str, Any]] = []
    for line in _lines(text):
        if ":" not in line:
            continue
        lang, _, rest = line.partition(":")
        level = rest.strip().split("/")[0].strip()
        ordv = onto.cefr_ordinal(level)
        records.append({"lang": lang.strip(), "cefr": level if ordv else None, "cefr_ordinal": ordv,
                        "strategic": onto.is_strategic_language(lang)})
    eng = next((r["cefr_ordinal"] for r in records if "англ" in onto._norm(r["lang"])), None)
    above_a2 = [r for r in records if (r["cefr_ordinal"] or 0) >= 3]
    return {"records": records, "features": {
        "lang_count": len(records),
        "english_cefr_ordinal": eng,
        "english_cefr": next((r["cefr"] for r in records if "англ" in onto._norm(r["lang"])), None),
        "multilingual": len(above_a2) >= 2,
        "has_strategic_language": any(r["strategic"] for r in records),
    }}


# --- C.7 Активности и научная деятельность ----------------------------------
def parse_activities(text: Any) -> Dict[str, Any]:
    """«Корпоративные активности» `Название: ГОД` → типы, свежесть, лидерская видимость."""
    records: List[Dict[str, Any]] = []
    for line in _lines(text):
        year = None
        name = line
        if ":" in line:
            name, _, year_s = line.rpartition(":")
            dt = parse_date_any(year_s.strip())
            year = dt.year if dt else None
        name = name.strip()
        records.append({"name": name, "year": year, "type": onto.activity_type(name),
                        "is_strategy_facilitation": onto.is_strategy_facilitation(name)})
    years = [r["year"] for r in records if r["year"]]
    return {"records": records, "features": {
        "activities_count": len(records),
        "activities_recency": (ANALYSIS_NOW.year - max(years)) if years else None,
        "has_strategy_facilitation": any(r["is_strategy_facilitation"] for r in records),
        "engagement_breadth": len({r["type"] for r in records if r["type"]}),
    }}


def parse_science(text: Any) -> Dict[str, Any]:
    """«Научная деятельность» (без даты) → has_publications, число."""
    lines = _lines(text)
    return {"records": lines, "features": {
        "has_publications": len(lines) > 0, "n_publications": len(lines)}}


def parse_degrees(text: Any) -> Dict[str, Any]:
    """«Учёные степени» `Степень: YYYY-MM-DD` → has_degree, тип. Пропуск ≠ отсутствие."""
    records: List[Dict[str, Any]] = []
    for line in _lines(text):
        deg, year = line, None
        if ":" in line:
            deg, _, date_s = line.rpartition(":")
            dt = parse_date_any(date_s.strip())
            year = dt.year if dt else None
        records.append({"degree": deg.strip(), "year": year})
    return {"records": records, "features": {
        "has_degree": len(records) > 0,
        "degree_types": [r["degree"] for r in records]}}


def parse_interests(text: Any) -> Dict[str, Any]:
    """Интересы (мягкий лайфстайл-прокси; НЕ фактор кадрового решения, Часть L)."""
    items = []
    for line in _lines(text):
        for token in re.split(r"[,\s]+", line):
            t = token.strip()
            if t:
                items.append(t)
    cats = {}
    for it in items:
        c = onto.interest_category(it)
        if c:
            cats.setdefault(c, []).append(it)
    return {"records": items, "features": {
        "interests_count": len(items),
        "interests_categories": sorted(cats.keys()),
    }}


# --- C.8 HTML-выводы паутинки (К11) -----------------------------------------
def parse_html_conclusion(html: Any) -> Dict[str, Any]:
    """Снимает HTML и извлекает секции «За счёт чего достигает результата» и «Зоны роста».

    Использует stdlib (html.parser) для устойчивости без внешних зависимостей.
    """
    if _isna(html):
        return {"strengths": None, "growth_zones": None, "sections": {}, "plain": None}
    raw = str(html)
    # Разбиваем по <span>…</span>-якорям, между которыми — текст секции.
    # Заменяем <br/> на перевод строки, снимаем прочие теги.
    spans = re.findall(r"<span>(.*?)</span>(.*?)(?=<span>|$)", raw, flags=re.IGNORECASE | re.DOTALL)
    sections: Dict[str, str] = {}
    for header, body in spans:
        h = _strip_tags(header)
        b = _strip_tags(body)
        if h:
            sections[h] = b
    plain = _strip_tags(raw)

    def find_section(keywords: List[str]) -> Optional[str]:
        for h, b in sections.items():
            hl = onto._norm(h)
            if any(onto._norm(k) in hl for k in keywords):
                return b.strip() or None
        return None

    return {
        "strengths": find_section(["за счет чего достигает результата", "за счёт чего"]),
        "growth_zones": find_section(["зоны роста", "зона роста"]),
        "sections": sections,
        "plain": plain.strip() or None,
    }


def _strip_tags(s: str) -> str:
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", " ", s)
    s = s.replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n", s)
    return s.strip()


# --- C.10 / A.5 нормализация «опыта» ----------------------------------------
def normalize_minmax(value: float, lo: float, hi: float) -> Optional[float]:
    """min–max нормализация в [0,1]. Для «опыта» (≈70–100) — НЕ делить на 100 (К5)."""
    if value is None or hi is None or lo is None or hi == lo:
        return None
    return round(max(0.0, min(1.0, (value - lo) / (hi - lo))), 4)


def percentile_rank(value: Optional[float], population: List[float]) -> Optional[float]:
    """Перцентильный ранг значения в популяции [0,1] (для разнородных по масштабу метрик)."""
    pop = [p for p in population if p is not None and not (isinstance(p, float) and np.isnan(p))]
    if value is None or not pop:
        return None
    below = sum(1 for p in pop if p < value)
    equal = sum(1 for p in pop if p == value)
    return round((below + 0.5 * equal) / len(pop), 4)


# --- Оценки (К2/К3/К4) -------------------------------------------------------
RESULT_ORDINAL = {"B": 3, "C": 2, "D": 1}
VALUES_ORDINAL = {"B": 3, "C": 2}


def eval_to_ordinal(code: Any, kind: str = "result") -> Optional[int]:
    c = str(code).strip().upper()
    table = RESULT_ORDINAL if kind == "result" else VALUES_ORDINAL
    return table.get(c)
