import os
import re
import io
import json
import math
import time
import html
import base64
import hashlib
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont

# ----------------------------
# Config / Env
# ----------------------------
WP_URL = os.environ.get("WP_URL", "").rstrip("/")
WP_USER = os.environ.get("WP_USER", "")
WP_APP_PASSWORD = os.environ.get("WP_APP_PASSWORD", "")
FEATURED_TEMPLATE_MEDIA_ID = int(os.environ.get("FEATURED_TEMPLATE_MEDIA_ID", "0") or "0")
SITE_NAME = os.environ.get("SITE_NAME", "ReloadItem.com")

POST_STATUSES = ["publish", "future"]  # 공개글 + 예약글
PER_PAGE = 50
SLEEP_BETWEEN_REQUESTS_SEC = 0.3

ARTIFACT_DIR = "artifacts"
os.makedirs(ARTIFACT_DIR, exist_ok=True)

if not (WP_URL and WP_USER and WP_APP_PASSWORD):
    raise SystemExit("Missing env: WP_URL, WP_USER, WP_APP_PASSWORD")

AUTH = (WP_USER, WP_APP_PASSWORD)
HEADERS_JSON = {"Content-Type": "application/json"}

# ----------------------------
# Helpers: WP REST
# ----------------------------
def wp_get(path: str, params: Optional[dict] = None):
    url = f"{WP_URL}{path}"
    r = requests.get(url, params=params, auth=AUTH, timeout=60)
    r.raise_for_status()
    return r

def wp_post(path: str, data=None, files=None, headers=None):
    url = f"{WP_URL}{path}"
    r = requests.post(url, data=data, files=files, auth=AUTH, headers=headers, timeout=120)
    r.raise_for_status()
    return r

def wp_patch(path: str, payload: dict):
    url = f"{WP_URL}{path}"
    r = requests.post(url, data=json.dumps(payload), auth=AUTH, headers=HEADERS_JSON, timeout=120)
    # WP는 PATCH 대신 POST로 업데이트되는 경우 많음
    r.raise_for_status()
    return r

def fetch_media_source_url(media_id: int) -> str:
    r = wp_get(f"/wp-json/wp/v2/media/{media_id}")
    j = r.json()
    return j.get("source_url", "")

def fetch_posts(status: str) -> List[dict]:
    posts = []
    page = 1
    while True:
        r = wp_get(
            "/wp-json/wp/v2/posts",
            params={"status": status, "per_page": PER_PAGE, "page": page, "_fields": "id,title,content,featured_media,categories,slug,link"},
        )
        batch = r.json()
        if not batch:
            break
        posts.extend(batch)
        if len(batch) < PER_PAGE:
            break
        page += 1
        time.sleep(SLEEP_BETWEEN_REQUESTS_SEC)
    return posts

def fetch_categories_map() -> Dict[int, str]:
    # 카테고리 이름 매핑 (id -> name)
    m = {}
    page = 1
    while True:
        r = wp_get("/wp-json/wp/v2/categories", params={"per_page": 100, "page": page, "_fields": "id,name"})
        batch = r.json()
        if not batch:
            break
        for c in batch:
            m[c["id"]] = c["name"]
        if len(batch) < 100:
            break
        page += 1
        time.sleep(SLEEP_BETWEEN_REQUESTS_SEC)
    return m

def upload_image_to_wp(img: Image.Image, filename: str, alt_text: str) -> int:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)

    files = {
        "file": (filename, buf, "image/png"),
    }
    # WP 업로드는 multipart
    r = wp_post("/wp-json/wp/v2/media", files=files, headers={"Content-Disposition": f'attachment; filename="{filename}"'})
    media = r.json()
    media_id = int(media["id"])

    # alt_text 업데이트
    wp_patch(f"/wp-json/wp/v2/media/{media_id}", {"alt_text": alt_text, "title": alt_text})
    return media_id

# ----------------------------
# Content cleanup rules
# ----------------------------
RP_TOKEN_RE = re.compile(r"\brp:[a-zA-Z0-9_]+\b")
JUST_Q_RE = re.compile(r"^\s*\?\s*$", re.MULTILINE)

