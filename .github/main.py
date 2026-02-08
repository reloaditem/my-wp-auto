import os
import requests
from requests.auth import HTTPBasicAuth
from openai import OpenAI
import random
import time

# 환경 변수 설정
OPENAI_KEY = os.environ.get('OPENAI_API_KEY')
UNSPLASH_KEY = os.environ.get('UNSPLASH_ACCESS_KEY')
WP_USER = os.environ.get('WP_USER')
WP_PASS = os.environ.get('WP_PASS')
WP_URL = "https://reloaditem.com/wp-json/wp/v2/posts/"

client = OpenAI(api_key=OPENAI_KEY)

# 카테고리 맵 (알려주신 ID 반영)
CATEGORY_MAP = {
    "Innovative Tech & AI Gadgets": 1,
    "Pro Camping & Family Adventure": 11,
    "Hidden Family Travel Gems": 4,
    "Advanced Parenting Science": 3,
    "Biohacking & Family Longevity": 2
}
TOPICS = list(CATEGORY_MAP.keys())

def get_unique_images(keywords):
    image_urls = []
    used_in_this_run = set()
    
    for query in keywords[:5]:
        found = False
        try:
            url = f"https://api.unsplash.com/search/photos?query={query.strip()}&client_id={UNSPLASH_KEY}&per_page=30&page={random.randint(1, 100)}"
            res = requests.get(url, timeout=10).json()
            if res.get('results'):
                results = res['results']
                random.shuffle(results)
                for photo in results:
                    if photo['id'] not in used_in_this_run:
                        image_urls.append(photo['urls']['regular'])
                        used_in_this_run.add(photo['id'])
                        found = True
                        break
        except Exception as e:
            print(f"이미지 검색 중 오류: {e}")
        
        if not found:
            image_urls.append(f"https://picsum.photos/800/600?random={random.randint(1, 99999)}")
    return image_urls

def get_blog_content():
    selected = random.choice(TOPICS)
    cat_id = CATEGORY_MAP[selected]
    print(f"선택된 주제: {selected} (ID: {cat_id})")
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": f"You are a pro blogger specializing in {selected}. Write in English. Use <h2> for subheadings. If no tags, ensure subheadings are short and end with a colon (:). NO ** symbols."},
                {"role": "user", "content": f"Write a 5-section blog about {selected}. Title: [Title], Keywords: [5 keywords], Body: Use [IMAGE1] to [IMAGE5]."}
            ]
        )
        text = response.choices[0].message.content.strip()
        lines = text.split('\n')

        title = f"Latest Insights on {selected}"
        keywords = ["lifestyle", "expert", "quality"]
        
        for line in lines:
            if "Title:" in line: title = line.replace("Title:", "").replace("**", "").replace("#", "").strip()
            if "Keywords:" in line: keywords = [k.strip() for k in line.replace("Keywords:", "").split(',') if k.strip()]

        final_images = get_unique_images(keywords)
        content_parts = []

        for line in lines:
            if any(x in line for x in ["Title:", "Keywords:"]): continue
            clean_line = line.replace("**", "").replace("#", "").strip()
            if not clean_line: continue
            
            # --- 소제목 인식 로직 대폭 강화 ---
            # 1. <h2> 태그가 있거나
            # 2. 65자 미만이면서 (숫자로 시작하거나, 콜론으로 끝나거나, 대문자로 시작하는 짧은 문장)
            is_likely_heading = (
                clean_line.startswith('<h') or 
                (len(clean_line) < 65 and (
                    clean_line[0].isdigit() or 
                    clean_line.endswith(':') or 
                    clean_line.isupper() or
                    clean_line.istitle()
                ))
            )

            if is_likely_heading:
                # 불필요한 장식 제거 후 스타일 입히기
                pure_text = clean_line.replace("<h2>","").replace("</h2>","").replace("1.","").replace("2.","").replace("3.","").replace("4.","").replace("5.","").strip(" :")
                content_parts.append(f'<h2 style="color: #1a2a6c; margin-top: 45px; border-left: 10px solid #f2a365; padding-left: 15px; font-weight: bold; line-height: 1.3;">{pure_text}</h2>')
            else:
                content_parts.append(f'<p style="line-height: 2.0; margin-bottom: 25px; font-size: 1.15em; color: #2c3e50;">{clean_line}</p>')

        content_body = "".join(content_parts)
        for i in range(len(final_images)):
            img_html = f'<div style="text-align:center; margin:45px 0;"><img src="{final_images[i]}" style="width:100%; max-width:850px; border-radius:15px; box-shadow: 0 10px 30px rgba(0,0,0,0.15);"></div>'
            content_body = content_body.replace(f"[IMAGE{i+1}]", img_html)

        return title, content_body, cat_id
    except Exception as e:
        print(f"글 생성 중 오류 발생: {e}")
        return None, None, None

if __name__ == "__main__":
    success_count = 0
    for i in range(2):
        print(f"\n--- {i+1}번째 포스팅 시도 ---")
        t, c, cid = get_blog_content()
        if t and c:
            payload = {"title": t, "content": c, "status": "publish", "categories": [cid]}
            res = requests.post(WP_URL, auth=HTTPBasicAuth(WP_USER, WP_PASS), json=payload)
            if res.status_code == 201:
                print(f"✅ 발행 성공: {t}")
                success_count += 1
            else:
                print(f"❌ 워드프레스 전송 실패: {res.status_code} - {res.text}")
        time.sleep(20)
    print(f"\n총 {success_count}개의 글이 성공적으로 처리되었습니다.")
