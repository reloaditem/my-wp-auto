import os
import re
import json
import random
import requests
from datetime import datetime, timedelta
from typing import List, Optional, Set
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
FEATURED_MEDIA_ID = int(os.environ.get("FEATURED_MEDIA_ID", "332"))
MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

POST_HOUR = int(os.environ.get("POST_HOUR", "10"))
POST_MINUTE = int(os.environ.get("POST_MINUTE", "0"))
DAYS_AHEAD_START = int(os.environ.get("DAYS_AHEAD_START", "1"))
CLUSTER_COUNT = int(os.environ.get("CLUSTER_COUNT", "1"))

EXCLUDE_CATEGORY_SLUGS = set(
    s.strip() for s in os.environ.get("EXCLUDE_CATEGORY_SLUGS", "").split(",") if s.strip()
)

WP_POST_URL = f"{WP_BASE}/wp-json/wp/v2/posts"
WP_CAT_URL = f"{WP_BASE}/wp-json/wp/v2/categories"
AUTH = HTTPBasicAuth(WP_USER, WP_PASS)

client = OpenAI(api_key=OPENAI_KEY)

# ==============================
# Helpers
# ==============================
IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.I)

def strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()

def normalize_title(t: str) -> str:
    t = strip_tags(t)
    t = re.sub(r"\s+", " ", t).strip().lower()
    return t

def wp_get(url: str):
    return requests.get(url, auth=AUTH, timeout=50)

def wp_post(url: str, json_data: dict):
    return requests.post(url, auth=AUTH, json=json_data, timeout=90)

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
    out = [c for c in out if c.get("slug") and c.get("id")]
    out = [c for c in out if c.get("slug") not in EXCLUDE_CATEGORY_SLUGS]
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
# Images
# ==============================
def unsplash_random(query: str) -> str:
    if not UNSPLASH_KEY:
        return ""
    q = requests.utils.quote(query)
    api = (
        f"https://api.unsplash.com/photos/random"
        f"?query={q}&orientation=landscape&client_id={UNSPLASH_KEY}"
    )
    r = requests.get(api, timeout=20)
    if r.status_code == 200:
        return (r.json().get("urls") or {}).get("regular") or ""
    return ""

def pick_inline_urls(title: str):
    q1 = title
    q2 = f"{title} software dashboard"
    q3 = f"{title} workflow automation"

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
        f"</figure>"
    )

# ==============================
# PartnerStack-safe: 가격 금액 제거(후처리)
# ==============================
CURRENCY_RE = re.compile(
    r"(\$|€|£|₩)\s?\d[\d,]*(?:\.\d+)?|\d[\d,]*(?:\.\d+)?\s?(\$|€|£|₩)",
    re.I
)
PER_RE = re.compile(r"\b(per\s+(month|mo|year|yr)|/mo|/month|/yr|/year)\b", re.I)

def sanitize_pricing(html: str) -> str:
    """
    - 정확한 금액/통화 표기를 제거
    - 'per month' 같은 표현도 완화
    """
    html = CURRENCY_RE.sub("pricing varies", html)
    html = PER_RE.sub("", html)
    # 표 안에 남는 'pricing varies'가 너무 많으면 읽기 어려우니 약간 정리
    html = re.sub(r"\bpricing varies\b(?:\s*-\s*pricing varies\b)+", "pricing varies", html, flags=re.I)
    return html

# ==============================
# Checklist (저장/출력)
# ==============================
def checklist_html() -> str:
    return "\n".join(
        [
            "<h2>Save / Print Checklist</h2>",
            "[rp_intro_checklist_v1]",
            "<ul>",
            "<li><strong>Pick 2–3 tools</strong> that match your budget and workflow.</li>",
            "<li><strong>Confirm must-have features</strong> (integrations, automation, reporting).</li>",
            "<li><strong>Check pricing structure</strong>: limits, add-ons, annual discounts.</li>",
            "<li><strong>Run a 7-day test</strong> with one real workflow end-to-end.</li>",
            "<li><strong>Decide & document</strong> success metrics and next steps.</li>",
            "</ul>",
            '[rp_save_print_v1 label="Open print window" sub="In the print window, you can save as PDF or print a copy."]',
        ]
    )

