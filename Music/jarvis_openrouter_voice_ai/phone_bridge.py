#!/usr/bin/env python3
"""JARVIS Phone Bridge — Phase 3 (runs inside Termux on Android).

Gives the JARVIS website hands-free access to the phone:
  - place normal calls          (termux-telephony-call)
  - send SMS                    (termux-sms-send)
  - read SMS inbox              (termux-sms-list)
  - read notifications          (termux-notification-list)  -> WhatsApp / SMS previews
  - open a WhatsApp chat        (termux-open https://wa.me/...)  (Phase 3: tap Send;
                                 fully silent WhatsApp send is Phase 4 / ADB)

Setup (one time)
  1. Install F-Droid, then install "Termux" and "Termux:API" from F-Droid.
  2. In Termux:
       pkg update && pkg install python termux-api
       termux-setup-storage            # allow file access
  3. Copy this file to the phone (e.g. Download folder), then:
       cp /sdcard/Download/phone_bridge.py ~/
       python ~/phone_bridge.py --port 8765
  4. The bridge prints a URL + token. Put both into
     JARVIS -> Settings -> Phone Bridge, then press "Test connection".
  5. Grant permissions when Android asks (Phone, SMS, Notifications).
     For notification reading: Android Settings -> Apps -> Special access ->
     Notification access -> enable "Termux:API".

Run on the same Wi-Fi as the JARVIS laptop. For remote use, put both on
Tailscale (or use an SSH reverse tunnel).
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

DEFAULT_PORT = 8765
MOCK = False


def run_cmd(cmd: list[str], timeout: int = 25) -> tuple[int, str, str]:
    if MOCK:
        joined = " ".join(cmd)
        print(f"[mock] {joined}")
        if cmd[0] == "termux-telephony-call":
            return 0, "", ""
        if cmd[0] == "termux-sms-send":
            return 0, "", ""
        if cmd[0] == "termux-sms-list":
            return 0, json.dumps([
                {"number": "+919876543210", "name": "Shireesha", "body": "Call me when free",
                 "received": "2026-11-24T09:12:00", "read": False},
                {"number": "+919123456780", "name": "Mom", "body": "Dinner at 8",
                 "received": "2026-11-24T08:40:00", "read": True},
            ]), ""
        if cmd[0] == "termux-notification-list":
            return 0, json.dumps([
                {"packageName": "com.whatsapp", "appName": "WhatsApp", "title": "Shireesha",
                 "content": "Are you coming today?", "when": "2026-11-24T09:20:00"},
                {"packageName": "com.whatsapp", "appName": "WhatsApp", "title": "Family group",
                 "content": "Mom: Bring sweets", "when": "2026-11-24T09:05:00"},
            ]), ""
        if cmd[0] == "termux-open":
            return 0, "", ""
        return 0, "", ""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except Exception as e:
        return -1, "", str(e)


def _digits(number: str) -> str:
    d = re.sub(r"\D", "", number or "")
    return d


def _filter_messages(notifs: list[dict]) -> list[dict]:
    out = []
    for n in notifs:
        pkg = str(n.get("packageName") or "").lower()
        app = str(n.get("appName") or "")
        if any(k in pkg for k in ("whatsapp", "mms", "messaging", "sms", "telegram")):
            out.append({
                "app": app or pkg,
                "from": n.get("title") or "",
                "text": n.get("content") or n.get("text") or "",
                "when": n.get("when") or "",
            })
    return out


class BridgeHandler(BaseHTTPRequestHandler):
    token = ""

    # ---------- helpers
    def _authed(self) -> bool:
        given = self.headers.get("X-Jarvis-Token") or ""
        if not given:
            qs = parse_qs(urlparse(self.path).query)
            given = (qs.get("token") or [""])[0]
        return bool(self.token) and secrets.compare_digest(str(given), str(self.token))

    def _send(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b"{}"
            return json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            return {}

    def log_message(self, fmt, *args):  # keep the Termux console clean
        print(f"[bridge] {self.address_string()} {fmt % args}")

    # ---------- GET
    def do_GET(self):
        if not self._authed():
            return self._send(401, {"ok": False, "error": "bad token"})
        path = urlparse(self.path).path.rstrip("/") or "/"
        qs = parse_qs(urlparse(self.path).query)

        if path == "/ping":
            return self._send(200, {
                "ok": True,
                "device": f"{platform.system()} {platform.release()}",
                "mock": MOCK,
            })

        if path == "/sms/list":
            limit = int((qs.get("limit") or ["10"])[0] or 10)
            code, out, err = run_cmd(["termux-sms-list", "-l", str(max(1, min(limit, 50)))])
            try:
                items = json.loads(out) if out else []
            except Exception:
                items = []
            return self._send(200 if code == 0 else 500, {
                "ok": code == 0, "items": items, "error": err,
            })

        if path == "/notifications":
            limit = int((qs.get("limit") or ["30"])[0] or 30)
            code, out, err = run_cmd(["termux-notification-list"])
            try:
                items = json.loads(out) if out else []
            except Exception:
                items = []
            messages = _filter_messages(items)[: max(1, min(limit, 50))]
            return self._send(200 if code == 0 else 500, {
                "ok": code == 0, "items": items[:limit], "messages": messages, "error": err,
            })

        if path == "/health":
            tools = {t: bool(shutil.which(t)) for t in (
                "termux-telephony-call", "termux-sms-send", "termux-sms-list",
                "termux-notification-list", "termux-open")}
            return self._send(200, {"ok": True, "tools": tools, "mock": MOCK})

        return self._send(404, {"ok": False, "error": "unknown path"})

    # ---------- POST
    def do_POST(self):
        if not self._authed():
            return self._send(401, {"ok": False, "error": "bad token"})
        path = urlparse(self.path).path.rstrip("/") or "/"
        body = self._body()

        if path == "/call":
            number = _digits(body.get("number") or "")
            if not number:
                return self._send(400, {"ok": False, "error": "missing number"})
            code, out, err = run_cmd(["termux-telephony-call", number])
            return self._send(200 if code == 0 else 500, {
                "ok": code == 0, "number": number, "error": err,
            })

        if path == "/sms":
            number = _digits(body.get("number") or "")
            text = str(body.get("text") or "").strip()
            if not number or not text:
                return self._send(400, {"ok": False, "error": "missing number or text"})
            code, out, err = run_cmd(["termux-sms-send", "-n", number, text])
            return self._send(200 if code == 0 else 500, {
                "ok": code == 0, "number": number, "error": err,
            })

        if path == "/whatsapp/open":
            number = _digits(body.get("number") or "")
            text = str(body.get("text") or "")
            if not number:
                return self._send(400, {"ok": False, "error": "missing number"})
            url = f"https://wa.me/{number}"
            if text:
                url += "?text=" + quote(text)
            code, out, err = run_cmd(["termux-open", url])
            return self._send(200 if code == 0 else 500, {
                "ok": code == 0, "number": number, "error": err,
                "note": "WhatsApp opened; tap Send/Call in the app (Phase 4 makes this silent).",
            })

        if path == "/whatsapp/send":
            # Phase 4 (ADB/accessibility) placeholder — honest error for now.
            return self._send(501, {
                "ok": False,
                "error": "Silent WhatsApp sending needs the Phase 4 ADB bridge.",
            })

        return self._send(404, {"ok": False, "error": "unknown path"})


def _local_ip() -> str:
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def main() -> None:
    global MOCK
    ap = argparse.ArgumentParser(description="JARVIS Phone Bridge (Termux)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--token", default=os.getenv("JARVIS_BRIDGE_TOKEN", ""))
    ap.add_argument("--mock", action="store_true", help="test mode: no real calls/SMS")
    args = ap.parse_args()
    MOCK = bool(args.mock)

    token = args.token or secrets.token_urlsafe(18)
    BridgeHandler.token = token
    ip = _local_ip()
    url = f"http://{ip}:{args.port}"

    print("=" * 62)
    print("  JARVIS PHONE BRIDGE" + ("  [MOCK MODE]" if MOCK else ""))
    print("=" * 62)
    print(f"  URL   : {url}")
    print(f"  Token : {token}")
    print()
    print("  Put both values into JARVIS -> Settings -> Phone Bridge.")
    print("  Keep this window open while using hands-free calls/SMS.")
    if not MOCK:
        missing = [t for t in ("termux-telephony-call", "termux-sms-send",
                               "termux-sms-list", "termux-notification-list", "termux-open")
                   if not shutil.which(t)]
        if missing:
            print()
            print("  WARNING missing Termux:API commands:", ", ".join(missing))
            print("  Run: pkg install termux-api   (and install the Termux:API app)")
    print("=" * 62)

    server = ThreadingHTTPServer(("0.0.0.0", args.port), BridgeHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBridge stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
