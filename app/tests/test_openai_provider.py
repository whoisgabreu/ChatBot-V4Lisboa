import httpx
import pytest

from app.ai.base import AIError, Attachment, ChatTurn
from app.ai.openai_provider import OpenAIProvider


def _provider(handler):
    provider = OpenAIProvider(
        base_url="https://api.test/v1",
        api_key="test",
        model="modelo",
        temperature=0.2,
        max_tokens=100,
    )
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return provider


async def test_reply_parses_content():
    def handler(request):
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test"
        return httpx.Response(200, json={"choices": [{"message": {"content": "ola!"}}]})

    provider = _provider(handler)
    reply = await provider.reply(
        jid="1@s.whatsapp.net",
        system="seja breve",
        history=[ChatTurn("user", "oi"), ChatTurn("assistant", "oi!")],
        user_text="tudo bem?",
    )
    assert reply == "ola!"


async def test_reply_includes_image():
    captured = {}

    def handler(request):
        captured["body"] = request.read().decode()
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    provider = _provider(handler)
    await provider.reply(
        jid="1@s.whatsapp.net",
        system="s",
        history=[],
        user_text="veja",
        attachments=[Attachment(kind="image", mime="image/png", data=b"abc")],
    )
    assert "image_url" in captured["body"]
    assert "data:image/png;base64,YWJj" in captured["body"]


async def test_reply_raises_on_provider_error():
    def handler(request):
        return httpx.Response(500, json={"error": "boom"})

    provider = _provider(handler)
    with pytest.raises(AIError, match="500"):
        await provider.reply(jid="1", system="s", history=[], user_text="oi")


async def test_retry_without_temperature_on_400():
    calls = {"count": 0}

    def handler(request):
        calls["count"] += 1
        body = request.read().decode()
        if "temperature" in body:
            return httpx.Response(400, json={"error": "unsupported"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    provider = _provider(handler)
    reply = await provider.reply(jid="1", system="s", history=[], user_text="oi")
    assert reply == "ok"
    assert calls["count"] == 2
