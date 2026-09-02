import os
import re
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

# ✅ 월별 시즌 키워드 (교육 연간 일정 기반, 수집 시점의 달에 맞춰 시드에 자동 추가)
SEASONAL_KEYWORDS = {
    1: ["겨울방학 계획", "예비중1", "예비고1"],
    2: ["신학기 준비", "예비중1 공부"],
    3: ["새학기 적응", "3월 학력평가"],
    4: ["1학기 중간고사", "수행평가"],
    5: ["중간고사 성적", "수행평가"],
    6: ["6월 모의고사", "기말고사 준비"],
    7: ["기말고사 성적", "여름방학 계획"],
    8: ["여름방학 공부", "2학기 준비"],
    9: ["9월 모의고사", "2학기 중간고사"],
    10: ["2학기 중간고사", "진로 체험"],
    11: ["수능", "기말고사 준비"],
    12: ["겨울방학 계획", "예비중1"],
}

# 시즌 키워드 자동 추가 여부 (Streamlit 사이드바에서 토글)
USE_SEASONAL = True

def seasonal_seeds(month=None):
    """수집 시점의 달에 해당하는 시즌 키워드 반환"""
    if month is None:
        month = datetime.today().month
    return SEASONAL_KEYWORDS.get(month, [])

# 시드당 자동완성 키워드 최대 몇 개까지 가져올지
MAX_SUGGESTIONS_PER_SEED = 8

# 채널당 수집 건수 (최대 100)
DISPLAY_PER_CHANNEL = 50

# ✅ 확장 키워드 차단 목록 (학부모 VOC와 무관한 자동완성 검색어 제외)
EXPANSION_BLOCKLIST = [
    # 감성/정보성 검색어
    "배경", "노래", "명언", "문구", "글귀", "짤", "뜻", "순위",
    "종류", "사이트", "폐지", "등급", "기간", "pc",
    # 성인/직업훈련
    "국비", "자격증", "부트캠프",
    # 지역명 (지역 학원·과외 광고 글로 이어짐)
    "서울", "부산", "대구", "대전", "인천", "광주", "울산", "세종",
    "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주",
]

def is_blocked_suggestion(keyword):
    """확장 키워드가 차단 목록에 걸리는지"""
    kw = keyword.lower()
    return any(b.lower() in kw for b in EXPANSION_BLOCKLIST)

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
                if entry and entry[0] and entry[0] != seed and not is_blocked_suggestion(entry[0]):
                    suggestions.append(entry[0])
        return suggestions[:MAX_SUGGESTIONS_PER_SEED]
    except Exception as e:
        print(f"  ⚠️ 자동완성 실패 [{seed}]: {e}")
        return []

def build_keywords():
    """시드 키워드 (+ 시즌 키워드) + 자동완성 확장 키워드 목록 생성"""
    seeds = list(SEED_KEYWORDS)
    if USE_SEASONAL:
        season = [kw for kw in seasonal_seeds() if kw not in seeds]
        if season:
            print(f"📅 시즌 키워드 추가 ({datetime.today().month}월): {', '.join(season)}")
        seeds += season
    keywords = []
    for seed in seeds:
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
    "모집", "선착순", "문의주세요", "문의 주세요",
    "카톡 문의", "전화 문의", "DM 문의",
    # 업체·서비스 홍보
    "유학원", "컨설팅", "부트캠프", "원데이클래스",
    "내일배움카드", "국비지원", "자격증", "수강",
    "과외",  # 실측 결과 '과외' 포함 글은 전부 지역 과외 홍보글이었음
]

# 정규식 기반 광고 패턴
AD_PATTERNS = [
    # "영덕동 고등학생 영어과외", "좌동 영어학원" 같은 지역명+과외/학원 홍보글
    r"[가-힣]{1,6}[동읍면역구]\s?[가-힣A-Za-z ]{0,15}(과외|학원|교습소)",
]

def is_ad(title, description, cafe_name=""):
    """광고성 글 여부 판단"""
    text = f"{title} {description} {cafe_name}"
    if any(kw in text for kw in AD_KEYWORDS):
        return True
    return any(re.search(p, text) for p in AD_PATTERNS)

# ✅ 학부모 화자 필터: 제목/요약에 아래 시그널이 하나라도 있어야 수집
#    (학생 본인 글, 무관한 정보성 글을 걸러냄. 끄려면 False)
PARENT_FILTER = True
PARENT_SIGNALS = [
    "아들", "딸", "자녀", "학부모", "엄마", "아빠", "부모",
    "우리 아이", "우리아이", "우리애", "울애", "애가", "애를", "애한테", "애들",
    "아이가", "아이를", "아이한테", "아이랑", "아이와", "아이에게",
    "중딩맘", "맘님", "육아",
]

def is_parent_voice(title, description):
    """학부모가 쓴 글로 보이는지 판단"""
    text = f"{title} {description}"
    return any(sig in text for sig in PARENT_SIGNALS)

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

def search_naver(keyword, endpoint, display=None, sort="date"):
    """네이버 검색 API 호출"""
    if display is None:
        display = DISPLAY_PER_CHANNEL
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
        non_parent_count = 0

        for item in items:
            title = clean_html(item.get("title", ""))
            description = clean_html(item.get("description", ""))
            link = item.get("link", "") or item.get("bloggerlink", "")
            cafe_name = item.get("cafename", "")  # 카페 전용

            # 작성일 (블로그 API만 제공, YYYYMMDD 형식)
            postdate = item.get("postdate", "")
            if len(postdate) == 8:
                postdate = f"{postdate[:4]}-{postdate[4:6]}-{postdate[6:]}"

            if is_ad(title, description, cafe_name):
                ad_count += 1
                continue

            if PARENT_FILTER and not is_parent_voice(title, description):
                non_parent_count += 1
                continue

            rows.append({
                "수집일": today,
                "작성일": postdate,
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

        kept = len(items) - ad_count - non_parent_count
        print(f"  → {channel_name}: {kept}건 수집 (광고 {ad_count}건·비학부모 {non_parent_count}건 제외)")

    return rows

def dedupe_rows(rows):
    """같은 링크의 글은 한 번만 남김 (여러 키워드에 걸린 중복 제거)"""
    seen = set()
    out = []
    for r in rows:
        link = r.get("링크", "")
        if link and link in seen:
            continue
        seen.add(link)
        out.append(r)
    return out

def collect_all(keywords):
    all_rows = []
    today = datetime.today().strftime("%Y-%m-%d")

    for keyword in keywords:
        print(f"\n🔍 키워드: [{keyword}]")
        all_rows.extend(collect_keyword(keyword, today))

    deduped = dedupe_rows(all_rows)
    removed = len(all_rows) - len(deduped)
    if removed:
        print(f"\n🔁 중복 제거: {removed}건 (키워드 여러 개에 걸린 같은 글)")

    return deduped

if __name__ == "__main__":
    print("=" * 50)
    print("🚀 타겟 인사이트 수집 시작")
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
