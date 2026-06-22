"""
Слой данных HR-агента: загрузка и нормализация 12 листов `emplo.xlsx`.

Реализует:
  * единый ключ `tn` (int) с нормализацией имени столбца по листам (К1, A.0);
  * нормализацию «грязных» заголовков (двойные пробелы, `\\n`, `\\xa0`);
  * толерантный парсер дат по реестру форматов (К8, A.13);
  * кэш загруженного файла (детерминизм, переиспользование между тулами);
  * интроспекцию справочников `distinct_values` для масштабонезависимости.

Масштабонезависимость: модуль НЕ хранит число сотрудников/закрытые перечни
блоков/ролей как источник истины — все фактические значения извлекаются из
файла в рантайме. Имена листов — структурные константы схемы, а не данные.
"""

import logging
import os
import re
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# --- Канонические имена листов (структура схемы, не данные) -----------------
SHEET_PROFILE = "профиль"
SHEET_SBERQ_FOCUS = "Паутинка (sberq и фокусные)"
SHEET_SBERTESTS = "Паутинка (сбертесты)"
SHEET_EXPERIENCE = "Паутинка (опыт)"
SHEET_CONCLUSIONS = "паутинка (выводы)"
SHEET_TRAINING = "обучение за 2 года"
SHEET_EVALUATIONS = "оценки за 5 лет"
SHEET_GOALS = "цели 2026"
SHEET_GRADE_CHANGES = "изменения грейдов за 5 лет"
SHEET_SBERQ_10 = "SberQ 1.0"
SHEET_SBERQ_30 = "SberQ 3.0"
SHEET_SBERQ_40 = "SberQ 4.0"

# Имена ключевого столбца, встречающиеся на разных листах (К1 / A.0).
# Сравнение идёт по НОРМАЛИЗОВАННОМУ заголовку (нижний регистр, схлопнутые пробелы).
_KEY_ALIASES = {"табельный номер", "тн", "tn", "табельный №", "табельный n"}

# Канонический год «сейчас» = год анализа (A.13). Берётся из окружения, дефолт 2026.
ANALYSIS_YEAR = int(os.environ.get("HR_ANALYSIS_YEAR", "2026"))
ANALYSIS_NOW = datetime(ANALYSIS_YEAR, 6, 30)

_DEFAULT_FILENAME = "emplo.xlsx"

# Кэш: ключ = (abspath, mtime) -> {sheet_name: DataFrame}
_CACHE: Dict[tuple, Dict[str, pd.DataFrame]] = {}
_CACHE_LOCK = threading.Lock()


