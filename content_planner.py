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
STOPWORDS = {
    # 화자/가족 표현
    "아이", "아들", "딸", "자녀", "엄마", "아빠", "부모", "학부모", "부모님",
    "애들", "우리", "저희", "육아", "형제", "남매",
    # 시드에 이미 포함된 일반 단어
    "중학생", "초등학생", "고등학생", "학생", "중딩", "초딩", "고딩",
    "중학교", "초등학교", "고등학교", "학교", "학년",
    # 글 형식 표현
    "고민", "걱정", "질문", "답변", "조언", "추천", "후기", "정보",
    "생각", "요즘", "진짜", "정말", "너무", "혹시", "궁금", "문의",
    "이야기", "얘기", "글", "내용", "경우", "정도", "때문", "이번",
    "오늘", "내일", "어제", "시간", "하루", "동안", "시작", "마음",
}

def extract_top_keywords(rows, top_n=5):
    """수집된 글의 제목+요약에서 명사를 뽑아 언급 글 수 기준 top N 반환.

    같은 글에서 여러 번 나와도 1회로 세서(문서 빈도) 한 글이 순위를 왜곡하지 않게 함.
    반환: [{"키워드", "언급글수", "예시글": [row, ...]}, ...]
    """
    kiwi = _get_kiwi()
    counter = Counter()
    keyword_rows = {}  # 키워드 → 해당 키워드가 나온 글 목록

    for row in rows:
        text = f"{row.get('제목', '')} {row.get('요약', '')}"
        nouns = set()
        # 붙어 있는 명사 토큰은 복합명사로 합침 ("레벨" + "테스트" → "레벨테스트")
        chunk = ""
        chunk_end = -1
        for token in kiwi.tokenize(text):
            if token.tag in ("NNG", "NNP"):
                if token.start == chunk_end:
                    chunk += token.form
                else:
                    if len(chunk) >= 2 and chunk not in STOPWORDS:
                        nouns.add(chunk)
                    chunk = token.form
                chunk_end = token.start + len(token.form)
            else:
                if len(chunk) >= 2 and chunk not in STOPWORDS:
                    nouns.add(chunk)
                chunk = ""
                chunk_end = -1
        if len(chunk) >= 2 and chunk not in STOPWORDS:
            nouns.add(chunk)
        for word in nouns:
            counter[word] += 1
            keyword_rows.setdefault(word, []).append(row)

    return [
        {"키워드": word, "언급글수": count, "예시글": keyword_rows[word]}
        for word, count in counter.most_common(top_n)
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

def search_news(keyword, display=8):
    """키워드 관련 최신 뉴스 검색 (보도자료 추정 라벨 포함)"""
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
    return articles

# ── 템플릿 기반 제목 초안 ──────────────────────────────

BLOG_TEMPLATES = [
    "{kw}, 학부모가 가장 많이 묻는 질문 5가지",
    "우리 아이 {kw} 고민, 이렇게 접근해보세요",
    "{kw} 때문에 흔들리는 아이, 부모가 해줄 수 있는 것",
    "{kw}에 대해 학부모들이 자주 하는 오해 3가지",
    "{kw} 앞에 선 부모의 마음, 선배맘은 이렇게 넘겼다",
]

CARDNEWS_TEMPLATES = [
    "{kw} 궁금증 총정리 — 학부모 질문 TOP 5",
    "{kw} 체크리스트: 우리 아이는 지금 어디쯤?",
    "숫자로 보는 {kw} — 요즘 학부모들의 진짜 고민",
    "{kw} 대응 3단계 가이드",
    "선배맘들의 {kw} 조언 모음.zip",
]

def blog_title_ideas(keyword):
    return [t.format(kw=keyword) for t in BLOG_TEMPLATES]

def cardnews_ideas(keyword):
    return [t.format(kw=keyword) for t in CARDNEWS_TEMPLATES]
