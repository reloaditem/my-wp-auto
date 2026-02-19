import os
import re
import io
import html as html_mod
import random
import requests
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from requests.auth import HTTPBasicAuth
from bs4 import BeautifulSoup
from PIL import Image

# =========================
# ENV (레포 시크릿명 그대로)
# =========================
WP_BASE = os.environ.get("WP_BASE", "").rstrip("/")
WP_USER = os.environ.get("WP_USER", "")
WP_PASS = os.environ.get("WP_PASS", "")

UNSPLASH_ACCESS_KEY = (os.environ.get("UNSPLASH_ACCESS_KEY") or "").strip()

# 대상: 공개 + 예약글
TARGET_STATUSES = [s.strip() for s in (os.environ.get("TARGET_STATUSES") or "publish,future").split(",") if s.strip()]
PER_STATUS_LIMIT = int((os.environ.get("PER_STATUS_LIMIT") or "50").strip())
DRY_RUN = (os.environ.get("DRY_RUN") or "0").strip() == "1"

# Featured 썸네일 생성(브랜드 통일)
BRAND_TEXT = (os.environ.get("BRAND_TEXT") or "RELOADITEM").strip()
FOOTER_TEXT = (os.environ.get("FOOTER_TEXT") or "AI TOOLS").strip()

# 내부 이미지 3장
ADD_BODY_IMAGES = (os.environ.get("ADD_BODY_IMAGES") or "1").strip() == "1"
UPLOAD_BODY_IMAGES_TO_WP = (os.environ.get("UPLOAD_BODY_IMAGES_TO_WP") or "1").strip() == "1"

# =========================
# WP REST
# =========================
AUTH = HTTPBasicAuth(WP_USER, WP_PASS)
WP_API = f"{WP_BASE}/wp-json/wp/v2"
POSTS_URL = f"{WP_API}/posts"
MEDIA_URL = f"{WP_API}/media"
CATS_URL = f"{WP_API}/categories"

if not (WP_BASE and WP_USER and WP_PASS):
    raise SystemExit("Missing env: WP_BASE, WP_USER, WP_PASS")

# =========================
# Regex 정리 / 금액 제거
# =========================
RP_TOKEN_RE = re.compile(r"\brp:[A-Za-z0-9_:-]+\b")
JUST_Q_RE = re.compile(r"^\s*\?\s*$", re.MULTILINE)

# Pricing 제거: PartnerStack 안전하게 "정확 금액" 싹 걷어냄
PRICE_HIT_RE = re.compile(
    r"(\$|€|£|₩)\s?\d|"
    r"\b(pricing|price|billed|annually|monthly|per\s+month|/mo|/month|per\s+year|/yr|per\s+agent|usd|eur|gbp|krw)\b",
    re.I
)

# 표 래핑 마커
TABLE_CSS_MARKER = "/* rp-table-scroll */"
SAVEPRINT_MARKER = "<!-- rp:save_print_v1 -->"
IMAGES_MARKER = "<!-- rp:body_images_v1 -->"

def wp_get(url: str, params: Optional[dict] = None):
    r = requests.get(url, params=params, auth=AUTH, timeout=60)
    return r

def wp_post(url: str, json_data: dict):
    r = requests.post(url, json=json_data, auth=AUTH, timeout=90)
    return r

def wp_upload_image_bytes(filename: str, image_bytes: bytes, mime: str = "image/jpeg") -> Optional[dict]:
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": mime,
    }
    r = requests.post(MEDIA_URL, headers=headers, data=image_bytes, auth=AUTH, timeout=120)
    if r.status_code in (200, 201):
        return r.json()
    return None

def fetch_categories_map() -> Dict[int, str]:
    out = {}
    page = 1
    while True:
        r = wp_get(CATS_URL, params={"per_page": 100, "page": page})
        if r.status_code != 200:
            break
        batch = r.json() or []
        if not batch:
            break
        for c in batch:
            out[c["id"]] = c.get("slug") or c.get("name") or ""
        if len(batch) < 100:
            break
        page += 1
    return out

def fetch_posts(status: str, limit: int) -> List[dict]:
    # per_page max 100
    r = wp_get(POSTS_URL, params={"status": status, "per_page": min(limit, 100), "orderby": "date", "order": "desc"})
    if r.status_code != 200:
        print("Fetch failed:", status, r.status_code, r.text[:200])
        return []
    return r.json() or []

