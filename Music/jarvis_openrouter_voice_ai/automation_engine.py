"""JARVIS Automation Engine — Phases 1-3

Phase 1 — Smart contacts
  * data/contacts.json with aliases + relationships + phones/emails
  * Fuzzy resolver (moms -> mom, aunts -> aunty, sireesha ~ shireesha)
  * Google Contacts CSV import

Phase 2 — Email (fully hands-free, server-side)
  * Send via SMTP
  * Read/summarize via IMAP ("check my email", "read the first email", "reply ...")

Phase 3 — Phone Bridge (Termux:API on Android)
  * Hands-free normal calls, SMS send/read, WhatsApp notifications
  * WhatsApp chat open with pre-filled message (tap Send; silent send is Phase 4)

Commands (work from the phone browser and the laptop browser):
  "call mom" / "dial aunty" / "phone sireesha"
  "text mom saying I'll be late"
  "whatsapp aunty saying hello"
  "check messages" / "check my email" / "read the first email"
  "reply to that email saying thanks"
  "send email to dad saying happy birthday"
  "remind me to buy milk at 3pm"
  "search for AI trends"
  "generate a docx called Todo List"
"""
import io
import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

INTEGRATIONS_FILE = DATA_DIR / "integrations.json"
LAST_EMAILS_FILE = DATA_DIR / "last_emails.json"
REMINDER_FILE = DATA_DIR / "reminders.json"


# ---------------------------------------------------------------- integrations
def load_integrations() -> dict:
    """Runtime integration settings saved from the JARVIS Settings page."""
    if not INTEGRATIONS_FILE.exists():
        return {}
    try:
        data = json.loads(INTEGRATIONS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_integrations(patch: dict) -> dict:
    """Deep-merge and persist integration settings. Returns the merged config."""
    cfg = load_integrations()
    for key, val in (patch or {}).items():
        if isinstance(val, dict) and isinstance(cfg.get(key), dict):
            cfg[key].update(val)
        else:
            cfg[key] = val
    try:
        INTEGRATIONS_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception:
        pass
    return cfg


# ---------------------------------------------------------------- SMTP
SMTP_CONFIG = {
    "host": os.getenv("SMTP_HOST", ""),
    "port": int(os.getenv("SMTP_PORT", "587") or 587),
    "user": os.getenv("SMTP_USER", ""),
    "password": os.getenv("SMTP_PASSWORD", ""),
    "from_email": os.getenv("SMTP_FROM", ""),
    "to_email": os.getenv("SMTP_TO", ""),
}


def _smtp_cfg() -> dict:
    saved = load_integrations().get("smtp", {}) or {}
    return {
        "host": os.getenv("SMTP_HOST") or saved.get("host") or SMTP_CONFIG["host"],
        "port": int(os.getenv("SMTP_PORT") or saved.get("port") or SMTP_CONFIG["port"] or 587),
        "user": os.getenv("SMTP_USER") or saved.get("user") or SMTP_CONFIG["user"],
        "password": os.getenv("SMTP_PASSWORD") or saved.get("password") or SMTP_CONFIG["password"],
        "from_email": os.getenv("SMTP_FROM") or saved.get("from_email") or SMTP_CONFIG["from_email"],
        "to_email": os.getenv("SMTP_TO") or saved.get("to_email") or SMTP_CONFIG["to_email"],
    }


def send_email(to_email: str, subject: str, body: str, cc: list = None) -> tuple[bool, str]:
    """Send an email via SMTP. Returns (success, message)."""
    import smtplib
    from email.message import EmailMessage
    cfg = _smtp_cfg()
    if not cfg["host"]:
        return False, "Email sending is not set up. Add your SMTP details in Settings → Email."
    try:
        msg = EmailMessage()
        msg["From"] = cfg["from_email"] or cfg["user"] or "jarvis@localhost"
        msg["To"] = to_email
        msg["Subject"] = subject or "Message from JARVIS"
        msg.set_content(body)
        if cc:
            msg["Cc"] = ", ".join(cc)
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=18) as s:
            s.starttls()
            if cfg["user"]:
                s.login(cfg["user"], cfg["password"])
            s.send_message(msg)
        return True, f"Email sent to {to_email}"
    except Exception as e:
        return False, f"Email failed: {e}"


