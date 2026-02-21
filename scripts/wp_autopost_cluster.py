import os
import re
import io
import html as html_mod
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Tuple

import requests
from requests.auth import HTTPBasicAuth
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont
from openai import OpenAI

# =========================
# ENV (GitHub Secrets)
# =========================
WP_BASE = os.environ.get("WP_BASE", "").rstrip("/")
WP_USER = os.environ.get("WP_USER", "")
WP_PASS = os.environ.get("WP_PASS", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "")

thumb_env = os.environ.get("THUMBNAIL_BASE_MEDIA_ID")
THUMBNAIL_BASE_MEDIA_ID = int(thumb_env) if thumb_env and thumb_env.strip() else 332
SITE_BRAND = os.environ.get("SITE_BRAND", "ReloadItem.com")
HEADER_TEXT = os.environ.get("HEADER_TEXT", "AI Tools · 2026")

# 발행: 매일 1개, KST 기준
KST = timezone(timedelta(hours=9))
PUBLISH_HOUR = int(os.environ.get("PUBLISH_HOUR_KST", "10"))  # 오전 10시
SLOTS_AHEAD_DAYS = int(os.environ.get("SLOTS_AHEAD_DAYS", "14"))  # 앞으로 2주치 빈 슬롯 채움
SKIP_WEEKDAY = os.environ.get("SKIP_WEEKDAY", "6")  # 6=일요일 스킵(원하면 6 지우거나 다른 숫자 0~6)

BODY_IMAGE_COUNT = int(os.environ.get("BODY_IMAGE_COUNT", "3"))
TIMEOUT = int(os.environ.get("HTTP_TIMEOUT", "30"))

# 타입 반복 규칙: INFO, INFO, VS
TYPE_PATTERN = ["INFO", "INFO", "VS"]

if not (WP_BASE and WP_USER and WP_PASS):
    raise SystemExit("Missing env: WP_BASE, WP_USER, WP_PASS")
if not OPENAI_API_KEY:
    raise SystemExit("Missing env: OPENAI_API_KEY")

auth = HTTPBasicAuth(WP_USER, WP_PASS)
client = OpenAI(api_key=OPENAI_API_KEY)

