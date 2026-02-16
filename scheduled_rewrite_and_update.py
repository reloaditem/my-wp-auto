import os
import re
import time
import requests
from datetime import datetime
from typing import List, Dict, Any
from requests.auth import HTTPBasicAuth
from openai import OpenAI

# ==============================
# ENV
# ==============================
WP_BASE = os.environ.get("WP_BASE", "https://reloaditem.com")
WP_USER = os.environ.get("WP_USER")
WP_PASS = os.environ.get("WP_PASS")

OPENAI_KEY = os.environ.get("OPENAI_API_KEY")
MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

TOP_N = int(os.environ.get("TOP_N", "3"))  # 기본 3개
DRY_RUN = os.environ.get("DRY_RUN", "true").lower() == "true"  # 기본 true(미리보기)
BACKUP_DIR = os.environ.get("BACKUP_DIR", "scheduled_backups_before_rewrite")
SLEEP_SECONDS = float(os.environ.get("SLEEP_SECONDS", "1.0"))

client = OpenAI(api_key=OPENAI_KEY)
WP_POSTS = f"{WP_BASE}/wp-json/wp/v2/posts"

# ==============================
# Utils
# ==============================
def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)

def slugify(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9\-]+", "-", s).strip("-")[:80] or "post"

def strip_code_fences(html: str) -> str:
    html = re.sub(r"^```[a-zA-Z]*\s*", "", html.strip())
    html = re.sub(r"\s*```$", "", html.strip())
    return html.strip()

def wp_get_future_posts(per_page: int = 100) -> List[Dict[str, Any]]:
    url = f"{WP_POSTS}?status=future&per_page={per_page}&orderby=date&order=asc"
    r = requests.get(url, auth=HTTPBasicAuth(WP_USER, WP_PASS), timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"WP GET failed: {r.status_code} {r.text[:200]}")
    return r.json()

def wp_update_post(post_id: int, new_html: str) -> None:
    # WP는 보통 POST /posts/{id} 로 업데이트 가능
    url = f"{WP_POSTS}/{post_id}"
    payload = {"content": new_html}
    r = requests.post(url, json=payload, auth=HTTPBasicAuth(WP_USER, WP_PASS), timeout=30)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"WP UPDATE failed: {r.status_code} {r.text[:200]}")

# ==============================
# PartnerStack approval-safe rewrite prompt
# ==============================
PARTNERSTACK_SYSTEM = """
You are editing articles for an affiliate marketing site that wants to be approved by PartnerStack and similar networks.
Your goal is to make the article look like a genuine, helpful buyer’s guide — not mass-generated affiliate content.

NON-NEGOTIABLE RULES
- Output ONLY clean HTML. No markdown, no backticks, no commentary.
- Keep the existing structure and all major HTML elements (H2/H3, lists, tables). Do not break tables.
- Keep [IMAGE1] and [IMAGE2] placeholders if they exist. Never remove them.
- Remove hype and absolutes: “guaranteed”, “best ever”, “instant”, “100%”, “perfect”, “no risk”, “secret trick”.
- Do NOT invent facts. If something is uncertain (pricing, limits, features), use cautious language:
  “Pricing varies by plan; check the vendor’s pricing page for the latest details.”
- Avoid aggressive competitor bashing.

PARTNERSTACK APPROVAL SIGNALS (MUST ADD / ENSURE)
Ensure these sections exist as H2 headings, with practical and specific content:
1) <h2>Who this is for (and who it’s not)</h2>
   - Include “Who this is NOT for” bullets (at least 4).
2) <h2>How we evaluate tools</h2>
   - Clear criteria: usability, SMB fit, integrations, support, transparency, pricing clarity.
   - Mention “we review public documentation + hands-on evaluation when possible”.
3) <h2>Disclosure</h2>
   - Short, plain statement: “We may earn a commission… It doesn’t affect our editorial process.”
4) <h2>Practical setup tips (first 30 days)</h2>
   - Concrete steps; avoid fluff.

CONTENT STYLE GUIDELINES
- Use a neutral, evidence-aware tone.
- Add realistic trade-offs and limitations.
- Prefer “recommendations by scenario” rather than “this is the best for everyone”.
- If you mention prices, avoid exact numbers unless already in the original; even then add “may change”.

OUTPUT REQUIREMENTS
- Keep length at least similar to original.
- Keep one comparison table (HTML <table>) if present; if missing, create one.
- End with a short “Next steps” paragraph encouraging checking product pages and starting with a trial.
""".strip()

