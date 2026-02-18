import os
import re
import io
import random
import requests
from datetime import datetime
from typing import Optional, List, Dict, Tuple
from requests.auth import HTTPBasicAuth

# ==============================
# ENV
# ==============================
WP_BASE = os.environ.get("WP_BASE", "https://reloaditem.com").rstrip("/")
WP_USER = os.environ["WP_USER"]
WP_PASS = os.environ["WP_PASS"]

# 썸네일 고정(원하면 0으로)
FEATURED_MEDIA_ID = int(os.environ.get("FEATURED_MEDIA_ID", "332"))
FORCE_FEATURED = os.environ.get("FORCE_FEATURED", "1").strip() == "1"

# 예약글 포함 기본값: publish,future
TARGET_STATUSES = [s.strip() for s in os.environ.get("TARGET_STATUSES", "publish,future").split(",") if s.strip()]
PER_STATUS_LIMIT = int(os.environ.get("PER_STATUS_LIMIT", "30"))  # 상태별 몇 개 처리할지
DRY_RUN = os.environ.get("DRY_RUN", "0").strip() == "1"

# 본문 이미지 3장 업로드/삽입
ADD_IMAGES = os.environ.get("ADD_IMAGES", "1").strip() == "1"
UPLOAD_IMAGES = os.environ.get("UPLOAD_IMAGES", "1").strip() == "1"  # 1=WP 미디어로 업로드(추천)
IMAGE_SOURCE = os.environ.get("IMAGE_SOURCE", "picsum").strip().lower()  # picsum or unsplash(키없으면 자동 picsum)
UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "").strip()

# 일괄 수정 안전장치(중복 삽입 방지 마커)
IMAGES_MARKER = "<!-- rp:images_v1 -->"
SAVEPRINT_MARKER = "<!-- rp:save_print_v1 -->"

AUTH = HTTPBasicAuth(WP_USER, WP_PASS)
WP_POST_URL = f"{WP_BASE}/wp-json/wp/v2/posts"
WP_MEDIA_URL = f"{WP_BASE}/wp-json/wp/v2/media"

# ==============================
# Regex: 금액/통화/월요금 제거
# ==============================
CURRENCY_RE = re.compile(
    r"(\$|€|£|₩)\s?\d[\d,]*(?:\.\d+)?|\d[\d,]*(?:\.\d+)?\s?(\$|€|£|£|₩)",
    re.I,
)
PER_RE = re.compile(r"\b(per\s+(month|mo|year|yr)|/mo|/month|/yr|/year)\b", re.I)

# "$10/month", "10 USD", "USD 10" 류도 제거
USD_STYLE_RE = re.compile(r"\b(?:USD|US\$|AUD|CAD|EUR|GBP|KRW)\s?\d[\d,]*(?:\.\d+)?\b", re.I)
CURRENCY_CODE_AFTER_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?\s?(?:USD|AUD|CAD|EUR|GBP|KRW)\b", re.I)

# ==============================
# Regex: 표 모바일 래핑
# ==============================
TABLE_RE = re.compile(r"(<table\b[^>]*>)(.*?)(</table>)", re.I | re.S)

# 이미지는 이미 3장 이상이면 건드리지 않음
IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.I)

def wp_get(url: str):
    return requests.get(url, auth=AUTH, timeout=60)

def wp_post(url: str, json_data: dict):
    return requests.post(url, auth=AUTH, json=json_data, timeout=90)

def wp_upload_image_bytes(filename: str, image_bytes: bytes, mime: str = "image/jpeg") -> Optional[Dict]:
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": mime,
    }
    r = requests.post(WP_MEDIA_URL, headers=headers, data=image_bytes, auth=AUTH, timeout=120)
    if r.status_code in (200, 201):
        return r.json()
    print("Upload failed:", r.status_code, r.text[:300])
    return None

def fetch_posts(status: str, per_page: int) -> List[Dict]:
    # WordPress REST는 페이지네이션 있음
    url = f"{WP_POST_URL}?status={status}&per_page={min(per_page,100)}"
    r = wp_get(url)
    if r.status_code != 200:
        print("Fetch posts failed:", status, r.status_code, r.text[:200])
        return []
    return r.json() or []

def sanitize_pricing(html: str) -> str:
    html = CURRENCY_RE.sub("pricing varies", html)
    html = USD_STYLE_RE.sub("pricing varies", html)
    html = CURRENCY_CODE_AFTER_RE.sub("pricing varies", html)
    html = PER_RE.sub("", html)
    # 자잘한 중복 표현 정리
    html = re.sub(r"\bpricing varies\b(?:\s*[-–—]\s*pricing varies\b)+", "pricing varies", html, flags=re.I)
    return html

