import requests
from requests.auth import HTTPBasicAuth
import os

# 깃허브 비밀 금고에서 정보를 가져옵니다
WP_USER = os.environ.get('WP_USER')
WP_PASS = os.environ.get('WP_PASS')
WP_URL = "https://reloaditem.com/wp-json/wp/v2/posts"

def post_to_wp():
    payload = {
        "title": "자동화로 생성된 미발행 포스팅",
        "content": "이 글은 깃허브에서 자동으로 보낸 글입니다.",
        "status": "draft" # 미발행 상태
    }
    
    res = requests.post(WP_URL, auth=HTTPBasicAuth(WP_USER, WP_PASS), json=payload)
    if res.status_code == 201:
        print("포스팅 성공!")
    else:
        print(f"실패: {res.status_code}")

if __name__ == "__main__":
    post_to_wp()
