# J.A.R.V.I.S. Mobile

A native Android voice assistant with a cyan HUD, real phone controls, a FastAPI AI gateway, and Telugu + English neural speech.

This is **not** a replacement Android OS. It is an Android application that can also be selected as the home app. The AOSP system underneath is unchanged. Everything below is either implemented and exercised on a device, or explicitly listed as blocked.

---

## What is in this repository

```
jarvis-os/
  android/                  Kotlin + Jetpack Compose app (package ai.jarvis.mobile)
  backend/                  FastAPI gateway that holds all AI keys
  docs/screenshots/         Captured emulator screens
  README.md                 This file
```

The existing Streamlit J.A.R.V.I.S. app in the parent directory is untouched. This project is additive.

---

## Architecture

```
┌──────────────────────────── Android phone ────────────────────────────┐
│  Compose HUD (Dashboard / Chat / Control / Vision / Vault / Settings)  │
│        │                                                              │
│  ChatViewModel ── AgentOrchestrator ── ToolRegistry ── DeviceController│
│        │                │                    │                        │
│        │                │                    └─ AccessibilityService  │
│        │                │                       (optional, global UI)  │
│        │                └─ streaming tool loop over SSE                │
│        │                                                              │
│  VoiceRecognizer (Android STT)   SpeechController (Edge MP3 + pauses)  │
│  Room (chat, memories, tasks)    DataStore (settings)                  │
│  WorkManager (task reminders)    CameraX (vision frames)               │
└──────────────────────────────────┬────────────────────────────────────┘
                                   │ HTTP + Bearer device token
┌──────────────────────────────────▼────────────────────────────────────┐
│  FastAPI backend                                                      │
│  /v1/chat/stream  /v1/vision/analyze  /v1/tts/segments  /v1/health    │
│  Provider order: DeepSeek official → OpenRouter → mock (tests only)    │
│  Edge TTS (free, no SLA) for Telugu and Indian English                 │
└───────────────────────────────────────────────────────────────────────┘
```

- **No AI key on the phone.** The APK stores only a device-pairing token.
- **Manual dependency injection** through `AppContainer`; no Hilt.
- **Room** stores chat history, memories, and tasks. **DataStore** stores settings.
- **Single `:app` module** with MVVM and a small clean-ish core layer.

---

## Quick start

### 0. One-click (recommended)

From the repo root:

```powershell
# Starts the FastAPI backend on :8000 AND sets up the adb reverse tunnel.
# Requires: Android emulator/USB device running.
.\jarvis-os\START_JARVIS.bat
```

Or individually:

```powershell
# Backend only
.\jarvis-os\backend\start_backend.bat

# ADB reverse tunnel only (after starting the emulator)
.\jarvis-os\android\setup_tunnel.bat
```

### 1. Backend

```powershell
cd jarvis-os/backend
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
# edit .env: add DEEPSEEK_API_KEY or OPENROUTER_API_KEY
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Check it:

```powershell
curl.exe http://127.0.0.1:8000/v1/health
```

Run the tests (no AI credits spent):

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

### 2. Android app

```powershell
cd jarvis-os/android
$env:JAVA_HOME='C:\Program Files\Android\Android Studio\jbr'
.\gradlew.bat :app:assembleDebug --no-daemon --console=plain
adb install -r app\build\outputs\apk\debug\app-debug.apk
adb reverse tcp:8000 tcp:8000
adb shell am start --display 0 -n ai.jarvis.mobile/.MainActivity
```

`adb reverse` makes `http://127.0.0.1:8000` inside the phone reach the laptop. It works for the emulator and for a USB-connected phone without opening a firewall port. For Wi-Fi use, put the laptop's LAN address in **Settings → Backend URL**.

The debug defaults are `http://127.0.0.1:8000` and `jarvis-dev-token`. The release build leaves both empty and requires configuration. Change the token before exposing the backend.

---

## Updating the app on your phone (no laptop needed)

There is a GitHub Actions workflow that builds the debug APK and publishes it to this repository's GitHub Releases page.

- The workflow runs automatically on every push to `main`, or you can trigger it manually via **Actions → Build J.A.R.V.I.S APK → Run workflow**.
- Each run attaches `jarvis-os/android/app/build/outputs/apk/debug/app-debug.apk` to a GitHub Release.

### Update from the phone (recommended path)

1. On the phone, allow installing unknown apps for your browser:
   `Settings → Apps → Special app access → Install unknown apps → Chrome (or your browser) → Allow`.
