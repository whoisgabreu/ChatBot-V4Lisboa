from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class MediaRef:
    kind: str
    mime: str = ""
    filename: str = ""
    base64_data: str | None = None
    raw_message: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class IncomingMessage:
    event_id: str
    message_id: str
    instance: str
    jid: str
    number: str
    push_name: str
    text: str
    is_group: bool
    from_me: bool = False
    media: list[MediaRef] = field(default_factory=list)
