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
WP_URL = "https://reloaditem.com/wp-json/wp/v2/posts/"

client = OpenAI(api_key=OPENAI_KEY)

def get_unique_images_by_keywords(keywords):
    """지정된 5개 키워드로 각각 다른 사진을 검색합니다."""
    image_urls = []
    used_ids = set()
    
    for query in keywords:
        try:
            # 검색어 다양성을 위해 스타일 키워드 추가
            enhanced_query = f"{query.strip()} lifestyle"
            url = f"https://api.unsplash.com/search/photos?query={enhanced_query}&client_id={UNSPLASH_KEY}&per_page=20&page={random.randint(1, 30)}"
            res = requests.get(url, timeout=10).json()
            
            if res.get('results'):
                random.shuffle(res['results'])
                for photo in res['results']:
                    if photo['id'] not in used_ids:
                        image_urls.append(photo['urls']['regular'])
                        used_ids.add(photo['id'])
                        break
        except: continue
    
    # 부족한 사진 채우기
    while len(image_urls) < 5:
        image_urls.append("https://images.unsplash.com/photo-1555252333-9f8e92e65df9")
    return image_urls[:5]

def get_blog_content(post_number):
    try:
        # 지피티에게 주제를 다양하게 잡으라고 페르소나 부여
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an expert parenting influencer. Write a high-quality blog post. Use <h3> for subheadings. NO ** or # symbols."},
                {"role": "user", "content": f"Post {post_number}: Pick ONE specific trendy Korean parenting item (e.g., a specific bouncer, high chair, or mat). \n1. Title: Catchy and SEO-friendly. \n2. Keywords: List 5 DIFFERENT visual keywords for Unsplash (e.g., 'minimalist nursery', 'wooden baby toy', 'happy mother and baby'). \n3. Body: 5 detailed sections. End each section with [IMAGE1] to [IMAGE5]."}
            ]
        )
        text = response.choices[0].message.content.strip()
        lines = text.split('\n')

        title = "Best Parenting Gear Review"
        keywords = []
        
        # 데이터 정제
        for line in lines:
            if "Title:" in line: title = line.replace("Title:", "").strip()
            if "Keywords:" in line:
                keywords = [k.strip() for k in line.replace("Keywords:", "").split(',') if k.strip()]

        # 사진 가져오기
        final_images = get_unique_images_by_keywords(keywords)

        content_parts = []
        for line in lines:
            if any(x in line for x in ["Title:", "Keywords:"]): continue
            clean_line = line.strip()
            if not clean_line: continue
            
            # 소제목 가독성 (크게, 파란 선, ** 제거)
            if clean_line.startswith('<h3') or clean_line.endswith(':') or (len(clean_line) < 60 and clean_line[0].isdigit()):
                pure_text = clean_line.replace("<h3>","").replace("</h3>","").replace(":","").replace("**", "")
                content_parts.append(f'<h3 style="color: #2c3e50; margin-top: 40px; margin-bottom: 20px; font-size: 1.65em; border-left: 6px solid #3498db; padding-left: 15px; font-weight: bold; line-height: 1.4;">{pure_text}</h3>')
            else:
                content_parts.append(f'<p style="line-height: 1.9; margin-bottom: 25px; font-size: 1.1em; color: #444;">{clean_line}</p>')

        content_body = "".join(content_parts)
        for i in range(5):
            img_html = f'<div style="text-align:center; margin:45px 0;"><img src="{final_images[i]}" style="width:100%; max-width:800px; border-radius:15px; box-shadow: 0 12px 24px rgba(0,0,0,0.15);"></div>'
            content_body = content_body.replace(f"[IMAGE{i+1}]", img_html)

        return title, content_body
    except Exception as e:
        print(f"Error: {e}")
        return None, None

def post_to_wordpress(title, content):
    if not title or not content: return
    payload = {"title": title, "content": content, "status": "draft"}
    res = requests.post(WP_URL, auth=HTTPBasicAuth(WP_USER, WP_PASS), json=payload)
    if res.status_code == 201:
        print(f"✅ 포스팅 성공: {title}")

if __name__ == "__main__":
    for i in range(2):
        t, c = get_blog_content(i + 1)
        post_to_wordpress(t, c)
        time.sleep(15)
