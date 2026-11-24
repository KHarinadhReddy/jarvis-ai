# JARVIS Phone Bridge — Setup (Phase 3)

The Phone Bridge lets the JARVIS **website** (phone or laptop browser) make
hands-free calls, send SMS, read SMS, and read WhatsApp/SMS notifications.
It runs inside **Termux** on your Android phone — no custom app build needed.

---

## 1. Install the apps (one time)

1. Install **F-Droid** → https://f-droid.org
2. From F-Droid install:
   - **Termux**
   - **Termux:API** (the add-on app, not just the package)

## 2. Prepare Termux

Open Termux and run:

```bash
pkg update && pkg upgrade -y
pkg install python termux-api -y
termux-setup-storage
```

Grant the storage permission when Android asks.

## 3. Copy the bridge script

Copy `phone_bridge.py` from this project to your phone's Download folder
(USB cable, Google Drive, or `scp`). Then in Termux:

```bash
cp /sdcard/Download/phone_bridge.py ~/
```

## 4. Run the bridge

```bash
python ~/phone_bridge.py --port 8765
```

You will see:

```
==============================================================
  JARVIS PHONE BRIDGE
==============================================================
  URL   : http://192.168.1.23:8765
  Token : AbCdEfGhIjKlMnOpQrStUvWx
```

Keep this Termux session open while using JARVIS.

> Test mode (no real calls/SMS): `python ~/phone_bridge.py --mock`

## 5. Connect JARVIS

On the laptop (or phone browser), open JARVIS:

- **Settings → Phone Bridge**
- URL: `http://192.168.1.23:8765` (your phone's address shown above)
- Token: the token shown above
- Press **Save bridge**, then **Test connection**
- You should see: *Connected — Linux ...*

The phone and laptop must be on the **same Wi-Fi**.
For use outside home, put both devices on **Tailscale** (free) and use the
Tailscale IP instead of the local one.

## 6. Grant Android permissions

When you first use each command, allow:

| Feature | Permission |
|---|---|
| Calls | Phone |
| SMS send/read | SMS |
| Notifications (WhatsApp previews) | Notification access |

For notifications: **Android Settings → Apps → Special app access →
Notification access → enable “Termux:API”**.

## 7. Commands that now work (phone or laptop browser)

Say or type:

```
call mom
dial aunty
text mom saying I'll be late
check messages
read my messages
```

Notes:
- `check messages` = unread email + latest SMS + WhatsApp notifications.
- WhatsApp **sending** opens the chat with the message pre-filled
  (tap Send). Fully silent WhatsApp send/call is Phase 4 (ADB automation).
- Normal calls are placed directly by the phone — fully hands-free.

## Troubleshooting

| Problem | Fix |
|---|---|
| “bridge unreachable” | Same Wi-Fi? Termux still running? Correct IP/port? |
| “missing Termux:API commands” | `pkg install termux-api` and install the Termux:API app |
| Calls do nothing | Allow the Phone permission for Termux:API |
| No WhatsApp notifications | Enable Notification access for Termux:API |
| Token rejected | Re-copy the token (it changes each run unless you pass `--token`) |

To keep the same token between restarts:

```bash
python ~/phone_bridge.py --port 8765 --token "my-secret-token"
```
