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

CATEGORY_MAP = {
    "Innovative Tech & AI Gadgets": 1,
    "Pro Camping & Family Adventure": 11,
    "Hidden Family Travel Gems": 4,
    "Advanced Parenting Science": 3,
    "Biohacking & Family Longevity": 2
}
TOPICS = list(CATEGORY_MAP.keys())

def get_unique_images(keywords):
    image_urls = []
    used_ids = set()
    for i in range(5):
        query = keywords[i] if i < len(keywords) else "lifestyle"
        found = False
        try:
            url = f"https://api.unsplash.com/search/photos?query={query.strip()}&client_id={UNSPLASH_KEY}&per_page=30&page={random.randint(1, 100)}"
            res = requests.get(url, timeout=10)
            if res.status_code == 200:
                results = res.json().get('results')
                if results:
                    photo = random.choice(results)
                    if photo['id'] not in used_ids:
                        image_urls.append(photo['urls']['regular'])
                        used_ids.add(photo['id'])
                        found = True
        except: pass
        if not found:
            image_urls.append(f"https://picsum.photos/seed/{random.randint(1, 9999)}/800/600")
    return image_urls

def get_blog_content():
    selected = random.choice(TOPICS)
    cat_id = CATEGORY_MAP[selected]
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": f"You are a pro blogger. Write about {selected}. Use <h2> for subheadings. NO ** symbols."},
                {"role": "user", "content": f"Write a 5-section blog. Title: [Title], Keywords: [5 keywords], Body: Use [IMAGE1] to [IMAGE5]."}
            ]
        )
        text = response.choices[0].message.content.strip()
        lines = text.split('\n')
        title = f"Latest on {selected}"
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
            
            # 소제목 인식 강화 (길이 기준 완화 및 조건 추가)
            is_heading = (len(clean_line) < 70) and (clean_line[0].isdigit() or clean_line.endswith(':') or clean_line.istitle())

            if is_heading:
                pure_text = clean_line.lstrip("0123456789. :").strip(" :")
                content_parts.append(f'<h2 style="color:#1a2a6c; margin:45px 0 20px 0; border-left:10px solid #f2a365; padding-left:15px; font-weight:bold; font-size:1.6em; line-height:1.3;">{pure_text}</h2>')
            else:
                content_parts.append(f'<p style="line-height:2.0; margin-bottom:25px; font-size:1.15em; color:#333;">{clean_line}</p>')

        content_body = "".join(content_parts)
        for i in range(len(final_images)):
            img_tag = f'<figure style="text-align:center; margin:40px 0;"><img src="{final_images[i]}" style="width:100%; border-radius:15px; box-shadow:0 10px 20px rgba(0,0,0,0.1);"></figure>'
            content_body = content_body.replace(f"[IMAGE{i+1}]", img_tag)
        return title, content_body, cat_id
    except: return None, None, None

if __name__ == "__main__":
    for i in range(2):
        t, c, cid = get_blog_content()
        if t and c:
            payload = {"title": t, "content": c, "status": "publish", "categories": [cid]}
            requests.post(WP_URL, auth=HTTPBasicAuth(WP_USER, WP_PASS), json=payload)
        time.sleep(20)
