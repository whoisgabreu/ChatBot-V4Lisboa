from __future__ import annotations

import logging
import uuid
from typing import Any

from app.models import IncomingMessage, MediaRef

logger = logging.getLogger(__name__)

MESSAGE_EVENTS = {"messages.upsert", "MESSAGES_UPSERT"}

_UNWRAP_KEYS = (
    "ephemeralMessage",
    "viewOnceMessage",
    "viewOnceMessageV2",
    "viewOnceMessageV2Extension",
    "documentWithCaptionMessage",
    "editedMessage",
)

_TEXT_KEYS = (
    "conversation",
    "extendedTextMessage",
    "imageMessage",
    "videoMessage",
    "documentMessage",
    "buttonsResponseMessage",
    "listResponseMessage",
    "templateButtonReplyMessage",
)

_IGNORED_SUFFIXES = ("@broadcast", "@newsletter")


def _unwrap(message: dict[str, Any]) -> dict[str, Any]:
    current = message
    for _ in range(5):
        for key in _UNWRAP_KEYS:
            nested = current.get(key)
            if isinstance(nested, dict) and isinstance(nested.get("message"), dict):
                current = nested["message"]
                break
        else:
            return current
    return current


def _extract_text(message: dict[str, Any]) -> str:
    if isinstance(message.get("conversation"), str):
        return message["conversation"].strip()

    node = message.get("extendedTextMessage")
    if isinstance(node, dict) and isinstance(node.get("text"), str):
        return node["text"].strip()

    for key in ("imageMessage", "videoMessage", "documentMessage"):
        node = message.get(key)
        if isinstance(node, dict) and isinstance(node.get("caption"), str):
            return node["caption"].strip()

    node = message.get("buttonsResponseMessage")
    if isinstance(node, dict):
        value = node.get("selectedDisplayText") or node.get("selectedButtonId")
        if isinstance(value, str):
            return value.strip()

    node = message.get("listResponseMessage")
    if isinstance(node, dict):
        value = node.get("title")
        if not value and isinstance(node.get("singleSelectReply"), dict):
            value = node["singleSelectReply"].get("selectedRowId")
        if isinstance(value, str):
            return value.strip()

    node = message.get("templateButtonReplyMessage")
    if isinstance(node, dict) and isinstance(node.get("selectedDisplayText"), str):
        return node["selectedDisplayText"].strip()

    node = message.get("interactiveResponseMessage")
    if isinstance(node, dict):
        body = node.get("body")
        if isinstance(body, dict) and isinstance(body.get("text"), str):
            return body["text"].strip()

    return ""


def _base64_from(node: dict[str, Any], data: dict[str, Any]) -> str | None:
    for container in (node, data, data.get("message") or {}):
        value = container.get("base64") if isinstance(container, dict) else None
        if isinstance(value, str) and value:
            return value
    return None


def _extract_media(
    message: dict[str, Any], data: dict[str, Any]
) -> list[MediaRef]:
    mapping = {
        "imageMessage": "image",
        "audioMessage": "audio",
        "videoMessage": "video",
        "documentMessage": "document",
        "stickerMessage": "image",
    }
    media: list[MediaRef] = []
    for key, kind in mapping.items():
        node = message.get(key)
        if not isinstance(node, dict):
            continue
        mime = node.get("mimetype") or node.get("mimeType") or ""
        filename = node.get("fileName") or f"{kind}"
        media.append(
            MediaRef(
                kind=kind,
                mime=mime,
                filename=filename,
                base64_data=_base64_from(node, data),
                raw_message=data,
            )
        )
    return media


def parse_webhook(
    payload: dict[str, Any], instance_default: str = ""
) -> list[IncomingMessage]:
    event = payload.get("event") or payload.get("type") or ""
    if event not in MESSAGE_EVENTS:
        logger.debug("evento ignorado: %s", event)
        return []

    data = payload.get("data")
    items = data if isinstance(data, list) else [data]
    instance = payload.get("instance") or instance_default or ""
    messages: list[IncomingMessage] = []

    for item in items:
        if not isinstance(item, dict):
            continue
        key = item.get("key") or {}
        jid = key.get("remoteJid") or item.get("remoteJid") or ""
        if not jid or jid.endswith(_IGNORED_SUFFIXES) or jid == "status@broadcast":
            continue

        message = item.get("message")
        if not isinstance(message, dict) or not message:
            continue
        message = _unwrap(message)

        message_id = key.get("id") or item.get("id") or f"local-{uuid.uuid4()}"
        is_group = jid.endswith("@g.us")
        number = jid.split("@", 1)[0] if not is_group else jid

        messages.append(
            IncomingMessage(
                event_id=f"{instance}:{message_id}",
                message_id=message_id,
                instance=instance,
                jid=jid,
                number=number,
                push_name=str(item.get("pushName") or "").strip(),
                text=_extract_text(message),
                is_group=is_group,
                from_me=bool(key.get("fromMe")),
                media=_extract_media(message, item),
            )
        )

    return messages
