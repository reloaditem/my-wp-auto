import os, re, random, requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
from requests.auth import HTTPBasicAuth
from openai import OpenAI

# ==============================
# ENV
# ==============================
WP_BASE = os.environ.get("WP_BASE", "https://reloaditem.com").rstrip("/")
WP_USER = os.environ["WP_USER"]
WP_PASS = os.environ["WP_PASS"]
OPENAI_KEY = os.environ["OPENAI_API_KEY"]

UNSPLASH_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "").strip()
FEATURED_MEDIA_ID = int(os.environ.get("FEATURED_MEDIA_ID", "332"))  # 공통 썸네일

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

# 예약
POST_HOUR = int(os.environ.get("POST_HOUR", "10"))
POST_MINUTE = int(os.environ.get("POST_MINUTE", "0"))
DAYS_AHEAD_START = int(os.environ.get("DAYS_AHEAD_START", "1"))
POST_COUNT = int(os.environ.get("POST_COUNT", "1"))

# 제목 중복 회피(최근 N개)
RECENT_TITLE_WINDOW = int(os.environ.get("RECENT_TITLE_WINDOW", "50"))

WP_POST_URL = f"{WP_BASE}/wp-json/wp/v2/posts"
WP_CAT_URL  = f"{WP_BASE}/wp-json/wp/v2/categories"
AUTH = HTTPBasicAuth(WP_USER, WP_PASS)
client = OpenAI(api_key=OPENAI_KEY)

# ==============================
# Helpers
# ==============================
def strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()

def normalize_title(t: str) -> str:
    t = strip_tags(t)
    t = re.sub(r"\s+", " ", t).strip().lower()
    return t

def wp_get(url: str):
    return requests.get(url, auth=AUTH, timeout=40)

def wp_post(url: str, json_data: dict):
    return requests.post(url, auth=AUTH, json=json_data, timeout=60)

def fetch_categories() -> List[dict]:
    out = []
    page = 1
    while True:
        url = f"{WP_CAT_URL}?per_page=100&page={page}"
        r = wp_get(url)
        if r.status_code != 200:
            break
        out.extend(r.json() or [])
        total_pages = int(r.headers.get("X-WP-TotalPages", "1"))
        if page >= total_pages:
            break
        page += 1
    # "uncategorized" 같은 건 빼고 싶으면 여기서 필터 가능
    out = [c for c in out if c.get("slug") and c.get("id")]
    return out

def fetch_recent_titles() -> Set[str]:
    titles = set()
    for status in ("publish", "future"):
        r = wp_get(f"{WP_POST_URL}?status={status}&per_page=50")
        if r.status_code != 200:
            continue
        for p in (r.json() or []):
            titles.add(normalize_title(p.get("title", {}).get("rendered", "")))
    return titles

# ==============================
# Schedule: 10:00 + collision avoid
# ==============================
def get_future_dates_set():
    r = wp_get(WP_POST_URL + "?status=future&per_page=100")
    used = set()
    if r.status_code != 200:
        return used
    for p in (r.json() or []):
        try:
            used.add(datetime.fromisoformat(p["date"]).replace(tzinfo=None))
        except Exception:
            pass
    return used

def next_available_10am(start_day: datetime, used: set):
    d = start_day.replace(hour=POST_HOUR, minute=POST_MINUTE, second=0, microsecond=0)
    while d in used:
        d += timedelta(days=1)
    used.add(d)
    return d

# ==============================
# Inline images
# ==============================
def unsplash_random(query: str) -> str:
    if not UNSPLASH_KEY:
        return ""
    q = requests.utils.quote(query)
    api = f"https://api.unsplash.com/photos/random?query={q}&orientation=landscape&client_id={UNSPLASH_KEY}"
    r = requests.get(api, timeout=20)
    if r.status_code == 200:
        return (r.json().get("urls") or {}).get("regular") or ""
    return ""

def pick_inline_urls(title: str):
    q1 = title
    q2 = f"{title} software dashboard"
    q3 = f"{title} checklist"

    urls = []
    for q in (q1, q2, q3):
        u = unsplash_random(q)
        if u:
            urls.append(u)

    if len(urls) == 3:
        return urls

    seed = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "ai-tools"
    return [
        f"https://picsum.photos/seed/{seed}-top/1200/800",
        f"https://picsum.photos/seed/{seed}-mid/1200/800",
        f"https://picsum.photos/seed/{seed}-bot/1200/800",
    ]

def img_block(url: str, alt: str) -> str:
    return (
        f'<figure style="margin:28px 0;">'
        f'<img src="{url}" alt="{alt}" style="width:100%;height:auto;border-radius:14px;" loading="lazy" />'
        f'</figure>'
    )

