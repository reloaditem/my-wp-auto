import os
import random
import requests
from requests.auth import HTTPBasicAuth
from openai import OpenAI
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

# ==============================
# ENV
# ==============================
OPENAI_KEY = os.environ.get("OPENAI_API_KEY")
WP_USER = os.environ.get("WP_USER")
WP_PASS = os.environ.get("WP_PASS")
UNSPLASH_KEY = os.environ.get("UNSPLASH_ACCESS_KEY")  # recommended

WP_BASE = "https://reloaditem.com/wp-json/wp/v2"
WP_POSTS_URL = f"{WP_BASE}/posts"
WP_CATS_URL = f"{WP_BASE}/categories"
WP_MEDIA_URL = f"{WP_BASE}/media"

client = OpenAI(api_key=OPENAI_KEY)

# ==============================
# SETTINGS
# ==============================
DAYS_TO_SCHEDULE = 7
POST_TIME_KST_HOUR = 10
POST_TIME_KST_MIN = 0

MIN_SCORE = 80
MAX_RETRY_IF_LOW_SCORE = 1

# 이미지 설정
NUM_BODY_IMAGES = 2             # ✅ 본문 이미지 2장(권장: 2~3)
SET_FEATURED_IMAGE = True       # ✅ 대표이미지(썸네일) 자동 설정

# ==============================
# HIGH-RPM PLAN (topic, category_slug)
# ==============================
PLAN = [
    ("HubSpot vs Salesforce Pricing (2026): Which CRM Is Better for Small Businesses?", "crm-software"),
    ("Best CRM Software for Small Businesses (2026): Pricing, Features, and Use Cases", "crm-software"),
    ("Zapier vs Make vs n8n: Best Automation Tool for Small Business Workflows", "automation-tools"),
    ("Best AI Customer Support Tools (2026): Chatbots, Helpdesk, and Ticket Automation", "automation-tools"),
    ("Best AI Email Marketing Tools (2026): Automation, Segmentation, and Deliverability", "marketing-ai"),
    ("Best AI Meeting Assistants (2026): Note-Taking, Transcription, and Action Items", "ai-productivity"),
    ("Notion AI vs ClickUp AI vs Asana AI: Best Project Management for Small Teams", "ai-productivity"),
]

# ==============================
# HELPERS
# ==============================
def wp_auth():
    return HTTPBasicAuth(WP_USER, WP_PASS)

def call_openai(messages, temperature=0.7):
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=temperature,
    )
    return resp.choices[0].message.content.strip()

def get_category_id_by_slug(slug: str) -> int:
    r = requests.get(WP_CATS_URL, params={"slug": slug, "per_page": 100}, auth=wp_auth(), timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"Failed to fetch categories (slug={slug}). HTTP {r.status_code}: {r.text[:200]}")
    data = r.json()
    if not data:
        raise RuntimeError(f"Category slug not found: {slug}")
    return int(data[0]["id"])

def kst_to_date_gmt(dt_kst: datetime) -> str:
    if dt_kst.tzinfo is None:
        raise ValueError("dt_kst must be timezone-aware")
    dt_utc = dt_kst.astimezone(timezone.utc)
    return dt_utc.strftime("%Y-%m-%dT%H:%M:%S")

# ==============================
# AUTO START DATE (read last scheduled date)
# ==============================
def get_latest_scheduled_post_date_gmt():
    params = {
        "status": "future",
        "per_page": 100,
        "orderby": "date",
        "order": "desc",
    }
    r = requests.get(WP_POSTS_URL, params=params, auth=wp_auth(), timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"Failed to fetch scheduled posts. HTTP {r.status_code}: {r.text[:200]}")
    posts = r.json()
    if not posts:
        return None
    return posts[0].get("date_gmt")

