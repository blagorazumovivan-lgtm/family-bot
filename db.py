"""
Работа с базой данных SQLite.

Таблицы:
  users     — зарегистрированные члены семьи
              (telegram_id — уникальный, name — как представился)
  messages  — анонимные письма
              (recipient_name — кому; автора в базе нет)
"""

import sqlite3
from datetime import datetime

DB_PATH = "family_bot.db"


def init_db() -> None:
    """Создаёт таблицы, если их ещё нет."""
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
    conn.close()


# ---------- users ----------

def register_user(telegram_id: int, name: str) -> bool:
    """
    Регистрирует пользователя.
    Возвращает True, если новый, False — если уже был зарегистрирован.
    """
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
    """Возвращает {id, telegram_id, name, created_at} или None."""
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


def get_all_users() -> list[dict]:
    """Возвращает всех зарегистрированных, отсортированных по имени."""
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
    """Сохраняет анонимное письмо. Возвращает id."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO messages (recipient_name, text, created_at) VALUES (?, ?, ?)",
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
    name: str, limit: int = 20
) -> list[tuple[int, str, str]]:
    """Письма для конкретного получателя. [(id, text, created_at), ...]"""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, text, created_at
        FROM messages
        WHERE recipient_name = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (name, limit),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def count_messages() -> int:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM messages")
    (n,) = cur.fetchone()
    conn.close()
    return n
