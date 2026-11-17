from __future__ import annotations

import asyncio
import base64
import logging
import time
from datetime import datetime

from app.ai.base import AIError, AIProvider, Attachment, ChatTurn
from app.config import Settings
from app.database import Database
from app.evolution import EvolutionClient
from app.models import IncomingMessage, MediaRef
from app.prompts import PromptManager
from app.tts import PiperTTS, TTSError
from app.utils import split_message

logger = logging.getLogger(__name__)

ERROR_REPLY = "Desculpe, tive um problema para responder agora. Pode tentar de novo em instantes?"
HELP_TEXT = (
    "*Comandos disponiveis*\n"
    "!reset - apaga a memoria da conversa\n"
    "!prompt - mostra o prompt atual e lista os disponiveis\n"
    "!prompt <nome> - troca o system prompt deste contato\n"
    "!audio - mostra o status das respostas em audio\n"
    "!audio on|off - liga/desliga respostas em audio neste contato\n"
    "!audio test <texto> - envia um audio de teste\n"
    "!status - informacoes do bot\n"
    "!id - mostra seu numero/JID\n"
    "!help - esta mensagem"
)
AUDIO_TEST_TEXT = (
    "Teste de audio do chatbot. Se voce esta ouvindo esta mensagem, "
    "o envio de audio esta funcionando."
)


