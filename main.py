import streamlit as st
import requests
from datetime import datetime, timedelta, timezone
import pandas as pd

# ────────────────────────────────────────────────────────────
# 초보자를 위한 설명
# 이 앱은 영화진흥위원회(KOBIS)의 "일별 박스오피스" 공개 API를 호출해서
# 어제 하루 동안의 박스오피스 순위를 스트림릿 화면에 보여주는 앱입니다.
# ────────────────────────────────────────────────────────────

st.set_page_config(page_title="어제의 박스오피스", page_icon="🎬", layout="wide")

# ── 1. 한국 시간(KST) 기준으로 "어제" 날짜 계산하기 ─────────────
# 스트림릿 클라우드 서버는 한국 시간이 아닐 수 있으므로,
# UTC 시각을 직접 한국 시간(UTC+9)으로 변환한 뒤 하루를 빼서 "어제"를 구합니다.
KST = timezone(timedelta(hours=9))


def get_yesterday_yyyymmdd() -> str:
    now_kst = datetime.now(timezone.utc).astimezone(KST)
    yesterday_kst = now_kst - timedelta(days=1)
    return yesterday_kst.strftime("%Y%m%d")


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
    url = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json?key=1faba8bb9be3b7bd55bde485aae12685&targetDt=20260920"

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
        return {
            "ok": False,
            "reason": (
                f"{target_dt} 날짜의 박스오피스 영화 목록이 비어 있습니다. "
                "해당 날짜의 집계가 아직 완료되지 않았을 수 있습니다."
            ),
        }

    return {"ok": True, "movies": movies}


# ── 3. 문자열 숫자를 진짜 숫자(int)로 바꾸기 ───────────────────
def to_int(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


# ── 4. 화면 그리기 ─────────────────────────────────────────────
st.title("🎬 어제의 박스오피스")

target_dt = get_yesterday_yyyymmdd()
target_dt_display = f"{target_dt[:4]}년 {target_dt[4:6]}월 {target_dt[6:]}일"
st.caption(f"기준 날짜(한국 시간 기준 어제): {target_dt_display}")

result = fetch_box_office(target_dt)

if not result["ok"]:
    # 빈 화면 대신, 무엇을 확인해야 하는지 안내 문구를 보여줍니다.
    st.error(result["reason"])
else:
    movies = result["movies"]

    # API가 원래 순위대로 정렬해서 주지만, 안전하게 우리도 숫자 기준으로 다시 정렬합니다.
    for m in movies:
        m["rank_num"] = to_int(m.get("rank"))
        m["audiCnt_num"] = to_int(m.get("audiCnt"))
        m["audiAcc_num"] = to_int(m.get("audiAcc"))
        m["scrnCnt_num"] = to_int(m.get("scrnCnt"))

    movies_sorted = sorted(movies, key=lambda m: m["rank_num"])

    # ── 4-1. 1위 영화 지표 카드 3장 ──
    top_movie = movies_sorted[0]
    st.subheader(f"🏆 1위: {top_movie.get('movieNm', '-')}")

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
                "영화명": m.get("movieNm", "-"),
                "개봉일": m.get("openDt", "-"),
                "관객수": m["audiCnt_num"],
                "누적관객": m["audiAcc_num"],
                "스크린수": m["scrnCnt_num"],
            }
            for m in movies_sorted
        ]
    )
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "관객수": st.column_config.NumberColumn(format="%d"),
            "누적관객": st.column_config.NumberColumn(format="%d"),
            "스크린수": st.column_config.NumberColumn(format="%d"),
        },
    )

    st.divider()

    # ── 4-3. 관객수 상위 5편 막대그래프 ──
    st.subheader("📊 관객수 상위 5편")
    top5 = sorted(movies_sorted, key=lambda m: m["audiCnt_num"], reverse=True)[:5]
    chart_df = pd.DataFrame(
        {m.get("movieNm", "-"): [m["audiCnt_num"]] for m in top5}
    ).T
    chart_df.columns = ["관객수"]
    st.bar_chart(chart_df)
