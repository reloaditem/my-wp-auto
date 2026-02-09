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
    for i in range(3):
        try:
            url = f"https://api.unsplash.com/search/photos?query={topic}&client_id={UNSPLASH_KEY}&per_page=15"
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
    print(f"🚀 애드센스 최적화 주제: {topic}")
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system", 
                    "content": (
                        "You are an expert SEO content creator for Google AdSense approval. "
                        "Write a comprehensive, high-quality professional guide (at least 1,200 words). "
                        "Structure: 1. Catchy Intro, 2. Detailed Body with 4-5 Subheadings, 3. Practical Tips, 4. Conclusion. "
                        "Format: Use <h2> for subheadings with style 'border-left:10px solid #f2a365; padding-left:15px; color:#1a2a6c; margin-top:35px;'. "
                        "Use <p> tags with style 'line-height:1.8; margin-bottom:20px;'. "
                        "IMPORTANT: Naturally place [IMAGE1], [IMAGE2], [IMAGE3] between sections. "
                        "DO NOT use markdown blocks like ```html. Pure HTML only."
                    )
                },
                {"role": "user", "content": f"Write an ultimate guide about '{topic}'. Focus on E-E-A-T principles (Experience, Expertise, Authoritativeness, and Trustworthiness). Start with 'Title: [Your Title]'."}
            ]
        )
        full_text = response.choices[0].message.content.strip()
        
        # 마크다운 찌꺼기 제거
        clean_text = full_text.replace("```html", "").replace("```", "").replace("`", "")
        
        # 타이틀 분리
        if "Title:" in clean_text:
            parts = clean_text.split('\n', 1)
            title = parts[0].replace('Title:', '').strip()
            content_body = parts[1].strip() if len(parts) > 1 else clean_text
        else:
            title = f"The Ultimate Guide to {topic}"
            content_body = clean_text

        # 이미지 처리 및 강제 삽입 로직
        images = get_unique_images(topic)
        for i, img_url in enumerate(images):
            tag = f'<figure style="margin:45px 0; text-align:center;"><img src="{img_url}" style="width:100%; border-radius:15px; box-shadow:0 10px 20px rgba(0,0,0,0.15);"><figcaption style="color:#888; font-size:0.9em; margin-top:10px;">Visualizing {topic}</figcaption></figure>'
            placeholder = f"[IMAGE{i+1}]"
            
            if placeholder in content_body:
                content_body = content_body.replace(placeholder, tag)
            else:
                content_body += f"\n\n{tag}"

        payload = {
            "title": title, 
            "content": content_body, 
            "status": "publish", 
            "categories": [cat_id]
        }
        
        res = requests.post(WP_URL, auth=HTTPBasicAuth(WP_USER, WP_PASS), json=payload)
        print(f"✅ 승인용 포스팅 성공: {title} ({res.status_code})")
        
    except Exception as e:
        print(f"❌ 오류 발생: {e}")

if __name__ == "__main__":
    post_one_blog()
