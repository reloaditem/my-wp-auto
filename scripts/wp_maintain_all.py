import os
import re
import math
import html as html_mod
import requests
from datetime import datetime
from typing import Optional, List, Dict, Tuple
from requests.auth import HTTPBasicAuth
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont
import io

# =========================
# ENV (너가 쓰는 시크릿 이름 기준)
# =========================
WP_BASE = os.environ.get("WP_BASE", "").rstrip("/")
WP_USER = os.environ.get("WP_USER", "")
WP_PASS = os.environ.get("WP_PASS", "")

THUMB_BG_MEDIA_ID = int(os.environ.get("THUMB_BG_MEDIA_ID", "332"))  # 네가 올린 공통 배경
SITE_BRAND = os.environ.get("SITE_BRAND", "ReloadItem")              # 썸네일 상단 브랜드

# 유지/수정 범위
POST_LIMIT = int(os.environ.get("POST_LIMIT", "50"))                 # 한번에 처리할 글 수
INCLUDE_FUTURE = os.environ.get("INCLUDE_FUTURE", "1") == "1"        # 예약글 포함

# 가격 표기 제거(PartnerStack 대비)
REMOVE_PRICING = os.environ.get("REMOVE_PRICING", "1") == "1"

# 본문 이미지(이미지 3개)는 cluster에서 넣는 게 메인.
# maintain에서는 "RP 잔재 제거 + 가격 제거 + 표 모바일 대응 class" 위주로만.
FIX_TABLES = True

auth = HTTPBasicAuth(WP_USER, WP_PASS)

def wp_get(url: str, params: dict = None) -> requests.Response:
    return requests.get(url, params=params, auth=auth, timeout=60)

def wp_post(url: str, json: dict = None, files=None, headers=None) -> requests.Response:
    return requests.post(url, json=json, files=files, headers=headers, auth=auth, timeout=120)

def wp_put(url: str, json: dict = None) -> requests.Response:
    return requests.post(url, json=json, auth=auth, timeout=60)

def must_env():
    missing = []
    for k in ["WP_BASE", "WP_USER", "WP_PASS"]:
        if not os.environ.get(k):
            missing.append(k)
    if missing:
        raise SystemExit(f"Missing env: {', '.join(missing)}")

def fetch_media_source_url(media_id: int) -> Optional[str]:
    r = wp_get(f"{WP_BASE}/wp-json/wp/v2/media/{media_id}")
    if r.status_code != 200:
        return None
    data = r.json()
    return data.get("source_url")

def download_bytes(url: str) -> Optional[bytes]:
    try:
        r = requests.get(url, timeout=60)
        if r.status_code != 200:
            return None
        return r.content
    except Exception:
        return None

def safe_ascii_category(cat: str) -> str:
    # 한글 카테고리면 썸네일 폰트 깨질 수 있어서 ascii만 남기거나 비움
    # (너가 원하면 나중에 NotoSansKR 폰트 파일을 repo에 넣고 해결 가능)
    if not cat:
        return ""
    if re.search(r"[^\x00-\x7F]", cat):
        return ""
    return cat.strip()

