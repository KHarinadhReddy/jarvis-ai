# J.A.R.V.I.S. backend — truly standalone (no laptop) hosting

The app only needs the backend reachable at a public **HTTPS** URL. The backend holds
all AI keys; the phone never stores an AI key — only the bearer `DEVICE_TOKEN`.

This project already runs on a public host with **no code changes**, because:

- It binds `0.0.0.0`.
- It starts with `uvicorn app.main:app`.
- `PORT` is taken from the environment (`--port $PORT` / `${PORT:-8000}`).
- All secrets are injected via environment variables (no `.env` needed in the image).
- `ALLOW_MOCK=false` in production; provider order is DeepSeek → OpenRouter → (tests-only mock).

## Option A — Render (one click)

1. Push this repo to GitHub.
2. Render → **New Blueprint** → pick `KHarinadhReddy/jarvis-ai`.
3. It reads `render.yaml`. On prompt, set secrets (`sync: false` entries):
   - `OPENROUTER_API_KEY` (and/or `DEEPSEEK_API_KEY`)
   - `DEVICE_TOKEN` (long random string)
4. Deploy → you get `https://jarvis-ai-backend.onrender.com`.

## Option B — Fly.io

```bash
cd jarvis-os/backend
fly launch                 # creates app, writes fly.toml
fly secrets set OPENROUTER_API_KEY=... DEVICE_TOKEN=...
fly deploy
```

## Option C — Railway

- New Project → GitHub repo → root directory `jarvis-os/backend`.
- Build `pip install -r requirements.txt`, start `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
- Set `OPENROUTER_API_KEY`, `DEVICE_TOKEN`, `ALLOW_MOCK=false`.

## Option D — Any Docker host

```bash
docker build -t jarvis-backend .
docker run -p 8000:8000 \
  -e OPENROUTER_API_KEY=... \
  -e DEVICE_TOKEN=... \
  -e ALLOW_MOCK=false \
  jarvis-backend
```

## Then point the app at the public URL

On the phone app → **Settings → Backend URL**, enter your public HTTPS URL, e.g.:

```
https://jarvis-ai-backend.onrender.com
```

and set **Device token** to the same `DEVICE_TOKEN`.

To make it truly no-touch, bake it in at build time in
`jarvis-os/android/app/build.gradle.kts`:

```kotlin
// debug
buildConfigField("String", "DEFAULT_BACKEND_URL", "\"https://jarvis-ai-backend.onrender.com\"")
buildConfigField("String", "DEFAULT_DEVICE_TOKEN", "\"<long random token>\"")
```

```kotlin
// release block
buildConfigField("String", "DEFAULT_BACKEND_URL", "\"https://jarvis-ai-backend.onrender.com\"")
buildConfigField("String", "DEFAULT_DEVICE_TOKEN", "\"<long random token>\"")
```

and rebuild + reinstall. Then **no laptop, no `adb reverse`, no local backend** is required.

## Verify

```bash
curl https://your-public-url/v1/health
# expect {"status":"online",...,"provider":"openrouter",...,"configured":true}
```

## Security

- `ALLOW_MOCK=false`.
- Long random `DEVICE_TOKEN`.
- `ALLOWED_ORIGINS` left empty for Android-only use.
- Keys only in platform env, never in the repo.
