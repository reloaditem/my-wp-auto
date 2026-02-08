import os
import requests
from requests.auth import HTTPBasicAuth
from openai import OpenAI

# 환경 변수 로드
OPENAI_KEY = os.environ.get('OPENAI_API_KEY')
UNSPLASH_KEY = os.environ.get('UNSPLASH_ACCESS_KEY')
WP_USER = os.environ.get('WP_USER')
WP_PASS = os.environ.get('WP_PASS')
WP_URL = "https://reloaditem.com/wp-json/wp/v2/posts"

# OpenAI 클라이언트 설정
client = OpenAI(api_key=OPENAI_KEY)

def get_unsplash_image(query):
    if not UNSPLASH_KEY: return None
    try:
        url = f"https://api.unsplash.com/search/photos?query={query}&client_id={UNSPLASH_KEY}&per_page=1"
        res = requests.get(url, timeout=10)
        data = res.json()
        if 'results' in data and len(data['results']) > 0:
            return data['results'][0]['urls']['regular']
        return None
    except: return None

def get_chatgpt_content():
    try:
        # 영문 포스팅 생성을 위한 ChatGPT 요청
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a professional blogger who writes high-quality content in English."},
                {"role": "user", "content": "Write an engaging and detailed blog post about 'Top Parenting Gear for Modern Dads'. \n\nRules:\n1. Language: English Only.\n2. Format:\n   Line 1: Title: [Your English Title]\n   Line 2: SearchTerm: [English keyword for image]\n   Body: Start writing content here with emojis and subheadings. Include a tag [IMAGE] in the middle."}
            ]
        )
        
        full_text = response.choices[0].message.content.strip()
        lines = full_text.split('\n')
        
        # 제목 및 검색어 파싱
        title = lines[0].replace("Title:", "").replace("**", "").strip()
        search_query = "parenting gear"
        content_start = 1
        
        if "SearchTerm:" in lines[1]:
            search_query = lines[1].replace("SearchTerm:", "").replace("**", "").strip()
            content_start = 2
            
        content_body = "\n".join(lines[content_start:]).strip()

        # 사진 가져오기 및 삽입
        image_url = get_unsplash_image(search_query)
        if image_url:
            img_tag = f'<div style="text-align:center; margin:20px 0;"><img src="{image_url}" style="width:100%; max-width:600px; border-radius:12px;"></div>'
            if "[IMAGE]" in content_body:
                content_body = content_body.replace("[IMAGE]", img_tag)
            else:
                content_body = img_tag + "<br><br>" + content_body
        
        # 워드프레스용 줄바꿈 처리
        return title, content_body.replace("\n", "<br>")

    except Exception as e:
        return "ChatGPT Generation Error", f"Technical Details: {str(e)}"

def post_to_wp():
    title, content = get_chatgpt_content()
    
    payload = {
        "title": title,
        "content": content,
        "status": "draft" # 워드프레스에 임시글로 저장 (검토 후 발행 가능)
    }
    
    res = requests.post(WP_URL, auth=HTTPBasicAuth(WP_USER, WP_PASS), json=payload)
    if res.status_code == 201:
        print(f"✅ Success! Posted: {title}")
    else:
        print(f"❌ Failed! Status Code: {res.status_code}")

if __name__ == "__main__":
    post_to_wp()
