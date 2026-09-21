import asyncio
import os
import sqlite3
from datetime import datetime, timezone


class Database:
    """Small async persistence layer.

    Uses PostgreSQL on Railway when DATABASE_URL is configured; otherwise falls
    back to SQLite. The fallback is useful for local tests. PostgreSQL is the
    recommended production backend because Railway's ephemeral filesystem can
    be reset between deployments/restarts.
    """

    def __init__(self):
        self.url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")
        self.sqlite_path = os.getenv("SQLITE_PATH", "bot_state.sqlite3")
        self.pool = None
        self._sqlite_lock = asyncio.Lock()

    async def init(self):
        if self.url:
            try:
                import asyncpg
                url = self.url.replace("postgres://", "postgresql://", 1)
                self.pool = await asyncpg.create_pool(url, min_size=1, max_size=4)
                await self.pool.execute("""
                    CREATE TABLE IF NOT EXISTS works (
                        id BIGSERIAL PRIMARY KEY,
                        source TEXT NOT NULL,
                        source_url TEXT NOT NULL,
                        title TEXT NOT NULL,
                        cover_file_id TEXT,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        UNIQUE(source, source_url)
                    );
                    CREATE TABLE IF NOT EXISTS sent_chapters (
                        chat_id BIGINT NOT NULL,
                        work_id BIGINT NOT NULL REFERENCES works(id) ON DELETE CASCADE,
                        chapter_key TEXT NOT NULL,
                        chapter_number TEXT,
                        name TEXT,
                        telegram_file_id TEXT,
                        sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY(chat_id, work_id, chapter_key)
                    );
                """)
                return
            except Exception as exc:
                print(f"DATABASE_URL indisponível; usando SQLite: {exc}")
                self.pool = None

        await asyncio.to_thread(self._sqlite_init)

    def _sqlite_conn(self):
        c = sqlite3.connect(self.sqlite_path, check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c

    def _sqlite_init(self):
        c = self._sqlite_conn()
        try:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS works (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    cover_file_id TEXT,
                    updated_at TEXT NOT NULL,
                    UNIQUE(source, source_url)
                );
                CREATE TABLE IF NOT EXISTS sent_chapters (
                    chat_id INTEGER NOT NULL,
                    work_id INTEGER NOT NULL,
                    chapter_key TEXT NOT NULL,
                    chapter_number TEXT,
                    name TEXT,
                    telegram_file_id TEXT,
                    sent_at TEXT NOT NULL,
                    PRIMARY KEY(chat_id, work_id, chapter_key),
                    FOREIGN KEY(work_id) REFERENCES works(id) ON DELETE CASCADE
                );
            """)
            c.commit()
        finally:
            c.close()

    async def get_or_create_work(self, source, source_url, title):
        now = datetime.now(timezone.utc).isoformat()
        if self.pool:
            async with self.pool.acquire() as c:
                row = await c.fetchrow(
                    """INSERT INTO works(source, source_url, title, updated_at)
                       VALUES($1,$2,$3,NOW())
                       ON CONFLICT(source, source_url) DO UPDATE SET title=EXCLUDED.title, updated_at=NOW()
                       RETURNING id, source, source_url, title, cover_file_id""",
                    source, str(source_url), title,
                )
                return dict(row)

        async with self._sqlite_lock:
            def op():
                c = self._sqlite_conn()
                try:
                    c.execute("""INSERT INTO works(source, source_url, title, updated_at)
                                 VALUES(?,?,?,?)
                                 ON CONFLICT(source, source_url) DO UPDATE SET title=excluded.title, updated_at=excluded.updated_at""",
                              (source, str(source_url), title, now))
                    c.commit()
                    row = c.execute("SELECT id,source,source_url,title,cover_file_id FROM works WHERE source=? AND source_url=?",
                                    (source, str(source_url))).fetchone()
                    return dict(row)
                finally:
                    c.close()
            return await asyncio.to_thread(op)

    async def set_cover_file_id(self, work_id, file_id):
        if not file_id:
            return
        if self.pool:
            await self.pool.execute("UPDATE works SET cover_file_id=$1, updated_at=NOW() WHERE id=$2", file_id, work_id)
            return
        async with self._sqlite_lock:
            await asyncio.to_thread(self._sqlite_set_cover, work_id, file_id)

    def _sqlite_set_cover(self, work_id, file_id):
        c = self._sqlite_conn()
        try:
            c.execute("UPDATE works SET cover_file_id=?, updated_at=? WHERE id=?",
                      (file_id, datetime.now(timezone.utc).isoformat(), work_id))
            c.commit()
        finally:
            c.close()

    async def sent_keys(self, chat_id, work_id):
        if self.pool:
            rows = await self.pool.fetch("SELECT chapter_key FROM sent_chapters WHERE chat_id=$1 AND work_id=$2", chat_id, work_id)
            return {r["chapter_key"] for r in rows}
        async with self._sqlite_lock:
            def op():
                c = self._sqlite_conn()
                try:
                    rows = c.execute("SELECT chapter_key FROM sent_chapters WHERE chat_id=? AND work_id=?", (chat_id, work_id)).fetchall()
                    return {r[0] for r in rows}
                finally:
                    c.close()
            return await asyncio.to_thread(op)

    async def mark_sent(self, chat_id, work_id, chapter_key, chapter_number, name, telegram_file_id=None):
        now = datetime.now(timezone.utc).isoformat()
        if self.pool:
            await self.pool.execute(
                """INSERT INTO sent_chapters(chat_id,work_id,chapter_key,chapter_number,name,telegram_file_id)
                   VALUES($1,$2,$3,$4,$5,$6)
                   ON CONFLICT(chat_id,work_id,chapter_key) DO UPDATE SET telegram_file_id=EXCLUDED.telegram_file_id""",
                chat_id, work_id, chapter_key, str(chapter_number or ""), str(name or ""), telegram_file_id,
            )
            return
        async with self._sqlite_lock:
            await asyncio.to_thread(self._sqlite_mark, chat_id, work_id, chapter_key, chapter_number, name, telegram_file_id, now)

    def _sqlite_mark(self, chat_id, work_id, chapter_key, chapter_number, name, telegram_file_id, now):
        c = self._sqlite_conn()
        try:
            c.execute("""INSERT INTO sent_chapters(chat_id,work_id,chapter_key,chapter_number,name,telegram_file_id,sent_at)
                         VALUES(?,?,?,?,?,?,?)
                         ON CONFLICT(chat_id,work_id,chapter_key) DO UPDATE SET telegram_file_id=excluded.telegram_file_id""",
                      (chat_id, work_id, chapter_key, str(chapter_number or ""), str(name or ""), telegram_file_id, now))
            c.commit()
        finally:
            c.close()

    async def close(self):
        if self.pool:
            await self.pool.close()
