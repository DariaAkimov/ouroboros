"""
Тул ``get_employee_profile`` — нормализованный профиль одного сотрудника.

Собирает данные по всем 12 листам + производные признаки (стаж-float, сводка
Impact Ledger, тиры наград, компетенции SberQ 4.0, последняя оценка/тренд, история
грейдов, языки, образование, цели) и сырьё для цитирования (evidence). Тонкая
обёртка над ``analysis.build_features``. Принимает ``tn`` (из ``resolve_person``).
"""

import logging

from ._common import envelope, ToolContext, ToolEntry

import analysis as A

log = logging.getLogger(__name__)


def handler(ctx: ToolContext, **kwargs) -> str:
    tn = kwargs.get("tn")
    if tn is None:
        return envelope(None, ok=False,
                        data_gaps=["Не указан параметр 'tn' (табельный номер). Сначала используйте resolve_person."])
    try:
        tn = int(tn)
    except (ValueError, TypeError):
        return envelope(None, ok=False, data_gaps=[f"Некорректный табельный номер: {tn!r}."])
    try:
        bf = A.build_features(tn, ctx)
        if not bf["found"]:
            return envelope({"tn": tn, "found": False}, ok=True,
                            data_gaps=bf["data_gaps"],
                            extra={"message": f"Профиль {tn} не найден."})
        feats = bf["features"]
        sections = kwargs.get("sections")
        if sections:
            feats = {k: v for k, v in feats.items() if any(s in k for s in sections)}
        return envelope({"tn": tn, "identity": bf["identity"], "features": feats},
                        evidence=bf["evidence"], data_gaps=bf["data_gaps"])
    except Exception as e:  # pragma: no cover
        log.error("get_employee_profile: %s", e)
        return f"⚠️ Не удалось собрать профиль: {e}"


SCHEMA = {
    "name": "get_employee_profile",
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
        "required": ["tn"]},
}

TOOL = ToolEntry(name="get_employee_profile", schema=SCHEMA, handler=handler,
                 is_code_tool=False, timeout_sec=20)
