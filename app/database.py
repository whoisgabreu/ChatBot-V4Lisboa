from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS contacts (
    jid         TEXT PRIMARY KEY,
    name        TEXT,
    session_id  TEXT,
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    jid         TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    created_at  INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_jid_id ON messages (jid, id);

CREATE TABLE IF NOT EXISTS processed_events (
    event_id    TEXT PRIMARY KEY,
    created_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS prefs (
    jid         TEXT NOT NULL,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    PRIMARY KEY (jid, key)
);
"""


@dataclass(slots=True)
class StoredMessage:
    role: str
    content: str


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.executescript(SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    def _conn(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("database not connected")
        return self._db

    async def is_new_event(self, event_id: str) -> bool:
        """Returns True if the event was not processed before (and marks it)."""
        async with self._lock:
            db = self._conn()
            cursor = await db.execute(
                "INSERT OR IGNORE INTO processed_events (event_id, created_at) VALUES (?, ?)",
                (event_id, int(time.time())),
            )
            await db.commit()
            return cursor.rowcount == 1

    async def cleanup_events(self, ttl_seconds: int) -> None:
        cutoff = int(time.time()) - ttl_seconds
        async with self._lock:
            db = self._conn()
            await db.execute(
                "DELETE FROM processed_events WHERE created_at < ?", (cutoff,)
            )
            await db.commit()

    async def upsert_contact(self, jid: str, name: str | None) -> None:
        now = int(time.time())
        async with self._lock:
            db = self._conn()
            await db.execute(
                """
                INSERT INTO contacts (jid, name, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(jid) DO UPDATE SET
                    name = COALESCE(excluded.name, contacts.name),
                    updated_at = excluded.updated_at
                """,
                (jid, name, now, now),
            )
            await db.commit()

    async def get_session_id(self, jid: str) -> str | None:
        async with self._lock:
            db = self._conn()
            cursor = await db.execute(
                "SELECT session_id FROM contacts WHERE jid = ?", (jid,)
            )
            row = await cursor.fetchone()
            return row["session_id"] if row else None

    async def set_session_id(self, jid: str, session_id: str | None) -> None:
        now = int(time.time())
        async with self._lock:
            db = self._conn()
            await db.execute(
                """
                INSERT INTO contacts (jid, session_id, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(jid) DO UPDATE SET
                    session_id = excluded.session_id,
                    updated_at = excluded.updated_at
                """,
                (jid, session_id, now, now),
            )
            await db.commit()

    async def add_message(self, jid: str, role: str, content: str) -> None:
        async with self._lock:
            db = self._conn()
            await db.execute(
                "INSERT INTO messages (jid, role, content, created_at) VALUES (?, ?, ?, ?)",
                (jid, role, content, int(time.time())),
            )
            await db.commit()

    async def get_history(
        self, jid: str, limit: int, max_chars: int
    ) -> list[StoredMessage]:
        async with self._lock:
            db = self._conn()
            cursor = await db.execute(
                "SELECT role, content FROM messages WHERE jid = ? ORDER BY id DESC LIMIT ?",
                (jid, max(1, limit)),
            )
            rows = await cursor.fetchall()

        history: list[StoredMessage] = []
        total = 0
        for row in rows:
            content = row["content"]
            if total + len(content) > max_chars and history:
                break
            total += len(content)
            history.append(StoredMessage(role=row["role"], content=content))

        history.reverse()
        return history

    async def clear_history(self, jid: str) -> None:
        async with self._lock:
            db = self._conn()
            await db.execute("DELETE FROM messages WHERE jid = ?", (jid,))
            await db.commit()

    async def get_pref(self, jid: str, key: str) -> str | None:
        async with self._lock:
            db = self._conn()
            cursor = await db.execute(
                "SELECT value FROM prefs WHERE jid = ? AND key = ?", (jid, key)
            )
            row = await cursor.fetchone()
            return row["value"] if row else None

    async def set_pref(self, jid: str, key: str, value: str) -> None:
        async with self._lock:
            db = self._conn()
            await db.execute(
                """
                INSERT INTO prefs (jid, key, value) VALUES (?, ?, ?)
                ON CONFLICT(jid, key) DO UPDATE SET value = excluded.value
                """,
                (jid, key, value),
            )
            await db.commit()

    async def count_messages(self, jid: str) -> int:
        async with self._lock:
            db = self._conn()
            cursor = await db.execute(
                "SELECT COUNT(*) AS total FROM messages WHERE jid = ?", (jid,)
            )
            row = await cursor.fetchone()
            return int(row["total"]) if row else 0
