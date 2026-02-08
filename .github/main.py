import os
import requests
from requests.auth import HTTPBasicAuth
import google.generativeai as genai

# 1. 환경 변수 로드 (공백 없이 깨끗하게 처리)
GEMINI_KEY = os.environ.get('GEMINI_API_KEY')
WP_USER = os.environ.get('WP_USER')
WP_PASS = os.environ.get('WP_PASS')
WP_URL = "https://reloaditem.com/wp-json/wp/v2/posts"

# 2. Gemini 설정
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

def get_gemini_content():
    try:
        # AI에게 시킬 명령어
        prompt = "워드프레스 블로그에 올릴 유익한 IT 트렌드나 자기계발 정보 글을 하나 작성해줘. 첫 줄은 '제목: [제목]' 형식으로 쓰고 그 다음 줄부터 본문을 작성해줘. 한국어로 아주 정성스럽게 작성해."
        response = model.generate_content(prompt)
        full_text = response.text
        
        # 제목과 본문 분리 로직
        lines = full_text.strip().split('\n')
        title = lines[0].replace("제목:", "").replace("**제목:**", "").strip()
        content = "\n".join(lines[1:]).strip()
        
        if not title:
            title = "오늘의 새로운 소식"
            
        return title, content
    except Exception as e:
        print(f"AI 글 생성 중 오류: {e}")
        return "제목 없음", "본문 생성 실패"

def post_to_wp():
    title, content = get_gemini_content()
    
    # 워드프레스 전송 데이터
    payload = {
        "title": title,
        "content": content,
        "status": "draft"
    }
    
    # 실제 전송
    res = requests.post(WP_URL, auth=HTTPBasicAuth(WP_USER, WP_PASS), json=payload)
    
    if res.status_code == 201:
        print(f"✅ 포스팅 성공: {title}")
    else:
        print(f"❌ 실패 코드: {res.status_code}")
        print(f"상세 내용: {res.text}")

if __name__ == "__main__":
    post_to_wp()