# --- Нормализация заголовков и ключа ----------------------------------------
def normalize_header(name: Any) -> str:
    """Чистит заголовок столбца: NBSP→пробел, схлопывание пробельных, strip.

    Сохраняет содержательные символы (включая бэкслеши в `ЦА\\ТБ\\ПЦП`).
    """
    s = str(name).replace("\xa0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _looks_like_key(header_norm: str) -> bool:
    return header_norm.strip().lower() in _KEY_ALIASES


def _normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Нормализует заголовки и приводит ключевой столбец к `tn` (int)."""
    df = df.copy()
    df.columns = [normalize_header(c) for c in df.columns]

    # Найти и переименовать ключевой столбец в канон `tn`.
    key_col = None
    for c in df.columns:
        if _looks_like_key(c):
            key_col = c
            break
    if key_col is not None:
        if key_col != "tn":
            df = df.rename(columns={key_col: "tn"})
        # Привести значения к целому; нечисловые → NaN, затем nullable Int.
        df["tn"] = pd.to_numeric(df["tn"], errors="coerce").astype("Int64")

    # Тримминг строковых ячеек (сохраняем оригинальный регистр для вывода).
    for c in df.columns:
        if df[c].dtype == object:
            df[c] = df[c].map(lambda v: v.strip() if isinstance(v, str) else v)
    return df


# --- Разрешение пути и загрузка ---------------------------------------------
def resolve_xlsx_path(ctx: Any = None) -> str:
    """Определяет путь к `emplo.xlsx`.

    Приоритет: ctx.xlsx_path → ctx.config['xlsx_path'] → env EMPLO_XLSX_PATH →
    файл рядом с этим модулем.
    """
    if ctx is not None:
        path = getattr(ctx, "xlsx_path", None)
        if path:
            return str(path)
        cfg = getattr(ctx, "config", None)
        if isinstance(cfg, dict) and cfg.get("xlsx_path"):
            return str(cfg["xlsx_path"])
    env = os.environ.get("EMPLO_XLSX_PATH")
    if env:
        return env
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), _DEFAULT_FILENAME)


def load_workbook(ctx: Any = None, path: Optional[str] = None) -> Dict[str, pd.DataFrame]:
    """Загружает все листы, нормализует и кэширует. Детерминированно."""
    path = path or resolve_xlsx_path(ctx)
    abspath = os.path.abspath(path)
    if not os.path.exists(abspath):
        raise FileNotFoundError(
            f"Файл данных не найден по пути: {abspath}. "
            f"Задайте переменную окружения EMPLO_XLSX_PATH или ctx.xlsx_path."
        )
    mtime = os.path.getmtime(abspath)
    cache_key = (abspath, mtime)
    with _CACHE_LOCK:
        if cache_key in _CACHE:
            return _CACHE[cache_key]
    raw = pd.read_excel(abspath, sheet_name=None, engine="openpyxl")
    normalized = {name: _normalize_dataframe(df) for name, df in raw.items()}
    with _CACHE_LOCK:
        _CACHE[cache_key] = normalized
    return normalized


def get_sheet(name: str, ctx: Any = None) -> pd.DataFrame:
    """Возвращает нормализованный DataFrame листа с ключом `tn`."""
    wb = load_workbook(ctx)
    if name not in wb:
        # Терпимый матчинг по нормализованному имени (на случай мелких отличий).
        target = normalize_header(name).lower()
        for k in wb:
            if normalize_header(k).lower() == target:
                return wb[k]
        raise KeyError(f"Лист '{name}' отсутствует в книге. Доступны: {list(wb)}")
    return wb[name]


def get_profile_row(tn: int, ctx: Any = None) -> Optional[pd.Series]:
    """Строка профиля одного сотрудника по `tn` (или None)."""
    prof = get_sheet(SHEET_PROFILE, ctx)
    sub = prof[prof["tn"] == int(tn)]
    if sub.empty:
        return None
    return sub.iloc[0]


def get_rows_for(name: str, tn: int, ctx: Any = None) -> pd.DataFrame:
    """Все строки листа `name` для сотрудника `tn` (для многострочных листов)."""
    df = get_sheet(name, ctx)
    if "tn" not in df.columns:
        return df.iloc[0:0]
    return df[df["tn"] == int(tn)]


# --- Интроспекция справочников (масштабонезависимое обнаружение) -------------
def distinct_values(field: str, sheet: str = SHEET_PROFILE, ctx: Any = None) -> Dict[str, int]:
    """Возвращает {значение: количество} по полю листа, упорядоченно по убыванию.

    Поддерживает терпимый матчинг имени поля (по нормализованному заголовку).
    """
    df = get_sheet(sheet, ctx)
    col = _match_column(df, field)
    if col is None:
        raise KeyError(
            f"Поле '{field}' не найдено на листе '{sheet}'. Доступные поля: {list(df.columns)}"
        )
    vc = df[col].dropna()
    # Для строк нормализуем пробелы при подсчёте, но возвращаем оригинал.
    counts = vc.value_counts()
    return {str(k): int(v) for k, v in counts.items()}


def _match_column(df: pd.DataFrame, field: str) -> Optional[str]:
    """Находит реальный столбец по точному или нормализованному имени."""
    if field in df.columns:
        return field
    target = normalize_header(field).lower()
    for c in df.columns:
        if normalize_header(c).lower() == target:
            return c
    # Частичное совпадение (для длинных «грязных» заголовков вроде коэффициента).
    for c in df.columns:
        if target and target in normalize_header(c).lower():
            return c
    return None


def column(df: pd.DataFrame, field: str) -> Optional[pd.Series]:
    """Безопасный доступ к столбцу по терпимому имени (или None)."""
    col = _match_column(df, field)
    return df[col] if col is not None else None


def all_tns(ctx: Any = None) -> List[int]:
    """Все табельные номера популяции (из профиля)."""
    prof = get_sheet(SHEET_PROFILE, ctx)
    return [int(x) for x in prof["tn"].dropna().tolist()]


# --- Парсер дат по реестру форматов (К8 / A.13) -----------------------------
_DATE_FORMATS = [
    ("%Y-%m-%d %H:%M:%S", "datetime"),   # обучение за 2 года
    ("%Y-%m-%d", "date"),                # награды, учёные степени
    ("%d.%m.%Y", "date"),                # цели, изменения грейдов
]


def parse_date_any(value: Any, year_only_month: int = 7, year_only_day: int = 1) -> Optional[datetime]:
    """Толерантный парсер дат: поддерживает 4 формата из A.13 + «только год».

    «Только год» (курсы/образование/активности) → 1 июля этого года (для
    упорядочивания). Невалидное значение → None (никогда не падает).
    Никогда не сравнивать строковые даты лексикографически — только через эту ф-ю.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (pd.Timestamp,)):
        return value.to_pydatetime()
    s = str(value).strip()
    if not s or s.lower() in ("nan", "nat", "none"):
        return None
    # Полные форматы.
    for fmt, _ in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    # Только год (4 цифры).
    m = re.fullmatch(r"(\d{4})", s)
    if m:
        return datetime(int(m.group(1)), year_only_month, year_only_day)
    # Год внутри строки (например «: 2024» уже вырезан парсерами; на всякий случай).
    m = re.search(r"\b(19|20)\d{2}\b", s)
    if m:
        try:
            return datetime(int(m.group(0)), year_only_month, year_only_day)
        except ValueError:
            return None
    return None


def years_since(value: Any) -> Optional[float]:
    """Свежесть в годах от даты до точки анализа (ANALYSIS_NOW)."""
    dt = parse_date_any(value)
    if dt is None:
        return None
    return round((ANALYSIS_NOW - dt).days / 365.25, 2)


def clear_cache() -> None:
    """Сброс кэша (для тестов/перезагрузки)."""
    with _CACHE_LOCK:
        _CACHE.clear()


# --- Удобный список листов (для документации/диагностики) -------------------
def sheet_names(ctx: Any = None) -> List[str]:
    return list(load_workbook(ctx).keys())
