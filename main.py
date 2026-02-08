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

def generate_dalle_image(prompt):
    """DALL-E 3를 사용하여 고유한 메인 이미지를 생성합니다."""
    try:
        print(f"🎨 AI 이미지 생성 중: {prompt}")
        response = client.images.generate(
            model="dall-e-3",
            prompt=f"A high-quality, realistic lifestyle photo of {prompt}. Korean setting, warm lighting, 4k resolution, professional photography.",
            size="1024x1024",
            quality="standard",
            n=1,
        )
        return response.data[0].url
    except Exception as e:
        print(f"❌ DALL-E 생성 실패: {e}")
        return None

def get_unsplash_images(queries, num_images=5):
    """랜덤 페이지에서 중복 없이 Unsplash 이미지를 가져옵니다."""
    if not UNSPLASH_KEY: return []
    image_urls = []
    for query in queries:
        random_page = random.randint(1, 10)
        try:
            url = f"https://api.unsplash.com/search/photos?query=Korean {query.strip()}&client_id={UNSPLASH_KEY}&per_page=10&page={random_page}"
            res = requests.get(url, timeout=10).json()
            if res.get('results'):
                image_urls.append(random.choice(res['results'])['urls']['regular'])
        except: continue
        if len(image_urls) >= num_images: break
    return image_urls

def get_blog_content(post_number):
    try:
        # 지피티에게 글과 이미지 생성용 프롬프트를 요청
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a professional Korean parenting blogger. Write in ENGLISH."},
                {"role": "user", "content": f"Post {post_number}: Write about a unique Korean parenting item. \nLine 1: Title: [Title]\nLine 2: ImagePrompt: [Short English description for AI image generation]\nLine 3: Keywords: [5 keywords for search]\nBody: 5 sections. Place [IMAGE1] to [IMAGE5]."}
            ]
        )
        lines = response.choices[0].message.content.strip().split('\n')
        title = lines[0].replace("Title:", "").strip()
        img_prompt = lines[1].replace("ImagePrompt:", "").strip()
        keywords = lines[2].replace("Keywords:", "").split(",")

        # 1. 메인 이미지는 DALL-E로 생성 
        main_img_url = generate_dalle_image(img_prompt)
        
        # 2. 본문 이미지는 Unsplash 랜덤
        sub_img_urls = get_unsplash_images(keywords, 5)
        
        content_body = "\n".join(lines[3:]).strip()
        
        # 메인 이미지 맨 상단에 배치
        if main_img_url:
            content_body = f'<div style="text-align:center; margin-bottom:40px;"><img src="{main_img_url}" style="width:100%; border-radius:20px; border: 3px solid #f0f0f0;"></div>' + content_body

        # 본문 태그 교체
        for i, url in enumerate(sub_img_urls):
            tag = f"[IMAGE{i+1}]"
            img_html = f'<div style="text-align:center; margin:30px 0;"><img src="{url}" style="width:100%; max-width:700px; border-radius:15px;"></div>'
            content_body = content_body.replace(tag, img_html)

        return title, content_body.replace("\n", "<br>")
    except Exception as e:
        return "Error", str(e)

def post_to_wordpress(title, content, is_first):
    status = "publish" if is_first else "draft"
    payload = {"title": title, "content": content, "status": status}
    res = requests.post(WP_URL, auth=HTTPBasicAuth(WP_USER, WP_PASS), json=payload)
    print(f"🚀 [{status}] 완료: {title} ({res.status_code})")

if __name__ == "__main__":
    num = random.randint(2, 3)
    for i in range(num):
        t, c = get_blog_content(i + 1)
        post_to_wordpress(t, c, (i == 0))
        time.sleep(15)