PRICE_LINE_RE = re.compile(
    r"(\$\s*\d|\bPricing\b|\bPrice\b|\bper\s+month\b|\bper\s+agent\b|\bbilled\b|\bannually\b|\bmonthly\b|\bUSD\b)",
    re.IGNORECASE,
)

def remove_rp_tokens(text: str) -> str:
    text = RP_TOKEN_RE.sub("", text)
    text = JUST_Q_RE.sub("", text)
    # 빈 줄 정리
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text

def remove_pricing_blocks(html_content: str) -> str:
    """
    - Pricing 섹션/문단/리스트/테이블을 공격적으로 제거
    - PartnerStack에서 싫어하는 '금액' 노출을 최대한 제거
    """
    soup = BeautifulSoup(html_content, "lxml")

    # 1) Pricing note 같은 문단 제거
    for p in soup.find_all(["p", "li"]):
        if p.get_text(" ", strip=True) and PRICE_LINE_RE.search(p.get_text(" ", strip=True)):
            p.decompose()

    # 2) 표에서 $/Pricing 들어간 행/셀 제거
    for table in soup.find_all("table"):
        t = table.get_text(" ", strip=True)
        if t and PRICE_LINE_RE.search(t):
            table.decompose()

    # 3) 헤딩이 Pricing/가격이면 다음 요소들 일부 제거
    for h in soup.find_all(["h2", "h3", "h4"]):
        title = h.get_text(" ", strip=True)
        if title and PRICE_LINE_RE.search(title):
            # 다음 형제들을 다음 헤딩 전까지 제거
            nxt = h.find_next_sibling()
            h.decompose()
            while nxt and nxt.name not in ["h2", "h3", "h4"]:
                to_del = nxt
                nxt = nxt.find_next_sibling()
                to_del.decompose()

    return str(soup.body.decode_contents() if soup.body else soup)

def wrap_tables_for_mobile(html_content: str) -> str:
    soup = BeautifulSoup(html_content, "lxml")
    for table in soup.find_all("table"):
        # 이미 래핑되어 있으면 패스
        parent = table.parent
        if parent and parent.name == "div" and "rp-table-scroll" in (parent.get("class") or []):
            continue
        wrapper = soup.new_tag("div")
        wrapper["class"] = "rp-table-scroll"
        table.wrap(wrapper)
    return str(soup.body.decode_contents() if soup.body else soup)

def inject_table_scroll_css(html_content: str) -> str:
    """
    테마 CSS를 건드리지 않아도 되게, 포스트 content 상단에 최소 CSS 1회 삽입.
    (이미 있으면 중복 삽입 방지)
    """
    css_marker = "/* rp-table-scroll */"
    if css_marker in html_content:
        return html_content
    css = """
<style>
/* rp-table-scroll */
.rp-table-scroll{width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch;margin:16px 0;}
.rp-table-scroll table{min-width:680px;}
</style>
"""
    return css + html_content

# ----------------------------
# Thumbnail / Images generation
# ----------------------------
def download_template_image() -> Image.Image:
    if FEATURED_TEMPLATE_MEDIA_ID <= 0:
        # 마지막 fallback: 그냥 검정 배경
        img = Image.new("RGB", (1200, 630), (10, 10, 10))
        return img

    src = fetch_media_source_url(FEATURED_TEMPLATE_MEDIA_ID)
    if not src:
        img = Image.new("RGB", (1200, 630), (10, 10, 10))
        return img

    r = requests.get(src, timeout=60)
    r.raise_for_status()
    img = Image.open(io.BytesIO(r.content)).convert("RGB")
    # 표준 OG 썸네일 비율로 리사이즈(너 배경이 이미 16:9면 그대로)
    img = img.resize((1200, 630))
    return img

def get_font(size: int) -> ImageFont.FreeTypeFont:
    # GitHub runner에 기본 폰트가 제한적이라, Pillow 기본 폰트 fallback 포함
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except Exception:
        return ImageFont.load_default()

