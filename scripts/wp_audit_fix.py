import os, re, json
import requests
from datetime import datetime
from typing import List, Dict, Any, Optional
from requests.auth import HTTPBasicAuth
from dateutil import tz
from PIL import Image, ImageDraw, ImageFont

# =========================
# ENV
# =========================
WP_BASE = os.environ.get("WP_BASE", "https://reloaditem.com").rstrip("/")
WP_USER = os.environ.get("WP_USER")
WP_PASS = os.environ.get("WP_PASS")

SCOPE = os.environ.get("SCOPE", "both")   # published | future | both
LIMIT = int(os.environ.get("LIMIT", "20"))
DRY_RUN = os.environ.get("DRY_RUN", "true").lower() == "true"

BACKUP_DIR = os.environ.get("BACKUP_DIR", "audit_backups")
ASSET_BG = os.environ.get("THUMB_BG", "assets/thumbnail_bg.png")

KST = tz.gettz("Asia/Seoul")

WP_POSTS = f"{WP_BASE}/wp-json/wp/v2/posts"
WP_MEDIA = f"{WP_BASE}/wp-json/wp/v2/media"

MARK_INTRO = "<!-- rp:intro_checklist_v1 -->"
MARK_SAVEPRINT = "<!-- rp:save_print_v1 -->"
MARK_PRICING = "<!-- rp:pricing_neutral_v1 -->"
MARK_TOC = "<!-- rp:toc_v1 -->"
MARK_IMAGES = "<!-- rp:images_v1 -->"

CATEGORY_LABEL_MAP = {
    "crm-software": "CRM SOFTWARE",
    "automation-tools": "AUTOMATION TOOLS",
    "marketing-ai": "AI MARKETING",
    "ai-productivity": "AI PRODUCTIVITY",
}

# =========================
# Helpers
# =========================
def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)

def strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "")

def wp_get(url: str):
    r = requests.get(url, auth=HTTPBasicAuth(WP_USER, WP_PASS), timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"WP GET failed {r.status_code}: {r.text[:200]}")
    return r.json()

def wp_post(url: str, payload: dict):
    r = requests.post(url, json=payload, auth=HTTPBasicAuth(WP_USER, WP_PASS), timeout=45)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"WP POST failed {r.status_code}: {r.text[:200]}")
    return r.json()

def backup(post_id: int, title: str, status: str, html: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9\-]+", "-", strip_tags(title)).strip("-")[:80] or "post"
    fn = f"{BACKUP_DIR}/{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{status}_{post_id}_{safe}.html"
    with open(fn, "w", encoding="utf-8") as f:
        f.write(html or "")
    return fn

# =========================
# Thumbnail generator (template 기반)
# =========================
def _load_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    # ubuntu-latest 기본 폰트
    path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    return ImageFont.truetype(path, size=size)

def wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> List[str]:
    words = text.split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        bbox = draw.textbbox((0,0), test, font=font)
        if bbox[2] <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines[:3]  # 최대 3줄

def generate_thumb(title: str, label: str, out_path: str, size=(1200, 800)):
    bg = Image.open(ASSET_BG).convert("RGBA").resize(size)
    W, H = size
    im = Image.new("RGBA", size)
    im.paste(bg, (0, 0))

    draw = ImageDraw.Draw(im)

    # 중앙 반투명 박스(가독성)
    pad = int(W * 0.08)
    box = (pad, int(H*0.18), W - pad, int(H*0.82))
    overlay = Image.new("RGBA", size, (0,0,0,0))
    od = ImageDraw.Draw(overlay)
    od.rounded_rectangle(box, radius=28, fill=(255,255,255,235))
    im = Image.alpha_composite(im, overlay)
    draw = ImageDraw.Draw(im)

    # 상단/하단 골드 라인(얇게)
    gold = (212, 175, 55, 255)
    y_top = int(H*0.14)
    y_bot = int(H*0.86)
    x1, x2 = pad, W - pad
    draw.line((x1, y_top, x2, y_top), fill=gold, width=4)
    draw.line((x1, y_bot, x2, y_bot), fill=gold, width=4)

    # 텍스트
    label_font = _load_font(34, True)
    title_font = _load_font(64, True)
    site_font = _load_font(30, True)

    # label
    label_txt = (label or "AI TOOLS").upper()
    draw.text((pad+24, int(H*0.22)), label_txt, fill=(20, 20, 20, 255), font=label_font)

    # title wrapped
    max_w = W - (pad*2) - 48
    lines = wrap_text(draw, title, title_font, max_w)
    start_y = int(H*0.33)
    for i, line in enumerate(lines):
        draw.text((pad+24, start_y + i*78), line, fill=(10, 10, 10, 255), font=title_font)

    # site
    draw.text((pad+24, int(H*0.74)), "ReloadItem.com", fill=(40, 40, 40, 255), font=site_font)

    im.convert("RGB").save(out_path, "PNG", optimize=True)

