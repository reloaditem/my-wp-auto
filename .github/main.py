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

def get_unsplash_images(queries, num_images=6):
    """육아 주제에 한국적 요소를 결합하여 사진을 검색합니다."""
    if not UNSPLASH_KEY: return []
    image_urls = []
    
    # 육아와 한국을 결합하는 핵심 접두어
    korean_context = ["Korean baby", "Korean family", "Korean mom", "Korean dad", "Korean child"]
    
    for query in queries:
        # 지피티가 준 키워드에 'Korean'을 붙여서 육아 관련 사진이 나오게 함
        search_query = f"Korean {query.strip()}"
        try:
            url = f"https://api.unsplash.com/search/photos?query={search_query}&client_id={UNSPLASH_KEY}&per_page=1"
            res = requests.get(url, timeout=10).json()
            if res.get('results'):
                image_urls.append(res['results'][0]['urls']['regular'])
            else:
                # 결과가 없으면 육아 관련 한국인 사진 기본형으로 검색
                backup_query = random.choice(korean_context)
                url = f"https://api.unsplash.com/search/photos?query={backup_query}&client_id={UNSPLASH_KEY}&per_page=1"
                res = requests.get(url, timeout=10).json()
                if res.get('results'):
                    image_urls.append(res['results'][0]['urls']['regular'])
        except: continue
        if len(image_urls) >= num_images: break

    # 끝까지 이미지가 부족하면 가장 안전한 육아 이미지로 채움
    while len(image_urls) < num_images:
        image_urls.append("https://images.unsplash.com/photo-1555252333-9f8e92e65df9?q=80&w=1000") # 육아 기본 이미지
    return image_urls

def get_blog_content(post_number):
    """한국의 육아와 라이프스타일 주제로 글을 생성합니다."""
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a blogger specializing in Korean parenting and lifestyle. ENGLISH ONLY."},
                {"role": "user", "content": f"Post {post_number}: Write about a unique Korean parenting trend or must-have item. \nLine 1: Title: [Title]\nLine 2: Keywords: [6 specific baby gear or parenting keywords]\nBody: 6 sections. Place [IMAGE1] to [IMAGE6]."}
            ]
        )
        text = response.choices[0].message.content.strip()
        lines = text.split('\n')
        title = lines[0].replace("Title:", "").strip()
        keywords = lines[1].replace("Keywords:", "").split(",") if "Keywords:" in lines[1] else ["baby care"]
        
        # 주제에 맞는 육아 사진 6장 가져오기
        image_urls = get_unsplash_images(keywords, 6)
        content_body = "\n".join(lines[2:]).strip()

        for i, url in enumerate(image_urls):
            tag = f"[IMAGE{i+1}]"
            img_html = f'<div style="text-align:center; margin:35px 0;"><img src="{url}" style="width:100%; max-width:750px; border-radius:20px;"></div>'
            content_body = content_body.replace(tag, img_html) if tag in content_body else content_body + "<br>" + img_html

        return title, content_body.replace("\n", "<br>")
    except Exception as e:
        return "Error", str(e)

def post_to_wordpress(title, content, is_first):
    """첫 포스팅은 발행, 이후는 임시 저장"""
    status = "publish" if is_first else "draft"
    payload = {"title": title, "content": content, "status": status}
    requests.post(WP_URL, auth=HTTPBasicAuth(WP_USER, WP_PASS), json=payload)

if __name__ == "__main__":
    num_posts = random.randint(2, 3) # 2~3개 생성
    for i in range(num_posts):
        is_first = (i == 0) # 첫 글만 발행
        title, content = get_blog_content(i + 1)
        post_to_wordpress(title, content, is_first)
        time.sleep(10)
