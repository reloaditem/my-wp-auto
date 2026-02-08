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
    """중복 방지를 위해 랜덤하게 5장의 한국 관련 육아 사진을 가져옵니다."""
    if not UNSPLASH_KEY: return []
    image_urls = []
    
    for query in queries:
        random_page = random.randint(1, 15) # 검색 범위 확대
        try:
            # 주제와 한국 분위기 결합
            search_query = f"Korean {query.strip()}"
            url = f"https://api.unsplash.com/search/photos?query={search_query}&client_id={UNSPLASH_KEY}&per_page=10&page={random_page}"
            res = requests.get(url, timeout=10).json()
            
            if res.get('results'):
                # 검색 결과 중 랜덤 선택
                image_urls.append(random.choice(res['results'])['urls']['regular'])
        except:
            continue
        
        if len(image_urls) >= num_images:
            break

    # 사진이 부족할 경우 대비한 백업 사진들
    while len(image_urls) < num_images:
        image_urls.append("https://images.unsplash.com/photo-1517154421773-0529f29ea451?q=80&w=1000")
        
    return image_urls[:num_images] # 정확히 5개만 반환

def get_blog_content(post_number):
    """한국 육아 주제로 글을 생성하고 사진 5장을 배치합니다."""
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a professional Korean parenting blogger. Write in ENGLISH."},
                {"role": "user", "content": f"Post {post_number}: Write a long, detailed blog post about a unique Korean parenting trend or item. \nLine 1: Title: [Title]\nLine 2: Keywords: [5 descriptive keywords for photo search]\nBody: Write 5 sections. Place [IMAGE1], [IMAGE2], [IMAGE3], [IMAGE4], and [IMAGE5] at the end of each section."}
            ]
        )
        text = response.choices[0].message.content.strip()
        lines = text.split('\n')
        
        title = lines[0].replace("Title:", "").replace("**", "").strip()
        keywords = lines[1].replace("Keywords:", "").split(",") if "Keywords:" in lines[1] else ["baby", "korea"]
        
        # 사진 5장 가져오기
        image_urls = get_unsplash_images(keywords, 5)
        content_body = "\n".join(lines[2:]).strip()

        # 본문의 이미지 태그 5개를 HTML로 교체
        for i in range(5):
            tag = f"[IMAGE{i+1}]"
            img_url = image_urls[i] if i < len(image_urls) else image_urls[0]
            img_html = f'<div style="text-align:center; margin:35px 0;"><img src="{img_url}" style="width:100%; max-width:750px; border-radius:15px; box-shadow: 0 5px 15px rgba(0,0,0,0.1);"></div>'
            
            if tag in content_body:
                content_body = content_body.replace(tag, img_html)
            else:
                content_body += "<br>" + img_html

        return title, content_body.replace("\n", "<br>")
    except Exception as e:
        return "Content Error", str(e)

def post_to_wordpress(title, content):
    """모든 포스팅을 '임시 저장(draft)' 상태로 전송합니다."""
    # status를 'draft'로 고정하여 자동 발행 방지
    payload = {
        "title": title, 
        "content": content, 
        "status": "draft" 
    }
    res = requests.post(WP_URL, auth=HTTPBasicAuth(WP_USER, WP_PASS), json=payload)
    if res.status_code == 201:
        print(f"✅ 임시 저장 성공: {title}")
    else:
        print(f"❌ 실패 ({res.status_code}): {title}")

if __name__ == "__main__":
    # 한 번 실행 시 2~3개의 포스팅 생성
    num_posts = random.randint(2, 3)
    print(f"🚀 총 {num_posts}개의 포스팅을 임시 저장으로 생성합니다...")
    
    for i in range(num_posts):
        title, content = get_blog_content(i + 1)
        post_to_wordpress(title, content)
        time.sleep(15) # 안정적인 전송을 위한 간격
