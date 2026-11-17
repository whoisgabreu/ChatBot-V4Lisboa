import pytest

from app.database import Database


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "bot.sqlite3")
    await database.connect()
    yield database
    await database.close()


async def test_deduplicate_events(db):
    assert await db.is_new_event("a:1") is True
    assert await db.is_new_event("a:1") is False
    assert await db.is_new_event("a:2") is True


async def test_history_respects_limits(db):
    jid = "5511999999999@s.whatsapp.net"
    for index in range(5):
        await db.add_message(jid, "user", f"mensagem {index}")

    history = await db.get_history(jid, limit=3, max_chars=10_000)
    assert [item.content for item in history] == [
        "mensagem 2",
        "mensagem 3",
        "mensagem 4",
    ]

    limited = await db.get_history(jid, limit=10, max_chars=15)
    assert len(limited) == 1


async def test_prefs_and_session(db):
    jid = "5511999999999@s.whatsapp.net"
    assert await db.get_pref(jid, "prompt") is None
    await db.set_pref(jid, "prompt", "vendas")
    assert await db.get_pref(jid, "prompt") == "vendas"

    assert await db.get_session_id(jid) is None
    await db.set_session_id(jid, "ses_123")
    assert await db.get_session_id(jid) == "ses_123"
    await db.set_session_id(jid, None)
    assert await db.get_session_id(jid) is None


async def test_clear_history(db):
    jid = "5511999999999@s.whatsapp.net"
    await db.add_message(jid, "user", "oi")
    await db.clear_history(jid)
    assert await db.get_history(jid, 10, 1000) == []
