"""
Работа с базой данных SQLite.

Таблица messages хранит анонимные сообщения:
  id         — уникальный номер
  text       — текст сообщения
  created_at — когда отправлено
"""

import sqlite3
from datetime import datetime

DB_PATH = "family_bot.db"


def init_db() -> None:
    """Создаёт таблицу, если её ещё нет."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            text       TEXT    NOT NULL,
            created_at TEXT    NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def save_message(text: str) -> int:
    """Сохраняет анонимное сообщение. Возвращает id."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO messages (text, created_at) VALUES (?, ?)",
        (text, datetime.now().strftime("%Y-%m-%d %H:%M")),
    )
    conn.commit()
    msg_id = cur.lastrowid
    conn.close()
    return msg_id


def get_recent_messages(limit: int = 10) -> list[tuple[int, str, str]]:
    """Возвращает последние N сообщений: [(id, text, created_at), ...]."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, text, created_at FROM messages ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def count_messages() -> int:
    """Сколько всего сообщений."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM messages")
    (n,) = cur.fetchone()
    conn.close()
    return n
