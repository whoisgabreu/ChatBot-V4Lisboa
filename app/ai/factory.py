from __future__ import annotations

from app.ai.base import AIProvider
from app.ai.openai_provider import OpenAIProvider
from app.ai.opencode_provider import OpenCodeProvider
from app.config import Settings
from app.database import Database


def build_provider(settings: Settings, db: Database) -> AIProvider:
    if settings.ai_provider == "opencode":
        return OpenCodeProvider(
            db=db,
            base_url=settings.opencode_base_url,
            username=settings.opencode_username,
            password=settings.opencode_password,
            provider_id=settings.opencode_provider_id,
            model_id=settings.opencode_model_id,
            agent=settings.opencode_agent,
            timeout=max(settings.ai_timeout, 90.0),
            transcribe_enabled=settings.transcribe_enabled,
            transcribe_base_url=settings.transcribe_base_url,
            transcribe_api_key=settings.transcribe_api_key,
            transcribe_model=settings.transcribe_model,
        )

    return OpenAIProvider(
        base_url=settings.ai_base_url,
        api_key=settings.ai_api_key,
        model=settings.ai_model,
        temperature=settings.ai_temperature,
        max_tokens=settings.ai_max_tokens,
        timeout=settings.ai_timeout,
        transcribe_enabled=settings.transcribe_enabled,
        transcribe_base_url=settings.transcribe_base_url,
        transcribe_api_key=settings.transcribe_api_key,
        transcribe_model=settings.transcribe_model,
    )
