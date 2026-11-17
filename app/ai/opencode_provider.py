from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

from app.ai.base import AIError, AIProvider, Attachment, ChatTurn
from app.ai.sanitize import has_tool_markup, strip_tool_markup
from app.ai.transcription import transcribe_audio
from app.database import Database

logger = logging.getLogger(__name__)

FALLBACK_REPLY = (
    "Nao consegui concluir essa pesquisa agora. Pode tentar novamente em instantes?"
)
CORRECTIVE_INSTRUCTION = (
    "\n\nSua resposta anterior tentou usar uma ferramenta indisponivel e veio com "
    "marcacoes internas. Nao use bash, terminal, arquivos ou ferramentas desabilitadas. "
    "Se precisar de dados atuais, use websearch. Responda apenas o texto final em "
    "portugues, sem XML, JSON de tool call ou DSML."
)


class OpenCodeProvider(AIProvider):
    """Usa o servidor HTTP do opencode (`opencode serve`) como motor de IA.

    Cada contato do WhatsApp ganha uma sessao propria no opencode, o que mantem
    o contexto no servidor e acelera as respostas seguintes. As ferramentas sao
    controladas pelo agente configurado em `opencode.json`.
    """

    name = "opencode"
    supports_vision = True

    def __init__(
        self,
        *,
        db: Database,
        base_url: str,
        username: str = "opencode",
        password: str = "",
        provider_id: str = "opencode-go",
        model_id: str = "deepseek-v4.1-flash",
        agent: str = "whatsapp",
        timeout: float = 90.0,
        transcribe_enabled: bool = True,
        transcribe_base_url: str = "",
        transcribe_api_key: str = "",
        transcribe_model: str = "whisper-1",
    ) -> None:
        self.db = db
        self.base_url = base_url.rstrip("/")
        self.provider_id = provider_id
        self.model_id = model_id
        self.agent = agent
        self.transcribe_enabled = transcribe_enabled
        self.transcribe_base_url = transcribe_base_url.rstrip("/")
        self.transcribe_api_key = transcribe_api_key
        self.transcribe_model = transcribe_model

        auth = (username, password) if password else None
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout, auth=auth)

    # -- sessoes -----------------------------------------------------------
    async def _create_session(self, jid: str) -> str:
        response = await self._client.post("/session", json={"title": f"wa:{jid}"})
        response.raise_for_status()
        session_id = response.json().get("id")
        if not session_id:
            raise AIError("opencode nao retornou id de sessao")
        await self.db.set_session_id(jid, session_id)
        return session_id

    async def _ensure_session(self, jid: str) -> str:
        session_id = await self.db.get_session_id(jid)
        if session_id:
            return session_id
        return await self._create_session(jid)

    async def reset(self, jid: str) -> None:
        session_id = await self.db.get_session_id(jid)
        if session_id:
            try:
                await self._client.delete(f"/session/{session_id}")
            except httpx.HTTPError as exc:
                logger.warning("nao foi possivel apagar sessao opencode: %s", exc)
        await self.db.set_session_id(jid, None)

    # -- requisicao --------------------------------------------------------
    def _parts(
        self, user_text: str, images: list[Attachment]
    ) -> list[dict[str, Any]]:
        parts: list[dict[str, Any]] = [
            {"type": "text", "text": user_text or "Mensagem recebida."}
        ]
        for image in images:
            encoded = base64.b64encode(image.data).decode("ascii")
            parts.append(
                {
                    "type": "file",
                    "mime": image.mime or "image/jpeg",
                    "filename": image.filename or "image.jpg",
                    "url": f"data:{image.mime or 'image/jpeg'};base64,{encoded}",
                }
            )
        return parts

    def _body(
        self, *, system: str, parts: list[dict[str, Any]]
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": {"providerID": self.provider_id, "modelID": self.model_id},
            "system": system,
            "parts": parts,
        }
        if self.agent:
            body["agent"] = self.agent
        return body

    async def _send(self, session_id: str, body: dict[str, Any]) -> dict[str, Any]:
        response = await self._client.post(f"/session/{session_id}/message", json=body)
        if response.status_code == 404:
            raise _SessionGone()
        if response.status_code >= 400:
            status = response.status_code
            raise AIError(
                f"opencode respondeu {status}: {response.text[:500]}",
                retryable=status >= 500 or status == 429,
            )
        try:
            return response.json()
        except ValueError as exc:
            raise AIError("resposta invalida do opencode") from exc

    @staticmethod
    def _extract_text(body: dict[str, Any]) -> str:
        info = body.get("info") or {}
        error = info.get("error")
        if isinstance(error, dict):
            data = error.get("data") if isinstance(error.get("data"), dict) else {}
            message = data.get("message") or error.get("name") or "erro desconhecido"
            status = data.get("statusCode")
            retryable = not isinstance(status, int) or status >= 500 or status == 429
            raise AIError(f"opencode: {message}", retryable=retryable)
        if error:
            raise AIError(f"opencode: {error}")

        texts = [
            part.get("text", "")
            for part in body.get("parts", [])
            if isinstance(part, dict)
            and part.get("type") == "text"
            and not part.get("ignored")
        ]
        return "".join(texts).strip()

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
        images = [a for a in attachments if a.kind == "image" and a.data]
        parts = self._parts(user_text, images)

        session_id = await self._ensure_session(jid)
        for attempt in range(2):
            try:
                body = await self._send(
                    session_id, self._body(system=system, parts=parts)
                )
                text = self._extract_text(body)

                if not text and images:
                    logger.warning("opencode nao respondeu com imagem, tentando sem anexo")
                    fallback_parts = self._parts(
                        user_text + "\n\n[O usuario enviou uma imagem que nao pode ser anexada.]",
                        [],
                    )
                    body = await self._send(
                        session_id,
                        self._body(system=system, parts=fallback_parts),
                    )
                    text = self._extract_text(body)

                if not text:
                    raise AIError("opencode retornou resposta vazia")

                clean = strip_tool_markup(text)
                if clean:
                    return clean

                if not has_tool_markup(text):
                    return text

                logger.warning("resposta apenas com markup de ferramenta; pedindo correcao")
                corrective = await self._send(
                    session_id,
                    self._body(
                        system=system + CORRECTIVE_INSTRUCTION,
                        parts=[
                            {
                                "type": "text",
                                "text": (
                                    "Refaca a resposta sem mostrar marcacoes de ferramenta."
                                ),
                            }
                        ],
                    ),
                )
                corrected = strip_tool_markup(self._extract_text(corrective))
                if corrected:
                    return corrected
                return FALLBACK_REPLY

            except _SessionGone:
                if attempt == 0:
                    logger.info("sessao opencode expirou, criando nova")
                    session_id = await self._create_session(jid)
                    continue
                raise AIError("sessao opencode indisponivel") from None
            except httpx.HTTPError as exc:
                raise AIError(f"falha de conexao com opencode: {exc}") from exc
        raise AIError("opencode nao respondeu")

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


class _SessionGone(Exception):
    pass
