import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "bot.db")


def _ensure_dir():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


def _connect():
    _ensure_dir()
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = _connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stats (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            download_count INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS download_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            platform TEXT,
            title TEXT,
            url TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS banned_users (
            user_id INTEGER PRIMARY KEY,
            banned_by INTEGER,
            reason TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def increment_downloads(user_id: int, username: str, full_name: str):
    conn = _connect()
    conn.execute("""
        INSERT INTO stats (user_id, username, full_name, download_count)
        VALUES (?, ?, ?, 1)
        ON CONFLICT(user_id) DO UPDATE SET
            download_count = download_count + 1,
            username = excluded.username,
            full_name = excluded.full_name
    """, (user_id, username, full_name))
    conn.commit()
    conn.close()


def log_download(user_id: int, platform: str, title: str, url: str):
    conn = _connect()
    conn.execute(
        "INSERT INTO download_logs (user_id, platform, title, url) VALUES (?, ?, ?, ?)",
        (user_id, platform, title, url),
    )
    conn.commit()
    conn.close()


def get_stats(user_id: int) -> int:
    conn = _connect()
    row = conn.execute(
        "SELECT download_count FROM stats WHERE user_id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return row[0] if row else 0


def get_total_stats() -> int:
    conn = _connect()
    row = conn.execute("SELECT SUM(download_count) FROM stats").fetchone()
    conn.close()
    return row[0] if row and row[0] else 0


def get_total_users() -> int:
    conn = _connect()
    row = conn.execute("SELECT COUNT(*) FROM stats").fetchone()
    conn.close()
    return row[0] if row else 0


def get_all_users() -> list[dict]:
    conn = _connect()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT user_id, username, full_name, download_count FROM stats ORDER BY download_count DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_user_history(user_id: int, limit: int = 10) -> list[dict]:
    conn = _connect()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT platform, title, url, timestamp FROM download_logs WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def ban_user(user_id: int, banned_by: int, reason: str = ""):
    conn = _connect()
    conn.execute(
        "INSERT OR REPLACE INTO banned_users (user_id, banned_by, reason) VALUES (?, ?, ?)",
        (user_id, banned_by, reason),
    )
    conn.commit()
    conn.close()


def unban_user(user_id: int):
    conn = _connect()
    conn.execute("DELETE FROM banned_users WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def is_banned(user_id: int) -> bool:
    conn = _connect()
    row = conn.execute(
        "SELECT 1 FROM banned_users WHERE user_id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return row is not None


def get_banned_users() -> list[dict]:
    conn = _connect()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT b.user_id, b.reason, b.timestamp, s.username, s.full_name
           FROM banned_users b
           LEFT JOIN stats s ON b.user_id = s.user_id
           ORDER BY b.timestamp DESC"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
