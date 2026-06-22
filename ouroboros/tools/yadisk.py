"""
Инструменты для работы с Яндекс.Диском: загрузка PDF и получение публичных ссылок.
Требует установки: pip install yadisk
И наличия переменной окружения: MY_YA_DISK (токен Яндекс.Диска)
"""

import logging
import os
from typing import Optional

import yadisk

from ouroboros.tools.registry import ToolContext, ToolEntry

log = logging.getLogger(__name__)

# Инициализация клиента Яндекс.Диска
def _get_yandex_client() -> Optional[yadisk.YaDisk]:
    """Создаёт клиента Яндекс.Диска."""
    token = os.environ.get("MY_YA_DISK", "")
    if not token:
        log.error("MY_YA_DISK не задан в переменных окружения")
        return None
    
    y = yadisk.YaDisk(token=token)
    if not y.check_token():
        log.error("Не удалось авторизоваться на Яндекс.Диске")
        return None
    
    return y


def upload_pdf_on_disk(upload_file_path: str, upload_file_name: str) -> str:
    """
    Загрузка PDF файла на облачный диск Яндекс.Диск.
    
    Args:
        upload_file_path: Путь к локальному PDF файлу
        upload_file_name: Имя файла на диске (с расширением .pdf)
    
    Returns:
        str: "ok" в случае успеха, иначе сообщение об ошибке
    """
    try:
        y = _get_yandex_client()
        if y is None:
            return "Ошибка: не удалось подключиться к Яндекс.Диску"
        
        # Проверяем существование файла
        if not os.path.exists(upload_file_path):
            return f"Ошибка: файл '{upload_file_path}' не найден"
        
        # Проверяем расширение файла
        if not upload_file_name.lower().endswith('.pdf'):
            return "Ошибка: файл должен иметь расширение .pdf"
        
        remote_path = f"/news_translation/{upload_file_name}"
        
        log.info("Загрузка файла: %s -> %s", upload_file_path, remote_path)
        y.upload(upload_file_path, remote_path)
        
        log.info("Файл успешно загружен: %s", remote_path)
        return "ok"
        
    except yadisk.exceptions.PathExistsError:
        return f"Ошибка: файл '{upload_file_name}' уже существует на диске"
    except yadisk.exceptions.PermissionDeniedError:
        return "Ошибка: недостаточно прав для загрузки файла"
    except Exception as e:
        log.error("Ошибка при загрузке файла: %s", e)
        return f"⚠️ Ошибка загрузки: {str(e)}"


def get_file_link(filename: str) -> str:
    """
    Получение публичной ссылки на просмотр PDF документа.
    
    Args:
        filename: Имя файла в полном формате (например, "document.pdf")
    
    Returns:
        str: Публичная ссылка на файл или сообщение об ошибке
    """
    try:
        y = _get_yandex_client()
        if y is None:
            return "Ошибка: не удалось подключиться к Яндекс.Диску"
        
        # Проверяем расширение файла
        if not filename.lower().endswith('.pdf'):
            return "Ошибка: файл должен иметь расширение .pdf"
        
        remote_path = f"/news_translation/{filename}"
        
        log.info("Получение ссылки для файла: %s", remote_path)
        
        # Проверяем существование файла
        if not y.exists(remote_path):
            return f"Ошибка: файл '{filename}' не найден на диске"
        
        # Получаем метаданные файла
        meta = y.get_meta(remote_path)
        
        # Если публичной ссылки нет, создаём её
        if not meta.public_url:
            log.info("Создание публичной ссылки для: %s", remote_path)
            y.publish(remote_path)
            meta = y.get_meta(remote_path)  # Обновляем метаданные
        
        return meta.public_url or "Ошибка: не удалось получить публичную ссылку"
        
    except yadisk.exceptions.PermissionDeniedError:
        return "Ошибка: недостаточно прав для получения ссылки"
    except yadisk.exceptions.NotFoundError:
        return f"Ошибка: файл '{filename}' не найден"
    except Exception as e:
        log.error("Ошибка при получении ссылки: %s", e)
        return f"⚠️ Ошибка получения ссылки: {str(e)}"


# ----- Хэндлер для загрузки PDF -----
def _upload_pdf_handler(ctx: ToolContext, **kwargs) -> str:
    """
    Вызывается агентом при использовании инструмента `upload_pdf`.
    """
    file_path = kwargs.get("file_path")
    file_name = kwargs.get("file_name")
    
    if not file_path:
        return "Ошибка: не указан параметр 'file_path' (путь к локальному PDF файлу)"
    
    if not file_name:
        return "Ошибка: не указан параметр 'file_name' (имя файла на диске)"
    
    if not isinstance(file_path, str) or not isinstance(file_name, str):
        return "Ошибка: 'file_path' и 'file_name' должны быть строками"
    
    return upload_pdf_on_disk(file_path, file_name)


# ----- Хэндлер для получения ссылки -----
def _get_file_link_handler(ctx: ToolContext, **kwargs) -> str:
    """
    Вызывается агентом при использовании инструмента `get_pdf_link`.
    """
    filename = kwargs.get("filename")
    
    if not filename:
        return "Ошибка: не указан параметр 'filename' (имя файла с расширением .pdf)"
    
    if not isinstance(filename, str):
        return "Ошибка: 'filename' должен быть строкой"
    
    return get_file_link(filename)


# ----- Регистрация инструментов -----
def get_tools():
    """Возвращает список инструментов."""
    return [
        ToolEntry(
            name="upload_pdf",
            schema={
                "name": "upload_pdf",
                "description": (
                    "Загружает PDF файл на Яндекс.Диск в папку 'news_translation'."
                    "Используй этот инструмент, когда нужно сохранить PDF отчёт на облачный диск."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "Полный или относительный путь к локальному PDF файлу для загрузки"
                        },
                        "file_name": {
                            "type": "string",
                            "description": "Имя файла на Яндекс.Диске (должно заканчиваться на .pdf)"
                        }
                    },
                    "required": ["file_path", "file_name"]
                }
            },
            handler=_upload_pdf_handler,
            is_code_tool=False,
            timeout_sec=120,  # Загрузка может занять время
        ),
        ToolEntry(
            name="get_pdf_link",
            schema={
                "name": "get_pdf_link",
                "description": (
                    "Получает публичную ссылку на PDF файл, хранящийся на Яндекс.Диске в папке 'news_translation'. "
                    "Используй этот инструмент, когда нужно получить ссылку для просмотра или скачивания PDF."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": "Имя файла на Яндекс.Диске с расширением .pdf (например, 'report_2026.pdf')"
                        }
                    },
                    "required": ["filename"]
                }
            },
            handler=_get_file_link_handler,
            is_code_tool=False,
            timeout_sec=30,
        )
    ]