def wrap_tables_for_mobile(html: str) -> str:
    def repl(m):
        table_open, inner, table_close = m.group(1), m.group(2), m.group(3)
        # 이미 래핑되어 있으면 스킵
        # 아주 단순하게 근처에 rp-table-wrap 있으면 건너뜀
        snippet_before = html[max(0, m.start()-120):m.start()]
        if "rp-table-wrap" in snippet_before:
            return m.group(0)
        return (
            '<div class="rp-table-wrap" style="overflow-x:auto; -webkit-overflow-scrolling:touch; width:100%; margin:16px 0;">'
            f"{table_open}{inner}{table_close}</div>"
        )
    return TABLE_RE.sub(repl, html)

def remove_weird_artifacts(html: str) -> str:
    # 예전 rp 글자/이상한 백틱/깨진 따옴표 일부 정리(과격하게 지우진 않음)
    html = html.replace("&#8220;`", "")
    html = html.replace("&#8221;`", "")
    html = html.replace("“`", "").replace("”`", "")
    return html

def picsum_url(seed: str, w: int = 1200, h: int = 800) -> str:
    return f"https://picsum.photos/seed/{seed}/{w}/{h}"

def unsplash_random_url(query: str) -> Optional[str]:
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
    ctype = r.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
    return r.content, ctype

