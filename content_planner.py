"""수집된 VOC에서 화제 키워드 top N을 뽑고,
키워드별 관련 뉴스 검색 + 블로그/카드뉴스 제목 초안을 만든다."""
import re
from collections import Counter

import naver_voc_collector as voc

# Kiwi 인스턴스는 무거우므로 모듈 레벨에서 1회만 생성 (지연 로딩)
_kiwi = None

def _get_kiwi():
    global _kiwi
    if _kiwi is None:
        from kiwipiepy import Kiwi
        _kiwi = Kiwi()
    return _kiwi

# ✅ 키워드 추출 제외 단어
#    - 학부모 화자 시그널(아이·엄마 등)은 거의 모든 글에 들어가서 순위만 차지함
#    - 검색 시드에 이미 들어간 일반 단어(중학생 등)도 마찬가지
# 화자/가족 표현 + 잡토큰: 단독으로도, 명사구의 일부로도 쓰지 않음
# ("아이 수학" 같은 구가 만들어지는 것 방지)
HARD_STOPWORDS = {
    "아이", "아들", "딸", "자녀", "엄마", "아빠", "부모", "학부모", "부모님",
    "애들", "우리", "저희", "육아", "형제", "남매",
    "vs", "및", "관련", "대비",
}

STOPWORDS = {
    # 시드에 이미 포함된 일반 단어
    "중학생", "초등학생", "고등학생", "학생", "중딩", "초딩", "고딩",
    "중학교", "초등학교", "고등학교", "학교", "학년",
    # 글 형식 표현
    "고민", "걱정", "질문", "답변", "조언", "추천", "후기", "정보",
    "생각", "요즘", "진짜", "정말", "너무", "혹시", "궁금", "문의",
    "이야기", "얘기", "글", "내용", "경우", "정도", "때문", "이번",
    "오늘", "내일", "어제", "시간", "하루", "동안", "시작", "마음",
    # 단독으로는 소재가 안 되는 저정보 단어 (명사구의 일부로는 허용됨)
    "중학", "초등", "고등", "준비", "방법", "필요", "문제", "상황",
    "이유", "부분", "가능", "도움", "느낌", "말씀", "정말로",
}

# 명사구(2단어)가 단어 하나보다 콘텐츠 소재로 구체적이므로 순위에 가중치를 줌
BIGRAM_WEIGHT = 1.5

def _noun_chunks(kiwi, text):
    """붙어 있는 명사 토큰을 복합명사로 합쳐 (단어, 시작, 끝) 목록 반환.
    ("레벨"+"테스트" → "레벨테스트"). 'AI' 같은 영문 토큰(SL)도 포함."""
    chunks = []
    chunk, start, end = "", -1, -1
    for token in kiwi.tokenize(text):
        if token.tag in ("NNG", "NNP", "SL"):
            if token.start == end:
                chunk += token.form
            else:
                if chunk:
                    chunks.append((chunk, start, end))
                chunk, start = token.form, token.start
            end = token.start + len(token.form)
        else:
            if chunk:
                chunks.append((chunk, start, end))
            chunk, end = "", -1
    if chunk:
        chunks.append((chunk, start, end))
    return chunks

