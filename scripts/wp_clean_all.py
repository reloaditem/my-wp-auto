import os, re, io, math, time, requests
from PIL import Image, ImageDraw, ImageFont

WP_BASE = os.environ["WP_BASE"].rstrip("/")
WP_USER = os.environ["WP_USER"]
WP_PASS = os.environ["WP_PASS"]
AUTH = (WP_USER, WP_PASS)

THUMB_BASE_MEDIA_ID = int(os.environ.get("THUMBNAIL_BASE_MEDIA_ID", "332"))
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"

DEJAVU_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
DEJAVU_REG  = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

def wp_get(url, **kw):
    r = requests.get(url, auth=AUTH, timeout=60, **kw)
    r.raise_for_status()
    return r

def wp_post(url, **kw):
    r = requests.post(url, auth=AUTH, timeout=60, **kw)
    r.raise_for_status()
    return r

def fetch_media_source_url(media_id:int)->str:
    j = wp_get(f"{WP_BASE}/wp-json/wp/v2/media/{media_id}").json()
    return j["source_url"]

def fetch_base_image()->Image.Image:
    src = fetch_media_source_url(THUMB_BASE_MEDIA_ID)
    img_bytes = requests.get(src, timeout=60).content
    return Image.open(io.BytesIO(img_bytes)).convert("RGBA")

def sanitize_title(t:str)->str:
    t = re.sub(r"\s+", " ", (t or "").strip())
    return t

def ellipsis(s:str, max_len:int)->str:
    if len(s) <= max_len: return s
    return s[:max(0, max_len-1)].rstrip() + "…"

def wrap_2_lines(title:str, line_max:int=28, total_max:int=55):
    title = sanitize_title(title)
    title = ellipsis(title, total_max)
    import textwrap
    lines = textwrap.wrap(title, width=line_max)
    if len(lines) <= 2:
        return lines
    merged = " ".join(lines[:2])
    merged = ellipsis(merged, line_max*2)
    lines2 = textwrap.wrap(merged, width=line_max)
    return lines2[:2]

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

def render_thumb(base_img:Image.Image, title:str):
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
    title_top = 205
    title_bottom = 470
    max_w = W - pad_x*2
    max_h = title_bottom - title_top

    lines = wrap_2_lines(title, 28, 55)
    font, line_h = fit_font(draw, lines, max_w, max_h)

    # Top label (inside your box region)
    label_font = ImageFont.truetype(DEJAVU_BOLD, 30)
    draw.text((pad_x, 120), "AI Tools • 2026", font=label_font, fill=(20,20,20,235))

    # Title centered
    total_h = line_h * len(lines)
    y = title_top + (max_h-total_h)//2
    for line in lines:
        w = draw.textlength(line, font=font)
        x = (W - w)/2
        draw.text((x,y), line, font=font, fill=(15,15,15,245))
        y += line_h

    # Bottom label
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

def clean_content(html:str)->str:
    # remove rp:* standalone lines
    html = re.sub(r'^\s*rp:[a-zA-Z0-9_]+\s*$', '', html, flags=re.M)
    # remove lone ? lines
    html = re.sub(r'^\s*\?\s*$', '', html, flags=re.M)
    # normalize excessive empty paragraphs
    html = re.sub(r'(<p>\s*(?:&nbsp;|\s)*<\/p>\s*){2,}', '<p></p>', html, flags=re.I)
    return html

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
    base_img = fetch_base_image()
    targets = []
    for st in ["publish", "future"]:
        targets.extend(list_posts(st))

    print("targets:", len(targets))
    for p in targets:
        post_id = p["id"]
        title = p["title"]["rendered"]
        content = p["content"]["rendered"] or ""
        cleaned = clean_content(content)

        # thumbnail generation
        png = render_thumb(base_img, sanitize_title(re.sub("<.*?>", "", title)))
        media_id = upload_png(png, f"thumb-post-{post_id}.png")

        payload = {
            "content": cleaned,
            "featured_media": media_id
        }
        update_post(post_id, payload)
        print("updated:", post_id, "featured_media:", media_id)
        time.sleep(0.5)

if __name__ == "__main__":
    main()