class ChatHandler:
    def __init__(
        self,
        *,
        settings: Settings,
        db: Database,
        prompts: PromptManager,
        ai: AIProvider,
        evolution: EvolutionClient,
        tts: PiperTTS | None = None,
    ) -> None:
        self.settings = settings
        self.db = db
        self.prompts = prompts
        self.ai = ai
        self.evolution = evolution
        self.tts = tts
        self.started_at = time.time()

    # -- entrada -----------------------------------------------------------
    async def handle(self, msg: IncomingMessage) -> None:
        if msg.is_group and self.settings.ignore_groups:
            logger.debug("grupo ignorado: %s", msg.jid)
            return

        allowed = self.settings.allowed_numbers_set
        if allowed and msg.number not in allowed:
            logger.info("numero nao autorizado: %s", msg.number)
            return

        await self.db.upsert_contact(msg.jid, msg.push_name or None)
        text = msg.text.strip()

        if (
            text[:1] in {"/", "!"}
            and self._is_admin(msg.number)
            and await self._handle_command(msg, text)
        ):
            return

        if self.settings.evolution_mark_read:
            await self.evolution.mark_read(msg.jid, msg.message_id)

        user_text, attachments = await self._prepare_media(msg)
        if not user_text and not attachments:
            logger.debug("mensagem sem conteudo processavel de %s", msg.jid)
            return

        system = await self._system_prompt(msg)

        stored = await self.db.get_history(
            msg.jid, self.settings.history_limit, self.settings.history_max_chars
        )
        history = [ChatTurn(role=row.role, content=row.content) for row in stored]

        if self.settings.evolution_typing:
            await self.evolution.send_presence(msg.jid, "composing")

        reply = await self._generate(
            msg=msg, system=system, history=history, user_text=user_text, attachments=attachments
        )

        if self.settings.evolution_typing:
            await self.evolution.send_presence(msg.jid, "paused")

        if reply is None:
            await self._send(msg, ERROR_REPLY)
            return

        await self.db.add_message(msg.jid, "user", user_text)
        await self.db.add_message(msg.jid, "assistant", reply)

        audio_enabled = await self._audio_enabled(msg.jid)
        audio_sent = False
        if audio_enabled:
            audio_sent = await self._send_audio(msg, reply)

        if not audio_sent or self.settings.audio_send_text:
            await self._send(msg, reply)

    # -- geracao -----------------------------------------------------------
    async def _generate(
        self,
        *,
        msg: IncomingMessage,
        system: str,
        history: list[ChatTurn],
        user_text: str,
        attachments: list[Attachment],
    ) -> str | None:
        attempts = max(0, self.settings.max_retries) + 1
        for attempt in range(attempts):
            try:
                reply = await self.ai.reply(
                    jid=msg.jid,
                    system=system,
                    history=history,
                    user_text=user_text,
                    attachments=attachments,
                )
                reply = reply.strip()
                if reply:
                    return reply
                logger.warning("resposta vazia do provedor (tentativa %s)", attempt + 1)
            except AIError as exc:
                logger.error("erro do provedor (tentativa %s): %s", attempt + 1, exc)
                if not exc.retryable:
                    break
            except Exception:
                logger.exception("erro inesperado ao gerar resposta")
            if attempt < attempts - 1:
                await asyncio.sleep(0.6 * (2**attempt))
        return None

    async def _system_prompt(self, msg: IncomingMessage) -> str:
        prompt_name = await self.db.get_pref(msg.jid, "prompt")
        try:
            template = self.prompts.get(prompt_name)
        except FileNotFoundError:
            logger.warning("prompt %r indisponivel, usando padrao", prompt_name)
            template = self.prompts.get(None)

        system = PromptManager.render(
            template,
            name=msg.push_name or "contato",
            number=msg.number,
            instance=msg.instance,
        )
        if self.settings.system_extra:
            system = f"{system}\n\n{self.settings.system_extra}"
        return system

    async def _audio_enabled(self, jid: str) -> bool:
        preference = await self.db.get_pref(jid, "audio")
        if preference is None:
            return self.settings.audio_reply_default
        return preference == "on"

    # -- midia -------------------------------------------------------------
    async def _prepare_media(
        self, msg: IncomingMessage
    ) -> tuple[str, list[Attachment]]:
        parts: list[str] = []
        if msg.text:
            parts.append(msg.text)

        attachments: list[Attachment] = []
        for media in msg.media:
            data_mime = await self.evolution.resolve_media(media)
            if data_mime is None:
                parts.append(self._media_note(media, failed=True))
                continue

            data, mime = data_mime
            if len(data) > self.settings.media_max_bytes:
                logger.warning("midia ignorada por tamanho: %s bytes", len(data))
                parts.append(self._media_note(media, failed=True))
                continue

            if media.kind == "audio":
                attachment = Attachment(
                    kind="audio",
                    mime=mime or media.mime or "audio/ogg",
                    data=data,
                    filename=media.filename or "audio.ogg",
                )
                transcript = await self.ai.transcribe(attachment)
                if transcript:
                    parts.append(f"[Transcricao do audio]: {transcript}")
                else:
                    parts.append("[Audio recebido, mas nao foi possivel transcrever]")
            elif media.kind == "image":
                attachments.append(
                    Attachment(
                        kind="image",
                        mime=mime or media.mime or "image/jpeg",
                        data=data,
                        filename=media.filename or "image.jpg",
                    )
                )
                parts.append("[Imagem enviada pelo contato]")
            else:
                parts.append(self._media_note(media))

        user_text = "\n".join(part for part in parts if part).strip()
        return user_text, attachments

    @staticmethod
    def _media_note(media: MediaRef, failed: bool = False) -> str:
        labels = {
            "audio": "Audio",
            "image": "Imagem",
            "video": "Video",
            "document": "Documento",
        }
        label = labels.get(media.kind, "Midia")
        if failed:
            return f"[{label} recebido, mas nao foi possivel baixar]"
        return f"[{label} recebido]"

    # -- comandos ----------------------------------------------------------
    def _is_admin(self, number: str) -> bool:
        admins = self.settings.admin_numbers_set
        return bool(admins) and number in admins

    async def _handle_command(self, msg: IncomingMessage, text: str) -> bool:
        command, _, argument = text[1:].partition(" ")
        command = command.lower().strip()
        argument = argument.strip()

        if command in {"help", "ajuda"}:
            await self._send(msg, HELP_TEXT)
        elif command in {"reset", "limpar"}:
            await self.db.clear_history(msg.jid)
            await self.ai.reset(msg.jid)
            await self._send(msg, "Memoria da conversa apagada.")
        elif command in {"prompt", "prompts"}:
            await self._command_prompt(msg, command, argument)
        elif command in {"audio", "voz"}:
            await self._command_audio(msg, argument)
        elif command in {"status", "ping"}:
            await self._command_status(msg)
        elif command in {"id", "jid"}:
            await self._send(msg, f"Numero: {msg.number}\nJID: {msg.jid}")
        else:
            return False
        return True

    async def _command_prompt(
        self, msg: IncomingMessage, command: str, argument: str
    ) -> None:
        available = self.prompts.list()
        current = await self.db.get_pref(msg.jid, "prompt") or self.prompts.default_name

        if command == "prompts" or (command == "prompt" and not argument):
            listing = "\n".join(f"- {name}" for name in available) or "(nenhum)"
            await self._send(
                msg,
                f"*Prompt atual:* {current}\n\n*Disponiveis:*\n{listing}\n\n"
                "Use: !prompt <nome>",
            )
            return

        if not self.prompts.exists(argument):
            listing = ", ".join(available) or "(nenhum)"
            await self._send(
                msg, f"Prompt *{argument}* nao encontrado.\nDisponiveis: {listing}"
            )
            return

        await self.db.set_pref(msg.jid, "prompt", self.prompts.normalize_name(argument))
        await self.ai.reset(msg.jid)
        await self._send(msg, f"System prompt alterado para *{argument}*.")

    async def _command_audio(self, msg: IncomingMessage, argument: str) -> None:
        action, _, test_text = argument.partition(" ")
        action = action.lower().strip()
        test_text = test_text.strip()

        if action in {"on", "ligar", "ativar"}:
            await self.db.set_pref(msg.jid, "audio", "on")
            await self._send(msg, "Respostas em audio ativadas para este contato.")
            return

        if action in {"off", "desligar", "desativar"}:
            await self.db.set_pref(msg.jid, "audio", "off")
            await self._send(msg, "Respostas em audio desativadas. Voltando ao texto.")
            return

        if action in {"test", "teste"}:
            if self.tts is None or not self.tts.enabled:
                await self._send(msg, "TTS desabilitado. Ative TTS_ENABLED no .env.")
                return
            if not await self._send_audio(msg, test_text or AUDIO_TEST_TEXT):
                await self._send(msg, "Nao foi possivel gerar/enviar o audio de teste.")
            return

        enabled = await self._audio_enabled(msg.jid)
        tts_status = self.tts.status if self.tts else "disabled"
        await self._send(
            msg,
            f"*Audio:* {'ligado' if enabled else 'desligado'}\n"
            f"*TTS:* {tts_status}\n\n"
            "Use: !audio on | !audio off | !audio test <texto>",
        )

    async def _command_status(self, msg: IncomingMessage) -> None:
        total = await self.db.count_messages(msg.jid)
        uptime = int(time.time() - self.started_at)
        hours, remainder = divmod(uptime, 3600)
        minutes, seconds = divmod(remainder, 60)
        prompt_name = (
            await self.db.get_pref(msg.jid, "prompt") or self.prompts.default_name
        )
        audio_enabled = await self._audio_enabled(msg.jid)
        tts_status = self.tts.status if self.tts else "disabled"
        await self._send(
            msg,
            "*Status*\n"
            f"Provedor: {self.ai.name}\n"
            f"Prompt: {prompt_name}\n"
            f"Audio: {'ligado' if audio_enabled else 'desligado'} (TTS {tts_status})\n"
            f"Mensagens na memoria: {total}\n"
            f"Uptime: {hours:02d}:{minutes:02d}:{seconds:02d}\n"
            f"Hora: {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        )

    # -- saida -------------------------------------------------------------
    async def _send_audio(self, msg: IncomingMessage, text: str) -> bool:
        if self.tts is None or not self.tts.enabled:
            logger.debug("TTS indisponivel; enviando texto")
            return False

        try:
            wav_bytes = await self.tts.synthesize(text)
        except TTSError as exc:
            logger.warning("falha ao sintetizar audio: %s", exc)
            return False
        except Exception:
            logger.exception("erro inesperado no TTS")
            return False

        encoded = base64.b64encode(wav_bytes).decode("ascii")
        try:
            await self.evolution.send_whatsapp_audio(msg.jid, encoded)
        except Exception:
            logger.exception("falha ao enviar audio PTT para %s", msg.jid)
            return False

        return True

    async def _send(self, msg: IncomingMessage, text: str) -> None:
        output = f"{self.settings.reply_prefix}{text}".strip()
        for chunk in split_message(output, self.settings.max_reply_chars):
            try:
                await self.evolution.send_text(msg.jid, chunk)
            except Exception:
                logger.exception("falha ao enviar mensagem para %s", msg.jid)
                return
