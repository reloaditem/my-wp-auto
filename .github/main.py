import os
import requests
from requests.auth import HTTPBasicAuth
from openai import OpenAI
import random
import time

# 환경 변수
OPENAI_KEY = os.environ.get('OPENAI_API_KEY')
UNSPLASH_KEY = os.environ.get('UNSPLASH_ACCESS_KEY')
WP_USER = os.environ.get('WP_USER')
WP_PASS = os.environ.get('WP_PASS')
WP_URL = "https://reloaditem.com/wp-json/wp/v2/posts/"
USED_IDS_FILE = "used_photo_ids.txt"

client = OpenAI(api_key=OPENAI_KEY)

# 확장된 5대 카테고리
TOPICS = [
    {"subject": "Innovative Parenting Gear", "persona": "a tech-savvy parenting expert"},
    {"subject": "Family Camping Tips & Gear", "persona": "a professional camping enthusiast"},
    {"subject": "Global Family Travel Destinations", "persona": "a world-traveling family blogger"},
    {"subject": "Latest Consumer Technology & Gadgets", "persona": "a tech reviewer"},
    {"subject": "Holistic Health & Wellness for Families", "persona": "a health and nutrition consultant"}
]

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
    # 사진의 분위기를 살려줄 스타일 키워드
    styles = ["lifestyle", "cinematic", "high-resolution", "clean", "modern"]

    for query in keywords[:5]:
        found = False
        for attempt in range(5):
            if found: break
            # 키워드 조합을 무작위화하여 결과 다변화
            search_query = f"{query.strip()} {random.choice(styles)}"
            random_page = random.randint(1, 80)
            
            try:
                url = f"https://api.unsplash.com/search/photos?query={search_query}&client_id={UNSPLASH_KEY}&per_page=20&page={random_page}"
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
            except: continue
            
        if not found:
            image_urls.append(f"https://images.unsplash.com/photo-1493246507139-91e8bef99c02?auto=format&fit=crop&w=800&q=80")

    return image_urls

def get_blog_content(post_number):
    # 5가지 대주제 중 무작위 선택
    selected = random.choice(TOPICS)
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": f"You are {selected['persona']}. Write in ENGLISH. Use <h3> for subheadings. NO ** or # symbols."},
                {"role": "user", "content": f"Topic: {selected['subject']}. Write a 5-section blog post. \n1. Title: Catchy and professional. \n2. Keywords: 5 DIFFERENT specific English visual keywords for Unsplash photos. \n3. Body: Place [IMAGE1] to [IMAGE5] at the end of each section."}
            ]
        )
        text = response.choices[0].message.content.strip()
        lines = text.split('\n')

        title = f"{selected['subject']} Insights"
        keywords = ["technology", "nature", "health", "family"]
        
        for line in lines:
            if "Title:" in line: title = line.replace("Title:", "").strip()
            if "Keywords:" in line:
                keywords = [k.strip() for k in line.replace("Keywords:", "").split(',') if k.strip()]

        final_images = get_unique_images(keywords)

        content_parts = []
        for line in lines:
            if any(x in line for x in ["Title:", "Keywords:"]): continue
            clean_line = line.replace("**", "").replace("#", "").strip()
            if not clean_line: continue
            
            # 디자인: 시원시원한 소제목 스타일
            if clean_line.startswith('<h3') or clean_line.endswith(':') or (len(clean_line) < 65 and clean_line[0].isdigit()):
                pure_text = clean_line.replace("<h3>","").replace("</h3>","").replace(":","")
                content_parts.append(f'<h3 style="color: #1a2a6c; margin-top: 45px; margin-bottom: 20px; font-size: 1.7em; border-left: 8px solid #f2a365; padding-left: 15px; font-weight: bold; line-height: 1.3;">{pure_text}</h3>')
            else:
                content_parts.append(f'<p style="line-height: 1.9; margin-bottom: 25px; font-size: 1.15em; color: #2c3e50;">{clean_line}</p>')

        content_body = "".join(content_parts)
        for i in range(len(final_images)):
            img_html = f'<div style="text-align:center; margin:50px 0;"><img src="{final_images[i]}" style="width:100%; max-width:850px; border-radius:20px; box-shadow: 0 15px 35px rgba(0,0,0,0.2);"></div>'
            content_body = content_body.replace(f"[IMAGE{i+1}]", img_html)

        return title, content_body
    except Exception as e:
        print(f"Error: {e}")
        return None, None

def post_to_wordpress(title, content):
    if not title or not content: return
    # 상태를 'publish'로 바꾸면 바로 발행됩니다. 확인용이라면 'draft' 유지하세요.
    payload = {"title": title, "content": content, "status": "draft"}
    res = requests.post(WP_URL, auth=HTTPBasicAuth(WP_USER, WP_PASS), json=payload)
    if res.status_code == 201:
        print(f"✅ 포스팅 발행 완료: {title}")

if __name__ == "__main__":
    # 한 번 실행 시 2개의 글 생성
    for i in range(2):
        t, c = get_blog_content(i + 1)
        post_to_wordpress(t, c)
        time.sleep(20)
