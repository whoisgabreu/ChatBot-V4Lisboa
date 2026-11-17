from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque

from app.config import Settings
from app.handler import ChatHandler
from app.models import IncomingMessage

logger = logging.getLogger(__name__)


class RateLimiter:
    """Limite simples por contato (janela deslizante de 60s)."""

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def wait(self, key: str) -> None:
        if self.per_minute <= 0:
            return
        async with self._locks[key]:
            while True:
                now = time.monotonic()
                bucket = self._events[key]
                while bucket and now - bucket[0] > 60:
                    bucket.popleft()
                if len(bucket) < self.per_minute:
                    bucket.append(now)
                    return
                delay = 60 - (now - bucket[0])
                if delay <= 0:
                    continue
                logger.debug("rate limit para %s, aguardando %.1fs", key, delay)
                await asyncio.sleep(delay)


class MessageQueue:
    def __init__(self, handler: ChatHandler, settings: Settings) -> None:
        self.handler = handler
        self.settings = settings
        self._queue: asyncio.Queue[IncomingMessage] = asyncio.Queue(
            maxsize=settings.queue_max_size
        )
        self._workers: list[asyncio.Task[None]] = []
        self._semaphore = asyncio.Semaphore(max(1, settings.max_concurrent))
        self._limiter = RateLimiter(settings.rate_limit_per_minute)
        self._contact_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._running = False

    @property
    def size(self) -> int:
        return self._queue.qsize()

    async def start(self) -> None:
        self._running = True
        workers = max(1, self.settings.max_concurrent)
        self._workers = [
            asyncio.create_task(self._worker(index), name=f"worker-{index}")
            for index in range(workers)
        ]
        logger.info("fila iniciada com %s workers", workers)

    async def stop(self) -> None:
        self._running = False
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers = []

    async def put(self, message: IncomingMessage) -> bool:
        try:
            self._queue.put_nowait(message)
            return True
        except asyncio.QueueFull:
            logger.warning("fila cheia, descartando mensagem de %s", message.jid)
            return False

    async def _worker(self, index: int) -> None:
        while self._running:
            try:
                message = await self._queue.get()
            except asyncio.CancelledError:
                break
            try:
                async with self._semaphore, self._contact_locks[message.jid]:
                    await self._limiter.wait(message.jid)
                    await self.handler.handle(message)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("erro ao processar mensagem de %s", message.jid)
            finally:
                self._queue.task_done()