def ellipsize(text: str, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"

def draw_centered_multiline(draw: ImageDraw.ImageDraw, box: Tuple[int,int,int,int], text: str, font: ImageFont.ImageFont, fill=(20,20,20)):
    x1,y1,x2,y2 = box
    w = x2-x1
    # 간단 줄바꿈
    words = text.split(" ")
    lines = []
    cur = ""
    for wd in words:
        test = (cur + " " + wd).strip()
        if draw.textlength(test, font=font) <= w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)

    # 높이 계산
    line_h = int(font.size * 1.2)
    total_h = line_h * len(lines)
    start_y = y1 + (y2 - y1 - total_h) // 2

    for i, line in enumerate(lines):
        lw = draw.textlength(line, font=font)
        lx = x1 + (w - lw) // 2
        ly = start_y + i * line_h
        draw.text((lx, ly), line, font=font, fill=fill)

def make_featured_thumbnail(template: Image.Image, post_title: str, category_label: str) -> Image.Image:
    img = template.copy()
    draw = ImageDraw.Draw(img)

    # 텍스트 길이 제한(썸네일에서 안 짤리게)
    title = ellipsize(post_title, 60)
    cat = ellipsize(category_label.upper(), 22)

    # 반투명 박스 영역(너 템플릿 중앙 박스가 이미 있으면, 텍스트만)
    # 텍스트 영역만 안전하게 중앙에
    title_font = get_font(64)
    cat_font = get_font(30)
    site_font = get_font(28)

    # 카테고리(상단)
    draw.text((120, 150), cat, font=cat_font, fill=(30, 30, 30))

    # 제목(중앙 박스 안)
    draw_centered_multiline(draw, (120, 190, 1080, 430), title, title_font, fill=(20,20,20))

    # 사이트명(하단)
    draw.text((120, 455), SITE_NAME, font=site_font, fill=(30, 30, 30))

    return img

def make_section_image(template: Image.Image, label: str, subtitle: str) -> Image.Image:
    img = template.copy()
    draw = ImageDraw.Draw(img)

    label_font = get_font(48)
    sub_font = get_font(32)

    label = ellipsize(label, 36)
    subtitle = ellipsize(subtitle, 60)

    # 약간 아래쪽에 배치
    draw_centered_multiline(draw, (120, 220, 1080, 360), label, label_font, fill=(20,20,20))
    draw_centered_multiline(draw, (120, 360, 1080, 440), subtitle, sub_font, fill=(30,30,30))
    return img

def insert_images_at_positions(html_content: str, img_tags: List[str]) -> str:
    """
    본문을 기준으로 상/중/하 3장 배치:
    - 상: 첫 번째 h2/h3 앞(없으면 첫 문단 뒤)
    - 중: 전체 길이 55% 근처
    - 하: Conclusion/FAQs 앞 또는 끝 80% 근처
    """
    soup = BeautifulSoup(html_content, "lxml")

    # 삽입 지점 후보 노드
    nodes = list(soup.find_all(["p","h2","h3","h4","ul","ol","table","blockquote"]))
    if not nodes:
        # 그냥 끝에 추가
        soup.append(BeautifulSoup("".join(img_tags), "lxml"))
        return str(soup.body.decode_contents() if soup.body else soup)

    def insert_before(node, tag_html):
        node.insert_before(BeautifulSoup(tag_html, "lxml"))

    # 1) 상단
    first_h = soup.find(["h2","h3"])
    if first_h:
        insert_before(first_h, img_tags[0])
    else:
        # 첫 p 뒤
        p = soup.find("p")
        if p:
            p.insert_after(BeautifulSoup(img_tags[0], "lxml"))
        else:
            nodes[0].insert_before(BeautifulSoup(img_tags[0], "lxml"))

    # nodes 다시 계산
    nodes = list(soup.find_all(["p","h2","h3","h4","ul","ol","table","blockquote"]))
    n = len(nodes)

    # 2) 중간
    mid_idx = max(0, min(n-1, int(n*0.55)))
    nodes[mid_idx].insert_before(BeautifulSoup(img_tags[1], "lxml"))

    # 3) 하단: Conclusion/FAQ 앞 우선
    concl = None
    for h in soup.find_all(["h2","h3","h4"]):
        t = h.get_text(" ", strip=True).lower()
        if "conclusion" in t or "faq" in t or "faqs" in t:
            concl = h
            break
    if concl:
        insert_before(concl, img_tags[2])
    else:
        nodes = list(soup.find_all(["p","h2","h3","h4","ul","ol","table","blockquote"]))
        n = len(nodes)
        end_idx = max(0, min(n-1, int(n*0.82)))
        nodes[end_idx].insert_before(BeautifulSoup(img_tags[2], "lxml"))

    return str(soup.body.decode_contents() if soup.body else soup)

