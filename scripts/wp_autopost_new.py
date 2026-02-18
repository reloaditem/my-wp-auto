import os, re, random, requests
from datetime import datetime, timedelta
from typing import Optional
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
FEATURED_MEDIA_ID = int(os.environ.get("FEATURED_MEDIA_ID", "332"))  # 공통 썸네일(배경)

# 예약 정책
POST_HOUR = int(os.environ.get("POST_HOUR", "10"))
POST_MINUTE = int(os.environ.get("POST_MINUTE", "0"))
DAYS_AHEAD_START = int(os.environ.get("DAYS_AHEAD_START", "1"))
POST_COUNT = int(os.environ.get("POST_COUNT", "1"))  # 한 번 실행 시 몇 개 생성할지

# OpenAI 모델
MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

WP_POST_URL = f"{WP_BASE}/wp-json/wp/v2/posts"
AUTH = HTTPBasicAuth(WP_USER, WP_PASS)
client = OpenAI(api_key=OPENAI_KEY)

CATEGORY_SLUGS = [
    "crm-software",
    "automation-tools",
    "marketing-ai",
    "ai-productivity",
]

# ==============================
# Helpers
# ==============================
def strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()

def wp_get(url: str):
    r = requests.get(url, auth=AUTH, timeout=30)
    return r

def wp_post(url: str, json_data: dict):
    r = requests.post(url, auth=AUTH, json=json_data, timeout=40)
    return r

def get_category_id(slug: str) -> Optional[int]:
    url = f"{WP_BASE}/wp-json/wp/v2/categories?slug={slug}"
    r = requests.get(url, auth=AUTH, timeout=30)
    if r.status_code == 200 and r.json():
        return r.json()[0]["id"]
    return None

# ==============================
# Schedule: 10:00 + collision avoid
# ==============================
def get_future_dates_set():
    r = wp_get(WP_POST_URL + "?status=future&per_page=100")
    if r.status_code != 200:
        return set()
    used = set()
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
# Unsplash inline images (topic-based)
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

    # fallback (always works)
    seeds = [
        f"{re.sub(r'\\s+','-',title.lower())[:40]}-top",
        f"{re.sub(r'\\s+','-',title.lower())[:40]}-mid",
        f"{re.sub(r'\\s+','-',title.lower())[:40]}-bot",
    ]
    return [f"https://picsum.photos/seed/{s}/1200/800" for s in seeds]

def img_block(url: str, alt: str) -> str:
    return (
        f'<figure style="margin:28px 0;">'
        f'<img src="{url}" alt="{alt}" style="width:100%;height:auto;border-radius:14px;" loading="lazy" />'
        f'</figure>'
    )

# ==============================
# Checklist blocks (3번 포함)
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
# OpenAI generate article (HTML)
# ==============================
def call_openai(messages):
    resp = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=0.6,
    )
    return resp.choices[0].message.content.strip()

def generate_article(topic: str) -> str:
    messages = [
        {
            "role": "system",
            "content": (
                "You are a professional SaaS reviewer writing for small businesses.\n"
                "Write a detailed SEO article (minimum ~1500 words).\n"
                "Use clean HTML only (no markdown).\n"
                "Include: pricing, pros/cons, a comparison table, who this is for, how we evaluate, disclosure, FAQs.\n"
                "In the INTRO, add a short note that a save/print-friendly checklist is included at the end using shortcode [rp_intro_checklist_v1].\n"
                "Insert these placeholders naturally in the content: [IMAGE_TOP], [IMAGE_MID], [IMAGE_BOT].\n"
                "At the END, include a section titled 'Save / Print Checklist' and include shortcode [rp_save_print_v1].\n"
                "Avoid overly promotional tone. Be specific and structured."
            )
        },
        {"role": "user", "content": f"Write about: {topic}"}
    ]
    return call_openai(messages)

# ==============================
# Publish (schedule future)
# ==============================
def publish_article(title: str, content: str, category_slug: str, publish_date: datetime):
    category_id = get_category_id(category_slug)

    # inline images
    u1, u2, u3 = pick_inline_urls(title)
    content = content.replace("[IMAGE_TOP]", img_block(u1, f"{title} cover"))
    content = content.replace("[IMAGE_MID]", img_block(u2, f"{title} example"))
    content = content.replace("[IMAGE_BOT]", img_block(u3, f"{title} checklist"))

    # ensure checklist at end (safety)
    if "Save / Print Checklist" not in strip_tags(content):
        content = content.rstrip() + "\n" + checklist_html() + "\n"

    payload = {
        "title": title,
        "content": content,
        "status": "future",
        "date": publish_date.isoformat(),
        "categories": [category_id] if category_id else [],
        "featured_media": FEATURED_MEDIA_ID,
    }

    r = wp_post(WP_POST_URL, payload)
    print("WP:", r.status_code, title, "->", publish_date.isoformat())
    if r.status_code not in (200, 201):
        print(r.text[:400])

def main():
    # 네가 원하면 토픽을 여기서 계속 확장 가능
    topics = [
        "Best AI Tools for Small Business Customer Support (2026)",
        "Best AI Email Marketing Tools (2026): Automation, Segmentation, Deliverability",
        "Zapier vs Make vs n8n (2026): Best Automation Tool for SMB Workflows",
        "Best AI Meeting Assistants (2026): Notes, Transcription, Action Items",
        "Notion AI vs ClickUp AI vs Asana AI (2026): Best for Small Teams",
    ]
    random.shuffle(topics)

    used = get_future_dates_set()
    start_day = datetime.now() + timedelta(days=DAYS_AHEAD_START)

    for i in range(POST_COUNT):
        topic = topics[i % len(topics)]
        category_slug = random.choice(CATEGORY_SLUGS)

        publish_date = next_available_10am(start_day, used)
        start_day = publish_date + timedelta(days=1)

        print("Generating:", topic)
        article = generate_article(topic)
        publish_article(topic, article, category_slug, publish_date)

if __name__ == "__main__":
    main()
