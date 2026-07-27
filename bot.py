"""
Семейный Telegram-бот Blazor.

Возможности:
  /start   — поприветствовать / зарегистрироваться
  Написать письмо — выбрать получателя и отправить анонимное письмо
  Входящие — посмотреть письма, адресованные тебе
  Помощь  — справка

Хранение:
  users    — кто зарегистрировался (telegram_id ↔ name)
  messages — анонимные письма (только recipient_name, без автора)
"""

import os

import telebot
from dotenv import load_dotenv
from telebot.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from db import (
    count_messages,
    count_users,
    get_all_users,
    get_messages_for_recipient,
    get_user_by_telegram_id,
    register_user,
    save_message,
)

# ---------- Настройка ----------

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN не найден в .env")

bot = telebot.TeleBot(TOKEN)

# Состояния пользователей:
#   None                       — обычный режим
#   "awaiting_name"            — ждём имя для регистрации
#   "writing:<recipient_name>" — пишем письмо для конкретного получателя
user_states: dict[int, str] = {}


# ---------- Тексты ----------

WELCOME_NEW = (
    "Привет. Я — <b>Blazor</b>, ваш семейный бот.\n\n"
    "Помогу спланировать расписание и добавлю тёплых моментов "
    "в ваши будни. Здесь можно писать друг другу анонимные письма "
    "и делиться тем, что на душе.\n\n"
    "Напишите, пожалуйста, как вас зовут — это имя увидят другие "
    "члены семьи, когда будут писать вам."
)

WELCOME_BACK = (
    "С возвращением, <b>{name}</b>.\n"
    "Используйте кнопки внизу, чтобы написать письмо "
    "или посмотреть входящие."
)

HELP_TEXT = (
    "<b>Что я умею:</b>\n\n"
    "<b>Написать письмо</b> — выбрать получателя и отправить "
    "анонимное письмо\n"
    "<b>Входящие</b> — посмотреть письма, адресованные вам\n"
    "<b>Помощь</b> — эта справка\n\n"
    "Все письма анонимны. Никто не узнает автора."
)

EMPTY_INBOX = "Входящих пока нет. Подождите, пока кто-то решит вам написать."

NO_RECIPIENTS = (
    "В семье пока только вы. Попросите близких запустить бота — "
    "пусть каждый представится, и тогда можно будет писать друг другу."
)

NAME_REJECTED = "Имя должно быть от 1 до 40 символов. Попробуйте ещё раз."


# ---------- Клавиатуры ----------

def main_reply_keyboard() -> ReplyKeyboardMarkup:
    """Главное меню — кнопки внизу экрана (persistent)."""
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        KeyboardButton("Написать письмо"),
        KeyboardButton("Входящие"),
    )
    kb.add(KeyboardButton("Помощь"))
    return kb


def recipient_keyboard(current_user_name: str) -> InlineKeyboardMarkup | None:
    """Inline-кнопки со всеми членами семьи, кроме самого юзера."""
    users = get_all_users()
    recipients = [
        u for u in users if u["name"].lower() != current_user_name.lower()
    ]
    if not recipients:
        return None
    kb = InlineKeyboardMarkup(row_width=2)
    for user in recipients:
        kb.add(
            InlineKeyboardButton(
                user["name"],
                callback_data=f"to:{user['name']}",
            )
        )
    return kb


# ---------- Вспомогательное ----------

def clear_state(user_id: int) -> None:
    user_states.pop(user_id, None)


# ---------- Команды ----------

@bot.message_handler(commands=["start"])
def handle_start(message: Message) -> None:
    clear_state(message.from_user.id)
    user = get_user_by_telegram_id(message.from_user.id)

    if user:
        bot.send_message(
            message.chat.id,
            WELCOME_BACK.format(name=user["name"]),
            parse_mode="HTML",
            reply_markup=main_reply_keyboard(),
        )
    else:
        user_states[message.from_user.id] = "awaiting_name"
        bot.send_message(
            message.chat.id,
            WELCOME_NEW,
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove(),
        )


@bot.message_handler(commands=["help"])
def handle_help(message: Message) -> None:
    clear_state(message.from_user.id)
    bot.send_message(
        message.chat.id,
        HELP_TEXT,
        parse_mode="HTML",
        reply_markup=main_reply_keyboard(),
    )


# ---------- Reply-кнопки (внизу экрана) ----------

@bot.message_handler(func=lambda m: m.text == "Написать письмо")
def handle_write_button(message: Message) -> None:
    user = get_user_by_telegram_id(message.from_user.id)
    if not user:
        bot.send_message(message.chat.id, "Сначала представьтесь — нажмите /start.")
        return

    clear_state(message.from_user.id)
    kb = recipient_keyboard(user["name"])
    if kb is None:
        bot.send_message(
            message.chat.id,
            NO_RECIPIENTS,
            reply_markup=main_reply_keyboard(),
        )
        return

    bot.send_message(
        message.chat.id,
        "Выберите, кому хотите написать:",
        reply_markup=kb,
    )


