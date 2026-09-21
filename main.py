import streamlit as st
import requests
from datetime import datetime, timedelta, timezone
import pandas as pd

# ────────────────────────────────────────────────────────────
# 초보자를 위한 설명
# 이 앱은 영화진흥위원회(KOBIS)의 "일별 박스오피스" 공개 API를 호출해서
# 사용자가 달력에서 고른 날짜의 박스오피스 순위를 스트림릿 화면에 보여주는 앱입니다.
# ────────────────────────────────────────────────────────────

st.set_page_config(page_title="박스오피스 조회", page_icon="🎬", layout="wide")

# ── 1. 한국 시간(KST) 기준으로 "오늘"과 "어제" 날짜 계산하기 ────
# 스트림릿 클라우드 서버는 한국 시간이 아닐 수 있으므로,
# UTC 시각을 직접 한국 시간(UTC+9)으로 변환해서 씁니다.
# 오늘 건 아직 집계 전이므로, 달력에서 고를 수 있는 가장 늦은 날짜는 "어제"까지로 제한합니다.
KST = timezone(timedelta(hours=9))


def get_today_kst_date():
    return datetime.now(timezone.utc).astimezone(KST).date()


def get_yesterday_kst_date():
    return get_today_kst_date() - timedelta(days=1)


# ── 2. KOBIS API 호출 함수 ─────────────────────────────────────
# st.cache_data(ttl=3600)을 붙이면, 같은 target_dt로 한 시간(3600초) 안에
# 다시 요청이 오더라도 API를 또 부르지 않고 저장해둔 결과를 그대로 돌려줍니다.
@st.cache_data(ttl=3600)
def fetch_box_office(target_dt: str) -> dict:
    """
    KOBIS 일별 박스오피스 API를 호출합니다.
    성공하면 {"ok": True, "movies": [...]} 형태로,
    실패하면 {"ok": False, "reason": "사람이 읽을 수 있는 안내 문구"} 형태로 돌려줍니다.
    """
    url = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"

    # 인증키는 코드에 직접 적지 않고, 스트림릿 비밀 금고(secrets)에서 불러옵니다.
    # 스트림릿 클라우드 배포 시 "Settings > Secrets"에 KOBIS_KEY = "발급받은키" 형태로 등록해야 합니다.
    try:
        api_key = st.secrets["KOBIS_KEY"]
    except Exception:
        return {
            "ok": False,
            "reason": (
                "인증키(KOBIS_KEY)를 찾을 수 없습니다. "
                "스트림릿 클라우드의 Settings > Secrets에 KOBIS_KEY 값이 등록되어 있는지 확인해 주세요."
            ),
        }

    params = {"key": api_key, "targetDt": target_dt}

    # 네트워크 요청 자체가 실패하는 경우 (타임아웃, 인터넷 연결 문제 등)
    try:
        response = requests.get(url, params=params, timeout=10)
    except requests.exceptions.RequestException:
        return {
            "ok": False,
            "reason": (
                "KOBIS 서버에 요청을 보내는 데 실패했습니다. "
                "인터넷 연결 상태나 KOBIS 서버 상태를 확인해 주세요."
            ),
        }

    # HTTP 상태 코드가 200이 아닌 경우
    if response.status_code != 200:
        return {
            "ok": False,
            "reason": f"KOBIS 서버가 오류 응답(상태코드 {response.status_code})을 보냈습니다. 잠시 후 다시 시도해 주세요.",
        }

    # 응답이 JSON 형태가 아닌 경우 (예: HTML 에러 페이지가 온 경우)
    try:
        data = response.json()
    except ValueError:
        return {
            "ok": False,
            "reason": "KOBIS 서버 응답을 해석할 수 없습니다(JSON 형식이 아님). 요청 주소나 API 상태를 확인해 주세요.",
        }

    # 인증키가 틀려도 상태코드는 200이고, 대신 faultInfo 상자가 옵니다.
    if "faultInfo" in data:
        message = data["faultInfo"].get("message", "알 수 없는 오류")
        return {
            "ok": False,
            "reason": (
                f"KOBIS API가 오류를 반환했습니다: {message}\n"
                "인증키(KOBIS_KEY)가 올바른지, 혹은 요청 변수가 올바른지 확인해 주세요."
            ),
        }

    # 정상적인 경우라면 boxOfficeResult 안에 dailyBoxOfficeList가 있어야 합니다.
    try:
        movies = data["boxOfficeResult"]["dailyBoxOfficeList"]
    except (KeyError, TypeError):
        return {
            "ok": False,
            "reason": "예상한 응답 구조(boxOfficeResult > dailyBoxOfficeList)를 찾을 수 없습니다. API 응답 형식이 바뀌었을 수 있습니다.",
        }

    if not movies:
        # 영화 목록이 비어서 오는 경우는 "아직 집계 전"이라는 뜻일 가능성이 가장 크므로
        # reason_type을 따로 구분해서, 화면에서 전용 안내 문구를 보여줄 수 있게 합니다.
        return {
            "ok": False,
            "reason_type": "empty",
            "reason": "그날은 아직 집계 전입니다.",
        }

    return {"ok": True, "movies": movies}


