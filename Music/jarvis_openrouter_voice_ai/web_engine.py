"""JARVIS web engine: multi-source search + real page scraping + caching.

No API key required. Sources: DuckDuckGo HTML, Bing HTML/RSS, Google News RSS,
Wikipedia REST, and direct article extraction with trafilatura (bs4 fallback).
"""
from __future__ import annotations

import concurrent.futures as cf
import html as _html
import json
import re
import sqlite3
import threading
import time
import urllib.parse as up
import urllib.robotparser as robotparser
from pathlib import Path
from typing import Any

import requests

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None

try:
    import trafilatura
except Exception:
    trafilatura = None

APP_DIR = Path(__file__).resolve().parent
CACHE_DB = APP_DIR / "jarvis_web_cache.db"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36 JARVIS/1.0"
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.5",
    "Accept-Language": "en-US,en;q=0.9",
}
MAX_PAGE_BYTES = 1_400_000
_ROBOTS: dict[str, robotparser.RobotFileParser | None] = {}
_ROBOTS_LOCK = threading.Lock()
_JUNK_DOMAINS = {
    "whatsapp.com", "wa.me", "scribd.com", "deviantart.com", "pinterest.com",
    "quora.com", "answers.microsoft.com", "merohealthline.com",
}
_STOP = {
    "the", "a", "an", "and", "or", "of", "in", "on", "at", "to", "for", "with",
    "is", "are", "was", "were", "be", "what", "who", "when", "where", "why",
    "how", "does", "do", "did", "can", "could", "should", "about", "tell", "me",
    "please", "latest", "today", "current", "best", "top", "under", "over",
}


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
def _db():
    c = sqlite3.connect(CACHE_DB, timeout=6)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=6000")
        c.execute(
            "CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT, created REAL)"
        )
    except Exception:
        pass
    return c


def _cache_get(key: str, ttl: float) -> str:
    try:
        c = _db()
        try:
            row = c.execute("SELECT value, created FROM cache WHERE key=?", (key,)).fetchone()
        finally:
            c.close()
        if row and (time.time() - float(row["created"])) <= ttl:
            return str(row["value"])
    except Exception:
        pass
    return ""


def _cache_set(key: str, value: str) -> None:
    if not value:
        return
    try:
        c = _db()
        try:
            c.execute(
                "INSERT INTO cache(key, value, created) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, created=excluded.created",
                (key, value[:40000], time.time()),
            )
            c.commit()
            # occasional prune
            if time.time() % 20 < 1:
                c.execute("DELETE FROM cache WHERE created < ?", (time.time() - 86400 * 3,))
                c.commit()
        finally:
            c.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _clean_text(t: str, limit: int = 6000) -> str:
    t = _html.unescape(t or "")
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:limit]


def _domain(url: str) -> str:
    try:
        return (up.urlparse(url).netloc or "").lower().replace("www.", "")
    except Exception:
        return ""


def _unwrap_ddg(url: str) -> str:
    try:
        if "duckduckgo.com/l/" in url and "uddg=" in url:
            qs = up.parse_qs(up.urlparse(url).query)
            if qs.get("uddg"):
                return qs["uddg"][0]
    except Exception:
        pass
    if url.startswith("//"):
        return "https:" + url
    return url


def _norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def _cache_key(prefix: str, q: str) -> str:
    return "v4:" + prefix + ":" + re.sub(r"\s+", " ", (q or "").lower().strip())[:240]


# ---------------------------------------------------------------------------
# Search sources
# ---------------------------------------------------------------------------
def _ddg_search(query: str, max_results: int = 5) -> list[dict]:
    out: list[dict] = []
    try:
        r = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query, "kl": "us-en"},
            headers=HEADERS,
            timeout=4,
        )
        if r.status_code != 200:
            raise ValueError(f"ddg {r.status_code}")
        if BeautifulSoup is None:
            return out
        soup = BeautifulSoup(r.text, "html.parser")
        for res in soup.select(".result"):
            a = res.select_one("a.result__a")
            if not a:
                continue
            url = _unwrap_ddg(a.get("href", ""))
            title = _clean_text(a.get_text(" ", strip=True), 240)
            sn = res.select_one(".result__snippet")
            snippet = _clean_text(sn.get_text(" ", strip=True), 420) if sn else ""
            if title and url.startswith("http"):
                out.append({"title": title, "url": url, "snippet": snippet, "source": "ddg"})
            if len(out) >= max_results:
                break
    except Exception:
        pass
    if out:
        return out
    # lite fallback
    try:
        r = requests.get(
            "https://lite.duckduckgo.com/lite/",
            params={"q": query},
            headers=HEADERS,
            timeout=4,
        )
        if r.status_code == 200 and BeautifulSoup is not None:
            soup = BeautifulSoup(r.text, "html.parser")
            links = soup.select("a.result-link")
            snips = soup.select("td.result-snippet")
            for i, a in enumerate(links[:max_results]):
                url = _unwrap_ddg(a.get("href", ""))
                title = _clean_text(a.get_text(" ", strip=True), 240)
                snippet = _clean_text(snips[i].get_text(" ", strip=True), 420) if i < len(snips) else ""
                if title and url.startswith("http"):
                    out.append({"title": title, "url": url, "snippet": snippet, "source": "ddg-lite"})
    except Exception:
        pass
    return out


