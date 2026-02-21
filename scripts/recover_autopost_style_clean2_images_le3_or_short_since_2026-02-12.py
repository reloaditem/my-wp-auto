#!/usr/bin/env python3
"""
recover_autopost_style_clean2_images_le3_or_short_since_2026-02-12.py

Purpose
- Scan WordPress posts (publish + future) since AFTER_DATE_KST (default: 2026-02-12 KST).
- Only FIX posts that match ANY of:
  1) word count < MIN_WORDS
  2) body image count < BODY_IMAGE_COUNT (default: 3)
  3) looks like a broken print/checklist stub
  4) title/body mismatch score < TITLE_MATCH_MIN (default: 0.25)

When fixing:
- Back up original HTML to BACKUP_DIR before overwriting
- Regenerate full approval-friendly article (raw HTML)
- Ensure BODY_IMAGE_COUNT images using Unsplash (if key provided)
- Add internal links + related posts block
- Append print-friendly checklist section
- Strip pricing mentions
- Wrap tables for mobile scroll
- CLEAN LEVEL 2: aggressive HTML cleanup to remove junk / fences / Gutenberg leftovers,
  remove <h1>, remove scripts/styles, remove empty tags, normalize links, etc.
- Featured image (thumbnail) stays unchanged (only "content" is updated)

Required ENV:
  WP_BASE, WP_USER, WP_PASS, OPENAI_API_KEY

Recommended ENV:
  UNSPLASH_ACCESS_KEY

Optional ENV:
  DRY_RUN=1|0 (default 1)
  MAX_FIX=10
  MIN_WORDS=700
  AFTER_DATE_KST=2026-02-12
  INTERNAL_LINKS=3
  BODY_IMAGE_COUNT=3
  TITLE_MATCH_MIN=0.25
  BACKUP_DIR=backups
  MODEL=gpt-4.1-mini
  HTTP_TIMEOUT=30
"""

import os
import re
import html
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict

import requests
from requests.auth import HTTPBasicAuth
from bs4 import BeautifulSoup, Comment

try:
    from zoneinfo import ZoneInfo
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
UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "")

DRY_RUN = os.environ.get("DRY_RUN", "1").strip() != "0"
MAX_FIX = int(os.environ.get("MAX_FIX", "10"))
MIN_WORDS = int(os.environ.get("MIN_WORDS", "700"))
AFTER_DATE_KST = os.environ.get("AFTER_DATE_KST", "2026-02-12").strip()

INTERNAL_LINKS = int(os.environ.get("INTERNAL_LINKS", "3"))
BODY_IMAGE_COUNT = int(os.environ.get("BODY_IMAGE_COUNT", "3"))
TITLE_MATCH_MIN = float(os.environ.get("TITLE_MATCH_MIN", "0.25"))

MODEL = os.environ.get("MODEL", "gpt-4.1-mini")
TIMEOUT = int(os.environ.get("HTTP_TIMEOUT", "30"))
BACKUP_DIR = os.environ.get("BACKUP_DIR", "backups").strip() or "backups"

if not (WP_BASE and WP_USER and WP_PASS):
    raise SystemExit("Missing env: WP_BASE, WP_USER, WP_PASS")

auth = HTTPBasicAuth(WP_USER, WP_PASS)
client = OpenAI(api_key=OPENAI_API_KEY) if (OpenAI and OPENAI_API_KEY) else None


# -------------------------
# Date helpers
# -------------------------
def parse_after_dt_utc(date_ymd_kst: str) -> datetime:
    if not ZoneInfo:
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
# Backup helpers
# -------------------------
def _safe_filename(s: str) -> str:
    s = re.sub(r"[\s]+", "_", s.strip())
    s = re.sub(r"[^a-zA-Z0-9가-힣_\-]+", "", s)
    return s[:80] or "post"

def backup_post_html(post_id: int, title_html: str, content_html: str) -> str:
    os.makedirs(BACKUP_DIR, exist_ok=True)
    title_plain = BeautifulSoup(title_html or "", "html.parser").get_text(" ", strip=True)
    title_plain = html.unescape(title_plain)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"{ts}_id{post_id}_{_safe_filename(title_plain)}.html"
    path = os.path.join(BACKUP_DIR, fname)
    header = f"<!-- BACKUP {ts} | post_id={post_id} | title={title_plain} -->\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(header)
        f.write(content_html or "")
    return path


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

def _body_image_count(html_text: str) -> int:
    soup = BeautifulSoup(html_text or "", "html.parser")
    return len(soup.find_all("img"))

