import io
from datetime import datetime

import pandas as pd
import streamlit as st

import naver_voc_collector as voc

# Streamlit Cloud 배포 시 secrets에서 API 키 읽기 (로컬은 config_local.py 사용)
try:
    if "NAVER_CLIENT_ID" in st.secrets:
        voc.CLIENT_ID = st.secrets["NAVER_CLIENT_ID"]
        voc.CLIENT_SECRET = st.secrets["NAVER_CLIENT_SECRET"]
except FileNotFoundError:
    pass

st.set_page_config(page_title="아틀라스 VOC 수집기", page_icon="🔍", layout="wide")
st.title("🔍 아틀라스 VOC 수집기")
st.caption("네이버 카페·블로그·지식iN에서 학부모 VOC를 수집합니다. 시드 키워드는 자동완성으로 확장됩니다.")

# ── 사이드바: 수집 설정 ──────────────────────────────
with st.sidebar:
    st.header("⚙️ 수집 설정")

    seeds_text = st.text_area(
        "시드 키워드 (한 줄에 하나)",
        value="\n".join(voc.SEED_KEYWORDS),
        height=250,
    )
    seeds = [s.strip() for s in seeds_text.splitlines() if s.strip()]

    expand = st.toggle("자동완성으로 키워드 확장", value=True)
    max_sug = st.slider("시드당 확장 키워드 수", 0, 15, voc.MAX_SUGGESTIONS_PER_SEED)

    st.subheader("필터")
    parent_filter = st.toggle(
        "학부모 글만 수집", value=True,
        help="제목/요약에 '아들·딸·자녀·우리 아이' 같은 학부모 표현이 있는 글만 남깁니다.",
    )
    display_per_channel = st.slider("채널당 수집 건수", 10, 100, voc.DISPLAY_PER_CHANNEL, step=10)

    st.subheader("채널")
    channels = {}
    for name in voc.CHANNELS:
        channels[name] = st.checkbox(name, value=True)

# ── 수집 실행 ──────────────────────────────
if st.button("🚀 수집 시작", type="primary", use_container_width=True):
    if not voc.CLIENT_ID or not voc.CLIENT_SECRET:
        st.error("네이버 API 키가 설정되지 않았습니다. Streamlit secrets 또는 config_local.py를 확인해주세요.")
        st.stop()
    if not seeds:
        st.error("시드 키워드를 1개 이상 입력해주세요.")
        st.stop()

    voc.CHANNELS.update(channels)
    voc.MAX_SUGGESTIONS_PER_SEED = max_sug
    voc.PARENT_FILTER = parent_filter
    voc.DISPLAY_PER_CHANNEL = display_per_channel

    # 1) 키워드 확장
    with st.status("🌱 키워드 확장 중...", expanded=True) as status:
        keywords = []
        for seed in seeds:
            if seed not in keywords:
                keywords.append(seed)
            if expand and max_sug > 0:
                expanded = voc.get_suggestions(seed)
                new = [kw for kw in expanded if kw not in keywords]
                keywords.extend(new)
                st.write(f"**{seed}** → {', '.join(new) if new else '(확장 없음)'}")
        status.update(label=f"🌱 키워드 확장 완료: 총 {len(keywords)}개", state="complete")

    # 2) 키워드별 수집
    progress = st.progress(0.0, text="수집 준비 중...")
    today = datetime.today().strftime("%Y-%m-%d")
    all_rows = []
    for i, kw in enumerate(keywords):
        progress.progress((i + 1) / len(keywords), text=f"수집 중... [{kw}] ({i + 1}/{len(keywords)})")
        all_rows.extend(voc.collect_keyword(kw, today))
    progress.empty()

    deduped = voc.dedupe_rows(all_rows)
    if len(deduped) < len(all_rows):
        st.info(f"🔁 중복 제거: 같은 글 {len(all_rows) - len(deduped)}건을 제외했습니다.")
    all_rows = deduped

    if not all_rows:
        st.warning("수집된 데이터가 없습니다. API 키와 키워드를 확인해주세요.")
        st.stop()

    df = pd.DataFrame(all_rows)
    st.session_state["voc_df"] = df

# ── 결과 표시 ──────────────────────────────
if "voc_df" in st.session_state:
    df = st.session_state["voc_df"]

    st.success(f"✅ 총 {len(df)}건 수집 완료")
    col1, col2, col3 = st.columns(3)
    col1.metric("총 수집 건수", f"{len(df):,}건")
    col2.metric("키워드 수", df["검색키워드"].nunique())
    col3.metric("채널 수", df["채널"].nunique())

    st.dataframe(df, use_container_width=True, height=500)

    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    st.download_button(
        "📥 엑셀 다운로드",
        data=buf.getvalue(),
        file_name=f"VOC수집_{datetime.today().strftime('%Y%m%d_%H%M')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
