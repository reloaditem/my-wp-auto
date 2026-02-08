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

# Gemini 설정 (모델명을 latest로 변경하여 404 에러 해결)
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash-latest')

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
        너는 한국의 베테랑 '육아대디' 블로거야. '육아는 템빨' 주제로 정성스러운 포스팅을 작성해줘.
        형식 가이드:
        1. 첫 줄은 '제목: [흥미로운 제목]'
        2. 두 번째 줄은 '검색어: [이미지 영어 키워드]' (예: baby nursery)
        3. 세 번째 줄부터는 본문을 아주 길고 유익하게 써줘. (소제목, 이모지 활용)
        4. 본문 중간에 반드시 [IMAGE] 문구를 넣어줘.
        """
        response = model.generate_content(prompt)
        full_text = response.text.strip()
        
        # 텍스트가 비어있는지 확인
        if not full_text:
            return "육아대디의 장비빨 일기", "AI 응답이 비어있습니다."

        lines = full_text.split('\n')
        title = lines[0].replace("제목:", "").replace("**", "").strip()
        
        search_query = "baby"
        if len(lines) > 1 and "검색어:" in lines[1]:
            search_query = lines[1].replace("검색어:", "").replace("**", "").strip()
            content_body = "\n".join(lines[2:]).strip()
        else:
            content_body = "\n".join(lines[1:]).strip()

        # 이미지가 없을 경우 대비 안전장치
        image_url = get_unsplash_image(search_query)
        if image_url:
            img_tag = f'<div style="text-align:center;"><img src="{image_url}" style="width:100%; max-width:600px; border-radius:10px; margin:20px 0;"></div>'
            if "[IMAGE]" in content_body:
                content_body = content_body.replace("[IMAGE]", img_tag)
            else:
                content_body = img_tag + "<br><br>" + content_body
        
        # 줄바꿈을 HTML 태그로 변환 (워드프레스 가독성)
        content_body = content_body.replace("\n", "<br>")
        
        return title, content_body

    except Exception as e:
        return "육아대디의 장비빨 일상", f"에러 발생: {str(e)}"

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
        print(f"❌ 실패 코드: {res.status_code}, 메시지: {res.text}")

if __name__ == "__main__":
    post_to_wp()