# =========================
# 썸네일 생성 (블랙+골드)
# =========================
def _get_font(size: int, bold: bool = True):
    # pillow default font fallback
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
    img = Image.new("RGB", (W, H), (10, 10, 12))  # matte black
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

    # 폰트가 너무 크면 줄바꿈 후 폭 초과 가능 → 간단히 축소
    while True:
        too_wide = any(draw.textlength(ln, font=kw_font) > max_width for ln in lines)
        if not too_wide:
            break
        kw_font = _get_font(max(28, kw_font.size - 4), bold=True)
        lines = _wrap_lines(draw, kw, kw_font, max_width, max_lines=2)
        if kw_font.size <= 28:
            break

    line_h = int(kw_font.size * 1.12)
    total_h = line_h * len(lines)
    start_y = int(H*0.50) - total_h//2

    for i, ln in enumerate(lines):
        lw = draw.textlength(ln, font=kw_font)
        x = (W - lw)//2
        y = start_y + i*line_h
        draw.text((x+2, y+2), ln, font=kw_font, fill=(0, 0, 0))
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
    # alt/title set
    requests.post(f"{MEDIA_URL}/{media_id}", json={"title": title, "alt_text": alt}, auth=AUTH, timeout=60)
    return media_id

def keyword_from_category_slug(slug: str) -> str:
    m = {
        "crm-software": "CRM",
        "automation-tools": "AUTOMATION",
        "marketing-ai": "MARKETING",
        "ai-productivity": "PRODUCTIVITY",
    }
    return m.get(slug, "AI TOOLS")

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

def build_body_image_urls(title: str) -> List[str]:
    seed = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or str(random.randint(1000,9999))
    queries = [title, f"{title} software dashboard", f"{title} workflow automation"]
    urls = []
    for i, q in enumerate(queries):
        u = unsplash_url(q) or picsum(f"{seed}-{i+1}")
        urls.append(u)
    return urls

def upload_or_use(url: str, filename_prefix: str) -> str:
    if not UPLOAD_BODY_IMAGES_TO_WP:
        return url
    dl = download_image(url)
    if not dl:
        return url
    b, ctype = dl
    ext = "jpg" if "jpeg" in ctype else ("png" if "png" in ctype else "jpg")
    up = wp_upload_image_bytes(f"{filename_prefix}.{ext}", b, ctype)
    if up and up.get("source_url"):
        return up["source_url"]
    return url

# =========================
# 콘텐츠 수정 로직
# =========================
def remove_rp_and_artifacts(html_text: str) -> str:
    html_text = RP_TOKEN_RE.sub("", html_text)
    html_text = JUST_Q_RE.sub("", html_text)
    html_text = re.sub(r"\n{3,}", "\n\n", html_text)
    return html_text

def remove_pricing(html_text: str) -> str:
    soup = BeautifulSoup(html_text, "lxml")

    # 문단/리스트에서 가격 히트면 제거
    for tag in soup.find_all(["p", "li"]):
        t = tag.get_text(" ", strip=True)
        if t and PRICE_HIT_RE.search(t):
            tag.decompose()

    # 가격 언급된 표 제거
    for table in soup.find_all("table"):
        t = table.get_text(" ", strip=True)
        if t and PRICE_HIT_RE.search(t):
            table.decompose()

    # "Pricing" 헤딩 섹션 제거
    for h in soup.find_all(["h2", "h3", "h4"]):
        ht = h.get_text(" ", strip=True)
        if ht and PRICE_HIT_RE.search(ht):
            nxt = h.find_next_sibling()
            h.decompose()
            while nxt and nxt.name not in ["h2", "h3", "h4"]:
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
    if re.search(r"id=[\"']save-print[\"']", html_text, flags=re.I):
        return SAVEPRINT_MARKER + "\n" + html_text
    block = "\n".join([
        SAVEPRINT_MARKER,
        '<h2 id="save-print">Save or Print Checklist</h2>',
        '<p><strong>안내:</strong> 이 체크리스트는 <strong>저장 및 출력</strong>이 가능합니다. '
        '아래 버튼을 누르면 <strong>출력창</strong>이 열립니다. 출력창에서 <strong>"PDF로 저장"</strong>을 선택하면 저장할 수 있어요.</p>',
        '<p><button onclick="window.print()" style="padding:12px 18px;border-radius:12px;border:1px solid #ccc;cursor:pointer;font-weight:700;">출력창 열기</button></p>',
    ])
    return html_text.rstrip() + "\n\n" + block + "\n"

