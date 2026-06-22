"""
Общая инфраструктура пакета тулов: контракт фреймворка + конверт ответа §4.

Каждый тул лежит в собственном модуле ``tools/<имя_тула>.py`` (хэндлер + schema +
``ToolEntry``) и импортирует отсюда:

* ``ToolContext`` / ``ToolEntry`` — контракт реестра (настоящий ``ouroboros`` в
  продуктиве, иначе локальный стаб ``_framework``);
* ``envelope`` — сборка единого JSON-конверта §4
  ``{ok, data, evidence, assumptions, data_gaps, needs_clarification, scale_note}``;
* ``SCALE_NOTE`` — стандартная пометка о масштабонезависимости.

Здесь же лежит сериализатор numpy/pandas → JSON, чтобы хэндлеры не дублировали его.
"""

import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

# Бизнес-слои скилла (analysis/data_loader/parsers/resolve/ontology) лежат В КОРНЕ
# пакета, а не внутри него. Гарантируем, что корень на sys.path до их импорта —
# независимо от того, как был загружен пакет (по имени или по пути).
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import numpy as np

# Контракт фреймворка: в продуктиве — настоящий ouroboros; иначе локальный стаб.
try:  # pragma: no cover
    from ouroboros.tools.registry import ToolContext, ToolEntry
except ImportError:  # pragma: no cover
    from _framework import ToolContext, ToolEntry

__all__ = ["ToolContext", "ToolEntry", "envelope", "json_default", "SCALE_NOTE"]

SCALE_NOTE = ("Значения справочников и пороги получены из данных в рантайме, "
              "не зашиты; популяция — выборка, в проде записей больше.")


def json_default(o: Any):
    """Сериализация numpy/pandas-типов и дат в JSON-совместимые значения."""
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


def envelope(data: Any, evidence: Optional[List] = None, assumptions: Optional[List] = None,
             data_gaps: Optional[List] = None, needs_clarification: bool = False,
             ok: bool = True, extra: Optional[Dict] = None) -> str:
    """Собирает единый конверт ответа тула (§4) и сериализует его в JSON-строку."""
    obj = {
        "ok": ok,
        "data": data,
        "evidence": evidence or [],
        "assumptions": assumptions or [],
        "data_gaps": data_gaps or [],
        "needs_clarification": bool(needs_clarification),
        "scale_note": SCALE_NOTE,
    }
    if extra:
        obj.update(extra)
    return json.dumps(obj, ensure_ascii=False, default=json_default)
