from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

AttachmentKind = Literal["image", "audio", "video", "document"]


@dataclass(slots=True)
class Attachment:
    kind: AttachmentKind
    mime: str
    data: bytes
    filename: str = "file"
    caption: str = ""


@dataclass(slots=True)
class ChatTurn:
    role: str
    content: str


class AIError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class AIProvider(ABC):
    name: str = "base"
    supports_vision: bool = False

    @abstractmethod
    async def reply(
        self,
        *,
        jid: str,
        system: str,
        history: list[ChatTurn],
        user_text: str,
        attachments: list[Attachment] | None = None,
    ) -> str:
        ...

    async def reset(self, jid: str) -> None:
        return None

    async def close(self) -> None:
        return None

    async def transcribe(self, attachment: Attachment) -> str | None:
        return None