2. Open the GitHub repository's **Releases** page in the phone browser.
3. Download the latest `app-debug.apk`.
4. Tap the downloaded file and install.

That's it — no laptop, no ADB, no rebuild on your machine.

### Update from the laptop (existing path)

```powershell
cd jarvis-os/android
$env:JAVA_HOME='C:\Program Files\Android\Android Studio\jbr'
.\gradlew.bat :app:assembleDebug --no-daemon --console=plain
adb install -r app\build\outputs\apk\debug\app-debug.apk
```

One-click variant:

```powershell
.\jarvis-os\android\install_update.bat
```

---

## AI providers and models

The backend selects the first configured provider:

| Order | Provider | Default model | Notes |
|---|---|---|---|
| 1 | DeepSeek official (`https://api.deepseek.com`) | `deepseek-flash` | Preferred; thinking controlled by `{"thinking":{"type":"enabled"}}` |
| 2 | OpenRouter | `deepseek/deepseek-v4.1-flash` | Fallback when only `OPENROUTER_API_KEY` is set |
| 3 | Mock | `mock` | Tests only; never enabled in production |

On this development machine only an OpenRouter key exists. The free tier cannot call paid DeepSeek models, so live verification used `nvidia/nemotron-3.5-super-vl:free` (vision + tools + 1M context, 50 requests/day). The production default remains `deepseek/deepseek-v4.1-flash`; point `OPENROUTER_MODEL` at whatever model your key can actually use.

Environment variables (see `backend/app/config.py`):

| Variable | Purpose |
|---|---|
| `DEEPSEEK_API_KEY` | Official DeepSeek key |
| `DEEPSEEK_MODEL` | Default `deepseek-flash` |
| `OPENROUTER_API_KEY` | Fallback key |
| `OPENROUTER_MODEL` | Default `deepseek/deepseek-v4.1-flash` |
| `DEVICE_TOKEN` | Bearer token the app must present |
| `TTS_VOICE_EN`, `TTS_VOICE_TE` | Edge neural voice names |
| `TTS_RATE_LIMIT_PER_MINUTE` | Per-device speech limit |
| `ALLOW_MOCK` | Test-only mock provider |

---

## Voice pipeline

- **Input:** Android `SpeechRecognizer` push-to-talk. English (`en-IN`) and Telugu (`te-IN`) chips. No background microphone by default.
- **Output:** the backend splits the reply into sentences, calls Edge TTS per sentence, and returns MP3 clips with a pause and optional breath schedule. The phone plays them in order with `MediaPlayer`, real silence, a synthesized breath, and audio focus. It falls back to an installed Android TTS voice for English if Edge fails.
- **Interruption:** speaking can be stopped; the next request cancels the previous audio job.
- **Honesty:** pauses and breaths are scheduled by code, not generated by the model. No confidence score is invented.

Edge TTS is a free, unofficial service with no SLA. For a production deployment, put Azure Speech, Google Cloud TTS, or Sarvam behind the same `/v1/tts/segments` interface.

---

## Phone control

Every tool maps to a real Android API. Results are reported exactly as they happened.

| Tool | Real action |
|---|---|
| `device_status` | Battery, charging, temperature, current, network, storage, volume, brightness, accessibility |
| `app_open` | Launch an installed app by visible name |
| `settings_open` | Open the correct system settings panel |
| `system_flashlight` | Camera torch on/off |
| `system_brightness` | Write `Settings.System.SCREEN_BRIGHTNESS` (needs Modify system settings) |
| `system_volume` | Change a real audio stream index |
| `media_control` | Send media keys to the active session |
| `phone_call` | Place a call (confirmation required) |
| `phone_sms` | Send an SMS (confirmation required) |
| `calendar_create` | Insert a calendar event (confirmation required) |
| `alarm_set`, `timer_set` | Hand off to the clock app |
| `web_open`, `share_text` | Browser / share sheet intents |
| `ui_global_action` | Home, Back, Recents, Shade, Quick Settings, power dialog, split screen via the optional AccessibilityService |
| `contacts_search` | Query the contacts provider |
| `apps_list` | List launchable apps |

**Confirmation before execution:** `phone_call`, `phone_sms`, and `calendar_create` show a dialog before the action runs, in both the local parser path and the LLM tool path. Cancelling produces “Cancelled. I did not perform that action.”

**What Android does not allow:** a normal app cannot silently toggle Wi-Fi, Bluetooth, or mobile data. J.A.R.V.I.S. opens the system panel instead of pretending. The AccessibilityService is optional, user-enabled, declares `canRetrieveWindowContent="false"`, and is used only for global actions.