def should_fix_post(title_html: str, content_html: str) -> Dict[str, bool]:
    flags = {"short": False, "stub": False, "title_mismatch": False, "few_images": False}
    words = _plain_words(content_html)
    imgc = _body_image_count(content_html)

    if words < MIN_WORDS:
        flags["short"] = True
    if _looks_like_print_stub(content_html):
        flags["stub"] = True
    if _title_coverage_score(title_html, content_html) < TITLE_MATCH_MIN:
        flags["title_mismatch"] = True
    if imgc < BODY_IMAGE_COUNT:
        flags["few_images"] = True

    return flags


# -------------------------
# Content transforms (pricing, tables, fences)
# -------------------------
PRICE_PATTERNS = [
    r"\$\s?\d[\d,]*(\.\d+)?",
    r"USD\s?\d[\d,]*(\.\d+)?",
    r"\b\d[\d,]*(\.\d+)?\s?(USD|달러)\b",
    r"\b\d[\d,]*(\.\d+)?\s?(원|KRW)\b",
    r"\b(?:price|pricing|cost)\s*[:\-]\s*.*?(<|$)",
    r"\bfrom\s+\$\s?\d[\d,]*(\.\d+)?",
    r"\bstarting\s+at\s+\$\s?\d[\d,]*(\.\d+)?",
]

def strip_pricing(html_text: str) -> str:
    if not html_text:
        return html_text

    for pat in PRICE_PATTERNS:
        html_text = re.sub(pat, "", html_text, flags=re.IGNORECASE)

    soup = BeautifulSoup(html_text, "html.parser")

    # Remove explicit pricing paragraphs
    for p in list(soup.find_all(["p", "li"])):
        t = p.get_text(" ", strip=True).lower()
        if any(k in t for k in ["pricing", "price", "cost", "per month", "usd", "$", "krw", "원"]) and any(ch.isdigit() for ch in t):
            p.decompose()

    # Remove price columns / rows from tables
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        header_cells = rows[0].find_all(["th", "td"])
        header_texts = [c.get_text(" ", strip=True).lower() for c in header_cells]
        price_cols = [i for i, t in enumerate(header_texts) if any(k in t for k in ["price", "pricing", "cost", "plan"])]
        if price_cols:
            for tr in rows:
                cells = tr.find_all(["th", "td"])
                for idx in sorted(price_cols, reverse=True):
                    if idx < len(cells):
                        cells[idx].decompose()
        for tr in list(table.find_all("tr")):
            t = tr.get_text(" ", strip=True).lower()
            if ("$" in t) or ("usd" in t) or ("/mo" in t) or ("per month" in t) or ("krw" in t):
                tr.decompose()

    return str(soup)

def fix_tables(html_text: str) -> str:
    if not html_text:
        return html_text
    soup = BeautifulSoup(html_text, "html.parser")
    changed = False
    for table in soup.find_all("table"):
        if table.parent and table.parent.name == "div" and "table-scroll" in (table.parent.get("class") or []):
            continue
        wrapper = soup.new_tag("div")
        wrapper["class"] = ["table-scroll"]
        table.wrap(wrapper)
        changed = True

    if changed:
        style_id = "ri-table-scroll-style"
        if not soup.find("style", attrs={"id": style_id}):
            style = soup.new_tag("style")
            style["id"] = style_id
            style.string = """
.table-scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:18px 0;border:1px solid rgba(0,0,0,.08);border-radius:12px}
.table-scroll table{min-width:640px;width:100%;border-collapse:collapse}
.table-scroll th,.table-scroll td{padding:10px 12px}
"""
            soup.insert(0, style)
    return str(soup)

def strip_markdown_fences(s: str) -> str:
    if not s:
        return s
    s = s.strip()
    # Remove common fences (start/end)
    s = re.sub(r"^\s*```[a-zA-Z0-9_-]*\s*", "", s)
    s = re.sub(r"\s*```\s*$", "", s)
    # Remove any remaining stray triple backticks
    s = s.replace("```", "")
    return s.strip()


# -------------------------
# CLEAN LEVEL 2 (aggressive HTML cleanup)
# -------------------------
ALLOWED_TAGS = {
    "p","br","hr","ul","ol","li",
    "h2","h3","h4",
    "strong","em","b","i","u",
    "a","img","figure","figcaption",
    "blockquote",
    "table","thead","tbody","tr","th","td",
    "code","pre",
    "div","span",
    "style",
}

ALLOWED_ATTRS = {
    "a": {"href","title","rel","target"},
    "img": {"src","alt","title","loading","width","height","srcset","sizes","style"},
    "figure": {"class","style"},
    "div": {"class","style"},
    "span": {"class","style"},
    "table": {"class","style"},
    "th": {"colspan","rowspan"},
    "td": {"colspan","rowspan"},
    "style": {"id"},
}

