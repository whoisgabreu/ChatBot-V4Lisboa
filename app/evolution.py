from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

from app.config import Settings
from app.models import MediaRef

logger = logging.getLogger(__name__)


class EvolutionError(RuntimeError):
    pass


class EvolutionClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.evolution_base_url.rstrip("/"),
            timeout=httpx.Timeout(60.0, connect=10.0),
        )

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.settings.evolution_api_key:
            headers["apikey"] = self.settings.evolution_api_key
        return headers

    def _instance(self) -> str:
        if not self.settings.evolution_instance:
            raise EvolutionError("EVOLUTION_INSTANCE nao configurado")
        return self.settings.evolution_instance

    async def send_text(self, jid: str, text: str) -> None:
        url = f"/message/sendText/{self._instance()}"
        body = {"number": jid, "text": text, "linkPreview": False}
        response = await self._client.post(url, headers=self._headers(), json=body)
        if response.status_code >= 400:
            raise EvolutionError(
                f"sendText falhou ({response.status_code}): {response.text[:300]}"
            )

    async def send_whatsapp_audio(
        self,
        jid: str,
        audio_base64: str,
        *,
        delay: int | None = None,
        encoding: bool | None = None,
    ) -> None:
        audio = audio_base64.strip()
        if audio.startswith("data:"):
            audio = audio.split(",", 1)[-1]
        if not audio:
            raise EvolutionError("audio base64 vazio")

        audio_delay = self.settings.evolution_audio_delay if delay is None else delay
        audio_delay = max(0, min(int(audio_delay), 110_000))
        audio_encoding = (
            self.settings.evolution_audio_encoding if encoding is None else encoding
        )

        url = f"/message/sendWhatsAppAudio/{self._instance()}"
        body = {
            "number": jid,
            "audio": audio,
            "delay": audio_delay,
            "encoding": audio_encoding,
        }
        response = await self._client.post(url, headers=self._headers(), json=body)
        if response.status_code >= 400:
            raise EvolutionError(
                f"sendWhatsAppAudio falhou ({response.status_code}): {response.text[:300]}"
            )

    async def send_presence(self, jid: str, presence: str = "composing") -> None:
        url = f"/chat/sendPresence/{self._instance()}"
        body = {"number": jid, "presence": presence}
        try:
            response = await self._client.post(url, headers=self._headers(), json=body)
            if response.status_code >= 400:
                logger.debug("sendPresence retornou %s", response.status_code)
        except httpx.HTTPError as exc:
            logger.debug("sendPresence falhou: %s", exc)

    async def mark_read(self, jid: str, message_id: str) -> None:
        url = f"/chat/markMessageAsRead/{self._instance()}"
        body = {"readMessages": [{"remoteJid": jid, "fromMe": False, "id": message_id}]}
        try:
            response = await self._client.post(url, headers=self._headers(), json=body)
            if response.status_code >= 400:
                logger.debug("markMessageAsRead retornou %s", response.status_code)
        except httpx.HTTPError as exc:
            logger.debug("markMessageAsRead falhou: %s", exc)

    async def resolve_media(self, media: MediaRef) -> tuple[bytes, str] | None:
        if media.base64_data:
            try:
                raw = media.base64_data
                if raw.startswith("data:"):
                    raw = raw.split(",", 1)[1]
                return base64.b64decode(raw), media.mime
            except (ValueError, IndexError) as exc:
                logger.warning("base64 de midia invalido: %s", exc)
                return None

        if not self.settings.evolution_download_media:
            return None

        url = f"/chat/getBase64FromMediaMessage/{self._instance()}"
        body = {"message": media.raw_message, "convertToMp4": False}
        try:
            response = await self._client.post(url, headers=self._headers(), json=body)
            response.raise_for_status()
            data: Any = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("falha ao baixar midia: %s", exc)
            return None

        if not isinstance(data, dict):
            return None
        encoded = data.get("base64") or data.get("media")
        mime = data.get("mimetype") or media.mime
        if not isinstance(encoded, str) or not encoded:
            return None
        try:
            return base64.b64decode(encoded), mime
        except ValueError:
            return None

    async def close(self) -> None:
        await self._client.aclose()
