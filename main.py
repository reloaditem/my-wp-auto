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

# 5대 대주제 설정
TOPICS = [
    {"subject": "Innovative Tech & AI Gadgets", "persona": "a tech reviewer"},
    {"subject": "Pro Camping & Family Adventure", "persona": "an outdoor expert"},
    {"subject": "Hidden Family Travel Gems", "persona": "a travel journalist"},
    {"subject": "Advanced Parenting Science", "persona": "a developmental specialist"},
    {"subject": "Biohacking & Family Longevity", "persona": "a wellness coach"}
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
    
    for query in keywords[:5]:
        found = False
        try:
            url = f"https://api.unsplash.com/search/photos?query={query.strip()}&client_id={UNSPLASH_KEY}&per_page=15&page={random.randint(1, 50)}"
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
            random_seed = random.randint(1, 100000)
            image_urls.append(f"https://images.unsplash.com/photo-{random_seed}?auto=format&fit=crop&w=800&q=60")
    return image_urls

def get_blog_content():
    selected = random.choice(TOPICS)
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": f"You are {selected['persona']}. Use <h2> for subheadings. NO ** symbols."},
                {"role": "user", "content": f"Write about {selected['subject']}. Title: [Title], Keywords: [5 keywords], Body: [IMAGE1]...[IMAGE5]"}
            ]
        )
        text = response.choices[0].message.content.strip()
        lines = text.split('\n')

        title = "Expert Insights"
        keywords = ["gear"]
        for line in lines:
            if "Title:" in line: title = line.replace("Title:", "").strip()
            if "Keywords:" in line: keywords = [k.strip() for k in line.replace("Keywords:", "").split(',') if k.strip()]

        final_images = get_unique_images(keywords)
        content_parts = []

        for line in lines:
            if any(x in line for x in ["Title:", "Keywords:"]): continue
            clean_line = line.replace("**", "").replace("#", "").strip()
            if not clean_line: continue
            
            if (len(clean_line) < 65 and (clean_line[0].isdigit() or clean_line.endswith(':'))):
                pure_text = clean_line.strip("1234567890. :")
                content_parts.append(f'<h2 style="color: #1a2a6c; margin-top: 40px; border-left: 10px solid #f2a365; padding-left: 15px; font-weight: bold;">{pure_text}</h2>')
            else:
                content_parts.append(f'<p style="line-height: 1.8; margin-bottom: 25px; font-size: 1.1em;">{clean_line}</p>')

        content_body = "".join(content_parts)
        for i in range(len(final_images)):
            img_html = f'<div style="text-align:center; margin:40px 0;"><img src="{final_images[i]}" style="width:100%; max-width:850px; border-radius:15px; box-shadow: 0 10px 20px rgba(0,0,0,0.15);"></div>'
            content_body = content_body.replace(f"[IMAGE{i+1}]", img_html)

        return title, content_body
    except: return None, None

if __name__ == "__main__":
    for i in range(2):
        t, c = get_blog_content()
        if t and c:
            # --- status를 'publish'로 변경하여 즉시 발행 ---
            requests.post(WP_URL, auth=HTTPBasicAuth(WP_USER, WP_PASS), json={"title": t, "content": c, "status": "publish"})
        time.sleep(15)
    
    if os.path.exists(USED_IDS_FILE):
        os.remove(USED_IDS_FILE)
