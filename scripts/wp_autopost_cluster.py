import os
import re
import random
import requests
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple
from requests.auth import HTTPBasicAuth
from bs4 import BeautifulSoup
from openai import OpenAI
from PIL import Image
import io

# =========================
# ENV (레포 시크릿명 그대로)
# =========================
WP_BASE = os.environ.get("WP_BASE", "").rstrip("/")
WP_USER = os.environ.get("WP_USER", "")
WP_PASS = os.environ.get("WP_PASS", "")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

UNSPLASH_ACCESS_KEY = (os.environ.get("UNSPLASH_ACCESS_KEY") or "").strip()

POST_HOUR = int((os.environ.get("POST_HOUR") or "10").strip())
POST_MINUTE = int((os.environ.get("POST_MINUTE") or "0").strip())

# 클러스터(3개 1세트) 몇 세트 만들지
CLUSTER_COUNT = int((os.environ.get("CLUSTER_COUNT") or "1").strip())

# 빈값("")으로 들어오면 터지던 문제 방지
DAYS_AHEAD_START = int((os.environ.get("DAYS_AHEAD_START") or "1").strip())

# 월~토만(일요일 스킵): 0=월 ... 6=일
ALLOWED_WEEKDAYS = set(int(x.strip()) for x in (os.environ.get("ALLOWED_WEEKDAYS") or "0,1,2,3,4,5").split(",") if x.strip())

BRAND_TEXT = (os.environ.get("BRAND_TEXT") or "RELOADITEM").strip()
FOOTER_TEXT = (os.environ.get("FOOTER_TEXT") or "AI TOOLS").strip()

if not (WP_BASE and WP_USER and WP_PASS):
    raise SystemExit("Missing env: WP_BASE, WP_USER, WP_PASS")
if not OPENAI_API_KEY:
    raise SystemExit("Missing env: OPENAI_API_KEY")

AUTH = HTTPBasicAuth(WP_USER, WP_PASS)
WP_API = f"{WP_BASE}/wp-json/wp/v2"
POSTS_URL = f"{WP_API}/posts"
MEDIA_URL = f"{WP_API}/media"
CATS_URL = f"{WP_API}/categories"

client = OpenAI(api_key=OPENAI_API_KEY)

# =========================
# 카테고리 슬러그
# =========================
CATEGORY_SLUGS = [
    "crm-software",
    "automation-tools",
    "marketing-ai",
    "ai-productivity",
]

def keyword_from_slug(slug: str) -> str:
    m = {
        "crm-software": "CRM",
        "automation-tools": "AUTOMATION",
        "marketing-ai": "MARKETING",
        "ai-productivity": "PRODUCTIVITY",
    }
    return m.get(slug, "AI TOOLS")

# =========================
# WordPress helpers
# =========================
def wp_get(url: str, params: Optional[dict] = None):
    return requests.get(url, params=params, auth=AUTH, timeout=60)

def wp_post(url: str, json_data: dict):
    return requests.post(url, json=json_data, auth=AUTH, timeout=90)

def get_category_id(slug: str) -> Optional[int]:
    r = wp_get(CATS_URL, params={"slug": slug})
    if r.status_code == 200 and r.json():
        return int(r.json()[0]["id"])
    return None

def get_last_scheduled_date() -> datetime:
    r = wp_get(POSTS_URL, params={"status": "future", "per_page": 100})
    if r.status_code != 200:
        return datetime.now()
    posts = r.json() or []
    if not posts:
        return datetime.now()
    # WP가 ISO 문자열로 줌
    dates = []
    for p in posts:
        try:
            dates.append(datetime.fromisoformat(p["date"]))
        except Exception:
            pass
    return max(dates) if dates else datetime.now()

