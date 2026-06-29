import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "bot.db")


def _ensure_dir():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


def init_db():
    _ensure_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stats (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            download_count INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


def increment_downloads(user_id: int, username: str):
    _ensure_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO stats (user_id, username, download_count)
        VALUES (?, ?, 1)
        ON CONFLICT(user_id) DO UPDATE SET
            download_count = download_count + 1,
            username = excluded.username
    """, (user_id, username))
    conn.commit()
    conn.close()


def get_stats(user_id: int) -> int:
    _ensure_dir()
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT download_count FROM stats WHERE user_id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return row[0] if row else 0


def get_total_stats() -> int:
    _ensure_dir()
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT SUM(download_count) FROM stats").fetchone()
    conn.close()
    return row[0] if row and row[0] else 0
