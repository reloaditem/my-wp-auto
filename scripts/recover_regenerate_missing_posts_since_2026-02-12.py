#!/usr/bin/env python3
"""
recover_regenerate_missing_posts_since.py

Scan WordPress posts (publish + future) starting from a specific date (KST by default),
detect "broken" content (print/checklist stub, too-short, title mismatch),
and regenerate aligned content + internal links.

DEFAULT: scans from 2026-02-12 00:00:00 Asia/Seoul (KST).

USAGE:
  export WP_BASE="https://example.com"
  export WP_USER="your_wp_user"
  export WP_PASS="your_application_password"
  export OPENAI_API_KEY="..."        # required for regeneration
  python scripts/recover_regenerate_missing_posts_since.py

SAFE DEFAULTS:
  - DRY_RUN=1 by default (no updates). Set DRY_RUN=0 to apply updates.
  - MAX_FIX=10 by default.

ENV:
  DRY_RUN=1|0
  MAX_FIX=10
  MIN_WORDS=500
  AFTER_DATE_KST="2026-02-12"        # YYYY-MM-DD (KST)
  INTERNAL_LINKS=3
  MODEL="gpt-4.1-mini"
  HTTP_TIMEOUT=30
"""

import os
import re
import html
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict

import requests
from requests.auth import HTTPBasicAuth
from bs4 import BeautifulSoup

try:
    from zoneinfo import ZoneInfo  # py>=3.9
except Exception:
    ZoneInfo = None  # type: ignore

try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # type: ignore


# -------------------------
# ENV
# -------------------------
WP_BASE = os.environ.get("WP_BASE", "").rstrip("/")
WP_USER = os.environ.get("WP_USER", "")
WP_PASS = os.environ.get("WP_PASS", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

DRY_RUN = os.environ.get("DRY_RUN", "1").strip() != "0"
MAX_FIX = int(os.environ.get("MAX_FIX", "10"))
MIN_WORDS = int(os.environ.get("MIN_WORDS", "500"))

AFTER_DATE_KST = os.environ.get("AFTER_DATE_KST", "2026-02-12").strip()
INTERNAL_LINKS = int(os.environ.get("INTERNAL_LINKS", "3"))
MODEL = os.environ.get("MODEL", "gpt-4.1-mini")

TIMEOUT = int(os.environ.get("HTTP_TIMEOUT", "30"))

if not (WP_BASE and WP_USER and WP_PASS):
    raise SystemExit("Missing env: WP_BASE, WP_USER, WP_PASS")

auth = HTTPBasicAuth(WP_USER, WP_PASS)
client = OpenAI(api_key=OPENAI_API_KEY) if (OpenAI and OPENAI_API_KEY) else None


# -------------------------
# Date helpers
# -------------------------
def parse_after_dt_utc(date_ymd_kst: str) -> datetime:
    # Interpret YYYY-MM-DD as 00:00:00 in Asia/Seoul, then convert to UTC.
    if not ZoneInfo:
        # Fallback: fixed +09:00
        kst = timezone(timedelta(hours=9))
    else:
        kst = ZoneInfo("Asia/Seoul")
    try:
        d = datetime.strptime(date_ymd_kst, "%Y-%m-%d")
    except ValueError:
        raise SystemExit("AFTER_DATE_KST must be YYYY-MM-DD, e.g. 2026-02-12")
    dt_kst = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=kst)
    return dt_kst.astimezone(timezone.utc)


# -------------------------
# WP REST helpers (GET-safe)
# -------------------------
def _wp_get(path: str, params: Optional[dict] = None):
    url = f"{WP_BASE}{path}"
    headers = {"Accept": "application/json"}
    r = requests.get(url, params=params or {}, headers=headers, auth=auth, timeout=TIMEOUT)
    ct = (r.headers.get("content-type") or "").lower()
    if "application/json" not in ct:
        print("NON-JSON RESPONSE:", r.status_code, ct, "URL:", r.url)
        print("BODY(head):", (r.text or "")[:300])
        r.raise_for_status()
        raise SystemExit("WP did not return JSON (blocked/redirected/WAF).")
    r.raise_for_status()
    return r.json()


def _wp_list(path: str, params: Optional[dict] = None) -> List[dict]:
    data = _wp_get(path, params=params)
    if isinstance(data, dict):
        raise SystemExit(f"WP API error at {path}: {data.get('code')} / {data.get('message')}")
    if not isinstance(data, list):
        raise SystemExit(f"Unexpected WP response type at {path}: {type(data)}")
    cleaned = [x for x in data if isinstance(x, dict)]
    if len(cleaned) != len(data):
        bad = [x for x in data if not isinstance(x, dict)]
        raise SystemExit(f"Non-dict items in list response at {path}: sample={bad[:2]}")
    return cleaned