def _bing_search(query: str, max_results: int = 5) -> list[dict]:
    out: list[dict] = []
    try:
        r = requests.get(
            "https://www.bing.com/search",
            params={"q": query, "setlang": "en", "cc": "us"},
            headers=HEADERS,
            timeout=4,
        )
        if r.status_code != 200 or BeautifulSoup is None:
            return out
        soup = BeautifulSoup(r.text, "html.parser")
        for li in soup.select("li.b_algo"):
            a = li.select_one("h2 a")
            if not a:
                continue
            url = a.get("href", "")
            title = _clean_text(a.get_text(" ", strip=True), 240)
            p = li.select_one(".b_caption p") or li.select_one("p")
            snippet = _clean_text(p.get_text(" ", strip=True), 420) if p else ""
            if title and url.startswith("http"):
                out.append({"title": title, "url": url, "snippet": snippet, "source": "bing"})
            if len(out) >= max_results:
                break
    except Exception:
        pass
    if out:
        return out
    # RSS fallback
    try:
        r = requests.get(
            f"https://www.bing.com/search?format=rss&q={up.quote_plus(query)}",
            headers=HEADERS,
            timeout=3,
        )
        if r.status_code == 200:
            for it in re.findall(r"<item>.*?</item>", r.text, re.DOTALL)[:max_results]:
                t = re.search(r"<title>(.*?)</title>", it, re.DOTALL)
                l = re.search(r"<link>(.*?)</link>", it)
                d = re.search(r"<description>(.*?)</description>", it, re.DOTALL)
                title = _clean_text(t.group(1) if t else "", 240)
                url = _clean_text(l.group(1) if l else "", 500)
                snippet = _clean_text(d.group(1) if d else "", 420)
                if title and url.startswith("http"):
                    out.append({"title": title, "url": url, "snippet": snippet, "source": "bing-rss"})
    except Exception:
        pass
    return out


def _google_news(query: str, max_results: int = 5) -> list[dict]:
    out: list[dict] = []
    try:
        r = requests.get(
            "https://news.google.com/rss/search?q=" + up.quote_plus(query) + "&hl=en-US&gl=US&ceid=US:en",
            headers=HEADERS,
            timeout=4,
        )
        if r.status_code != 200:
            return out
        for it in re.findall(r"<item>.*?</item>", r.text, re.DOTALL)[:max_results]:
            t = re.search(r"<title>(.*?)</title>", it, re.DOTALL)
            l = re.search(r"<link>(.*?)</link>", it, re.DOTALL)
            d = re.search(r"<pubDate>(.*?)</pubDate>", it, re.DOTALL)
            title = _clean_text(t.group(1) if t else "", 240)
            url = _clean_text(l.group(1) if l else "", 600)
            when = _clean_text(d.group(1) if d else "", 40)
            if title and url:
                out.append({
                    "title": title,
                    "url": url,
                    "snippet": f"Published {when}" if when else "",
                    "source": "google-news",
                })
    except Exception:
        pass
    return out


