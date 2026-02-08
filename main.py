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

# [핵심] 404 에러 방지를 위한 설정 (정식 버전 v1 사용)
genai.configure(api_key=GEMINI_KEY, transport='rest')

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
        # 모델 설정
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        # [수정] 영문 포스팅을 위한 강력한 영문 프롬프트
        prompt = """
        Write a professional and engaging blog post in ENGLISH.
        Topic: "Korean 'Parenting Daddy' Life and the Must-have Baby Items (The power of gear)"
        
        Guidelines:
        1. Language: STRICTLY ENGLISH ONLY.
        2. First line: Title: [Your Title]
        3. Second line: SearchTerm: [English Keyword for Image] (e.g., baby stroller)
        4. Content: Write a detailed post including subheadings and emojis. 
        5. Place the tag [IMAGE] in the middle of the content.
        """
        
        response = model.generate_content(prompt)
        full_text = response.text.strip()
        
        if not full_text:
            return "Parenting Daddy's Daily Life", "Failed to generate content."

        lines = full_text.split('\n')
        title = lines[0].replace("Title:", "").replace("**", "").strip()
        
        search_query = "baby"
        if len(lines) > 1 and "SearchTerm:" in lines[1]:
            search_query = lines[1].replace("SearchTerm:", "").strip()
            content_body = "\n".join(lines[2:]).strip()
        else:
            content_body = "\n".join(lines[1:]).strip()

        # 이미지 처리 (Unsplash에서 사진 가져오기)
        image_url = get_unsplash_image(search_query)
        if image_url:
            img_tag = f'<div style="text-align:center;"><img src="{image_url}" style="width:100%; max-width:600px; border-radius:10px; margin:20px 0;"></div>'
            if "[IMAGE]" in content_body:
                content_body = content_body.replace("[IMAGE]", img_tag)
            else:
                content_body = img_tag + "<br><br>" + content_body
        
        # 워드프레스 줄바꿈 처리
        content_body = content_body.replace("\n", "<br>")
        
        return title, content_body

    except Exception as e:
        return "Post Error", f"Error details: {str(e)}"

def post_to_wp():
    title, content = get_gemini_content()
    
    payload = {
        "title": title,
        "content": content,
        "status": "draft"
    }
    
    res = requests.post(WP_URL, auth=HTTPBasicAuth(WP_USER, WP_PASS), json=payload)
    if res.status_code == 201:
        print(f"✅ Success: {title}")
    else:
        print(f"❌ Failed: {res.status_code}")

if __name__ == "__main__":
    post_to_wp()
