from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

from app.ai.base import AIError, AIProvider, Attachment, ChatTurn
from app.ai.transcription import transcribe_audio

logger = logging.getLogger(__name__)


class OpenAIProvider(AIProvider):
    name = "openai"
    supports_vision = True

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float = 0.4,
        max_tokens: int = 500,
        timeout: float = 60.0,
        transcribe_enabled: bool = True,
        transcribe_base_url: str = "",
        transcribe_api_key: str = "",
        transcribe_model: str = "whisper-1",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.transcribe_enabled = transcribe_enabled
        self.transcribe_base_url = (transcribe_base_url or base_url).rstrip("/")
        self.transcribe_api_key = transcribe_api_key or api_key
        self.transcribe_model = transcribe_model
        self._client = httpx.AsyncClient(timeout=timeout)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    @staticmethod
    def _image_content(attachment: Attachment) -> dict[str, Any]:
        encoded = base64.b64encode(attachment.data).decode("ascii")
        mime = attachment.mime or "image/jpeg"
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{encoded}"},
        }

    def _user_content(
        self, text: str, attachments: list[Attachment]
    ) -> str | list[dict[str, Any]]:
        images = [a for a in attachments if a.kind == "image" and a.data]
        if not images:
            return text
        content: list[dict[str, Any]] = [{"type": "text", "text": text}]
        content.extend(self._image_content(image) for image in images)
        return content

    def _build_messages(
        self,
        *,
        system: str,
        history: list[ChatTurn],
        user_text: str,
        attachments: list[Attachment],
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for turn in history:
            messages.append({"role": turn.role, "content": turn.content})
        messages.append(
            {"role": "user", "content": self._user_content(user_text, attachments)}
        )
        return messages

    async def _post_completion(self, payload: dict[str, Any]) -> httpx.Response:
        url = f"{self.base_url}/chat/completions"
        return await self._client.post(url, headers=self._headers(), json=payload)

    async def reply(
        self,
        *,
        jid: str,
        system: str,
        history: list[ChatTurn],
        user_text: str,
        attachments: list[Attachment] | None = None,
    ) -> str:
        attachments = attachments or []
        messages = self._build_messages(
            system=system,
            history=history,
            user_text=user_text,
            attachments=attachments,
        )
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if self.max_tokens:
            payload["max_tokens"] = self.max_tokens

        try:
            response = await self._post_completion(payload)
            if response.status_code == 400:
                logger.warning("requisicao rejeitada (400), tentando payload minimo")
                fallback = {"model": self.model, "messages": messages}
                response = await self._post_completion(fallback)
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            detail = exc.response.text[:500]
            retryable = status >= 500 or status == 429
            raise AIError(
                f"provedor respondeu {status}: {detail}", retryable=retryable
            ) from exc
        except httpx.HTTPError as exc:
            raise AIError(f"falha de conexao com o provedor: {exc}") from exc
        except ValueError as exc:
            raise AIError("resposta invalida do provedor") from exc

        choices = body.get("choices") if isinstance(body, dict) else None
        if not choices:
            raise AIError("provedor retornou resposta sem choices")

        content = choices[0].get("message", {}).get("content")
        text = self._flatten_content(content)
        if not text:
            raise AIError("provedor retornou resposta vazia")
        return text.strip()

    @staticmethod
    def _flatten_content(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = [
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            ]
            return "".join(parts)
        return ""

    async def transcribe(self, attachment: Attachment) -> str | None:
        if not self.transcribe_enabled or not attachment.data:
            return None
        return await transcribe_audio(
            self._client,
            base_url=self.transcribe_base_url,
            api_key=self.transcribe_api_key,
            model=self.transcribe_model,
            data=attachment.data,
            filename=attachment.filename,
            mime=attachment.mime,
        )

    async def close(self) -> None:
        await self._client.aclose()
