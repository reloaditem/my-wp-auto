import os
import requests
from requests.auth import HTTPBasicAuth
import google.generativeai as genai

# 환경 변수 로드
GEMINI_KEY = os.environ.get('GEMINI_API_KEY')
UNSPLASH_KEY = os.environ.get('UNSPLASH_ACCESS_KEY')
WP_USER = os.environ.get('WP_USER')
WP_PASS = os.environ.get('WP_PASS')
WP_URL = "https://reloaditem.com/wp-json/wp/v2/posts"

# Gemini 설정
genai.configure(api_key=GEMINI_KEY)

def get_unsplash_image(query):
    if not UNSPLASH_KEY:
        return None
    try:
        url = f"https://api.unsplash.com/search/photos?query={query}&client_id={UNSPLASH_KEY}&per_page=1"
        res = requests.get(url, timeout=10)
        data = res.json()
        if 'results' in data and len(data['results']) > 0:
            return data['results'][0]['urls']['regular']
        return None
    except:
        return None

def get_gemini_content():
    try:
        # 모델 설정 (가장 안정적인 기본 호출 방식)
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        # 영문 포스팅을 위한 명확한 지시
        prompt = """
        Write a professional blog post STRICTLY IN ENGLISH.
        Topic: "Smart Parenting: Essential Gadgets for Modern Dads"
        
        Format:
        1. Title: [Your English Title]
        2. SearchTerm: [English keyword for image]
        3. Body: Comprehensive blog content with emojis and subheadings in English.
        4. Place the tag [IMAGE] in the middle of the post.
        """
        
        response = model.generate_content(prompt)
        full_text = response.text.strip()
        
        lines = full_text.split('\n')
        title = lines[0].replace("Title:", "").replace("**", "").strip()
        
        search_query = "baby"
        if len(lines) > 1 and "SearchTerm:" in lines[1]:
            search_query = lines[1].replace("SearchTerm:", "").replace("**", "").strip()
            content_body = "\n".join(lines[2:]).strip()
        else:
            content_body = "\n".join(lines[1:]).strip()

        # 이미지 처리
        image_url = get_unsplash_image(search_query)
        if image_url:
            img_tag = f'<div style="text-align:center; margin:20px 0;"><img src="{image_url}" style="width:100%; max-width:600px; border-radius:10px;"></div>'
            if "[IMAGE]" in content_body:
                content_body = content_body.replace("[IMAGE]", img_tag)
            else:
                content_body = img_tag + "<br><br>" + content_body
        
        return title, content_body.replace("\n", "<br>")

    except Exception as e:
        return "Post Generation Error", f"Details: {str(e)}"

def post_to_wp():
    title, content = get_gemini_content()
    payload = {"title": title, "content": content, "status": "draft"}
    res = requests.post(WP_URL, auth=HTTPBasicAuth(WP_USER, WP_PASS), json=payload)
    if res.status_code == 201:
        print(f"✅ Successfully Posted: {title}")
    else:
        print(f"❌ Failed: {res.status_code}")

if __name__ == "__main__":
    post_to_wp()
