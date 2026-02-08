import os
import requests
from requests.auth import HTTPBasicAuth
import json

# 환경 변수 로드
WP_USER = os.environ.get('WP_USER')
WP_PASS = os.environ.get('WP_PASS')
# URL 끝에 슬래시(/) 유무를 확인하기 위해 직접 체크
WP_URL = "https://reloaditem.com/wp-json/wp/v2/posts"

def debug_post():
    print(f"📡 진단 시작: {WP_URL} 접속 시도 중...")
    
    # 아주 간단한 테스트 데이터
    payload = {
        "title": "Connection Test - " + os.environ.get('GITHUB_RUN_ID', '1'),
        "content": "Testing the connection after Jetpack install.",
        "status": "draft"
    }
    
    try:
        # 1. 사이트 접속 자체가 되는지 확인
        print(f"🔍 1단계: 사용자명({WP_USER})으로 인증 시도...")
        response = requests.post(
            WP_URL, 
            auth=HTTPBasicAuth(WP_USER, WP_PASS), 
            json=payload,
            timeout=30
        )
        
        print(f"📊 응답 상태 코드: {response.status_code}")
        
        if response.status_code == 201:
            print("✅ [성공] 글이 정상적으로 생성되었습니다! 워드프레스 '임시글'을 확인하세요.")
        elif response.status_code == 401:
            print("❌ [인증 실패] 비밀번호가 여전히 틀립니다. '애플리케이션 비밀번호'를 다시 확인하세요.")
            print(f"상세 내용: {response.text}")
        elif response.status_code == 403:
            print("❌ [접근 거부] 서버나 보안 플러그인이 API를 막고 있습니다.")
            print(f"상세 내용: {response.text}")
        elif response.status_code == 404:
            print("❌ [경로 오류] WP_URL 주소가 잘못되었습니다. 사이트 설정에서 고유주소를 확인하세요.")
        else:
            print(f"❌ [기타 오류] 서버 응답: {response.text}")

    except Exception as e:
        print(f"🔥 네트워크 레벨 오류 발생: {e}")

if __name__ == "__main__":
    debug_post()
