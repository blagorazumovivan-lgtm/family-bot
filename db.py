"""
Работа с базой данных SQLite.

Таблицы:
  users     — зарегистрированные члены семьи
              (telegram_id — уникальный, name — как представился;
               status — где сейчас: apartment / dacha / grandparents / not_home)
  messages  — анонимные письма
              (recipient_name — кому; is_read — прочитано или нет;
               автора в базе нет)
"""

import os
import sqlite3
from datetime import datetime

# На Render persistent disk монтируется в /data.
# Локально (и в CI) используем текущую папку.
DB_PATH = os.getenv("FAMILY_BOT_DB", "/data/family_bot.db" if os.path.isdir("/data") else "family_bot.db")


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
    conn.commit()

    # Проверяем схему messages. Если её нет или она устаревшая — пересоздаём.
    cur.execute("PRAGMA table_info(messages)")
    existing = {row[1] for row in cur.fetchall()}

    if not existing:
        # Таблицы нет — создаём с нуля
        cur.execute(
            """
            CREATE TABLE messages (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                recipient_name TEXT    NOT NULL,
                text           TEXT    NOT NULL,
                created_at     TEXT    NOT NULL,
                is_read        INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.commit()
    else:
        # Таблица есть — мигрируем
        if "recipient_name" not in existing:
            print(
                "[db] Обнаружена устаревшая схема messages "
                "(нет recipient_name). Пересоздаю."
            )
            cur.execute("DROP TABLE messages")
            conn.commit()
            cur.execute(
                """
                CREATE TABLE messages (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    recipient_name TEXT    NOT NULL,
                    text           TEXT    NOT NULL,
                    created_at     TEXT    NOT NULL,
                    is_read        INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.commit()
        elif "is_read" not in existing:
            cur.execute(
                "ALTER TABLE messages "
                "ADD COLUMN is_read INTEGER NOT NULL DEFAULT 0"
            )
            conn.commit()

    # Миграция users: добавляем колонки для статуса «где я».
    cur.execute("PRAGMA table_info(users)")
    user_cols = {row[1] for row in cur.fetchall()}
    if "status" not in user_cols:
        cur.execute("ALTER TABLE users ADD COLUMN status TEXT")
    if "status_updated_at" not in user_cols:
        cur.execute("ALTER TABLE users ADD COLUMN status_updated_at TEXT")
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


# ---------- statuses (где я сейчас) ----------

# Допустимые коды статусов
STATUS_APARTMENT = "apartment"      # квартира
STATUS_DACHA = "dacha"              # дача
STATUS_GRANDPARENTS = "grandparents"  # у деда с бабой
STATUS_NOT_HOME = "not_home"        # не дома

VALID_STATUSES = {
    STATUS_APARTMENT,
    STATUS_DACHA,
    STATUS_GRANDPARENTS,
    STATUS_NOT_HOME,
}


def set_user_status(telegram_id: int, status: str) -> None:
    """Устанавливает текущий статус пользователя. Пишет timestamp."""
    if status not in VALID_STATUSES:
        raise ValueError(f"Unknown status: {status}")
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "UPDATE users "
        "SET status = ?, status_updated_at = ? "
        "WHERE telegram_id = ?",
        (
            status,
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            telegram_id,
        ),
    )
    conn.commit()
    conn.close()


def get_all_users_with_status() -> list[dict]:
    """Все пользователи с их текущим статусом (если указали)."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, telegram_id, name, status, status_updated_at "
        "FROM users ORDER BY name"
    )
    rows = cur.fetchall()
    conn.close()
    return [
        {
            "id": r[0],
            "telegram_id": r[1],
            "name": r[2],
            "status": r[3],
            "status_updated_at": r[4],
        }
        for r in rows
    ]
