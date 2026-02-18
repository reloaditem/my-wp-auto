import os, re, io, time, requests
from PIL import Image, ImageDraw, ImageFont

WP_BASE = os.environ["WP_BASE"].rstrip("/")
WP_USER = os.environ["WP_USER"]
WP_PASS = os.environ["WP_PASS"]
AUTH = (WP_USER, WP_PASS)

UNSPLASH_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "").strip()
INLINE_PROVIDER = os.environ.get("INLINE_IMAGE_PROVIDER", "unsplash").strip().lower()  # unsplash|picsum

MODE = os.environ.get("MODE", "maintain").strip().lower()      # maintain | seed
STATUSES = [s.strip() for s in os.environ.get("STATUSES", "publish,future").split(",") if s.strip()]
LIMIT = int(os.environ.get("LIMIT", "0"))
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"

# 썸네일은 seed 모드에서만 "없을 때 1회 생성"을 유지하고 싶으면(현재 구조 유지)
THUMB_BASE_MEDIA_ID = int(os.environ.get("THUMBNAIL_BASE_MEDIA_ID", "332"))
DEJAVU_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
DEJAVU_REG  = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

INLINE_START = "<!-- INLINE_IMAGES_V1_START -->"
INLINE_END   = "<!-- INLINE_IMAGES_V1_END -->"

CHECK_START = "<!-- CHECKLIST_V1_START -->"
CHECK_END   = "<!-- CHECKLIST_V1_END -->"

IMG_TAG = re.compile(r"<img\b[^>]*>", re.I)
H2 = re.compile(r"<h2\b[^>]*>(.*?)</h2>", re.I | re.S)

def wp_get(url, **kw):
    r = requests.get(url, auth=AUTH, timeout=60, **kw)
    r.raise_for_status()
    return r

def wp_post(url, **kw):
    r = requests.post(url, auth=AUTH, timeout=60, **kw)
    r.raise_for_status()
    return r

def strip_tags(s:str)->str:
    return re.sub(r"<[^>]+>", "", s or "").strip()

def clean_content(html:str)->str:
    html = re.sub(r'^\s*rp:[a-zA-Z0-9_]+\s*$', '', html, flags=re.M)
    html = re.sub(r'^\s*\?\s*$', '', html, flags=re.M)
    html = re.sub(r'(<p>\s*(?:&nbsp;|\s)*<\/p>\s*){2,}', '<p></p>', html, flags=re.I)
    return html

# ----------------- Inline images (주제맞춤 3장) -----------------
def extract_h2_titles(html:str, max_n=6):
    titles = []
    for m in H2.finditer(html or ""):
        t = strip_tags(m.group(1))
        if t and len(t) >= 3:
            titles.append(t)
        if len(titles) >= max_n:
            break
    return titles

