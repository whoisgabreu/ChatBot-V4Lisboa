from __future__ import annotations

import asyncio
import io
import logging
import re
import wave
from typing import Any

from app.config import Settings

logger = logging.getLogger(__name__)

LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
MARKDOWN_RE = re.compile(r"[*_~`#>|]+")
EMOJI_RE = re.compile(
    "[\U0001f000-\U0001faff\U00002600-\U000027bf"
    "\U0001f1e6-\U0001f1ff\u2b00-\u2bff\ufe0f]"
)
SPACE_RE = re.compile(r"\s+")


class TTSError(RuntimeError):
    pass


class PiperTTS:
    """Sintese local com Piper, mantendo a voz carregada em memoria."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.status = "disabled" if not settings.tts_enabled else "idle"
        self.error: str | None = None
        self._voice: Any = None
        self._load_lock = asyncio.Lock()
        self._synth_lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return self.settings.tts_enabled

    async def warmup(self) -> None:
        if not self.enabled:
            return
        try:
            await self._ensure_voice()
            self.status = "ready"
            logger.info("TTS pronto (voz: %s)", self.settings.tts_voice_path)
        except Exception as exc:
            self.status = "error"
            self.error = str(exc)
            logger.exception("falha ao carregar o TTS: %s", exc)

    async def _ensure_voice(self) -> None:
        if self._voice is not None:
            return
        async with self._load_lock:
            if self._voice is not None:
                return
            path = self.settings.tts_voice_path
            if not path.is_file():
                raise TTSError(f"modelo de voz nao encontrado: {path}")

            self.status = "loading"

            def load() -> Any:
                from piper import PiperVoice

                return PiperVoice.load(str(path))

            self._voice = await asyncio.to_thread(load)
            self.status = "ready"

    async def synthesize(self, text: str) -> bytes:
        if not self.enabled:
            raise TTSError("TTS desabilitado")
        clean = self.clean_text(text, self.settings.tts_max_chars)
        if not clean:
            raise TTSError("nenhum texto falavel apos a limpeza")

        await self._ensure_voice()
        async with self._synth_lock:
            return await asyncio.to_thread(self._synthesize_sync, clean)

    def _synthesize_sync(self, text: str) -> bytes:
        from piper import SynthesisConfig

        config = SynthesisConfig(
            speaker_id=self.settings.tts_speaker_id,
            length_scale=self.settings.tts_length_scale,
            noise_scale=self.settings.tts_noise_scale,
            noise_w_scale=self.settings.tts_noise_w_scale,
            volume=self.settings.tts_volume,
        )
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            self._voice.synthesize_wav(text, wav_file, syn_config=config)

        data = buffer.getvalue()
        if not data:
            raise TTSError("Piper retornou audio vazio")
        return data

    @staticmethod
    def clean_text(text: str, max_chars: int) -> str:
        cleaned = LINK_RE.sub(r"\1", text)
        cleaned = URL_RE.sub(" ", cleaned)
        cleaned = MARKDOWN_RE.sub(" ", cleaned)
        cleaned = EMOJI_RE.sub("", cleaned)
        cleaned = SPACE_RE.sub(" ", cleaned).strip()

        if max_chars > 0 and len(cleaned) > max_chars:
            window = cleaned[:max_chars]
            cut = max(
                window.rfind("."),
                window.rfind("!"),
                window.rfind("?"),
                window.rfind("\n"),
            )
            if cut < max_chars // 2:
                cut = max_chars
            else:
                cut += 1
            cleaned = window[:cut].rstrip(" ,;:-\n")

        return cleaned.strip()
