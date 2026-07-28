"""
Семейный Telegram-бот Blazor.

Возможности:
  /start         — поприветствовать / зарегистрироваться
  Спросить        — задать вопрос AI-помощнику (через MiniMax M2.7)
  Написать письмо — выбрать получателя и отправить анонимное письмо
  Входящие       — посмотреть письма, адресованные тебе
  Где я?         — обновить свой статус (квартира / дача / у деда с бабой / не дома)
  Кто где?       — посмотреть, где сейчас каждый член семьи
  Помощь         — справка

Хранение:
  users    — кто зарегистрировался (telegram_id ↔ name, status)
  messages — анонимные письма
             (recipient_name, is_read; автора в базе нет)

Поведение:
  — При сохранении письма бот сам отправляет push-уведомление получателю
  — В главном меню кнопка «Входящие» показывает счётчик непрочитанных
  — При просмотре /inbox все письма помечаются как прочитанные
  — При смене статуса бот рассылает push-уведомление всем членам семьи
  — «Спросить» шлёт вопрос в MiniMax (Anthropic-совместимый API) и
    возвращает ответ. История не сохраняется — каждый вопрос отдельно.
"""

import os

import anthropic
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
    count_unread,
    count_users,
    get_all_users,
    get_all_users_with_status,
    get_messages_for_recipient,
    get_user_by_name,
    get_user_by_telegram_id,
    mark_all_read,
    register_user,
    save_message,
    set_user_status,
)

# ---------- Настройка ----------

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN не найден в .env")

bot = telebot.TeleBot(TOKEN)

# AI-конфиг (MiniMax, Anthropic-совместимый API).
# Если ключа нет — «Спросить» вежливо скажет «не настроено», бот не падает.
MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "").strip()
ANTHROPIC_BASE_URL = os.getenv(
    "ANTHROPIC_BASE_URL", "https://api.minimax.io/anthropic"
)
MINIMAX_MODEL = os.getenv("MINIMAX_MODEL", "MiniMax-M2.7")

# Состояния пользователей:
#   None                       — обычный режим
#   "awaiting_name"            — ждём имя для регистрации
#   "awaiting_question"        — ждём вопрос для AI
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

HELP_TEXT = (
    "<b>Что я умею:</b>\n\n"
    "<b>Спросить</b> — задать вопрос AI-помощнику "
    "(через MiniMax M2.7)\n"
    "<b>Написать письмо</b> — выбрать получателя и отправить "
    "анонимное письмо\n"
    "<b>Входящие</b> — посмотреть письма, адресованные вам\n"
    "<b>Где я?</b> — сказать семье, где вы сейчас "
    "(квартира / дача / у деда с бабой / не дома)\n"
    "<b>Кто где?</b> — посмотреть, где сейчас каждый член семьи\n"
    "<b>Помощь</b> — эта справка\n\n"
    "Все письма анонимны. Никто не узнает автора. "
    "Когда вам пишут или меняют статус — приходит уведомление в Telegram."
)

# Системный промпт для AI-ответов. Дружелюбно, по-русски, без эмодзи.
ASK_SYSTEM_PROMPT = (
    "Ты — Blazor, дружелюбный AI-помощник для русскоязычной семьи. "
    "Отвечай на русском, кратко и по делу. "
    "Длинные ответы структурируй списками или шагами. "
    "Не выдумывай факты — если не знаешь, скажи прямо. "
    "Эмодзи в ответах не используй (если не попросят явно)."
)

EMPTY_INBOX = "Входящих пока нет. Подождите, пока кто-то решит вам написать."

NO_RECIPIENTS = (
    "В семье пока только вы. Попросите близких запустить бота — "
    "пусть каждый представится, и тогда можно будет писать друг другу."
)

NAME_REJECTED = "Имя должно быть от 1 до 40 символов. Попробуйте ещё раз."

LETTER_PUSH_HEADER = "Новое анонимное письмо!\n\n"

# Человекочитаемые названия статусов
STATUS_LABELS = {
    "apartment": "🏠 Квартира",
    "dacha": "🌲 Дача",
    "grandparents": "👴 У деда с бабой",
    "not_home": "🚶 Не дома",
}


# ---------- Клавиатуры ----------

