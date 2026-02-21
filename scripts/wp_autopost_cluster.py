import os
import re
import json
import html as html_mod
import random
import requests
from datetime import datetime, timedelta, time as dtime
from typing import Optional, List, Dict, Tuple
from requests.auth import HTTPBasicAuth
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont
import io

from openai import OpenAI

# =========================
# ENV
# =========================
WP_BASE = os.environ.get("WP_BASE", "").rstrip("/")
WP_USER = os.environ.get("WP_USER", "")
WP_PASS = os.environ.get("WP_PASS", "")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "")

THUMB_BG_MEDIA_ID = int(os.environ.get("THUMB_BG_MEDIA_ID", "332"))
SITE_BRAND = os.environ.get("SITE_BRAND", "ReloadItem")

# 발행 시간: KST 오전 10시 고정
PUBLISH_HOUR_KST = int(os.environ.get("PUBLISH_HOUR_KST", "10"))
PUBLISH_MIN_KST = int(os.environ.get("PUBLISH_MIN_KST", "0"))

# 한번 실행 시 몇 개 생성할지
POSTS_PER_RUN = int(os.environ.get("POSTS_PER_RUN", "3"))

# 가격표기 제거
REMOVE_PRICING = os.environ.get("REMOVE_PRICING", "1") == "1"

# 카테고리 랜덤 발행(네가 원한 방식)
RANDOM_CATEGORY = os.environ.get("RANDOM_CATEGORY", "1") == "1"

auth = HTTPBasicAuth(WP_USER, WP_PASS)

def must_env():
    missing = []
    for k in ["WP_BASE", "WP_USER", "WP_PASS", "OPENAI_API_KEY"]:
        if not os.environ.get(k):
            missing.append(k)
    if missing:
        raise SystemExit(f"Missing env: {', '.join(missing)}")

def wp_get(path: str, params: dict = None) -> requests.Response:
    return requests.get(f"{WP_BASE}{path}", params=params, auth=auth, timeout=60)

def wp_post(path: str, json_body: dict = None, headers=None, data=None) -> requests.Response:
    return requests.post(f"{WP_BASE}{path}", json=json_body, headers=headers, data=data, auth=auth, timeout=120)

def fetch_media_source_url(media_id: int) -> Optional[str]:
    r = wp_get(f"/wp-json/wp/v2/media/{media_id}")
    if r.status_code != 200:
        return None
    return r.json().get("source_url")

def download_bytes(url: str) -> Optional[bytes]:
    try:
        r = requests.get(url, timeout=60)
        if r.status_code != 200:
            return None
        return r.content
    except Exception:
        return None

def safe_ascii_category(cat: str) -> str:
    if not cat:
        return ""
    if re.search(r"[^\x00-\x7F]", cat):
        return ""
    return cat.strip()

def make_featured_image(bg_bytes: bytes, title: str, category: str) -> bytes:
    img = Image.open(io.BytesIO(bg_bytes)).convert("RGBA")
    img = img.resize((1200, 630))

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)

    panel_margin = 90
    panel = (panel_margin, 140, 1200 - panel_margin, 630 - 140)
    d.rounded_rectangle(panel, radius=26, fill=(0, 0, 0, 160), outline=(212, 175, 55, 200), width=3)
    d.line((panel[0] + 30, panel[1] + 28, panel[2] - 30, panel[1] + 28), fill=(212, 175, 55, 220), width=3)
    d.line((panel[0] + 30, panel[3] - 28, panel[2] - 30, panel[3] - 28), fill=(212, 175, 55, 220), width=3)

    img = Image.alpha_composite(img, overlay)
    d = ImageDraw.Draw(img)

    try:
        font_title = ImageFont.truetype("DejaVuSans.ttf", 54)
        font_meta = ImageFont.truetype("DejaVuSans.ttf", 26)
        font_brand = ImageFont.truetype("DejaVuSans.ttf", 28)
    except Exception:
        font_title = ImageFont.load_default()
        font_meta = ImageFont.load_default()
        font_brand = ImageFont.load_default()

    cat = safe_ascii_category(category)
    d.text((panel[0] + 40, panel[1] + 45), SITE_BRAND, fill=(255, 255, 255, 235), font=font_brand)
    if cat:
        d.text((panel[2] - 40 - d.textlength(cat, font=font_meta), panel[1] + 52), cat, fill=(212, 175, 55, 235), font=font_meta)

    t = title.strip()
    max_w = panel[2] - panel[0] - 80
    words = t.split()
    lines = []
    cur = ""
    for w in words:
        test = (cur + " " + w).strip()
        if d.textlength(test, font=font_title) <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    lines = lines[:3]

    y = panel[1] + 125
    for line in lines:
        d.text((panel[0] + 40, y), line, fill=(255, 255, 255, 245), font=font_title)
        y += 68

    domain = re.sub(r"^https?://", "", WP_BASE).split("/")[0]
    d.text((panel[0] + 40, panel[3] - 80), domain, fill=(255, 255, 255, 200), font=font_meta)

    out = io.BytesIO()
    img.convert("RGB").save(out, format="JPEG", quality=92, optimize=True)
    return out.getvalue()

