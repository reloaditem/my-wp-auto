import os
import requests
from requests.auth import HTTPBasicAuth
from openai import OpenAI
import random
import time

# 환경 변수 설정
OPENAI_KEY = os.environ.get('OPENAI_API_KEY')
UNSPLASH_KEY = os.environ.get('UNSPLASH_ACCESS_KEY')
WP_USER = os.environ.get('WP_USER')
WP_PASS = os.environ.get('WP_PASS')
WP_URL = "https://reloaditem.com/wp-json/wp/v2/posts"

client = OpenAI(api_key=OPENAI_KEY)

def get_unsplash_images(queries, num_images=5):
    """중복 방지 강화된 이미지 검색 로직"""
    if not UNSPLASH_KEY: return []
    image_urls = []
    used_ids = set()
    styles = ["minimal", "lifestyle", "modern", "aesthetic"]

    for query in queries:
        search_query = f"{query.strip()} {random.choice(styles)}"
        random_page = random.randint(1, 100)
        try:
            url = f"https://api.unsplash.com/search/photos?query={search_query}&client_id={UNSPLASH_KEY}&per_page=20&page={random_page}"
            res = requests.get(url, timeout=10).json()
            if res.get('results'):
                random.shuffle(res['results'])
                for photo in res['results']:
                    if photo['id'] not in used_ids:
                        image_urls.append(photo['urls']['regular'])
                        used_ids.add(photo['id'])
                        break
        except: continue
        if len(image_urls) >= num_images: break
    return image_urls

def get_blog_content(post_number):
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a professional blogger. Write in ENGLISH. Use clear headings for each section."},
                {"role": "user", "content": f"Post {post_number}: Write a detailed blog post about a Korean parenting gear. \n- Title: [Title]\n- Keywords: [5 English keywords for images]\n- Body: 5 sections with interesting subheadings. Use [IMAGE1] to [IMAGE5]."}
            ]
        )
        text = response.choices[0].message.content.strip()
        lines = text.split('\n')

        # 1. 제목 추출 및 정리
        title = lines[0].replace("Title:", "").replace("**", "").replace("#", "").strip()

        # 2. 키워드 추출 (검색용으로만 쓰고 본문에서는 제외)
        keywords = []
        for line in lines:
            if "Keywords:" in line:
                keywords = [k.strip() for k in line.replace("Keywords:", "").split(',') if k.strip()]
                break
        
        # 3. 사진 가져오기
        image_urls = get_unsplash_images(keywords, 5)

        # 4. 본문 가공 (소제목 크기 키우고 ** 제거)
        content_parts = []
        body_started = False
        
        for line in lines[2:]: # 제목과 키워드 줄 제외하고 시작
            clean_line = line.replace("**", "").replace("#", "").strip()
            if not clean_line: continue
            
            # 소제목(Heading)처럼 보이는 줄을 발견하면 <h3> 태그 입히기
            if any(clean_line.startswith(word) for word in ["Section", "1.", "2.", "3.", "4.", "5.", "Introduction", "Conclusion"]) or (len(clean_line) < 50 and clean_line.endswith(':')):
                content_parts.append(f'<h3 style="color: #2c3e50; margin-top: 40px; margin-bottom: 20px; font-size: 1.5em; border-left: 5px solid #3498db; padding-left: 15px;">{clean_line}</h3>')
            else:
                content_parts.append(f'<p style="line-height: 1.8; margin-bottom: 20px;">{clean_line}</p>')

        content_body = "".join(content_parts)

        # 5. 이미지 삽입
        for i in range(5):
            tag = f"[IMAGE{i+1}]"
            img_url = image_urls[i] if i < len(image_urls) else "https://images.unsplash.com/photo-1555252333-9f8e92e65df9"
            img_html = f'<div style="text-align:center; margin:40px 0;"><img src="{img_url}" style="width:100%; max-width:800px; border-radius:15px; box-shadow: 0 10px 25px rgba(0,0,0,0.1);"></div>'
            content_body = content_body.replace(tag, img_html) if tag in content_body else content_body + img_html

        return title, content_body
    except Exception as e:
        return "Error", str(e)

def post_to_wordpress(title, content):
    payload = {"title": title, "content": content, "status": "draft"}
    requests.post(WP_URL, auth=HTTPBasicAuth(WP_USER, WP_PASS), json=payload)
    print(f"✅ 가독성 강화 포스팅 임시저장 완료: {title}")

if __name__ == "__main__":
    num = random.randint(2, 3)
    for i in range(num):
        t, c = get_blog_content(i + 1)
        post_to_wordpress(t, c)
        time.sleep(15)
