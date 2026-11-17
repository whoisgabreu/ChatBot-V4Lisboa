# ChatBot WhatsApp + Evolution API + IA

Bot de atendimento para WhatsApp que recebe mensagens pela **Evolution API**, responde
usando um provedor de IA e mantém memória por contato. O system prompt é configurável por
arquivos e pode ser trocado por contato via comando.

## Recursos

- Webhook assíncrono (FastAPI) que responde na hora e processa em fila.
- Provedores de IA:
  - **OpenAI-compatível** (OpenAI, Groq, OpenRouter, vLLM, LM Studio...) — mais rápido.
  - **opencode** via `opencode serve` — sessão por contato, system prompt por mensagem.
- System prompts em arquivos (`prompts/*.md`) com recarga automática ao editar.
- Memória persistente por contato em SQLite, com limite de mensagens e de caracteres.
- Áudio transcrito (Whisper/OpenAI-compatível) e imagens enviadas ao modelo com visão.
- Respostas em áudio Push-To-Talk (PTT) com TTS local (Piper), por contato/comando.
- Fila com concorrência limitada, debounce por contato e rate limit por minuto.
- Deduplicação de webhooks (a Evolution pode reenviar eventos).
- Docker e docker-compose inclusos.

## Estrutura

```
app/
  main.py            FastAPI + webhook + lifespan
  config.py          configuração via .env
  database.py        SQLite (memória, dedup, preferências)
  parser.py          interpretação dos eventos da Evolution
  evolution.py       envio de texto/áudio/imagem e download de mídia
  handler.py         orquestra prompt + memória + IA + envio
  queue.py           fila, concorrência e rate limit
  prompts.py         carregamento/hot reload dos system prompts
  tts.py             síntese de voz local com Piper
  ai/
    sanitize.py      remoção de markup DSML/tool calls
    openai_provider.py
    opencode_provider.py
    factory.py
opencode.json        agente `whatsapp` (websearch apenas)
prompts/
  system.md          prompt padrão
  vendas.md          exemplo de prompt alternativo
```

## 1. Configuração

```bash
cp .env.example .env
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Edite o `.env` com a URL/chave da Evolution e o provedor de IA.

### Evolution API

1. Crie/conecte uma instância.
2. Configure o webhook para `http://SEU_HOST:8000/webhook/evolution`.
3. Eventos necessários: `MESSAGES_UPSERT`.
4. Recomendado: ativar `webhookBase64` para mídia já chegar no webhook.
5. Se usar `EVOLUTION_WEBHOOK_SECRET`, envie esse valor no header
   `EVOLUTION_WEBHOOK_HEADER` (padrão `x-webhook-secret`) ou em `?secret=`.

Exemplo via API da Evolution:

```bash
curl -X POST "$EVOLUTION_BASE_URL/webhook/set/$EVOLUTION_INSTANCE" \
  -H "apikey: $EVOLUTION_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "webhook": {
      "enabled": true,
      "url": "http://SEU_HOST:8000/webhook/evolution",
      "events": ["MESSAGES_UPSERT"],
      "webhookByEvents": false,
      "webhookBase64": true
    }
  }'
```

## 2. Rodar

Atalho (cria venv, instala dependências, sobe o `opencode serve` se necessário e inicia o bot):

```bash
./run.sh
```

Ou manualmente:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Health check: `GET http://localhost:8000/health`.

> Para expor localmente use `ngrok http 8000` (ou Cloudflare Tunnel) e aponte o webhook
> para a URL pública.

## 3. Provedores de IA

### OpenAI-compatível (recomendado para velocidade)

```env
AI_PROVIDER=openai
AI_BASE_URL=https://api.openai.com/v1
AI_API_KEY=sk-...
AI_MODEL=gpt-4o-mini
```

Funciona com qualquer endpoint compatível. Exemplos:

| Provedor    | AI_BASE_URL                       | AI_MODEL              |
| ----------- | --------------------------------- | --------------------- |
| OpenAI      | https://api.openai.com/v1         | gpt-4o-mini           |
| Groq        | https://api.groq.com/openai/v1    | llama-3.3-70b-versatile |
| OpenRouter  | https://openrouter.ai/api/v1      | openai/gpt-4o-mini    |
| Ollama      | http://localhost:11434/v1         | llama3.1              |

### opencode

É possível usar o próprio opencode como motor. Inicie o servidor em um terminal (o
`run.sh` já faz isso na porta configurada):

```bash
opencode serve --port 4097
# se quiser proteger:
OPENCODE_SERVER_PASSWORD=segredo opencode serve --port 4097
```

O opencode precisa ter um provedor autenticado (`opencode auth login`) e um modelo
disponível. Então configure:

```env
AI_PROVIDER=opencode
OPENCODE_BASE_URL=http://127.0.0.1:4097
OPENCODE_PROVIDER_ID=opencode-go
OPENCODE_MODEL_ID=deepseek-v4.1-flash
OPENCODE_AGENT=whatsapp
```

Cada contato ganha uma sessão própria no opencode. O `system` é enviado em cada
mensagem a partir do arquivo de prompt.

O agente `whatsapp` é definido em `opencode.json` e restringe as ferramentas:

- `websearch`: permitido, para clima, cotação, notícias e dados atuais.
- `bash`, `read`, `edit`, `write`, `glob`, `grep`, `task`, `webfetch`, etc.: negados.

O DeepSeek não navega sozinho; ele usa a ferramenta `websearch` do opencode. Se o
modelo tentar chamar uma ferramenta indisponível, o bot remove qualquer markup DSML
antes de enviar e faz uma tentativa corretiva.

