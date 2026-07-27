"""
Работа с базой данных SQLite.

Таблицы:
  users     — зарегистрированные члены семьи
              (telegram_id — уникальный, name — как представился)
  messages  — анонимные письма
              (recipient_name — кому; is_read — прочитано или нет;
               автора в базе нет)
"""

import sqlite3
from datetime import datetime

DB_PATH = "family_bot.db"


def init_db() -> None:
    """Создаёт таблицы и применяет миграции."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE NOT NULL,
            name        TEXT    NOT NULL,
            created_at  TEXT    NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            recipient_name TEXT    NOT NULL,
            text           TEXT    NOT NULL,
            created_at     TEXT    NOT NULL
        )
        """
    )
    conn.commit()

    # Миграция: добавляем колонку is_read, если её ещё нет
    cur.execute("PRAGMA table_info(messages)")
    columns = {row[1] for row in cur.fetchall()}
    if "is_read" not in columns:
        cur.execute(
            "ALTER TABLE messages ADD COLUMN is_read INTEGER NOT NULL DEFAULT 0"
        )
        conn.commit()

    conn.close()


# ---------- users ----------

def register_user(telegram_id: int, name: str) -> bool:
    """Регистрирует пользователя. False, если уже зарегистрирован."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO users (telegram_id, name, created_at) VALUES (?, ?, ?)",
            (telegram_id, name, datetime.now().strftime("%Y-%m-%d %H:%M")),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def get_user_by_telegram_id(telegram_id: int) -> dict | None:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, telegram_id, name, created_at FROM users WHERE telegram_id = ?",
        (telegram_id,),
    )
    row = cur.fetchone()
    conn.close()
    if row:
        return {
            "id": row[0],
            "telegram_id": row[1],
            "name": row[2],
            "created_at": row[3],
        }
    return None


def get_user_by_name(name: str) -> dict | None:
    """Поиск пользователя по имени (без учёта регистра)."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, telegram_id, name, created_at FROM users "
        "WHERE LOWER(name) = LOWER(?)",
        (name,),
    )
    row = cur.fetchone()
    conn.close()
    if row:
        return {
            "id": row[0],
            "telegram_id": row[1],
            "name": row[2],
            "created_at": row[3],
        }
    return None


def get_all_users() -> list[dict]:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, telegram_id, name, created_at FROM users ORDER BY name"
    )
    rows = cur.fetchall()
    conn.close()
    return [
        {"id": r[0], "telegram_id": r[1], "name": r[2], "created_at": r[3]}
        for r in rows
    ]


def count_users() -> int:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    (n,) = cur.fetchone()
    conn.close()
    return n


# ---------- messages ----------

def save_message(recipient_name: str, text: str) -> int:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO messages (recipient_name, text, created_at) "
        "VALUES (?, ?, ?)",
        (
            recipient_name,
            text,
            datetime.now().strftime("%Y-%m-%d %H:%M"),
        ),
    )
    conn.commit()
    msg_id = cur.lastrowid
    conn.close()
    return msg_id


def get_messages_for_recipient(
    name: str, limit: int = 20, only_unread: bool = False
) -> list[tuple[int, str, str, int]]:
    """[(id, text, created_at, is_read), ...] — сначала новые."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    if only_unread:
        cur.execute(
            """
            SELECT id, text, created_at, is_read FROM messages
            WHERE recipient_name = ? AND is_read = 0
            ORDER BY id DESC LIMIT ?
            """,
            (name, limit),
        )
    else:
        cur.execute(
            """
            SELECT id, text, created_at, is_read FROM messages
            WHERE recipient_name = ?
            ORDER BY id DESC LIMIT ?
            """,
            (name, limit),
        )
    rows = cur.fetchall()
    conn.close()
    return rows


def count_unread(name: str) -> int:
    """Сколько непрочитанных у получателя."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM messages "
        "WHERE recipient_name = ? AND is_read = 0",
        (name,),
    )
    (n,) = cur.fetchone()
    conn.close()
    return n


def mark_all_read(name: str) -> int:
    """Пометить все непрочитанные как прочитанные. Возвращает сколько."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "UPDATE messages SET is_read = 1 "
        "WHERE recipient_name = ? AND is_read = 0",
        (name,),
    )
    n = cur.rowcount
    conn.commit()
    conn.close()
    return n


def count_messages() -> int:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM messages")
    (n,) = cur.fetchone()
    conn.close()
    return n
