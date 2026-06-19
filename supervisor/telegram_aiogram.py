# content of /content/drive/MyDrive/ouroboros_dev/supervisor/telegram_aiogram.py

import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message
import sys
import os

# Добавляем путь к проекту, чтобы импортировать всё необходимое
sys.path.append('/content/drive/MyDrive/ouroboros_pulse')

from supervisor.state import load_state, save_state
from supervisor.workers import handle_chat_direct

log = logging.getLogger(__name__)

# Настройки бота
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set.")

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

# Словарь для хранения флага занятости по каждому чату
# Нужен, чтобы предотвратить одновременную обработку нескольких сообщений из одного чата
busy_chats = {}

@dp.message(Command(commands=["panic", "restart", "status", "review", "evolve", "bg"]))
async def handle_owner_commands(message: Message):
    """
    Обработчик команд супервизора (только для владельца).
    Сохраняет ту же логику, что была в colab_launcher.py.
    """
    user_id = message.from_user.id
    st = load_state()
    owner_id = st.get("owner_id")
    chat_id = message.chat.id
    
    # Если владелец еще не назначен, делаем этим пользователем владельцем
    if owner_id is None:
        st["owner_id"] = user_id
        st["owner_chat_id"] = chat_id
        save_state(st)
        await message.reply("✅ You are now registered as the owner.")
        owner_id = user_id

    # Если команду отправил не владелец — игнорируем
    if user_id != owner_id:
        return

    command = message.text.strip().lower()
    
    # --- Логика команд супервизора (скопирована из вашего старого кода) ---
    if command.startswith("/panic"):
        await message.reply("🛑 PANIC: stopping everything now.")
        # Здесь вызовите вашу функцию kill_workers() и завершите процесс
        # raise SystemExit("PANIC")
    elif command.startswith("/status"):
        # Здесь запросите статус из вашей системы и отправьте его
        await message.reply("📊 Status: System is operational.") # Пример ответа
    # ... добавьте остальные команды (/restart, /review и т.д.) ...
    else:
        await message.reply(f"⚠️ Unknown command: {command}")


@dp.message()
async def handle_all_messages(message: Message):
    """
    Основной обработчик для всех сообщений.
    Срабатывает, если нет команды или это не чат с владельцем.
    """

    chat_id = message.chat.id
    user_id = message.from_user.id
    text = message.text or message.caption or ""
    trigger_words = ["нагайна", "бот", "агент", "@nagini_hr_bot"]
    lower_text = text.lower()

    # await bot.send_message(
    #     chat_id=message.chat.id,
    #     text=f"CHAT INFO:\n\nid: {message.chat.id} \n\ntype: {message.chat.type} ",
    #     reply_to_message_id=message.message_id
    # )
    # 1. Проверяем, нужно ли отвечать
    should_respond = False
        # Проверяем триггерные слова
    if any(word in lower_text for word in trigger_words):
        # 1. Игнорируем сообщения от самого бота
        if message.from_user.id == bot.id:
            should_respond = False
        should_respond = True

        # await bot.send_message(
        #     chat_id=message.chat.id,
        #     text=f"Aiogram text group chat trigger_words",
        #     reply_to_message_id=message.message_id
        # )
        # Проверяем, что бота упомянули по username
        if not should_respond and message.mention and message.mention.username == (await bot.me()).username:
            should_respond = True

        # Опционально: проверка на reply к сообщению бота
        if not should_respond and message.reply_to_message and message.reply_to_message.from_user.id == (await bot.me()).id:
            should_respond = True

    # 2. Логика занятости и обработки сообщения
    # if busy_chats.get(chat_id, False):
    #     # Если бот занят в этом чате, сообщим об этом
    #     await message.reply("⏳ Еще не закончил предыдущую задачу. Подождите немного.")
    #     return

    # # Говорим, что взяли в работу
    # busy_chats[chat_id] = True
    if should_respond:
        await message.reply("✅ Взял в работу!")

        try:
            # 3. Вызываем основного агента Ouroboros
            # Обратите внимание: handle_chat_direct - синхронная функция.
            # Запускаем её в отдельном потоке, чтобы не блокировать aiogram.
            loop = asyncio.get_event_loop()
            # Передаем chat_id, текст и изображение (если есть)
            # handle_chat_direct должна быть адаптирована для работы с aiogram
            await loop.run_in_executor(None, handle_chat_direct, chat_id, f"Message from {message.from_user.username}:\n{text}", None)
            
            # 4. Отправка ответа от агента (логика ответа на сообщение)
            # Здесь мы ожидаем, что handle_chat_direct сохранит результат в какое-то место.
            # Для простоты пока отправим фиктивный ответ.
            # В реальности нужно дождаться ответа от LLM.
            final_answer = "Ответ готов"
            await message.reply(final_answer, reply_to_message_id=message.message_id)
            
        except Exception as e:
            log.error(f"Failed to process message in chat {chat_id}: {e}")
            await message.reply("😵 Произошла внутренняя ошибка. Проверьте логи.")
        finally:
            busy_chats[chat_id] = False

async def main():
    """Основная функция для запуска поллинга."""
    await dp.start_polling(bot)

async def run_telegram_aiogram():
    """Запуск поллинга aiogram (без создания нового event loop)."""
    await dp.start_polling(bot)