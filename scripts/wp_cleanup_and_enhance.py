import os
import re
import sys
import json
from datetime import datetime
import requests
from requests.auth import HTTPBasicAuth

# ==============================
# ENV
# ==============================
WP_USER = os.environ.get("WP_USER")
WP_PASS = os.environ.get("WP_PASS")
WP_BASE = os.environ.get("WP_BASE_URL", "https://reloaditem.com")

DRY_RUN = os.environ.get("DRY_RUN", "1") == "1"  # 1=미리보기, 0=반영
TARGET_STATUSES = os.environ.get("TARGET_STATUSES", "publish,future").split(",")

# 이미지/썸네일(브랜드 이미지) - 너가 원하는 매트릭스 썸네일(고정)로 쓸 수 있음
BRAND_IMAGE_URL = os.environ.get("BRAND_IMAGE_URL", "").strip()  # 본문 삽입용(권장)
FEATURED_MEDIA_ID = os.environ.get("FEATURED_MEDIA_ID", "").strip()  # 대표 이미지(썸네일) 고정하고 싶으면 WP 미디어 ID 넣기

# 이미지 없으면 Unsplash 대체 사용(원하면)
UNSPLASH_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "").strip()

AUTH = HTTPBasicAuth(WP_USER, WP_PASS)
POSTS_ENDPOINT = f"{WP_BASE}/wp-json/wp/v2/posts"

# ==============================
# CLEANUP RULES
# ==============================
RP_PATTERN = re.compile(r"(^|\n)\s*rp:[a-zA-Z0-9_]+\s*(?=\n|$)")
LONE_Q_PATTERN = re.compile(r"(^|\n)\s*\?\s*(?=\n|$)")

IMG_TAG_PATTERN = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
H2_PATTERN = re.compile(r"<h2[^>]*>(.*?)</h2>", re.IGNORECASE | re.DOTALL)

def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()

# ==============================
# IMAGE HELPERS
# ==============================
def pick_image_urls(title: str) -> list[str]:
    """
    목표: 이미지 3장 (상/중/하)
    - BRAND_IMAGE_URL 있으면 3장 모두 그걸로(가장 단순/안정)
    - 없으면 Unsplash(키 있으면), 없으면 picsum
    """
    if BRAND_IMAGE_URL:
        return [BRAND_IMAGE_URL, BRAND_IMAGE_URL, BRAND_IMAGE_URL]

    # Unsplash(선택)
    if UNSPLASH_KEY:
        try:
            q = requests.utils.quote(title[:80])
            url = f"https://api.unsplash.com/search/photos?query={q}&client_id={UNSPLASH_KEY}&per_page=12"
            r = requests.get(url, timeout=20)
            if r.status_code == 200:
                results = r.json().get("results") or []
                picks = []
                for it in results[:3]:
                    u = (it.get("urls") or {}).get("regular")
                    if u:
                        picks.append(u)
                if len(picks) >= 3:
                    return picks[:3]
        except Exception:
            pass

    # fallback
    return [
        "https://picsum.photos/seed/ai-top/1200/800",
        "https://picsum.photos/seed/ai-mid/1200/800",
        "https://picsum.photos/seed/ai-bottom/1200/800",
    ]

def make_img_block(url: str, alt: str) -> str:
    return (
        f'<figure style="margin:28px 0;">'
        f'<img src="{url}" alt="{alt}" style="width:100%;height:auto;border-radius:14px;" loading="lazy" />'
        f'</figure>'
    )

