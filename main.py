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
    if not UNSPLASH_KEY: return None
    try:
        url = f"https://api.unsplash.com/search/photos?query={query}&client_id={UNSPLASH_KEY}&per_page=1"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            data = res.json()
            if data.get('results'):
                return data['results'][0]['urls']['regular']
        return None
    except: return None

def get_gemini_content():
    try:
        prompt = """
        한국의 육아대디 블로거로서 '육아는 템빨' 주제로 글을 써줘.
        1. 첫 줄은 무조건 '제목: [제목]' 형식으로 써줘.
        2. 두 번째 줄은 무조건 '검색어: [영어키워드]' 형식으로 써줘.
        3. 그 다음 줄부터 본문을 아주 길고 정성스럽게 써줘. 
        4. 본문 중간에 [IMAGE] 라는 글자를 꼭 넣어줘.
        """
        response = model.generate_content(prompt)
        full_text = response.text.strip()
        
        lines = full_text.split('\n')
        
        # 1. 제목 추출 (첫 줄에 '제목:'이 없어도 첫 줄을 제목으로 사용)
        title = lines[0].replace("제목:", "").replace("**", "").strip()
        
        # 2. 검색어 추출 및 본문 시작 위치 찾기
        search_query = "baby"
        content_start_idx = 1
        
        if len(lines) > 1 and "검색어:" in lines[1]:
            search_query = lines[1].replace("검색어:", "").replace("**", "").strip()
            content_start_idx = 2
        
        # 3. 본문 합치기 (본문이 비어있지 않게 보장)
        content_body = "\n".join(lines[content_start_idx:]).strip()
        
        # 만약 본문이 너무 짧으면 전체 텍스트를 그냥 본문으로 사용 (안전장치)
        if len(content_body) < 10:
            content_body = full_text

        # 4. 이미지 처리
        image_url = get_unsplash_image(search_query)
        if image_url:
            img_tag = f'<img src="{image_url}" alt="{search_query}" style="width:100%; max-width:600px; height:auto; display:block; margin:20px auto;">'
            if "[IMAGE]" in content_body:
                content_body = content_body.replace("[IMAGE]", img_tag)
            else:
                content_body = img_tag + "\n\n" + content_body
        
        # 워드프레스 개행(줄바꿈) 처리
        content_body = content_body.replace("\n", "<br>")
        
        return title, content_body
    except Exception as e:
        print(f"오류 발생: {e}")
        return "육아대디의 장비빨 일상", f"글 생성 중 오류가 발생했습니다: {e}"

def post_to_wp():
    title, content = get_gemini_content()
    
    # 전송 데이터 로그 확인 (에러 추적용)
    print(f"--- 전송될 제목: {title}")
    print(f"--- 본문 길이: {len(content)} 자")

    payload = {
        "title": title,
        "content": content, # HTML 형식을 지원하기 위해 'content' 필드 사용
        "status": "draft"
    }
    
    res = requests.post(WP_URL, auth=HTTPBasicAuth(WP_USER, WP_PASS), json=payload)
    if res.status_code == 201:
        print(f"✅ 성공: {title}")
    else:
        print(f"❌ 실패 코드: {res.status_code}")
        print(f"응답: {res.text}")

if __name__ == "__main__":
    post_to_wp()
