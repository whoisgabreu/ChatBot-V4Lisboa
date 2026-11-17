from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


async def transcribe_audio(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    api_key: str,
    model: str,
    data: bytes,
    filename: str,
    mime: str,
    timeout: float = 60.0,
) -> str | None:
    if not data or not base_url:
        return None

    url = base_url.rstrip("/") + "/audio/transcriptions"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    files = {"file": (filename or "audio.ogg", data, mime or "audio/ogg")}
    payload = {"model": model}

    try:
        response = await client.post(
            url, headers=headers, data=payload, files=files, timeout=timeout
        )
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("falha ao transcrever audio: %s", exc)
        return None

    text = body.get("text") if isinstance(body, dict) else None
    return text.strip() if isinstance(text, str) and text.strip() else None