def _wikipedia_direct(query: str) -> dict | None:
    """Fast Wikipedia summary for who/what/where style questions."""
    try:
        q = _clean_text(query, 300)
        # "what is the capital of France" -> "capital of France" (question words poison the search).
        if re.match(r"^(what|who|where|when)\b", q.lower()):
            q = re.sub(
                r"^(what|who|where|when)\s+(is|are|was|were|does|do|did)\s+",
                "", q, flags=re.I,
            )
            q = re.sub(r"^the\s+", "", q.strip(), flags=re.I)
        q = re.sub(r"^(tell me about|explain|define|definition of|meaning of|search for|look up)\s+", "", q, flags=re.I)
        q = q.strip(" ?.!")
        if len(q) < 2:
            q = _clean_text(query, 300)

        # Prefer an exact/prefix title (e.g. "capital of France" -> "Capital of France"
        # which redirects to Paris) over fuzzy search hits like "Closed-ended question".
        try:
            op = requests.get(
                "https://en.wikipedia.org/w/api.php",
                params={"action": "opensearch", "search": q, "limit": 1, "namespace": 0, "format": "json"},
                headers=HEADERS,
                timeout=2,
            )
            if op.status_code == 200:
                titles = (op.json() or [None, []])[1]
                if titles and titles[0]:
                    ot = titles[0]
                    sm0 = requests.get(
                        "https://en.wikipedia.org/api/rest_v1/page/summary/"
                        + up.quote(ot.replace(" ", "_"), safe=""),
                        headers=HEADERS,
                        timeout=2,
                    )
                    if sm0.status_code == 200:
                        d0 = sm0.json()
                        text0 = _clean_text(d0.get("extract", ""), 1400)
                        if len(text0) >= 60 and d0.get("type", "standard") not in ("disambiguation",):
                            url0 = (d0.get("content_urls", {}).get("desktop", {}) or {}).get("page", "")
                            if not url0:
                                url0 = "https://en.wikipedia.org/wiki/" + up.quote(ot.replace(" ", "_"))
                            return {
                                "title": d0.get("title") or ot,
                                "url": url0,
                                "snippet": text0,
                                "source": "wikipedia",
                            }
        except Exception:
            pass

        sr = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": q,
                "format": "json",
                "srlimit": 1,
                "utf8": 1,
            },
            headers=HEADERS,
            timeout=2.5,
        )
        if sr.status_code != 200:
            return None
        pages = sr.json().get("query", {}).get("search", [])
        if not pages:
            return None
        title = pages[0].get("title", "")
        if not title:
            return None
        sm = requests.get(
            "https://en.wikipedia.org/api/rest_v1/page/summary/" + up.quote(title.replace(" ", "_"), safe=""),
            headers=HEADERS,
            timeout=2.5,
        )
        if sm.status_code != 200:
            return None
        d = sm.json()
        extract = _clean_text(d.get("extract", ""), 1400)
        if len(extract) < 60:
            return None
        url = (d.get("content_urls", {}).get("desktop", {}) or {}).get("page", "")
        if not url:
            url = "https://en.wikipedia.org/wiki/" + up.quote(title.replace(" ", "_"))
        return {"title": title, "url": url, "snippet": extract, "source": "wikipedia"}
    except Exception:
        return None


def _duck_instant(query: str) -> dict | None:
    try:
        r = requests.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
            headers=HEADERS,
            timeout=2,
        )
        if r.status_code != 200:
            return None
        d = r.json()
        text = _clean_text(d.get("AbstractText") or d.get("Answer") or "", 1200)
        if len(text) < 40:
            return None
        url = d.get("AbstractURL") or ""
        title = d.get("Heading") or query
        return {"title": title, "url": url, "snippet": text, "source": "ddg-instant"}
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Search aggregation
# ---------------------------------------------------------------------------
def search(query: str, max_results: int = 6, news: bool = False) -> list[dict]:
    q = _clean_text(query, 300)
    if not q:
        return []
    ck = _cache_key("search:news" if news else "search", q)
    cached = _cache_get(ck, 900)
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass

    results: list[dict] = []
    if news:
        results.extend(_google_news(q, max_results))

    # Meaningful query tokens for relevance filtering (Bing sometimes returns WhatsApp spam).
    qtokens = {t for t in re.findall(r"[a-z0-9]{3,}", q.lower()) if t not in _STOP}

    with cf.ThreadPoolExecutor(max_workers=3) as ex:
        f_ddg = ex.submit(_ddg_search, q, max_results)
        f_bing = ex.submit(_bing_search, q, max_results)
        f_wiki = ex.submit(_wikipedia_direct, q) if _is_definitional(q) else None
        for f in (f_ddg, f_bing, f_wiki):
            if f is None:
                continue
            try:
                r = f.result(timeout=5)
            except Exception:
                r = None
            if isinstance(r, list):
                results.extend(r)
            elif isinstance(r, dict):
                results.append(r)

    # Dedup by URL and title, filter junk + irrelevant results, keep order.
    seen: set[str] = set()
    out: list[dict] = []
    for r in results:
        url = (r.get("url") or "").strip()
        title = _clean_text(r.get("title", ""), 240)
        snippet = _clean_text(r.get("snippet", ""), 600)
        if not title or not url.startswith("http"):
            continue
        dom = _domain(url)
        if any(j in dom for j in _JUNK_DOMAINS):
            continue
        # Relevance: at least one meaningful query token must appear in the result text.
        if qtokens and r.get("source") not in ("wikipedia", "ddg-instant"):
            hay = (title + " " + snippet + " " + url).lower()
            if not any(tok in hay for tok in qtokens):
                continue
        key = dom + "|" + _norm_title(title)
        if key in seen:
            continue
        seen.add(key)
        r["title"] = title
        r["snippet"] = snippet
        out.append(r)
        if len(out) >= max_results:
            break

    if out:
        _cache_set(ck, json.dumps(out, ensure_ascii=False))
    return out


