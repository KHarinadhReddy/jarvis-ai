# J.A.R.V.I.S. Backend

FastAPI backend for the J.A.R.V.I.S. Android app. It holds all AI keys and exposes authenticated endpoints for chat, vision, speech, and planning.

## Run locally

```powershell
cd jarvis-os/backend
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env and add DEEPSEEK_API_KEY (or OPENROUTER_API_KEY)
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000/docs` for the API explorer.

## Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /v1/health` | Provider/model status (no auth) |
| `POST /v1/chat/stream` | SSE streaming chat |
| `POST /v1/chat` | Non-streaming chat |
| `POST /v1/vision/analyze` | Image analysis (multipart) |
| `POST /v1/tts` | Edge neural TTS audio |
| `POST /v1/tts/segments` | Per-sentence MP3 clips plus pause/breath plan |
| `POST /v1/tts/plan` | Sentence/pause/breath plan |
| `GET /v1/tts/voices` | Available Telugu/English voices |
| `POST /v1/agent/plan` | Structured plan proposal |

All endpoints except health require `Authorization: Bearer <DEVICE_TOKEN>`.

## Android connection

- Emulator: `http://10.0.2.2:8000`
- Physical phone: `http://<laptop-LAN-IP>:8000` on the same Wi-Fi, or a Tailscale IP.
- The app never receives an AI key. It stores only the device token.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Tests use a mock provider and a fake TTS function; they do not spend AI credits.

## Production notes

- Put the backend behind HTTPS (Caddy, Cloudflare Tunnel, or a reverse proxy).
- Change `DEVICE_TOKEN` to a long random secret.
- Replace the in-memory rate limiter with Redis for multi-user deployments.
- Edge TTS is a free neural voice service without an SLA; for production, add Azure Speech, Google Cloud TTS, or Sarvam as a provider behind the same `/v1/tts` interface.
- DeepSeek official TTS/ASR do not support Telugu; Edge TTS is used for Telugu and Indian English. Android STT handles input.
