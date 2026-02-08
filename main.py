def get_unique_images(keywords):
    image_urls = []
    used_in_this_run = set()
    
    for i in range(5):
        query = keywords[i] if i < len(keywords) else "lifestyle"
        found = False
        try:
            # Unsplash API 호출
            url = f"https://api.unsplash.com/search/photos?query={query.strip()}&client_id={UNSPLASH_KEY}&per_page=20&page={random.randint(1, 100)}"
            res = requests.get(url, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if data.get('results'):
                    results = data['results']
                    random.shuffle(results)
                    for photo in results:
                        if photo['id'] not in used_in_this_run:
                            # ⚠️ 중요: 원본 대신 가벼운 regular 사이즈 사용
                            image_urls.append(photo['urls']['regular'])
                            used_in_this_run.add(photo['id'])
                            found = True
                            break
        except: pass
        
        # Unsplash 실패 시 Picsum 백업 (절대 깨지지 않음)
        if not found:
            print(f"📸 {i+1}번 사진 Picsum 대체 로드")
            image_urls.append(f"https://picsum.photos/seed/{random.randint(1, 99999)}/800/600")
            
    return image_urls

# ... (중략: get_blog_content 내부의 이미지 치환 로직 부분) ...

        content_body = "".join(content_parts)
        for i in range(len(final_images)):
            # 💡 워드프레스가 가장 좋아하는 표준 이미지 HTML 구조
            img_html = (
                f'<figure style="text-align:center; margin:40px 0;">'
                f'<img src="{final_images[i]}" alt="lifestyle image" '
                f'style="width:100%; max-width:850px; height:auto; border-radius:15px; box-shadow: 0 10px 25px rgba(0,0,0,0.2);">'
                f'</figure>'
            )
            content_body = content_body.replace(f"[IMAGE{i+1}]", img_html)