def _wp_update_post(post_id: int, payload: dict):
    url = f"{WP_BASE}/wp-json/wp/v2/posts/{post_id}"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    r = requests.post(url, json=payload, headers=headers, auth=auth, timeout=TIMEOUT)
    if r.status_code >= 400:
        r = requests.put(url, json=payload, headers=headers, auth=auth, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


# -------------------------
# Detection heuristics
# -------------------------
PRINT_STUB_PATTERNS = [
    r"save\s*(and|or)\s*print\s*checklist",
    r"print\s*(this)?\s*page",
    r"print\s*window",
    r"\bchecklist\b",
]

def _plain_words(html_text: str) -> int:
    soup = BeautifulSoup(html_text or "", "html.parser")
    text = soup.get_text(" ", strip=True)
    if not text:
        return 0
    return len(re.findall(r"\w+", text))

def _looks_like_print_stub(html_text: str) -> bool:
    t = BeautifulSoup(html_text or "", "html.parser").get_text(" ", strip=True).lower()
    if not t:
        return True
    for pat in PRINT_STUB_PATTERNS:
        if re.search(pat, t, flags=re.IGNORECASE):
            if len(t) < 2500:
                return True
    return False

def _title_coverage_score(title_html: str, html_text: str) -> float:
    title_plain = BeautifulSoup(title_html or "", "html.parser").get_text(" ", strip=True)
    title_plain = html.unescape(title_plain).lower().strip()
    body_plain = BeautifulSoup(html_text or "", "html.parser").get_text(" ", strip=True).lower()
    toks = [t for t in re.findall(r"[a-z0-9가-힣]+", title_plain) if len(t) >= 3]
    if not toks:
        return 1.0
    hit = sum(1 for t in toks if t in body_plain)
    return hit / max(len(toks), 1)

def is_broken_post(title_html: str, content_html: str) -> bool:
    words = _plain_words(content_html)
    if words < MIN_WORDS:
        return True
    if _looks_like_print_stub(content_html):
        return True
    if _title_coverage_score(title_html, content_html) < 0.25:
        return True
    return False


# -------------------------
# Internal links
# -------------------------
def get_categories_map() -> Dict[int, str]:
    cats: List[dict] = []
    page = 1
    while True:
        chunk = _wp_list("/wp-json/wp/v2/categories", {"per_page": 100, "page": page})
        if not chunk:
            break
        cats.extend(chunk)
        if len(chunk) < 100:
            break
        page += 1
    return {c["id"]: c.get("name", "") for c in cats}

def get_related_posts(cat_id: Optional[int], exclude_id: int, k: int) -> List[dict]:
    if not cat_id or k <= 0:
        return []
    rel = _wp_list(
        "/wp-json/wp/v2/posts",
        {
            "per_page": min(max(k * 2, 6), 20),
            "page": 1,
            "status": "publish",
            "categories": cat_id,
            "orderby": "date",
            "order": "desc",
        },
    )
    out = []
    for p in rel:
        if p.get("id") == exclude_id:
            continue
        out.append(p)
        if len(out) >= k:
            break
    return out

def make_related_block(related: List[dict]) -> str:
    if not related:
        return ""
    items = []
    for p in related:
        link = (p.get("link") or "").strip()
        title = BeautifulSoup((p.get("title") or {}).get("rendered", ""), "html.parser").get_text(" ", strip=True)
        if link and title:
            items.append(f'<li><a href="{link}">{html.escape(title)}</a></li>')
    if not items:
        return ""
    return '<hr/>\n<h2>Related posts</h2>\n<ul>\n' + "\n".join(items) + "\n</ul>\n"


# -------------------------
# Regeneration
# -------------------------
def regenerate_article(title_html: str, category_name: str, related: List[dict]) -> str:
    if not client:
        raise SystemExit("OPENAI_API_KEY not set (required).")

    title = BeautifulSoup(title_html or "", "html.parser").get_text(" ", strip=True)
    title = html.unescape(title).strip()

    related_titles = []
    for p in related:
        t = BeautifulSoup((p.get("title") or {}).get("rendered", ""), "html.parser").get_text(" ", strip=True)
        if t:
            related_titles.append(t)
    related_titles = related_titles[:INTERNAL_LINKS]

    system = (
        "You write high-quality, neutral, informational long-form blog articles about SaaS tools. "
        "Avoid pricing, avoid exaggerated marketing claims, and keep an approval-friendly tone. "
        "Output must be valid HTML only."
    )

    user = f"""
Write a complete blog article that matches this exact post title:

TITLE: {title}

CATEGORY: {category_name or "SaaS"}

Requirements:
- 1200–1800 words (approx), structured with H2/H3 headings.
- Neutral, informational tone. No direct pricing (no '$', 'USD', 'KRW', 'per month', etc).
- Include one comparison section if relevant (without pricing).
- Include a concise FAQ (3–5 Q/A).
- Include a short conclusion with a non-pushy CTA (no prices).
- Avoid hype like "best ever", "guaranteed", "must buy", etc.
- Add 2 internal-link anchor sentences naturally in the body, referencing these related titles (do not invent URLs): {related_titles}
- Use placeholders for internal links like: <a href="{{INTERNAL_LINK_1}}">Title</a> and <a href="{{INTERNAL_LINK_2}}">Title</a>
- Do not include any "save/print checklist" text.
Return HTML only.
""".strip()

    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.6,
    )
    html_out = (resp.choices[0].message.content or "").strip()

    # Fill placeholders with real URLs (best-effort)
    placeholders = {}
    for idx, p in enumerate(related[:2], start=1):
        placeholders[f"{{INTERNAL_LINK_{idx}}}"] = (p.get("link") or "").strip()

    for ph, url in placeholders.items():
        html_out = html_out.replace(ph, url if url else "#")

    html_out = html_out + "\n" + make_related_block(related)
    return html_out


