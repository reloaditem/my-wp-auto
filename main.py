import os
import requests
from requests.auth import HTTPBasicAuth
from openai import OpenAI
import random
import time # 요청 간 시간 간격을 두기 위함

# 환경 변수 로드 (절대 변경 금지)
OPENAI_KEY = os.environ.get('OPENAI_API_KEY')
UNSPLASH_KEY = os.environ.get('UNSPLASH_ACCESS_KEY')
WP_USER = os.environ.get('WP_USER')
WP_PASS = os.environ.get('WP_PASS')
WP_URL = "https://reloaditem.com/wp-json/wp/v2/posts"

client = OpenAI(api_key=OPENAI_KEY)

# --- [ 함수: Unsplash에서 이미지 가져오기 ] ---
def get_unsplash_images(queries, num_images=5):
    """지정된 키워드로 Unsplash에서 여러 이미지를 가져옵니다."""
    if not UNSPLASH_KEY: return []
    image_urls = []
    
    # 한국 분위기 키워드 추가 (기본 검색어 + 랜덤 한국 키워드)
    korean_keywords = ['korea', 'seoul', 'korean food', 'korean culture', 'korean tradition', 'busan', 'jeju']
    
    for i, query in enumerate(queries):
        # 섞어서 사용: ChatGPT가 준 키워드 + 무작위 한국 키워드
        search_query = f"{query.strip()} {random.choice(korean_keywords)}"
        try:
            url = f"https://api.unsplash.com/search/photos?query={search_query}&client_id={UNSPLASH_KEY}&per_page=1"
            res = requests.get(url, timeout=10).json()
            if res.get('results'):
                image_urls.append(res['results'][0]['urls']['regular'])
            else: # 검색 결과가 없으면 기본 한국 키워드로 대체
                backup_query = random.choice(korean_keywords)
                url = f"https://api.unsplash.com/search/photos?query={backup_query}&client_id={UNSPLASH_KEY}&per_page=1"
                res = requests.get(url, timeout=10).json()
                if res.get('results'):
                    image_urls.append(res['results'][0]['urls']['regular'])
        except:
            continue
        
        if len(image_urls) >= num_images: # 필요한 이미지 수만큼만 가져옴
            break
            
    # 필요한 이미지 수가 부족하면 한국 관련 기본 이미지로 채움
    while len(image_urls) < num_images:
        backup_query = random.choice(korean_keywords)
        try:
            url = f"https://api.unsplash.com/search/photos?query={backup_query}&client_id={UNSPLASH_KEY}&per_page=1"
            res = requests.get(url, timeout=10).json()
            if res.get('results'):
                image_urls.append(res['results'][0]['urls']['regular'])
            else:
                image_urls.append("https://via.placeholder.com/600x400?text=Image+Placeholder") # 최종 백업
        except:
            image_urls.append("https://via.placeholder.com/600x400?text=Image+Placeholder") # 최종 백업
    
    return image_urls

# --- [ 함수: ChatGPT로 블로그 콘텐츠 생성 ] ---
def get_blog_content_from_chatgpt(post_number):
    """ChatGPT로 한국 관련 블로그 포스팅 내용을 생성합니다."""
    try:
        # 매번 다른 한국 관련 주제를 선정하도록 지시
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a professional blogger specializing in Korean culture, travel, food, or lifestyle. Write in ENGLISH ONLY. Make sure each post has a unique, engaging topic about Korea."},
                {"role": "user", "content": f"Create a long-form blog post (Post {post_number}) about a unique trending topic related to 'South Korea'. \n\nRequirements:\n1. Language: English Only.\n2. Structure:\n   Line 1: Title: [Catchy Title about Korea]\n   Line 2: Keywords: [5 to 7 diverse keywords for images, separated by commas, related to the topic and Korea]\n   Body: Write 5 to 7 detailed sections with subheadings and emojis. Explicitly place [IMAGE1], [IMAGE2], ..., [IMAGE7] tags where appropriate in the body to suggest image placements."}
            ]
        )
        text = response.choices[0].message.content.strip()
        lines = text.split('\n')
        
        title = lines[0].replace("Title:", "").replace("**", "").strip()
        
        # 키워드 추출 (5~7개)
        keywords_str = ""
        if "Keywords:" in lines[1]:
            keywords_str = lines[1].replace("Keywords:", "").strip()
        
        keywords = [k.strip() for k in keywords_str.split(',') if k.strip()]
        
        # 최소 5개, 최대 7개의 이미지를 요청하도록 조정
        num_images_to_get = random.randint(5, 7)
        if len(keywords) < num_images_to_get: # 키워드가 부족하면 기본 한국 키워드 추가
            keywords.extend(random.sample(['korea', 'seoul', 'hanok', 'kpop', 'kdrama', 'korean food', 'travel korea'], num_images_to_get - len(keywords)))
        
        image_urls = get_unsplash_images(keywords[:num_images_to_get], num_images_to_get) # 필요한 개수만큼만 넘김
        
        content_body = "\n".join(lines[2:]).strip()

        # 본문의 이미지 태그들을 실제 HTML로 변환
        for i in range(num_images_to_get):
            tag_to_replace = f"[IMAGE{i+1}]"
            # 이미지 URL이 있으면 사용, 없으면 플레이스홀더
            img_src = image_urls[i] if i < len(image_urls) else "https://via.placeholder.com/600x400?text=Image+Placeholder"
            
            # 모바일 최적화 및 전문적인 디자인
            img_html = f'<div style="text-align:center; margin:35px 0;"><img src="{img_src}" style="width:100%; max-width:750px; border-radius:20px; box-shadow: 0 10px 20px rgba(0,0,0,0.15);"></div>'
            
            if tag_to_replace in content_body:
                content_body = content_body.replace(tag_to_replace, img_html)
            else:
                # 태그가 없으면 본문 끝에 추가 (모든 이미지가 들어가도록)
                content_body += "<br>" + img_html

        return title, content_body.replace("\n", "<br>")
    except Exception as e:
        return f"ChatGPT Content Generation Error (Post {post_number})", f"Details: {str(e)}"

# --- [ 함수: 워드프레스에 포스팅 ] ---
def post_to_wordpress(title, content):
    """생성된 콘텐츠를 워드프레스에 발행합니다."""
    payload = {
        "title": title, 
        "content": content, 
        "status": "publish" # 즉시 발행 (혹은 'draft'로 임시 저장)
    }
    try:
        res = requests.post(WP_URL, auth=HTTPBasicAuth(WP_USER, WP_PASS), json=payload)
        if res.status_code == 201:
            print(f"✅ Success! Posted: {title} (Status: {res.status_code})")
        else:
            print(f"❌ Failed to post '{title}': {res.status_code} - {res.text}")
    except Exception as e:
        print(f"❌ Network or WordPress Error for '{title}': {str(e)}")

# --- [ 메인 실행 함수 ] ---
if __name__ == "__main__":
    num_posts_to_create = random.randint(2, 3) # 한 번 실행 시 2~3개 포스팅
    print(f"🚀
