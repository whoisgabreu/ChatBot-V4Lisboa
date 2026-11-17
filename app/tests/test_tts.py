import pytest

from app.config import Settings
from app.tts import PiperTTS, TTSError


class FakeVoice:
    def __init__(self):
        self.texts = []

    def synthesize_wav(self, text, wav_file, syn_config=None):
        self.texts.append(text)
        wav_file.setframerate(22050)
        wav_file.setsampwidth(2)
        wav_file.setnchannels(1)
        wav_file.writeframes(b"\x00\x00" * 200)


def make_tts(tmp_path, enabled=True):
    settings = Settings(
        _env_file=None,
        tts_enabled=enabled,
        tts_voice_path=tmp_path / "voz.onnx",
        tts_max_chars=50,
    )
    return PiperTTS(settings)


def test_clean_text_removes_markdown_links_and_emojis():
    cleaned = PiperTTS.clean_text(
        "**Ola** _mundo_ 😀 https://exemplo.com [site](https://x.com)", 500
    )
    assert "Ola" in cleaned
    assert "mundo" in cleaned
    assert "site" in cleaned
    assert "*" not in cleaned
    assert "_" not in cleaned
    assert "http" not in cleaned
    assert "😀" not in cleaned


def test_clean_text_truncates_on_sentence_boundary():
    text = "Primeira frase completa. Segunda frase que sera cortada no meio."
    cleaned = PiperTTS.clean_text(text, 25)
    assert cleaned == "Primeira frase completa."


def test_clean_text_keeps_accents():
    assert PiperTTS.clean_text("Ola, coracao e acao", 100) == "Ola, coracao e acao"
    assert PiperTTS.clean_text("Olá, coração e ação", 100) == "Olá, coração e ação"


async def test_synthesize_returns_wav_bytes(tmp_path):
    tts = make_tts(tmp_path)
    voice = FakeVoice()
    tts._voice = voice

    audio = await tts.synthesize("**Oi** para voce")

    assert audio.startswith(b"RIFF")
    assert b"WAVE" in audio
    assert voice.texts == ["Oi para voce"]


async def test_synthesize_disabled_raises(tmp_path):
    tts = make_tts(tmp_path, enabled=False)
    with pytest.raises(TTSError, match="desabilitado"):
        await tts.synthesize("oi")


async def test_missing_model_raises(tmp_path):
    tts = make_tts(tmp_path)
    with pytest.raises(TTSError, match="nao encontrado"):
        await tts.synthesize("oi")
