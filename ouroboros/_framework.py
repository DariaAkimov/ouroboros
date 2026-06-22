"""
Резервная (fallback) реализация контракта фреймворка инструментов `ouroboros`.

В продуктиве используется настоящий модуль ``ouroboros.tools.registry``
(см. ``tool_example.py``). Этот стаб подключается только если настоящий пакет
недоступен (например, при автономном прогоне тестов скилла), чтобы импорт
``from ouroboros.tools.registry import ToolContext, ToolEntry`` не падал и
структура регистрации тулов оставалась идентичной эталону.

Контракт повторяет поля, используемые в ``tool_example.py``:
    ToolEntry(name=..., schema={...}, handler=..., is_code_tool=False, timeout_sec=...)
    handler(ctx: ToolContext, **kwargs) -> str
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional


@dataclass
class ToolContext:
    """Контекст исполнения тула.

    Может нести конфигурацию, путь к данным и общий кэш. Слой данных
    (`data_loader`) использует `xlsx_path`/`config['xlsx_path']`, если они заданы,
    иначе берёт путь из переменной окружения ``EMPLO_XLSX_PATH`` либо дефолт.
    """

    config: Dict[str, Any] = field(default_factory=dict)
    xlsx_path: Optional[str] = None
    cache: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolEntry:
    """Описание одного инструмента для реестра агента."""

    name: str
    schema: Dict[str, Any]
    handler: Callable[..., str]
    is_code_tool: bool = False
    timeout_sec: int = 30