def keywordize(s:str)->str:
    s = strip_tags(s)
    s = re.sub(r"[^a-zA-Z0-9\s\-:]", " ", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s[:80] or "ai tools"

def unsplash_random(query:str)->str:
    if not UNSPLASH_KEY:
        return ""
    q = requests.utils.quote(keywordize(query))
    api = f"https://api.unsplash.com/photos/random?query={q}&orientation=landscape&client_id={UNSPLASH_KEY}"
    r = requests.get(api, timeout=20)
    if r.status_code == 200:
        return (r.json().get("urls") or {}).get("regular") or ""
    return ""

def pick_inline_urls(title:str, html:str):
    h2s = extract_h2_titles(html)
    q1 = title
    q2 = h2s[1] if len(h2s) >= 2 else f"{title} workflow"
    q3 = h2s[-1] if h2s else f"{title} checklist"

    if INLINE_PROVIDER == "unsplash" and UNSPLASH_KEY:
        urls = []
        for q in (q1,q2,q3):
            u = unsplash_random(q)
            if u: urls.append(u)
        if len(urls) == 3:
            return urls

    seeds = [
        f"{keywordize(q1).replace(' ', '-')}-top",
        f"{keywordize(q2).replace(' ', '-')}-mid",
        f"{keywordize(q3).replace(' ', '-')}-bot",
    ]
    return [f"https://picsum.photos/seed/{s}/1200/800" for s in seeds]

def img_block(url:str, alt:str)->str:
    return (
        f'<figure style="margin:28px 0;">'
        f'<img src="{url}" alt="{alt}" style="width:100%;height:auto;border-radius:14px;" loading="lazy" />'
        f'</figure>'
    )

def render_inline_block(title:str, html:str)->str:
    urls = pick_inline_urls(title, html)
    return "\n".join([
        INLINE_START,
        img_block(urls[0], f"{title} cover"),
        img_block(urls[1], f"{title} example"),
        img_block(urls[2], f"{title} checklist"),
        INLINE_END
    ])

def upsert_inline_images_fill_only(html:str, title:str)->str:
    """
    ✅ maintain 모드 요구사항:
    - 이미 이미지가 충분히 있으면(>=3) 건드리지 않음
    - INLINE_IMAGES 마커가 이미 있으면 건드리지 않음(=이미 자동 블록 존재)
    - 없을 때만 삽입
    """
    if INLINE_START in html and INLINE_END in html:
        return html

    img_count = len(IMG_TAG.findall(html or ""))
    if img_count >= 3:
        return html

    block = render_inline_block(title, html)

    # 첫 문단 뒤에 삽입
    m = re.search(r"</p\s*>", html, flags=re.I)
    if m:
        i = m.end()
        return html[:i] + "\n" + block + "\n" + html[i:]
    return block + "\n" + html

# ----------------- Checklist + Print/Save (3번) -----------------
def checklist_block_html()->str:
    # WP에 PHP shortcode 이미 넣어둔 전제: [rp_intro_checklist_v1], [rp_save_print_v1]
    return "\n".join([
        CHECK_START,
        '<h2>Save / Print Checklist</h2>',
        '[rp_intro_checklist_v1]',
        '<ul>',
        '<li><strong>Pick a tool</strong>: shortlist 2–3 options that match your budget and workflow.</li>',
        '<li><strong>Check key features</strong>: integrations, automation, reporting, and team permissions.</li>',
        '<li><strong>Validate pricing</strong>: confirm monthly cost, add-ons, and annual discounts.</li>',
        '<li><strong>Run a 7-day test</strong>: try one real workflow end-to-end before committing.</li>',
        '<li><strong>Decide & document</strong>: write down why you chose it and what “success” looks like.</li>',
        '</ul>',
        '[rp_save_print_v1 label="Open print window" sub="In the print window, you can save as PDF or print a copy."]',
        CHECK_END
    ])

def ensure_checklist_once(html:str)->str:
    """
    - 체크리스트 마커가 있으면 그대로 둠
    - 없으면 맨 하단(Conclusion/FAQs 뒤) 쪽에 붙임
    """
    if CHECK_START in html and CHECK_END in html:
        return html

    block = checklist_block_html()

    # 이미 Save/Print 섹션 비슷한 게 있으면 중복 방지(간단 가드)
    if re.search(r"Save\s*/\s*Print\s*Checklist", html, flags=re.I):
        return html

    return (html.rstrip() + "\n\n" + block + "\n")

# ----------------- Thumbnail seed mode only -----------------
def fetch_media_source_url(media_id:int)->str:
    j = wp_get(f"{WP_BASE}/wp-json/wp/v2/media/{media_id}").json()
    return j["source_url"]

def fetch_base_image():
    src = fetch_media_source_url(THUMB_BASE_MEDIA_ID)
    img_bytes = requests.get(src, timeout=60).content
    return Image.open(io.BytesIO(img_bytes)).convert("RGBA")

def wrap_2_lines(title:str, line_max:int=28, total_max:int=55):
    title = re.sub(r"\s+", " ", (title or "").strip())
    title = title if len(title) <= total_max else (title[:total_max-1].rstrip() + "…")
    import textwrap
    lines = textwrap.wrap(title, width=line_max)
    if len(lines) <= 2:
        return lines
    merged = " ".join(lines[:2])
    merged = merged if len(merged) <= line_max*2 else (merged[:line_max*2-1].rstrip() + "…")
    return textwrap.wrap(merged, width=line_max)[:2]

def fit_font(draw, lines, max_w, max_h, start_size=74, min_size=46):
    size = start_size
    while size >= min_size:
        font = ImageFont.truetype(DEJAVU_BOLD, size=size)
        line_h = int(size * 1.18)
        total_h = line_h * len(lines)
        widths = [draw.textlength(line, font=font) for line in lines] or [0]
        if max(widths) <= max_w and total_h <= max_h:
            return font, line_h
        size -= 2
    font = ImageFont.truetype(DEJAVU_BOLD, size=min_size)
    return font, int(min_size*1.18)

def render_thumb(base_img, title:str):
    W,H = 1200,630
    bw,bh = base_img.size
    scale = max(W/bw, H/bh)
    nw,nh = int(bw*scale), int(bh*scale)
    img = base_img.resize((nw,nh), Image.LANCZOS)
    left = (nw-W)//2
    top  = (nh-H)//2
    img = img.crop((left, top, left+W, top+H)).convert("RGBA")

    draw = ImageDraw.Draw(img)
    pad_x = 90
    title_top, title_bottom = 205, 470
    max_w = W - pad_x*2
    max_h = title_bottom - title_top

    lines = wrap_2_lines(title, 28, 55)
    font, line_h = fit_font(draw, lines, max_w, max_h)

    label_font = ImageFont.truetype(DEJAVU_BOLD, 30)
    draw.text((pad_x, 120), "AI Tools • 2026", font=label_font, fill=(20,20,20,235))

    total_h = line_h * len(lines)
    y = title_top + (max_h-total_h)//2
    for line in lines:
        w = draw.textlength(line, font=font)
        x = (W - w)/2
        draw.text((x,y), line, font=font, fill=(15,15,15,245))
        y += line_h

    bottom_font = ImageFont.truetype(DEJAVU_REG, 28)
    bw2 = draw.textlength("ReloadItem.com", font=bottom_font)
    draw.text(((W-bw2)/2, 520), "ReloadItem.com", font=bottom_font, fill=(30,30,30,220))

    out = io.BytesIO()
    img.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()

def upload_png(png_bytes:bytes, filename:str)->int:
    url = f"{WP_BASE}/wp-json/wp/v2/media"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": "image/png",
    }
    r = wp_post(url, headers=headers, data=png_bytes)
    return r.json()["id"]