def clean_level2_html(html_text: str) -> str:
    if not html_text:
        return html_text

    # Remove any fenced blocks quickly
    html_text = strip_markdown_fences(html_text)

    soup = BeautifulSoup(html_text, "html.parser")

    # Remove HTML comments (incl Gutenberg <!-- wp:... -->)
    for c in soup.find_all(string=lambda t: isinstance(t, Comment)):
        c.extract()

    # Drop scripts/iframes/forms entirely
    for tag in soup.find_all(["script","iframe","form","input","button","textarea","noscript"]):
        tag.decompose()

    # Remove H1 (avoid duplicate title)
    for h1 in soup.find_all("h1"):
        h1.decompose()

    # Flatten disallowed tags: unwrap or remove
    for tag in list(soup.find_all(True)):
        if tag.name not in ALLOWED_TAGS:
            tag.unwrap()

    # Remove dangerous attrs, normalize link rel
    for tag in soup.find_all(True):
        allowed = ALLOWED_ATTRS.get(tag.name, set())
        if allowed:
            tag.attrs = {k: v for k, v in tag.attrs.items() if k in allowed}
        else:
            tag.attrs = {}

        if tag.name == "a":
            href = (tag.get("href") or "").strip()
            # Drop javascript: links
            if href.lower().startswith("javascript:"):
                tag.unwrap()
                continue
            # External links get noopener/noreferrer if target=_blank
            if tag.get("target") == "_blank":
                rel = (tag.get("rel") or [])
                if isinstance(rel, str):
                    rel = rel.split()
                rel_set = set(rel)
                rel_set.update({"noopener", "noreferrer"})
                tag["rel"] = " ".join(sorted(rel_set))
            # If empty anchor text, unwrap
            if not tag.get_text(" ", strip=True) and not tag.find("img"):
                tag.unwrap()

        if tag.name == "img":
            # Ensure loading=lazy
            if not tag.get("loading"):
                tag["loading"] = "lazy"

    # Remove empty p/div/span (unless contains img)
    for tag in list(soup.find_all(["p","div","span","figure"])):
        if tag.find("img"):
            continue
        if not tag.get_text(" ", strip=True):
            tag.decompose()

    # Deduplicate consecutive <br> (more than 2)
    out = str(soup)
    out = re.sub(r"(<br\s*/?>\s*){3,}", "<br/><br/>", out, flags=re.IGNORECASE)

    # Trim whitespace
    return out.strip()