# ==============================
# Internal link block
# ==============================
def make_link_block(list_url: str, comp_url: str, deep_url: str) -> str:
    return "\n".join(
        [
            '<div class="rp-related" style="border:1px solid rgba(0,0,0,.08);padding:14px 16px;border-radius:12px;margin:18px 0;">',
            "<strong>Related in this series</strong>",
            "<ul>",
            f'<li><a href="{list_url}">Start here: Best tools list</a></li>',
            f'<li><a href="{comp_url}">Compare: A vs B vs C</a></li>',
            f'<li><a href="{deep_url}">Deep dive: pricing & setup guide</a></li>',
            "</ul>",
            "<p style='margin:10px 0 0;'>Tip: Use the checklist at the end to save as PDF or print.</p>",
            "</div>",
        ]
    )

# ==============================
# OpenAI
# ==============================
def call_openai(messages):
    resp = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=0.6,
    )
    return resp.choices[0].message.content.strip()

def gen_cluster_plan(recent_titles: Set[str]) -> dict:
    avoid = ", ".join(list(recent_titles)[:12]) if recent_titles else ""
    messages = [
        {
            "role": "system",
            "content": (
                "You plan a 3-post topical cluster for a SaaS/AI tools blog.\n"
                "Return ONLY valid JSON with keys: topic, list_title, comparison_title, deep_title, tools, deep_tool.\n"
                "Constraints:\n"
                "- All titles must include year 2026.\n"
                "- list_title: starts with 'Best' and is list-style.\n"
                "- comparison_title: contains 'vs' and compares exactly 3 tools.\n"
                "- deep_title: is a deep dive on the FIRST tool (tools[0]) and mentions 'Pricing' or 'Guide'.\n"
                "- Keep each title <= 75 characters.\n"
                "- Tools should be realistic SaaS products.\n"
                "- No quotes in titles.\n"
            ),
        },
        {"role": "user", "content": f"Recent titles to avoid: {avoid}\nGenerate ONE cluster JSON:"},
    ]
    raw = call_openai(messages).strip()
    raw = raw[raw.find("{") : raw.rfind("}") + 1]
    return json.loads(raw)

def article_prompt_base() -> str:
    # ✅ 가격은 “구조/포인트”만, 정확한 금액은 절대 금지
    return (
        "You are a professional SaaS reviewer writing for small businesses.\n"
        "Write a detailed SEO article (minimum ~1500 words).\n"
        "Use clean HTML only (no markdown).\n"
        "Pricing rules (IMPORTANT):\n"
        "- Do NOT include exact prices or currency amounts ($, €, £, ₩, numbers like $29, 29/mo, etc.).\n"
        "- Describe pricing as plan structure (Free / Starter / Pro / Enterprise), limits, and what to verify.\n"
        "- Use phrases like 'pricing varies' and 'check the official pricing page'.\n"
        "Include: pros/cons, a comparison table (NO exact prices), who this is for, how we evaluate, disclosure, FAQs.\n"
        "In the INTRO, add a short note that a save/print-friendly checklist is included at the end using shortcode [rp_intro_checklist_v1].\n"
        "At the END, include a section titled 'Save / Print Checklist' and include shortcode [rp_save_print_v1].\n"
        "Avoid overly promotional tone. Be specific and structured.\n"
    )

