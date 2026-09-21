import asyncio
import os
import sqlite3
from pathlib import Path
from typing import Optional


class Database:
    """SQLite persistente usando somente a biblioteca padrão do Python."""

    def __init__(self):
        mount_path = os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
        configured = os.getenv("SQLITE_DB_PATH")
        if configured:
            self.path = Path(configured)
        elif mount_path:
            self.path = Path(mount_path) / "bot.db"
        else:
            self.path = Path("data") / "bot.db"
        self.conn: Optional[sqlite3.Connection] = None
        self.lock = asyncio.Lock()

    async def connect(self):
        if self.conn is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path.as_posix(), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS works (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                source TEXT NOT NULL,
                source_url TEXT NOT NULL,
                cover_file_id TEXT,
                last_update TEXT,
                UNIQUE(source, source_url)
            );

            CREATE TABLE IF NOT EXISTS chapters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                work_id INTEGER NOT NULL,
                chapter_number TEXT,
                source_url TEXT NOT NULL,
                telegram_file_id TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                sent_at TEXT,
                UNIQUE(work_id, source_url),
                FOREIGN KEY(work_id) REFERENCES works(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_chapters_work_status
                ON chapters(work_id, status);
            """
        )
        self.conn.commit()

    async def close(self):
        async with self.lock:
            if self.conn is not None:
                self.conn.close()
                self.conn = None

    async def ensure_work(self, title: str, source: str, source_url: str) -> int:
        await self.connect()
        async with self.lock:
            self.conn.execute(
                """
                INSERT INTO works(title, source, source_url)
                VALUES (?, ?, ?)
                ON CONFLICT(source, source_url) DO UPDATE SET title=excluded.title
                """,
                (title, source, source_url),
            )
            self.conn.commit()
            row = self.conn.execute(
                "SELECT id FROM works WHERE source=? AND source_url=?",
                (source, source_url),
            ).fetchone()
            return int(row[0])

    async def is_chapter_sent(self, source: str, source_url: str) -> bool:
        await self.connect()
        async with self.lock:
            row = self.conn.execute(
                """
                SELECT 1
                FROM chapters c
                JOIN works w ON w.id=c.work_id
                WHERE w.source=? AND c.source_url=? AND c.status='sent'
                LIMIT 1
                """,
                (source, source_url),
            ).fetchone()
            return row is not None

    async def save_chapter_sent(
        self,
        title: str,
        source: str,
        work_url: str,
        chapter_url: str,
        chapter_number: str,
        telegram_file_id: Optional[str],
    ):
        work_id = await self.ensure_work(title, source, work_url)
        async with self.lock:
            self.conn.execute(
                """
                INSERT INTO chapters(work_id, chapter_number, source_url, telegram_file_id, status, sent_at)
                VALUES (?, ?, ?, ?, 'sent', datetime('now'))
                ON CONFLICT(work_id, source_url) DO UPDATE SET
                    chapter_number=excluded.chapter_number,
                    telegram_file_id=excluded.telegram_file_id,
                    status='sent',
                    sent_at=datetime('now')
                """,
                (work_id, chapter_number, chapter_url, telegram_file_id),
            )
            self.conn.commit()

    async def get_chapter_file_id(self, source: str, source_url: str) -> Optional[str]:
        await self.connect()
        async with self.lock:
            row = self.conn.execute(
                """
                SELECT c.telegram_file_id
                FROM chapters c
                JOIN works w ON w.id=c.work_id
                WHERE w.source=? AND c.source_url=? AND c.status='sent'
                LIMIT 1
                """,
                (source, source_url),
            ).fetchone()
            return row[0] if row else None

    async def set_cover_file_id(self, title: str, source: str, source_url: str, file_id: str):
        work_id = await self.ensure_work(title, source, source_url)
        async with self.lock:
            self.conn.execute(
                "UPDATE works SET cover_file_id=? WHERE id=?",
                (file_id, work_id),
            )
            self.conn.commit()


DB = Database()