---

## Battery behaviour

Three modes, persisted in DataStore:

- **Cinematic** — fast reactor, scanline every 6.5 s.
- **Balanced** — slower reactor, scanline every 14 s.
- **Saver** — static reactor, no scanline animation.

Animations are lifecycle-aware and stop when the screen is not active. There is no polling loop for chat. Reminders use WorkManager, whose minimum periodic interval is 15 minutes; reminders can be late or skipped under Doze or low battery. This is an Android limit, not a fake timer.

---

## Security and privacy

- AI keys live only in `backend/.env`.
- The app authenticates with a bearer device token.
- Chat history, memories, and tasks stay in the phone's Room database.
- The backend has a per-device rate limiter and a separate TTS limit.
- The AccessibilityService does not read window content or password fields.
- Use HTTPS and a long random `DEVICE_TOKEN` outside local testing.

---

## Verified on this machine (28 Nov 2026)

Environment: Windows, Android emulator `Medium_Phone` (API 37, `emulator-5554`), backend on `127.0.0.1:8000` through `adb reverse`.

Real and observed:

- Debug APK builds; app launches on display 0.
- Dashboard reports `ONLINE`, the actual provider/model, and real battery/network/storage.
- Chat streams a real model reply; the LLM tool loop executed `apps_list` after a second `/v1/chat/stream` request and answered with installed apps.
- Context injection answered “How much battery do I have left” with the real 100% charging state.
- Torch on/off changed the real camera torch and showed a legible HUD notice.
- Volume + changed `STREAM_MUSIC` from index 6 to 7 and reported 50%.
- Brightness wrote 153/255 and the UI showed 60%.
- Vision returned a correct description of a generated test image (blue square, red circle, “JARVIS VISION” text).
- Vault persisted a memory and a task; a real `TaskReminderWorker` job appeared in JobScheduler.
- Settings link test returned provider, model, vision, and Telugu TTS status; Save persisted Power Saver and the dashboard showed `SAVER`.
- AccessibilityService bound as “J.A.R.V.I.S. Device Control”; the Home global action moved the system to the launcher.
- Confirmation-before-execution: “call 5551234” showed the dialog first; Cancel produced the cancellation reply and no call.
- Push-to-talk enters `MIC LIVE` / `LISTENING`; with no host microphone it stops honestly with “I did not catch that.”
- Backend: 18 tests pass.

Not verified or blocked:

- **No physical phone was connected.** Only the emulator was available. Telephony, SMS, contacts, and calendar have no real data in the emulator, so those paths are API-correct but not fully exercised.
- **No DeepSeek key.** The official `deepseek-flash` path is implemented but was not live-tested. Live tests used the free OpenRouter Nemotron model.
- **No host microphone in the emulator.** Speech recognition start/stop and the no-input path were verified; real transcription was not.
- **Media keys** were sent, but the emulator had no active media session to observe a response.
- **Hands-free wake word is not implemented.** `VoiceSessionService` is a documented placeholder. Background listening is off by default.
- **This is not a custom OS.** It is an app/launcher candidate on stock Android.

---

## Known limitations

- Edge TTS has no SLA and may change or fail.
- WorkManager reminders are approximate (15-minute minimum).
- Free OpenRouter models have daily request limits.
- The release build has no default backend URL or token by design.
- AGP 9's built-in Kotlin is disabled via `android.builtInKotlin=false` and `android.newDsl=false` because it conflicts with Kotlin 2.3.21 + KSP 2.3.14. This is temporary and documented in `gradle.properties`.
- Compose BOM is pinned to `2026.09.00` because newer BOMs require compileSdk 37.1 while only android-37.0 is installed.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| App says the link is quiet | Start the backend; run `adb reverse tcp:8000 tcp:8000` |
| `Missing bearer token` | Use the same `DEVICE_TOKEN` in the app and backend |
| Vision returns 502 | The model returned no usable content; retry, or switch to a vision-capable model |
| Accessibility shows “not connected” | Enable J.A.R.V.I.S. Device Control in Android accessibility settings; a force-stop unbinds it |
| Reminder arrives late | WorkManager/Doze limit; not a bug |
| `adb` starts the app on a virtual display | Use `am start --display 0 ...` |

---

## Screenshots

See `docs/screenshots/` for the captured Dashboard, Chat, Control, Vision, Vault, and Settings screens.