# ---------------------------------------------------------------- contacts
def get_contacts() -> dict:
    """Legacy flat map name -> email/phone (kept for social/message helpers)."""
    contacts: dict[str, str] = {}
    try:
        import contacts_engine as ce
        for c in ce.list_contacts():
            name = (c.get("name") or "").strip().lower()
            if not name:
                continue
            contacts[name] = (c.get("email") or c.get("phone") or c.get("whatsapp") or "").strip()
            for alias in c.get("aliases") or []:
                contacts[str(alias).strip().lower()] = contacts[name]
    except Exception:
        pass
    # Legacy flat contacts.json
    cj = DATA_DIR / "contacts.json"
    if cj.exists():
        try:
            extra = json.loads(cj.read_text(encoding="utf-8"))
            if isinstance(extra, dict) and "contacts" not in extra:
                contacts.update({str(k).lower(): str(v) for k, v in extra.items()})
        except Exception:
            pass
    return contacts


def _resolve_contact(who: str) -> tuple[Optional[dict], str]:
    """Resolve a spoken name. Returns (contact, clarification_message)."""
    try:
        import contacts_engine as ce
    except Exception:
        return None, ""
    res = ce.resolve(who)
    if res.get("ambiguous"):
        names = ", ".join(ce.describe(c) for c in res.get("candidates", [])[:3])
        return None, f"Which one did you mean — {names}? Please say the full name."
    return res.get("contact"), ""


def _resolve_phone(who: str, whatsapp: bool = False) -> tuple[str, str, str]:
    """Returns (number, display_name, error)."""
    try:
        import contacts_engine as ce
    except Exception:
        ce = None
    if ce:
        res = ce.resolve(who)
        if res.get("ambiguous"):
            names = ", ".join(ce.describe(c) for c in res.get("candidates", [])[:3])
            return "", "", f"Which one did you mean — {names}? Please say the full name."
        c = res.get("contact")
        if c:
            num = ce.whatsapp_for(c) if whatsapp else ce.phone_for(c)
            if not num:
                return "", "", f"{c.get('name')} has no {'WhatsApp' if whatsapp else 'phone'} number saved."
            return num, ce.describe(c), ""
    # A raw number spoken directly
    digits = re.sub(r"[^\d+]", "", who or "")
    if len(re.sub(r"\D", "", digits)) >= 7:
        return digits, who, ""
    return "", "", f"I couldn't find “{who}” in your contacts. Add them in Settings → Contacts."


# ---------------------------------------------------------------- phone bridge
def _bridge_cfg() -> dict:
    saved = load_integrations().get("phone_bridge", {}) or {}
    return {
        "url": (os.getenv("PHONE_BRIDGE_URL") or saved.get("url") or "").strip().rstrip("/"),
        "token": (os.getenv("PHONE_BRIDGE_TOKEN") or saved.get("token") or "").strip(),
    }


def _bridge_request(path: str, payload: Optional[dict] = None, timeout: int = 12) -> dict:
    import urllib.error
    import urllib.request
    cfg = _bridge_cfg()
    if not cfg["url"]:
        return {"ok": False, "error": "Phone bridge is not connected. Open Settings → Phone Bridge and add the bridge URL + token."}
    if not cfg["token"]:
        return {"ok": False, "error": "Phone bridge token is missing. Copy it from the Termux window into Settings → Phone Bridge."}
    url = cfg["url"] + path
    try:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data, method=("POST" if payload is not None else "GET"))
        req.add_header("X-Jarvis-Token", cfg["token"])
        if data:
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw or "{}")
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8", errors="replace") or "{}")
        except Exception:
            return {"ok": False, "error": f"Bridge HTTP {e.code}"}
    except Exception as e:
        return {"ok": False, "error": f"Phone bridge unreachable: {e}"}


def bridge_ping() -> dict:
    return _bridge_request("/ping", timeout=6)


def bridge_health() -> dict:
    return _bridge_request("/health", timeout=8)


def bridge_call(number: str) -> dict:
    return _bridge_request("/call", {"number": number})


def bridge_sms(number: str, text: str) -> dict:
    return _bridge_request("/sms", {"number": number, "text": text})


def bridge_sms_list(limit: int = 10) -> dict:
    return _bridge_request(f"/sms/list?limit={int(limit)}")


def bridge_notifications(limit: int = 20) -> dict:
    return _bridge_request(f"/notifications?limit={int(limit)}")


def bridge_whatsapp_open(number: str, text: str = "") -> dict:
    return _bridge_request("/whatsapp/open", {"number": number, "text": text})


# ---------------------------------------------------------------- IMAP email
_LAST_EMAILS: list[dict] = []


def _imap_cfg() -> dict:
    saved = load_integrations().get("imap", {}) or {}
    smtp = _smtp_cfg()
    return {
        "host": os.getenv("IMAP_HOST") or saved.get("host") or "imap.gmail.com",
        "port": int(os.getenv("IMAP_PORT") or saved.get("port") or 993),
        "user": os.getenv("IMAP_USER") or saved.get("user") or smtp["user"],
        "password": os.getenv("IMAP_PASSWORD") or saved.get("password") or smtp["password"],
    }


