import os
import requests
from requests.auth import HTTPBasicAuth
from openai import OpenAI
from datetime import datetime, timedelta, timezone

# ==============================
# ENV
# ==============================
OPENAI_KEY = os.environ.get("OPENAI_API_KEY")
WP_USER = os.environ.get("WP_USER")
WP_PASS = os.environ.get("WP_PASS")

WP_BASE = "https://reloaditem.com/wp-json/wp/v2"
WP_POSTS_URL = f"{WP_BASE}/posts"
WP_CATS_URL = f"{WP_BASE}/categories"

client = OpenAI(api_key=OPENAI_KEY)

# ==============================
# 예약 설정
# ==============================
DAYS_TO_SCHEDULE = 7           # 몇 개 예약할지 (5~7 추천)
POST_TIME_KST_HOUR = 10        # 한국시간 발행 시각
POST_TIME_KST_MIN = 0

MIN_SCORE = 80
MAX_RETRY_IF_LOW_SCORE = 1     # 점수 낮으면 재시도 1회

# ==============================
# 고단가 PLAN (topic, category_slug)
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
# Helpers
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

def schedule_post(title: str, content_html: str, category_id: int, date_gmt_iso: str):
    payload = {
        "title": title,
        "content": content_html,
        "status": "future",          # 예약 발행
        "date_gmt": date_gmt_iso,    # UTC 기준 예약 시간
        "categories": [category_id],
    }
    r = requests.post(WP_POSTS_URL, auth=wp_auth(), json=payload, timeout=30)
    return r.status_code, r.text

# ==============================
# Main
# ==============================
def main():
    if not (OPENAI_KEY and WP_USER and WP_PASS):
        raise RuntimeError("Missing env vars: OPENAI_API_KEY, WP_USER, WP_PASS")

    # 내일 KST부터 하루 1개씩 예약
    KST = timezone(timedelta(hours=9))
    now_kst = datetime.now(KST)
    start_date_kst = (now_kst + timedelta(days=1)).date()

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
            status, body = schedule_post(topic, content, cat_id, date_gmt)
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
