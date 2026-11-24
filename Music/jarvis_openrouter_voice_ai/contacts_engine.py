"""JARVIS Contacts Engine — Phase 1: smart contacts + fuzzy name resolution.

Features
- Contact store in data/contacts.json (name, aliases, relationship, phone, whatsapp, email)
- Google Contacts CSV import (old + new export formats)
- Fuzzy resolver: plurals ("moms" -> "mom"), relationship synonyms
  ("aunty"/"aunt"/"aunties"), Indian-English phonetics ("sireesha" ~ "shireesha"),
  difflib scoring, ambiguity detection and learned aliases.
- Backward compatible with the old flat {name: email} contacts.json format.

The resolver is used by automation_engine for calls, SMS, WhatsApp and email so the
same understanding works on phone and laptop (it runs server-side).
"""
from __future__ import annotations

import csv
import io
import json
import re
import uuid
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Optional

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
CONTACTS_FILE = DATA_DIR / "contacts.json"

# Canonical relationship -> spoken variants (lowercase, singular/plural handled too)
RELATION_GROUPS: dict[str, set[str]] = {
    "mother": {"mom", "mommy", "mommie", "mum", "mummy", "mother", "amma", "maa", "ma", "mata", "aai", "momma"},
    "father": {"dad", "daddy", "papa", "father", "appa", "abba", "baba", "baap"},
    "aunty": {"aunty", "aunt", "auntie", "aunties", "aunts", "maasi", "masi", "chachi", "pinni", "attha", "mavshi"},
    "uncle": {"uncle", "uncles", "uncleji", "chacha", "mama", "kaka", "mausa"},
    "sister": {"sister", "sisters", "sis", "didi", "akka", "chechi", "behen"},
    "brother": {"brother", "brothers", "bro", "bhai", "anna", "bhaiya"},
    "wife": {"wife", "spouse", "biwi", "patni"},
    "husband": {"husband", "spouse", "pati"},
    "son": {"son", "beta", "babu"},
    "daughter": {"daughter", "beti"},
    "friend": {"friend", "friends", "buddy", "yaar", "dost"},
    "boss": {"boss", "manager"},
    "doctor": {"doctor", "dr"},
}

_REL_LOOKUP: dict[str, str] = {}
for _rel, _words in RELATION_GROUPS.items():
    for _w in _words:
        _REL_LOOKUP[_w] = _rel

_FILLER_WORDS = {"my", "our", "the", "a", "an", "to", "please", "contact", "number", "phone", "mobile", "whatsapp"}

DEFAULT_COUNTRY_CODE = "91"  # India