# -------------------------
# Unsplash images
# -------------------------
def unsplash_search(query: str, count: int = 3) -> List[str]:
    if not UNSPLASH_ACCESS_KEY:
        return []
    try:
        url = "https://api.unsplash.com/search/photos"
        params = {
            "query": query,
            "per_page": min(max(count, 3), 10),
            "orientation": "landscape",
            "content_filter": "high",
        }
        headers = {"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"}
        r = requests.get(url, params=params, headers=headers, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        results = data.get("results", [])
        urls = []
        for item in results:
            u = item.get("urls", {}).get("regular")
            if u:
                urls.append(u)
        return urls[:count]
    except Exception:
        return []

def ensure_body_images(html_text: str, topic: str) -> str:
    if BODY_IMAGE_COUNT <= 0:
        return html_text
    soup = BeautifulSoup(html_text or "", "html.parser")
    imgs = soup.find_all("img")
    if len(imgs) >= BODY_IMAGE_COUNT:
        return str(soup)

    need = BODY_IMAGE_COUNT - len(imgs)
    urls = unsplash_search(topic, count=max(need, BODY_IMAGE_COUNT))
    if not urls:
        return str(soup)

    h2s = soup.find_all(["h2", "h3"])
    insert_points = []
    if h2s:
        insert_points = [h2s[0]]
        if len(h2s) >= 2:
            insert_points.append(h2s[len(h2s)//2])
        if len(h2s) >= 3:
            insert_points.append(h2s[-1])
    else:
        insert_points = [soup.find() or soup]

    def make_img(url: str, alt: str):
        fig = soup.new_tag("figure")
        fig["class"] = ["wp-block-image", "size-large"]
        img = soup.new_tag("img")
        img["src"] = url
        img["alt"] = alt
        img["loading"] = "lazy"
        img["style"] = "width:100%;border-radius:14px;margin:26px 0;"
        fig.append(img)
        return fig

    for i in range(need):
        fig = make_img(urls[i % len(urls)], f"{topic} illustration")
        anchor = insert_points[i % len(insert_points)]
        anchor.insert_before(fig)

    return str(soup)


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
# Print-friendly checklist block
# -------------------------
def make_print_checklist_block(title: str) -> str:
    safe_title = html.escape(title.strip() or "This article")
    return f"""
<hr/>
<h2>Quick checklist</h2>
<p>Use this checklist to apply what you learned in <strong>{safe_title}</strong>.</p>
<ol>
  <li>Define the primary goal and success metric.</li>
  <li>List required integrations and data sources.</li>
  <li>Map the minimal workflow (inputs → processing → outputs).</li>
  <li>Set governance: roles, review cadence, and data handling.</li>
  <li>Run a small pilot, review results, then iterate.</li>
</ol>
<p><em>Print tip:</em> use your browser print function (Ctrl/Cmd + P).</p>
""".strip()


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
        "You write high-quality, neutral, informational long-form blog articles about SaaS tools and workflows. "
        "Avoid pricing, avoid exaggerated marketing claims, and keep an approval-friendly tone. "
        "Output MUST be raw HTML only (no markdown, no ``` fences)."
    )

    user = f"""
Write a complete blog article that matches this exact post title:

TITLE: {title}
CATEGORY: {category_name or "SaaS"}

Hard requirements (must follow):
- Output raw HTML only. Do NOT wrap in ``` fences. No markdown.
- 1200–1800 words, structured with <h2>/<h3> headings.
- Neutral, informational tone. No direct pricing: do NOT include '$', 'USD', 'KRW', 'per month', or numeric price figures.
- Include one comparison section if relevant (without pricing).
- Include a concise FAQ (3–5 Q/A).
- Include a short conclusion with a non-pushy CTA (no prices).
- Avoid hype like "best ever", "guaranteed", "must buy", etc.
- Add 2 internal-link anchor sentences naturally in the body referencing these related titles (do not invent URLs): {related_titles}
- Use placeholders for internal links exactly like:
  <a href="{{INTERNAL_LINK_1}}">Title</a> and <a href="{{INTERNAL_LINK_2}}">Title</a>

Return HTML only.
""".strip()

    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.6,
    )
    html_out = (resp.choices[0].message.content or "")
    html_out = strip_markdown_fences(html_out)

    # Fill placeholders with real URLs (best-effort)
    placeholders = {}
    for idx, p in enumerate(related[:2], start=1):
        placeholders[f"{{INTERNAL_LINK_{idx}}}"] = (p.get("link") or "").strip()

    for ph, url in placeholders.items():
        html_out = html_out.replace(ph, url if url else "#")

    # Normalize & add features
    html_out = strip_pricing(html_out)
    html_out = fix_tables(html_out)
    html_out = ensure_body_images(html_out, title)

    html_out = html_out + "\n" + make_related_block(related)
    html_out = html_out + "\n" + make_print_checklist_block(title)

    # CLEAN LEVEL 2
    html_out = clean_level2_html(html_out)

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
    print(f"[INFO] DRY_RUN={DRY_RUN} MAX_FIX={MAX_FIX} MIN_WORDS={MIN_WORDS} INTERNAL_LINKS={INTERNAL_LINKS} BODY_IMAGE_COUNT={BODY_IMAGE_COUNT} TITLE_MATCH_MIN={TITLE_MATCH_MIN} MODEL={MODEL}")
    print(f"[INFO] UNSPLASH={'ON' if bool(UNSPLASH_ACCESS_KEY) else 'OFF'} BACKUP_DIR={BACKUP_DIR}")

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

        flags = should_fix_post(title_html, content_html)
        if not any(flags.values()):
            continue

        cat_ids = p.get("categories") or []
        cat_id = cat_ids[0] if cat_ids else None
        cat_name = cat_map.get(cat_id, "") if cat_id else ""

        related = get_related_posts(cat_id, exclude_id=pid, k=INTERNAL_LINKS)

        title_plain = BeautifulSoup(title_html, "html.parser").get_text(" ", strip=True)
        words = _plain_words(content_html)
        imgc = _body_image_count(content_html)
        print(f"[FLAG] id={pid} words={words} imgs={imgc} cat={cat_name} flags={flags} title={title_plain!r}")

        if not client:
            print("[SKIP] No OPENAI_API_KEY. Cannot regenerate.")
            continue

        new_html = regenerate_article(title_html, cat_name, related)
        new_words = _plain_words(new_html)
        new_imgc = _body_image_count(new_html)
        print(f"[GEN ] id={pid} regenerated_words={new_words} regenerated_imgs={new_imgc}")

        if DRY_RUN:
            print(f"[DRY ] Would update post id={pid}")
        else:
            backup_path = backup_post_html(pid, title_html, content_html)
            print(f"[BAK ] Saved original HTML -> {backup_path}")
            _wp_update_post(pid, {"content": new_html})
            print(f"[OK  ] Updated post id={pid}")

        fixed += 1
        if fixed >= MAX_FIX:
            print("[DONE] Reached MAX_FIX limit.")
            break

    print(f"[DONE] fixed={fixed} (DRY_RUN={DRY_RUN})")


if __name__ == "__main__":
    main()