def make_featured_image(bg_bytes: bytes, title: str, category: str) -> bytes:
    # 1200x630 (OG/썸네일 안정)
    img = Image.open(io.BytesIO(bg_bytes)).convert("RGBA")
    img = img.resize((1200, 630))

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)

    # 중앙 패널
    panel_margin = 90
    panel = (panel_margin, 140, 1200 - panel_margin, 630 - 140)
    d.rounded_rectangle(panel, radius=26, fill=(0, 0, 0, 160), outline=(212, 175, 55, 200), width=3)

    # 상/하단 골드 라인
    d.line((panel[0] + 30, panel[1] + 28, panel[2] - 30, panel[1] + 28), fill=(212, 175, 55, 220), width=3)
    d.line((panel[0] + 30, panel[3] - 28, panel[2] - 30, panel[3] - 28), fill=(212, 175, 55, 220), width=3)

    img = Image.alpha_composite(img, overlay)
    d = ImageDraw.Draw(img)

    # 폰트(환경에 기본 포함된 DejaVu 사용)
    try:
        font_title = ImageFont.truetype("DejaVuSans.ttf", 54)
        font_meta = ImageFont.truetype("DejaVuSans.ttf", 26)
        font_brand = ImageFont.truetype("DejaVuSans.ttf", 28)
    except Exception:
        font_title = ImageFont.load_default()
        font_meta = ImageFont.load_default()
        font_brand = ImageFont.load_default()

    cat = safe_ascii_category(category)
    # 상단 텍스트
    d.text((panel[0] + 40, panel[1] + 45), SITE_BRAND, fill=(255, 255, 255, 235), font=font_brand)
    if cat:
        d.text((panel[2] - 40 - d.textlength(cat, font=font_meta), panel[1] + 52), cat, fill=(212, 175, 55, 235), font=font_meta)

    # 타이틀 줄바꿈
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
    lines = lines[:3]  # 3줄까지만 (모바일 썸네일 잘림 방지)

    y = panel[1] + 125
    for line in lines:
        d.text((panel[0] + 40, y), line, fill=(255, 255, 255, 245), font=font_title)
        y += 68

    # 하단 도메인
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
    r = requests.post(
        f"{WP_BASE}/wp-json/wp/v2/media",
        data=image_bytes,
        headers=headers,
        auth=auth,
        timeout=120,
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Media upload failed: {r.status_code} {r.text[:300]}")
    return r.json()["id"]

def get_category_name(post: dict) -> str:
    # WP REST에서 categories는 ID 배열. 이름 얻으려면 별도 호출.
    cats = post.get("categories") or []
    if not cats:
        return ""
    cid = cats[0]
    r = wp_get(f"{WP_BASE}/wp-json/wp/v2/categories/{cid}")
    if r.status_code != 200:
        return ""
    return r.json().get("name", "")
def strip_pricing(html_text: str) -> str:
    if not REMOVE_PRICING:
        return html_text

    soup = BeautifulSoup(html_text, "html.parser")

    # 1) 가격 문자열 자체는 치환(삭제) — 본문은 유지
    #    (PartnerStack 민감 요소 제거 목적)
    for node in soup.find_all(string=True):
        s = str(node)
        s2 = re.sub(r"\$\s?\d+(\.\d+)?", "", s)                 # $99, $99.9 제거
        s2 = re.sub(r"\b\d+\s*/\s*mo\b", "", s2, flags=re.I)    # 19/mo 제거
        s2 = re.sub(r"\bper\s+month\b", "", s2, flags=re.I)     # per month 제거
        s2 = re.sub(r"\bmonthly\b", "", s2, flags=re.I)         # monthly 제거
        if s2 != s:
            node.replace_with(s2)

    # 2) “Pricing:” 같은 가격 섹션 문단만 제거(전체 삭제 X)
    #    너무 공격적으로 지우면 본문 망가져서, '가격 섹션'으로 보이는 것만 제거
    pricing_pat = re.compile(r"\b(pricing\s*:|price\s*:|billing\s*:)\b", re.I)

    # p/li/figcaption 등 텍스트 블록에서 pricing_pat 잡히면 그 블록만 제거
    for tag in soup.find_all(["p", "li", "figcaption", "blockquote"]):
        txt = tag.get_text(" ", strip=True)
        if pricing_pat.search(txt):
            tag.decompose()

    # 3) 표(table)에서 가격 패턴이 강하게 보이는 row만 제거
    row_pat = re.compile(r"(\$\s?\d+|\bper\s+month\b|\bmonthly\b|\b\/\s*mo\b)", re.I)
    for tr in soup.find_all("tr"):
        txt = tr.get_text(" ", strip=True)
        if row_pat.search(txt):
            tr.decompose()

    return str(soup)


def clean_rp_markers(html_text: str) -> str:
    # 과거 rp:xxx 텍스트로 박힌 것 / 또는 주석 형태 제거
    html_text = re.sub(r"\brp:[a-zA-Z0-9_\-]+\b", "", html_text)
    html_text = re.sub(r"<!--\s*rp:[^>]+-->", "", html_text)
    return html_text

def fix_tables(html_text: str) -> str:
    if not FIX_TABLES:
        return html_text
    # table에 wrapper class를 넣기 (CSS는 WP쪽에 추가)
    soup = BeautifulSoup(html_text, "html.parser")
    for table in soup.find_all("table"):
        # 이미 wrapper가 있으면 스킵
        parent = table.parent
        if parent and parent.name == "div" and "ri-table" in (parent.get("class") or []):
            continue
        wrapper = soup.new_tag("div")
        wrapper["class"] = ["ri-table"]
        table.wrap(wrapper)
        table["class"] = list(set((table.get("class") or []) + ["ri-table__table"]))
    return str(soup)

def list_posts(status: str, per_page: int = 50) -> List[dict]:
    posts = []
    page = 1
    while True:
        r = wp_get(f"{WP_BASE}/wp-json/wp/v2/posts", params={"status": status, "per_page": per_page, "page": page})
        if r.status_code != 200:
            break
        batch = r.json()
        if not batch:
            break
        posts.extend(batch)
        if len(batch) < per_page:
            break
        page += 1
        if len(posts) >= POST_LIMIT:
            break
    return posts[:POST_LIMIT]

def update_post(post_id: int, payload: dict):
    r = wp_put(f"{WP_BASE}/wp-json/wp/v2/posts/{post_id}", json=payload)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Post update failed: {post_id} {r.status_code} {r.text[:300]}")

def main():
    must_env()

    bg_url = fetch_media_source_url(THUMB_BG_MEDIA_ID)
    if not bg_url:
        raise SystemExit(f"Cannot fetch background media source_url for id={THUMB_BG_MEDIA_ID}")
    bg_bytes = download_bytes(bg_url)
    if not bg_bytes:
        raise SystemExit("Cannot download background image bytes")

    statuses = ["publish"]
    if INCLUDE_FUTURE:
        statuses.append("future")

    all_posts = []
    for st in statuses:
        all_posts.extend(list_posts(st))

    print(f"Found posts: {len(all_posts)}")

    for p in all_posts:
        pid = p["id"]
        title = (p.get("title") or {}).get("rendered", "").strip()
        content = (p.get("content") or {}).get("rendered", "")

        # 1) 본문 정리
        new_content = content
        new_content = clean_rp_markers(new_content)
        new_content = strip_pricing(new_content)
        new_content = fix_tables(new_content)

        # 2) Featured 이미지: "고정 ID"가 아니라 글마다 생성해 업로드 → featured_media로 세팅
        cat_name = get_category_name(p)
        thumb_bytes = make_featured_image(bg_bytes, html_mod.unescape(title), cat_name)
        media_id = upload_media(thumb_bytes, f"thumb_{pid}.jpg")

        # 본문이 너무 짧아지면(실수로 삭제) 업데이트하지 않게 방어
        plain = BeautifulSoup(new_content, "html.parser").get_text(" ", strip=True)
        if len(plain) < 200:   # 200자 이하면 위험으로 간주
            print(f"SKIP content overwrite (too short) post {pid}")
        payload = {"featured_media": media_id}
        else:
    payload = {"content": new_content, "featured_media": media_id}
        payload = {
            "content": new_content,
            "featured_media": media_id,
        }

        update_post(pid, payload)
        print(f"Updated post {pid} | featured_media={media_id}")

if __name__ == "__main__":
    main()