# ----------------------------
# Main
# ----------------------------
def main():
    cat_map = fetch_categories_map()
    template = download_template_image()

    all_posts = []
    for st in POST_STATUSES:
        all_posts.extend(fetch_posts(st))
        time.sleep(SLEEP_BETWEEN_REQUESTS_SEC)

    print(f"[INFO] posts fetched: {len(all_posts)} (statuses={POST_STATUSES})")

    for idx, post in enumerate(all_posts, start=1):
        post_id = post["id"]
        title = post["title"]["rendered"] if isinstance(post.get("title"), dict) else ""
        raw_html = post["content"]["rendered"] if isinstance(post.get("content"), dict) else ""
        featured_media = int(post.get("featured_media") or 0)
        cats = post.get("categories") or []
        cat_name = cat_map.get(cats[0], "AI Tools") if cats else "AI Tools"

        print(f"[{idx}/{len(all_posts)}] post_id={post_id} title={title}")

        # 1) 텍스트 정리
        cleaned = remove_rp_tokens(raw_html)
        cleaned = remove_pricing_blocks(cleaned)
        cleaned = wrap_tables_for_mobile(cleaned)
        cleaned = inject_table_scroll_css(cleaned)

        # 2) 본문용 이미지 3장 생성(썸네일 템플릿 기반 but 라벨/부제만 변경)
        sec1 = make_section_image(template, "Quick Summary", ellipsize(title, 50))
        sec2 = make_section_image(template, "Comparison & Use Cases", cat_name)
        sec3 = make_section_image(template, "Checklist (Save / Print)", "Use the print window to save as PDF")

        sec1_id = upload_image_to_wp(sec1, f"rp_{post_id}_sec1.png", f"{title} - summary image")
        sec2_id = upload_image_to_wp(sec2, f"rp_{post_id}_sec2.png", f"{title} - comparison image")
        sec3_id = upload_image_to_wp(sec3, f"rp_{post_id}_sec3.png", f"{title} - checklist image")

        # 본문에 삽입할 img 태그
        img_tags = [
            f'<figure class="wp-block-image"><img src="{fetch_media_source_url(sec1_id)}" alt="{html.escape(title)} summary" /></figure>',
            f'<figure class="wp-block-image"><img src="{fetch_media_source_url(sec2_id)}" alt="{html.escape(title)} comparison" /></figure>',
            f'<figure class="wp-block-image"><img src="{fetch_media_source_url(sec3_id)}" alt="{html.escape(title)} checklist" /></figure>',
        ]

        cleaned = insert_images_at_positions(cleaned, img_tags)

        # 3) Featured 썸네일: “배경 + 제목/카테고리 텍스트”로 포스트마다 새로 생성
        featured_img = make_featured_thumbnail(template, html.unescape(BeautifulSoup(title, "lxml").get_text()), cat_name)
        new_featured_id = upload_image_to_wp(featured_img, f"rp_{post_id}_featured.png", f"{title} featured image")

        # 4) 포스트 업데이트(본문 + featured)
        wp_patch(
            f"/wp-json/wp/v2/posts/{post_id}",
            {
                "content": cleaned,
                "featured_media": new_featured_id,
            },
        )

        # 간단 preview 저장(아티팩트)
        with open(os.path.join(ARTIFACT_DIR, f"post_{post_id}.html"), "w", encoding="utf-8") as f:
            f.write(cleaned)

        time.sleep(SLEEP_BETWEEN_REQUESTS_SEC)

    print("[DONE] maintenance finished.")

if __name__ == "__main__":
    main()
