"""
Тул ``extract_impact`` — Impact Ledger (Часть C.2) по одному tn или когорте.

Структурирует количественные результаты из «Ключевых достижений» (эконом-эффект,
размер команды, SLA, сокращение цикла, число инициатив …) + СЫРЫЕ фрагменты для
цитирования. Числа — самоописания, не аудит (A.14.4). Обёртка над
``parsers.parse_impact_ledger``.
"""

import logging

from ._common import envelope, ToolContext, ToolEntry

import data_loader as dl
import parsers as P

log = logging.getLogger(__name__)


def handler(ctx: ToolContext, **kwargs) -> str:
    tn = kwargs.get("tn")
    tns = kwargs.get("tns")
    if tn is None and not tns:
        return envelope(None, ok=False, data_gaps=["Укажите 'tn' или 'tns'."])
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
        return envelope({"employees": out}, evidence=evidence, data_gaps=gaps)
    except Exception as e:  # pragma: no cover
        log.error("extract_impact: %s", e)
        return f"⚠️ Не удалось извлечь Impact Ledger: {e}"


SCHEMA = {
    "name": "extract_impact",
    "description": "Impact Ledger (Часть C.2) по одному tn или когорте: структурированные "
                   "количественные результаты из «Ключевых достижений» (эконом-эффект млн ₽/год, "
                   "размер команды, SLA %, сокращение цикла, число инициатив, предотвращённые "
                   "потери, релизы, рост в п.п./%) + СЫРЫЕ фрагменты для цитирования. "
                   "Числа — самоописания, не аудит.",
    "parameters": {"type": "object", "properties": {
        "tn": {"type": "integer", "description": "Один табельный номер."},
        "tns": {"type": "array", "items": {"type": "integer"}, "description": "Когорта табельных номеров."}},
        "required": []},
}

TOOL = ToolEntry(name="extract_impact", schema=SCHEMA, handler=handler,
                 is_code_tool=False, timeout_sec=30)
