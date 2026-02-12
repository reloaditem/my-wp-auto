import os
import requests
from requests.auth import HTTPBasicAuth
from openai import OpenAI

# ==============================
# 환경 변수
# ==============================

OPENAI_KEY = os.environ.get('OPENAI_API_KEY')
WP_USER = os.environ.get('WP_USER')
WP_PASS = os.environ.get('WP_PASS')
WP_URL = "https://reloaditem.com/wp-json/wp/v2/posts/"

client = OpenAI(api_key=OPENAI_KEY)

topic = "Best AI Productivity Tools for Small Businesses in 2026"

# ==============================
# OpenAI 호출 함수
# ==============================

def call_openai(messages):
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.7,
    )
    return response.choices[0].message.content.strip()

# ==============================
# 1️⃣ 글 생성
# ==============================

def generate_article():
    messages = [
        {
            "role": "system",
            "content": """
You are a professional SaaS reviewer writing for small business owners.

Write a detailed SEO-optimized article (minimum 1800 words).

Requirements:
- Focus on AI productivity tools for small businesses.
- Include at least 5 specific tools.
- Mention real pricing numbers.
- Add one HTML comparison table.
- Include Pros and Cons for each tool.
- Add 5 FAQ questions and answers.
- Avoid generic phrases.
- Use clear, professional language.
- No fluff.
- Pure HTML only (no markdown).
"""
        },
        {"role": "user", "content": f"Write the full article about: {topic}"}
    ]

    return call_openai(messages)

# ==============================
# 2️⃣ 자기 개선
# ==============================

def improve_article(article):
    messages = [
        {
            "role": "system",
            "content": """
Improve the article below.

Fix:
- Generic language
- Weak explanations
- Missing pricing clarity
- Repetitive content

Strengthen:
- Specific examples
- Clear comparison points
- Commercial intent

Keep structure and HTML.
Return full improved article.
"""
        },
        {"role": "user", "content": article}
    ]

    return call_openai(messages)

# ==============================
# 3️⃣ 점수 평가
# ==============================

def score_article(article):
    messages = [
        {
            "role": "system",
            "content": """
Score this article from 0 to 100.

Criteria:
- Specificity
- SEO structure
- Commercial intent
- Trustworthiness
- Professional tone

Return ONLY a number.
"""
        },
        {"role": "user", "content": article}
    ]

    score_text = call_openai(messages)

    try:
        return int(score_text)
    except:
        return 0

# ==============================
# 4️⃣ 워드프레스 발행
# ==============================

def publish_article(content):
    payload = {
        "title": topic,
        "content": content,
        "status": "publish",
    }

    res = requests.post(
        WP_URL,
        auth=HTTPBasicAuth(WP_USER, WP_PASS),
        json=payload
    )

    print("WordPress status:", res.status_code)

# ==============================
# 실행
# ==============================

def main():
    print("Generating article...")
    article = generate_article()

    print("Improving article...")
    improved = improve_article(article)

    print("Scoring article...")
    score = score_article(improved)

    print("Final score:", score)

    if score >= 80:
        print("Publishing article...")
        publish_article(improved)
    else:
        print("Article rejected due to low score.")

if __name__ == "__main__":
    main()