def generate_article(title: str, role: str, tools: List[str]) -> str:
    """
    role: 'list' | 'comparison' | 'deep'
    tools: ["A","B","C"]  (deep: A=tools[0], alternatives=B,C)
    """
    A, B, C = tools[0], tools[1], tools[2]

    if role == "list":
        link_rules = (
            "Add 2–3 contextual internal links in the body using these placeholders exactly:\n"
            "- [[LINK_COMP]] once\n"
            "- [[LINK_DEEP]] once\n"
            'Format example: <a href="[[LINK_COMP]]">see the full comparison</a>\n'
        )
    elif role == "comparison":
        link_rules = (
            "Add 2–3 contextual internal links in the body using these placeholders exactly:\n"
            "- [[LINK_LIST]] once\n"
            "- [[LINK_DEEP]] once\n"
        )
    else:  # deep
        link_rules = (
            "Add 2–3 contextual internal links in the body using these placeholders exactly:\n"
            "- [[LINK_LIST]] once\n"
            "- [[LINK_COMP]] once\n"
            "Also include an 'Alternatives' section that links the alternatives to the comparison using placeholders:\n"
            f'- Mention {B} as <a href="[[ALT_B]]">{B}</a>\n'
            f'- Mention {C} as <a href="[[ALT_C]]">{C}</a>\n'
        )

    cluster_context = (
        "Cluster context:\n"
        f"- Primary tool (deep dive): {A}\n"
        f"- Alternatives: {B}, {C}\n"
    )

    messages = [
        {"role": "system", "content": article_prompt_base()},
        {
            "role": "user",
            "content": (
                f"Title: {title}\n"
                f"{cluster_context}\n"
                f"{link_rules}\n"
                "IMPORTANT: Do not include exact currency amounts.\n"
                "HTML only.\n"
                "Now write the article:"
            ),
        },
    ]
    return call_openai(messages)

