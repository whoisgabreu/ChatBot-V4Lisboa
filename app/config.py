from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "whatsapp-ai-bot"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"

    # Evolution API
    evolution_base_url: str = "http://localhost:8080"
    evolution_api_key: str = ""
    evolution_instance: str = ""
    evolution_webhook_secret: str = ""
    evolution_webhook_header: str = "x-webhook-secret"
    evolution_download_media: bool = True
    evolution_typing: bool = True
    evolution_mark_read: bool = True

    # Provedor de IA: openai (qualquer API compativel) ou opencode (opencode serve)
    ai_provider: Literal["openai", "opencode"] = "openai"
    ai_base_url: str = "https://api.openai.com/v1"
    ai_api_key: str = ""
    ai_model: str = "gpt-4o-mini"
    ai_temperature: float = 0.4
    ai_max_tokens: int = 500
    ai_timeout: float = 60.0

    # opencode serve
    opencode_base_url: str = "http://127.0.0.1:4097"
    opencode_username: str = "opencode"
    opencode_password: str = ""
    opencode_provider_id: str = "opencode-go"
    opencode_model_id: str = "deepseek-v4.1-flash"
    opencode_agent: str = "whatsapp"

    # System prompts
    prompts_dir: Path = Path("prompts")
    prompt_file: str = "system.md"
    system_extra: str = ""

    # Memoria
    database_path: Path = Path("data/bot.sqlite3")
    history_limit: int = 20
    history_max_chars: int = 12_000

    # Comportamento
    ignore_groups: bool = True
    ignore_from_me: bool = True
    allowed_numbers: str = ""
    admin_numbers: str = ""
    reply_prefix: str = ""
    max_reply_chars: int = 3_500
    max_retries: int = 2
    audio_reply_default: bool = False
    audio_send_text: bool = False

    # Fila / rate limit
    max_concurrent: int = 4
    rate_limit_per_minute: int = 20
    queue_max_size: int = 1_000
    dedup_ttl_seconds: int = 600

    # Midia
    transcribe_enabled: bool = True
    transcribe_base_url: str = ""
    transcribe_api_key: str = ""
    transcribe_model: str = "whisper-1"
    media_max_bytes: int = 15 * 1024 * 1024

    # TTS (Piper) e respostas em audio (Push-To-Talk)
    tts_enabled: bool = False
    tts_voice_path: Path = Path("voiceGeneration/pt_BR-jeff-medium.onnx")
    tts_speaker_id: int | None = None
    tts_length_scale: float = 1.0
    tts_noise_scale: float = 0.667
    tts_noise_w_scale: float = 0.8
    tts_volume: float = 1.0
    tts_max_chars: int = 900
    evolution_audio_delay: int = 1_200
    evolution_audio_encoding: bool = True

    #------------------------------------------------------------------------
    @property
    def allowed_numbers_set(self) -> set[str]:
        return {normalize_number(n) for n in split_csv(self.allowed_numbers)}

    @property
    def admin_numbers_set(self) -> set[str]:
        return {normalize_number(n) for n in split_csv(self.admin_numbers)}


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def normalize_number(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


@lru_cache
def get_settings() -> Settings:
    return Settings()
