"""JARVIS Automation Engine — Phase 2 + Phase 3

Features:
- Email (SMTP) — send emails with natural voice commands
- Calendar & Reminders — local reminder system with scheduling
- Research & Docs — web search + file summarization + document generation
- Documents — PDFs, DOCX, Excel, Sheets
- Social Posting — SMTP-based posts
- Messages — SMS via SMTP gateways

Commands (all work via natural voice on mobile):
- "send email to [name] saying [text]"
- "remind me [task] at [time]" / "in [minutes] minutes"
- "search [query] and summarize"
- "open document" / "write to file"
"""
import os
import re
import json
import time
import threading
import tempfile
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Optional

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# ---------------- SMTP Config ----------------
SMTP_CONFIG = {
    "host": os.getenv("SMTP_HOST", ""),
    "port": int(os.getenv("SMTP_PORT", "587")),
    "user": os.getenv("SMTP_USER", ""),
    "password": os.getenv("SMTP_PASSWORD", ""),
    "from_email": os.getenv("SMTP_FROM", ""),
    "to_email": os.getenv("SMTP_TO", ""),
}

# ---------------- Contacts (from user profile or .env) ----------------
def get_contacts() -> dict:
    """Load email/phone contacts from user_profile + contacts.json"""
    contacts = {}
    try:
        import memory_engine as mem
        p = mem.load_user_profile() if mem else {}
        if p.get("preferences"):
            for line in p["preferences"].split(". "):
                m = re.search(r"(\w[\w.\-+_]*)\s*[:=]\s*([\w.\-+_]+@[\w.]+)", line)
                if m:
                    contacts[m.group(1).lower()] = m.group(2)
    except Exception:
        pass
    # contacts.json for sms/social
    cj = DATA_DIR / "contacts.json"
    if cj.exists():
        try:
            extra = json.loads(cj.read_text())
            contacts.update(extra)
        except Exception:
            pass
    return contacts


# ---------------- SMTP Email ----------------
def send_email(to_email: str, subject: str, body: str, cc: list = None) -> tuple[bool, str]:
    """Send an email via SMTP. Returns (success, message)."""
    import smtplib
    from email.message import EmailMessage
    try:
        msg = EmailMessage()
        msg["From"] = SMTP_CONFIG["from_email"] or "jarvis@localhost"
        msg["To"] = to_email
        if SMTP_CONFIG["user"]:
            msg["From"] = SMTP_CONFIG["user"]
        msg["Subject"] = subject
        msg.set_content(body)
        if cc:
            msg["Cc"] = ", ".join(cc)
        if SMTP_CONFIG["host"]:
            with smtplib.SMTP(SMTP_CONFIG["host"], SMTP_CONFIG["port"], timeout=15) as s:
                s.starttls()
                if SMTP_CONFIG["user"]:
                    s.login(SMTP_CONFIG["user"], SMTP_CONFIG["password"])
                s.send_message(msg)
            return True, f"Email sent to {to_email}"
        else:
            return False, "No SMTP configured. Add SMTP_HOST/USER/PASSWORD to .env."
    except Exception as e:
        return False, f"Email failed: {e}"


def send_sms(phone_number: str, message: str) -> tuple[bool, str]:
    """Send SMS via SMTP-to-SMS gateway or Twilio (if configured)."""
    # Try SMTP-based SMS first (common gateways: ...@vtext.com, @txt.att.net, etc.)
    gateways = {
        "verizon": f"{_digits(phone_number)}@vtext.com",
        "att": f"{_digits(phone_number)}@txt.att.net",
        "tmobile": f"{_digits(phone_number)}@tmomail.net",
        "sprint": f"{_digits(phone_number)}@messaging.sprintpcs.com",
        "virgin": f"{_digits(phone_number)}@vmobl.com",
    }
    try:
        import smtplib
        if SMTP_CONFIG["host"]:
            with smtplib.SMTP(SMTP_CONFIG["host"], SMTP_CONFIG["port"], timeout=15) as s:
                s.starttls()
                if SMTP_CONFIG["user"]:
                    s.login(SMTP_CONFIG["user"], SMTP_CONFIG["password"])
                s.sendmail(
                    SMTP_CONFIG["from_email"] or "jarvis@localhost",
                    [phone_number],
                    f"{message}\n\n[From: JARVIS AI]",
                )
            return True, f"SMS sent to {phone_number}"
    except Exception:
        pass
    return False, "Could not send SMS. Add SMTP config or Twilio."


def _digits(phone: str) -> str:
    """Extract digits from phone number."""
    return re.sub(r"\D", "", phone or "")


# ---------------- Calendar & Reminders ----------------
REMINDER_FILE = DATA_DIR / "reminders.json"


def load_reminders() -> list:
    if REMINDER_FILE.exists():
        try:
            return json.loads(REMINDER_FILE.read_text())
        except Exception:
            pass
    return []


def save_reminders(items: list) -> None:
    REMINDER_FILE.write_text(json.dumps(items, indent=2))


