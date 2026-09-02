import io
from datetime import datetime

import pandas as pd
import streamlit as st

import naver_voc_collector as voc
import content_planner as planner

# Streamlit Cloud 배포 시 secrets에서 API 키 읽기 (로컬은 config_local.py 사용)
try:
    if "NAVER_CLIENT_ID" in st.secrets:
        voc.CLIENT_ID = st.secrets["NAVER_CLIENT_ID"]
        voc.CLIENT_SECRET = st.secrets["NAVER_CLIENT_SECRET"]
except FileNotFoundError:
    pass

st.set_page_config(page_title="타겟 인사이트 수집기", page_icon="🔍", layout="wide")
st.title("🔍 타겟 인사이트 수집기")
st.caption("네이버 카페·블로그·지식iN에서 학부모들의 실제 목소리를 수집합니다. 시드 키워드는 자동완성으로 확장됩니다.")

# ── 사이드바: 수집 설정 ──────────────────────────────
with st.sidebar:
    st.header("⚙️ 수집 설정")

    seeds_text = st.text_area(
        "시드 키워드 (한 줄에 하나)",
        value="\n".join(voc.SEED_KEYWORDS),
        height=250,
    )
    seeds = [s.strip() for s in seeds_text.splitlines() if s.strip()]

    season_kws = voc.seasonal_seeds()
    use_seasonal = st.toggle(
        "시즌 키워드 자동 추가", value=True,
        help="교육 연간 일정에 맞는 이달의 키워드를 시드에 자동으로 추가합니다.",
    )
    if use_seasonal and season_kws:
        st.caption(f"📅 이달의 시즌 키워드: {', '.join(season_kws)}")

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

    if use_seasonal:
        seeds += [kw for kw in season_kws if kw not in seeds]

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
    st.session_state.pop("content_plan", None)  # 새 수집이면 이전 분석 결과 무효화

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

    # ── 키워드 분석 & 콘텐츠 초안 ──────────────────────────────
    st.divider()
    st.header("🧩 콘텐츠 소재 분석")
    st.caption(
        "수집된 글에서 자주 언급된 키워드 TOP 5를 뽑고, 키워드별 관련 뉴스와 "
        "블로그/카드뉴스 제목 초안을 만듭니다. 📢 표시는 보도자료로 추정되는 기사입니다."
    )

    if st.button("🔎 TOP 5 키워드 분석 & 초안 생성", use_container_width=True):
        rows = df.to_dict("records")
        with st.status("키워드 추출 중... (첫 실행은 형태소 분석기 로딩으로 수십 초 걸릴 수 있어요)") as status:
            top_keywords = planner.extract_top_keywords(rows, top_n=5)
            plan = []
            for entry in top_keywords:
                kw = entry["키워드"]
                status.update(label=f"관련 뉴스 검색 중... [{kw}]")
                news = planner.search_news(kw)
                plan.append({
                    **entry,
                    "뉴스": news,
                    "블로그초안": planner.blog_idea_drafts(kw, entry["예시글"], news),
                    "카드뉴스초안": planner.cardnews_idea_drafts(kw, entry["예시글"], news),
                })
            status.update(label="✅ 분석 완료", state="complete")
        st.session_state["content_plan"] = plan

    for i, entry in enumerate(st.session_state.get("content_plan", []), start=1):
        kw = entry["키워드"]
        with st.expander(f"**{i}위. {kw}** — {entry['언급글수']}건의 글에서 언급", expanded=(i == 1)):
            st.markdown("##### 💬 학부모들은 이렇게 말해요")
            for row in entry["예시글"][:5]:
                link = row.get("링크", "")
                title = row.get("제목", "")
                channel = row.get("채널", "")
                if link:
                    st.markdown(f"- [{title}]({link}) `{channel}`")
                else:
                    st.markdown(f"- {title} `{channel}`")

            st.markdown("##### 📰 관련 뉴스")
            if entry["뉴스"]:
                for article in entry["뉴스"]:
                    label = " 📢 `보도자료 추정`" if article["보도자료추정"] else ""
                    st.markdown(f"- [{article['제목']}]({article['링크']}){label}")
            else:
                st.markdown("_관련 뉴스를 찾지 못했습니다._")

            col_blog, col_card = st.columns(2)
            with col_blog:
                st.markdown("##### ✍️ 블로그 제목 초안")
                for t in entry["블로그초안"]:
                    st.markdown(f"- {t}")
            with col_card:
                st.markdown("##### 🃏 카드뉴스 주제 초안")
                for t in entry["카드뉴스초안"]:
                    st.markdown(f"- {t}")