def _decode_mime(value: str) -> str:
    from email.header import decode_header
    out = []
    for part, enc in decode_header(value or ""):
        if isinstance(part, bytes):
            try:
                out.append(part.decode(enc or "utf-8", errors="replace"))
            except Exception:
                out.append(part.decode("utf-8", errors="replace"))
        else:
            out.append(str(part))
    return "".join(out)


def _strip_html(html: str) -> str:
    import html as _html
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = _html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _email_body(msg, limit: int = 2500) -> str:
    text = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if "attachment" in disp.lower():
                continue
            payload = part.get_payload(decode=True) or b""
            charset = part.get_content_charset() or "utf-8"
            if ctype == "text/plain" and not text:
                text = payload.decode(charset, errors="replace")
            elif ctype == "text/html" and not text:
                text = _strip_html(payload.decode(charset, errors="replace"))
    else:
        payload = msg.get_payload(decode=True) or b""
        charset = msg.get_content_charset() or "utf-8"
        raw = payload.decode(charset, errors="replace")
        text = _strip_html(raw) if msg.get_content_type() == "text/html" else raw
    return re.sub(r"\n{3,}", "\n\n", text).strip()[:limit]


def check_email(limit: int = 6, unread_only: bool = True) -> dict:
    """Fetch recent emails via IMAP. Returns {ok, error, items, unread}."""
    global _LAST_EMAILS
    cfg = _imap_cfg()
    if not (cfg["user"] and cfg["password"]):
        return {"ok": False, "items": [], "unread": 0,
                "error": "Email reading is not set up. Add your Gmail address + app password in Settings → Email."}
    try:
        import email as _email
        import imaplib
        from email.utils import parsedate_to_datetime

        box = imaplib.IMAP4_SSL(cfg["host"], cfg["port"])
        box.login(cfg["user"], cfg["password"])
        box.select("INBOX", readonly=True)
        typ, data = box.search(None, "UNSEEN" if unread_only else "ALL")
        ids = (data[0] or b"").split() if typ == "OK" else []
        unread = len(ids)
        items: list[dict] = []
        for n, mid in enumerate(ids[-limit:][::-1], 1):
            typ, msg_data = box.fetch(mid, "(RFC822)")
            if typ != "OK" or not msg_data:
                continue
            raw = b"".join(p[1] for p in msg_data if isinstance(p, tuple) and p[1])
            msg = _email.message_from_bytes(raw)
            subject = _decode_mime(msg.get("Subject") or "(no subject)")
            sender = _decode_mime(msg.get("From") or "")
            date_raw = msg.get("Date") or ""
            try:
                date_s = parsedate_to_datetime(date_raw).strftime("%d %b %H:%M")
            except Exception:
                date_s = date_raw[:25]
            body = _email_body(msg)
            items.append({"n": n, "from": sender, "subject": subject, "date": date_s,
                          "body": body, "snippet": body[:180]})
        box.logout()
        _LAST_EMAILS = items
        try:
            LAST_EMAILS_FILE.write_text(json.dumps(items, indent=2), encoding="utf-8")
        except Exception:
            pass
        return {"ok": True, "items": items, "unread": unread, "error": ""}
    except Exception as e:
        return {"ok": False, "items": [], "unread": 0, "error": f"IMAP error: {e}"}


def email_summary(limit: int = 5) -> dict:
    r = check_email(limit=limit)
    if not r["ok"]:
        return {"ok": False, "text": r["error"]}
    items = r["items"]
    if not items:
        return {"ok": True, "text": "No unread emails — inbox is clear."}
    lines = [f"You have {r['unread']} unread email{'s' if r['unread'] != 1 else ''}."]
    for it in items:
        lines.append(f"{it['n']}. From {it['from']} — {it['subject']} ({it['date']})")
    return {"ok": True, "text": "\n".join(lines)}