def _is_definitional(q: str) -> bool:
    low = (q or "").lower().strip()
    if re.match(r"^how\s+(to|do i|can i|should i)\b", low):
        return False
    return bool(re.match(r"^(who|what|where|when|why|how)\b", low)) or bool(
        re.search(r"\b(meaning|definition|define|capital of|population of|height of)\b", low)
    )


# ---------------------------------------------------------------------------
# Page fetching / extraction
# ---------------------------------------------------------------------------
def _robots_allowed(url: str) -> bool:
    try:
        p = up.urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        with _ROBOTS_LOCK:
            rp = _ROBOTS.get(base, "missing")  # type: ignore[assignment]
        if rp == "missing":
            rp = None
            try:
                rr = requests.get(base + "/robots.txt", headers=HEADERS, timeout=1.5)
                if rr.status_code == 200 and rr.text:
                    rp = robotparser.RobotFileParser()
                    rp.parse(rr.text.splitlines())
            except Exception:
                rp = None
            with _ROBOTS_LOCK:
                _ROBOTS[base] = rp
        if rp is None:
            return True
        return bool(rp.can_fetch(UA, url))
    except Exception:
        return True


def fetch_page_text(url: str, max_chars: int = 5000) -> str:
    url = (url or "").strip()
    if not url.startswith("http"):
        return ""
    ck = _cache_key("page", url)
    cached = _cache_get(ck, 21600)
    if cached:
        return cached[:max_chars]
    if not _robots_allowed(url):
        return ""
    try:
        r = requests.get(url, headers=HEADERS, timeout=6, stream=True, allow_redirects=True)
        if r.status_code != 200:
            return ""
        ctype = (r.headers.get("Content-Type") or "").lower()
        if "html" not in ctype and "text" not in ctype:
            return ""
        chunks, total = [], 0
        for chunk in r.iter_content(32768):
            if not chunk:
                continue
            chunks.append(chunk)
            total += len(chunk)
            if total >= MAX_PAGE_BYTES:
                break
        raw = b"".join(chunks)
        enc = r.encoding or "utf-8"
        try:
            html_text = raw.decode(enc, errors="replace")
        except Exception:
            html_text = raw.decode("utf-8", errors="replace")
    except Exception:
        return ""

    text = ""
    if trafilatura is not None:
        try:
            text = trafilatura.extract(
                html_text,
                include_comments=False,
                include_tables=False,
                favor_precision=True,
                no_fallback=False,
            ) or ""
        except Exception:
            text = ""
    if len(text) < 180 and BeautifulSoup is not None:
        try:
            soup = BeautifulSoup(html_text, "html.parser")
            for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form", "noscript", "svg"]):
                tag.decompose()
            root = soup.find("article") or soup.find("main") or soup.body or soup
            parts = []
            for el in root.find_all(["h1", "h2", "h3", "p", "li"]):
                t = _clean_text(el.get_text(" ", strip=True), 800)
                if len(t) >= 40:
                    parts.append(t)
            text = "\n".join(parts)
            if len(text) < 120:
                desc = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
                if desc and desc.get("content"):
                    text = _clean_text(desc["content"], 800)
        except Exception:
            pass
    text = _clean_text(text, max_chars)
    if len(text) >= 120:
        _cache_set(ck, text)
    return text


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def quick_fact(query: str, budget: float = 4.0) -> dict | None:
    """Wikipedia + DDG instant answer in parallel. Returns a context dict or None."""
    q = _clean_text(query, 300)
    if not q:
        return None
    ck = _cache_key("quick", q)
    cached = _cache_get(ck, 21600)
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass
    items: list[dict] = []
    with cf.ThreadPoolExecutor(max_workers=2) as ex:
        fw = ex.submit(_wikipedia_direct, q)
        fd = ex.submit(_duck_instant, q)
        for f in (fw, fd):
            try:
                r = f.result(timeout=budget)
            except Exception:
                r = None
            if r and r.get("snippet") and len(r["snippet"]) >= 80:
                items.append(r)
    if not items:
        return None
    # Prefer Wikipedia; add the other as a second source when useful.
    items.sort(key=lambda x: 0 if x.get("source") == "wikipedia" else 1)
    lines = []
    sources = []
    for i, it in enumerate(items[:2], 1):
        lines.append(f"[{i}] {it['title']} — {it.get('url','')}\n{it['snippet']}")
        if it.get("url"):
            sources.append({"title": it["title"], "url": it["url"], "source": it.get("source", "")})
    data = {
        "context": "Live web facts:\n" + "\n\n".join(lines),
        "sources": sources,
        "quick": True,
    }
    _cache_set(ck, json.dumps(data, ensure_ascii=False))
    return data


