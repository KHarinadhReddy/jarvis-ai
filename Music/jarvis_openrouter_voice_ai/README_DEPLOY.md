# JARVIS — Free Cloud Deploy (works when your PC is off)

Streamlit Community Cloud gives you a public HTTPS URL, free. The phone
mic/camera work because the URL is HTTPS. Memory (SQLite) is **ephemeral** on
the free tier: it survives normal use but resets when the app sleeps/reboots
and always when you redeploy.

## 0) One-time local commit (already prepared)

```powershell
cd "C:\Users\RAMULUREDDY\Music\jarvis_openrouter_voice_ai"
git add .
git commit -m "JARVIS mobile: unified chat+voice, instant nav, online deploy"
```

## 1) Create a GitHub repo

1. Go to https://github.com/new
2. Name: `jarvis-ai` · Private is fine · **Do not** add README/gitignore.
3. Copy the repo URL, then:

```powershell
git remote add origin https://github.com/<YOUR_USER>/jarvis-ai.git
git branch -M main
git push -u origin main
```

(If Git asks for a password, use a Personal Access Token:
GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
→ Generate new token → scope `repo` → paste the token as the password.)

## 2) Deploy on Streamlit Community Cloud

1. Go to https://share.streamlit.io and sign in with GitHub.
2. Click **New app**.
3. Repository: `<YOUR_USER>/jarvis-ai` · Branch: `main` · Main file path: `jarvis_exact.py`
4. Click **Advanced settings → Secrets** and paste:

```toml
OPENROUTER_API_KEY = "sk-or-v1-xxxxxxxxxxxxxxxxxxxx"
```

5. Click **Deploy**. First build takes ~3–6 minutes.
6. You get a URL like `https://jarvis-ai-xxxx.streamlit.app`.

## 3) On your phone

1. Open the Streamlit URL in Chrome/Safari.
2. Menu → **Add to Home Screen** (manifest + icons already configured).
3. The app auto-detects mobile and opens the HUD.
4. Allow microphone/camera when asked (HTTPS is required and Streamlit Cloud provides it).

## Notes

- **Wake/sleep:** free apps sleep after ~15 min without traffic. First open
  after sleep takes ~20–40 s. Keep it awake by visiting it, or upgrade later.
- **Speed:** replies are OpenRouter + `:online` web grounding, same as local.
- **Media:** YouTube/Spotify playback happens on the phone; no host files needed.
- **Desktop version:** `?view=desktop` on any device.
- **Persistent memory:** for production, move `jarvis_memory.db` + `memory_media/`
  to Supabase/Turso/S3 and set the same env vars. Ask me and I'll wire it.
- **Secrets never committed:** `.env`, `user_profile.json`, `tasks.json`,
  `jarvis_memory.db`, `jarvis_web_cache.db`, and `memory_media/` are git-ignored.

## Alternative: Hugging Face Spaces (no sleep on paid; 48 h sleep on free)

1. https://huggingface.co/new-space → SDK: **Streamlit**.
2. Add `OPENROUTER_API_KEY` under Settings → Variables and secrets → Secrets.
3. Clone the Space repo and push these files:
   `jarvis_exact.py`, `memory_engine.py`, `web_engine.py`, `requirements.txt`,
   `static/`, `.streamlit/config.toml`.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Build fails on `pyaudio` | `requirements.txt` is cloud-safe; never add pyaudio there. |
| "Invalid key" on cloud | Add `OPENROUTER_API_KEY` in app Secrets, then reboot the app. |
| Mic button does nothing | Use Chrome; allow microphone; the app needs HTTPS. |
| App asleep | Open the URL and wait ~30 s for the container to wake. |
