from __future__ import annotations

import asyncio
import hmac
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.ai.factory import build_provider
from app.config import Settings, get_settings
from app.database import Database
from app.evolution import EvolutionClient
from app.handler import ChatHandler
from app.parser import parse_webhook
from app.prompts import PromptManager
from app.queue import MessageQueue
from app.tts import PiperTTS

logger = logging.getLogger(__name__)


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )


async def _cleanup_loop(db: Database, settings: Settings) -> None:
    interval = max(60, settings.dedup_ttl_seconds // 2)
    while True:
        try:
            await asyncio.sleep(interval)
            await db.cleanup_events(settings.dedup_ttl_seconds)
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("erro na limpeza periodica")


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        setup_logging(app_settings.log_level)
        logger.info("iniciando %s", app_settings.app_name)

        db = Database(app_settings.database_path)
        await db.connect()

        prompts = PromptManager(app_settings.prompts_dir, app_settings.prompt_file)
        ai = build_provider(app_settings, db)
        evolution = EvolutionClient(app_settings)
        tts = PiperTTS(app_settings)
        if app_settings.tts_enabled:
            await tts.warmup()
        handler = ChatHandler(
            settings=app_settings,
            db=db,
            prompts=prompts,
            ai=ai,
            evolution=evolution,
            tts=tts,
        )
        queue = MessageQueue(handler, app_settings)
        await queue.start()

        app.state.settings = app_settings
        app.state.db = db
        app.state.prompts = prompts
        app.state.ai = ai
        app.state.evolution = evolution
        app.state.tts = tts
        app.state.handler = handler
        app.state.queue = queue
        app.state.started_at = time.time()

        cleanup_task = asyncio.create_task(_cleanup_loop(db, app_settings))
        try:
            yield
        finally:
            cleanup_task.cancel()
            await asyncio.gather(cleanup_task, return_exceptions=True)
            await queue.stop()
            await ai.close()
            await evolution.close()
            await db.close()
            logger.info("encerrado")

    app = FastAPI(title=app_settings.app_name, version="1.0.0", lifespan=lifespan)

    @app.get("/")
    async def index() -> dict[str, object]:
        return {
            "name": app_settings.app_name,
            "provider": app_settings.ai_provider,
            "webhook": "/webhook/evolution",
        }

    @app.get("/health")
    async def health(request: Request) -> dict[str, object]:
        state = request.app.state
        return {
            "status": "ok",
            "provider": state.ai.name,
            "tts": state.tts.status,
            "queue_size": state.queue.size,
            "uptime": int(time.time() - state.started_at),
        }

    def check_secret(request: Request, secret: str | None) -> None:
        expected = app_settings.evolution_webhook_secret
        if not expected:
            return
        header = request.headers.get(app_settings.evolution_webhook_header, "")
        provided = header or secret or ""
        if not hmac.compare_digest(provided.encode(), expected.encode()):
            raise HTTPException(status_code=401, detail="invalid webhook secret")

    async def process(
        request: Request, secret: str | None, instance: str | None = None
    ) -> JSONResponse:
        check_secret(request, secret)
        try:
            payload = await request.json()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid json") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="invalid payload")

        state = request.app.state
        try:
            messages = parse_webhook(
                payload, instance or app_settings.evolution_instance
            )
        except Exception:
            logger.exception("falha ao interpretar webhook")
            return JSONResponse({"ok": False, "accepted": 0}, status_code=200)

        accepted = 0
        for message in messages:
            if app_settings.ignore_from_me and message.from_me:
                continue
            if not await state.db.is_new_event(message.event_id):
                continue
            if await state.queue.put(message):
                accepted += 1

        return JSONResponse({"ok": True, "accepted": accepted})

    @app.post("/webhook/evolution")
    async def webhook(
        request: Request, secret: str | None = Query(default=None)
    ) -> JSONResponse:
        return await process(request, secret)

    @app.post("/webhook/evolution/{instance}")
    async def webhook_instance(
        instance: str, request: Request, secret: str | None = Query(default=None)
    ) -> JSONResponse:
        return await process(request, secret, instance)

    return app


app = create_app()
