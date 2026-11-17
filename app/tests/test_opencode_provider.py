import json

import httpx
import pytest

from app.ai.opencode_provider import FALLBACK_REPLY, OpenCodeProvider
from app.database import Database

FW = "\uff5c"
DSML_ONLY = (
    f"<{FW}DSML{FW} calls>\n"
    f'<{FW}DSML{FW} invoke name="bash">\n'
    f"</{FW}DSML{FW} invoke>\n"
    f"</{FW}DSML{FW} calls>"
)


def make_provider(handler):
    provider = OpenCodeProvider(
        db=None,  # type: ignore[arg-type]
        base_url="http://opencode.test",
        agent="whatsapp",
        provider_id="opencode-go",
        model_id="deepseek-v4.1-flash",
    )
    provider._client = httpx.AsyncClient(
        base_url="http://opencode.test",
        transport=httpx.MockTransport(handler),
    )
    return provider


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "bot.sqlite3")
    await database.connect()
    yield database
    await database.close()


def message_response(text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "info": {"role": "assistant"},
            "parts": [{"type": "text", "text": text}],
        },
    )


async def test_reply_uses_whatsapp_agent_without_tools(db):
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.read())
        return message_response("Ola!")

    provider = make_provider(handler)
    await db.set_session_id("5511@s.whatsapp.net", "ses_test")
    provider.db = db

    reply = await provider.reply(
        jid="5511@s.whatsapp.net", system="seja breve", history=[], user_text="oi"
    )
    await provider._client.aclose()

    assert reply == "Ola!"
    assert captured["body"]["agent"] == "whatsapp"
    assert "tools" not in captured["body"]


async def test_reply_retries_when_only_dsml(db):
    calls = []

    def handler(request):
        calls.append(json.loads(request.read()))
        if len(calls) == 1:
            return message_response(DSML_ONLY)
        return message_response("A cotacao esta em R$ 5,40.")

    provider = make_provider(handler)
    await db.set_session_id("5511@s.whatsapp.net", "ses_test")
    provider.db = db

    reply = await provider.reply(
        jid="5511@s.whatsapp.net", system="seja breve", history=[], user_text="dolar?"
    )
    await provider._client.aclose()

    assert reply == "A cotacao esta em R$ 5,40."
    assert len(calls) == 2
    assert "Refaca a resposta" in calls[1]["parts"][0]["text"]
    assert "DSML" in calls[1]["system"]


async def test_reply_returns_fallback_when_retry_is_also_dsml(db):
    def handler(request):
        return message_response(DSML_ONLY)

    provider = make_provider(handler)
    await db.set_session_id("5511@s.whatsapp.net", "ses_test")
    provider.db = db

    reply = await provider.reply(
        jid="5511@s.whatsapp.net", system="seja breve", history=[], user_text="dolar?"
    )
    await provider._client.aclose()

    assert reply == FALLBACK_REPLY
    assert "DSML" not in reply


async def test_reply_keeps_text_when_dsml_is_mixed(db):
    def handler(request):
        return message_response(f"Cotacao: R$ 5,40.\n{DSML_ONLY}")

    provider = make_provider(handler)
    await db.set_session_id("5511@s.whatsapp.net", "ses_test")
    provider.db = db

    reply = await provider.reply(
        jid="5511@s.whatsapp.net", system="seja breve", history=[], user_text="dolar?"
    )
    await provider._client.aclose()

    assert reply == "Cotacao: R$ 5,40."