def main_reply_keyboard(unread_count: int = 0) -> ReplyKeyboardMarkup:
    """Главное меню. На кнопке «Входящие» — счётчик непрочитанных."""
    inbox_text = (
        f"Входящие ({unread_count})" if unread_count > 0 else "Входящие"
    )
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        KeyboardButton("Спросить"),
        KeyboardButton("Написать письмо"),
    )
    kb.add(
        KeyboardButton(inbox_text),
        KeyboardButton("Где я?"),
    )
    kb.add(
        KeyboardButton("Кто где?"),
        KeyboardButton("Помощь"),
    )
    return kb


def status_keyboard() -> InlineKeyboardMarkup:
    """Inline-кнопки для выбора одного из 4 статусов."""
    kb = InlineKeyboardMarkup(row_width=2)
    for code, label in STATUS_LABELS.items():
        kb.add(
            InlineKeyboardButton(label, callback_data=f"status:{code}")
        )
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


def safe_send(telegram_id: int, text: str, silent: bool = False) -> bool:
    """
    Пытается отправить сообщение юзеру в Telegram.
    silent=True — без звука и без вибрации (для «фоновых» уведомлений,
    которые не должны отвлекать).
    Возвращает True если успешно, False если нет (юзер не запустил бота,
    заблокировал, и т.п.).
    """
    try:
        bot.send_message(
            telegram_id,
            text,
            parse_mode="HTML",
            disable_notification=silent,
        )
        return True
    except Exception as exc:
        # Типичные причины: юзер не начинал чат с ботом, или заблокировал
        print(f"[!] Не удалось доставить push юзеру {telegram_id}: {exc!r}")
        return False


# ---------- Команды ----------