def insert_body_images(html_text: str, title: str) -> str:
    if not ADD_BODY_IMAGES:
        return html_text
    if IMAGES_MARKER in html_text:
        return html_text

    soup = BeautifulSoup(html_text, "lxml")
    # 이미 이미지가 3개 이상이면 마커만 추가(중복 방지)
    if len(soup.find_all("img")) >= 3:
        return IMAGES_MARKER + "\n" + html_text

    urls = build_body_image_urls(title)
    final_urls = []
    for i, u in enumerate(urls):
        final_urls.append(upload_or_use(u, f"rp_body_{re.sub(r'[^a-z0-9]+','-',title.lower())[:24]}_{i+1}"))

    tags = [
        f'<figure class="wp-block-image"><img src="{final_urls[0]}" alt="{html_mod.escape(title)} image 1" loading="lazy" style="width:100%;border-radius:14px;margin:26px 0;"></figure>',
        f'<figure class="wp-block-image"><img src="{final_urls[1]}" alt="{html_mod.escape(title)} image 2" loading="lazy" style="width:100%;border-radius:14px;margin:26px 0;"></figure>',
        f'<figure class="wp-block-image"><img src="{final_urls[2]}" alt="{html_mod.escape(title)} image 3" loading="lazy" style="width:100%;border-radius:14px;margin:26px 0;"></figure>',
    ]

    # 삽입 위치: 상/중/하
    # 상: 첫 h2 앞(없으면 첫 p 뒤)
    h2 = soup.find(["h2", "h3"])
    if h2:
        h2.insert_before(BeautifulSoup(tags[0], "lxml"))
    else:
        p = soup.find("p")
        if p:
            p.insert_after(BeautifulSoup(tags[0], "lxml"))
        else:
            soup.append(BeautifulSoup(tags[0], "lxml"))

    # 중: 55% 지점
    blocks = soup.find_all(["p", "h2", "h3", "ul", "ol", "table", "blockquote"])
    if blocks:
        mid = blocks[min(len(blocks)-1, int(len(blocks)*0.55))]
        mid.insert_before(BeautifulSoup(tags[1], "lxml"))

    # 하: conclusion/faq 앞(없으면 82% 지점)
    target = None
    for h in soup.find_all(["h2","h3","h4"]):
        t = h.get_text(" ", strip=True).lower()
        if "conclusion" in t or "faq" in t or "faqs" in t:
            target = h
            break
    if target:
        target.insert_before(BeautifulSoup(tags[2], "lxml"))
    else:
        blocks = soup.find_all(["p", "h2", "h3", "ul", "ol", "table", "blockquote"])
        if blocks:
            end = blocks[min(len(blocks)-1, int(len(blocks)*0.82))]
            end.insert_before(BeautifulSoup(tags[2], "lxml"))
        else:
            soup.append(BeautifulSoup(tags[2], "lxml"))

    out = str(soup.body.decode_contents() if soup.body else soup)
    return IMAGES_MARKER + "\n" + out

def update_post(post_id: int, content: str, featured_media: Optional[int]) -> bool:
    payload = {"content": content}
    if featured_media is not None:
        payload["featured_media"] = featured_media

    if DRY_RUN:
        print("[DRY_RUN] update post:", post_id, "featured:", bool(featured_media))
        return True

    r = wp_post(f"{POSTS_URL}/{post_id}", payload)
    if r.status_code not in (200, 201):
        print("Update failed:", post_id, r.status_code, r.text[:300])
        return False
    return True

def main():
    print("WP_BASE:", WP_BASE)
    print("TARGET_STATUSES:", TARGET_STATUSES, "PER_STATUS_LIMIT:", PER_STATUS_LIMIT, "DRY_RUN:", DRY_RUN)

    cat_map = fetch_categories_map()

    total = 0
    ok = 0

    for status in TARGET_STATUSES:
        posts = fetch_posts(status, PER_STATUS_LIMIT)
        print(f"\n== {status}: {len(posts)} posts ==")

        for p in posts:
            total += 1
            post_id = int(p.get("id"))
            title = (p.get("title") or {}).get("rendered") or ""
            content = (p.get("content") or {}).get("rendered") or ""

            cats = p.get("categories") or []
            cat_slug = cat_map.get(cats[0], "ai-tools") if cats else "ai-tools"
            keyword = keyword_from_category_slug(cat_slug)

            orig = content

            # 1) rp/이상문자
            content = remove_rp_and_artifacts(content)

            # 2) 가격 제거
            content = remove_pricing(content)

            # 3) 표 모바일 래핑 + CSS
            content = wrap_tables_mobile(content)

            # 4) 본문 이미지 3장(썸네일 재사용 X)
            content = insert_body_images(content, BeautifulSoup(title, "lxml").get_text())

            # 5) Save/Print 섹션 보장
            content = ensure_save_print(content)

            # 6) Featured 썸네일 생성(블랙+골드 브랜드 통일)
            featured_id = None
            thumb = make_brand_thumbnail_square(keyword=keyword, brand=BRAND_TEXT, footer=FOOTER_TEXT, size=1200)
            featured_id = upload_png_image(
                thumb,
                filename=f"rp_{post_id}_featured_{keyword.lower()}.png",
                title=f"{BRAND_TEXT} - {keyword}",
                alt=f"{BRAND_TEXT} - {keyword}",
            )

            changed = (content != orig) or (featured_id is not None)
            if not changed:
                print("No change:", post_id, title[:70])
                ok += 1
                continue

            print("Updating:", post_id, "|", title[:80], "| kw:", keyword)
            if update_post(post_id, content, featured_id):
                ok += 1

    print(f"\nDONE {ok}/{total}")

if __name__ == "__main__":
    main()
