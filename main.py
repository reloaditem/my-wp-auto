import os
import requests
from requests.auth import HTTPBasicAuth
from openai import OpenAI
import random
import time
import string

# 환경 변수 로드
OPENAI_KEY = os.environ.get('OPENAI_API_KEY')
UNSPLASH_KEY = os.environ.get('UNSPLASH_ACCESS_KEY')
WP_USER = os.environ.get('WP_USER')
WP_PASS = os.environ.get('WP_PASS')
WP_URL = "https://reloaditem.com/wp-json/wp/v2/posts"

client = OpenAI(api_key=OPENAI_KEY)

def get_unsplash_images(queries, num_images=5):
    """검색 결과의 깊은 곳까지 뒤져서 중복을 원천 차단합니다."""
    if not UNSPLASH_KEY: return []
    image_urls = []
    used_ids = set()
    
    # 검색 결과에 변화를 줄 무작위 스타일 키워드
    styles = ["minimal", "modern", "lifestyle", "aesthetic", "soft", "high quality", "detail", "indoor", "outdoor"]

    for query in queries:
        # 1. 검색어 변조: 원본 키워드 + 랜덤 스타일 조합으로 검색 결과 리스트를 뒤섞음
        style_suffix = random.choice(styles)
        search_query = f"{query.strip()} {style_suffix}"
        
        # 2. 깊은 페이지 탐색: 1~100페이지 사이를 무작위로 점프
        random_page = random.randint(1, 100)
        
        try:
            url = f"https://api.unsplash.com/search/photos?query={search_query}&client_id={UNSPLASH_KEY}&per_page=30&page={random_page}"
            res = requests.get(url, timeout=10).json()
            
            if res.get('results'):
                # 3. 가져온 30장의 사진 중에서도 무작위로 하나를 선택
                random.shuffle(res['results'])
                for photo in res['results']:
                    if photo['id'] not in used_ids:
                        image_urls.append(photo['urls']['regular'])
                        used_ids.add(photo['id'])
                        break
        except:
            continue
        
        if len(image_urls) >= num_images:
            break

    # 사진이 부족할 경우 대비 (완전 무작위 육아 관련 검색)
    while len(image_urls) < num_images:
        backup_q = f"baby care {random.choice(styles)}"
        try:
            url = f"https://api.unsplash.com/search/photos?query={backup_q}&client_id={UNSPLASH_KEY}&per_page=30&page={random.randint(1, 150)}"
            res = requests.get(url, timeout=10).json()
            if res.get('results'):
                img = random.choice(res['results'])
                if img['id'] not in used_ids:
                    image_urls.append(img['urls']['regular'])
                    used_ids.add(img['id'])
        except: break
            
    return image_urls[:num_images]

def get_blog_content(post_number):
    """한국 육아 장비 주제로 글을 쓰고, 장비명으로 사진을 찾습니다."""
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a professional blogger specializing in Korean parenting gear. Write in ENGLISH."},
                {"role": "user", "content": f"Post {post_number}: Write about a popular Korean parenting gear. \nTitle: [Title]\nKeywords: [5 specific English names of the baby gear components for image search]\nBody: 5 detailed sections. Use [IMAGE1] to [IMAGE5]."}
            ]
        )
        lines = response.choices[0].message.content.strip().split('\n')
        title = lines[0].replace("Title:", "").replace("**", "").strip()
        
        # 장비명 위주의 키워드 추출
        keywords_str = lines[1].replace("Keywords:", "").strip()
        keywords = [k.strip() for k in keywords_str.split(',') if k.strip()]
        
        # 중복 방지 강화된 로직으로 사진 5장 가져오기
        image_urls = get_unsplash_images(keywords, 5)
        content_body = "\n".join(lines[2:]).strip()

        for i in range(5):
            tag = f"[IMAGE{i+1}]"
            img_url = image_urls[i] if i < len(image_urls) else "https://images.unsplash.com/photo-1555252333-9f8e92e65df9"
            img_html = f'<div style="text-align:center; margin:45px 0;"><img src="{img_url}" style="width:100%; max-width:750px; border-radius:20px; box-shadow: 0 10px 30px rgba(0,0,0,0.1);"></div>'
            
            if tag in content_body:
                content_body = content_body.replace(tag, img_html)
            else:
                content_body += "<br>" + img_html

        return title, content_body.replace("\n", "<br>")
    except Exception as e:
        return "Error", str(e)

def post_to_wordpress(title, content):
    # 모두 임시 저장(draft)으로 전송
    payload = {"title": title, "content": content, "status": "draft"}
    res = requests.post(WP_URL, auth=HTTPBasicAuth(WP_USER, WP_PASS), json=payload)
    print(f"✅ [임시저장 완료] 중복방지 필터 적용: {title}")

if __name__ == "__main__":
    num = random.randint(2, 3)
    for i in range(num):
        t, c = get_blog_content(i + 1)
        post_to_wordpress(t, c)
        time.sleep(15) # 전송 안정성 확보
