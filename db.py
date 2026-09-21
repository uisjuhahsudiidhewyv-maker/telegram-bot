import os
import sqlite3
from datetime import datetime, timezone

try:
    import asyncpg
except ImportError:  # pragma: no cover
    asyncpg = None


class Database:
    def __init__(self):
        self.url = (os.getenv("DATABASE_URL") or "").strip()
        self.sqlite_path = os.getenv("DB_PATH", "bot.db")
        self.pool = None
        self.kind = "postgres" if self.url else "sqlite"

    async def connect(self):
        if self.kind == "postgres":
            if asyncpg is None:
                raise RuntimeError("DATABASE_URL foi definido, mas o pacote asyncpg não está instalado.")
            url = self.url.replace("postgres://", "postgresql://", 1)
            self.pool = await asyncpg.create_pool(url, min_size=1, max_size=4, command_timeout=30)
            async with self.pool.acquire() as con:
                await con.execute("""
                    CREATE TABLE IF NOT EXISTS works (
                        id BIGSERIAL PRIMARY KEY,
                        title TEXT NOT NULL,
                        source TEXT NOT NULL,
                        source_url TEXT NOT NULL,
                        cover_file_id TEXT,
                        last_update TIMESTAMPTZ,
                        UNIQUE(source, source_url)
                    )
                """)
                await con.execute("""
                    CREATE TABLE IF NOT EXISTS chapters (
                        id BIGSERIAL PRIMARY KEY,
                        work_id BIGINT NOT NULL REFERENCES works(id) ON DELETE CASCADE,
                        chapter_number TEXT,
                        chapter_name TEXT,
                        source_url TEXT NOT NULL,
                        telegram_file_id TEXT,
                        status TEXT NOT NULL DEFAULT 'PENDING',
                        sent_at TIMESTAMPTZ,
                        UNIQUE(work_id, source_url)
                    )
                """)
        else:
            con = sqlite3.connect(self.sqlite_path)
            try:
                con.execute("""
                    CREATE TABLE IF NOT EXISTS works (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL,
                        source TEXT NOT NULL,
                        source_url TEXT NOT NULL,
                        cover_file_id TEXT,
                        last_update TEXT,
                        UNIQUE(source, source_url)
                    )
                """)
                con.execute("""
                    CREATE TABLE IF NOT EXISTS chapters (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        work_id INTEGER NOT NULL,
                        chapter_number TEXT,
                        chapter_name TEXT,
                        source_url TEXT NOT NULL,
                        telegram_file_id TEXT,
                        status TEXT NOT NULL DEFAULT 'PENDING',
                        sent_at TEXT,
                        UNIQUE(work_id, source_url),
                        FOREIGN KEY(work_id) REFERENCES works(id) ON DELETE CASCADE
                    )
                """)
                con.commit()
            finally:
                con.close()

    async def close(self):
        if self.pool:
            await self.pool.close()
            self.pool = None

    @staticmethod
    def _now():
        return datetime.now(timezone.utc)

    async def upsert_work(self, title, source, source_url):
        if self.kind == "postgres":
            async with self.pool.acquire() as con:
                return await con.fetchval("""
                    INSERT INTO works(title, source, source_url, last_update)
                    VALUES($1,$2,$3,$4)
                    ON CONFLICT(source, source_url) DO UPDATE SET
                        title=EXCLUDED.title,
                        last_update=EXCLUDED.last_update
                    RETURNING id
                """, title, source, source_url, self._now())
        con = sqlite3.connect(self.sqlite_path)
        try:
            con.execute("""
                INSERT INTO works(title, source, source_url, last_update)
                VALUES(?,?,?,?)
                ON CONFLICT(source, source_url) DO UPDATE SET
                    title=excluded.title, last_update=excluded.last_update
            """, (title, source, source_url, self._now().isoformat()))
            row = con.execute("SELECT id FROM works WHERE source=? AND source_url=?", (source, source_url)).fetchone()
            con.commit()
            return row[0]
        finally:
            con.close()

    async def get_cover_file_id(self, source, source_url):
        if self.kind == "postgres":
            async with self.pool.acquire() as con:
                return await con.fetchval("SELECT cover_file_id FROM works WHERE source=$1 AND source_url=$2", source, source_url)
        con = sqlite3.connect(self.sqlite_path)
        try:
            row = con.execute("SELECT cover_file_id FROM works WHERE source=? AND source_url=?", (source, source_url)).fetchone()
            return row[0] if row else None
        finally:
            con.close()

    async def set_cover_file_id(self, source, source_url, file_id):
        if self.kind == "postgres":
            async with self.pool.acquire() as con:
                await con.execute("""
                    UPDATE works SET cover_file_id=$1, last_update=$2
                    WHERE source=$3 AND source_url=$4
                """, file_id, self._now(), source, source_url)
            return
        con = sqlite3.connect(self.sqlite_path)
        try:
            con.execute("""
                UPDATE works SET cover_file_id=?, last_update=?
                WHERE source=? AND source_url=?
            """, (file_id, self._now().isoformat(), source, source_url))
            con.commit()
        finally:
            con.close()

    async def upsert_chapter(self, work_id, chapter):
        number = str(chapter.get("chapter_number") or "")
        name = str(chapter.get("name") or "")
        url = str(chapter.get("url") or "")
        if not url:
            return None
        if self.kind == "postgres":
            async with self.pool.acquire() as con:
                return await con.fetchval("""
                    INSERT INTO chapters(work_id, chapter_number, chapter_name, source_url)
                    VALUES($1,$2,$3,$4)
                    ON CONFLICT(work_id, source_url) DO UPDATE SET
                        chapter_number=EXCLUDED.chapter_number,
                        chapter_name=EXCLUDED.chapter_name
                    RETURNING id
                """, work_id, number, name, url)
        con = sqlite3.connect(self.sqlite_path)
        try:
            con.execute("""
                INSERT INTO chapters(work_id, chapter_number, chapter_name, source_url)
                VALUES(?,?,?,?)
                ON CONFLICT(work_id, source_url) DO UPDATE SET
                    chapter_number=excluded.chapter_number,
                    chapter_name=excluded.chapter_name
            """, (work_id, number, name, url))
            row = con.execute("SELECT id FROM chapters WHERE work_id=? AND source_url=?", (work_id, url)).fetchone()
            con.commit()
            return row[0]
        finally:
            con.close()

    async def mark_chapter_sent(self, work_id, source_url, telegram_file_id):
        if self.kind == "postgres":
            async with self.pool.acquire() as con:
                await con.execute("""
                    UPDATE chapters SET telegram_file_id=$1, status='SENT', sent_at=$2
                    WHERE work_id=$3 AND source_url=$4
                """, telegram_file_id, self._now(), work_id, source_url)
            return
        con = sqlite3.connect(self.sqlite_path)
        try:
            con.execute("""
                UPDATE chapters SET telegram_file_id=?, status='SENT', sent_at=?
                WHERE work_id=? AND source_url=?
            """, (telegram_file_id, 'sent', work_id, source_url))
            con.commit()
        finally:
            con.close()

    async def is_chapter_sent(self, source, source_url, chapter_url):
        if self.kind == "postgres":
            async with self.pool.acquire() as con:
                return bool(await con.fetchval("""
                    SELECT EXISTS(
                        SELECT 1 FROM chapters c JOIN works w ON w.id=c.work_id
                        WHERE w.source=$1 AND w.source_url=$2 AND c.source_url=$3 AND c.status='SENT'
                    )
                """, source, source_url, chapter_url))
        con = sqlite3.connect(self.sqlite_path)
        try:
            row = con.execute("""
                SELECT 1 FROM chapters c JOIN works w ON w.id=c.work_id
                WHERE w.source=? AND w.source_url=? AND c.source_url=? AND c.status='SENT'
            """, (source, source_url, chapter_url)).fetchone()
            return bool(row)
        finally:
            con.close()

