import os
import requests
from requests.auth import HTTPBasicAuth
import google.generativeai as genai

# 1. 깃허브 Secrets에 저장한 이름과 똑같아야 합니다!
GEMINI_KEY = os.environ.get('GEMINI_API_KEY') 
WP_USER = os.environ.get('WP_USER')
WP_PASS = os.environ.get('WP_PASS')
WP_URL = "https://reloaditem.com/wp-json/wp/v2/posts"

# Gemini 설정
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

def get_gemini_content():
    # 제가 사용자님 블로그에 어울리는 글을 쓰도록 명령어를 다듬었습니다.
    prompt = "워드프레스 블로그에 올릴 유익한 IT 또는 생활 정보 글을 하나 작성해줘. 형식은 '제목: [제목]'으로 시작하고 그 다음 줄에 본문을 써줘."
    response = model.generate_content(prompt)
    full_text = response.text
    
    lines = full_text.split('\n')
    title = lines[0].replace("제목:", "").strip()
    content = "\n".join(lines[1:]).strip()
    
    return title, content

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

if __name__ == "__main__":
    post_to_wp()