def _last_emails() -> list[dict]:
    global _LAST_EMAILS
    if _LAST_EMAILS:
        return _LAST_EMAILS
    try:
        data = json.loads(LAST_EMAILS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def read_email(index: int = 1) -> str:
    items = _last_emails()
    if not items:
        return "No emails cached yet. Say “check my email” first."
    idx = max(0, min(index - 1, len(items) - 1))
    it = items[idx]
    return f"Email {idx + 1} from {it['from']} — {it['subject']}.\n\n{it['body'][:1400]}"


def reply_last_email(body: str) -> tuple[bool, str]:
    items = _last_emails()
    if not items:
        return False, "There is no email to reply to. Say “check my email” first."
    it = items[0]
    m = re.search(r"<([^>]+)>", it["from"])
    addr = m.group(1) if m else it["from"].strip()
    subj = it["subject"] if it["subject"].lower().startswith("re:") else "Re: " + it["subject"]
    return send_email(addr, subj, body)


# ---------------------------------------------------------------- reminders
def load_reminders() -> list:
    if REMINDER_FILE.exists():
        try:
            data = json.loads(REMINDER_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            pass
    return []


def save_reminders(items: list) -> None:
    REMINDER_FILE.write_text(json.dumps(items, indent=2), encoding="utf-8")


def _clean_text(s: str) -> str:
    """Normalize smart quotes/apostrophes for regex matching."""
    if not s:
        return ""
    return (s.replace("\u201c", "").replace("\u201d", "")
             .replace("\u2018", "'").replace("\u2019", "'")
             .replace("\u2014", " ").replace("\u2013", "-")
             .replace("\u2026", "...")
             .strip())


def parse_time_natural(text: str) -> tuple[datetime, bool]:
    """Parse natural time expressions: 'in 5 minutes', 'at 3pm', 'tomorrow 2pm'."""
    t = _clean_text(text).lower().strip()
    now = datetime.now()
    m = re.search(r"(?:in|after)\s+(\d+)\s*(minute?s?|hour?s?|min|hr)", t)
    if m:
        n = int(m.group(1))
        unit = m.group(2).rstrip("s")
        if unit.startswith("hr"):
            return now + timedelta(hours=n), True
        return now + timedelta(minutes=n), True
    m = re.search(r"(\d+)\s*(minutes?|min|hours?|hr)$", t)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if unit.startswith("hr"):
            return now + timedelta(hours=n), True
        return now + timedelta(minutes=n), True
    m = re.search(r"(?:today|tomorrow)?\s*(?:at\s*)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", t)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        ampm = (m.group(3) or "pm").lower()
        if ampm == "am" and hour == 12:
            hour = 0
        elif ampm == "pm" and hour != 12:
            hour += 12
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now and "tomorrow" in t:
            target += timedelta(days=1)
        elif target <= now:
            target += timedelta(days=1)
        return target, True
    return now, False


def set_reminder(task: str, when_str: str) -> tuple[str, bool]:
    target, ok = parse_time_natural(when_str)
    if not ok or target <= datetime.now() + timedelta(seconds=10):
        return f"Could not parse time: “{when_str}”. Try “in 5 minutes” or “tomorrow at 3pm”.", False
    reminders = load_reminders()
    rid = f"r{len(reminders) + 1}_{int(target.timestamp())}"
    reminders.append({"id": rid, "task": task, "time": target.isoformat(), "due": False})
    save_reminders(reminders)
    return f"Reminder set for {target.strftime('%I:%M %p, %A %d %b')}: “{task}”", True


def check_reminders() -> list[str]:
    reminders = load_reminders()
    now = datetime.now()
    due = []
    changed = False
    for r in reminders:
        try:
            t = datetime.fromisoformat(r["time"])
        except Exception:
            continue
        if not r.get("due") and now >= t - timedelta(minutes=1):
            r["due"] = True
            changed = True
            due.append(f"⏰ REMINDER: {r['task']} (at {t.strftime('%H:%M')})")
    if changed:
        save_reminders(reminders)
    return due


# ---------------------------------------------------------------- research/docs
def search_and_summarize(query: str, budget: int = 5) -> str:
    """Search + summarize via web_engine. Returns summary text."""
    try:
        import web_engine as webx
        d = webx.get_context(query, deep=False, budget=budget)
        if d and d.get("context"):
            return d["context"][:500]
    except Exception:
        pass
    import sys
    jarvis_dir = str(APP_DIR)
    if jarvis_dir not in sys.path:
        sys.path.insert(0, jarvis_dir)
    try:
        from jarvis_exact import search_web
        return search_web(query, 4)[:400] or "No results found."
    except Exception:
        return "Search unavailable right now."


def generate_doc(kind: str, title: str, content: str, data_dir: str = "") -> str:
    """Generate a document: pdf, docx, xlsx, txt. Returns file path."""
    files_dir = DATA_DIR / "docs"
    files_dir.mkdir(exist_ok=True)
    safe_title = re.sub(r"[^\w\-. ]", "", title)[:50] or "doc"
    try:
        if kind in ("docx", "doc"):
            import docx
            doc = docx.Document()
            doc.add_heading(title, 0)
            doc.add_paragraph(content)
            path = files_dir / f"{safe_title}.docx"
            doc.save(path)
            return str(path)
        elif kind == "xlsx":
            import openpyxl
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.append([title])
            for i, line in enumerate(content.split("\n")):
                ws.append([i + 1, line])
            path = files_dir / f"{safe_title}.xlsx"
            wb.save(path)
            return str(path)
        elif kind == "pdf":
            from PIL import Image, ImageDraw
            img = Image.new("RGB", (800, 1000), "white")
            d = ImageDraw.Draw(img)
            d.text((50, 50), title, fill="black")
            y = 80
            for line in content.split("\n")[:50]:
                d.text((50, y), line[:100], fill="black")
                y += 15
            path = files_dir / f"{safe_title}.pdf"
            img.save(path, "PDF", resolution=72.0)
            return str(path)
        else:
            path = files_dir / f"{safe_title}.txt"
            path.write_text(f"{title}\n{'=' * 60}\n\n{content}", encoding="utf-8")
            return str(path)
    except Exception:
        return ""


# ---------------------------------------------------------------- social / messages
def social_post(platform: str, content: str, recipient: str = "") -> tuple[str, bool]:
    contacts = get_contacts()
    if recipient and recipient.lower() in contacts:
        addr = contacts[recipient.lower()]
    else:
        addr = recipient or _smtp_cfg()["to_email"] or ""
    if addr:
        ok, msg = send_email(addr, f"Social post: {platform}", content)
        return msg, ok
    return f"No recipient configured for {platform}. Add contacts in Settings → Contacts.", False


def send_sms(phone_number: str, message: str) -> tuple[bool, str]:
    """Send SMS through the phone bridge; fall back to the SMTP gateway."""
    res = bridge_sms(phone_number, message)
    if res.get("ok"):
        return True, f"SMS sent to {phone_number}"
    # SMTP-to-SMS fallback
    import smtplib
    cfg = _smtp_cfg()
    if cfg["host"] and "@" not in (phone_number or ""):
        digits = re.sub(r"\D", "", phone_number or "")
        gateways = [f"{digits}@vtext.com", f"{digits}@txt.att.net",
                    f"{digits}@tmomail.net", f"{digits}@messaging.sprintpcs.com"]
        for addr in gateways[:1]:  # try the first gateway only
            try:
                with smtplib.SMTP(cfg["host"], cfg["port"], timeout=15) as s:
                    s.starttls()
                    if cfg["user"]:
                        s.login(cfg["user"], cfg["password"])
                    s.sendmail(cfg["from_email"] or cfg["user"], [addr],
                               f"{message}\n\n[From: JARVIS AI]")
                return True, f"SMS sent to {phone_number}"
            except Exception:
                break
    return False, res.get("error") or "Could not send SMS. Check Settings → Phone Bridge."


def send_message(phone_number: str, text: str) -> tuple[str, bool]:
    """Send an SMS/message: bridge first, email fallback."""
    contacts = get_contacts()
    target = contacts.get(phone_number.lower(), phone_number)
    ok, msg = send_sms(target, text)
    if ok:
        return msg, True
    cfg = _smtp_cfg()
    if cfg["to_email"]:
        ok2, msg2 = send_email(cfg["to_email"], f"Message to {phone_number}", text)
        return msg2, ok2
    return msg, False


# ---------------------------------------------------------------- dispatcher
def _result(ok: bool, message: str, intent: str, speak: bool = True) -> dict:
    return {"success": ok, "message": message, "should_speak": speak, "intent": intent}


def _orig(p: str, low: str, m, group: int) -> str:
    """Return a regex group from the ORIGINAL text (preserves case for message bodies).

    Matching runs on the lowercased copy; for ASCII input the spans line up.
    """
    try:
        return p[m.start(group):m.end(group)].strip()
    except Exception:
        return (m.group(group) or "").strip()


def dispatch_command(command: str) -> dict:
    """Main entry point. Returns {success, message, should_speak, intent}."""
    p = _clean_text(command or "").strip()
    low = p.lower()
    if not p:
        return {"success": False, "message": "", "should_speak": True}

    # ============ WhatsApp (send + call) — before generic call/text ============
    if "whatsapp" in low:
        # "call mom on whatsapp" / "whatsapp call mom" / "video call mom on whatsapp"
        m = re.match(r"^(?:make\s+)?(?:a\s+)?(?:video\s+|voice\s+)?(?:whatsapp\s+)?call\s+(.+?)\s+on\s+whatsapp$", low)
        if not m:
            m = re.match(r"^(?:whatsapp\s+)?(?:video\s+|voice\s+)?call\s+(.+?)\s+(?:on|via)\s+whatsapp$", low)
        if not m:
            m = re.match(r"^whatsapp\s+(?:video\s+|voice\s+)?call\s+(.+)$", low)
        if m:
            who = _orig(p, low, m, 1)
            num, name, err = _resolve_phone(who, whatsapp=True)
            if err:
                return _result(False, err, "whatsapp_call")
            res = bridge_whatsapp_open(num, "")
            if res.get("ok"):
                return _result(True, f"Opened WhatsApp with {name}. Tap the call icon to start the {'video ' if 'video' in low else ''}call. (Silent WhatsApp calling arrives with the Phase 4 ADB bridge.)", "whatsapp_call")
            link = f"https://wa.me/{re.sub(r'[^0-9]', '', num)}"
            return _result(False, f"{res.get('error') or 'Phone bridge not connected'}\nWhatsApp link: {link}", "whatsapp_call")
        # "send whatsapp to mom saying ..." / "whatsapp mom saying ..." / "message mom on whatsapp saying ..."
        m = re.match(r"^(?:send\s+)?(?:a\s+)?(?:whatsapp(?:\s+message)?|message|text)\s+(?:to\s+)?(.+?)\s+(?:on\s+whatsapp\s+)?(?:saying|with|that|about)\s+(.+)$", low)
        if m:
            who = _orig(p, low, m, 1)
            text = _orig(p, low, m, 2)
            num, name, err = _resolve_phone(who, whatsapp=True)
            if err:
                return _result(False, err, "whatsapp_send")
            res = bridge_whatsapp_open(num, text)
            if res.get("ok"):
                return _result(True, f"WhatsApp chat with {name} opened and your message is pre-filled — tap Send. (Silent sending needs the Phase 4 ADB bridge.)", "whatsapp_send")
            link = f"https://wa.me/{re.sub(r'[^0-9]', '', num)}?text={__import__('urllib.parse', fromlist=['quote']).quote(text)}"
            return _result(False, f"{res.get('error') or 'Phone bridge not connected'}\nWhatsApp link: {link}", "whatsapp_send")
        return {"success": False, "message": "", "should_speak": True}

    # ============ Contact info: "who is mom", "mom's number" ============
    m = re.match(r"^(?:who\s+is|who's|what(?:'s| is)\s+(?:the\s+)?(?:number|phone|email)\s+(?:of|for)|show\s+contact)\s+(.+?)\s*\??$", low)
    if not m:
        m = re.match(
            r"^(?!check|read|send|write|open|reply|search|call|text|sms|whatsapp|remind|post|generate|save|add|remember)\b"
            r"(?:what(?:'s| is)\s+)?(.+?)(?:'s)?\s+(?:number|phone|email|contact)\s*\??$",
            low,
        )
    if m:
        who = _orig(p, low, m, 1)
        try:
            import contacts_engine as ce
            res = ce.resolve(who)
            if res.get("ambiguous"):
                names = ", ".join(ce.describe(c) for c in res.get("candidates", [])[:3])
                return _result(False, f"Which one — {names}?", "contact_info")
            c = res.get("contact")
            if not c:
                return _result(False, f"I couldn't find “{who}” in your contacts.", "contact_info")
            bits = [ce.describe(c)]
            if c.get("email"):
                bits.append(f"email {c['email']}")
            return _result(True, " — ".join(bits) + ".", "contact_info")
        except Exception:
            return {"success": False, "message": "", "should_speak": True}

    # ============ Normal calls ============
    m = re.match(r"^(?:call|dial|ring|phone)\s+(?:up\s+)?(?:my\s+|our\s+)?(.+?)(?:\s+on\s+(?:speaker|phone))?$", low)
    if m:
        who = re.sub(r"'s\s+(?:number|phone|mobile)$", "", _orig(p, low, m, 1), flags=re.I)
        num, name, err = _resolve_phone(who, whatsapp=False)
        if err:
            return _result(False, err, "call")
        res = bridge_call(num)
        if res.get("ok"):
            return _result(True, f"Calling {name} at {num}…", "call")
        return _result(False, f"{res.get('error') or 'Phone bridge not connected'}\nDial manually: {num}", "call")

    # ============ SMS / text ============
    m = re.match(r"^(?:text|sms|send\s+(?:an?\s+)?sms\s+to)\s+(.+?)\s+(?:saying|with|that|about)\s+(.+)$", low)
    if m:
        who = _orig(p, low, m, 1)
        text = _orig(p, low, m, 2)
        num, name, err = _resolve_phone(who, whatsapp=False)
        if err:
            return _result(False, err, "sms")
        res = bridge_sms(num, text)
        if res.get("ok"):
            return _result(True, f"SMS sent to {name} ({num}).", "sms")
        return _result(False, f"{res.get('error') or 'Phone bridge not connected'}\nNumber: {num}", "sms")

    # ============ Email send (contact-aware) ============
    m = re.match(r"^(?:send|write)?\s*(?:an?\s+)?(?:email|mail)\s+(?:to\s+|for\s+)?(.+?)\s+(?:saying|with|that|about)\s+(.+)$", low)
    if m:
        who = _orig(p, low, m, 1).rstrip(".")
        body = _orig(p, low, m, 2).rstrip(".")
        if "@" in who:
            addr = who
        else:
            c, clarify = _resolve_contact(who)
            if clarify:
                return _result(False, clarify, "email_send")
            if not c or not (c.get("email") or "").strip():
                return _result(False, f"I couldn't find an email address for “{who}”. Add it in Settings → Contacts.", "email_send")
            addr = c["email"]
        ok, msg = send_email(addr, "Message from JARVIS", body)
        return _result(ok, msg, "email_send")

    # ============ Check / read messages ============
    if re.match(r"^(?:check|read|any|do\s+i\s+have)\s+(?:my\s+)?messages\b", low):
        parts = []
        em = email_summary(limit=5)
        parts.append("Email: " + (em["text"] if em["ok"] else em["text"]))
        sms = bridge_sms_list(limit=5)
        if sms.get("ok"):
            items = sms.get("items") or []
            unread = [i for i in items if not i.get("read")]
            if items:
                parts.append("SMS: " + " | ".join(f"{(i.get('name') or i.get('number'))}: {str(i.get('body') or '')[:70]}" for i in items[:3]))
            else:
                parts.append("SMS: none.")
        else:
            parts.append("SMS: " + str(sms.get("error") or "phone bridge not connected"))
        wa = bridge_notifications(limit=10)
        if wa.get("ok"):
            msgs = wa.get("messages") or []
            if msgs:
                parts.append("WhatsApp: " + " | ".join(f"{m.get('from')}: {str(m.get('text') or '')[:70]}" for m in msgs[:3]))
            else:
                parts.append("WhatsApp: no new notifications.")
        else:
            parts.append("WhatsApp: " + str(wa.get("error") or "phone bridge not connected"))
        return _result(True, "\n".join(parts), "check_messages")

    if re.match(r"^(?:check|any|do\s+i\s+have)\s+(?:my\s+|new\s+|unread\s+)?(?:e-?mails?|inbox|mail)\b", low):
        em = email_summary(limit=5)
        return _result(em["ok"], em["text"], "check_email")

    m = re.match(r"^(?:read|open)\s+(?:the\s+)?(first|latest|last|\d+(?:st|nd|rd|th)?)\s+(?:e-?mail|message)$", low)
    if m:
        word = m.group(1)
        idx = 1
        if word.isdigit():
            idx = int(word)
        elif word.startswith(("last", "latest")):
            idx = len(_last_emails()) or 1
        return _result(True, read_email(idx), "read_email")

    if re.match(r"^(?:read)\s+(?:my\s+|the\s+)?(?:e-?mails?|inbox|messages)\b", low):
        items = _last_emails()
        if not items:
            em = email_summary(limit=3)
            return _result(em["ok"], em["text"], "read_email")
        text = "\n\n".join(f"From {it['from']} — {it['subject']}:\n{it['snippet']}" for it in items[:3])
        return _result(True, text, "read_email")

    m = re.match(r"^reply(?:\s+to)?(?:\s+that|\s+the\s+last)?\s+(?:e-?mail)\s+(?:saying\s+|with\s+)?(.+)$", low)
    if m:
        ok, msg = reply_last_email(_orig(p, low, m, 1))
        return _result(ok, msg, "email_reply")

    # ============ Contact save by voice ============
    m = re.match(r"^(?:save|add|remember)\s+(?:contact\s+)?(.+?)(?:'s)?\s+(?:number|phone|mobile|whatsapp|email)\s+(?:is|as|=)\s+(.+)$", low)
    if m:
        who = _orig(p, low, m, 1)
        val = _orig(p, low, m, 2).rstrip(".")
        try:
            import contacts_engine as ce
            field = "email" if ("@" in val or "email" in low) else ("whatsapp" if "whatsapp" in low else "phone")
            saved = ce.upsert_contact({"name": who.title(), field: val})
            return _result(True, f"Saved {saved.get('name')} — {field} {val}.", "contact_save")
        except Exception as e:
            return _result(False, f"Could not save contact: {e}", "contact_save")

    # ============ Reminders ============
    m = re.match(r"^remind\s+(?:me\s+)?(?:to\s+|about\s+|that\s+)?(.+?)\s+(?:at|in|on)\s+(.+)$", low)
    if m:
        msg, ok = set_reminder(_orig(p, low, m, 1), _orig(p, low, m, 2))
        return _result(ok, msg, "reminder")

    # ============ Research ============
    m = re.match(r"^search\s+(?:for\s+)?(?:and\s+summarize\s+|summarize)?(.+)$", low)
    if m:
        query = _orig(p, low, m, 1)
        summary = search_and_summarize(query)
        return _result(True, f"Search results for '{query}':\n\n{summary}", "search", speak=False)

    # ============ Documents ============
    m = re.match(r"^(?:generate|write)\s+(?:a\s+)?(docx|doc|xlsx|pdf|txt)\s+(?:file\s+)?(?:titled\s+|called\s+|named\s+)?['\"]?(.+?)['\"]?$", low)
    if m:
        kind = m.group(1)
        title = _orig(p, low, m, 2) or f"document-{int(time.time())}"
        content = f"Generated by JARVIS on {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n{title}"
        path = generate_doc(kind, title, content)
        return _result(bool(path), f"Created document: {path}" if path else "Failed to create document.", "document")

    # ============ Social ============
    m = re.match(r"^post\s+(?:on|to)\s+(twitter|x|linkedin|facebook)\s+(?:saying\s+|content:\s+)?(.+)$", low)
    if m:
        msg, ok = social_post(m.group(1).lower(), _orig(p, low, m, 2))
        return _result(ok, msg, "social_post")

    # ============ Generic message (SMS bridge / email fallback) ============
    m = re.match(r"^(?:send\s+)?message\s+(?:to\s+)?(.+?)\s+(?:saying\s+)?(.+)$", low)
    if m:
        who = _orig(p, low, m, 1).rstrip(".")
        text = _orig(p, low, m, 2)
        num, name, err = _resolve_phone(who, whatsapp=False)
        if not err and num:
            res = bridge_sms(num, text)
            if res.get("ok"):
                return _result(True, f"Message sent to {name}.", "message")
            return _result(False, f"{res.get('error') or 'Phone bridge not connected'}\nNumber: {num}", "message")
        msg, ok = send_message(who, text)
        return _result(ok, msg, "message")

    # ============ Open files ============
    m = re.match(r"^open\s+(?:document|report|spreadsheet|file)\s+(.+?)\b", low)
    if m:
        file_ref = m.group(1).strip()
        for sp in (DATA_DIR / file_ref, DATA_DIR / "docs" / file_ref):
            if sp.exists():
                try:
                    os.startfile(str(sp))
                    return _result(True, f"Opened {sp.name}", "open_file")
                except Exception as e:
                    return _result(False, f"Could not open {sp.name}: {e}", "open_file")
        return _result(False, f"File not found: {file_ref}", "open_file")

    return {"success": False, "message": "", "should_speak": True}


# ---------------------------------------------------------------- email drafts
def draft_email_reply(original: str) -> str:
    """Generate a draft reply for an email body."""
    try:
        from jarvis_exact import DEFAULT, call_or
        api_key = ""
        from jarvis_exact import _server_key_from_env_file
        api_key = _server_key_from_env_file()
    except Exception:
        api_key = ""
    if not api_key:
        return "Reply draft unavailable (no API key configured)."
    try:
        msgs = [
            {"role": "system", "content": "You are JARVIS. Draft a brief, professional email reply to the following email body. Return ONLY the reply text."},
            {"role": "user", "content": original[:2000]},
        ]
        reply, err = call_or(api_key, DEFAULT, msgs, 0.2, 300)
        return reply or "Could not generate draft."
    except Exception:
        return "Could not generate draft."


def summarize_document(path: str, max_len: int = 400) -> str:
    """Summarize a document file (DOCX, PDF, TXT)."""
    path = Path(path)
    try:
        content = ""
        if path.suffix.lower() in (".txt", ".md", ".csv"):
            content = path.read_text(errors="ignore")[:2000]
        elif path.suffix.lower() == ".docx":
            import docx
            d = docx.Document(path)
            content = "\n".join(p.text for p in d.paragraphs)[:2000]
        elif path.suffix.lower() == ".pdf":
            import subprocess
            r = subprocess.run(["pdftotext", str(path), "-"], capture_output=True, text=True, timeout=10)
            content = (r.stdout or "")[:2000]
        if content.strip():
            try:
                import web_engine as webx
                result = webx.summarize_text(content[:2000], path.name) if hasattr(webx, "summarize_text") else ""
            except Exception:
                result = ""
            if result:
                return result[:max_len]
            return content[:max_len]
    except Exception:
        pass
    return f"Could not read {path.name}"


# ---------------------------------------------------------------- reference
SMS_GATEWAYS = {
    "verizon": "vtext.com",
    "att": "txt.att.net",
    "t-mobile": "tmomail.net",
    "sprint": "messaging.sprintpcs.com",
    "virgin": "vmobl.com",
}


if __name__ == "__main__":
    print("Automation engine loaded")
    print(f"Data dir: {DATA_DIR}")
    print(f"Reminders: {len(load_reminders())}")
    print(f"SMTP config: {_smtp_cfg()['host'] or 'not set'}")
    print(f"IMAP config: {_imap_cfg()['user'] or 'not set'}")
    print(f"Phone bridge: {_bridge_cfg()['url'] or 'not set'}")
