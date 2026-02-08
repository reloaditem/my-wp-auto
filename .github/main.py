import os
import requests
from requests.auth import HTTPBasicAuth
from openai import OpenAI
import random
import time

# 환경 변수 로드
OPENAI_KEY = os.environ.get('OPENAI_API_KEY')
UNSPLASH_KEY = os.environ.get('UNSPLASH_ACCESS_KEY')
WP_USER = os.environ.get('WP_USER')
WP_PASS = os.environ.get('WP_PASS')
WP_URL = "https://reloaditem.com/wp-json/wp/v2/posts"

client = OpenAI(api_key=OPENAI_KEY)

def get_unsplash_images(queries, num_images=5):
    """한국 테마를 섞어서 이미지를 가져옵니다."""
    if not UNSPLASH_KEY: return []
    image_urls = []
    korean_keywords = ['korea', 'seoul', 'korean culture', 'korean tradition', 'seoul city']
    
    for query in queries:
        search_query = f"{query.strip()} {random.choice(korean_keywords)}"
        try:
            url = f"https://api.unsplash.com/search/photos?query={search_query}&client_id={UNSPLASH_KEY}&per_page=1"
            res = requests.get(url, timeout=10).json()
            if res.get('results'):
                image_urls.append(res['results'][0]['urls']['regular'])
        except: continue
        if len(image_urls) >= num_images: break

    while len(image_urls) < num_images:
        image_urls.append("https://images.unsplash.com/photo-1517154421773-0529f29ea451?q=80&w=1000") # 서울 기본 이미지
    return image_urls

def get_blog_content(post_number):
    """한국 관련 완전 자동 주제로 글을 생성합니다."""
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a professional blogger. Write a long post about a UNIQUE South Korean topic. ENGLISH ONLY."},
                {"role": "user", "content": f"Post {post_number}: Write a detailed blog post about a unique aspect of Korea. \nLine 1: Title: [Title]\nLine 2: Keywords: [6 keywords]\nBody: 6 sections with emojis. Place [IMAGE1] to [IMAGE6] tags."}
            ]
        )
        text = response.choices[0].message.content.strip()
        lines = text.split('\n')
        title = lines[0].replace("Title:", "").strip()
        keywords = lines[1].replace("Keywords:", "").split(",") if "Keywords:" in lines[1] else ["korea"]
        
        image_urls = get_unsplash_images(keywords, 6)
        content_body = "\n".join(lines[2:]).strip()

        for i, url in enumerate(image_urls):
            tag = f"[IMAGE{i+1}]"
            img_html = f'<div style="text-align:center; margin:35px 0;"><img src="{url}" style="width:100%; max-width:750px; border-radius:20px; box-shadow: 0 10px 20px rgba(0,0,0,0.15);"></div>'
            content_body = content_body.replace(tag, img_html) if tag in content_body else content_body + "<br>" + img_html

        return title, content_body.replace("\n", "<br>")
    except Exception as e:
        return "Error", str(e)

def post_to_wordpress(title, content, is_first):
    """첫 번째 포스팅만 발행(publish), 나머지는 임시(draft)로 설정합니다."""
    # 핵심 로직: 첫 번째 글이면 publish, 아니면 draft
    status = "publish" if is_first else "draft"
    
    payload = {"title": title, "content": content, "status": status}
    res = requests.post(WP_URL, auth=HTTPBasicAuth(WP_USER, WP_PASS), json=payload)
    print(f"[{status}] Result: {res.status_code} - {title}")

if __name__ == "__main__":
    num_posts = random.randint(2, 3) # 2~3개 생성
    print(f"🚀 Starting {num_posts} posts...")
    
    for i in range(num_posts):
        is_first = (i == 0) # 첫 번째 포스팅인지 확인
        title, content = get_blog_content(i + 1)
        post_to_wordpress(title, content, is_first)
        time.sleep(10) # 서버 부하 방지 간격