@bot.message_handler(commands=["start"])
def handle_start(message: Message) -> None:
    clear_state(message.from_user.id)
    user = get_user_by_telegram_id(message.from_user.id)

    if user:
        unread = count_unread(user["name"])
        extra = ""
        if unread > 0:
            extra = (
                f"\n\nУ вас <b>{unread}</b> непрочитанных "
                f"{_plural_letter(unread)}. "
                f"Нажмите «Входящие» чтобы прочитать."
            )
        bot.send_message(
            message.chat.id,
            f"С возвращением, <b>{user['name']}</b>.{extra}",
            parse_mode="HTML",
            reply_markup=main_reply_keyboard(unread),
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
    user = get_user_by_telegram_id(message.from_user.id)
    unread = count_unread(user["name"]) if user else 0
    bot.send_message(
        message.chat.id,
        HELP_TEXT,
        parse_mode="HTML",
        reply_markup=main_reply_keyboard(unread),
    )


# ---------- Reply-кнопки (внизу экрана) ----------

@bot.message_handler(func=lambda m: m.text == "Спросить")
def handle_ask_button(message: Message) -> None:
    """Кнопка «Спросить» — переводим в режим ожидания вопроса для AI."""
    user = get_user_by_telegram_id(message.from_user.id)
    if not user:
        bot.send_message(
            message.chat.id, "Сначала представьтесь — нажмите /start."
        )
        return

    if not MINIMAX_API_KEY:
        bot.send_message(
            message.chat.id,
            "AI-помощник пока не настроен: в .env не указан "
            "MINIMAX_API_KEY. Попросите админа бота добавить ключ.",
            reply_markup=main_reply_keyboard(),
        )
        return

    clear_state(message.from_user.id)
    user_states[message.from_user.id] = "awaiting_question"
    bot.send_message(
        message.chat.id,
        "Напишите свой вопрос — отвечу через пару секунд.\n"
        "Чтобы отменить — /start или любая кнопка внизу.",
        reply_markup=main_reply_keyboard(),
    )


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


@bot.message_handler(func=lambda m: m.text and m.text.startswith("Входящие"))
def handle_inbox_button(message: Message) -> None:
    """Ловит и 'Входящие', и 'Входящие (3)'."""
    user = get_user_by_telegram_id(message.from_user.id)
    if not user:
        bot.send_message(message.chat.id, "Сначала представьтесь — нажмите /start.")
        return

    clear_state(message.from_user.id)
    show_inbox(message.chat.id, user["name"])


@bot.message_handler(func=lambda m: m.text == "Помощь")
def handle_help_button(message: Message) -> None:
    clear_state(message.from_user.id)
    user = get_user_by_telegram_id(message.from_user.id)
    unread = count_unread(user["name"]) if user else 0
    bot.send_message(
        message.chat.id,
        HELP_TEXT,
        parse_mode="HTML",
        reply_markup=main_reply_keyboard(unread),
    )


@bot.message_handler(func=lambda m: m.text == "Где я?")
def handle_where_am_i(message: Message) -> None:
    """Показывает инлайн-клавиатуру для смены своего статуса."""
    user = get_user_by_telegram_id(message.from_user.id)
    if not user:
        bot.send_message(
            message.chat.id, "Сначала представьтесь — нажмите /start."
        )
        return

    clear_state(message.from_user.id)

    current = user.get("status")
    current_label = STATUS_LABELS.get(current, "<i>не указано</i>")

    bot.send_message(
        message.chat.id,
        f"Где вы сейчас?\nТекущий статус: <b>{current_label}</b>",
        parse_mode="HTML",
        reply_markup=status_keyboard(),
    )


@bot.message_handler(func=lambda m: m.text == "Кто где?")
def handle_whos_where(message: Message) -> None:
    """Показывает, где сейчас каждый член семьи."""
    user = get_user_by_telegram_id(message.from_user.id)
    if not user:
        bot.send_message(
            message.chat.id, "Сначала представьтесь — нажмите /start."
        )
        return

    clear_state(message.from_user.id)
    show_family_statuses(message.chat.id)


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


@bot.callback_query_handler(func=lambda c: c.data.startswith("status:"))
def handle_status_choice(callback: CallbackQuery) -> None:
    """Юзер нажал одну из 4 кнопок статуса."""
    status_code = callback.data[len("status:"):]
    user = get_user_by_telegram_id(callback.from_user.id)
    if not user:
        bot.answer_callback_query(
            callback.id, "Сначала зарегистрируйтесь через /start"
        )
        return

    if status_code not in STATUS_LABELS:
        bot.answer_callback_query(callback.id, "Неизвестный статус")
        return

    set_user_status(callback.from_user.id, status_code)
    label = STATUS_LABELS[status_code]

    bot.answer_callback_query(callback.id, f"Статус: {label}")
    bot.send_message(
        callback.message.chat.id,
        f"Запомнила. Вы сейчас: <b>{label}</b>.\n"
        f"Семья получит уведомление.",
        parse_mode="HTML",
        reply_markup=main_reply_keyboard(),
    )

    # Бродкастим всем остальным
    broadcast_status_change(user["name"], label)


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

    # Вопрос к AI
    if state == "awaiting_question":
        clear_state(message.from_user.id)
        question = (message.text or "").strip()
        if not question:
            bot.send_message(
                message.chat.id,
                "Пустой вопрос — нечего отвечать. Нажмите «Спросить» ещё раз.",
                reply_markup=main_reply_keyboard(),
            )
            return

        # Покажем «Думаю...» — потом обновим на ответ (если влезет)
        thinking_msg = bot.send_message(message.chat.id, "Думаю...")
        answer = ask_ai(question)
        send_ai_answer(
            message.chat.id, answer, thinking_msg.message_id
        )
        return

    # Пишем письмо для получателя
    if state and state.startswith("writing:"):
        recipient_name = state[len("writing:"):]
        msg_text = message.text or ""
        msg_id = save_message(recipient_name, msg_text)
        clear_state(message.from_user.id)

        # Push-уведомление получателю в Telegram (с текстом письма)
        recipient = get_user_by_name(recipient_name)
        if recipient:
            pushed = safe_send(
                recipient["telegram_id"],
                f"{LETTER_PUSH_HEADER}<i>{_escape(msg_text)}</i>",
            )
            push_status = (
                "Уведомление доставлено."
                if pushed
                else "Получатель ещё не запускал бота — письмо "
                "будет ждать во Входящих."
            )
        else:
            push_status = (
                "Получатель ещё не представился боту — письмо "
                "будет ждать во Входящих."
            )

        bot.send_message(
            message.chat.id,
            f"Письмо доставлено. Номер: <b>#{msg_id}</b>.\n{push_status}",
            parse_mode="HTML",
            reply_markup=main_reply_keyboard(),
        )
        return

    # Любой другой текст — дружелюбная подсказка
    user = get_user_by_telegram_id(message.from_user.id)
    if user:
        unread = count_unread(user["name"])
        bot.send_message(
            message.chat.id,
            f"Я вас не совсем понял, <b>{user['name']}</b>.\n"
            f"Используйте кнопки внизу экрана.",
            parse_mode="HTML",
            reply_markup=main_reply_keyboard(unread),
        )
    else:
        bot.send_message(
            message.chat.id,
            "Здравствуйте. Нажмите /start, чтобы представиться.",
        )


# ---------- Вспомогательное: входящие ----------

def show_family_statuses(chat_id: int) -> None:
    """Печатает «кто где» — все члены семьи и их текущий статус."""
    users = get_all_users_with_status()
    if not users:
        bot.send_message(
            chat_id,
            "В семье пока никого нет. Попросите близких запустить бота.",
            reply_markup=main_reply_keyboard(),
        )
        return

    lines = ["<b>Кто где сейчас:</b>\n"]
    for u in users:
        status = u.get("status")
        if status and status in STATUS_LABELS:
            label = STATUS_LABELS[status]
            ts = u.get("status_updated_at") or "—"
            lines.append(
                f"• {u['name']}: {label}  <i>(обновлено {ts})</i>"
            )
        else:
            lines.append(f"• {u['name']}: <i>не указано</i>")

    bot.send_message(
        chat_id,
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=main_reply_keyboard(),
    )


def broadcast_status_change(user_name: str, status_label: str) -> None:
    """Шлёт тихий пуш всем членам семьи (кроме автора изменения).
    Без звука — статус «кто где» это фоновая инфа, не должна отвлекать."""
    for u in get_all_users_with_status():
        if u["name"].lower() == user_name.lower():
            continue
        safe_send(
            u["telegram_id"],
            f"📍 <b>{user_name}</b> теперь: {status_label}",
            silent=True,
        )


# ---------- AI: «Спросить» ----------

def ask_ai(question: str) -> str:
    """Шлёт вопрос в MiniMax (Anthropic-совместимый API) и возвращает ответ.
    При любой ошибке возвращает короткое дружелюбное сообщение для юзера.
    История не ведётся — каждый вопрос отдельно, без контекста."""
    if not MINIMAX_API_KEY:
        return "AI-ключ не настроен в .env."

    try:
        client = anthropic.Anthropic(
            base_url=ANTHROPIC_BASE_URL,
            api_key=MINIMAX_API_KEY,
            timeout=30.0,
        )
        response = client.messages.create(
            model=MINIMAX_MODEL,
            max_tokens=1024,
            system=ASK_SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": question},
            ],
        )
        parts = []
        for block in response.content:
            # У text-блоков есть .text; у thinking — .thinking
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        answer = "".join(parts).strip()
        return answer or "AI вернул пустой ответ. Попробуйте иначе."
    except anthropic.APITimeoutError:
        return "AI не отвечает (таймаут 30 сек). Попробуйте позже."
    except anthropic.APIConnectionError as exc:
        return f"Нет связи с AI: {type(exc).__name__}. Попробуйте позже."
    except anthropic.APIStatusError as exc:
        return (
            f"AI вернул ошибку {exc.status_code}: "
            f"{getattr(exc, 'message', '')[:200] or type(exc).__name__}"
        )
    except anthropic.APIError as exc:
        return f"Ошибка AI ({type(exc).__name__}). Попробуйте ещё раз."
    except Exception as exc:
        return f"Что-то пошло не так ({type(exc).__name__}). Попробуйте ещё раз."