def upload_media(image_bytes: bytes, filename: str) -> int:
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": "image/jpeg",
    }
    r = requests.post(f"{WP_BASE}/wp-json/wp/v2/media", data=image_bytes, headers=headers, auth=auth, timeout=120)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Media upload failed: {r.status_code} {r.text[:300]}")
    return r.json()["id"]

def get_categories() -> List[dict]:
    cats = []
    page = 1
    while True:
        r = wp_get("/wp-json/wp/v2/categories", params={"per_page": 100, "page": page})
        if r.status_code != 200:
            break
        batch = r.json()
        if not batch:
            break
        cats.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    # uncategorized 제거(원하면)
    cats = [c for c in cats if c.get("slug") != "uncategorized"]
    return cats

def unsplash_search(query: str) -> Optional[str]:
    if not UNSPLASH_ACCESS_KEY:
        return None
    try:
        r = requests.get(
            "https://api.unsplash.com/search/photos",
            params={"query": query, "per_page": 10, "orientation": "landscape"},
            headers={"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"},
            timeout=60,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        results = data.get("results") or []
        if not results:
            return None
        pick = random.choice(results[:8])
        return pick["urls"]["regular"]
    except Exception:
        return None

def strip_pricing(text: str) -> str:
    if not REMOVE_PRICING:
        return text
    lines = text.splitlines()
    out = []
    price_pat = re.compile(r"(\$\s?\d+|\d+\s?\/\s?mo|\bper\s+month\b|\bmonthly\b|\bPricing\b:)", re.I)
    for ln in lines:
        if price_pat.search(ln):
            continue
        out.append(ln)
    text2 = "\n".join(out)
    text2 = re.sub(r"\$\s?\d+(\.\d+)?", "", text2)
    return text2

def add_table_wrappers(html_text: str) -> str:
    soup = BeautifulSoup(html_text, "html.parser")
    for table in soup.find_all("table"):
        parent = table.parent
        if parent and parent.name == "div" and "ri-table" in (parent.get("class") or []):
            continue
        wrapper = soup.new_tag("div")
        wrapper["class"] = ["ri-table"]
        table.wrap(wrapper)
        table["class"] = list(set((table.get("class") or []) + ["ri-table__table"]))
    return str(soup)

def insert_images(html_text: str, topic: str, title: str) -> str:
    # 3개: intro / mid / end
    # 실패하면 그냥 스킵
    urls = []
    for q in [topic, f"{topic} software", f"{topic} workflow"]:
        u = unsplash_search(q)
        if u:
            urls.append(u)
        if len(urls) >= 3:
            break

    if len(urls) < 1:
        return html_text

    soup = BeautifulSoup(html_text, "html.parser")
    paras = soup.find_all(["p", "h2", "h3"])
    if not paras:
        return html_text

    def fig(url: str, idx: int):
        f = soup.new_tag("figure")
        f["class"] = ["wp-block-image"]
        img = soup.new_tag("img")
        img["src"] = url
        img["alt"] = f"{html_mod.escape(title)} image {idx}"
        img["loading"] = "lazy"
        img["style"] = "width:100%;border-radius:14px;margin:22px 0;"
        f.append(img)
        return f

    # 위치 선정
    a = max(1, min(3, len(paras)-1))
    b = max(a+2, len(paras)//2)
    c = max(b+2, len(paras)-2)

    inserts = [(a, 0), (b, 1), (c, 2)]
    for pos, idx in reversed(inserts):
        if idx < len(urls):
            paras[pos].insert_after(fig(urls[idx], idx+1))
    return str(soup)

def next_kst_10_slots(n: int) -> List[datetime]:
    # “월화수 / 목금토” 느낌으로: 일요일 제외하고 다음 10시 슬롯 n개 생성
    # KST 기준 -> UTC 변환은 WP가 사이트 타임존 따라가므로 여기서는 ISO로 "현지 시간" 넣어도 됨(WP 설정이 KST이면 OK)
    now = datetime.now()
    slots = []
    d = now.date()
    while len(slots) < n:
        d += timedelta(days=1)
        # Sunday skip
        if d.weekday() == 6:
            continue
        slots.append(datetime.combine(d, dtime(PUBLISH_HOUR_KST, PUBLISH_MIN_KST, 0)))
    return slots

def generate_article(client: OpenAI, category_name: str) -> Tuple[str, str, str]:
    # 제목/주제/본문 생성
    prompt = f"""
You write for a practical AI tools & software review blog.
Category: {category_name}

Rules:
- No exact dollar amounts, no per-month pricing numbers, no $ symbols.
- Clear sections: Introduction, Top Tools (5-8 tools), Comparison Table, Practical Setup Tips, FAQs, Conclusion.
- Add a short note near the top: "A save/print-friendly checklist is included at the end. Use the print window to save as a PDF or print."
- Include a checklist section at the end (bullets with [ ]), and tell readers to use print window to save/print.
- Keep it helpful for small businesses.
- Write in English.

Return JSON with keys: title, topic, html
"""
    resp = client.responses.create(
        model="gpt-5-mini",
        input=prompt,
    )
    txt = resp.output_text
    # JSON 파싱
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        raise RuntimeError("Model did not return JSON")
    data = json.loads(m.group(0))
    title = data["title"].strip()
    topic = data["topic"].strip()
    html_body = data["html"].strip()
    return title, topic, html_body

def create_post(title: str, content_html: str, category_id: int, featured_media_id: int, date_local: datetime):
    payload = {
        "title": title,
        "content": content_html,
        "status": "future",
        "categories": [category_id],
        "featured_media": featured_media_id,
        "date": date_local.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    r = wp_post("/wp-json/wp/v2/posts", json_body=payload)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Post create failed: {r.status_code} {r.text[:300]}")
    return r.json()["id"]

def main():
    must_env()

    client = OpenAI(api_key=OPENAI_API_KEY)

    # background bytes
    bg_url = fetch_media_source_url(THUMB_BG_MEDIA_ID)
    if not bg_url:
        raise SystemExit(f"Cannot fetch background media source_url for id={THUMB_BG_MEDIA_ID}")
    bg_bytes = download_bytes(bg_url)
    if not bg_bytes:
        raise SystemExit("Cannot download background image bytes")

    cats = get_categories()
    if not cats:
        raise SystemExit("No categories found")

    slots = next_kst_10_slots(POSTS_PER_RUN)

    for i in range(POSTS_PER_RUN):
        cat = random.choice(cats) if RANDOM_CATEGORY else cats[0]
        cat_id = cat["id"]
        cat_name = cat.get("name", "")

        title, topic, body = generate_article(client, cat_name)

        # 정리
        body = strip_pricing(body)
        body = add_table_wrappers(body)
        body = insert_images(body, topic=topic, title=title)

        # featured 생성/업로드
        thumb_bytes = make_featured_image(bg_bytes, title, cat_name)
        thumb_id = upload_media(thumb_bytes, f"thumb_new_{int(datetime.now().timestamp())}_{i}.jpg")

        post_id = create_post(title, body, cat_id, thumb_id, slots[i])
        print(f"Created future post id={post_id} at {slots[i]} KST | cat={cat_name} | featured={thumb_id}")

if __name__ == "__main__":
    main()