def _clean_text(s: str) -> str:
    """Normalize smart quotes/apostrophes for regex matching."""
    if not s:
        return ""
    return (s.replace("\u201c", "").replace("\u201d", "")
             .replace("\u2018", "").replace("\u2019", "")
             .replace("\u2014", " ").replace("\u2013", "-")
             .replace("\u2026", "...")
             .strip())


def parse_time_natural(text: str) -> tuple[datetime, bool]:
    """Parse natural time expressions: 'in 5 minutes', 'at 3pm', 'tomorrow 2pm'."""
    t = _clean_text(text).lower().strip()
    now = datetime.now()
    # "in X minutes/hours" or "after X minutes"
    m = re.search(r"(?:in|after)\s+(\d+)\s*(minute?s?|hour?s?|min|hr)", t)
    if m:
        n = int(m.group(1))
        unit = m.group(2).rstrip("s")
        if unit.startswith("hr"):
            return now + timedelta(hours=n), True
        return now + timedelta(minutes=n), True
    # "X minutes" or "X hours" alone
    m = re.search(r"(\d+)\s*(minutes?|min|hours?|hr)$", t)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if unit.startswith("hr"):
            return now + timedelta(hours=n), True
        return now + timedelta(minutes=n), True
    # "at 3pm" or "at 3:30pm" or "3pm"
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
        elif target <= now and "today" in t:
            target += timedelta(days=1)
        return target, True
    # "at 3:30pm"
    m = re.search(r"at\s+(\d{1,2}):(\d{2})\s*(am|pm)?", t)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2))
        ampm = (m.group(3) or "pm").lower()
        if ampm == "am" and hour == 12:
            hour = 0
        elif ampm == "pm" and hour != 12:
            hour += 12
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target, True
    return now, False


def set_reminder(task: str, when_str: str) -> tuple[str, bool]:
    """Set a reminder. Returns (message, success)."""
    target, ok = parse_time_natural(when_str)
    if not ok or target <= datetime.now() + timedelta(seconds=10):
        return f"Could not parse time: “{when_str}”. Try “in 5 minutes” or “tomorrow at 3pm”.", False
    reminders = load_reminders()
    rid = f"r{len(reminders)+1}_{int(target.timestamp())}"
    reminders.append({"id": rid, "task": task, "time": target.isoformat(), "due": False})
    save_reminders(reminders)
    return f"Reminder set for {target.strftime('%I:%M %p, %A %d %b')}: “{task}”", True


def check_reminders() -> list[str]:
    """Return list of due-but-unshown reminders."""
    reminders = load_reminders()
    now = datetime.now()
    due = []
    changed = False
    for r in reminders:
        try:
            t = datetime.fromisoformat(r["time"])
        except Exception:
            continue
        if not r["due"] and now >= t - timedelta(minutes=1):
            r["due"] = True
            changed = True
            due.append(f"⏰ REMINDER: {r['task']} (at {t.strftime('%H:%M')})")
    if changed:
        save_reminders(reminders)
    return due


# ---------------- Research & Documents ----------------
def search_and_summarize(query: str, budget: int = 5) -> str:
    """Search + summarize via web_engine. Returns summary text."""
    try:
        import web_engine as webx
        d = webx.get_context(query, deep=False, budget=budget)
        if d and d.get("context"):
            return d["context"][:500]
    except Exception:
        pass
    # Fallback: web_search + summarize
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
            lines = content.split("\n")
            for i, line in enumerate(lines):
                ws.append([i + 1, line])
            path = files_dir / f"{safe_title}.xlsx"
            wb.save(path)
            return str(path)
        elif kind == "pdf":
            # Use wkhtmltopdf or pandoc if available, else text file
            path = files_dir / f"{safe_title}.pdf"
            # Simple text-to-PDF via fpdf is not installed; use PIL + custom render
            from PIL import Image, ImageDraw, ImageFont
            img = Image.new("RGB", (800, 1000), "white")
            d = ImageDraw.Draw(img)
            d.text((50, 50), title, fill="black")
            y = 80
            for line in content.split("\n")[:50]:
                d.text((50, y), line[:100], fill="black")
                y += 15
            img.save(path, "PDF", resolution=72.0)
            return str(path)
        else:  # txt or default
            path = files_dir / f"{safe_title}.txt"
            path.write_text(f"{title}\n{'='*60}\n\n{content}", encoding="utf-8")
            return str(path)
    except Exception:
        return ""


# ---------------- Social Posting ----------------
def social_post(platform: str, content: str, recipient: str = "") -> tuple[str, bool]:
    """Post to social media. Uses email-based posting or API if available."""
    if recipient and recipient in get_contacts():
        addr = get_contacts()[recipient]
    else:
        addr = recipient or SMTP_CONFIG["to_email"] or ""
    if addr:
        ok, msg = send_email(addr, f"Social post: {platform}", content)
        return msg, ok
    return f"No recipient configured for {platform}. Add contacts to contacts.json or use SMTP.", False