> Após alterar `opencode.json` ou o agente, reinicie o `opencode serve` (config é
> carregada apenas no startup). Depois envie `!reset` no WhatsApp para limpar sessões
> antigas que ainda tenham DSML no histórico.

Se o bot rodar em Docker e o opencode no host:

```env
OPENCODE_BASE_URL=http://host.docker.internal:4097
```

## 4. System prompts

Os arquivos ficam em `prompts/` e são recarregados automaticamente quando você edita
(mesmo com o bot rodando).

- `PROMPT_FILE` define o prompt padrão (ex.: `system.md`).
- Placeholders disponíveis: `{{name}}`, `{{number}}`, `{{instance}}`, `{{date}}`, `{{time}}`.
- `SYSTEM_EXTRA` adiciona um texto fixo ao final de qualquer prompt.

Comandos (somente para números em `ADMIN_NUMBERS`):

| Comando              | Ação                                             |
| -------------------- | ------------------------------------------------ |
| `!reset`             | Apaga a memória da conversa e reinicia a sessão  |
| `!prompt`            | Mostra o prompt atual e lista os disponíveis     |
| `!prompt vendas`     | Troca o system prompt **daquele contato**        |
| `!audio`             | Mostra se o áudio está ligado e o status do TTS  |
| `!audio on` / `off`  | Liga/desliga respostas em voz neste contato      |
| `!audio test <texto>`| Gera e envia um PTT de teste                     |
| `!status`            | Provedor, prompt, áudio, mensagens e uptime      |
| `!id`                | Mostra o número/JID do contato                   |
| `!help`              | Ajuda                                            |

## 5. Áudio e imagem

- **Áudio recebido**: baixa o arquivo da Evolution e transcreve usando
  `TRANSCRIBE_BASE_URL`/`TRANSCRIBE_MODEL`. Com `AI_PROVIDER=openai` o padrão é usar
  `AI_BASE_URL`; com `AI_PROVIDER=opencode` preencha `TRANSCRIBE_BASE_URL` explicitamente.
- **Imagem**: envia para o modelo com visão (provedor OpenAI-compatível). No opencode a
  imagem é anexada como `file`; se o modelo/servidor não aceitar, o bot avisa no texto.

Para desativar a transcrição: `TRANSCRIBE_ENABLED=false`.

### Respostas em áudio (Push-To-Talk)

O bot converte a resposta da IA em voz com o **Piper TTS local**, usando o modelo
`voiceGeneration/pt_BR-jeff-medium.onnx`. A voz fica carregada em memória (warmup no
startup) e a síntese roda em thread separada, sem travar o event loop.

- O áudio é gerado em WAV, convertido para base64 puro e enviado em
  `POST /message/sendWhatsAppAudio/{instance}`.
- `EVOLUTION_AUDIO_DELAY` simula o status “gravando áudio...” antes do envio.
- `EVOLUTION_AUDIO_ENCODING=true` pede que a Evolution converta para OGG/Opus nativo do
  WhatsApp (o host da Evolution precisa ter FFmpeg; isso já é padrão na imagem oficial).
- Se o TTS ou o envio falhar, o bot envia o texto como fallback.

Configuração:

```env
TTS_ENABLED=true
TTS_VOICE_PATH=voiceGeneration/pt_BR-jeff-medium.onnx
TTS_MAX_CHARS=900

AUDIO_REPLY_DEFAULT=false   # padrão texto; ligue por contato com !audio on
AUDIO_SEND_TEXT=false       # true = envia áudio + texto

EVOLUTION_AUDIO_DELAY=1200
EVOLUTION_AUDIO_ENCODING=true
```

O model é grande (~63 MB) e é copiado para a imagem Docker.

## 6. Docker

```bash
docker compose up -d --build
```

Volumes: `./data` (SQLite) e `./prompts` (somente leitura).

## 7. Testes e lint

```bash
pip install -r requirements-dev.txt
pytest
ruff check .
```

## Variáveis principais

| Variável                  | Padrão                    | Descrição                                   |
| ------------------------- | ------------------------- | ------------------------------------------- |
| `AI_PROVIDER`             | `openai`                  | `openai` ou `opencode`                      |
| `AI_MODEL`                | `gpt-4o-mini`             | modelo do provedor OpenAI-compatível        |
| `PROMPT_FILE`             | `system.md`               | prompt padrão                               |
| `DATABASE_PATH`           | `data/bot.sqlite3`        | arquivo SQLite                              |
| `HISTORY_LIMIT`           | `20`                      | mensagens lembradas por contato             |
| `ADMIN_NUMBERS`           | vazio                     | números autorizados a usar comandos         |
| `ALLOWED_NUMBERS`         | vazio                     | restringe quem o bot atende (vazio = todos) |
| `IGNORE_GROUPS`           | `true`                    | ignora conversas de grupo                   |
| `TTS_ENABLED`             | `false`                   | habilita síntese de voz com Piper           |
| `TTS_VOICE_PATH`          | `voiceGeneration/...onnx` | modelo de voz Piper                         |
| `AUDIO_REPLY_DEFAULT`     | `false`                   | responde em áudio por padrão                |
| `AUDIO_SEND_TEXT`         | `false`                   | envia áudio e texto juntos                  |
| `EVOLUTION_AUDIO_DELAY`   | `1200`                    | delay do “gravando áudio...” (ms)           |
| `MAX_CONCURRENT`          | `4`                       | respostas simultâneas                       |
| `RATE_LIMIT_PER_MINUTE`   | `20`                      | limite por contato                          |
| `MAX_REPLY_CHARS`         | `3500`                    | divide respostas longas                     |

Veja todas em `.env.example`.
# ChatBot-V4Lisboa
