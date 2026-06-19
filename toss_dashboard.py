"""토스 광고비 업데이트 대시보드 (Streamlit)

실행:
    streamlit run toss_dashboard.py
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import streamlit as st

st.set_page_config(
    page_title="토스 광고비 업데이트",
    page_icon="💙",
    layout="centered",
)

st.markdown("""
<style>
  @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');

  html, body, *, *::before, *::after,
  [class*="css"], input, button, select, textarea, label, p, span, div,
  .stMarkdown, .stText, .stDateInput, .stButton,
  [data-testid], [data-baseweb] {
    font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, sans-serif !important;
  }

  .toss-header {
    background: #0064FF;
    border-radius: 16px;
    padding: 28px 32px 24px;
    margin-bottom: 28px;
    color: white;
  }
  .toss-header h1 { font-size: 22px; font-weight: 700; margin: 0 0 4px; }
  .toss-header p  { font-size: 14px; opacity: .75; margin: 0; }

  .toss-card {
    background: white;
    border: 1px solid #F2F4F6;
    border-radius: 16px;
    padding: 24px;
    margin-bottom: 16px;
    box-shadow: 0 2px 8px rgba(0,0,0,.04);
  }
  .toss-card-title {
    font-size: 13px; font-weight: 600; color: #6B7684;
    text-transform: uppercase; letter-spacing: .05em;
    margin-bottom: 14px;
  }

  .log-box {
    background: #F8F9FA;
    border: 1px solid #E9ECEF;
    border-radius: 12px;
    padding: 16px;
    font-size: 13px;
    line-height: 1.7;
    font-family: 'Consolas', monospace !important;
    max-height: 320px;
    overflow-y: auto;
    white-space: pre-wrap;
  }

  .result-row {
    display: flex; justify-content: space-between; align-items: center;
    padding: 10px 0; border-bottom: 1px solid #F2F4F6; font-size: 14px;
  }
  .result-row:last-child { border-bottom: none; }
  .result-channel { color: #4E5968; }
  .result-cost { font-weight: 700; color: #0064FF; }

  /* 일반 재수집 버튼 */
  div[data-testid="stButton"]:nth-of-type(1) > button {
    background: #0064FF; color: white; border: none;
    border-radius: 12px; padding: 18px 32px; font-size: 16px;
    font-weight: 700; width: 100%; min-height: 56px; line-height: 1.4;
    transition: background .15s;
  }
  div[data-testid="stButton"]:nth-of-type(1) > button:hover { background: #0052CC; }

  /* 토스 대시보드 재수집 버튼 */
  div[data-testid="stButton"]:nth-of-type(2) > button {
    background: white; color: #0064FF;
    border: 2px solid #0064FF;
    border-radius: 12px; padding: 18px 32px; font-size: 16px;
    font-weight: 700; width: 100%; min-height: 56px; line-height: 1.4;
    transition: all .15s;
  }
  div[data-testid="stButton"]:nth-of-type(2) > button:hover {
    background: #E8F3FF;
  }

  div.stButton > button:disabled { background: #C2D3F0 !important; border: none !important; color: white !important; cursor: not-allowed; }

  .block-container { padding-top: 2rem; max-width: 680px; }
  footer { display: none; }
  #MainMenu { display: none; }
</style>
""", unsafe_allow_html=True)

# ── 상수 ──────────────────────────────────────────────────────────────────────
_HERE = Path(__file__).parent
SPREADSHEET_ID = "18Gzpi_yeYQXbjqChlhm9EHT7z0Gi-65D0NCX7iC3SJ4"
TARGET_SHEET   = "토스업로드"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit?gid=1288015996#gid=1288015996"

# ── 세션 스테이트 ─────────────────────────────────────────────────────────────
for key in ["logs", "result", "error", "running"]:
    if key not in st.session_state:
        st.session_state[key] = [] if key == "logs" else (False if key == "running" else None)

# ── import ────────────────────────────────────────────────────────────────────
sys.path.insert(0, str(_HERE))
from toss_update_bot import (
    _client, _date_range, calculate_rows, apply_exception_costs,
    load_mapping, scrape_dashboard,
    SOURCE_SHEET, SPREADSHEET_ID as _SID,
)
import gspread


def run_update(start: date, end: date, use_toss: bool) -> dict:
    target_dates = _date_range(start, end)
    date_strs = [d.strftime("%Y-%m-%d") for d in target_dates]
    logs = []

    def log(msg): logs.append(msg)

    log(f"📥 토스update 시트 읽는 중... ({start} ~ {end})")
    client = _client()
    sh = client.open_by_key(SPREADSHEET_ID)
    all_rows = sh.worksheet(SOURCE_SHEET).get_all_values()
    header, source_rows = all_rows[1], all_rows[2:]
    log("✅ 토스update 시트 로드")

    rows = calculate_rows(header, source_rows, target_dates)
    default_count = len(target_dates)
    log(f"📊 기본 계산: 기본행 {default_count}개 + 소재행 {len(rows) - default_count}개")

    if use_toss:
        log("🔍 토스 대시보드 스크래핑 중...")
        campaigns = scrape_dashboard()
        if not campaigns:
            raise RuntimeError("캠페인 데이터가 없습니다. 토스 광고 플랫폼에 로그인되어 있는지 확인해주세요.")
        log(f"✅ 캠페인 {len(campaigns)}개 수집")
        mapping = load_mapping(client)
        log(f"✅ 매핑 {len(mapping)}개 로드")
        rows = apply_exception_costs(rows, campaigns, mapping, header, source_rows, target_dates)
        log("✅ 집행완료 예외 로직 적용")

    # 시트 업데이트
    ws = sh.worksheet(TARGET_SHEET)
    target_strs = set(date_strs)
    all_data = ws.get_all_values()

    to_delete = [i + 1 for i, row in enumerate(all_data) if row and row[0] in target_strs]
    for idx in sorted(to_delete, reverse=True):
        ws.delete_rows(idx)
    log(f"🗑️ 기존 {len(to_delete)}개 행 삭제")

    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
        log(f"➕ {len(rows)}개 행 추가")

    total_rows = len(ws.get_all_values())
    sh.batch_update({"requests": [{"sortRange": {
        "range": {
            "sheetId": ws.id,
            "startRowIndex": 1,
            "endRowIndex": total_rows,
            "startColumnIndex": 0,
            "endColumnIndex": 8,
        },
        "sortSpecs": [{"dimensionIndex": 0, "sortOrder": "ASCENDING"}],
    }}]})
    log("✅ 날짜 오름차순 정렬 완료")

    return {
        "logs": logs,
        "sojaebang": [r for r in rows if r[4] != "없음"],
        "deleted": len(to_delete),
        "dates": date_strs,
        "used_toss": use_toss,
    }


# ── UI ────────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="toss-header">
  <h1>💙 토스 광고비 업데이트</h1>
  <p>날짜를 선택하고 업데이트하면 클릭 수 기반으로 광고비를 자동 계산합니다</p>
</div>
""", unsafe_allow_html=True)

# 날짜 선택
st.markdown('<div class="toss-card"><div class="toss-card-title">📅 업데이트 기간 설정</div>', unsafe_allow_html=True)

yesterday = date.today() - timedelta(days=1)
col1, col2 = st.columns(2)
with col1:
    start_date = st.date_input("시작 날짜", value=yesterday, max_value=date.today(), key="start")
with col2:
    end_date = st.date_input("종료 날짜", value=yesterday, max_value=date.today(), key="end")

if start_date > end_date:
    st.error("시작 날짜가 종료 날짜보다 늦습니다.")
    st.stop()

days_count = (end_date - start_date).days + 1
st.markdown(
    f'<p style="font-size:13px;color:#6B7684;margin-top:4px;">'
    f'선택 기간: <b style="color:#0064FF">{days_count}일</b> ({start_date} ~ {end_date})</p>',
    unsafe_allow_html=True
)
st.markdown('</div>', unsafe_allow_html=True)

# 버튼 영역
st.markdown('<div class="toss-card"><div class="toss-card-title">🔄 재수집 방식 선택</div>', unsafe_allow_html=True)

col_a, col_b = st.columns(2)
with col_a:
    btn_normal = st.button(
        "일반 재수집",
        disabled=st.session_state.running,
        help="클릭 기반 구간 비용으로 재업로드 (토스 로그인 불필요)",
    )
with col_b:
    btn_toss = st.button(
        "토스 대시보드 재수집",
        disabled=st.session_state.running,
        help="토스 대시보드 스크래핑 후 집행완료 예외 비용 적용 (Chrome 로그인 필요)",
    )

st.markdown(
    '<p style="font-size:12px;color:#B0B8C1;margin-top:8px;">'
    '💡 일반 재수집: 클릭 &lt; 10,000 → 클릭×10원 / 이상 → 만 단위×10만원<br>'
    '💡 토스 대시보드 재수집: 집행완료+집행비용&lt;예상비용인 경우 실제 집행비용으로 보정</p>',
    unsafe_allow_html=True
)
st.markdown('</div>', unsafe_allow_html=True)

# 버튼 클릭 처리
use_toss = None
if btn_normal:
    use_toss = False
elif btn_toss:
    use_toss = True

if use_toss is not None and not st.session_state.running:
    st.session_state.running = True
    st.session_state.logs    = []
    st.session_state.result  = None
    st.session_state.error   = None

    try:
        result = run_update(start_date, end_date, use_toss)
        st.session_state.result = result
        st.session_state.logs   = result["logs"]
    except Exception as e:
        st.session_state.error = str(e)
    finally:
        st.session_state.running = False

    st.rerun()

# 로그
if st.session_state.logs:
    log_text = "\n".join(st.session_state.logs)
    st.markdown(
        f'<div class="toss-card"><div class="toss-card-title">📋 실행 로그</div>'
        f'<div class="log-box">{log_text}</div></div>',
        unsafe_allow_html=True
    )

# 에러
if st.session_state.error:
    st.markdown(
        f'<div class="toss-card" style="border-color:#FFCDD2;">'
        f'<div class="toss-card-title">❌ 오류 발생</div>'
        f'<p style="color:#D32F2F;font-size:14px;margin:0;">{st.session_state.error}</p>'
        f'</div>',
        unsafe_allow_html=True
    )

# 결과
if st.session_state.result:
    r = st.session_state.result
    sojaebang = r["sojaebang"]
    mode_label = "토스 대시보드 재수집" if r["used_toss"] else "일반 재수집"

    st.markdown(
        f'<div class="toss-card">'
        f'<div class="toss-card-title">✅ {mode_label} 완료</div>'
        f'<div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:16px;">'
        f'  <div style="flex:1;background:#E8F3FF;border-radius:12px;padding:16px;text-align:center;">'
        f'    <div style="font-size:24px;font-weight:800;color:#0064FF">{len(sojaebang)}</div>'
        f'    <div style="font-size:12px;color:#6B7684;margin-top:2px;">소재행</div>'
        f'  </div>'
        f'  <div style="flex:1;background:#F3FFF3;border-radius:12px;padding:16px;text-align:center;">'
        f'    <div style="font-size:24px;font-weight:800;color:#00B761">{r["deleted"]}</div>'
        f'    <div style="font-size:12px;color:#6B7684;margin-top:2px;">삭제된 행</div>'
        f'  </div>'
        f'  <div style="flex:1;background:#FFF8E1;border-radius:12px;padding:16px;text-align:center;">'
        f'    <div style="font-size:24px;font-weight:800;color:#F59E0B">{len(r["dates"])}</div>'
        f'    <div style="font-size:12px;color:#6B7684;margin-top:2px;">업데이트 일수</div>'
        f'  </div>'
        f'</div>',
        unsafe_allow_html=True
    )

    if sojaebang:
        rows_html = ""
        for row in sojaebang:
            d_str   = row[0]
            channel = row[4]
            clicks  = f"{int(row[6]):,}" if str(row[6]).isdigit() else str(row[6])
            cost    = f"{int(row[7]):,}원" if str(row[7]).isdigit() else str(row[7])
            rows_html += (
                f'<div class="result-row">'
                f'  <span style="color:#B0B8C1;font-size:12px;width:88px">{d_str}</span>'
                f'  <span class="result-channel" style="flex:1;padding:0 8px">{channel}</span>'
                f'  <span style="color:#6B7684;font-size:13px;width:70px;text-align:right">{clicks} 클릭</span>'
                f'  <span class="result-cost" style="width:90px;text-align:right">{cost}</span>'
                f'</div>'
            )
        st.markdown(
            f'<div style="border:1px solid #F2F4F6;border-radius:12px;padding:4px 16px;">{rows_html}</div>',
            unsafe_allow_html=True
        )

    st.markdown(
        f'<div style="text-align:center;margin-top:20px;">'
        f'<a href="{SHEET_URL}" target="_blank" style="'
        f'display:inline-block;background:#0064FF;color:white;text-decoration:none;'
        f'border-radius:12px;padding:12px 28px;font-size:15px;font-weight:700;">'
        f'📊 시트에서 확인하기</a></div>',
        unsafe_allow_html=True
    )

    st.markdown('</div>', unsafe_allow_html=True)
