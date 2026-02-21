# =========================
# FIXED VERSION (415 PATCH)
# wp_maintain_all.py
# =========================

import os
import re
import io
import html as html_mod
import random
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Tuple

import requests
from requests.auth import HTTPBasicAuth
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont
from openai import OpenAI


# =========================
# ENV
# =========================
WP_BASE = os.environ.get("WP_BASE", "").rstrip("/")
WP_USER = os.environ.get("WP_USER", "")
WP_PASS = os.environ.get("WP_PASS", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "")

thumb_env = os.environ.get("THUMBNAIL_BASE_MEDIA_ID")
THUMBNAIL_BASE_MEDIA_ID = int(thumb_env) if thumb_env and thumb_env.strip() else 332

SITE_BRAND = os.environ.get("SITE_BRAND", "ReloadItem.com")
HEADER_TEXT = os.environ.get("HEADER_TEXT", "AI Tools · 2026")

MIN_PLAIN_TEXT_LEN = int(os.environ.get("MIN_PLAIN_TEXT_LEN", "200"))
BODY_IMAGE_COUNT = int(os.environ.get("BODY_IMAGE_COUNT", "3"))
TIMEOUT = int(os.environ.get("HTTP_TIMEOUT", "30"))

if not (WP_BASE and WP_USER and WP_PASS):
    raise SystemExit("Missing env: WP_BASE, WP_USER, WP_PASS")

auth = HTTPBasicAuth(WP_USER, WP_PASS)
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


# =========================
# SAFE REQUEST WRAPPER
# =========================
def wp_get(path: str, params: Optional[dict] = None):
    url = f"{WP_BASE}{path}"
    headers = {
        "Accept": "application/json"
    }
    r = requests.get(
        url,
        params=params or {},
        headers=headers,
        auth=auth,
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


def wp_get_list(path: str, params: Optional[dict] = None):
    # 415 FIX: 반드시 GET + params만 사용
    return wp_get(path, params)


def wp_post(path: str, payload: dict):
    url = f"{WP_BASE}{path}"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    r = requests.post(
        url,
        json=payload,
        headers=headers,
        auth=auth,
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


def wp_put(path: str, payload: dict):
    url = f"{WP_BASE}{path}"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    # WordPress는 POST로 update 받는 경우 많음
    r = requests.post(
        url,
        json=payload,
        headers=headers,
        auth=auth,
        timeout=TIMEOUT,
    )

    if r.status_code >= 400:
        r = requests.put(
            url,
            json=payload,
            headers=headers,
            auth=auth,
            timeout=TIMEOUT,
        )

    r.raise_for_status()
    return r.json()


# =========================
# CATEGORY FETCH (safe pagination)
# =========================
def wp_get_categories() -> List[dict]:
    cats = []
    page = 1

    while True:
        chunk = wp_get_list(
            "/wp-json/wp/v2/categories",
            params={
                "per_page": 100,
                "page": page
            }
        )

        if not chunk:
            break

        cats.extend(chunk)

        if len(chunk) < 100:
            break

        page += 1

    return cats


# =========================
# MAIN
# =========================
def main():
    cats = wp_get_categories()
    print(f"Categories loaded: {len(cats)}")


if __name__ == "__main__":
    main()
