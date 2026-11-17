import httpx
import pytest

from app.config import Settings
from app.evolution import EvolutionClient, EvolutionError


def make_client(handler):
    settings = Settings(
        _env_file=None,
        evolution_base_url="https://evo.test",
        evolution_instance="instancia",
        evolution_api_key="chave",
        evolution_audio_delay=1200,
        evolution_audio_encoding=True,
    )
    client = EvolutionClient(settings)
    client._client = httpx.AsyncClient(
        base_url=settings.evolution_base_url,
        transport=httpx.MockTransport(handler),
    )
    return client


async def test_send_whatsapp_audio_payload():
    captured = {}

    def handler(request):
        captured["path"] = request.url.path
        captured["apikey"] = request.headers.get("apikey")
        captured["body"] = request.read().decode()
        return httpx.Response(200, json={"ok": True})

    client = make_client(handler)
    await client.send_whatsapp_audio(
        "5531999999999@s.whatsapp.net", "data:audio/wav;base64,QUJD"
    )
    await client._client.aclose()

    assert captured["path"] == "/message/sendWhatsAppAudio/instancia"
    assert captured["apikey"] == "chave"
    assert '"audio":"QUJD"' in captured["body"].replace(" ", "")
    assert '"delay":1200' in captured["body"].replace(" ", "")
    assert '"encoding":true' in captured["body"].replace(" ", "")


async def test_send_whatsapp_audio_clamps_delay():
    captured = {}

    def handler(request):
        captured["body"] = request.read().decode().replace(" ", "")
        return httpx.Response(200, json={"ok": True})

    client = make_client(handler)
    await client.send_whatsapp_audio("1@s.whatsapp.net", "QUJD", delay=999_999)
    await client._client.aclose()

    assert '"delay":110000' in captured["body"]


async def test_send_whatsapp_audio_rejects_empty():
    def handler(request):
        return httpx.Response(200, json={"ok": True})

    client = make_client(handler)
    with pytest.raises(EvolutionError, match="vazio"):
        await client.send_whatsapp_audio("1@s.whatsapp.net", "  ")
    await client._client.aclose()


async def test_send_whatsapp_audio_raises_on_error():
    def handler(request):
        return httpx.Response(500, text="falhou")

    client = make_client(handler)
    with pytest.raises(EvolutionError, match="500"):
        await client.send_whatsapp_audio("1@s.whatsapp.net", "QUJD")
    await client._client.aclose()
