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
model = genai.GenerativeModel('gemini-1.5-flash')

def get_unsplash_image(query):
    """Unsplash에서 검색어에 맞는 이미지 URL을 가져옵니다."""
    try:
        url = f"https://api.unsplash.com/search/photos?query={query}&client_id={UNSPLASH_KEY}&per_page=1"
        res = requests.get(url)
        if res.status_code == 200:
            data = res.json()
            if data['results']:
                return data['results'][0]['urls']['regular']
        return None
    except:
        return None

def get_gemini_content():
    prompt = """
    너는 한국의 육아대디 블로거야. '육아는 템빨' 주제로 포스팅을 작성해줘.
    형식:
    1. 첫 줄은 '제목: [제목]'
    2. 두 번째 줄은 '검색어: [이미지 검색용 영어 키워드 하나]' (예: baby stroller, baby bottle)
    3. 그 다음부터는 본문을 작성해줘. 본문 중간에 [IMAGE] 라는 문구를 꼭 한 번 넣어줘.
    """
    response = model.generate_content(prompt)
    full_text = response.text
    lines = full_text.strip().split('\n')
    
    title = lines[0].replace("제목:", "").strip()
    search_query = lines[1].replace("검색어:", "").strip()
    content_body = "\n".join(lines[2:]).strip()
    
    # 이미지 가져오기 및 삽입
    image_url = get_unsplash_image(search_query)
    if image_url:
        img_tag = f'<img src="{image_url}" alt="{search_query}" style="width:100%; height:auto;">'
        content_body = content_body.replace("[IMAGE]", img_tag)
    
    return title, content_body

def post_to_wp():
    title, content = get_gemini_content()
    payload = {"title": title, "content": content, "status": "draft"}
    res = requests.post(WP_URL, auth=HTTPBasicAuth(WP_USER, WP_PASS), json=payload)
    if res.status_code == 201:
        print(f"✅ 성공: {title}")
    else:
        print(f"❌ 실패: {res.status_code}")

if __name__ == "__main__":
    post_to_wp()