def extract_top_keywords(rows, top_n=5):
    """수집된 글의 제목+요약에서 명사·명사구를 뽑아 언급 글 수 기준 top N 반환.

    - 같은 글에서 여러 번 나와도 1회로 셈 (한 글이 순위를 왜곡하지 않게)
    - 한 칸 띄어 인접한 명사 쌍은 명사구로도 셈 ("레벨테스트 준비") — 가중치를 줘서
      "준비" 같은 애매한 단독 명사보다 구체적인 구가 상위에 오게 함
    - 이미 뽑힌 키워드를 포함하거나 그 일부인 후보는 건너뜀 (중복 방지)
    반환: [{"키워드", "언급글수", "예시글": [row, ...]}, ...]
    """
    kiwi = _get_kiwi()
    scores = Counter()
    keyword_rows = {}  # 키워드 → 해당 키워드가 나온 글 목록

    for row in rows:
        text = f"{row.get('제목', '')} {row.get('요약', '')}"
        chunks = _noun_chunks(kiwi, text)

        # 화자 표현·잡토큰은 구를 만들기 전에 아예 걸러냄
        chunks = [c for c in chunks if c[0].lower() not in HARD_STOPWORDS]

        terms = set()
        weights = {}
        for word, _, _ in chunks:
            if len(word) >= 2 and word not in STOPWORDS:
                terms.add(word)
                weights[word] = 1.0
        # 한 칸 띄어 인접한 명사 쌍 → 명사구 ("레벨테스트" + "준비" → "레벨테스트 준비")
        for (w1, _, e1), (w2, s2, _) in zip(chunks, chunks[1:]):
            if s2 - e1 == 1 and len(w1) >= 2 and len(w2) >= 2:
                # 두 단어 다 불용어면 구도 애매함 ("준비 방법" 등) → 제외
                if w1 in STOPWORDS and w2 in STOPWORDS:
                    continue
                phrase = f"{w1} {w2}"
                terms.add(phrase)
                weights[phrase] = BIGRAM_WEIGHT

        for term in terms:
            scores[term] += weights[term]
            keyword_rows.setdefault(term, []).append(row)

    # 점수순으로 뽑되, 이미 뽑힌 키워드와 포함 관계인 후보는 건너뜀
    # ("레벨테스트"와 "레벨테스트 준비"가 같이 나오는 것 방지)
    picked = []
    for term, _ in scores.most_common():
        if len(picked) >= top_n:
            break
        if any(term in p or p in term for p in picked):
            continue
        picked.append(term)

    # 예시글은 키워드가 제목에 직접 들어간 글을 앞에 배치
    # (요약에만 스치듯 언급된 글이 대표 예시로 뜨는 것 방지)
    return [
        {
            "키워드": term,
            "언급글수": len(keyword_rows[term]),
            "예시글": sorted(keyword_rows[term], key=lambda r: term not in r.get("제목", "")),
        }
        for term in picked
    ]

# ── 관련 뉴스 검색 + 보도자료 라벨링 ──────────────────────────────

# 보도자료(업체 홍보 기사)에 흔한 표현 — 배제하지 않고 라벨만 붙임
PRESS_RELEASE_KEYWORDS = [
    "출시", "론칭", "런칭", "선보인다", "선보여", "선봬", "오픈",
    "업무협약", "MOU", "협약 체결", "협약을 체결",
    "모집", "개최", "특강", "설명회", "이벤트", "할인", "혜택", "접수",
    "관계자는", "돌파", "수강생", "누적 회원",
]

# "○○에듀, △△ 서비스 출시" 처럼 회사명 주어로 시작하는 제목
PRESS_RELEASE_PATTERNS = [
    r"^[가-힣A-Za-z0-9·&]{2,20},\s",
]

def is_press_release(title, description):
    """보도자료성 기사로 추정되는지 (라벨링용, 필터링 아님)"""
    text = f"{title} {description}"
    if any(kw in text for kw in PRESS_RELEASE_KEYWORDS):
        return True
    return any(re.search(p, title) for p in PRESS_RELEASE_PATTERNS)

# 지역 행정·지자체 소식 판별용 지역명 (전국 단위 소재가 아닌 기사를 목록 뒤로 보냄)
REGION_NAMES = [
    "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
    "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주",
    "수원", "성남", "용인", "고양", "창원", "청주", "천안", "전주", "안산",
    "안양", "김해", "평택", "포항", "구미", "원주", "진주", "춘천", "여수",
    "순천", "목포", "군산", "익산", "경주", "거제", "양산", "아산", "파주",
    "시흥", "김포", "광명", "군포", "오산", "이천", "안성", "의정부",
    "남양주", "화성", "부천", "하남", "구리", "강릉", "충주", "제천",
    "당진", "서산", "논산", "공주", "정읍", "나주", "광양", "상주",
    "안동", "영주", "영천", "밀양", "통영", "사천", "서귀포",
]

def is_regional_news(title):
    """지역명으로 시작하는 지자체·지역 소식인지"""
    return any(title.startswith(region) for region in REGION_NAMES)

def search_news(keyword, display=8):
    """키워드 관련 최신 뉴스 검색 (보도자료 추정 라벨 포함, 지역 소식은 뒤로)"""
    result = voc.search_naver(keyword, "news", display=display, sort="sim")
    if not result or "items" not in result:
        return []
    articles = []
    for item in result["items"]:
        title = voc.clean_html(item.get("title", ""))
        description = voc.clean_html(item.get("description", ""))
        articles.append({
            "제목": title,
            "요약": description,
            "링크": item.get("originallink") or item.get("link", ""),
            "보도자료추정": is_press_release(title, description),
        })
    # 전국 단위 기사 → 지역 소식 → 보도자료 추정 순으로 정렬 (배제는 안 함)
    articles.sort(key=lambda a: (a["보도자료추정"], is_regional_news(a["제목"])))
    return articles

