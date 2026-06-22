"""
Разрешение сущностей (Часть G методологии).

  * `resolve_person` — ФИО (полное/частичное) или `tn` → кандидаты с
    дизамбигуаторами; при >1 совпадении `needs_clarification=True`,
    никогда не «угадывать» одного из многих молча (G.1).
  * `resolve_role_block` — роль/блок/англоназвание → сущности данных;
    протокол «нет точного совпадения» и обработка несуществующих блоков
    («Финансы») — не подменять молча (B.1/B.4/G.2).

Все результаты сверяются с ФАКТИЧЕСКИМИ значениями данных (масштабонезависимо):
канон из онтологии-сида подтверждается через `distinct_values`.
"""

import re
from typing import Any, Dict, List, Optional

import data_loader as dl
import ontology as onto


def _norm(s: Any) -> str:
    return onto._norm(s)


# --- G.1 Человек -------------------------------------------------------------
def resolve_person(query: Any, ctx: Any = None,
                   block: Optional[str] = None, role: Optional[str] = None,
                   tb: Optional[str] = None, grade: Optional[int] = None) -> Dict[str, Any]:
    """Разрешает человека по ФИО (полному/частичному) или табельному номеру.

    Дополнительные дизамбигуаторы (block/role/tb/grade) сужают список омонимов.
    Возвращает словарь с кандидатами и флагом needs_clarification.
    """
    prof = dl.get_sheet(dl.SHEET_PROFILE, ctx)
    q = str(query).strip()

    # Если запрос — табельный номер.
    digits = re.fullmatch(r"\d{3,}", q.replace(" ", ""))
    if digits:
        tn = int(q.replace(" ", ""))
        sub = prof[prof["tn"] == tn]
        cands = _to_candidates(sub)
        return {"query": query, "resolved": cands[0] if len(cands) == 1 else None,
                "candidates": cands, "needs_clarification": False,
                "found": len(cands) > 0,
                "message": None if cands else f"Сотрудник с табельным номером {tn} не найден в данных."}

    # Поиск по ФИО (полное / частичное / по фамилии).
    qn = _norm(q)
    fio_norm = prof["ФИО"].map(_norm)
    # Точное совпадение полного ФИО.
    mask = fio_norm == qn
    if not mask.any():
        # Совпадение по токенам (все слова запроса входят в ФИО).
        q_tokens = [t for t in qn.split() if t]
        if q_tokens:
            mask = fio_norm.map(lambda f: all(tok in f.split() for tok in q_tokens))
        if not mask.any():
            # Частичное вхождение (фамилия/подстрока).
            mask = fio_norm.str.contains(re.escape(qn), na=False)

    sub = prof[mask].copy()

    # Применить дизамбигуаторы запроса.
    applied = {}
    if not sub.empty and block:
        rb = resolve_role_block(block_query=block, ctx=ctx)
        if rb.get("resolved_block"):
            sub2 = sub[sub["Функциональный блок"] == rb["resolved_block"]]
            if not sub2.empty:
                sub, applied["block"] = sub2, rb["resolved_block"]
    if not sub.empty and role:
        rn = _norm(role)
        sub2 = sub[sub["Роль"].map(lambda r: rn in _norm(r))]
        if not sub2.empty:
            sub, applied["role"] = sub2, role
    if not sub.empty and tb:
        tn_norm = _norm(tb)
        sub2 = sub[sub["ЦА\\ТБ\\ПЦП"].map(lambda r: tn_norm in _norm(r))]
        if not sub2.empty:
            sub, applied["tb"] = sub2, tb
    if not sub.empty and grade is not None:
        sub2 = sub[sub["Грейд"] == int(grade)]
        if not sub2.empty:
            sub, applied["grade"] = sub2, int(grade)

    cands = _to_candidates(sub)
    found = len(cands) > 0
    needs = len(cands) > 1
    msg = None
    if not found:
        msg = (f"Человек по запросу «{query}» не найден. Возможные причины: "
               f"вне целевой выборки руководящего корпуса, иное написание ФИО, "
               f"или поиск следует вести по табельному номеру.")
    elif needs:
        msg = (f"Найдено несколько кандидатов ({len(cands)}) по запросу «{query}». "
               f"Уточните по блоку/роли/ТБ/грейду или укажите табельный номер.")
    return {"query": query, "resolved": cands[0] if found and not needs else None,
            "candidates": cands, "needs_clarification": needs, "found": found,
            "applied_disambiguators": applied, "message": msg}