# ==============================
# CONTENT ENHANCERS
# ==============================
def ensure_images_3(content: str, title: str) -> str:
    """
    - 본문에 <img>가 3장 미만이면 상/중/하로 채움
    - 3장 이상이면 건드리지 않음
    """
    img_count = len(IMG_TAG_PATTERN.findall(content or ""))
    if img_count >= 3:
        return content

    urls = pick_image_urls(_strip_html(title))
    top = make_img_block(urls[0], _strip_html(title) + " - cover")
    mid = make_img_block(urls[1], _strip_html(title) + " - screenshot")
    bot = make_img_block(urls[2], _strip_html(title) + " - checklist")

    html = content or ""

    # 1) 상단: 첫 <h2> 전에 넣기(없으면 맨 앞)
    m = re.search(r"<h2\b[^>]*>", html, flags=re.IGNORECASE)
    if m:
        html = html[:m.start()] + top + "\n" + html[m.start():]
    else:
        html = top + "\n" + html

    # 2) 중간: 두 번째 h2 직전(없으면 중간쯤)
    h2s = list(re.finditer(r"<h2\b[^>]*>", html, flags=re.IGNORECASE))
    if len(h2s) >= 2:
        i = h2s[1].start()
        html = html[:i] + mid + "\n" + html[i:]
    else:
        mid_pos = max(0, len(html)//2)
        html = html[:mid_pos] + "\n" + mid + "\n" + html[mid_pos:]

    # 3) 하단: 마지막 FAQ/Conclusion 전, 없으면 맨 끝
    tail_anchor = re.search(r"<h2\b[^>]*>\s*(FAQs?|Conclusion|Next steps)\b", html, flags=re.IGNORECASE)
    if tail_anchor:
        i = tail_anchor.start()
        html = html[:i] + bot + "\n" + html[i:]
    else:
        html = html + "\n" + bot

    return html


def ensure_comparison_table(content: str) -> str:
    """
    - 'Comparison Table' 섹션이 있는데, 테이블이 없으면 기본 테이블 삽입
    - 이미 <table> 있으면 건드리지 않음
    """
    html = content or ""
    if re.search(r"Comparison Table", html, flags=re.IGNORECASE) is None:
        return html

    # Comparison Table 이후 가까운 영역에 table이 이미 있으면 pass
    idx = re.search(r"Comparison Table", html, flags=re.IGNORECASE).start()
    window = html[idx: idx + 2000]
    if "<table" in window.lower():
        return html

    table = """
<table style="width:100%;border-collapse:collapse;margin:18px 0;">
  <thead>
    <tr>
      <th style="border:1px solid #ddd;padding:10px;text-align:left;">Tool</th>
      <th style="border:1px solid #ddd;padding:10px;text-align:left;">Best for</th>
      <th style="border:1px solid #ddd;padding:10px;text-align:left;">Starting price</th>
      <th style="border:1px solid #ddd;padding:10px;text-align:left;">Key strengths</th>
      <th style="border:1px solid #ddd;padding:10px;text-align:left;">Limitations</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td style="border:1px solid #ddd;padding:10px;">(Example) Tool A</td>
      <td style="border:1px solid #ddd;padding:10px;">Small teams</td>
      <td style="border:1px solid #ddd;padding:10px;">$—</td>
      <td style="border:1px solid #ddd;padding:10px;">Automation, templates</td>
      <td style="border:1px solid #ddd;padding:10px;">Advanced setup</td>
    </tr>
    <tr>
      <td style="border:1px solid #ddd;padding:10px;">(Example) Tool B</td>
      <td style="border:1px solid #ddd;padding:10px;">Scaling support</td>
      <td style="border:1px solid #ddd;padding:10px;">$—</td>
      <td style="border:1px solid #ddd;padding:10px;">Analytics, integrations</td>
      <td style="border:1px solid #ddd;padding:10px;">Higher tiers</td>
    </tr>
  </tbody>
</table>
<p style="font-size:0.95em;opacity:0.85;margin-top:6px;">
Pricing varies by plan, features, and billing cycle. For the most accurate and up-to-date information, refer to each vendor’s official pricing page.
</p>
""".strip()

    # 'Comparison Table' 헤딩 바로 다음 줄에 삽입
    # 케이스1) <h2>Comparison Table</h2> 형태
    html = re.sub(
        r"(<h2\b[^>]*>\s*Comparison Table\s*</h2>)",
        r"\1\n" + table,
        html,
        flags=re.IGNORECASE
    )
    # 케이스2) 텍스트로만 있을 때
    if "<table" not in html[idx: idx + 2500].lower():
        html = re.sub(
            r"(Comparison Table\s*)",
            r"\1\n" + table + "\n",
            html,
            count=1,
            flags=re.IGNORECASE
        )

    return html


def ensure_save_print_section(content: str) -> str:
    """
    - "save/print-friendly checklist" 안내 + 버튼이 없으면, 글 하단에 추가
    """
    html = content or ""
    has_print_button = ("window.print" in html) or ("print window" in html.lower() and "button" in html.lower())
    has_checklist_word = re.search(r"\bChecklist\b", html, flags=re.IGNORECASE) is not None

    if has_print_button and has_checklist_word:
        return html

    block = """
<section style="margin:34px 0;padding:18px 16px;border:1px solid rgba(255,255,255,0.18);border-radius:14px;">
  <h2 style="margin-top:0;">Checklist</h2>
  <p style="margin:0 0 12px 0;">
    Note: A save/print-friendly checklist is included below. Use the print window to save it as a PDF or print a copy.
  </p>
  <button type="button" onclick="window.print()" style="display:inline-block;padding:10px 14px;border-radius:10px;border:1px solid rgba(255,255,255,0.35);background:transparent;color:inherit;cursor:pointer;">
    Open print window (Save as PDF / Print)
  </button>
  <ul style="margin:14px 0 0 18px;">
    <li>[ ] Define your main goal</li>
    <li>[ ] Map your current workflow</li>
    <li>[ ] List required integrations</li>
    <li>[ ] Confirm security & privacy requirements</li>
    <li>[ ] Set evaluation criteria</li>
    <li>[ ] Run a structured trial (7–14 days)</li>
    <li>[ ] Plan onboarding and training</li>
    <li>[ ] Schedule review checkpoints (week 2 / week 4)</li>
  </ul>
  <p style="opacity:0.85;margin:12px 0 0 0;">
    Tip: In the print window, change the destination to <strong>Save as PDF</strong> to store a clean digital copy.
  </p>
</section>
""".strip()

    # FAQ/Conclusion 앞에 넣기(없으면 맨 끝)
    anchor = re.search(r"<h2\b[^>]*>\s*(FAQs?|Conclusion|Next steps)\b", html, flags=re.IGNORECASE)
    if anchor:
        i = anchor.start()
        html = html[:i] + block + "\n" + html[i:]
    else:
        html = html + "\n" + block

    return html


def clean_and_enhance(content: str, title: str) -> str:
    html = content or ""

    # 1) rp 제거
    html = RP_PATTERN.sub("\n", html)

    # 2) 단독 ? 제거
    html = LONE_Q_PATTERN.sub("\n", html)

    # 3) 비교표 보강
    html = ensure_comparison_table(html)

    # 4) save/print + checklist 누락 시 추가
    html = ensure_save_print_section(html)

    # 5) 이미지 3장 보강(3장 미만일 때만)
    html = ensure_images_3(html, title)

    # 6) 빈 줄 정리
    html = re.sub(r"\n{3,}", "\n\n", html).strip()

    return html


# ==============================
# WP API
# ==============================
def wp_get_all(status: str, per_page: int = 100):
    page = 1
    all_posts = []
    while True:
        url = f"{POSTS_ENDPOINT}?status={status}&per_page={per_page}&page={page}"
        r = requests.get(url, auth=AUTH, timeout=30)
        if r.status_code != 200:
            print(f"[ERROR] GET {url} -> {r.status_code} {r.text[:300]}")
            break

        items = r.json()
        if not items:
            break

        all_posts.extend(items)

        total_pages = int(r.headers.get("X-WP-TotalPages", "1"))
        if page >= total_pages:
            break
        page += 1

    return all_posts


def wp_update_post(post_id: int, payload: dict):
    url = f"{POSTS_ENDPOINT}/{post_id}"
    r = requests.post(url, auth=AUTH, json=payload, timeout=30)
    return r


def main():
    if not WP_USER or not WP_PASS:
        print("[FATAL] WP_USER / WP_PASS env is missing.")
        sys.exit(1)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backups = []
    report = []

    for st in [s.strip() for s in TARGET_STATUSES if s.strip()]:
        posts = wp_get_all(st)
        print(f"\n[INFO] status={st} posts={len(posts)}")

        for p in posts:
            post_id = p["id"]
            title = p.get("title", {}).get("rendered", "")
            content = p.get("content", {}).get("rendered", "")
            featured_media = p.get("featured_media", 0) or 0

            new_content = clean_and_enhance(content, title)

            payload = {}
            changed = False

            if new_content != content:
                payload["content"] = new_content
                changed = True

            # 대표이미지(썸네일) 고정 옵션: env FEATURED_MEDIA_ID가 있고, 현재 0이면 설정
            if FEATURED_MEDIA_ID.isdigit() and featured_media == 0:
                payload["featured_media"] = int(FEATURED_MEDIA_ID)
                changed = True

            if changed:
                backups.append({
                    "id": post_id,
                    "status": st,
                    "title": title,
                    "before": content,
                    "before_featured_media": featured_media,
                })

                if DRY_RUN:
                    print(f"[DRY] would update: ({st}) {post_id} - {title}")
                else:
                    r = wp_update_post(post_id, payload)
                    ok = r.status_code in (200, 201)
                    print(f"[UPD] ({st}) {post_id} -> {r.status_code} ok={ok}")
                    if not ok:
                        print("      ", r.text[:300])

                report.append({"id": post_id, "status": st, "title": title, "changed": True})
            else:
                report.append({"id": post_id, "status": st, "title": title, "changed": False})

    backup_path = f"enhance_backup_{stamp}.json"
    report_path = f"enhance_report_{stamp}.json"

    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump(backups, f, ensure_ascii=False, indent=2)

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n[DONE] DRY_RUN={DRY_RUN}")
    print(f"[OUT] backup: {backup_path}")
    print(f"[OUT] report: {report_path}")

if __name__ == "__main__":
    main()