# ----------------- WP list/update -----------------
def list_posts(status:str):
    per_page = 100
    page = 1
    out = []
    while True:
        url = f"{WP_BASE}/wp-json/wp/v2/posts?status={status}&per_page={per_page}&page={page}"
        r = wp_get(url)
        items = r.json()
        out.extend(items)
        total_pages = int(r.headers.get("X-WP-TotalPages", "1"))
        if page >= total_pages:
            break
        page += 1
    return out

def update_post(post_id:int, payload:dict):
    if DRY_RUN:
        print("[DRY_RUN] would update", post_id, payload.keys())
        return
    wp_post(f"{WP_BASE}/wp-json/wp/v2/posts/{post_id}", json=payload)

def main():
    base_img = fetch_base_image() if MODE == "seed" else None

    targets = []
    for st in STATUSES:
        targets.extend(list_posts(st))

    if LIMIT > 0:
        targets = targets[:LIMIT]

    print("mode:", MODE, "targets:", len(targets))

    for p in targets:
        post_id = p["id"]
        title = strip_tags(p["title"]["rendered"])
        content = p["content"]["rendered"] or ""
        featured = int(p.get("featured_media") or 0)

        cleaned = clean_content(content)

        # ✅ 1번 요구: 이미지 3장 "없는 글만" 채우기
        cleaned = upsert_inline_images_fill_only(cleaned, title)

        # ✅ 3번 요구: 체크리스트(저장/출력 안내) 없으면 추가
        cleaned = ensure_checklist_once(cleaned)

        payload = {"content": cleaned}

        # 썸네일은 seed 모드에서만 "없을 때 1회 생성"
        if MODE == "seed" and featured == 0:
            png = render_thumb(base_img, title)
            media_id = upload_png(png, f"thumb-post-{post_id}.png")
            payload["featured_media"] = media_id
            print("thumb created:", post_id, media_id)
        else:
            print("thumb untouched:", post_id, featured)

        update_post(post_id, payload)
        time.sleep(0.25)

if __name__ == "__main__":
    main()