def send_ai_answer(chat_id: int, text: str, thinking_msg_id: int) -> None:
    """Доставляет ответ AI в чат. Пытается отредактировать «Думаю...»,
    если ответ короткий и edit проходит. Иначе — удаляет «Думаю...» и
    шлёт ответ. Длинные ответы режет на части (лимит Telegram 4096)."""
    MAX = 4000

    # Короткий ответ — пробуем отредактировать «Думаю...»
    if len(text) <= MAX:
        try:
            bot.edit_message_text(
                text, chat_id=chat_id, message_id=thinking_msg_id
            )
            bot.send_message(
                chat_id,
                "Ещё что-нибудь? Жмите «Спросить».",
                reply_markup=main_reply_keyboard(),
            )
            return
        except Exception:
            pass  # edit не сработал (например, слишком давно) — fallback

    # Длинный ответ или edit не сработал — удаляем «Думаю...» и шлём как есть
    try:
        bot.delete_message(chat_id=chat_id, message_id=thinking_msg_id)
    except Exception:
        pass

    if len(text) <= MAX:
        bot.send_message(
            chat_id, text, reply_markup=main_reply_keyboard()
        )
        return

    # Длинный ответ — кусками
    chunks = [text[i:i + MAX] for i in range(0, len(text), MAX)]
    for i, chunk in enumerate(chunks, 1):
        suffix = (
            f"\n\n(часть {i} из {len(chunks)})" if len(chunks) > 1 else ""
        )
        bot.send_message(chat_id, chunk + suffix)
    bot.send_message(
        chat_id, "Готово.", reply_markup=main_reply_keyboard()
    )