def upload_media(file_path: str, title: str) -> Optional[dict]:
    fn = os.path.basename(file_path)
    headers = {
        "Content-Disposition": f'attachment; filename="{fn}"',
        "Content-Type": "image/png",
    }
    with open(file_path, "rb") as f:
        r = requests.post(
            WP_MEDIA,
            headers=headers,
            data=f.read(),
            auth=HTTPBasicAuth(WP_USER, WP_PASS),
            timeout=60,
        )
    if r.status_code == 201:
        return r.json()
    return None

# =========================
# Content fixers
# =========================
def add_intro_note(html: str) -> str:
    if MARK_INTRO in html:
        return html
    note = (
        f'{MARK_INTRO}'
        '<p><strong>Note:</strong> A save/print-friendly checklist is included at the end of this guide. '
        'Use the print window to save it as a PDF or print a copy.</p>'
    )
    m = re.search(r"</p\s*>", html, flags=re.I)
    if m:
        i = m.end()
        return html[:i] + "\n" + note + "\n" + html[i:]
    return note + "\n" + html

def neutralize_pricing(html: str) -> str:
    if MARK_PRICING in html:
        return html
    out = html
    out = re.sub(r"\$\s?\d+(\.\d+)?\s?[–-]\s?\$\s?\d+(\.\d+)?", "Entry-level pricing available", out)
    out = re.sub(r"[$€£]\s?\d+(\.\d+)?(\s?\/\s?(month|mo|year|yr|user|seat))?", "Entry-level pricing available", out, flags=re.I)

    note = (
        f"{MARK_PRICING}"
        "<p><em>Pricing note:</em> Pricing varies by plan, features, and billing cycle. "
        "For the most accurate and up-to-date information, refer to the vendor’s official pricing page.</p>"
    )
    # 첫 H2 뒤에 넣기
    out = re.sub(r"(<h2[^>]*>.*?</h2>)", r"\1" + note, out, count=1, flags=re.S | re.I)
    return out

def ensure_save_print_section(html: str) -> str:
    if MARK_SAVEPRINT in html or 'id="save-print"' in html.lower():
        return html
    sec = f"""
{MARK_SAVEPRINT}
<h2 id="save-print">Save or Print Checklist</h2>
<p>
You can <strong>save or print</strong> this checklist for later use.
Click the button below to open the <strong>print window</strong>.
In the print window, choose <strong>"Save as PDF"</strong> to store it as a file,
or select your printer to get a physical copy.
</p>
<p>
  <button onclick="window.print()"
    style="padding:12px 18px; border-radius:12px; border:1px solid #ccc; cursor:pointer; font-weight:600;">
    Open Print Window
  </button>
</p>
<div style="border:1px solid #ddd; padding:18px; border-radius:12px; margin:20px 0;">
  <h3 style="margin-top:0;">Checklist</h3>
  <ul>
    <li>[ ] Define your main goal</li>
    <li>[ ] Map your current workflow</li>
    <li>[ ] List required integrations</li>
    <li>[ ] Confirm security &amp; privacy requirements</li>
    <li>[ ] Set evaluation criteria</li>
    <li>[ ] Run a structured trial (7–14 days)</li>
    <li>[ ] Plan onboarding and training</li>
    <li>[ ] Schedule review checkpoints (week 2 / week 4)</li>
  </ul>
</div>
<p><em>Tip:</em> In the print window, change the destination to <strong>Save as PDF</strong> to store a clean digital copy.</p>
""".strip()
    return html.rstrip() + "\n\n" + sec + "\n"