# =========================
# WP REST helpers
# =========================
def wp_get(path: str, params: Optional[dict] = None):
    url = f"{WP_BASE}{path}"
    headers = {"Accept": "application/json"}
    r = requests.get(url, params=params or {}, headers=headers, auth=auth, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()

def wp_get_list(path: str, params: Optional[dict] = None):
    url = f"{WP_BASE}{path}"
    headers = {"Accept": "application/json"}  # GET에는 Content-Type 넣지 말 것
    r = requests.get(url, params=params or {}, headers=headers, auth=auth, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()

def wp_post(path: str, payload: dict) -> dict:
    url = f"{WP_BASE}{path}"
    r = requests.post(url, json=payload, auth=auth, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()

def wp_upload_media(file_bytes: bytes, filename: str, mime: str = "image/jpeg") -> int:
    url = f"{WP_BASE}/wp-json/wp/v2/media"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": mime,
    }
    r = requests.post(url, headers=headers, data=file_bytes, auth=auth, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()["id"]

def wp_get_media_source_url(media_id: int) -> str:
    j = wp_get(f"/wp-json/wp/v2/media/{media_id}")
    return j.get("source_url", "")

def wp_get_categories() -> List[dict]:
    cats = []
    page = 1
    while True:
        chunk = wp_get_list("/wp-json/wp/v2/categories", params={"per_page": 100, "page": page})
        if not chunk:
            break
        cats.extend(chunk)
        if len(chunk) < 100:
            break
        page += 1
    # 고정 순서(안 흔들리게): id 기준 정렬
    cats.sort(key=lambda x: x.get("id", 0))
    return cats

def wp_get_recent_posts(limit: int = 30) -> List[dict]:
    # publish + future 섞어서 최근순으로 가져오기(다음 로직 계산용)
    posts = wp_get_list(
        "/wp-json/wp/v2/posts",
        params={"per_page": min(limit, 100), "status": "publish,future", "orderby": "date", "order": "desc"},
    )
    return posts

def wp_get_future_posts_in_range(start_iso: str, end_iso: str) -> List[dict]:
    return wp_get_list(
        "/wp-json/wp/v2/posts",
        params={"per_page": 100, "status": "future", "after": start_iso, "before": end_iso, "orderby": "date", "order": "asc"},
    )

# =========================
# Content rules
# =========================
PRICE_PATTERNS = [
    r"\$\s?\d[\d,]*(\.\d+)?",
    r"USD\s?\d[\d,]*(\.\d+)?",
    r"\b\d[\d,]*(\.\d+)?\s?(USD|달러)\b",
    r"\b\d[\d,]*(\.\d+)?\s?(원|KRW)\b",
    r"\bfrom\s+\$\s?\d[\d,]*(\.\d+)?",
    r"\bstarting\s+at\s+\$\s?\d[\d,]*(\.\d+)?",
]

def strip_pricing(html: str) -> str:
    if not html:
        return html
    for pat in PRICE_PATTERNS:
        html = re.sub(pat, "", html, flags=re.IGNORECASE)
    return html

def fix_tables(html: str) -> str:
    if not html:
        return html
    soup = BeautifulSoup(html, "html.parser")
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
.table-scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:18px 0;border:1px solid rgba(255,255,255,.08);border-radius:12px}
.table-scroll table{min-width:640px;width:100%;border-collapse:collapse}
.table-scroll th,.table-scroll td{padding:10px 12px}
"""
            soup.insert(0, style)
    return str(soup)

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

def ensure_body_images(html: str, topic: str) -> str:
    if BODY_IMAGE_COUNT <= 0:
        return html
    soup = BeautifulSoup(html or "", "html.parser")
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

    used = 0
    for i in range(need):
        u = urls[i % len(urls)]
        fig = soup.new_tag("figure")
        fig["class"] = ["wp-block-image", "size-large"]
        img = soup.new_tag("img")
        img["src"] = u
        img["alt"] = f"{topic} illustration"
        img["loading"] = "lazy"
        img["style"] = "width:100%;border-radius:14px;margin:26px 0;"
        fig.append(img)
        anchor = insert_points[used % len(insert_points)]
        anchor.insert_before(fig)
        used += 1

    return str(soup)

# =========================
# Thumbnail generation
# =========================
def download_bytes(url: str) -> Optional[bytes]:
    try:
        r = requests.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        return r.content
    except Exception:
        return None

def load_font(size: int) -> ImageFont.ImageFont:
    for path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            continue
    return ImageFont.load_default()

def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> List[str]:
    words = re.split(r"\s+", text.strip())
    lines = []
    cur = ""
    for w in words:
        test = (cur + " " + w).strip()
        width = draw.textbbox((0, 0), test, font=font)[2]
        if width <= max_width:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines

def make_featured_image(bg_bytes: bytes, title: str, category: str) -> bytes:
    base = Image.open(io.BytesIO(bg_bytes)).convert("RGBA")
    base = base.resize((1200, 675))

    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    gold = (212, 175, 55, 220)
    draw.line([(120, 90), (1080, 90)], fill=gold, width=3)
    draw.line([(120, 585), (1080, 585)], fill=gold, width=3)

    panel = (90, 140, 1110, 535)
    draw.rounded_rectangle(panel, radius=28, fill=(0, 0, 0, 140), outline=(212, 175, 55, 140), width=2)

    font_header = load_font(28)
    font_title = load_font(56)
    font_footer = load_font(24)

    header = HEADER_TEXT
    footer_left = SITE_BRAND
    footer_right = (category or "").upper()

    w = draw.textbbox((0, 0), header, font=font_header)[2]
    draw.text(((1200 - w) / 2, 170), header, font=font_header, fill=gold)

    lines = wrap_text(draw, title, font_title, 920)
    y = 250
    for line in lines[:3]:
        w = draw.textbbox((0, 0), line, font=font_title)[2]
        draw.text(((1200 - w) / 2, y), line, font=font_title, fill=(255, 255, 255, 235))
        y += 70

    draw.text((170, 500), footer_left, font=font_footer, fill=(255, 255, 255, 210))
    if footer_right:
        w = draw.textbbox((0, 0), footer_right, font=font_footer)[2]
        draw.text((1200 - 170 - w, 500), footer_right, font=font_footer, fill=gold)

    out = Image.alpha_composite(base, overlay).convert("RGB")
    buf = io.BytesIO()
    out.save(buf, format="JPEG", quality=92, optimize=True)
    return buf.getvalue()

# =========================
# Type + Category rotation logic
# =========================
def is_vs_post(title: str) -> bool:
    t = (title or "").lower()
    return " vs " in t or " vs:" in t or t.startswith("vs ") or " versus " in t

def classify_type_from_post(post: dict) -> str:
    title_html = (post.get("title") or {}).get("rendered", "")
    title = BeautifulSoup(title_html, "html.parser").get_text(" ", strip=True)
    return "VS" if is_vs_post(title) else "INFO"

def next_type_from_recent(recent_posts: List[dict]) -> str:
    """
    최근 글들을 보고 TYPE_PATTERN(INFO,INFO,VS)의 다음을 계산
    - 최근 글이 패턴 어디까지 왔는지 매칭해서 다음 타입 결정
    """
    seq = []
    for p in recent_posts[:20]:
        seq.append(classify_type_from_post(p))

    # seq[0]이 가장 최신. 최근 흐름의 끝을 찾기 위해 역순으로 패턴을 맞춤
    seq_rev = list(reversed(seq))  # 오래된 -> 최신
    best_idx = None
    best_len = -1

    # 패턴이 무한 반복이라고 보고, seq_rev 끝부분과 가장 잘 맞는 길이를 찾는다
    for start in range(len(TYPE_PATTERN)):
        pat = []
        for i in range(len(seq_rev)):
            pat.append(TYPE_PATTERN[(start + i) % len(TYPE_PATTERN)])
        # 끝에서부터 최대 일치 길이
        k = 0
        for i in range(1, len(seq_rev) + 1):
            if seq_rev[-i] == pat[-i]:
                k += 1
            else:
                break
        if k > best_len:
            best_len = k
            best_idx = (start + len(seq_rev)) % len(TYPE_PATTERN)

    # best_idx는 "다음 위치"
    return TYPE_PATTERN[best_idx] if best_idx is not None else TYPE_PATTERN[0]

def next_category_id(cats: List[dict], recent_posts: List[dict]) -> int:
    """
    최근 글(예약 포함)의 카테고리 기반으로 다음 카테고리를 순차 회전
    """
    if not cats:
        raise SystemExit("No categories in WP.")
    cat_ids = [c["id"] for c in cats]

    # 최근 글에서 첫 번째 카테고리 id를 찾는다
    last_cat_id = None
    for p in recent_posts[:30]:
        cids = p.get("categories") or []
        if cids:
            last_cat_id = cids[0]
            break

    if last_cat_id in cat_ids:
        idx = cat_ids.index(last_cat_id)
        return cat_ids[(idx + 1) % len(cat_ids)]
    return cat_ids[0]

def cat_name_from_id(cats: List[dict], cid: int) -> str:
    for c in cats:
        if c.get("id") == cid:
            return c.get("name", "")
    return ""

# =========================
# AI: generate post
# =========================
def ai_generate_article(title: str, category: str, post_type: str) -> str:
    sys = (
        "You are writing for a SaaS/AI tools blog. "
        "Do NOT mention any prices, dollar amounts, plan fees, or currency. "
        "Avoid pricing tables or pricing columns. "
        "Write in natural English. Use clear headings (H2/H3), bullets, and practical steps. "
        "Return HTML only."
    )

    if post_type == "VS":
        user = f"""
Write a comparison blog post.

Title: {title}
Category: {category}

Requirements:
- 1300~1900 words.
- Explain what each tool is, who it fits, and decision criteria.
- Include a comparison table with only: "Best for", "Strengths", "Weaknesses", "Integrations", "Learning curve" (NO pricing).
- Add a section near the top titled "Save or Print Checklist" with a short note:
  "Use the print window to save as PDF or print a copy."
- End with a checklist (bulleted with [ ] items).
- No prices, no currency, no $/mo, no plan fees.
Return HTML only.
"""
    else:
        user = f"""
Write a practical guide blog post.

Title: {title}
Category: {category}

Requirements:
- 1200~1800 words.
- Include: intro paragraph, 6~9 sections, conclusion.
- Add a section near the top titled "Save or Print Checklist" with a short note:
  "Use the print window to save as PDF or print a copy."
- End with a checklist (bulleted with [ ] items).
- No prices, no currency, no $/mo, no plan fees.
Return HTML only.
"""

    resp = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "system", "content": sys}, {"role": "user", "content": user}],
        temperature=0.6,
    )
    return resp.choices[0].message.content

# =========================
# Scheduling slots: daily 1
# =========================
def upcoming_slots(now_kst: datetime) -> List[datetime]:
    slots = []
    skip = int(SKIP_WEEKDAY)
    for d in range(SLOTS_AHEAD_DAYS + 1):
        dt = datetime.combine(now_kst.date() + timedelta(days=d), datetime.min.time(), tzinfo=KST).replace(hour=PUBLISH_HOUR)
        if dt < now_kst:
            continue
        if dt.weekday() == skip:
            continue
        slots.append(dt)  # 매일 1개
    return slots

def iso(dt: datetime) -> str:
    return dt.isoformat()

def main():
    cats = wp_get_categories()
    if not cats:
        raise SystemExit("No categories found in WP.")

    recent = wp_get_recent_posts(limit=40)

    # 썸네일 배경 다운로드
    bg_url = wp_get_media_source_url(THUMBNAIL_BASE_MEDIAID)
    bg_bytes = download_bytes(bg_url) if bg_url else None
    if not bg_bytes:
        raise SystemExit("Could not download thumbnail background. Check THUMBNAIL_BASE_MEDIAID")

    now_kst = datetime.now(tz=KST)
    slots = upcoming_slots(now_kst)
    if not slots:
        print("No slots generated. Exiting.")
        return

    # 이미 예약된 글 시간 범위 체크
    start = iso(slots[0] - timedelta(hours=1))
    end = iso(slots[-1] + timedelta(hours=1))
    existing_future = wp_get_future_posts_in_range(start, end)
    existing_keys = set()
    for p in existing_future:
        date_local = p.get("date")
        if date_local:
            existing_keys.add(date_local[:16])

    targets = [s for s in slots if s.isoformat()[:16] not in existing_keys]
    if not targets:
        print("No empty slots to fill. Exiting.")
        return

    print(f"Now(KST)={now_kst.isoformat()} | targets={len(targets)}")

    # 현재 패턴/카테고리 시작점 계산
    cur_type = next_type_from_recent(recent)
    cur_cat_id = next_category_id(cats, recent)

    for dt in targets:
        cat_name = cat_name_from_id(cats, cur_cat_id) or "AI Tools"

        # 타입별 제목 템플릿
        if cur_type == "VS":
            title = f"{cat_name}: Tool A vs Tool B vs Tool C — What to Choose in 2026"
        else:
            title = f"Best {cat_name} Tools (2026): A Practical Guide for Small Teams"

        # 본문 생성/정리
        html = ai_generate_article(title, cat_name, cur_type)
        html = strip_pricing(html)
        html = fix_tables(html)
        html = ensure_body_images(html, f"{cat_name} {cur_type}")

        # 썸네일 생성 업로드
        safe_title = html_mod.unescape(BeautifulSoup(title, "html.parser").get_text(" ", strip=True))
        thumb_bytes = make_featured_image(bg_bytes, safe_title, cat_name)
        media_id = wp_upload_media(thumb_bytes, f"thumb_auto_{dt.strftime('%Y%m%d_%H%M')}.jpg", mime="image/jpeg")

        payload = {
            "title": title,
            "status": "future",
            "date": dt.isoformat(),
            "content": html,
            "categories": [cur_cat_id],
            "featured_media": media_id,
        }

        created = wp_post("/wp-json/wp/v2/posts", payload)
        print(f"Created future post id={created['id']} date={created.get('date')} type={cur_type} cat={cat_name}")

        # 다음 글 준비: 타입 패턴 진행 + 카테고리 회전
        # 타입: INFO,INFO,VS 반복
        idx = TYPE_PATTERN.index(cur_type)
        cur_type = TYPE_PATTERN[(idx + 1) % len(TYPE_PATTERN)]

        # 카테고리: 매번 다음 카테고리로 회전
        cat_ids = [c["id"] for c in cats]
        cur_idx = cat_ids.index(cur_cat_id) if cur_cat_id in cat_ids else -1
        cur_cat_id = cat_ids[(cur_idx + 1) % len(cat_ids)]

if __name__ == "__main__":
    main()
