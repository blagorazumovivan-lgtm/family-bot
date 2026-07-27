"""
Семейный Telegram-бот.

Возможности:
  /start    — главное меню с кнопками
  /send     — написать анонимное сообщение
  /inbox    — посмотреть последние анонимные сообщения
  /help     — справка
  /stats    — сколько всего сообщений

Кнопки под сообщением:
  ✉️ Написать анонимно
  📥 Входящие
  ℹ️ Помощь
"""

import os

import telebot
from dotenv import load_dotenv
from telebot.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from db import count_messages, get_recent_messages, save_message

# Загружаем токен из .env
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN не найден в .env")

bot = telebot.TeleBot(TOKEN)

# Кто сейчас в режиме "пишу сообщение"
# Ключ — user_id, значение — None или "writing"
user_states: dict[int, str] = {}


# ---------- Клавиатуры (кнопки) ----------

def main_keyboard() -> InlineKeyboardMarkup:
    """Главное меню с тремя кнопками."""
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("✉️ Написать анонимно", callback_data="write"),
        InlineKeyboardButton("📥 Входящие", callback_data="inbox"),
    )
    kb.add(InlineKeyboardButton("ℹ️ Помощь", callback_data="help"))
    return kb


def after_write_keyboard() -> InlineKeyboardMarkup:
    """Кнопки после того, как сообщение сохранено."""
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📥 Посмотреть входящие", callback_data="inbox"),
        InlineKeyboardButton("✉️ Написать ещё", callback_data="write"),
    )
    return kb


# ---------- Команды ----------

@bot.message_handler(commands=["start"])
def handle_start(message: Message) -> None:
    """Приветственное сообщение с кнопками."""
    text = (
        "👋 <b>Привет! Я — семейный бот.</b>\n\n"
        "Тут можно:\n"
        "✉️  написать <b>анонимное</b> сообщение\n"
        "📥  почитать, что пишут другие\n\n"
        "Автор всегда остаётся инкогнито. Никаких имён, "
        "никаких утечек.\n\n"
        "Выбирай:"
    )
    bot.send_message(
        message.chat.id,
        text,
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )


@bot.message_handler(commands=["help"])
def handle_help(message: Message) -> None:
    """Справка по командам."""
    text = (
        "🤖 <b>Что я умею:</b>\n\n"
        "/start — главное меню\n"
        "/send — написать анонимное сообщение\n"
        "/inbox — посмотреть последние 10 сообщений\n"
        "/stats — сколько всего анонимок получено\n"
        "/help — эта справка\n\n"
        "💡 <i>Совет: просто напиши /start и тыкай кнопки.</i>"
    )
    bot.send_message(message.chat.id, text, parse_mode="HTML")


@bot.message_handler(commands=["send"])
def handle_send(message: Message) -> None:
    """Начать писать анонимное сообщение."""
    user_states[message.from_user.id] = "writing"
    bot.send_message(
        message.chat.id,
        "✍️ <b>Окей, пиши.</b>\n"
        "Я сохраню текст как есть, без автора. "
        "Чтобы отменить — нажми /start.",
        parse_mode="HTML",
    )


@bot.message_handler(commands=["inbox"])
def handle_inbox_cmd(message: Message) -> None:
    """Показать входящие через команду."""
    show_inbox(message.chat.id)


@bot.message_handler(commands=["stats"])
def handle_stats(message: Message) -> None:
    """Сколько всего анонимных сообщений."""
    n = count_messages()
    bot.send_message(
        message.chat.id,
        f"📊 Всего анонимных сообщений: <b>{n}</b>",
        parse_mode="HTML",
    )


# ---------- Нажатия на кнопки ----------

@bot.callback_query_handler(func=lambda c: c.data in {"write", "inbox", "help"})
def handle_callback(callback: CallbackQuery) -> None:
    """Обрабатывает нажатия на inline-кнопки."""
    action = callback.data
    chat_id = callback.message.chat.id

    if action == "write":
        user_states[callback.from_user.id] = "writing"
        bot.send_message(
            chat_id,
            "✍️ <b>Окей, пиши.</b> Я сохраню анонимно.",
            parse_mode="HTML",
        )

    elif action == "inbox":
        show_inbox(chat_id)

    elif action == "help":
        bot.send_message(
            chat_id,
            "🤖 <b>Команды:</b>\n"
            "/start  /send  /inbox  /stats  /help",
            parse_mode="HTML",
        )

    # Убирает «часики» на кнопке (типа «запрос обработан»)
    bot.answer_callback_query(callback.id)


# ---------- Получение текста ----------

@bot.message_handler(func=lambda m: True)
def handle_text(message: Message) -> None:
    """Ловим любой текст. Если юзер в режиме writing — сохраняем."""
    if user_states.get(message.from_user.id) == "writing":
        # Сохраняем сообщение
        msg_id = save_message(message.text)
        user_states.pop(message.from_user.id, None)

        bot.send_message(
            message.chat.id,
            f"✅ Готово! Твоё сообщение сохранено анонимно.\n"
            f"Номер: <b>#{msg_id}</b>",
            parse_mode="HTML",
            reply_markup=after_write_keyboard(),
        )
    else:
        # Пользователь не в режиме writing — покажем меню
        bot.send_message(
            message.chat.id,
            "🤔 Не понимаю. Нажми /start чтобы открыть меню.",
            reply_markup=main_keyboard(),
        )


# ---------- Вспомогательные ----------

def show_inbox(chat_id: int) -> None:
    """Показывает последние анонимные сообщения."""
    messages = get_recent_messages(limit=10)
    if not messages:
        bot.send_message(
            chat_id,
            "📭 Пока пусто. Будь первым — нажми «Написать анонимно».",
            reply_markup=main_keyboard(),
        )
        return

    lines = ["📥 <b>Последние анонимные сообщения:</b>\n"]
    for msg_id, text, created_at in messages:
        # Если сообщение слишком длинное — обрежем
        short = text if len(text) <= 200 else text[:197] + "..."
        lines.append(f"<b>#{msg_id}</b>  <i>({created_at})</i>\n{short}\n")

    bot.send_message(
        chat_id,
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )


# ---------- Запуск ----------

if __name__ == "__main__":
    print("Бот запущен. Нажми Ctrl+C чтобы остановить.")
    bot.polling()
