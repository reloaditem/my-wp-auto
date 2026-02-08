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

# 404 에러 방지를 위한 핵심 설정: 모델 이름을 경로와 함께 정확히 기재
genai.configure(api_key=GEMINI_KEY)

def get_unsplash_image(query):
    if not UNSPLASH_KEY: return None
    try:
        url = f"https://api.unsplash.com/search/photos?query={query}&client_id={UNSPLASH_KEY}&per_page=1"
        res = requests.get(url, timeout=10)
        data = res.json()
        return data['results'][0]['urls']['regular'] if data.get('results') else None
    except: return None

def get_gemini_content():
    try:
        # 정식 v1 API에서 작동하도록 모델 경로 지정
        model = genai.GenerativeModel('models/gemini-1.5-flash')
        
        # 강력한 영문 포스팅 지시
        prompt = """
        Write a professional blog post STRICTLY IN ENGLISH.
        Topic: "Smart Parenting: Essential Gadgets for Modern Dads"
        
        Format:
        1. Title: [Your English Title]
        2. SearchTerm: [One English keyword for image]
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
            content_body = content_body.replace("[IMAGE]", img_tag) if "[IMAGE]" in content_body else img_tag + "<br>" + content_body
        
        return title, content_body.replace("\n", "<br>")

    except Exception as e:
        # 에러 발생 시 워드프레스에 상세 에러를 찍어서 확인
        return "⚠️ Technical Error Report", f"Error Detail: {str(e)}"

def post_to_wp():
    title, content = get_gemini_content()
    payload = {"title": title, "content": content, "status": "draft"}
    res = requests.post(WP_URL, auth=HTTPBasicAuth(WP_USER, WP_PASS), json=payload)
    print(f"Post Result: {res.status_code}")

if __name__ == "__main__":
    post_to_wp()