# ── 3. 문자열 숫자를 진짜 숫자(int)로 바꾸기 ───────────────────
def to_int(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


# ── 3-1. 순위 증감(rankInten)을 화살표 문자열로 바꾸기 ──────────
def rank_change_display(value: str) -> str:
    n = to_int(value)
    if n > 0:
        return f"▲{n}"
    elif n < 0:
        return f"▼{abs(n)}"
    else:
        return "-"


def rank_change_color(text: str) -> str:
    # pandas Styler에 넘길 CSS 문자열입니다.
    if text.startswith("▲"):
        return "color: red"
    elif text.startswith("▼"):
        return "color: blue"
    return ""


# ── 4. 화면 그리기 ─────────────────────────────────────────────
st.title("🎬 박스오피스 조회")

today_kst = get_today_kst_date()
yesterday_kst = get_yesterday_kst_date()

selected_date = st.date_input(
    "조회할 날짜를 선택하세요 (오늘 건 아직 집계 전이라 어제까지만 고를 수 있어요)",
    value=yesterday_kst,
    max_value=yesterday_kst,
)

target_dt = selected_date.strftime("%Y%m%d")
target_dt_display = f"{target_dt[:4]}년 {target_dt[4:6]}월 {target_dt[6:]}일"
st.caption(f"기준 날짜: {target_dt_display}")

# ── 진단용 패널 ──────────────────────────────────────────────
# 날짜를 바꿔도 결과가 똑같아 보일 때, 실제로 어떤 날짜로 요청했는지와
# 캐시를 강제로 비우고 다시 불러온 결과를 비교해 볼 수 있게 해 줍니다.
with st.expander("🔧 문제 진단 (날짜를 바꿔도 결과가 같을 때 눌러보세요)"):
    st.write(f"실제로 API에 보낸 target_dt 값: `{target_dt}`")
    st.write("이 값이 날짜를 바꿀 때마다 다르게 보인다면, 캐시나 코드 문제가 아니라 "
             "① 인증키가 예시/테스트 키이거나, ② 그날 실제로 박스오피스가 동일한 경우일 가능성이 높습니다.")
    if st.button("이 날짜의 캐시를 지우고 API 다시 호출하기"):
        fetch_box_office.clear()
        st.rerun()

result = fetch_box_office(target_dt)

if not result["ok"]:
    # 영화 목록이 비어서 온 경우(아직 집계 전)와, 그 외 오류를 구분해서 안내합니다.
    if result.get("reason_type") == "empty":
        st.info(result["reason"])
    else:
        st.error(result["reason"])
else:
    movies = result["movies"]

    # API가 원래 순위대로 정렬해서 주지만, 안전하게 우리도 숫자 기준으로 다시 정렬합니다.
    for m in movies:
        m["rank_num"] = to_int(m.get("rank"))
        m["audiCnt_num"] = to_int(m.get("audiCnt"))
        m["audiAcc_num"] = to_int(m.get("audiAcc"))
        m["scrnCnt_num"] = to_int(m.get("scrnCnt"))
        # 누적관객이 100만 명을 넘으면 영화명 옆에 트로피 이모지를 붙입니다.
        display_name = m.get("movieNm", "-")
        if m["audiAcc_num"] >= 1_000_000:
            display_name = f"{display_name} 🏆"
        m["movieNm_display"] = display_name

    movies_sorted = sorted(movies, key=lambda m: m["rank_num"])

    # ── 4-1. 1위 영화 지표 카드 3장 ──
    top_movie = movies_sorted[0]
    st.subheader(f"🥇 1위: {top_movie['movieNm_display']}")

    col1, col2, col3 = st.columns(3)
    col1.metric("오늘 관객수", f"{top_movie['audiCnt_num']:,}명")
    col2.metric("누적 관객수", f"{top_movie['audiAcc_num']:,}명")
    col3.metric("스크린수", f"{top_movie['scrnCnt_num']:,}개")

    st.divider()

    # ── 4-2. 전체 표 ──
    st.subheader("📋 전체 순위표")
    df = pd.DataFrame(
        [
            {
                "순위": m["rank_num"],
                "순위변동": rank_change_display(m.get("rankInten")),
                "영화명": m["movieNm_display"],
                "개봉일": m.get("openDt", "-"),
                "관객수": m["audiCnt_num"],
                "누적관객": m["audiAcc_num"],
                "스크린수": m["scrnCnt_num"],
            }
            for m in movies_sorted
        ]
    )
    # 순위변동 글자에 색을 입히기 위해 pandas Styler를 사용합니다.
    # (▲ 오름: 빨간색, ▼ 내림: 파란색)
    styled_df = (
        df.style.map(rank_change_color, subset=["순위변동"])
        .format({"관객수": "{:,}", "누적관객": "{:,}", "스크린수": "{:,}"})
    )
    st.dataframe(styled_df, use_container_width=True, hide_index=True)

    st.divider()

    # ── 4-3. 관객수 상위 5편 막대그래프 ──
    st.subheader("📊 관객수 상위 5편")
    top5 = sorted(movies_sorted, key=lambda m: m["audiCnt_num"], reverse=True)[:5]
    chart_df = pd.DataFrame(
        {m["movieNm_display"]: [m["audiCnt_num"]] for m in top5}
    ).T
    chart_df.columns = ["관객수"]
    st.bar_chart(chart_df)