# -------------------------
# Post iteration
# -------------------------
def get_posts(status: str, after_dt_utc: datetime) -> List[dict]:
    posts: List[dict] = []
    page = 1
    after_iso = after_dt_utc.isoformat().replace("+00:00", "Z")
    while True:
        chunk = _wp_list(
            "/wp-json/wp/v2/posts",
            {
                "per_page": 100,
                "page": page,
                "status": status,
                "orderby": "date",
                "order": "asc",
                "after": after_iso,
            },
        )
        if not chunk:
            break
        posts.extend(chunk)
        if len(chunk) < 100:
            break
        page += 1
    return posts


def main():
    after_dt_utc = parse_after_dt_utc(AFTER_DATE_KST)
    print(f"[INFO] AFTER_DATE_KST={AFTER_DATE_KST} => AFTER_UTC={after_dt_utc.isoformat()}")
    print(f"[INFO] DRY_RUN={DRY_RUN} MAX_FIX={MAX_FIX} MIN_WORDS={MIN_WORDS} INTERNAL_LINKS={INTERNAL_LINKS} MODEL={MODEL}")

    cat_map = get_categories_map()

    candidates: List[dict] = []
    for st in ("publish", "future"):
        ps = get_posts(st, after_dt_utc)
        print(f"[SCAN] status={st} posts={len(ps)}")
        candidates.extend(ps)

    fixed = 0
    for p in candidates:
        pid = int(p["id"])
        title_html = (p.get("title") or {}).get("rendered", "")
        content_html = (p.get("content") or {}).get("rendered", "")

        if not is_broken_post(title_html, content_html):
            continue

        cat_ids = p.get("categories") or []
        cat_id = cat_ids[0] if cat_ids else None
        cat_name = cat_map.get(cat_id, "") if cat_id else ""

        related = get_related_posts(cat_id, exclude_id=pid, k=INTERNAL_LINKS)

        title_plain = BeautifulSoup(title_html, "html.parser").get_text(" ", strip=True)
        words = _plain_words(content_html)
        print(f"[FLAG] id={pid} words={words} cat={cat_name} title={title_plain!r}")

        if not client:
            print("[SKIP] No OPENAI_API_KEY. Cannot regenerate.")
            continue

        new_html = regenerate_article(title_html, cat_name, related)
        new_words = _plain_words(new_html)
        print(f"[GEN ] id={pid} regenerated_words={new_words}")

        if DRY_RUN:
            print(f"[DRY ] Would update post id={pid}")
        else:
            _wp_update_post(pid, {"content": new_html})
            print(f"[OK  ] Updated post id={pid}")

        fixed += 1
        if fixed >= MAX_FIX:
            print("[DONE] Reached MAX_FIX limit.")
            break

    print(f"[DONE] fixed={fixed} (DRY_RUN={DRY_RUN})")


if __name__ == "__main__":
    main()
