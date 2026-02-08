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

def get_5_unique_images(keywords):
    """한 포스팅 내에서 절대 중복되지 않는 5장의 사진을 가져옵니다."""
    image_urls = []
    session_used_ids = set() # 이번 포스팅에서 사용된 사진 ID 저장소
    default_img = "https://images.unsplash.com/photo-1555252333-9f8e92e65df9"
    
    # 5개의 키워드를 순회
    for query in keywords[:5]:
        try:
            # 1~100페이지 중 무작위 페이지 선택 (검색 결과의 다양성 확보)
            random_page = random.randint(1, 100)
            url = f"https://api.unsplash.com/search/photos?query={query.strip()}&client_id={UNSPLASH_KEY}&per_page=30&page={random_page}"
            res = requests.get(url, timeout=10).json()
            
            if res.get('results'):
                # 결과 30장을 무작위로 섞음
                results = res['results']
                random.shuffle(results)
                
                found = False
                for photo in results:
                    p_id = photo['id']
                    # 이미 이번 포스팅에서 뽑힌 ID가 아닌 경우만 선택
                    if p_id not in session_used_ids:
                        image_urls.append(photo['urls']['regular'])
                        session_used_ids.add(p_id)
                        found = True
                        break
                
                if not found: # 30장 모두 중복이라면(드문 경우) 첫 번째 사진 사용
                    image_urls.append(results[0]['urls']['regular'])
            else:
                image_urls.append(default_img)
        except:
            image_urls.append(default_img)
            
    # 혹시라도 5장이 안 채워졌을 경우 대비
    while len(image_urls) < 5:
        image_urls.append(default_img)
        
    return image_urls

def get_blog_content(post_number):
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a professional blogger. Write in ENGLISH. Use <h3> for subheadings. NO ** or #."},
                {"role": "user", "content": f"Post {post_number}: Write about a Korean parenting gear. \nTitle: [Title]\nKeywords: [5 different English keywords for images]\nBody: 5 sections. Place [IMAGE1] to [IMAGE5]."}
            ]
        )
        text = response.choices[0].message.content.strip()
        lines = text.split('\n')

        title = "Parenting Gear Review"
        keywords = ["baby product"]
        for line in lines:
            if "Title:" in line: title = line.replace("Title:", "").replace("**", "").replace("#", "").strip()
            if "Keywords:" in line: keywords = [k.strip() for k in line.replace("Keywords:", "").split(',') if k.strip()]

        # 중복 방지 로직이 적용된 사진 가져오기
        final_images = get_5_unique_images(keywords)

        content_parts = []
        for line in lines:
            if any(x in line for x in ["Title:", "Keywords:"]): continue
            clean_line = line.replace("**", "").replace("#", "").strip()
            if not clean_line: continue
            
            # 소제목 가독성 스타일 (크게, 파란 선)
            if clean_line.startswith('<h3') or clean_line.endswith(':') or (len(clean_line) < 50 and clean_line[0].isdigit()):
                pure_text = clean_line.replace("<h3>","").replace("</h3>","").replace(":","")
                content_parts.append(f'<h3 style="color: #2c3e50; margin-top: 40px; margin-bottom: 20px; font-size: 1.6em; border-left: 6px solid #3498db; padding-left: 15px; font-weight: bold;">{pure_text}</h3>')
            else:
                content_parts.append(f'<p style="line-height: 1.8; margin-bottom: 20px; font-size: 1.1em;">{clean_line}</p>')

        content_body = "".join(content_parts)
        for i in range(5):
            img_html = f'<div style="text-align:center; margin:35px 0;"><img src="{final_images[i]}" style="width:100%; max-width:750px; border-radius:12px; box-shadow: 0 10px 20px rgba(0,0,0,0.1);"></div>'
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
        print(f"✅ 포스팅 완료: {title}")

if __name__ == "__main__":
    for i in range(random.randint(2, 3)):
        t, c = get_blog_content(i + 1)
        post_to_wordpress(t, c)
        time.sleep(10)