# ---------------------------------------------------------------- utilities
def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = s.replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", "").replace("\u201d", "")
    s = re.sub(r"[^a-z0-9@+.\- ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _singular(word: str) -> str:
    w = (word or "").strip().lower()
    if len(w) <= 3:
        return w
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith(("ses", "xes", "zes", "ches", "shes")):
        return w[:-2]
    if w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def relationship_of(word: str) -> str:
    w = _norm(word)
    if not w:
        return ""
    return _REL_LOOKUP.get(w) or _REL_LOOKUP.get(_singular(w), "")


def phonetic_key(s: str) -> str:
    """Simple Indian-English tolerant phonetic key (sireesha ~ shireesha)."""
    t = re.sub(r"[^a-z]", "", _norm(s))
    if not t:
        return ""
    t = (t.replace("ph", "f").replace("sh", "s").replace("ch", "c")
          .replace("kh", "k").replace("gh", "g").replace("bh", "b")
          .replace("dh", "d").replace("jh", "j").replace("th", "t"))
    t = (t.replace("ee", "i").replace("oo", "u").replace("aa", "a")
          .replace("ai", "e").replace("au", "o").replace("ou", "o"))
    t = re.sub(r"(.)\1+", r"\1", t)
    if len(t) > 3 and t.endswith(("a", "h")):
        t = t[:-1]
    return t


def clean_query(query: str) -> str:
    """Normalize a spoken name: drop fillers/possessives, singularize relationship words."""
    q = _norm(query).replace("'s", " ")
    toks = [t for t in q.split() if t not in _FILLER_WORDS]
    out = []
    for t in toks:
        rel = relationship_of(t)
        out.append(rel if rel else t)
    return " ".join(out).strip()


def normalize_phone(p: str, default_cc: str = "") -> str:
    """Return a dialable number. 10-digit local numbers get the default country code."""
    raw = (p or "").strip()
    if not raw:
        return ""
    has_plus = raw.startswith("+")
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return ""
    if has_plus:
        return "+" + digits
    cc = (default_cc or DEFAULT_COUNTRY_CODE or "").strip()
    if len(digits) == 10 and cc:
        return f"+{cc}{digits}"
    if len(digits) > 10:
        return "+" + digits
    return digits


# ---------------------------------------------------------------- store
def _empty_store() -> dict:
    return {"contacts": [], "learned": {}}


def load_store() -> dict:
    """Load the contact store, migrating the legacy flat {name: email} format."""
    if not CONTACTS_FILE.exists():
        return _empty_store()
    try:
        data = json.loads(CONTACTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return _empty_store()
    if isinstance(data, dict) and "contacts" in data:
        data.setdefault("learned", {})
        if not isinstance(data.get("contacts"), list):
            data["contacts"] = []
        return data
    if isinstance(data, dict):  # legacy flat map
        contacts = []
        for name, val in data.items():
            if not isinstance(val, str):
                continue
            c = {"id": f"c_{uuid.uuid4().hex[:8]}", "name": str(name), "aliases": [],
                 "relationship": "", "phone": "", "whatsapp": "", "email": ""}
            if "@" in val:
                c["email"] = val
            else:
                c["phone"] = val
            contacts.append(c)
        return {"contacts": contacts, "learned": {}}
    if isinstance(data, list):
        return {"contacts": [c for c in data if isinstance(c, dict)], "learned": {}}
    return _empty_store()


def save_store(store: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    CONTACTS_FILE.write_text(json.dumps(store, indent=2, ensure_ascii=False), encoding="utf-8")


def list_contacts() -> list[dict]:
    return sorted(load_store().get("contacts", []), key=lambda c: (c.get("name") or "").lower())


def get_contact(contact_id: str) -> Optional[dict]:
    for c in load_store().get("contacts", []):
        if c.get("id") == contact_id:
            return c
    return None


def upsert_contact(data: dict, contact_id: str = "") -> dict:
    """Add or update a contact. Returns the saved contact."""
    store = load_store()
    contacts = store.setdefault("contacts", [])
    cid = contact_id or data.get("id") or f"c_{uuid.uuid4().hex[:8]}"
    existing = next((c for c in contacts if c.get("id") == cid), None)

    aliases = data.get("aliases") or []
    if isinstance(aliases, str):
        aliases = [a.strip() for a in re.split(r"[,;]", aliases) if a.strip()]
    rel = _norm(data.get("relationship") or "")
    rel = relationship_of(rel) or rel

    rec = existing or {"id": cid, "name": "", "aliases": [], "relationship": "", "phone": "", "whatsapp": "", "email": ""}
    for key in ("name", "phone", "whatsapp", "email"):
        if data.get(key) is not None:
            rec[key] = str(data.get(key) or "").strip()
    if data.get("relationship") is not None:
        rec["relationship"] = rel
    if data.get("aliases") is not None:
        merged = []
        for a in list(rec.get("aliases") or []) + list(aliases):
            a = str(a).strip()
            if a and a.lower() not in {m.lower() for m in merged}:
                merged.append(a)
        rec["aliases"] = merged
    if existing is None:
        contacts.append(rec)
    save_store(store)
    return rec


def delete_contact(contact_id: str) -> bool:
    store = load_store()
    before = len(store.get("contacts", []))
    store["contacts"] = [c for c in store.get("contacts", []) if c.get("id") != contact_id]
    learned = store.get("learned", {})
    store["learned"] = {k: v for k, v in learned.items() if v != contact_id}
    save_store(store)
    return len(store["contacts"]) < before


def learn_alias(query: str, contact_id: str) -> None:
    q = clean_query(query)
    if not q or not contact_id:
        return
    store = load_store()
    store.setdefault("learned", {})[q] = contact_id
    save_store(store)


# ---------------------------------------------------------------- resolver
def _contact_names(c: dict) -> list[str]:
    names = [c.get("name") or ""]
    names.extend(c.get("aliases") or [])
    rel = _norm(c.get("relationship") or "")
    if rel:
        names.append(rel)
    return [n for n in names if n]


def _score(query: str, c: dict) -> tuple[float, str]:
    q = clean_query(query)
    if not q:
        return 0.0, ""
    q_tokens = q.split()
    best, method = 0.0, ""

    for n in _contact_names(c):
        nn = clean_query(n)
        if not nn:
            continue
        if q == nn:
            return 1.0, "exact"
        if nn in q_tokens:  # "aunty shireesha" contains "shireesha"
            best, method = max(best, 0.96), "token"
        # Exact first name of a longer name ("sireesha" vs "Sireesha Rao") is a
        # strong signal but should stay close to phonetic matches so ambiguity
        # detection can ask before dialing the wrong person.
        if nn.split() and q == nn.split()[0]:
            if 0.95 > best:
                best, method = 0.95, "first-name"
        ratio = SequenceMatcher(None, q, nn).ratio()
        if ratio > best:
            best, method = ratio, "fuzzy"
        pk_q, pk_n = phonetic_key(q), phonetic_key(nn)
        if pk_q and pk_n:
            pr = SequenceMatcher(None, pk_q, pk_n).ratio()
            if pr * 0.98 > best:
                best, method = pr * 0.98, "phonetic"

    # Relationship-only queries ("mom", "aunty")
    rel = _norm(c.get("relationship") or "")
    if rel and len(q_tokens) <= 2:
        rel_words = RELATION_GROUPS.get(rel, {rel}) | {rel}
        if any(t in rel_words for t in q_tokens):
            score = 0.92 if len(q_tokens) == 1 else 0.88
            if score > best:
                best, method = score, "relationship"

    return best, method


def resolve(query: str, threshold: float = 0.72) -> dict:
    """Resolve a spoken name to a contact.

    Returns {contact, confidence, method, candidates, ambiguous}.
    """
    store = load_store()
    contacts = store.get("contacts", [])
    learned = store.get("learned", {})
    q = clean_query(query)

    if not q:
        return {"contact": None, "confidence": 0.0, "method": "", "candidates": [], "ambiguous": False}

    # Exact learned alias wins
    if q in learned:
        c = next((x for x in contacts if x.get("id") == learned[q]), None)
        if c:
            return {"contact": c, "confidence": 1.0, "method": "learned", "candidates": [c], "ambiguous": False}

    scored: list[tuple[float, str, dict]] = []
    for c in contacts:
        s, m = _score(q, c)
        if s >= threshold:
            scored.append((s, m, c))
    scored.sort(key=lambda x: -x[0])

    if not scored:
        return {"contact": None, "confidence": 0.0, "method": "", "candidates": [], "ambiguous": False}

    top_score, top_method, top_contact = scored[0]
    ambiguous = (
        len(scored) > 1
        and (top_score - scored[1][0]) < 0.06
        and scored[1][0] >= threshold
        and scored[1][2].get("id") != top_contact.get("id")
    )
    return {
        "contact": top_contact,
        "confidence": round(top_score, 3),
        "method": top_method,
        "candidates": [s[2] for s in scored[:5]],
        "ambiguous": ambiguous,
    }


def describe(contact: dict) -> str:
    if not contact:
        return ""
    bits = [contact.get("name") or "Unknown"]
    if contact.get("relationship"):
        bits.append(f"({contact['relationship']})")
    if contact.get("phone") or contact.get("whatsapp"):
        bits.append(contact.get("whatsapp") or contact.get("phone") or "")
    return " ".join(b for b in bits if b)


def phone_for(contact: dict, prefer_whatsapp: bool = False) -> str:
    if not contact:
        return ""
    if prefer_whatsapp and contact.get("whatsapp"):
        return normalize_phone(contact["whatsapp"])
    return normalize_phone(contact.get("phone") or contact.get("whatsapp") or "")


def whatsapp_for(contact: dict) -> str:
    if not contact:
        return ""
    return normalize_phone(contact.get("whatsapp") or contact.get("phone") or "")


def email_for(contact: dict) -> str:
    return (contact.get("email") or "").strip() if contact else ""


def find_by_email(email: str) -> Optional[dict]:
    e = (email or "").strip().lower()
    if not e:
        return None
    for c in load_store().get("contacts", []):
        if (c.get("email") or "").strip().lower() == e:
            return c
    return None


# ---------------------------------------------------------------- Google CSV
def _row_name(row: dict) -> str:
    for key in ("Name", "Full Name", "Display Name"):
        v = (row.get(key) or "").strip()
        if v:
            return v
    first = (row.get("First Name") or row.get("Given Name") or "").strip()
    middle = (row.get("Middle Name") or row.get("Additional Name") or "").strip()
    last = (row.get("Last Name") or row.get("Family Name") or "").strip()
    return " ".join(p for p in (first, middle, last) if p).strip()


def _first_col(row: dict, prefix: str, max_n: int = 12) -> str:
    for i in range(1, max_n + 1):
        v = (row.get(f"{prefix} {i} - Value") or "").strip()
        if v:
            return v
    return ""


def import_google_csv(source: Any) -> dict:
    """Import a Google Contacts CSV export.

    `source` may be a path, raw text, bytes, or a file-like object.
    Returns {"added": n, "updated": n, "skipped": n, "error": str}.
    """
    result = {"added": 0, "updated": 0, "skipped": 0, "error": ""}
    try:
        if isinstance(source, (bytes, bytearray)):
            text = source.decode("utf-8-sig", errors="replace")
        elif isinstance(source, str):
            if "\n" in source or source.count(",") > 3:
                text = source
            else:
                text = Path(source).read_text(encoding="utf-8-sig", errors="replace")
        elif hasattr(source, "read"):
            raw = source.read()
            text = raw.decode("utf-8-sig", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
        else:
            result["error"] = "Unsupported CSV source."
            return result
    except Exception as e:
        result["error"] = f"Could not read CSV: {e}"
        return result

    try:
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
    except Exception as e:
        result["error"] = f"Could not parse CSV: {e}"
        return result

    if not rows:
        result["error"] = "CSV has no rows."
        return result

    store = load_store()
    contacts = store.setdefault("contacts", [])

    def find_existing(name: str, phone: str, email: str) -> Optional[dict]:
        nn = _norm(name)
        for c in contacts:
            if nn and _norm(c.get("name") or "") == nn:
                return c
            cphone = normalize_phone(c.get("phone") or c.get("whatsapp") or "")
            if phone and cphone and normalize_phone(phone) == cphone:
                return c
            if email and (c.get("email") or "").strip().lower() == email.lower():
                return c
        return None

    for row in rows:
        if not isinstance(row, dict):
            continue
        name = _row_name(row)
        phone = _first_col(row, "Phone")
        email = _first_col(row, "E-mail")
        if not (name or phone or email):
            result["skipped"] += 1
            continue
        name = name or (email.split("@")[0] if email else phone)
        nickname = (row.get("Nickname") or "").strip()
        group = (row.get("Group Membership") or "").strip()
        aliases = []
        if nickname:
            aliases.append(nickname)
        rel = ""
        for token in re.split(r"[^a-z]+", (group + " " + nickname).lower()):
            r = relationship_of(token)
            if r:
                rel = r
                break
        existing = find_existing(name, phone, email)
        if existing:
            changed = False
            if phone and not existing.get("phone"):
                existing["phone"] = phone
                changed = True
            if email and not existing.get("email"):
                existing["email"] = email
                changed = True
            if rel and not existing.get("relationship"):
                existing["relationship"] = rel
                changed = True
            merged = list(existing.get("aliases") or [])
            for a in aliases:
                if a.lower() not in {m.lower() for m in merged}:
                    merged.append(a)
                    changed = True
            existing["aliases"] = merged
            if changed:
                result["updated"] += 1
            else:
                result["skipped"] += 1
        else:
            contacts.append({
                "id": f"c_{uuid.uuid4().hex[:8]}",
                "name": name,
                "aliases": aliases,
                "relationship": rel,
                "phone": phone,
                "whatsapp": "",
                "email": email,
            })
            result["added"] += 1

    save_store(store)
    return result


# ---------------------------------------------------------------- self-test
if __name__ == "__main__":
    import tempfile

    store = _empty_store()
    store["contacts"] = [
        {"id": "c1", "name": "Shireesha", "aliases": ["siri"], "relationship": "aunty",
         "phone": "9876543210", "whatsapp": "", "email": "shireesha@example.com"},
        {"id": "c2", "name": "Lakshmi", "aliases": [], "relationship": "mother",
         "phone": "9123456780", "whatsapp": "", "email": "mom@example.com"},
        {"id": "c3", "name": "Sireesha Rao", "aliases": [], "relationship": "friend",
         "phone": "9000000001", "whatsapp": "", "email": "sireesha.rao@example.com"},
    ]
    save_store(store)
    for q in ["mom", "moms", "aunty", "aunts", "sireesha", "shireesha", "siri", "lakshmi"]:
        r = resolve(q)
        c = r["contact"]
        print(f"{q!r:12} -> {(c or {}).get('name')!r:16} conf={r['confidence']} method={r['method']} ambiguous={r['ambiguous']}")
    print("phone:", phone_for(resolve("mom")["contact"]))