def deep_context(query: str, deep: bool = False, budget: float = 7.0) -> dict:
    """Search + scrape top pages. Returns {context, sources, quick, elapsed}."""
    q = _clean_text(query, 300)
    start = time.time()
    if not q:
        return {"context": "", "sources": [], "quick": False, "elapsed": 0.0}
    ck = _cache_key("deep:" + ("1" if deep else "0"), q)
    cached = _cache_get(ck, 1200)
    if cached:
        try:
            d = json.loads(cached)
            d["cached"] = True
            return d
        except Exception:
            pass

    news = bool(re.search(r"\b(news|latest|today|breaking|headlines?|update)\b", q.lower()))
    results = search(q, max_results=(5 if deep else 4), news=news)
    sources: list[dict] = []
    blocks: list[str] = []
    snippets: list[str] = []
    for r in results:
        if r.get("snippet"):
            snippets.append(f"- {r['title']} — {r['snippet']} ({r.get('url','')})")

    # Wikipedia result is already a summary: use it as a block, not a fetched page.
    wiki = next((r for r in results if r.get("source") == "wikipedia"), None)
    if wiki:
        blocks.append(f"[{len(blocks)+1}] {wiki['title']} — {wiki['url']}\n{wiki['snippet']}")
        sources.append({"title": wiki["title"], "url": wiki["url"], "source": "wikipedia"})

    # Pick pages to scrape: skip wiki and known hard-blocked platforms.
    skip = {"wikipedia.org", "youtube.com", "youtu.be", "twitter.com", "x.com", "facebook.com",
            "instagram.com", "tiktok.com", "linkedin.com", "reddit.com"}
    targets = [r for r in results if _domain(r.get("url", "")) not in skip and r.get("url")]
    max_pages = 3 if deep else 2
    targets = targets[:max_pages]

    if targets:
        with cf.ThreadPoolExecutor(max_workers=len(targets)) as ex:
            futs = {ex.submit(fetch_page_text, t["url"], 5000): t for t in targets}
            deadline = start + max(2.0, budget - 1.5)
            remaining = list(futs.keys())
            while remaining and time.time() < deadline:
                timeout = max(0.5, deadline - time.time())
                try:
                    for fut in cf.as_completed(remaining, timeout=timeout):
                        t = futs[fut]
                        remaining.remove(fut)
                        try:
                            text = fut.result()
                        except Exception:
                            text = ""
                        if text and len(text) >= 160:
                            blocks.append(f"[{len(blocks)+1}] {t['title']} — {t['url']}\n{text}")
                            sources.append({"title": t["title"], "url": t["url"], "source": t.get("source", "")})
                        if len(blocks) >= (max_pages + (1 if wiki else 0)):
                            remaining = []
                            break
                except cf.TimeoutError:
                    break
            # Cancel any still-running futures
            for fut in remaining:
                fut.cancel()

    parts = []
    if blocks:
        parts.append("Scraped page content (live):\n" + "\n\n".join(blocks))
    if snippets:
        parts.append("Search result snippets:\n" + "\n".join(snippets[:6]))
    context = "\n\n".join(parts)[:14000]
    data = {
        "context": context,
        "sources": sources or [{"title": r["title"], "url": r["url"], "source": r.get("source", "")} for r in results[:4]],
        "quick": False,
        "elapsed": round(time.time() - start, 2),
    }
    if context:
        _cache_set(ck, json.dumps(data, ensure_ascii=False))
    return data