def rewrite_html_partnerstack(title: str, html: str) -> str:
    user = f"""
TITLE: {title}

Rewrite the following HTML to be more neutral, evidence-conscious, and approval-safe for PartnerStack.

HTML:
{html}
""".strip()

    resp = client.chat.completions.create(
        model=MODEL,
        temperature=0.4,
        messages=[
            {"role": "system", "content": PARTNERSTACK_SYSTEM},
            {"role": "user", "content": user},
        ],
    )
    out = strip_code_fences(resp.choices[0].message.content)

    # Placeholder 보호 (원문에 있었는데 사라지면 복구)
    if "[IMAGE1]" in html and "[IMAGE1]" not in out:
        out = out.replace("</p>", " [IMAGE1]</p>", 1) if "</p>" in out else "[IMAGE1]\n" + out
    if "[IMAGE2]" in html and "[IMAGE2]" not in out:
        out = out + "\n<p>[IMAGE2]</p>"

    return out

def main():
    if not (WP_USER and WP_PASS and OPENAI_KEY):
        raise RuntimeError("Missing env: WP_USER / WP_PASS / OPENAI_API_KEY")

    posts = wp_get_future_posts()
    if not posts:
        print("No scheduled (future) posts found.")
        return

    # 날짜 빠른 순
    posts.sort(key=lambda p: datetime.fromisoformat(p["date"]))
    target = posts[:TOP_N]

    print(f"Found {len(posts)} future posts. Targeting earliest {len(target)}.")
    print(f"MODEL={MODEL} | DRY_RUN={DRY_RUN} | TOP_N={TOP_N}")

    ensure_dir(BACKUP_DIR)

    for p in target:
        post_id = p["id"]
        title = p["title"]["rendered"]
        date = p["date"]
        link = p.get("link", "")
        html = p.get("content", {}).get("rendered", "")

        if not html.strip():
            print(f"[SKIP] empty content: {post_id} {title}")
            continue

        # 원본 백업
        base = f"{BACKUP_DIR}/{date[:10]}_{post_id}_{slugify(title)}"
        orig_fn = base + "_ORIGINAL.html"
        with open(orig_fn, "w", encoding="utf-8") as f:
            f.write(html)

        print(f"\n=== {date} | ID {post_id} ===")
        print(f"Title: {title}")
        print(f"Link:  {link}")
        print(f"Backup: {orig_fn}")

        # 리라이트
        new_html = rewrite_html_partnerstack(title, html)

        # 안전 체크(헤딩/HTML 최소 조건)
        low = new_html.lower()
        if "<h2" not in low:
            print("[WARN] No <h2> found after rewrite. Skipping update for safety.")
            continue
        if "<html" in low or "<body" in low:
            print("[WARN] Full document wrapper detected. Skipping update for safety.")
            continue

        if DRY_RUN:
            preview_fn = base + "_REWRITTEN_PREVIEW.html"
            with open(preview_fn, "w", encoding="utf-8") as f:
                f.write(new_html)
            print(f"[DRY_RUN] Preview saved: {preview_fn}")
        else:
            wp_update_post(post_id, new_html)
            print("[UPDATED] WordPress post updated.")

        time.sleep(SLEEP_SECONDS)

    print("\nDone.")

if __name__ == "__main__":
    main()
