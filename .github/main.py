import os
import requests
from requests.auth import HTTPBasicAuth
from openai import OpenAI
import random
import time

# 환경 변수 및 설정
OPENAI_KEY = os.environ.get('OPENAI_API_KEY')
UNSPLASH_KEY = os.environ.get('UNSPLASH_ACCESS_KEY')
WP_USER = os.environ.get('WP_USER')
WP_PASS = os.environ.get('WP_PASS')
WP_URL = "https://reloaditem.com/wp-json/wp/v2/posts/"
USED_IDS_FILE = "used_photo_ids.txt"

client = OpenAI(api_key=OPENAI_KEY)

# 보내주신 카테고리 ID 매핑 (정확히 반영 완료)
CATEGORY_MAP = {
    "Innovative Tech & AI Gadgets": 1,      # 기술 (ID: 1)
    "Pro Camping & Family Adventure": 11,   # 캠핑 (ID: 11)
    "Hidden Family Travel Gems": 4,         # 여행 (ID: 4)
    "Advanced Parenting Science": 3,        # 육아 (ID: 3)
    "Biohacking & Family Longevity": 2      # 건강 (ID: 2)
}

# 대주제 리스트 생성
TOPICS = list(CATEGORY_MAP.keys())

def load_used_ids():
    if os.path.exists(USED_IDS_FILE):
        with open(USED_IDS_FILE, "r") as f:
            return set(f.read().splitlines())
    return set()

def save_used_id(photo_id):
    with open(USED_IDS_FILE, "a") as f:
        f.write(photo_id + "\n")

def get_unique_images(keywords):
    image_urls = []
    already_used = load_used_ids()
    current_post_ids = set()
    styles = ["lifestyle", "modern", "high-resolution", "clean", "cinematic"]

    for query in keywords[:5]:
        found = False
        try:
            # 다양성을 위해 1~80페이지 무작위 검색
            url = f"https://api.unsplash.com/search/photos?query={query.strip()}&client_id={UNSPLASH_KEY}&per_page=15&page={random.randint(1, 80)}"
            res = requests.get(url, timeout=10).json()
            if res.get('results'):
                results = res['results']
                random.shuffle(results)
                for photo in results:
                    p_id = photo['id']
                    if p_id not in already_used and p_id not in current_post_ids:
                        image_urls.append(photo['urls']['regular'])
                        current_post_ids.add(p_id)
                        save_used_id(p_id)
                        found = True
                        break
        except: pass
        
        if not found:
            # 검색 실패 시 대체 이미지 (고유 시드값 부여)
            random_seed = random.randint(1, 1000000)
            image_urls.append(f"https://images.unsplash.com/photo-{random_seed}?auto=format&fit=crop&w=800&q=60")
    return image_urls

def get_blog_content():
    # 주제와 카테고리 ID 결정
    selected_subject = random.choice(TOPICS)
    cat_id = CATEGORY_MAP[selected_subject]
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": f"You are a professional blogger specializing in {selected_subject}. Write in ENGLISH. Use <h2> for subheadings. NO ** or # symbols."},
                {"role": "user", "content": f"Write a 5-section blog about {selected_subject}. \nTitle: [Title]\nKeywords: [5 visual keywords for Unsplash]\nBody: Use [IMAGE1] to [IMAGE5] naturally."}
            ]
        )
        text = response.choices[0].message.content.strip()
        lines = text.split('\n')

        title = "Expert Review"
        keywords = ["lifestyle"]
        for line in lines:
            if "Title:" in line: title = line.replace("Title:", "").replace("**", "").replace("#", "").strip()
            if "Keywords:" in line: keywords = [k.strip() for k in line.replace("Keywords:", "").split(',') if k.strip()]

        final_images = get_unique_images(keywords)
        content_parts = []

        for line in lines:
            if any(x in line for x in ["Title:", "Keywords:"]): continue
            clean_line = line.replace("**", "").replace("#", "").strip()
            if not clean_line: continue
            
            # 소제목 자동 인식 및 스타일링 (파란 선 포인트)
            if (len(clean_line) < 65 and (clean_line[0].isdigit() or clean_line.endswith(':'))):
                pure_text = clean_line.strip("1234567890. :")
                content_parts.append(f'<h2 style="color: #1a2a6c; margin-top: 45px; border-left: 10px solid #f2a365; padding-left: 15px; font-weight: bold; line-height: 1.2;">{pure_text}</h2>')
            else:
                content_parts.append(f'<p style="line-height: 2.0; margin-bottom: 25px; font-size: 1.15em; color: #333;">{clean_line}</p>')

        content_body = "".join(content_parts)
        for i in range(len(final_images)):
            img_html = f'<div style="text-align:center; margin:45px 0;"><img src="{final_images[i]}" style="width:100%; max-width:850px; border-radius:15px; box-shadow: 0 10px 25px rgba(0,0,0,0.15);"></div>'
            content_body = content_body.replace(f"[IMAGE{i+1}]", img_html)

        return title, content_body, cat_id
    except: return None, None, None

if __name__ == "__main__":
    # 한 번에 2개씩 발행
    for i in range(2):
        t, c, cid = get_blog_content()
        if t and c:
            payload = {
                "title": t, 
                "content": c, 
                "status": "publish",
                "categories": [cid] # 지정된 카테고리로 쏙!
            }
            res = requests.post(WP_URL, auth=HTTPBasicAuth(WP_USER, WP_PASS), json=payload)
            if res.status_code == 201:
                print(f"✅ 발행 성공: {t} (Category ID: {cid})")
        time.sleep(20)
    
    # 마지막에 장바구니 비우기
    if os.path.exists(USED_IDS_FILE):
        os.remove(USED_IDS_FILE)
