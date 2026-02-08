def get_unique_images(keywords):
    image_urls = []
    used_in_this_run = set()
    
    # 5개의 사진 공간을 확보
    for i in range(5):
        query = keywords[i] if i < len(keywords) else "lifestyle"
        found = False
        
        # 1. Unsplash 시도
        try:
            url = f"https://api.unsplash.com/search/photos?query={query.strip()}&client_id={UNSPLASH_KEY}&per_page=20&page={random.randint(1, 100)}"
            res = requests.get(url, timeout=10)
            
            # 응답이 성공(200)일 때만 처리
            if res.status_code == 200:
                data = res.json()
                if data.get('results'):
                    results = data['results']
                    random.shuffle(results)
                    for photo in results:
                        if photo['id'] not in used_in_this_run:
                            image_urls.append(photo['urls']['regular'])
                            used_in_this_run.add(photo['id'])
                            found = True
                            break
            else:
                print(f"⚠️ Unsplash API 제한 또는 오류 (상태 코드: {res.status_code})")
        except:
            pass
        
        # 2. Unsplash 실패 시 Picsum으로 즉시 대체 (무조건 사진 생성)
        if not found:
            # 주제별로 다른 랜덤 사진이 나오도록 시드값 부여
            print(f"📸 {i+1}번째 사진을 대체 이미지로 채웁니다.")
            image_urls.append(f"https://picsum.photos/seed/{random.randint(1, 99999)}/800/600")
            
    return image_urls
