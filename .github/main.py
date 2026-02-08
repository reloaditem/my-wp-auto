def get_unique_images(keywords):
    image_urls = []
    already_used = load_used_ids()
    current_post_ids = set()
    
    # 가장 대중적인 키워드로 백업 리스트 준비
    backup_keywords = ["nature", "travel", "technology", "family", "interior"]

    for i in range(5):
        query = keywords[i] if i < len(keywords) else random.choice(backup_keywords)
        found = False
        try:
            # per_page를 늘려 선택지를 넓힘
            url = f"https://api.unsplash.com/search/photos?query={query.strip()}&client_id={UNSPLASH_KEY}&per_page=30&page={random.randint(1, 50)}"
            res = requests.get(url, timeout=10).json()
            
            if res.get('results'):
                results = res['results']
                random.shuffle(results)
                for photo in results:
                    p_id = photo['id']
                    if p_id not in already_used and p_id not in current_post_ids:
                        # 주소 뒤에 고유 파라미터를 붙여 강제로 다른 사진이 로드되게 함
                        img_url = f"{photo['urls']['regular']}&sig={random.randint(1, 9999)}"
                        image_urls.append(img_url)
                        current_post_ids.add(p_id)
                        save_used_id(p_id)
                        found = True
                        break
        except: pass
        
        # [강력 조치] 검색 실패 시, 절대 깨지지 않는 고화질 랜덤 이미지 서비스(Picsum) 활용
        if not found:
            # Lorem Picsum은 절대 깨지지 않고 랜덤 사진을 던져줍니다.
            image_urls.append(f"https://picsum.photos/800/600?random={random.randint(1, 100000)}")

    return image_urls
