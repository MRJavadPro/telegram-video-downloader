import sqlite3
import os
from datetime import datetime, timedelta
from typing import Optional


DB_PATH = os.getenv("DB_PATH", "./data/bot.db")


class Database:
    def __init__(self):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                is_banned INTEGER DEFAULT 0,
                total_downloads INTEGER DEFAULT 0,
                first_seen TEXT,
                last_active TEXT
            );

            CREATE TABLE IF NOT EXISTS downloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                video_title TEXT,
                video_url TEXT,
                quality TEXT,
                file_size INTEGER,
                download_time REAL,
                status TEXT DEFAULT 'success',
                timestamp TEXT,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        """)
        self.conn.commit()

    def add_user(self, user_id: int, username: str = "", first_name: str = "", last_name: str = ""):
        now = datetime.now().isoformat()
        self.conn.execute("""
            INSERT OR IGNORE INTO users (user_id, username, first_name, last_name, first_seen, last_active)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, username or "", first_name or "", last_name or "", now, now))
        self.conn.execute(
            "UPDATE users SET username=?, first_name=?, last_name=?, last_active=? WHERE user_id=?",
            (username or "", first_name or "", last_name or "", now, user_id)
        )
        self.conn.commit()

    def is_banned(self, user_id: int) -> bool:
        row = self.conn.execute("SELECT is_banned FROM users WHERE user_id=?", (user_id,)).fetchone()
        return bool(row and row["is_banned"])

    def ban_user(self, user_id: int):
        self.conn.execute("UPDATE users SET is_banned=1 WHERE user_id=?", (user_id,))
        self.conn.commit()

    def unban_user(self, user_id: int):
        self.conn.execute("UPDATE users SET is_banned=0 WHERE user_id=?", (user_id,))
        self.conn.commit()

    def log_download(self, user_id: int, video_title: str, video_url: str, quality: str, file_size: int, download_time: float, status: str = "success"):
        now = datetime.now().isoformat()
        self.conn.execute("""
            INSERT INTO downloads (user_id, video_title, video_url, quality, file_size, download_time, status, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, video_title, video_url, quality, file_size, download_time, status, now))
        self.conn.execute(
            "UPDATE users SET total_downloads = total_downloads + 1, last_active=? WHERE user_id=?",
            (now, user_id)
        )
        self.conn.commit()

    def get_user_stats(self, user_id: int) -> Optional[dict]:
        row = self.conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            return None
        return dict(row)

    def get_all_users(self) -> list:
        rows = self.conn.execute("SELECT * FROM users ORDER BY last_active DESC").fetchall()
        return [dict(r) for r in rows]

    def get_total_users(self) -> int:
        return self.conn.execute("SELECT COUNT(*) as cnt FROM users").fetchone()["cnt"]

    def get_total_downloads(self) -> int:
        return self.conn.execute("SELECT COUNT(*) as cnt FROM downloads").fetchone()["cnt"]

    def get_today_downloads(self) -> int:
        today = datetime.now().strftime("%Y-%m-%d")
        return self.conn.execute(
            "SELECT COUNT(*) as cnt FROM downloads WHERE timestamp LIKE ?",
            (f"{today}%",)
        ).fetchone()["cnt"]

    def get_downloads_by_date(self, days: int = 7) -> list:
        results = []
        for i in range(days):
            date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            cnt = self.conn.execute(
                "SELECT COUNT(*) as cnt FROM downloads WHERE timestamp LIKE ?",
                (f"{date}%",)
            ).fetchone()["cnt"]
            results.append({"date": date, "count": cnt})
        return list(reversed(results))

    def get_user_downloads(self, user_id: int, limit: int = 20) -> list:
        rows = self.conn.execute(
            "SELECT * FROM downloads WHERE user_id=? ORDER BY timestamp DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_setting(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str):
        self.conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value)
        )
        self.conn.commit()

    def get_top_users(self, limit: int = 10) -> list:
        rows = self.conn.execute(
            "SELECT * FROM users ORDER BY total_downloads DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


db = Database()
