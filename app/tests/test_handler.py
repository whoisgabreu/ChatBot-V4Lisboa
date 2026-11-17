import base64

import pytest

from app.ai.base import AIProvider
from app.config import Settings
from app.database import Database
from app.evolution import EvolutionError
from app.handler import ChatHandler
from app.models import IncomingMessage
from app.prompts import PromptManager
from app.tts import TTSError


class FakeAI(AIProvider):
    name = "fake"
    supports_vision = True

    def __init__(self):
        self.calls = []
        self.resets = []

    async def reply(self, *, jid, system, history, user_text, attachments=None):
        self.calls.append(
            {
                "jid": jid,
                "system": system,
                "history": history,
                "user_text": user_text,
                "attachments": attachments or [],
            }
        )
        return f"resposta para: {user_text}"

    async def reset(self, jid):
        self.resets.append(jid)


class FakeEvolution:
    def __init__(self):
        self.sent = []
        self.audios = []
        self.fail_audio = False

    async def send_text(self, jid, text):
        self.sent.append((jid, text))

    async def send_whatsapp_audio(self, jid, audio_base64, delay=None, encoding=None):
        if self.fail_audio:
            raise EvolutionError("falha simulada")
        self.audios.append((jid, audio_base64))

    async def send_presence(self, jid, presence="composing"):
        return None

    async def mark_read(self, jid, message_id):
        return None

    async def resolve_media(self, media):
        return None


class FakeTTS:
    enabled = True
    status = "ready"

    def __init__(self):
        self.texts = []
        self.fail = False

    async def synthesize(self, text):
        if self.fail:
            raise TTSError("falha simulada")
        self.texts.append(text)
        return b"RIFF-audio-fake"


@pytest.fixture
async def env(tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "system.md").write_text("Atenda {{name}}.", encoding="utf-8")
    (prompts_dir / "vendas.md").write_text("Venda bem.", encoding="utf-8")

    settings = Settings(
        _env_file=None,
        prompts_dir=prompts_dir,
        database_path=tmp_path / "bot.sqlite3",
        evolution_typing=False,
        evolution_mark_read=False,
        admin_numbers="5511999999999",
    )
    db = Database(settings.database_path)
    await db.connect()
    ai = FakeAI()
    evolution = FakeEvolution()
    tts = FakeTTS()
    handler = ChatHandler(
        settings=settings,
        db=db,
        prompts=PromptManager(settings.prompts_dir, settings.prompt_file),
        ai=ai,
        evolution=evolution,
        tts=tts,
    )
    handler.tts = tts
    yield handler, db, ai, evolution
    await db.close()


def make_message(text, number="5511999999999", jid=None):
    jid = jid or f"{number}@s.whatsapp.net"
    return IncomingMessage(
        event_id=f"teste:{number}",
        message_id="ABC",
        instance="teste",
        jid=jid,
        number=number,
        push_name="Fulano",
        text=text,
        is_group=jid.endswith("@g.us"),
    )


async def test_handle_persists_and_sends(env):
    handler, db, ai, evolution = env
    await handler.handle(make_message("Oi"))

    assert evolution.sent == [("5511999999999@s.whatsapp.net", "resposta para: Oi")]
    assert len(ai.calls) == 1
    assert ai.calls[0]["system"].startswith("Atenda Fulano.")

    history = await db.get_history("5511999999999@s.whatsapp.net", 10, 10_000)
    assert [(h.role, h.content) for h in history] == [
        ("user", "Oi"),
        ("assistant", "resposta para: Oi"),
    ]


async def test_handle_uses_existing_history(env):
    handler, db, ai, _ = env
    await handler.handle(make_message("primeira"))
    await handler.handle(make_message("segunda"))

    second_call = ai.calls[1]
    assert [turn.content for turn in second_call["history"]] == [
        "primeira",
        "resposta para: primeira",
    ]


async def test_reset_command(env):
    handler, db, ai, evolution = env
    await handler.handle(make_message("oi"))
    await handler.handle(make_message("!reset"))

    assert ai.resets == ["5511999999999@s.whatsapp.net"]
    assert await db.get_history("5511999999999@s.whatsapp.net", 10, 10_000) == []
    assert "Memoria" in evolution.sent[-1][1]


async def test_prompt_command_switches_prompt(env):
    handler, db, _, evolution = env
    await handler.handle(make_message("!prompt vendas"))

    assert await db.get_pref("5511999999999@s.whatsapp.net", "prompt") == "vendas"
    assert "vendas" in evolution.sent[-1][1]


async def test_non_admin_cannot_use_commands(env):
    handler, _, ai, _ = env
    await handler.handle(make_message("!reset", number="5511888888888"))

    assert ai.resets == []
    assert len(ai.calls) == 1


async def test_ignore_group_when_configured(env):
    handler, _, ai, evolution = env
    message = make_message("oi", number="12345", jid="12345@g.us")
    await handler.handle(message)

    assert ai.calls == []
    assert evolution.sent == []


async def test_audio_on_sends_ptt_instead_of_text(env):
    handler, db, _, evolution = env
    jid = "5511999999999@s.whatsapp.net"
    await db.set_pref(jid, "audio", "on")

    await handler.handle(make_message("Oi"))

    assert evolution.sent == []
    assert len(evolution.audios) == 1
    sent_jid, encoded = evolution.audios[0]
    assert sent_jid == jid
    assert base64.b64decode(encoded) == b"RIFF-audio-fake"
    assert handler.tts.texts == ["resposta para: Oi"]


async def test_audio_on_with_send_text(env):
    handler, db, _, evolution = env
    jid = "5511999999999@s.whatsapp.net"
    await db.set_pref(jid, "audio", "on")
    handler.settings.audio_send_text = True

    await handler.handle(make_message("Oi"))

    assert len(evolution.audios) == 1
    assert evolution.sent == [(jid, "resposta para: Oi")]


async def test_tts_failure_falls_back_to_text(env):
    handler, db, _, evolution = env
    jid = "5511999999999@s.whatsapp.net"
    await db.set_pref(jid, "audio", "on")
    handler.tts.fail = True

    await handler.handle(make_message("Oi"))

    assert evolution.audios == []
    assert evolution.sent == [(jid, "resposta para: Oi")]


async def test_audio_send_failure_falls_back_to_text(env):
    handler, db, _, evolution = env
    jid = "5511999999999@s.whatsapp.net"
    await db.set_pref(jid, "audio", "on")
    evolution.fail_audio = True

    await handler.handle(make_message("Oi"))

    assert evolution.audios == []
    assert evolution.sent == [(jid, "resposta para: Oi")]


async def test_audio_command_toggles_preference(env):
    handler, db, _, evolution = env
    jid = "5511999999999@s.whatsapp.net"

    await handler.handle(make_message("!audio on"))
    assert await db.get_pref(jid, "audio") == "on"
    assert "ativadas" in evolution.sent[-1][1]

    await handler.handle(make_message("!audio off"))
    assert await db.get_pref(jid, "audio") == "off"
    assert "desativadas" in evolution.sent[-1][1]


async def test_audio_test_command_sends_ptt(env):
    handler, _, ai, evolution = env

    await handler.handle(make_message("!audio test teste de voz"))

    assert ai.calls == []
    assert len(evolution.audios) == 1
    assert handler.tts.texts == ["teste de voz"]