# ---------------- Messages ----------------
def send_message(phone_number: str, text: str) -> tuple[str, bool]:
    """Send a message via SMS gateway or email."""
    contacts = get_contacts()
    if phone_number.lower() in contacts:
        phone_number = contacts[phone_number.lower()]
    ok, msg = send_sms(phone_number, text)
    if ok:
        return msg, True
    # Fallback: email message
    if SMTP_CONFIG["to_email"]:
        ok, msg = send_email(SMTP_CONFIG["to_email"], f"Message to {phone_number}", text)
        return msg, ok
    return "No SMS gateway configured. Set up contacts or SMTP.", False


# ---------------- Main dispatcher ----------------
def dispatch_command(command: str) -> dict:
    """
    Main entry point for automation commands.
    Returns: {"success": bool, "message": str, "should_speak": bool}
    """
    p = _clean_text(command).lower()
    result = {"success": False, "message": "", "should_speak": True}

    # --- Email ---
    m = re.match(r"^(?:send|write)?\s*(?:an?\s+)?(?:email|mail)\s+(?:to|for)\s+(.+?)\s+(?:saying|with|that|about)\s+(.+)$", p, re.I)
    if m:
        who = m.group(1).strip().rstrip(".")
        body = m.group(2).strip().rstrip(".")
        contacts = get_contacts()
        email = contacts.get(who.lower(), "")
        if not email and "@" not in who:
            email = f"{who.replace(' ', '.')}@example.com"  # guess
        ok, msg = send_email(email, "From JARVIS", body)
        result.update({"success": ok, "message": msg})
        return result

    # --- Reminders ---
    m = re.match(r"^remind\s+(?:me\s+)?(?:to\s+|about\s+|that\s+)?(.+?)\s+(?:at|in|on)\s+(.+)$", p)
    if m:
        task = m.group(1).strip()
        when = m.group(2).strip()
        msg, ok = set_reminder(task, when)
        result.update({"success": ok, "message": msg})
        return result

    # --- Research ---
    m = re.match(r"^search\s+(?:for\s+)?(?:and\s+summarize\s+|summarize)?(.+)$", p)
    if m:
        query = m.group(1).strip()
        summary = search_and_summarize(query)
        result.update({"success": True, "message": f"Search results for '{query}':\n\n{summary}", "should_speak": False})
        return result

    # --- Documents ---
    m = re.match(r"^(?:generate|write)\s+(?:a\s+)?(docx|doc|xlsx|pdf|txt)\s+(?:file\s+)?(?:titled\s+|called\s+|named\s+)?['\"]?(.+?)['\"]?$", p, re.I)
    if m:
        kind = m.group(1)
        title = m.group(2).strip() or f"document-{int(time.time())}"
        content = f"Generated by JARVIS on {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n{title}"
        path = generate_doc(kind, title, content)
        result.update({"success": bool(path), "message": f"Created document: {path}" if path else "Failed to create document."})
        return result

    # --- Social Posting ---
    m = re.match(r"^post\s+(?:on|to)\s+(twitter|x|linkedin|facebook)\s+(?:saying\s+|content:\s+)?(.+)$", p)
    if m:
        platform = m.group(1).lower()
        content = m.group(2).strip()
        msg, ok = social_post(platform, content)
        result.update({"success": ok, "message": msg})
        return result

    # --- Messages ---
    m = re.match(r"^(?:send\s+)?message\s+to\s+(\S+)\s+(?:saying\s+)?(.+)$", p)
    if m:
        who = m.group(1).strip().rstrip(".")
        text = m.group(2).strip()
        msg, ok = send_message(who, text)
        result.update({"success": ok, "message": msg})
        return result

    # --- Business automation ---
    # "run google sheets query", "open document", etc.
    m = re.match(r"^open\s+(?:document|report|spreadsheet|file)\s+(.+?)\b", p)
    if m:
        file_ref = m.group(1).strip()
        # Find file in data dir
        search_paths = [DATA_DIR / file_ref, DATA_DIR / "docs" / file_ref]
        for sp in search_paths:
            if sp.exists():
                os.startfile(str(sp))
                result.update({"success": True, "message": f"Opened {sp.name}"})
                return result
        result.update({"success": False, "message": f"File not found: {file_ref}"})
        return result

    return result


# ---------------- Email drafts ----------------
def draft_email_reply(original: str) -> str:
    """Generate a draft reply for an email body."""
    from jarvis_exact import call_or, DEFAULT
    try:
        import streamlit as st
        api_key = ""
        # Try to get key without full app context
        from jarvis_exact import _server_key_from_env_file
        api_key = _server_key_from_env_file()
    except Exception:
        pass
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
            # Use web_engine for summarization
            import web_engine as webx
            result = webx.summarize_text(content[:2000], path.name) if hasattr(webx, "summarize_text") else ""
            if result:
                return result[:max_len]
            return content[:max_len]
    except Exception:
        pass
    return f"Could not read {path.name}"


# ---------------- SMS gateway table (for quick reference) ----------------
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
    print(f"SMTP config: {SMTP_CONFIG['host'] or 'not set'}")
