import os
import re
import io
import html as html_mod
import random
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
WP_BASE = os.environ.get("WP_BASE", "").rstrip("/")  # e.g. https://reloaditem.com
WP_USER = os.environ.get("WP_USER", "")
WP_PASS = os.environ.get("WP_PASS", "")  # WP Application Password 권장
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "")

# 썸네일 배경으로 쓸 WP 미디어 ID (너가 준 332)
thumb_env = os.environ.get("THUMBNAIL_BASE_MEDIA_ID")
THUMBNAIL_BASE_MEDIA_ID = int(thumb_env) if thumb_env and thumb_env.strip() else 332

# 썸네일/브랜딩 텍스트
SITE_BRAND = os.environ.get("SITE_BRAND", "ReloadItem.com")
HEADER_TEXT = os.environ.get("HEADER_TEXT", "AI Tools · 2026")

# 유지보수 옵션
MIN_PLAIN_TEXT_LEN = int(os.environ.get("MIN_PLAIN_TEXT_LEN", "200"))  # 너무 짧으면 content overwrite 방지
BODY_IMAGE_COUNT = int(os.environ.get("BODY_IMAGE_COUNT", "3"))         # 본문 이미지 3개
TIMEOUT = int(os.environ.get("HTTP_TIMEOUT", "30"))

if not (WP_BASE and WP_USER and WP_PASS):
    raise SystemExit("Missing env: WP_BASE, WP_USER, WP_PASS")

auth = HTTPBasicAuth(WP_USER, WP_PASS)
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