def show_inbox(chat_id: int, user_name: str) -> None:
    # Помечаем всё как прочитанное
    marked = mark_all_read(user_name)

    # Показываем до 100 последних писем
    messages = get_messages_for_recipient(user_name, limit=100)
    if not messages:
        bot.send_message(
            chat_id, EMPTY_INBOX, reply_markup=main_reply_keyboard()
        )
        return

    # Собираем все строки
    header = f"Входящие письма для <b>{user_name}</b>:"
    if marked > 0:
        header += f" ({marked} помечено как прочитанное)"
    lines = [header]
    for msg_id, text, created_at, is_read in messages:
        short = text if len(text) <= 300 else text[:297] + "..."
        marker = "" if is_read else " <b>[новое]</b>"
        lines.append(
            f"<b>#{msg_id}</b>{marker}  <i>({created_at})</i>\n{short}"
        )
    lines.append(f"\nВсего показано: {len(messages)}")

    # Telegram ограничивает сообщение 4096 символами.
    # Если не влезает — режем по строкам на несколько сообщений.
    full_text = "\n\n".join(lines)
    MAX_LEN = 3800

    if len(full_text) <= MAX_LEN:
        bot.send_message(
            chat_id,
            full_text,
            parse_mode="HTML",
            reply_markup=main_reply_keyboard(0),
        )
        return

    chunks: list[str] = []
    current = ""
    for line in lines:
        candidate = (current + "\n\n" + line) if current else line
        if len(candidate) > MAX_LEN and current:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)

    total = len(chunks)
    for i, chunk in enumerate(chunks, start=1):
        suffix = (
            f"\n\n<i>(часть {i} из {total})</i>" if total > 1 else ""
        )
        kb = main_reply_keyboard(0) if i == total else None
        bot.send_message(
            chat_id, chunk + suffix, parse_mode="HTML", reply_markup=kb
        )


# ---------- Вспомогательные для текста ----------

def _escape(text: str) -> str:
    """Экранирует символы, которые Telegram-парсер HTML может съесть."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _plural_letter(n: int) -> str:
    """Склонение: 1 письмо, 2 письма, 5 писем."""
    n100 = n % 100
    if 11 <= n100 <= 14:
        return "писем"
    n10 = n % 10
    if n10 == 1:
        return "письмо"
    if 2 <= n10 <= 4:
        return "письма"
    return "писем"


# ---------- Запуск ----------

if __name__ == "__main__":
    import time

    print(
        f"Blazor запущен. "
        f"Пользователей в базе: {count_users()}, "
        f"писем: {count_messages()}."
    )

    # Защита от сетевых сбоев: если бот упал — подождать и перезапустить.
    while True:
        try:
            bot.polling(non_stop=True, interval=1, timeout=30)
        except KeyboardInterrupt:
            print("Остановка по Ctrl+C")
            break
        except Exception as exc:
            print(f"[!] Бот упал с ошибкой: {exc!r}")
            print("    Перезапуск через 5 секунд...")
            time.sleep(5)