def get_context(query: str, deep: bool = False, budget: float = 7.0) -> dict:
    """Best context for a question: quick Wikipedia for definitions, scraper otherwise."""
    q = _clean_text(query, 300)
    low = q.lower()
    definitional = _is_definitional(q) and len(low.split()) <= 14 and not re.search(
        r"\b(news|latest|today|price|stock|score|compare|vs|difference|how to|how do i|how can i)\b", low
    )
    if definitional and not deep:
        qf = quick_fact(q, budget=min(4.0, budget))
        if qf and len(qf.get("context", "")) >= 180:
            qf["elapsed"] = round(0.0, 2)
            return qf
    return deep_context(q, deep=deep, budget=budget)


def needs_web(prompt: str, deep: bool = False) -> bool:
    p = (prompt or "").strip().lower()
    if not p or len(p) > 400:
        return False
    if re.search(r"\b(search|look ?up|google|browse|scrape|find online|check online|web|internet)\b", p):
        return True
    # Time-sensitive topics need live data even without a question word
    # ("latest AI news today", "bitcoin price", "stock market today").
    time_sensitive = bool(re.search(
        r"\b(news|latest|today|tonight|current|currently|recent|recently|right now|live|breaking|"
        r"update|updates|price|prices|stock|stocks|score|scores|match|matches|election|"
        r"weather|forecast|release|released|launched|who won|how much is|how much does|"
        r"exchange rate|bitcoin|btc|usd|inr|eur)\b", p))
    if not re.search(
        r"\b(who|what|when|where|why|how|which|whose|is|are|was|were|do|does|did|can|could|should|"
        r"tell me|explain|define|meaning|compare|difference|versus|vs)\b", p
    ) and not time_sensitive:
        return False
    # Don't web-search personal memory or commands, math, media or local intents.
    if re.search(r"\b(my name|who am i|what do you remember|do you remember me|remember about me|"
                 r"my preferences?|my birthday|my age|my tasks?|my (?:schedule|projects?))\b", p):
        return False
    if re.search(r"\b(play|song|music|spotify|video|youtube|task|remind|weather|time|date|system|camera|"
                 r"remember|forget|plan my day|open)\b", p):
        return False
    # Personal statements are things to remember, not facts to research.
    if re.match(r"^(my |i am |i'm |i live |i work |i study |i like |i love |i prefer |i hate |"
                r"i'm building |i'm working |i'm learning |i've |we )", p) and "?" not in p:
        return False
    if re.fullmatch(r"[\d\s\+\-\*\/\(\)\.%=]+", p) or re.search(r"\b\d+\s*[\+\-\*\/]\s*\d+\b", p):
        return False
    if re.search(r"\b(who are you|what can you do|what are you|how are you|"
                 r"joke|poem|story|riddle|bedtime story)\b", p):
        return False
    if time_sensitive or deep:
        return True
    # All genuine informational questions get grounded (fast Wikipedia path first).
    words = len(p.split())
    return words >= 4


def looks_uncertain(reply: str) -> bool:
    t = (reply or "").lower()
    patterns = (
        "i don't know", "i do not know", "i cannot", "i can't", "unable to",
        "as of my knowledge", "as of my last", "no information", "not sure",
        "i'm not certain", "i am not certain", "cannot browse", "can't browse",
        "my knowledge cutoff", "i don't have access", "i do not have access",
    )
    return any(p in t for p in patterns) and len(t) < 700


def look_up(query: str, max_results: int = 4) -> str:
    """Human-readable snippet block (used by desktop paths and fallbacks)."""
    results = search(query, max_results=max_results)
    if not results:
        return ""
    lines = []
    for r in results:
        lines.append(f"- {r['title']} — {r.get('snippet', '')} ({r['url']})")
    return "\n".join(lines)


def web_sources(query: str, deep: bool = False, budget: float = 7.0) -> list[dict]:
    return get_context(query, deep=deep, budget=budget).get("sources", [])