def next_available_10am(start_day: datetime, used: set):
    d = start_day.replace(hour=POST_HOUR, minute=POST_MINUTE, second=0, microsecond=0)
    while True:
        if d.weekday() not in ALLOWED_WEEKDAYS:
            d += timedelta(days=1)
            d = d.replace(hour=POST_HOUR, minute=POST_MINUTE, second=0, microsecond=0)
            continue
        if d in used:
            d += timedelta(days=1)
            d = d.replace(hour=POST_HOUR, minute=POST_MINUTE, second=0, microsecond=0)
            continue
        used.add(d)
        return d

# =========================
# 썸네일 생성 (블랙+골드)
# =========================
def _get_font(size: int, bold: bool = True):
    try:
        from PIL import ImageFont
        p = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        if os.path.exists(p):
            return ImageFont.truetype(p, size=size)
        return ImageFont.load_default()
    except Exception:
        return None

def _wrap_lines(draw, text: str, font, max_width: int, max_lines: int = 2):
    words = re.sub(r"\s+", " ", text.strip()).split(" ")
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if draw.textlength(test, font=font) <= max_width:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while draw.textlength(last + "…", font=font) > max_width and len(last) > 0:
            last = last[:-1].rstrip()
        lines[-1] = (last + "…") if last else "…"
    return lines