# =========================
# WP REST helpers
# =========================
def wp_get(path: str, params: Optional[dict] = None) -> dict:
    url = f"{WP_BASE}{path}"
    r = requests.get(url, params=params, auth=auth, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()

def wp_get_list(path: str, params: Optional[dict] = None) -> List[dict]:
    url = f"{WP_BASE}{path}"
    r = requests.get(url, params=params, auth=auth, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()

def wp_post(path: str, payload: dict) -> dict:
    url = f"{WP_BASE}{path}"
    r = requests.post(url, json=payload, auth=auth, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()

def wp_put(path: str, payload: dict) -> dict:
    url = f"{WP_BASE}{path}"
    r = requests.post(url, json=payload, auth=auth, timeout=TIMEOUT)  # WP는 POST로 update도 받는 경우가 많음
    if r.status_code >= 400:
        # fallback: PUT
        r = requests.put(url, json=payload, auth=auth, timeout=TIMEOUT)
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
    return cats

def wp_get_category_name(cat_id: Optional[int]) -> str:
    if not cat_id:
        return ""
    try:
        j = wp_get(f"/wp-json/wp/v2/categories/{cat_id}")
        return j.get("name", "")
    except Exception:
        return ""


# =========================
# Content transforms
# =========================
RP_MARKER_RE = re.compile(r"(^|\n)\s*rp:[a-zA-Z0-9_\-]+(\s*\n|$)")

def clean_rp_markers(html: str) -> str:
    if not html:
        return html
    # rp:xxx 라인 제거
    html = RP_MARKER_RE.sub("\n", html)
    # 혼자 남은 물음표/깨진 줄 정리(“?”만 단독 줄인 경우)
    html = re.sub(r"(^|\n)\s*\?\s*(\n|$)", "\n", html)
    return html.strip()

# 가격/금액 표현 제거 (PartnerStack 등 고려)
PRICE_PATTERNS = [
    r"\$\s?\d[\d,]*(\.\d+)?",
    r"USD\s?\d[\d,]*(\.\d+)?",
    r"\b\d[\d,]*(\.\d+)?\s?(USD|달러)\b",
    r"\b\d[\d,]*(\.\d+)?\s?(원|KRW)\b",
    r"\b(?:price|pricing|cost)\s*[:\-]\s*.*?(<|$)",  # 헤더/라인 형태
    r"\bfrom\s+\$\s?\d[\d,]*(\.\d+)?",
    r"\bstarting\s+at\s+\$\s?\d[\d,]*(\.\d+)?",
]

def strip_pricing(html: str) -> str:
    if not html:
        return html
    # 텍스트 기반 제거
    for pat in PRICE_PATTERNS:
        html = re.sub(pat, "", html, flags=re.IGNORECASE)

    # 표(테이블)에서 Pricing/Price 단락/행 제거
    soup = BeautifulSoup(html, "html.parser")
    # "Pricing" "Price" "Plans" 같은 섹션 제목이면 섹션 자체를 과감히 제거하지는 않고, 표 안의 행만 제거
    for table in soup.find_all("table"):
        # 헤더에 price/pricing 있으면 그 열 제거
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

        # 행 자체가 가격 문구면 제거
        for tr in list(table.find_all("tr")):
            t = tr.get_text(" ", strip=True).lower()
            if any(k in t for k in ["price", "pricing", "cost", "per month", "/mo", "usd", "$"]):
                # 너무 공격적이면 표가 비는데, "가격 전용 행" 위주로만 제거
                if "$" in t or "usd" in t or "/mo" in t or "per month" in t:
                    tr.decompose()

    return str(soup)

def fix_tables(html: str) -> str:
    """모바일에서 표 가로 스크롤 되도록 래핑 + 스타일 1회 삽입"""
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

    # 스타일 1회 삽입 (테마 수정 없이도 적용되게)
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
            # 본문 최상단에 넣기
            if soup.body:
                soup.body.insert(0, style)
            else:
                soup.insert(0, style)

    return str(soup)

def ensure_body_images(html: str, topic: str) -> str:
    """본문에 이미지가 3개보다 적으면 Unsplash에서 주제 맞게 3장 채워넣기"""
    if BODY_IMAGE_COUNT <= 0 or not UNSPLASH_ACCESS_KEY:
        return html

    soup = BeautifulSoup(html or "", "html.parser")
    imgs = soup.find_all("img")
    if len(imgs) >= BODY_IMAGE_COUNT:
        return str(soup)

    need = BODY_IMAGE_COUNT - len(imgs)
    urls = unsplash_search(topic, count=max(need, BODY_IMAGE_COUNT))
    if not urls:
        return str(soup)

    # 넣는 위치: H2 앞/중간/후반
    h2s = soup.find_all(["h2", "h3"])
    insert_points = []
    if h2s:
        # 앞/중간/후반
        insert_points = [h2s[0]]
        if len(h2s) >= 2:
            insert_points.append(h2s[len(h2s)//2])
        if len(h2s) >= 3:
            insert_points.append(h2s[-1])
    else:
        insert_points = [soup.find() or soup]

    def make_img(url: str, alt: str) -> BeautifulSoup:
        fig = BeautifulSoup("", "html.parser").new_tag("figure")
        fig["class"] = ["wp-block-image", "size-large"]
        img = BeautifulSoup("", "html.parser").new_tag("img")
        img["src"] = url
        img["alt"] = alt
        img["loading"] = "lazy"
        img["style"] = "width:100%;border-radius:14px;margin:26px 0;"
        fig.append(img)
        return fig

    used = 0
    for i in range(need):
        url = urls[i % len(urls)]
        alt = f"{topic} illustration"
        fig = make_img(url, alt)
        anchor = insert_points[used % len(insert_points)]
        anchor.insert_before(fig)
        used += 1

    return str(soup)

def unsplash_search(query: str, count: int = 3) -> List[str]:
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


# =========================
# Thumbnail generation (black+gold, title/category)
# =========================
def download_bytes(url: str) -> Optional[bytes]:
    try:
        r = requests.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        return r.content
    except Exception:
        return None

def load_font(size: int) -> ImageFont.ImageFont:
    # GitHub runner에 기본 폰트가 제한적이어서, 없으면 기본 폰트로 폴백
    for path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            continue
    return ImageFont.load_default()

def make_featured_image(bg_bytes: bytes, title: str, category: str) -> bytes:
    """
    배경(bg) 위에:
    - 상단: HEADER_TEXT 또는 브랜드
    - 중단: title
    - 하단: SITE_BRAND + category
    """
    base = Image.open(io.BytesIO(bg_bytes)).convert("RGBA")

    # WP 썸네일 잘림 대비: 1200x675 (16:9)
    base = base.resize((1200, 675))

    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # 반투명 패널
    panel_margin = 90
    panel = (panel_margin, 140, 1200 - panel_margin, 675 - 140)
    draw.rounded_rectangle(panel, radius=28, fill=(0, 0, 0, 140), outline=(212, 175, 55, 140), width=2)

    # 골드 라인 (위/아래 대칭)
    gold = (212, 175, 55, 220)
    draw.line([(120, 90), (1080, 90)], fill=gold, width=3)
    draw.line([(120, 585), (1080, 585)], fill=gold, width=3)

    # 텍스트
    title = (title or "").strip()
    category = (category or "").strip()
    header = HEADER_TEXT
    footer_left = SITE_BRAND
    footer_right = category.upper() if category else ""

    font_header = load_font(28)
    font_title = load_font(56)
    font_footer = load_font(24)

    # Header centered
    w, h = draw.textbbox((0, 0), header, font=font_header)[2:]
    draw.text(((1200 - w) / 2, 170), header, font=font_header, fill=gold)

    # Title wrap
    max_width = 920
    lines = wrap_text(draw, title, font_title, max_width)
    y = 250
    for line in lines[:3]:
        w = draw.textbbox((0, 0), line, font=font_title)[2]
        draw.text(((1200 - w) / 2, y), line, font=font_title, fill=(255, 255, 255, 235))
        y += 70

    # Footer
    draw.text((170, 500), footer_left, font=font_footer, fill=(255, 255, 255, 210))
    if footer_right:
        w = draw.textbbox((0, 0), footer_right, font=font_footer)[2]
        draw.text((1200 - 170 - w, 500), footer_right, font=font_footer, fill=gold)

    out = Image.alpha_composite(base, overlay).convert("RGB")
    buf = io.BytesIO()
    out.save(buf, format="JPEG", quality=92, optimize=True)
    return buf.getvalue()

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


# =========================
# Main: update ALL posts (publish + future)
# =========================
def get_all_posts(status: str) -> List[dict]:
    posts = []
    page = 1
    while True:
        chunk = wp_get_list(
            "/wp-json/wp/v2/posts",
            params={"per_page": 100, "page": page, "status": status, "orderby": "date", "order": "desc"},
        )
        if not chunk:
            break
        posts.extend(chunk)
        if len(chunk) < 100:
            break
        page += 1
    return posts

def update_post(pid: int, payload: dict) -> None:
    wp_put(f"/wp-json/wp/v2/posts/{pid}", payload)

def main():
    cats = wp_get_categories()
    cat_map = {c["id"]: c.get("name", "") for c in cats}

    bg_url = wp_get_media_source_url(THUMBNAIL_BASE_MEDIA_ID)
    bg_bytes = download_bytes(bg_url) if bg_url else None
    if not bg_bytes:
        raise SystemExit("Could not download thumbnail background. Check THUMBNAIL_BASE_MEDIA_ID")

    for status in ["publish", "future"]:
        all_posts = get_all_posts(status)
        print(f"[{status}] posts={len(all_posts)}")

        for p in all_posts:
            pid = p["id"]
            title = (p.get("title") or {}).get("rendered", "")
            content = (p.get("content") or {}).get("rendered", "")

            # 1) 본문 정리
            new_content = content
            new_content = clean_rp_markers(new_content)
            new_content = strip_pricing(new_content)
            new_content = fix_tables(new_content)

            # 주제 추정: 제목 기반
            topic = BeautifulSoup(title or "", "html.parser").get_text(" ", strip=True) or "AI tools"
            new_content = ensure_body_images(new_content, topic)

            # 본문 너무 짧으면(실수로 비워지는 경우) content overwrite 방지
            plain = BeautifulSoup(new_content, "html.parser").get_text(" ", strip=True)
            if len(plain) < MIN_PLAIN_TEXT_LEN:
                print(f"SKIP content overwrite (too short) post {pid}")
                # 그래도 썸네일만 갱신하고 싶으면 아래를 주석 해제:
                # pass
                continue

            # 2) Featured 이미지: 매 글마다 생성 업로드 => featured_media 세팅
            cat_ids = p.get("categories") or []
            cat_name = cat_map.get(cat_ids[0], "") if cat_ids else ""
            safe_title = html_mod.unescape(BeautifulSoup(title, "html.parser").get_text(" ", strip=True))

            thumb_bytes = make_featured_image(bg_bytes, safe_title, cat_name)
            media_id = wp_upload_media(thumb_bytes, f"thumb_{pid}.jpg", mime="image/jpeg")

            payload = {
                "content": new_content,
                "featured_media": media_id,
            }

            update_post(pid, payload)
            print(f"Updated post {pid} | featured_media={media_id}")

if __name__ == "__main__":
    main()