def compute_start_date_kst():
    KST = timezone(timedelta(hours=9))
    latest_gmt_str = get_latest_scheduled_post_date_gmt()
    if not latest_gmt_str:
        now_kst = datetime.now(KST)
        return (now_kst + timedelta(days=1)).date()

    latest_utc = datetime.strptime(latest_gmt_str, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    latest_kst = latest_utc.astimezone(KST)
    return latest_kst.date() + timedelta(days=1)

# ==============================
# IMAGES (Unsplash -> fallback picsum)
# ==============================
def pick_image_url(query: str) -> str:
    """이미지 URL 1개 선택"""
    try:
        if UNSPLASH_KEY:
            url = f"https://api.unsplash.com/search/photos?query={query}&client_id={UNSPLASH_KEY}&per_page=15"
            res = requests.get(url, timeout=10)
            if res.status_code == 200:
                results = res.json().get("results", [])
                if results:
                    return random.choice(results)["urls"]["regular"]
    except:
        pass
    return f"https://picsum.photos/seed/{random.randint(1,999999)}/1200/675"

def inject_body_images(article_html: str, query: str, n: int):
    """본문에 이미지 n장 삽입: </h1> 뒤 + 첫 <h2> 앞 ... (단순/안전)"""
    urls = [pick_image_url(query) for _ in range(n)]

    figures = []
    for u in urls:
        figures.append(
            f'<figure style="margin:28px 0; text-align:center;">'
            f'<img src="{u}" alt="{query}" style="width:100%; border-radius:12px;"/>'
            f'<figcaption style="color:#888; font-size:0.9em; margin-top:8px;">Image related to {query}</figcaption>'
            f'</figure>'
        )

    lower = article_html.lower()

    # 1) </h1> 뒤
    if "<h1" in lower:
        end = lower.find("</h1>")
        if end != -1:
            insert_at = end + len("</h1>")
            article_html = article_html[:insert_at] + figures[0] + article_html[insert_at:]
        else:
            article_html = figures[0] + article_html
    else:
        article_html = figures[0] + article_html

    if n >= 2:
        lower = article_html.lower()
        idx_h2 = lower.find("<h2")
        if idx_h2 != -1:
            article_html = article_html[:idx_h2] + figures[1] + article_html[idx_h2:]
        else:
            article_html += figures[1]

    # n이 3 이상이면 끝에 더 붙이기
    for k in range(2, n):
        article_html += figures[k]

    return article_html

# ==============================
# FEATURED IMAGE (upload to WP media and set featured_media)
# ==============================
def guess_filename_from_url(url: str) -> str:
    path = urlparse(url).path
    name = os.path.basename(path) or "image.jpg"
    if "." not in name:
        name += ".jpg"
    return name

def upload_image_to_wp_media(image_url: str, title: str) -> int | None:
    """
    외부 이미지 URL을 다운로드 후 WP media로 업로드.
    성공하면 media_id 반환, 실패하면 None.
    """
    try:
        img_res = requests.get(image_url, timeout=20)
        if img_res.status_code != 200:
            return None

        content_type = img_res.headers.get("Content-Type", "image/jpeg")
        filename = guess_filename_from_url(image_url)

        headers = {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": content_type,
        }

        media_res = requests.post(
            WP_MEDIA_URL,
            auth=wp_auth(),
            headers=headers,
            data=img_res.content,
            timeout=30
        )

        if media_res.status_code not in (200, 201):
            return None

        media_json = media_res.json()
        media_id = media_json.get("id")

        # (선택) media title 업데이트 — 실패해도 무시
        if media_id:
            try:
                requests.post(
                    f"{WP_MEDIA_URL}/{media_id}",
                    auth=wp_auth(),
                    json={"title": title, "alt_text": title},
                    timeout=20
                )
            except:
                pass

        return int(media_id) if media_id else None
    except:
        return None

# ==============================
# PROMPTS
# ==============================
def build_prompts(topic: str):
    gen_system = """
You are a professional SaaS reviewer writing for small business owners.

Write a detailed SEO-optimized article (minimum 1800 words).

Requirements:
- Pure HTML only (NO markdown, NO ``` blocks).
- Include at least 5 specific tools/products (or clear contenders if it's a comparison topic).
- Mention real pricing numbers (monthly/annual where applicable). If pricing varies, clearly state tiers.
- Add ONE HTML comparison table (<table>...</table>).
- Include Pros and Cons for each tool (or each side in comparisons).
- Add 5 FAQ questions and answers.
- Use concrete examples and practical business scenarios.
- Avoid generic filler phrases and repetition.
- Professional, neutral tone.
- Use <h2> for major sections and <p> for paragraphs.
"""
    gen_user = f"""
Write the full article about:
{topic}

Start with a clear SEO title as an <h1>.
"""
    improve_system = """
Improve the article below.

Fix:
- Generic language, fluff, repetition
- Missing pricing clarity
- Weak comparisons / shallow explanations

Strengthen:
- Specific examples and use cases
- Clear buying intent
- Better table clarity

Keep it pure HTML.
Return the full improved article (no commentary).
"""
    score_system = """
Score this article from 0 to 100.

Criteria:
- Specificity and usefulness
- SEO structure and clarity
- Commercial intent
- Trustworthiness
- Professional tone

Return ONLY a number.
"""
    return gen_system, gen_user, improve_system, score_system

def generate_improve_score(topic: str):
    gen_system, gen_user, improve_system, score_system = build_prompts(topic)

    article = call_openai(
        [{"role": "system", "content": gen_system},
         {"role": "user", "content": gen_user}],
        temperature=0.7
    )

    improved = call_openai(
        [{"role": "system", "content": improve_system},
         {"role": "user", "content": article}],
        temperature=0.5
    )

    score_text = call_openai(
        [{"role": "system", "content": score_system},
         {"role": "user", "content": improved}],
        temperature=0.0
    )

    try:
        score = int(score_text.strip())
    except:
        score = 0

    return improved, score

# ==============================
# WORDPRESS (schedule post)
# ==============================
def schedule_post(title: str, content_html: str, category_id: int, date_gmt_iso: str, featured_media_id: int | None):
    payload = {
        "title": title,
        "content": content_html,
        "status": "future",
        "date_gmt": date_gmt_iso,
        "categories": [category_id],
    }
    if featured_media_id:
        payload["featured_media"] = featured_media_id

    r = requests.post(WP_POSTS_URL, auth=wp_auth(), json=payload, timeout=30)
    return r.status_code, r.text

# ==============================
# MAIN
# ==============================
def main():
    if not (OPENAI_KEY and WP_USER and WP_PASS):
        raise RuntimeError("Missing env vars: OPENAI_API_KEY, WP_USER, WP_PASS")

    if not UNSPLASH_KEY:
        print("⚠ UNSPLASH_ACCESS_KEY not set. Images will use picsum fallback.")

    KST = timezone(timedelta(hours=9))
    start_date_kst = compute_start_date_kst()
    print(f"Auto start_date_kst (next day after last scheduled post): {start_date_kst}")

    count = min(DAYS_TO_SCHEDULE, len(PLAN))

    for i in range(count):
        topic, cat_slug = PLAN[i]

        dt_kst = datetime(
            start_date_kst.year, start_date_kst.month, start_date_kst.day,
            POST_TIME_KST_HOUR, POST_TIME_KST_MIN, 0,
            tzinfo=KST
        ) + timedelta(days=i)

        date_gmt = kst_to_date_gmt(dt_kst)

        print("=" * 60)
        print(f"[{i+1}/{count}] Topic: {topic}")
        print(f"Category slug: {cat_slug}")
        print(f"Scheduled KST: {dt_kst.isoformat()} | date_gmt: {date_gmt}")

        cat_id = get_category_id_by_slug(cat_slug)
        print(f"Resolved category: slug={cat_slug} -> id={cat_id}")

        content, score = generate_improve_score(topic)
        print(f"Score: {score}")

        retry = 0
        while score < MIN_SCORE and retry < MAX_RETRY_IF_LOW_SCORE:
            retry += 1
            print(f"Retrying (score<{MIN_SCORE})... {retry}/{MAX_RETRY_IF_LOW_SCORE}")
            content, score = generate_improve_score(topic)
            print(f"New score: {score}")

        if score >= MIN_SCORE:
            # 본문 이미지 삽입
            content = inject_body_images(content, topic, NUM_BODY_IMAGES)

            # 대표이미지 업로드 + 설정
            featured_id = None
            if SET_FEATURED_IMAGE:
                featured_url = pick_image_url(topic)
                featured_id = upload_image_to_wp_media(featured_url, title=topic)
                print(f"Featured image upload: url={featured_url} -> media_id={featured_id}")

            status, body = schedule_post(topic, content, cat_id, date_gmt, featured_id)
            print(f"WordPress status: {status}")
            if status in (200, 201):
                print("✅ Scheduled successfully.")
            else:
                print("❌ WP error:", body[:300])
        else:
            print("❌ Rejected (low score). Not scheduled.")

    print("\nDONE.")

if __name__ == "__main__":
    main()