def title_seed(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    return s[:50] or f"post-{random.randint(1000,9999)}"

def build_image_blocks(title: str) -> List[str]:
    seed = title_seed(title)
    queries = [
        title,
        f"{title} software dashboard",
        f"{title} workflow automation",
    ]

    urls = []
    for i, q in enumerate(queries):
        if IMAGE_SOURCE == "unsplash":
            u = unsplash_random_url(q) or picsum_url(f"{seed}-{i+1}")
        else:
            u = picsum_url(f"{seed}-{i+1}")
        urls.append(u)

    # 업로드 모드면, 3장 다운로드 후 WP 업로드 -> source_url 사용
    final_urls = []
    if UPLOAD_IMAGES:
        for i, u in enumerate(urls):
            dl = download_image(u)
            if not dl:
                # fallback
                dl = download_image(picsum_url(f"{seed}-fb-{i+1}"))
                if not dl:
                    final_urls.append(u)
                    continue
            b, ctype = dl
            ext = "jpg" if "jpeg" in ctype else ("png" if "png" in ctype else "jpg")
            up = wp_upload_image_bytes(f"{seed}_{i+1}.{ext}", b, ctype)
            if up and up.get("source_url"):
                final_urls.append(up["source_url"])
            else:
                final_urls.append(u)
    else:
        final_urls = urls

    def img(url: str, alt: str, idx: int) -> str:
        return (
            f'<img src="{url}" alt="{alt}" '
            f'style="width:100%; margin:28px 0; border-radius:14px;" loading="lazy">'
        )

    return [
        img(final_urls[0], f"{title} cover", 1),
        img(final_urls[1], f"{title} example", 2),
        img(final_urls[2], f"{title} workflow", 3),
    ]

def insert_images_strategic(html: str, title: str) -> str:
    # 이미 마커가 있거나 이미지가 충분하면 스킵
    if IMAGES_MARKER in html:
        return html
    if len(IMG_TAG_RE.findall(html)) >= 3:
        # 그래도 마커만 남겨서 다음번 중복방지
        return IMAGES_MARKER + "\n" + html

    blocks = build_image_blocks(title)

    # 1) 상단: 첫 </p> 뒤
    top = blocks[0]
    m = re.search(r"</p\s*>", html, flags=re.I)
    if m:
        i = m.end()
        html = html[:i] + "\n" + top + "\n" + html[i:]
    else:
        html = top + "\n" + html

    # 2) 중간: 두 번째 <h2> 앞(없으면 첫 <h2> 앞, 그것도 없으면 중간)
    mid = blocks[1]
    h2s = list(re.finditer(r"<h2\b[^>]*>", html, flags=re.I))
    if len(h2s) >= 2:
        pos = h2s[1].start()
        html = html[:pos] + mid + "\n" + html[pos:]
    elif len(h2s) == 1:
        pos = h2s[0].start()
        html = html[:pos] + mid + "\n" + html[pos:]
    else:
        pos = max(0, len(html)//2)
        html = html[:pos] + "\n" + mid + "\n" + html[pos:]

    # 3) 하단: Save/Print / FAQ / Conclusion 앞
    bot = blocks[2]
    anchor = re.search(r"<h2\b[^>]*>\s*(Save|FAQ|FAQs|Conclusion)\b", html, flags=re.I)
    if anchor:
        pos = anchor.start()
        html = html[:pos] + bot + "\n" + html[pos:]
    else:
        html = html.rstrip() + "\n" + bot + "\n"

    # 마커 추가(중복 방지)
    return IMAGES_MARKER + "\n" + html

def ensure_save_print_section(html: str) -> str:
    # 이미 있으면 건드리지 않음
    if SAVEPRINT_MARKER in html:
        return html

    # 기존에 save/print 섹션이 있으면 마커만 추가
    if re.search(r"id=[\"']save-print[\"']", html, flags=re.I) or re.search(r"Save\s+or\s+Print", html, flags=re.I):
        return SAVEPRINT_MARKER + "\n" + html

    # 없으면 최소한의 안내 + 버튼(다운로드 대신 저장/출력)
    block = "\n".join([
        SAVEPRINT_MARKER,
        '<h2 id="save-print">Save or Print Checklist</h2>',
        '<p><strong>Note:</strong> You can <strong>save or print</strong> this checklist for later use. '
        'Click the button below to open the <strong>print window</strong>. '
        'In the print window, choose <strong>"Save as PDF"</strong> or print a copy.</p>',
        '<p><button onclick="window.print()" style="padding:12px 18px; border-radius:12px; border:1px solid #ccc; cursor:pointer; font-weight:600;">Open Print Window</button></p>',
    ])
    return html.rstrip() + "\n\n" + block + "\n"

def update_post(post_id: int, new_content: str, featured_media: Optional[int] = None) -> bool:
    payload = {"content": new_content}
    if featured_media is not None:
        payload["featured_media"] = featured_media

    if DRY_RUN:
        print("[DRY_RUN] would update:", post_id, "featured_media:", featured_media is not None)
        return True

    r = wp_post(f"{WP_POST_URL}/{post_id}", payload)
    ok = r.status_code in (200, 201)
    if not ok:
        print("Update failed:", post_id, r.status_code, r.text[:300])
    return ok

def process_one(post: Dict) -> bool:
    post_id = post.get("id")
    title = (post.get("title") or {}).get("rendered") or ""
    content = (post.get("content") or {}).get("rendered") or ""

    if not post_id or not content:
        return False

    original = content

    # 1) 금액 제거(PartnerStack 안전)
    content = sanitize_pricing(content)

    # 2) 이상한 잔여물 정리(rp/백틱 등)
    content = remove_weird_artifacts(content)

    # 3) 표 모바일 가로스크롤 래핑
    content = wrap_tables_for_mobile(content)

    # 4) 본문 이미지 3장 강제(없으면 생성/업로드해서 삽입)
    if ADD_IMAGES:
        content = insert_images_strategic(content, title)

    # 5) Save/Print 섹션 보장(없으면 추가)
    content = ensure_save_print_section(content)

    # 6) 썸네일 featured 고정(원하면)
    featured = FEATURED_MEDIA_ID if FORCE_FEATURED else None

    changed = (content != original) or (featured is not None)
    if not changed:
        print("No change:", post_id, "-", title[:60])
        return True

    print("Updating:", post_id, "-", title[:80])
    return update_post(post_id, content, featured_media=featured)

def main():
    print("WP_BASE:", WP_BASE)
    print("TARGET_STATUSES:", TARGET_STATUSES, "PER_STATUS_LIMIT:", PER_STATUS_LIMIT)
    print("FORCE_FEATURED:", FORCE_FEATURED, "FEATURED_MEDIA_ID:", FEATURED_MEDIA_ID)
    print("ADD_IMAGES:", ADD_IMAGES, "UPLOAD_IMAGES:", UPLOAD_IMAGES, "IMAGE_SOURCE:", IMAGE_SOURCE)
    print("DRY_RUN:", DRY_RUN)

    total = 0
    ok = 0

    for status in TARGET_STATUSES:
        posts = fetch_posts(status, PER_STATUS_LIMIT)
        print(f"\n== {status} posts: {len(posts)} ==")
        for p in posts:
            total += 1
            if process_one(p):
                ok += 1

    print(f"\nDONE: {ok}/{total} processed successfully.")

if __name__ == "__main__":
    main()
