import os
import requests
from requests.auth import HTTPBasicAuth
import google.generativeai as genai
from google.generativeai.types import RequestOptions

# 환경 변수 로드
GEMINI_KEY = os.environ.get('GEMINI_API_KEY')
UNSPLASH_KEY = os.environ.get('UNSPLASH_ACCESS_KEY')
WP_USER = os.environ.get('WP_USER')
WP_PASS = os.environ.get('WP_PASS')
WP_URL = "https://reloaditem.com/wp-json/wp/v2/posts"

# [핵심] 404 에러 해결을 위해 v1 정식 버전 서버로 고정
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
        # v1 정식 API 경로를 사용하도록 옵션 설정
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        # [수정] 강력한 영문 포스팅 지시어
        prompt = """
        Write a high-quality blog post in ENGLISH ONLY.
        Topic: "Korean 'Parenting Daddy' Life and Must-have Baby Items (Parenting is all about the gear)"
        
        Format:
        1. First line: Title: [Catchy Title in English]
        2. Second line: SearchTerm: [One English Keyword for Image] (e.g., baby carrier)
        3. Body: Write a detailed post with subheadings and emojis in English. 
        4. Place the tag [IMAGE] where a photo should go.
        """
        
        # v1 API를 강제 호출하여 404 에러 방지
        response = model.generate_content(
            prompt, 
            request_options=RequestOptions(api_version='v1')
        )
        full_text = response.text.strip()
        
        lines = full_text.split('\n')
        title = lines[0].replace("Title:", "").replace("**", "").strip()
        
        search_query = "baby"
        if len(lines) > 1 and "SearchTerm:" in lines[1]:
            search_query = lines[1].replace("SearchTerm:", "").strip()
            content_body = "\n".join(lines[2:]).strip()
        else:
            content_body = "\n".join(lines[1:]).strip()

        # 이미지 처리
        image_url = get_unsplash_image(search_query)
        if image_url:
            img_tag = f'<div style="text-align:center;"><img src="{image_url}" style="width:100%; max-width:600px; border-radius:10px;"></div>'
            content_body = content_body.replace("[IMAGE]", img_tag) if "[IMAGE]" in content_body else img_tag + "<br>" + content_body
        
        # 워드프레스 개행 처리
        return title, content_body.replace("\n", "<br>")

    except Exception as e:
        # 에러 발생 시 워드프레스 글 제목으로 에러 내용 확인
        return "⚠️ API Error Check", f"Detailed Error: {str(e)}"

def post_to_wp():
    title, content = get_gemini_content()
    payload = {"title": title, "content": content, "status": "draft"}
    res = requests.post(WP_URL, auth=HTTPBasicAuth(WP_USER, WP_PASS), json=payload)
    print(f"Post Result: {res.status_code}")

if __name__ == "__main__":
    post_to_wp()
