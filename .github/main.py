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
# 끝에 슬래시(/)를 붙여 경로 오류를 원천 차단합니다.
WP_URL = "https://reloaditem.com/wp-json/wp/v2/posts/"

client = OpenAI(api_key=OPENAI_KEY)

def get_5_different_images(keywords):
    """키워드별로 다른 사진 5장을 확실히 가져옵니다."""
    image_urls = []
    used_ids = set()
    default_img = "https://images.unsplash.com/photo-1555252333-9f8e92e65df9"

    for query in keywords[:5]:
        try:
            # 매번 다른 결과를 위해 랜덤 페이지 탐색
            url = f"https://api.unsplash.com/search/photos?query={query.strip()}&client_id={UNSPLASH_KEY}&per_page=15&page={random.randint(1, 50)}"
            res = requests.get(url, timeout=10).json()
            
            found = False
            if res.get('results'):
                random.shuffle(res['results'])
                for photo in res['results']:
                    if photo['id'] not in used_ids:
                        image_urls.append(photo['urls']['regular'])
                        used_ids.add(photo['id'])
                        found = True
                        break
            if not found: image_urls.append(default_img)
        except:
            image_urls.append(default_img)
    
    while len(image_urls) < 5:
        image_urls.append(default_img)
    return image_urls

def get_blog_content(post_number):
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a professional blogger. Write in ENGLISH. Use <h3> for headings. Do NOT use ** or #."},
                {"role": "user", "content": f"Post {post_number}: Write a detailed review of Korean parenting gear. \n- Title: [Title]\n- Keywords: [5 English search keywords]\n- Body: 5 sections with <h3> tags. Place [IMAGE1] to [IMAGE5] naturally."}
            ]
        )
        text = response.choices[0].message.content.strip()
        lines = text.split('\n')

        # 제목 및 키워드 추출
        title = "Korean Parenting Gear Review"
        keywords = ["baby care"]
        for line in lines:
            if "Title:" in line: title = line.replace("Title:", "").replace("**", "").replace("#", "").strip()
            if "Keywords:" in line: keywords = [k.strip() for k in line.replace("Keywords:", "").split(',') if k.strip()]

        final_images = get_5_different_images(keywords)

        # 본문 가공 (소제목 디자인 입히기)
        content_parts = []
        for line in lines:
            if any(x in line for x in ["Title:", "Keywords:"]): continue
            
            clean_line = line.replace("**", "").replace("#", "").strip()
            if not clean_line: continue
            
            # 소제목을 <h3> 태그와 스타일로 크게 만듭니다 (앞뒤 ** 제거)
            if clean_line.startswith('<h3') or clean_line.endswith(':') or (len(clean_line) < 60 and clean_line[0].isdigit()):
                clean_title = clean_line.replace("<h3>","").replace("</h3>","").replace(":","")
                content_parts.append(f'<h3 style="color: #2c3e50; margin-top: 40px; margin-bottom: 20px; font-size: 1.6em; border-left: 6px solid #3498db; padding-left: 15px; font-weight: bold;">{clean_title}</h3>')
            else:
                content_parts.append(f'<p style="line-height: 1.9; margin-bottom: 25px; font-size: 1.1em; color: #333;">{clean_line}</p>')

        content_body = "".join(content_parts)

        # 이미지 교체 (그림자 효과 추가)
        for i in range(5):
            img_tag = f'<div style="text-align:center; margin:40px 0;"><img src="{final_images[i]}" style="width:100%; max-width:750px; border-radius:15px; box-shadow: 0 10px 30px rgba(0,0,0,0.15);"></div>'
            content_body = content_body.replace(f"[IMAGE{i+1}]", img_tag)

        return title, content_body
    except Exception as e:
        print(f"❌ 생성 오류: {e}")
        return None, None

def post_to_wordpress(title, content):
    if not title or not content: return
    payload = {"title": title, "content": content, "status": "draft"}
    
    try:
        res = requests.post(WP_URL, auth=HTTPBasicAuth(WP_USER, WP_PASS), json=payload, timeout=30)
        if res.status_code == 201:
            print(f"✅ 포스팅 성공: {title}")
        else:
            print(f"❌ 오류 코드 {res.status_code}: {res.text}")
    except Exception as e:
        print(f"🔥 네트워크 에러: {e}")

if __name__ == "__main__":
    # 한 번 실행에 2~3개의 글을 생성
    for i in range(random.randint(2, 3)):
        t, c = get_blog_content(i + 1)
        post_to_wordpress(t, c)
        time.sleep(15)
