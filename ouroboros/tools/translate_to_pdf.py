"""
Инструмент для создания PDF с переводом новости на русский язык.
Использует fpdf2 + LiberationSerif для качественной кириллицы.

PDF содержит ТОЛЬКО русский текст:
- Заголовок новости на русском
- Дату
- Ссылку на источник
- Качественный перевод

Без секции «Original (English)» — по указанию darya9daria.
"""

import logging
import os
import tempfile
from datetime import datetime

from fpdf import FPDF

from ouroboros.tools.registry import ToolContext, ToolEntry

log = logging.getLogger(__name__)

# Путь к шрифтам Liberation Serif (полная поддержка кириллицы)
FONT_DIR = "/usr/share/fonts/truetype/liberation"
FONT_REGULAR = os.path.join(FONT_DIR, "LiberationSerif-Regular.ttf")
FONT_BOLD = os.path.join(FONT_DIR, "LiberationSerif-Bold.ttf")
FONT_ITALIC = os.path.join(FONT_DIR, "LiberationSerif-Italic.ttf")
FONT_BI = os.path.join(FONT_DIR, "LiberationSerif-BoldItalic.ttf")

# Запасной путь для Google Colab
if not os.path.exists(FONT_REGULAR):
    FONT_DIR_ALT = "/usr/share/fonts/truetype/dejavu"
    FONT_REGULAR = os.path.join(FONT_DIR_ALT, "DejaVuSans.ttf")
    FONT_BOLD = os.path.join(FONT_DIR_ALT, "DejaVuSans-Bold.ttf")
    FONT_ITALIC = os.path.join(FONT_DIR_ALT, "DejaVuSans-Oblique.ttf")
    FONT_BI = os.path.join(FONT_DIR_ALT, "DejaVuSans-BoldOblique.ttf")


def _sanitise_filename(title: str) -> str:
    """Превращает заголовок в безопасное имя файла."""
    keep = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ _-"
    safe = "".join(c if c in keep else "_" for c in title)
    safe = safe.strip().replace(" ", "_")[:80]
    return safe or "translated_news"


def create_pdf(russian_text: str, title: str, source_url: str = "") -> str:
    """
    Создаёт PDF с русским переводом новости.

    Args:
        russian_text: качественный перевод новости на русский язык
        title: заголовок новости на русском
        source_url: ссылка на оригинальный источник (опционально)

    Returns:
        str: путь к созданному PDF-файлу
    """
    if not russian_text.strip():
        raise ValueError("Текст перевода пуст")
    if not title.strip():
        raise ValueError("Заголовок пуст")

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # Подключаем шрифты
    pdf.add_font("Serif", "", FONT_REGULAR, uni=True)
    pdf.add_font("Serif", "B", FONT_BOLD, uni=True)
    pdf.add_font("Serif", "I", FONT_ITALIC, uni=True)
    pdf.add_font("Serif", "BI", FONT_BI, uni=True)

    # --- Заголовок ---
    pdf.set_font("Serif", "B", 16)
    pdf.multi_cell(0, 10, title, align="L")
    pdf.ln(4)

    # --- Дата ---
    pdf.set_font("Serif", "I", 10)
    pdf.set_text_color(100, 100, 100)
    date_str = datetime.now().strftime("%d %B %Y")
    months_ru = {
        "January": "января", "February": "февраля", "March": "марта",
        "April": "апреля", "May": "мая", "June": "июня",
        "July": "июля", "August": "августа", "September": "сентября",
        "October": "октября", "November": "ноября", "December": "декабря"
    }
    for en, ru in months_ru.items():
        date_str = date_str.replace(en, ru)
    pdf.cell(0, 6, date_str, ln=True)
    pdf.ln(2)

    # --- Ссылка на источник ---
    if source_url:
        pdf.set_font("Serif", "I", 9)
        pdf.set_text_color(0, 80, 180)
        pdf.cell(0, 6, f"Источник: {source_url}", ln=True, link=source_url)
        pdf.ln(6)

    # --- Разделитель ---
    pdf.set_draw_color(180, 180, 180)
    pdf.set_line_width(0.3)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(6)

    # --- Текст перевода ---
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Serif", "", 11)
    pdf.multi_cell(0, 6.5, russian_text, align="L")

    # --- Сохраняем ---
    safe_name = _sanitise_filename(title)
    pdf_path = os.path.join(tempfile.gettempdir(), f"{safe_name}.pdf")
    pdf.output(pdf_path)
    log.info("PDF создан: %s (%.1f KB)", pdf_path, os.path.getsize(pdf_path) / 1024)

    return pdf_path


# ----- Хэндлер инструмента -----
def _translate_to_pdf_handler(ctx: ToolContext, **kwargs) -> str:
    """
    Вызывается агентом при использовании инструмента `translate_to_pdf`.
    """
    russian_text = kwargs.get("russian_text", "")
    title = kwargs.get("title", "")
    source_url = kwargs.get("source_url", "")

    if not russian_text:
        return "Ошибка: не указан параметр 'russian_text' (текст перевода на русский)"
    if not title:
        return "Ошибка: не указан параметр 'title' (заголовок новости на русском)"

    if not isinstance(russian_text, str) or not isinstance(title, str):
        return "Ошибка: 'russian_text' и 'title' должны быть строками"

    try:
        pdf_path = create_pdf(russian_text=russian_text, title=title, source_url=source_url)
        return pdf_path
    except ValueError as e:
        return f"Ошибка создания PDF: {str(e)}"
    except Exception as e:
        log.error("Ошибка в translate_to_pdf: %s", e)
        return f"⚠️ Не удалось создать PDF: {str(e)}"


# ----- Регистрация инструмента -----
def get_tools():
    """Возвращает список инструментов."""
    return [
        ToolEntry(
            name="translate_to_pdf",
            schema={
                "name": "translate_to_pdf",
                "description": (
                    "Создаёт PDF-файл с русским переводом новости. "
                    "PDF содержит: заголовок на русском, дату, ссылку на источник, "
                    "текст перевода. Только русский текст — без английского оригинала. "
                    "Возвращает путь к созданному PDF-файлу. "
                    "После создания PDF загрузи его на Яндекс.Диск через upload_pdf, "
                    "затем получи публичную ссылку через get_pdf_link."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "russian_text": {
                            "type": "string",
                            "description": "Качественный перевод новости на русский язык."
                        },
                        "title": {
                            "type": "string",
                            "description": "Заголовок новости на русском языке."
                        },
                        "source_url": {
                            "type": "string",
                            "description": "Ссылка на оригинальный источник (опционально)."
                        }
                    },
                    "required": ["russian_text", "title"]
                }
            },
            handler=_translate_to_pdf_handler,
            is_code_tool=False,
            timeout_sec=60,
        )
    ]
