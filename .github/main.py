import os
import requests
from requests.auth import HTTPBasicAuth
import google.generativeai as genai

# 1. 환경 변수 안전하게 가져오기
GEMINI_KEY = os.environ.get('GEMINI_API_KEY')
WP_USER = os.environ.get('WP_USER')
WP_PASS = os.environ.get('WP_PASS')
WP_URL = "https://reloaditem.com/wp-json/wp/v2/posts"

# 2. Gemini 설정
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

def get_gemini_content():
    try:
        prompt = "워드프레스 블로그에 올릴 유익한 IT 또는 생활 정보 글을 하나 작성해줘. 첫 줄은 '제목: [제목]' 형식으로 쓰고 그 다음 줄에 본문을 써줘. 한국어로 작성해."
        response = model.generate_content(prompt)
        full_text = response.text
        
        lines = full_text.strip().split('\n')
        title = lines[0].replace("제목:", "").replace("**제목:**", "").strip()
        content = "\n".join(lines[1:]).strip()
        
        if not title: title = "오늘의 유익한 소식"
        return title, content
    except Exception as e:
        print(f"AI 글생성 실패: {e}")
        return "제목 없음", "본문 생성 실패"

def post_to_wp():
    title, content = get_gemini_content()
    
    payload = {
        "title": title,
        "content": content,
        "status": "draft"
    }
    
    res = requests.post(WP_URL, auth=HTTPBasicAuth(WP_USER, WP_PASS), json=payload)
    if res.status_code == 201:
        print(f"✅ 성공: {title}")
    else:
        print(f"❌ 실패 코드: {res.status_code}")
        print(f"상세 내용: {res.text}")

if __name__ == "__main__":
    post_to_wp()