def ensure_three_images(html: str, post_title: str, label: str, media_urls: List[str]) -> str:
    if MARK_IMAGES in html:
        return html
    if len(media_urls) < 3:
        return html

    img1 = f'<img src="{media_urls[0]}" alt="{post_title}" style="width:100%; margin:28px 0;">'
    img2 = f'<img src="{media_urls[1]}" alt="{post_title} checklist" style="width:100%; margin:28px 0;">'
    img3 = f'<img src="{media_urls[2]}" alt="{post_title} tips" style="width:100%; margin:28px 0;">'

    out = html

    # 1) 첫 문단 뒤
    m = re.search(r"</p\s*>", out, flags=re.I)
    if m:
        i = m.end()
        out = out[:i] + "\n" + MARK_IMAGES + "\n" + img1 + "\n" + out[i:]
    else:
        out = MARK_IMAGES + "\n" + img1 + "\n" + out

    # 2) 중반: 두 번째 H2 뒤(없으면 4번째 문단 뒤)
    h2s = list(re.finditer(r"<h2\b[^>]*>.*?</h2>", out, flags=re.I | re.S))
    if len(h2s) >= 2:
        i = h2s[1].end()
        out = out[:i] + "\n" + img2 + "\n" + out[i:]
    else:
        ps = list(re.finditer(r"</p\s*>", out, flags=re.I))
        if len(ps) >= 4:
            i = ps[3].end()
            out = out[:i] + "\n" + img2 + "\n" + out[i:]
        else:
            out = out + "\n" + img2 + "\n"

    # 3) 후반: Save/Print 앞
    sp = re.search(r'(<h2[^>]*id="save-print"[^>]*>.*?</h2>)', out, flags=re.I | re.S)
    if sp:
        out = out[:sp.start()] + img3 + "\n" + out[sp.start():]
    else:
        out = out + "\n" + img3 + "\n"

    return out

def get_category_label(post: dict) -> str:
    # WP에선 categories는 ID라서, 여기선 기본 라벨로 두고
    # 향후 auto_post에서 slug를 확정적으로 사용
    return "AI TOOLS"

def apply_all(post: dict) -> Optional[dict]:
    html = (post.get("content") or {}).get("rendered", "") or ""
    if not html.strip():
        return None

    title = strip_tags((post.get("title") or {}).get("rendered", "")) or "Guide"
    label = get_category_label(post)

    # 1) 썸네일 3장 생성(본문 이미지 3장도 동일 스타일)
    ensure_dir("tmp_thumbs")
    paths = []
    for idx, tag in enumerate(["GUIDE", "CHECKLIST", "TIPS"], start=1):
        p = f"tmp_thumbs/{post['id']}_{idx}.png"
        generate_thumb(title if idx == 1 else title, f"{label} • {tag}", p)
        paths.append(p)

    uploaded = []
    for pth in paths:
        up = upload_media(pth, title)
        if up and up.get("source_url"):
            uploaded.append(up)
    media_urls = [u["source_url"] for u in uploaded]
    featured_id = uploaded[0]["id"] if uploaded else (post.get("featured_media") or 0)

    html2 = html
    html2 = add_intro_note(html2)
    html2 = neutralize_pricing(html2)
    html2 = ensure_save_print_section(html2)
    html2 = ensure_three_images(html2, title, label, media_urls)

    changed = (html2 != html) or (not post.get("featured_media") and featured_id)
    if not changed:
        return None

    return {
        "post_id": post["id"],
        "title": title,
        "status": post.get("status", ""),
        "link": post.get("link", ""),
        "orig_html": html,
        "new_html": html2,
        "featured_id": featured_id,
    }

def main():
    if not (WP_USER and WP_PASS):
        raise RuntimeError("Missing WP_USER / WP_PASS")

    ensure_dir(BACKUP_DIR)

    targets = []
    if SCOPE in ("published", "both"):
        targets += wp_get(f"{WP_POSTS}?status=publish&per_page={LIMIT}&orderby=date&order=desc")
    if SCOPE in ("future", "both"):
        targets += wp_get(f"{WP_POSTS}?status=future&per_page={LIMIT}&orderby=date&order=asc")

    # de-dupe
    seen, uniq = set(), []
    for p in targets:
        pid = p.get("id")
        if pid in seen: 
            continue
        seen.add(pid)
        uniq.append(p)

    print(f"Targets={len(uniq)} SCOPE={SCOPE} DRY_RUN={DRY_RUN}")

    changed = 0
    for p in uniq:
        res = apply_all(p)
        if not res:
            print(f"[SKIP] {p['id']} | {strip_tags((p.get('title') or {}).get('rendered',''))[:70]}")
            continue

        fn = backup(res["post_id"], res["title"], res["status"], res["orig_html"])
        print(f"\n[CHANGE] {res['post_id']} | {res['title']}")
        print(f"Link: {res['link']}")
        print(f"Backup: {fn}")
        print(f"Featured(Media ID): {res['featured_id']}")

        if DRY_RUN:
            preview = fn.replace(".html", "_PREVIEW.html")
            with open(preview, "w", encoding="utf-8") as f:
                f.write(res["new_html"])
            print(f"[DRY_RUN] Preview: {preview}")
        else:
            wp_post(f"{WP_POSTS}/{res['post_id']}", {
                "content": res["new_html"],
                "featured_media": res["featured_id"] or 0,
            })
            print("[UPDATED]")

        changed += 1

    print(f"\nDone. Changed={changed}")

if __name__ == "__main__":
    main()
