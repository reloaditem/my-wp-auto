import os
import requests
import random
from datetime import datetime, timedelta
from typing import Optional
from requests.auth import HTTPBasicAuth
from openai import OpenAI

# ==============================
# 환경 변수
# ==============================

OPENAI_KEY = os.environ.get("OPENAI_API_KEY")
UNSPLASH_KEY = os.environ.get("UNSPLASH_ACCESS_KEY")
WP_USER = os.environ.get("WP_USER")
WP_PASS = os.environ.get("WP_PASS")

WP_POST_URL = "https://reloaditem.com/wp-json/wp/v2/posts"
WP_MEDIA_URL = "https://reloaditem.com/wp-json/wp/v2/media"

client = OpenAI(api_key=OPENAI_KEY)

# ==============================
# 카테고리 슬러그 매핑
# ==============================

CATEGORY_SLUGS = [
    "crm-software",
    "automation-tools",
    "marketing-ai",
    "ai-productivity",
]

# ==============================
# OpenAI 호출
# ==============================

def call_openai(messages):
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.7,
    )
    return response.choices[0].message.content.strip()

# ==============================
# 글 생성
# ==============================

def generate_article(topic):
    messages = [
        {
            "role": "system",
            "content": """
You are a professional SaaS reviewer writing for small businesses.

Write a detailed SEO article (minimum 1500 words).
Include pricing, pros/cons, comparison table.
Use clean HTML only.
Insert [IMAGE1] and [IMAGE2] placeholders naturally.
"""
        },
        {"role": "user", "content": f"Write about: {topic}"}
    ]
    return call_openai(messages)

# ==============================
# Unsplash 이미지
# ==============================

def get_image_url(query):
    url = f"https://api.unsplash.com/search/photos?query={query}&client_id={UNSPLASH_KEY}&per_page=10"
    res = requests.get(url, timeout=10)
    if res.status_code == 200:
        results = res.json().get("results")
        if results:
            return random.choice(results)["urls"]["regular"]
    return f"https://picsum.photos/seed/{random.randint(1,9999)}/1200/800"

# ==============================
# 워드프레스 이미지 업로드
# ==============================

def upload_image_to_wp(image_url: str, title: str) -> Optional[int]:
    image_data = requests.get(image_url).content

    headers = {
        "Content-Disposition": f'attachment; filename="{title}.jpg"',
        "Content-Type": "image/jpeg",
    }

    response = requests.post(
        WP_MEDIA_URL,
        headers=headers,
        data=image_data,
        auth=HTTPBasicAuth(WP_USER, WP_PASS),
    )

    if response.status_code == 201:
        media_id = response.json()["id"]
        print("Featured image uploaded:", media_id)
        return media_id

    print("Image upload failed:", response.status_code)
    return None

# ==============================
# 카테고리 ID 조회
# ==============================

def get_category_id(slug):
    url = f"https://reloaditem.com/wp-json/wp/v2/categories?slug={slug}"
    res = requests.get(url, auth=HTTPBasicAuth(WP_USER, WP_PASS))
    if res.status_code == 200 and res.json():
        return res.json()[0]["id"]
    return None

# ==============================
# 마지막 예약 날짜 조회
# ==============================

def get_last_scheduled_date():
    res = requests.get(
        WP_POST_URL + "?status=future&per_page=100",
        auth=HTTPBasicAuth(WP_USER, WP_PASS),
    )

    if res.status_code != 200:
        return datetime.now()

    posts = res.json()
    if not posts:
        return datetime.now()

    dates = [datetime.fromisoformat(p["date"]) for p in posts]
    return max(dates)

# ==============================
# 발행
# ==============================

def publish_article(title, content, category_slug, publish_date):

    category_id = get_category_id(category_slug)
    image_url = get_image_url(title)

    featured_id = upload_image_to_wp(image_url, title)

    # 본문 이미지 2장 삽입
    img1 = f'<img src="{image_url}" style="width:100%; margin:30px 0;">'
    img2_url = get_image_url(title + " software")
    img2 = f'<img src="{img2_url}" style="width:100%; margin:30px 0;">'

    content = content.replace("[IMAGE1]", img1)
    content = content.replace("[IMAGE2]", img2)

    payload = {
        "title": title,
        "content": content,
        "status": "future",
        "date": publish_date.isoformat(),
        "categories": [category_id] if category_id else [],
        "featured_media": featured_id if featured_id else 0,
    }

    res = requests.post(
        WP_POST_URL,
        json=payload,
        auth=HTTPBasicAuth(WP_USER, WP_PASS),
    )

    print("WordPress status:", res.status_code)

# ==============================
# 실행
# ==============================

def main():

    topics = [
        "Best CRM Software for Small Businesses (2026)",
        "Zapier vs Make vs n8n Comparison (2026)",
        "Best AI Marketing Tools for Lead Generation",
    ]

    last_date = get_last_scheduled_date()
    start_date = last_date + timedelta(days=1)

    print("Start scheduling from:", start_date.date())

    for i, topic in enumerate(topics):

        category_slug = random.choice(CATEGORY_SLUGS)
        publish_date = start_date + timedelta(days=i)

        print("Generating:", topic)

        article = generate_article(topic)

        publish_article(topic, article, category_slug, publish_date)

        print("Scheduled:", publish_date.date())

if __name__ == "__main__":
    main()