# ==============================
# Image placement fix (강제 3곳 삽입)
# ==============================
def insert_images_strategic(html: str, blocks: List[str]) -> str:
    """
    무조건 3개를 '상단/중간/하단'에 분산 삽입.
    - 상단: 첫 </p> 뒤
    - 중간: 2번째 <h2> 뒤 (없으면 첫 <h2> 뒤)
    - 하단: 체크리스트(또는 Conclusion/FAQs) 앞쪽
    """
    if not html:
        return "\n".join(blocks)

    # 기존 이미지가 3장 이상이면 굳이 더 넣지 않음(중복 방지)
    if len(IMG_TAG_RE.findall(html)) >= 3:
        return html

    # 1) 상단 삽입
    top = blocks[0]
    m = re.search(r"</p\s*>", html, flags=re.I)
    if m:
        i = m.end()
        html = html[:i] + "\n" + top + "\n" + html[i:]
    else:
        html = top + "\n" + html

    # 2) 중간 삽입: h2 찾기
    h2_iter = list(re.finditer(r"<h2\b[^>]*>", html, flags=re.I))
    mid = blocks[1]
    if len(h2_iter) >= 2:
        # 2번째 h2 태그 뒤쪽에 넣기
        pos = h2_iter[1].start()
        html = html[:pos] + mid + "\n" + html[pos:]
    elif len(h2_iter) == 1:
        pos = h2_iter[0].start()
        html = html[:pos] + mid + "\n" + html[pos:]
    else:
        # h2가 없으면 대충 중간쯤
        pos = max(0, len(html)//2)
        html = html[:pos] + "\n" + mid + "\n" + html[pos:]

    # 3) 하단 삽입: 체크리스트/FAQ/Conclusion 앞
    bot = blocks[2]
    anchor = re.search(r"<h2\b[^>]*>\s*(Save\s*/\s*Print\s*Checklist|FAQ|FAQs|Conclusion)\b", html, flags=re.I)
    if anchor:
        pos = anchor.start()
        html = html[:pos] + bot + "\n" + html[pos:]
    else:
        html = html.rstrip() + "\n" + bot + "\n"

    return html

# ==============================
# Publish / Update
# ==============================
def publish_future_post(
    title: str, content: str, category_id: int, publish_date: datetime
) -> Optional[dict]:
    # 1) 가격 금액 제거 후처리
    content = sanitize_pricing(content)

    # 2) 이미지 URL 준비 + 강제 분산 삽입
    u1, u2, u3 = pick_inline_urls(title)
    blocks = [
        img_block(u1, f"{title} cover"),
        img_block(u2, f"{title} example"),
        img_block(u3, f"{title} workflow"),
    ]
    content = insert_images_strategic(content, blocks)

    # 3) 체크리스트 보장
    if "Save / Print Checklist" not in strip_tags(content):
        content = content.rstrip() + "\n" + checklist_html() + "\n"

    payload = {
        "title": title,
        "content": content,
        "status": "future",
        "date": publish_date.isoformat(),
        "featured_media": FEATURED_MEDIA_ID,
        "categories": [category_id],
    }
    r = wp_post(WP_POST_URL, payload)
    print("WP:", r.status_code, "|", title, "->", publish_date.isoformat(), "| cat:", category_id)
    if r.status_code in (200, 201):
        return r.json()
    print(r.text[:600])
    return None

def inject_and_update(post_json: dict, list_url: str, comp_url: str, deep_url: str, tools: List[str]):
    post_id = post_json["id"]
    content = post_json["content"]["rendered"]

    # placeholder 치환
    content = content.replace('href="[[LINK_LIST]]"', f'href="{list_url}"')
    content = content.replace('href="[[LINK_COMP]]"', f'href="{comp_url}"')
    content = content.replace('href="[[LINK_DEEP]]"', f'href="{deep_url}"')

    # alternatives는 comparison으로 유도
    content = content.replace('href="[[ALT_B]]"', f'href="{comp_url}"')
    content = content.replace('href="[[ALT_C]]"', f'href="{comp_url}"')

    content = content.replace("[[LINK_LIST]]", list_url)
    content = content.replace("[[LINK_COMP]]", comp_url)
    content = content.replace("[[LINK_DEEP]]", deep_url)
    content = content.replace("[[ALT_B]]", comp_url)
    content = content.replace("[[ALT_C]]", comp_url)

    # 상단 링크박스 1회 삽입
    if 'class="rp-related"' not in content:
        link_block = make_link_block(list_url, comp_url, deep_url)
        m = re.search(r"</p\s*>", content, flags=re.I)
        if m:
            i = m.end()
            content = content[:i] + "\n" + link_block + "\n" + content[i:]
        else:
            content = link_block + "\n" + content

    r = wp_post(f"{WP_POST_URL}/{post_id}", {"content": content})
    print("Link update:", post_id, r.status_code)

# ==============================
# Main
# ==============================
def main():
    cats = fetch_categories()
    if not cats:
        raise RuntimeError("No categories found. Check WP credentials/permissions or exclusions.")

    recent_titles = fetch_recent_titles()
    used_times = get_future_dates_set()
    start_day = datetime.now() + timedelta(days=DAYS_AHEAD_START)

    for cluster_i in range(CLUSTER_COUNT):
        cat = random.choice(cats)
        cat_id = int(cat["id"])
        cat_slug = cat.get("slug", "")

        plan = gen_cluster_plan(recent_titles)

        list_title = (plan.get("list_title") or "").strip()
        comp_title = (plan.get("comparison_title") or "").strip()
        deep_title = (plan.get("deep_title") or "").strip()
        tools = plan.get("tools") or []
        if len(tools) != 3 or not list_title or not comp_title or not deep_title:
            raise RuntimeError(f"Bad cluster plan: {plan}")

        for t in (list_title, comp_title, deep_title):
            recent_titles.add(normalize_title(t))

        d1 = next_available_10am(start_day, used_times)
        d2 = next_available_10am(d1 + timedelta(days=1), used_times)
        d3 = next_available_10am(d2 + timedelta(days=1), used_times)
        start_day = d3 + timedelta(days=1)

        print(f"\n[Cluster #{cluster_i+1}] category={cat_slug}({cat_id})")
        print(" - LIST:", list_title, "=>", d1.date())
        print(" - COMP:", comp_title, "=>", d2.date())
        print(" - DEEP:", deep_title, "=>", d3.date())
        print(" - TOOLS:", tools)

        p1 = publish_future_post(list_title, generate_article(list_title, "list", tools), cat_id, d1)
        p2 = publish_future_post(comp_title, generate_article(comp_title, "comparison", tools), cat_id, d2)
        p3 = publish_future_post(deep_title, generate_article(deep_title, "deep", tools), cat_id, d3)

        if not (p1 and p2 and p3):
            print("Cluster publish failed; skipping link update.")
            continue

        list_url = p1.get("link")
        comp_url = p2.get("link")
        deep_url = p3.get("link")
        if not (list_url and comp_url and deep_url):
            print("Missing post links; skipping link update.")
            continue

        inject_and_update(p1, list_url, comp_url, deep_url, tools)
        inject_and_update(p2, list_url, comp_url, deep_url, tools)
        inject_and_update(p3, list_url, comp_url, deep_url, tools)

if __name__ == "__main__":
    main()