def make_brand_thumbnail_square(keyword: str, brand: str, footer: str, size: int = 1200) -> Image.Image:
    from PIL import ImageDraw
    W = H = size
    img = Image.new("RGB", (W, H), (10, 10, 12))
    draw = ImageDraw.Draw(img)

    gold = (198, 154, 68)
    off = (245, 245, 245)

    pad = int(W * 0.05)
    frame_w = max(3, int(W * 0.006))
    draw.rounded_rectangle((pad, pad, W-pad, H-pad), radius=int(W*0.03), outline=gold, width=frame_w)

    pad2 = pad + int(W * 0.02)
    draw.rounded_rectangle((pad2, pad2, W-pad2, H-pad2), radius=int(W*0.028), outline=(70, 70, 78), width=max(2, frame_w//2))

    header_font = _get_font(int(W * 0.06), bold=True)
    footer_font = _get_font(int(W * 0.045), bold=False)

    hx = pad2 + int(W*0.03)
    hy = pad2 + int(H*0.06)
    draw.text((hx, hy), brand.upper(), font=header_font, fill=off)

    line_y = hy + int(W*0.09)
    draw.line((hx, line_y, W - pad2 - int(W*0.03), line_y), fill=gold, width=max(3, int(W*0.004)))

    kw = (keyword or "AI TOOLS").upper()
    max_width = W - 2*(pad2 + int(W*0.05))
    kw_font = _get_font(int(W*0.13), bold=True)
    lines = _wrap_lines(draw, kw, kw_font, max_width, max_lines=2)
    while any(draw.textlength(ln, font=kw_font) > max_width for ln in lines) and kw_font.size > 28:
        kw_font = _get_font(max(28, kw_font.size - 4), bold=True)
        lines = _wrap_lines(draw, kw, kw_font, max_width, max_lines=2)

    line_h = int(kw_font.size * 1.12)
    total_h = line_h * len(lines)
    start_y = int(H*0.50) - total_h//2
    for i, ln in enumerate(lines):
        lw = draw.textlength(ln, font=kw_font)
        x = (W - lw)//2
        y = start_y + i*line_h
        draw.text((x+2, y+2), ln, font=kw_font, fill=(0,0,0))
        draw.text((x, y), ln, font=kw_font, fill=gold)

    ft = footer.upper()
    fw = draw.textlength(ft, font=footer_font)
    fx = (W - fw)//2
    fy = H - pad2 - int(H*0.10)
    draw.text((fx, fy), ft, font=footer_font, fill=off)
    return img

def upload_png_image(img: Image.Image, filename: str, title: str, alt: str) -> Optional[int]:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    r = requests.post(MEDIA_URL, headers=headers, data=buf.getvalue(), auth=AUTH, timeout=120)
    if r.status_code not in (200, 201):
        print("Media upload failed:", r.status_code, r.text[:200])
        return None
    media_id = int(r.json()["id"])
    requests.post(f"{MEDIA_URL}/{media_id}", json={"title": title, "alt_text": alt}, auth=AUTH, timeout=60)
    return media_id

# =========================
# 본문 이미지(주제 기반)
# =========================
def picsum(seed: str, w: int = 1200, h: int = 800) -> str:
    return f"https://picsum.photos/seed/{seed}/{w}/{h}"

def unsplash_url(query: str) -> Optional[str]:
    if not UNSPLASH_ACCESS_KEY:
        return None
    api = "https://api.unsplash.com/photos/random"
    params = {"query": query, "orientation": "landscape", "client_id": UNSPLASH_ACCESS_KEY}
    r = requests.get(api, params=params, timeout=30)
    if r.status_code == 200:
        return (r.json().get("urls") or {}).get("regular")
    return None

def download_image(url: str) -> Optional[Tuple[bytes, str]]:
    r = requests.get(url, timeout=60)
    if r.status_code != 200:
        return None
    ctype = (r.headers.get("Content-Type") or "image/jpeg").split(";")[0].strip()
    return r.content, ctype

def upload_image_to_wp(url: str, filename_prefix: str) -> str:
    dl = download_image(url)
    if not dl:
        return url
    b, ctype = dl
    ext = "jpg" if "jpeg" in ctype else ("png" if "png" in ctype else "jpg")
    headers = {
        "Content-Disposition": f'attachment; filename="{filename_prefix}.{ext}"',
        "Content-Type": ctype,
    }
    r = requests.post(MEDIA_URL, headers=headers, data=b, auth=AUTH, timeout=120)
    if r.status_code in (200, 201):
        return r.json().get("source_url") or url
    return url

# =========================
# 콘텐츠 생성 (OpenAI)
# =========================
PRICE_GUARD = """
Important constraints:
- Do NOT include exact prices, $ amounts, per-month figures, or billed annually numbers.
- If you must mention pricing, use vague language like "pricing varies" or "contact sales".
"""

def call_openai(messages: List[dict]) -> str:
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        temperature=0.7,
    )
    return (resp.choices[0].message.content or "").strip()

def generate_article(topic: str, kind: str) -> str:
    """
    kind: list / comparison / deep
    """
    if kind == "list":
        system = f"""
You are a professional SaaS reviewer writing for small businesses.
Write a detailed SEO article (minimum 1500 words).
Include: who it's for, how to choose, key features, practical setup tips.
Include ONE comparison table (HTML).
Use clean HTML only.
Insert placeholders [IMAGE1], [IMAGE2], [IMAGE3] naturally (intro/mid/late).
{PRICE_GUARD}
"""
        user = f"Write about: {topic}"
    elif kind == "comparison":
        system = f"""
You are a professional SaaS reviewer writing for small businesses.
Write a comparison article (minimum 1500 words) between 3-4 tools.
Include: decision framework, pros/cons, scenarios, and an HTML comparison table.
Use clean HTML only.
Insert placeholders [IMAGE1], [IMAGE2], [IMAGE3] naturally (intro/mid/late).
{PRICE_GUARD}
"""
        user = f"Write a comparison about: {topic}"
    else:
        system = f"""
You are a professional SaaS reviewer writing for small businesses.
Write a deep-dive single-tool or single-topic guide (minimum 1500 words).
Include: implementation steps, pitfalls, checklist, FAQs.
Use clean HTML only.
Insert placeholders [IMAGE1], [IMAGE2], [IMAGE3] naturally (intro/mid/late).
{PRICE_GUARD}
"""
        user = f"Write a deep guide about: {topic}"

    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    return call_openai(messages)

# =========================
# 본문 후처리: 표/Save&Print/가격 제거
# =========================
TABLE_CSS_MARKER = "/* rp-table-scroll */"
SAVEPRINT_MARKER = "<!-- rp:save_print_v1 -->"

PRICE_HIT_RE = re.compile(
    r"(\$|€|£|₩)\s?\d|"
    r"\b(pricing|price|billed|annually|monthly|per\s+month|/mo|/month|per\s+year|/yr|per\s+agent|usd|eur|gbp|krw)\b",
    re.I
)

def remove_pricing_blocks(html_text: str) -> str:
    soup = BeautifulSoup(html_text, "lxml")
    for tag in soup.find_all(["p", "li"]):
        t = tag.get_text(" ", strip=True)
        if t and PRICE_HIT_RE.search(t):
            tag.decompose()
    for table in soup.find_all("table"):
        t = table.get_text(" ", strip=True)
        if t and PRICE_HIT_RE.search(t):
            table.decompose()
    for h in soup.find_all(["h2","h3","h4"]):
        ht = h.get_text(" ", strip=True)
        if ht and PRICE_HIT_RE.search(ht):
            nxt = h.find_next_sibling()
            h.decompose()
            while nxt and nxt.name not in ["h2","h3","h4"]:
                kill = nxt
                nxt = nxt.find_next_sibling()
                kill.decompose()
    return str(soup.body.decode_contents() if soup.body else soup)

def wrap_tables_mobile(html_text: str) -> str:
    soup = BeautifulSoup(html_text, "lxml")
    for table in soup.find_all("table"):
        p = table.parent
        if p and p.name == "div" and "rp-table-scroll" in (p.get("class") or []):
            continue
        wrap = soup.new_tag("div")
        wrap["class"] = "rp-table-scroll"
        table.wrap(wrap)
    out = str(soup.body.decode_contents() if soup.body else soup)
    if TABLE_CSS_MARKER not in out:
        css = f"""
<style>
{TABLE_CSS_MARKER}
.rp-table-scroll{{width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch;margin:16px 0;}}
.rp-table-scroll table{{min-width:680px;}}
</style>
"""
        out = css + out
    return out

def ensure_save_print(html_text: str) -> str:
    if SAVEPRINT_MARKER in html_text:
        return html_text
    block = "\n".join([
        SAVEPRINT_MARKER,
        '<h2 id="save-print">Save or Print Checklist</h2>',
        '<p><strong>안내:</strong> 이 체크리스트는 <strong>저장 및 출력</strong>이 가능합니다. '
        '아래 버튼을 누르면 <strong>출력창</strong>이 열립니다. 출력창에서 <strong>"PDF로 저장"</strong>을 선택하면 저장할 수 있어요.</p>',
        '<p><button onclick="window.print()" style="padding:12px 18px;border-radius:12px;border:1px solid #ccc;cursor:pointer;font-weight:700;">출력창 열기</button></p>',
    ])
    return html_text.rstrip() + "\n\n" + block + "\n"

def fill_images(content: str, title: str) -> str:
    seed = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or str(random.randint(1000,9999))
    queries = [title, f"{title} software dashboard", f"{title} workflow automation"]
    urls = []
    for i, q in enumerate(queries):
        u = unsplash_url(q) or picsum(f"{seed}-{i+1}")
        u = upload_image_to_wp(u, f"rp_body_{seed}_{i+1}")
        urls.append(u)

    img1 = f'<figure class="wp-block-image"><img src="{urls[0]}" alt="{html_mod.escape(title)} image 1" loading="lazy" style="width:100%;border-radius:14px;margin:26px 0;"></figure>'
    img2 = f'<figure class="wp-block-image"><img src="{urls[1]}" alt="{html_mod.escape(title)} image 2" loading="lazy" style="width:100%;border-radius:14px;margin:26px 0;"></figure>'
    img3 = f'<figure class="wp-block-image"><img src="{urls[2]}" alt="{html_mod.escape(title)} image 3" loading="lazy" style="width:100%;border-radius:14px;margin:26px 0;"></figure>'

    content = content.replace("[IMAGE1]", img1)
    content = content.replace("[IMAGE2]", img2)
    content = content.replace("[IMAGE3]", img3)
    return content

# =========================
# 클러스터 토픽 생성
# =========================
def cluster_topics_for_category(cat_slug: str) -> List[Tuple[str, str]]:
    """
    return list of (kind, topic)
    """
    if cat_slug == "crm-software":
        return [
            ("list", "Best CRM Software for Small Businesses (2026)"),
            ("comparison", "HubSpot vs Salesforce vs Zoho CRM: Which is Better for Small Teams (2026)"),
            ("deep", "CRM Implementation Checklist for Small Businesses: Steps, Templates, and Pitfalls (2026)"),
        ]
    if cat_slug == "automation-tools":
        return [
            ("list", "Best Automation Tools for Small Business Workflows (2026)"),
            ("comparison", "Zapier vs Make vs n8n: Automation Tool Comparison (2026)"),
            ("deep", "How to Automate Lead Routing and Follow-ups with No-Code Workflows (2026)"),
        ]
    if cat_slug == "marketing-ai":
        return [
            ("list", "Best AI Marketing Tools for Lead Generation (2026)"),
            ("comparison", "Best AI Email Marketing Platforms: Automation, Segmentation, Deliverability (2026)"),
            ("deep", "AI Content Repurposing Workflow for Small Teams: A Step-by-Step Guide (2026)"),
        ]
    # ai-productivity
    return [
        ("list", "Best AI Productivity Tools for Small Businesses (2026)"),
        ("comparison", "Notion AI vs ClickUp AI vs Asana AI: Project Management for Small Teams (2026)"),
        ("deep", "Meeting Notes to Action Items: A Practical AI Workflow for Small Teams (2026)"),
    ]

# =========================
# 발행 (future 예약)
# =========================
def publish_future_post(title: str, content: str, cat_slug: str, publish_date: datetime) -> Optional[int]:
    cat_id = get_category_id(cat_slug)
    if not cat_id:
        print("Category id not found:", cat_slug)
        return None

    # 1) 일단 포스트 생성 (ID 확보)
    payload = {
        "title": title,
        "content": content,
        "status": "future",
        "date": publish_date.isoformat(),
        "categories": [cat_id],
    }
    r = wp_post(POSTS_URL, payload)
    if r.status_code not in (200, 201):
        print("Post create failed:", r.status_code, r.text[:300])
        return None

    post_id = int(r.json()["id"])

    # 2) Featured 썸네일 생성/업로드 후 featured_media 업데이트
    kw = keyword_from_slug(cat_slug)
    thumb = make_brand_thumbnail_square(keyword=kw, brand=BRAND_TEXT, footer=FOOTER_TEXT, size=1200)
    featured_id = upload_png_image(
        thumb,
        filename=f"rp_{post_id}_featured_{kw.lower()}.png",
        title=f"{BRAND_TEXT} - {kw}",
        alt=f"{BRAND_TEXT} - {kw}",
    )
    if featured_id:
        wp_post(f"{POSTS_URL}/{post_id}", {"featured_media": featured_id})

    print("Scheduled:", publish_date.isoformat(), "|", cat_slug, "|", title)
    return post_id

def main():
    last_future = get_last_scheduled_date()
    start = max(datetime.now(), last_future) + timedelta(days=DAYS_AHEAD_START)

    used = set()
    print("Start scheduling from:", start.isoformat())
    print("Clusters:", CLUSTER_COUNT)

    for c in range(CLUSTER_COUNT):
        cat_slug = random.choice(CATEGORY_SLUGS)
        topics = cluster_topics_for_category(cat_slug)

        for i, (kind, topic) in enumerate(topics):
            pub_date = next_available_10am(start + timedelta(days=i + c*3), used)

            print("Generating:", kind, "|", topic)
            article = generate_article(topic, kind)

            # 후처리
            article = fill_images(article, topic)
            article = remove_pricing_blocks(article)
            article = wrap_tables_mobile(article)
            article = ensure_save_print(article)

            publish_future_post(topic, article, cat_slug, pub_date)

if __name__ == "__main__":
    main()
