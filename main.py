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
    """장비 명칭(Gear Name)으로 글로벌 DB에서 사진을 가져와 중복을 방지합니다."""
    if not UNSPLASH_KEY: return []
    image_urls = []
    used_ids = set()
    
    for query in queries:
        # 사진 검색 시 'Korean'을 빼고 장비명으로만 검색하여 결과 다양화
        # 1~50페이지 사이 랜덤 점프
        random_page = random.randint(1, 50)
        try:
            url = f"https://api.unsplash.com/search/photos?query={query.strip()}&client_id={UNSPLASH_KEY}&per_page=15&page={random_page}"
            res = requests.get(url, timeout=10).json()
            
            if res.get('results'):
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

    # 부족할 경우 일반적인 육아 장비 키워드로 보충
    backups = ["stroller", "baby carrier", "baby bottle", "crib", "baby toy"]
    while len(image_urls) < num_images:
        try:
            url = f"https://api.unsplash.com/search/photos?query={random.choice(backups)}&client_id={UNSPLASH_KEY}&per_page=10&page={random.randint(1, 100)}"
            res = requests.get(url, timeout=10).json()
            img = random.choice(res['results'])
            if img['id'] not in used_ids:
                image_urls.append(img['urls']['regular'])
                used_ids.add(img['id'])
        except: break
            
    return image_urls[:num_images]

def get_blog_content(post_number):
    """글 주제는 한국 육아 장비, 사진은 장비명 위주로 추출"""
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an expert on Korean parenting gear (K-Baby goods). Write a detailed post in ENGLISH."},
                {"role": "user", "content": f"Post {post_number}: Write about a popular Korean parenting gear (e.g., specific brand or item type). \nTitle: [Title]\nKeywords: [5 specific English names of the baby gear mentioned in the post, for photo search]\nBody: 5 detailed sections. Use [IMAGE1] to [IMAGE5]."}
            ]
        )
        lines = response.choices[0].message.content.strip().split('\n')
        title = lines[0].replace("Title:", "").replace("**", "").strip()
        
        # 장비명 위주의 키워드 5개 (예: Stroller, Hipseat, Bouncer 등)
        keywords = lines[1].replace("Keywords:", "").split(",")
        
        image_urls = get_unsplash_images(keywords, 5)
        content_body = "\n".join(lines[2:]).strip()

        for i in range(5):
            tag = f"[IMAGE{i+1}]"
            img_url = image_urls[i] if i < len(image_urls) else "https://images.unsplash.com/photo-1555252333-9f8e92e65df9"
            img_html = f'<div style="text-align:center; margin:40px 0;"><img src="{img_url}" style="width:100%; border-radius:15px; box-shadow: 0 4px 15px rgba(0,0,0,0.1);"></div>'
            content_body = content_body.replace(tag, img_html) if tag in content_body else content_body + "<br>" + img_html

        return title, content_body.replace("\n", "<br>")
    except Exception as e:
        return "Error", str(e)

def post_to_wordpress(title, content):
    # 전체 포스팅 임시 저장(draft)
    payload = {"title": title, "content": content, "status": "draft"}
    requests.post(WP_URL, auth=HTTPBasicAuth(WP_USER, WP_PASS), json=payload)
    print(f"📦 [임시저장 완료] 주제: 한국 육아 장비 / 사진: 장비명 기반 - {title}")

if __name__ == "__main__":
    # 2~3개 포스팅 실행
    num = random.randint(2, 3)
    for i in range(num):
        t, c = get_blog_content(i + 1)
        post_to_wordpress(t, c)
        time.sleep(20)