@bot.message_handler(func=lambda m: m.text == "Входящие")
def handle_inbox_button(message: Message) -> None:
    user = get_user_by_telegram_id(message.from_user.id)
    if not user:
        bot.send_message(message.chat.id, "Сначала представьтесь — нажмите /start.")
        return

    clear_state(message.from_user.id)
    show_inbox(message.chat.id, user["name"])


@bot.message_handler(func=lambda m: m.text == "Помощь")
def handle_help_button(message: Message) -> None:
    clear_state(message.from_user.id)
    bot.send_message(
        message.chat.id,
        HELP_TEXT,
        parse_mode="HTML",
        reply_markup=main_reply_keyboard(),
    )


# ---------- Inline-кнопки (выбор получателя) ----------

@bot.callback_query_handler(func=lambda c: c.data.startswith("to:"))
def handle_recipient_choice(callback: CallbackQuery) -> None:
    recipient_name = callback.data[len("to:"):]
    user = get_user_by_telegram_id(callback.from_user.id)
    if not user:
        bot.answer_callback_query(
            callback.id, "Сначала зарегистрируйтесь через /start"
        )
        return

    user_states[callback.from_user.id] = f"writing:{recipient_name}"

    bot.send_message(
        callback.message.chat.id,
        f"Пишите письмо для <b>{recipient_name}</b>.\n"
        f"Оно будет доставлено анонимно. "
        f"Чтобы отменить — нажмите /start или любую кнопку внизу.",
        parse_mode="HTML",
        reply_markup=main_reply_keyboard(),
    )
    bot.answer_callback_query(callback.id)


# ---------- Обработка любого текста ----------

@bot.message_handler(func=lambda m: True)
def handle_text(message: Message) -> None:
    state = user_states.get(message.from_user.id)

    # Регистрация: ждём имя
    if state == "awaiting_name":
        name = (message.text or "").strip()
        if not (1 <= len(name) <= 40):
            bot.send_message(message.chat.id, NAME_REJECTED)
            return

        if register_user(message.from_user.id, name):
            clear_state(message.from_user.id)
            bot.send_message(
                message.chat.id,
                f"Приятно познакомиться, <b>{name}</b>.\n"
                f"Теперь вы можете писать письма семье и получать их.",
                parse_mode="HTML",
                reply_markup=main_reply_keyboard(),
            )
        else:
            existing = get_user_by_telegram_id(message.from_user.id)
            clear_state(message.from_user.id)
            bot.send_message(
                message.chat.id,
                f"Вы уже зарегистрированы как <b>{existing['name']}</b>.",
                parse_mode="HTML",
                reply_markup=main_reply_keyboard(),
            )
        return

    # Пишем письмо для получателя
    if state and state.startswith("writing:"):
        recipient_name = state[len("writing:"):]
        msg_id = save_message(recipient_name, message.text or "")
        clear_state(message.from_user.id)

        bot.send_message(
            message.chat.id,
            f"Письмо доставлено. Номер: <b>#{msg_id}</b>.",
            parse_mode="HTML",
            reply_markup=main_reply_keyboard(),
        )
        return

    # Любой другой текст — дружелюбная подсказка
    user = get_user_by_telegram_id(message.from_user.id)
    if user:
        bot.send_message(
            message.chat.id,
            f"Я вас не совсем понял, <b>{user['name']}</b>.\n"
            f"Используйте кнопки внизу экрана.",
            parse_mode="HTML",
            reply_markup=main_reply_keyboard(),
        )
    else:
        bot.send_message(
            message.chat.id,
            "Здравствуйте. Нажмите /start, чтобы представиться.",
        )


# ---------- Вспомогательное: входящие ----------

def show_inbox(chat_id: int, user_name: str) -> None:
    messages = get_messages_for_recipient(user_name, limit=20)
    if not messages:
        bot.send_message(
            chat_id, EMPTY_INBOX, reply_markup=main_reply_keyboard()
        )
        return

    lines = [f"Входящие письма для <b>{user_name}</b>:\n"]
    for msg_id, text, created_at in messages:
        short = text if len(text) <= 300 else text[:297] + "..."
        lines.append(f"<b>#{msg_id}</b>  <i>({created_at})</i>\n{short}\n")

    bot.send_message(
        chat_id,
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=main_reply_keyboard(),
    )


# ---------- Запуск ----------

if __name__ == "__main__":
    print(
        f"Blazor запущен. "
        f"Пользователей в базе: {count_users()}, "
        f"писем: {count_messages()}."
    )
    bot.polling()
