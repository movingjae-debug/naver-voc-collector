import os
import urllib.request
import urllib.parse
import json
import pandas as pd
from datetime import datetime

# ✅ 네이버 API 키: 환경변수 또는 config_local.py에서 읽음 (git에 올라가지 않음)
CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")
if not CLIENT_ID or not CLIENT_SECRET:
    try:
        from config_local import CLIENT_ID, CLIENT_SECRET
    except ImportError:
        pass

# ✅ 시드 키워드 (여기서 자동완성으로 검색어를 자동 확장함)
SEED_KEYWORDS = [
    "중학생 사춘기",    # L4 - 사춘기 관계
    "중학생 게임",      # L4 - 폰/게임 갈등
    "중학생 방학",      # L4 - 방학
    "AI 교육",          # L2 - AI시대 자녀교육
    "중학생 진로",      # L2 - 진로 탐색자
    "공부 동기부여",    # L1 - 핵심타깃(동기부여)
    "중학생 유학",      # L1 - 국제학교·유학 고민
    "고교학점제",       # L1/L2 - 고교학점제
]

# 시드당 자동완성 키워드 최대 몇 개까지 가져올지
MAX_SUGGESTIONS_PER_SEED = 8

def get_suggestions(seed):
    """네이버 자동완성에서 연관 검색어 가져오기 (비공식 API)"""
    params = urllib.parse.urlencode({
        "q": seed, "con": "0", "frm": "nv", "ans": "2",
        "r_format": "json", "r_enc": "UTF-8", "r_unicode": "0",
        "t_koreng": "1", "run": "2", "rev": "4", "q_enc": "UTF-8", "st": "100",
    })
    url = f"https://ac.search.naver.com/nx/ac?{params}"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        response = urllib.request.urlopen(request, timeout=5)
        data = json.loads(response.read().decode("utf-8"))
        suggestions = []
        for group in data.get("items", []):
            for entry in group:
                if entry and entry[0] and entry[0] != seed:
                    suggestions.append(entry[0])
        return suggestions[:MAX_SUGGESTIONS_PER_SEED]
    except Exception as e:
        print(f"  ⚠️ 자동완성 실패 [{seed}]: {e}")
        return []

def build_keywords():
    """시드 키워드 + 자동완성 확장 키워드 목록 생성"""
    keywords = []
    for seed in SEED_KEYWORDS:
        if seed not in keywords:
            keywords.append(seed)
        expanded = get_suggestions(seed)
        for kw in expanded:
            if kw not in keywords:
                keywords.append(kw)
        print(f"🌱 [{seed}] → 확장 {len(expanded)}개: {', '.join(expanded) if expanded else '(없음)'}")
    return keywords

# ✅ 광고성 글 필터링 키워드 (제목/요약/카페명에 포함되면 제외)
AD_KEYWORDS = [
    # 협찬/체험단 표시
    "협찬", "체험단", "서포터즈", "앰버서더", "원고료", "소정의",
    "지원받아", "제공받아", "제공 받아", "무상으로", "파트너스",
    # 홍보/판매성
    "광고", "홍보", "이벤트 참여", "추첨", "경품",
    "할인", "특가", "쿠폰", "프로모션", "런칭", "분양", "입점",
    # 상담/모집 유도 (학원·유학원 광고 글에 흔함)
    "무료 상담", "무료상담", "상담 문의", "상담문의", "설명회",
    "모집중", "모집 중", "선착순", "문의주세요", "문의 주세요",
    "카톡 문의", "전화 문의", "DM 문의",
]

def is_ad(title, description, cafe_name=""):
    """광고성 글 여부 판단"""
    text = f"{title} {description} {cafe_name}"
    return any(kw in text for kw in AD_KEYWORDS)

# ✅ 채널 설정 (끄고 싶은 채널은 False로)
CHANNELS = {
    "카페": True,
    "블로그": True,
    "지식iN": True,
}

# 채널별 API 엔드포인트
ENDPOINTS = {
    "카페": "cafearticle",
    "블로그": "blog",
    "지식iN": "kin",
}

def search_naver(keyword, endpoint, display=100, sort="date"):
    """네이버 검색 API 호출"""
    enc_keyword = urllib.parse.quote(keyword.encode('utf-8'))
    url = f"https://openapi.naver.com/v1/search/{endpoint}?query={enc_keyword}&display={display}&start=1&sort={sort}"

    request = urllib.request.Request(url)
    request.add_header("X-Naver-Client-Id", CLIENT_ID)
    request.add_header("X-Naver-Client-Secret", CLIENT_SECRET)

    try:
        response = urllib.request.urlopen(request)
        if response.getcode() == 200:
            return json.loads(response.read().decode("utf-8"))
    except Exception as e:
        print(f"  ⚠️ 오류 [{keyword} / {endpoint}]: {e}")
    return None

def clean_html(text):
    """HTML 태그 제거"""
    import re
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'")
    return text.strip()

def collect_keyword(keyword, today=None):
    """키워드 하나에 대해 활성화된 채널 전체 수집"""
    if today is None:
        today = datetime.today().strftime("%Y-%m-%d")
    rows = []

    for channel_name, is_active in CHANNELS.items():
        if not is_active:
            continue
        endpoint = ENDPOINTS[channel_name]
        result = search_naver(keyword, endpoint)
        if not result or "items" not in result:
            continue

        items = result["items"]
        ad_count = 0

        for item in items:
            title = clean_html(item.get("title", ""))
            description = clean_html(item.get("description", ""))
            link = item.get("link", "") or item.get("bloggerlink", "")
            cafe_name = item.get("cafename", "")  # 카페 전용

            if is_ad(title, description, cafe_name):
                ad_count += 1
                continue

            rows.append({
                "수집일": today,
                "채널": channel_name,
                "검색키워드": keyword,
                "제목": title,
                "요약": description,
                "카페명": cafe_name,
                "링크": link,
                "콘텐츠화가능성": "",   # 나중에 수동 입력
                "이면의심리": "",        # AI 분석 후 입력
                "메모": "",
            })

        print(f"  → {channel_name}: {len(items) - ad_count}건 수집 (광고성 {ad_count}건 제외)")

    return rows

def collect_all(keywords):
    all_rows = []
    today = datetime.today().strftime("%Y-%m-%d")

    for keyword in keywords:
        print(f"\n🔍 키워드: [{keyword}]")
        all_rows.extend(collect_keyword(keyword, today))

    return all_rows

if __name__ == "__main__":
    print("=" * 50)
    print("🚀 아틀라스 VOC 수집 시작")
    print("=" * 50)

    print("\n📌 시드 키워드 자동 확장 중...")
    keywords = build_keywords()
    print(f"\n📌 총 {len(keywords)}개 키워드로 수집 시작 (시드 {len(SEED_KEYWORDS)}개 + 확장)")

    rows = collect_all(keywords)

    if not rows:
        print("\n❌ 수집된 데이터가 없습니다. Client ID/Secret을 확인해주세요.")
    else:
        df = pd.DataFrame(rows)
        filename = f"VOC수집_{datetime.today().strftime('%Y%m%d_%H%M')}.xlsx"
        df.to_excel(filename, index=False)
        print(f"\n✅ 완료! {len(rows)}건 수집 → [{filename}] 저장됨")
        print(f"   파일 위치: 스크립트와 같은 폴더")
