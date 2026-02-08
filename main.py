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

def get_5_different_images(keywords):
    """한 포스팅에 들어갈 서로 다른 사진 5장을 확실히 가져옵니다."""
    if not UNSPLASH_KEY: return []
    
    all_collected_urls = []
    used_ids = set()
    
    # 지피티가 준 키워드 5개를 하나씩 돌며 사진을 찾습니다.
    for query in keywords:
        random_page = random.randint(1, 50)
        try:
            # 검색어마다 10개씩 결과를 가져와서 그 중 하나를 랜덤하게 픽!
            url = f"https://api.unsplash.com/search/photos?query={query.strip()}&client_id={UNSPLASH_KEY}&per_page=10&page={random_page}"
            res = requests.get(url, timeout=10).json()
            
            if res.get('results'):
                # 가져온 결과들을 무작위로 섞음
                random.shuffle(res['results'])
                for photo in res['results']:
                    if photo['id'] not in used_ids:
                        all_collected_urls.append(photo['urls']['regular'])
                        used_ids.add(photo['id'])
                        break # 한 키워드당 무조건 '새로운' 사진 1개만 확보하고 다음 키워드로
        except:
            continue

    # 만약 사진이 5장이 안 되면, 일반 육아 키워드로 부족한 만큼 채움
    backup_keywords = ["baby care", "nursery", "infant item", "toddler", "parenting lifestyle"]
    while len(all_collected_urls) < 5:
        bg_query = random.choice(backup_keywords)
        try:
            url = f"https://api.unsplash.com/search/photos?query={bg_query}&client_id={UNSPLASH_KEY}&per_page=20&page={random.randint(1, 100)}"
            res = requests.get(url, timeout=10).json()
            if res.get('results'):
                photo = random.choice(res['results'])
                if photo['id'] not in used_ids:
                    all_collected_urls.append(photo['urls']['regular'])
                    used_ids.add(photo['id'])
        except:
            all_collected_urls.append("https://images.unsplash.com/photo-1555252333-9f8e92e65df9")
            
    return all_collected_urls[:5] # 정확히 서로 다른 5장 반환

def get_blog_content(post_number):
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a professional blogger. Write in ENGLISH. Do not use ** symbols."},
                {"role": "user", "content": f"Post {post_number}: Write about a Korean parenting gear. \nTitle: [Title]\nKeywords: [5 different specific English keywords for baby gear]\nBody: 5 sections. Place [IMAGE1] to [IMAGE5] at the end of each section."}
            ]
        )
        lines = response.choices[0].message.content.strip().split('\n')
        title = lines[0].replace("Title:", "").strip()

        # 키워드 추출
        keywords = []
        for line in lines:
            if "Keywords:" in line:
                keywords = [k.strip() for k in line.replace("Keywords:", "").split(',') if k.strip()]
                break
        
        # 중요: 여기서 서로 다른 5장의 사진 리스트를 한꺼번에 받아옵니다.
        final_images = get_5_different_images(keywords)

        content_parts = []
        # 제목/키워드 줄 제외하고 본문 생성
        for line in lines[2:]:
            clean_line = line.replace("**", "").replace("#", "").strip()
            if not clean_line: continue
            
            # 소제목 가독성 처리
            if any(clean_line.startswith(str(i)) for i in range(1, 7)) or clean_line.endswith(':'):
                content_parts.append(f'<h3 style="color: #2c3e50; margin-top: 40px; font-size: 1.5em; border-left: 5px solid #3498db; padding-left: 15px;">{clean_line}</h3>')
            else:
                content_parts.append(f'<p style="line-height: 1.8; margin-bottom: 20px;">{clean_line}</p>')

        content_body = "".join(content_parts)

        # 본문 내 이미지 태그를 준비된 5장의 서로 다른 사진으로 교체
        for i in range(5):
            tag = f"[IMAGE{i+1}]"
            img_html = f'<div style="text-align:center; margin:40px 0;"><img src="{final_images[i]}" style="width:100%; max-width:800px; border-radius:15px; box-shadow: 0 8px 20px rgba(0,0,0,0.1);"></div>'
            content_body = content_body.replace(tag, img_html)

        return title, content_body
    except Exception as e:
        return "Error", str(e)

# (post_to_wordpress 함수 및 main 실행부는 이전과 동일)