def _to_candidates(sub) -> List[Dict[str, Any]]:
    out = []
    for _, r in sub.iterrows():
        out.append({
            "tn": int(r["tn"]),
            "ФИО": r.get("ФИО"),
            "блок": r.get("Функциональный блок"),
            "роль": r.get("Роль"),
            "грейд": int(r["Грейд"]) if dl.pd.notna(r.get("Грейд")) else None,
            "ЦА/ТБ": r.get("ЦА\\ТБ\\ПЦП"),
            "тир_роли": onto.role_tier(r.get("Роль")),
            "семейство_роли": onto.role_family(r.get("Роль")),
        })
    return out


# --- G.2 Роль и блок ---------------------------------------------------------
def resolve_role_block(role_query: Optional[str] = None, block_query: Optional[str] = None,
                       ctx: Any = None) -> Dict[str, Any]:
    """Сопоставляет роль/блок/англоназвание запроса с фактическими значениями данных.

    Протокол «нет совпадения» (B.4): не выдумывать; предложить ближайшие;
    зафиксировать допущение; при неоднозначности — needs_clarification.
    """
    actual_blocks = list(dl.distinct_values("Функциональный блок", ctx=ctx).keys())
    actual_roles = list(dl.distinct_values("Роль", ctx=ctx).keys())

    assumptions: List[str] = []
    alternatives: List[str] = []
    candidates_roles: List[str] = []
    needs_clarification = False
    resolved_block: Optional[str] = None
    resolved_role_family: Optional[str] = None
    notes: List[str] = []

    combined = " ".join([x for x in [role_query, block_query] if x])

    # 1) Англоязычная/неформальная должность (CDS, CISO, CFO …).
    title = onto.match_role_title(combined) if combined else None
    if title:
        resolved_role_family = title.get("family")
        if title.get("block") and title["block"] in actual_blocks:
            resolved_block = title["block"]
            assumptions.append(
                f"Трактую «{combined.strip()}» как руководящие роли семейства "
                f"«{resolved_role_family}» в блоке «{resolved_block}».")
        elif title.get("family") == "финансы":
            # CFO / финансовый контур — блока «Финансы» нет.
            notes.append("Блока «Финансы»/«финансовый блок» в данных нет.")
            hint = onto.NONEXISTENT_BLOCK_HINTS["финансы"]
            for b, desc in hint["nearest"]:
                if b in actual_blocks:
                    alternatives.append(f"{b} ({desc})")
            needs_clarification = True
        # Якорные роли, реально присутствующие в данных.
        for ar in title.get("anchor_roles", []):
            if ar in actual_roles:
                candidates_roles.append(ar)

    # 2) Явный блок в запросе.
    if block_query:
        ne = onto.nonexistent_block_hint(block_query)
        if ne:
            notes.append(ne["message"])
            for b, desc in ne["nearest"]:
                if b in actual_blocks and f"{b} ({desc})" not in alternatives:
                    alternatives.append(f"{b} ({desc})")
            needs_clarification = True
        else:
            canon = onto.match_block_synonym(block_query)
            if canon and canon in actual_blocks:
                resolved_block = canon
                if _norm(canon) != _norm(block_query):
                    assumptions.append(f"Блок «{block_query}» сопоставлен с «{canon}» в данных.")
            elif canon and canon not in actual_blocks:
                notes.append(f"Блок «{canon}» из онтологии отсутствует в текущих данных.")
                needs_clarification = True
            else:
                # Прямое частичное совпадение с фактическим блоком.
                hit = next((b for b in actual_blocks if _norm(block_query) in _norm(b)
                            or _norm(b) in _norm(block_query)), None)
                if hit:
                    resolved_block = hit
                else:
                    notes.append(f"Блок «{block_query}» не найден среди фактических блоков данных.")
                    alternatives = [f"{b}" for b in actual_blocks]
                    needs_clarification = True

    # 3) Семейство роли из текста роли (если ещё не задано).
    if role_query and not resolved_role_family:
        resolved_role_family = onto.role_family(role_query)

    # 4) Кандидатные роли по семейству/тексту, реально присутствующие в данных.
    if not candidates_roles:
        rq = _norm(role_query) if role_query else ""
        for rname in actual_roles:
            score = 0
            if rq and rq in _norm(rname):
                score += 2
            if resolved_role_family and onto.role_family(rname) == resolved_role_family:
                score += 1
            if score:
                candidates_roles.append(rname)
        # Уникализируем, сохраняя порядок.
        seen = set()
        candidates_roles = [r for r in candidates_roles if not (r in seen or seen.add(r))]

    return {
        "role_query": role_query,
        "block_query": block_query,
        "resolved_block": resolved_block,
        "resolved_role_family": resolved_role_family,
        "candidate_roles": candidates_roles,
        "assumptions": assumptions,
        "alternatives": alternatives,
        "notes": notes,
        "needs_clarification": needs_clarification,
        "actual_blocks": actual_blocks,
    }
