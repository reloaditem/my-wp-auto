import os
import requests
from requests.auth import HTTPBasicAuth
from openai import OpenAI
import random

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

def get_unique_images(topic):
    image_urls = []
    for i in range(5):
        try:
            url = f"https://api.unsplash.com/search/photos?query={topic}&client_id={UNSPLASH_KEY}&per_page=10"
            res = requests.get(url, timeout=10)
            if res.status_code == 200:
                results = res.json().get('results')
                if results:
                    image_urls.append(random.choice(results)['urls']['regular'])
                    continue
        except: pass
        image_urls.append(f"https://picsum.photos/seed/{random.randint(1,9999)}/800/600")
    return image_urls

def post_one_blog():
    topic = random.choice(list(CATEGORY_MAP.keys()))
    cat_id = CATEGORY_MAP[topic]
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a professional blogger. Write in HTML. Subheadings <h2> must have style 'border-left:10px solid #f2a365; padding-left:15px; color:#1a2a6c;'. Use [IMAGE1] to [IMAGE5] placeholders."},
                {"role": "user", "content": f"Write a long blog post about {topic}. Start with 'Title: [Your Title]'."}
            ]
        )
        full_text = response.choices[0].message.content.strip()
        title = full_text.split('\n')[0].replace('Title:', '').strip()
        content_body = full_text.split('\n', 1)[1].strip()

        images = get_unique_images(topic)
        for i, img_url in enumerate(images):
            tag = f'<figure style="margin:40px 0; text-align:center;"><img src="{img_url}" style="width:100%; border-radius:15px; box-shadow:0 8px 16px rgba(0,0,0,0.1);"></figure>'
            placeholder = f"[IMAGE{i+1}]"
            if placeholder in content_body:
                content_body = content_body.replace(placeholder, tag)
            else:
                content_body += f"\n\n{tag}"

        payload = {"title": title, "content": content_body, "status": "publish", "categories": [cat_id]}
        res = requests.post(WP_URL, auth=HTTPBasicAuth(WP_USER, WP_PASS), json=payload)
        print(f"Post Success: {title} (Status: {res.status_code})")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    post_one_blog()
