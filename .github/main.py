import os
import requests
from requests.auth import HTTPBasicAuth
import google.generativeai as genai

# 1. 환경 변수 안전하게 로드
GEMINI_KEY = os.environ.get('GEMINI_API_KEY')
UNSPLASH_KEY = os.environ.get('UNSPLASH_ACCESS_KEY')
WP_USER = os.environ.get('WP_USER')
WP_PASS = os.environ.get('WP_PASS')
WP_URL = "https://reloaditem.com/wp-json/wp/v2/posts"

# 2. Gemini 설정
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

def get_unsplash_image(query):
    """이미지 검색 실패 시 에러를 내지 않고 넘어가도록 보완"""
    if not UNSPLASH_KEY:
        print("⚠️ Unsplash 키가 설정되지 않았습니다.")
        return None
    try:
        # 영어 검색어가 아니면 검색이 안 될 수 있어 간단히 처리
        url = f"https://api.unsplash.com/search/photos?query={query}&client_id={UNSPLASH_KEY}&per_page=1"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            data = res.json()
            if data.get('results'):
                return data['results'][0]['urls']['regular']
        return None
    except Exception as e:
        print(f"⚠️ 이미지 검색 중 오류 발생: {e}")
        return None

def get_gemini_content():
    try:
        prompt = """
        한국의 육아대디 블로거로서 '육아는 템빨' 주제로 글을 써줘.
        첫 줄은 '제목: [제목]'
        두 번째 줄은 '검색어: [이미지 검색용 영어 키워드 하나]' (예: baby car seat)
        그 다음부터 본문을 작성하고, 본문 중간에 [IMAGE] 라고 써줘.
        """
        response = model.generate_content(prompt)
        full_text = response.text
        lines = full_text.strip().split('\n')
        
        title = lines[0].replace("제목:", "").strip()
        # 검색어 줄이 없을 경우를 대비
        search_query = "baby" 
        if "검색어:" in lines[1]:
            search_query = lines[1].replace("검색어:", "").strip()
        
        content_body = "\n".join(lines[2:]).strip()
        
        # 이미지 검색 및 태그 교체
        image_url = get_unsplash_image(search_query)
        if image_url:
            img_tag = f'<img src="{image_url}" alt="{search_query}" style="width:100%; max-width:600px; display:block; margin:20px auto;">'
            content_body = content_body.replace("[IMAGE]", img_tag)
        else:
            content_body = content_body.replace("[IMAGE]", "") # 이미지 없으면 문구 제거
            
        return title, content_body
    except Exception as e:
        print(f"⚠️ 글 생성 중 오류: {e}")
        return "육아대디의 일상 이야기", "글 생성에 실패했습니다."

def post_to_wp():
    title, content = get_gemini_content()
    payload = {
        "title": title,
        "content": content,
        "status": "draft"
    }
    
    res = requests.post(WP_URL, auth=HTTPBasicAuth(WP_USER, WP_PASS), json=payload)
    if res.status_code == 201:
        print(f"✅ 포스팅 성공: {title}")
    else:
        print(f"❌ 워드프레스 전송 실패: {res.status_code}")
        print(res.text)

if __name__ == "__main__":
    post_to_wp()