# ==============================
# Checklist
# ==============================
def checklist_html() -> str:
    return "\n".join([
        "<h2>Save / Print Checklist</h2>",
        "[rp_intro_checklist_v1]",
        "<ul>",
        "<li><strong>Pick 2–3 tools</strong> that match your budget and workflow.</li>",
        "<li><strong>Confirm must-have features</strong> (integrations, automation, reporting).</li>",
        "<li><strong>Check pricing</strong>: add-ons, limits, annual discounts.</li>",
        "<li><strong>Run a 7-day test</strong> with one real workflow end-to-end.</li>",
        "<li><strong>Decide & document</strong> success metrics and next steps.</li>",
        "</ul>",
        '[rp_save_print_v1 label="Open print window" sub="In the print window, you can save as PDF or print a copy."]',
    ])

# ==============================
# OpenAI: title generation + article generation
# ==============================
def call_openai(messages):
    resp = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=0.6,
    )
    return resp.choices[0].message.content.strip()

def generate_title(recent_titles: Set[str]) -> str:
    # 최근 제목 10개만 힌트로 넣고, 중복 피하게
    hint = ", ".join(list(recent_titles)[:10]) if recent_titles else ""
    messages = [
        {
            "role": "system",
            "content": (
                "You create SEO blog post titles for a SaaS/AI tools blog.\n"
                "Return ONLY one title line.\n"
                "Constraints:\n"
                "- Must be useful for small businesses.\n"
                "- Include the year 2026.\n"
                "- Prefer: Best / Comparison / Pricing / Guide / Alternatives.\n"
                "- Keep it <= 75 characters.\n"
                "- No quotes.\n"
            )
        },
        {
            "role": "user",
            "content": f"Recent titles to avoid: {hint}\nGenerate ONE new title:"
        }
    ]
    title = call_openai(messages).splitlines()[0].strip()
    if len(title) > 75:
        title = title[:74].rstrip() + "…"
    return title

def generate_article(title: str) -> str:
    messages = [
        {
            "role": "system",
            "content": (
                "You are a professional SaaS reviewer writing for small businesses.\n"
                "Write a detailed SEO article (minimum ~1500 words).\n"
                "Use clean HTML only (no markdown).\n"
                "Include: pricing, pros/cons, a comparison table, who this is for, how we evaluate, disclosure, FAQs.\n"
                "In the INTRO, add a short note that a save/print-friendly checklist is included at the end using shortcode [rp_intro_checklist_v1].\n"
                "Insert placeholders naturally: [IMAGE_TOP], [IMAGE_MID], [IMAGE_BOT].\n"
                "At the END, include a section titled 'Save / Print Checklist' and include shortcode [rp_save_print_v1].\n"
                "Avoid overly promotional tone. Be specific and structured."
            )
        },
        {"role": "user", "content": f"Title: {title}\nWrite the article:"}
    ]
    return call_openai(messages)

# ==============================
# Publish
# ==============================
def publish_article(title: str, content: str, category_id: Optional[int], publish_date: datetime):
    u1, u2, u3 = pick_inline_urls(title)
    content = content.replace("[IMAGE_TOP]", img_block(u1, f"{title} cover"))
    content = content.replace("[IMAGE_MID]", img_block(u2, f"{title} example"))
    content = content.replace("[IMAGE_BOT]", img_block(u3, f"{title} checklist"))

    if "Save / Print Checklist" not in strip_tags(content):
        content = content.rstrip() + "\n" + checklist_html() + "\n"

    payload = {
        "title": title,
        "content": content,
        "status": "future",
        "date": publish_date.isoformat(),
        "featured_media": FEATURED_MEDIA_ID,
    }
    if category_id:
        payload["categories"] = [category_id]

    r = wp_post(WP_POST_URL, payload)
    print("WP:", r.status_code, "|", title, "->", publish_date.isoformat(), "| cat:", category_id)
    if r.status_code not in (200, 201):
        print(r.text[:400])

def main():
    cats = fetch_categories()
    if not cats:
        raise RuntimeError("No categories found. Check WP credentials/permissions.")

    recent_titles = fetch_recent_titles()
    used_times = get_future_dates_set()
    start_day = datetime.now() + timedelta(days=DAYS_AHEAD_START)

    for _ in range(POST_COUNT):
        cat = random.choice(cats)
        cat_id = int(cat["id"])
        cat_slug = cat.get("slug", "")

        # 제목 생성 + 중복 회피(최대 3번 재시도)
        title = None
        for _try in range(3):
            cand = generate_title(recent_titles)
            if normalize_title(cand) not in recent_titles:
                title = cand
                break
        if not title:
            title = generate_title(recent_titles)

        recent_titles.add(normalize_title(title))

        publish_date = next_available_10am(start_day, used_times)
        start_day = publish_date + timedelta(days=1)

        print("Category:", cat_slug, "->", cat_id)
        print("Generating:", title)
        content = generate_article(title)

        publish_article(title, content, cat_id, publish_date)

if __name__ == "__main__":
    main()
