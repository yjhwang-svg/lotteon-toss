"""토스 광고비 업데이트 봇.

비용 계산 (기본):
    클릭 < 10,000          → 클릭 × 10
    10,000 ≤ 클릭 < 20,000 → 100,000
    20,000 ≤ 클릭 < 30,000 → 200,000  (이후 동일)

예외 로직 (--toss 플래그):
    집행완료 + 집행비용 < 예상비용인 캠페인에 대해
    - 단일일: 해당 날짜 비용 → 집행비용으로 교체
    - 기간: 마지막 날 제외 나머지는 기본 공식, 마지막 날 = 집행비용 - 앞 날 합계

사용법:
    py toss_update_bot.py                                    # 어제 (기본)
    py toss_update_bot.py --date 2026-06-07                 # 특정 날짜
    py toss_update_bot.py --start 2026-06-01 --end 2026-06-07
    py toss_update_bot.py --date 2026-06-07 --force         # 강제 재수집
    py toss_update_bot.py --date 2026-06-07 --force --toss  # 예외 로직 포함
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, date as Date
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

# ── 상수 ──────────────────────────────────────────────────────────────────────
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SA_FILE = (
    r"C:\Users\MADUP\주식회사매드업 Dropbox\광고사업부\4. 광고주"
    r"\카카오스타일\★ 지그재그\리포트\(이전)\2. 파이썬"
    r"\uploading-raw-data-to-gspread-a76f45bcfd36.json"
)
SPREADSHEET_ID    = "18Gzpi_yeYQXbjqChlhm9EHT7z0Gi-65D0NCX7iC3SJ4"
MAPPING_SHEET_KEY = "1FDog38MW7faYyHC4hXXcHg2e055cDDuOoH-3t9oeA-A"
MAPPING_GID       = 1340025873
SOURCE_SHEET      = "토스update"
TARGET_SHEET      = "토스업로드"
BH_PROJECT        = r"C:\Users\MADUP\Developer\browser-harness"

_HERE         = Path(__file__).parent
_SCRAPE_SCRIPT = _HERE / "_toss_scrape.py"
_SCRAPE_RESULT = _HERE / "_toss_scrape_result.json"

# ── 스크래핑 코드 (browser-harness용) ────────────────────────────────────────
_SCRAPE_CODE = '''\
import json, time

result_path = r"{result_path}"
TOSS_URL = "https://ads-platform.toss.im/visit-mission?contractIds=33743&tab=contract"

targets = cdp("Target.getTargets", {{}}).get("targetInfos", [])
toss_target = None
for t in targets:
    url = t.get("url", "")
    if "ads-platform.toss.im" in url and t.get("type") == "page":
        toss_target = t["targetId"]
        break

if not toss_target:
    new_tab(TOSS_URL)
    time.sleep(5)
else:
    switch_tab(toss_target)
    time.sleep(2)
    current_url = js("return location.href")
    if "tab=contract" not in current_url:
        js("location.href = '" + TOSS_URL + "'")
        time.sleep(4)

all_campaigns = []

def read_rows():
    return js("""
    return Array.from(document.querySelectorAll("tbody tr")).map(r =>
        Array.from(r.querySelectorAll("td")).map(c => c.textContent.trim())
    ).filter(r => r.length >= 10);
    """) or []

def click_next():
    return js("""
    const nav = document.querySelector("nav[aria-label], [class*=pagination], [class*=Pagination]");
    const btns = nav ? nav.querySelectorAll("button") : document.querySelectorAll("button");
    for (const b of btns) {{
        if (!b.disabled && (b.textContent.trim() === ">" || b.textContent.trim() === "다음")) {{
            b.click(); return true;
        }}
    }}
    return false;
    """)

seen = set()
stale = 0
for _ in range(50):
    time.sleep(0.8)
    new_count = 0
    for row in read_rows():
        # [체크, 집행상태, 소재상태, 캠페인ID, 캠페인명, 소재수, 집행일시, 타입, 예상비용, 집행비용, ...]
        status   = row[1] if len(row) > 1 else ""
        name     = row[4] if len(row) > 4 else ""
        period   = row[6] if len(row) > 6 else ""
        expected = row[8] if len(row) > 8 else ""
        actual   = row[9] if len(row) > 9 else ""
        if not (name and period):
            continue
        key = (name, period, expected, actual)
        if key in seen:
            continue
        seen.add(key)
        new_count += 1
        all_campaigns.append({{
            "campaign_name": name,
            "period": period,
            "status": status,
            "expected_cost": expected,
            "actual_cost": actual,
        }})
    # 다음 페이지 버튼이 없으면 종료
    if not click_next():
        break
    # 새 행이 2회 연속 없으면 종료 (버튼 오탐지로 무한루프 방지)
    if new_count == 0:
        stale += 1
        if stale >= 2:
            break
    else:
        stale = 0

with open(result_path, "w", encoding="utf-8") as f:
    json.dump(all_campaigns, f, ensure_ascii=False, indent=2)
'''


# ── 날짜 유틸 ─────────────────────────────────────────────────────────────────
def _date_range(start: Date, end: Date) -> list[Date]:
    out, cur = [], start
    while cur <= end:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def _parse_period(period_str: str) -> tuple[Date, Date]:
    parts = period_str.replace(" ", "").split("~")
    def to_date(s: str) -> Date:
        y, m, d = s.split(".")
        return Date(int(y), int(m), int(d))
    start = to_date(parts[0])
    end   = to_date(parts[1]) if len(parts) > 1 else start
    return start, end


def _parse_cost(s: str) -> int:
    cleaned = s.replace(",", "").replace("원", "").strip()
    try:
        return int(cleaned)
    except ValueError:
        return 0


# ── 비용 공식 ─────────────────────────────────────────────────────────────────
def calc_cost(clicks: int) -> int:
    """클릭 → 비용.

    - 10,000 미만: 클릭 × 10
    - 1만 단위 블록 안에서 나머지 < 5,000: (블록 수) × 100,000
      (예: 10,000~14,999 → 100,000 / 20,000~24,999 → 200,000)
    - 나머지 ≥ 5,000: 클릭 × 10
      (예: 15,000~19,999 / 25,000~29,999 → 클릭 × 10)
    """
    if clicks <= 0:
        return 0
    if clicks < 10_000:
        return clicks * 10
    if clicks % 10_000 < 5_000:
        return (clicks // 10_000) * 100_000
    return clicks * 10


# ── gspread ───────────────────────────────────────────────────────────────────
def _client() -> gspread.Client:
    """서비스 계정 인증. 우선순위: 환경변수 GCP_SA_JSON(JSON 문자열) → 로컬 파일."""
    sa_json = os.environ.get("GCP_SA_JSON")
    if sa_json:
        info = json.loads(sa_json)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    else:
        creds = Credentials.from_service_account_file(SA_FILE, scopes=SCOPES)
    return gspread.authorize(creds)


# ── 매핑 로드: G열(대시보드 캠페인명) → A열(토스update B열 상품명) ────────────
def load_mapping(client: gspread.Client) -> dict[str, str]:
    sh = client.open_by_key(MAPPING_SHEET_KEY)
    ws = next(w for w in sh.worksheets() if w.id == MAPPING_GID)
    rows = ws.get_all_values()
    mapping = {}
    for row in rows[1:]:
        a = row[0].strip() if len(row) > 0 else ""
        g = row[6].strip() if len(row) > 6 else ""
        if a and g:
            mapping[g] = a
    print(f"[토스봇] 매핑 {len(mapping)}개 로드")
    return mapping


# ── 대시보드 스크래핑 ──────────────────────────────────────────────────────────
def scrape_dashboard() -> list[dict]:
    code = _SCRAPE_CODE.format(result_path=str(_SCRAPE_RESULT).replace("\\", "\\\\"))
    _SCRAPE_SCRIPT.write_text(code, encoding="utf-8")

    print("[토스봇] 대시보드 스크래핑 중...")
    subprocess.run(
        ["uv", "run", "--project", BH_PROJECT, "browser-harness"],
        input=f"exec(open(r'{_SCRAPE_SCRIPT}', encoding='utf-8').read())\n",
        text=True, encoding="utf-8", errors="replace",
        cwd=str(_HERE),
    )

    if not _SCRAPE_RESULT.exists():
        raise RuntimeError("스크래핑 결과 파일이 생성되지 않았습니다.")

    data = json.loads(_SCRAPE_RESULT.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "error" in data:
        raise RuntimeError(data["error"])

    print(f"[토스봇] 캠페인 {len(data)}개 수집")
    return data


# ── 기본 행 생성 ──────────────────────────────────────────────────────────────
def calculate_rows(
    header: list[str],
    source_rows: list[list[str]],
    target_dates: list[Date],
) -> list[list[str]]:
    date_col: dict[str, int] = {
        h: i for i, h in enumerate(header)
        if len(h) == 10 and h[4] == "-" and h[7] == "-"
    }

    upload_rows: list[list[str]] = []

    for d in target_dates:
        d_str = d.strftime("%Y-%m-%d")
        col_i = date_col.get(d_str)

        upload_rows.append([d_str, "토스", "-", "없음", "없음", "0", "0", "0"])

        if col_i is None:
            continue

        for row in source_rows:
            if len(row) <= col_i:
                continue
            channel = row[0].strip()
            if not channel:
                continue
            raw = row[col_i].replace(",", "").strip()
            if not raw.isdigit():
                continue
            clicks = int(raw)
            if clicks == 0:
                continue

            upload_rows.append([
                d_str, "토스", "-", "없음",
                channel, "0", str(clicks), str(calc_cost(clicks)),
            ])

    return upload_rows


# ── 예외 로직: 집행완료 + 집행비용 < 예상비용 보정 ────────────────────────────
def apply_exception_costs(
    rows: list[list[str]],
    campaigns: list[dict],
    mapping: dict[str, str],
    header: list[str],
    source_rows: list[list[str]],
    target_dates: list[Date],
) -> list[list[str]]:
    """집행완료 캠페인의 일별 비용 합을 실제 집행비용에 맞춘다.

    한 상품에 캠페인이 여러 개(기간 겹침)일 수 있으므로, 각 캠페인을
    '시작일이 캠페인 기간 시작과 같은 소스 행'에만 적용한다.
    """
    date_col: dict[str, int] = {
        h: i for i, h in enumerate(header)
        if len(h) == 10 and h[4] == "-" and h[7] == "-"
    }
    target_date_strs = {d.strftime("%Y-%m-%d") for d in target_dates}

    # 업로드 행을 (날짜, 채널, 클릭수) → [행 인덱스] 로 인덱싱 (중복 소비용)
    upload_index: dict[tuple[str, str, str], list[int]] = {}
    for i, r in enumerate(rows):
        if len(r) >= 7:
            upload_index.setdefault((r[0], r[4], r[6].replace(",", "")), []).append(i)

    def source_cells(r: list[str]) -> dict[str, int]:
        """소스 행의 클릭이 있는 날짜 → 클릭수."""
        out = {}
        for d_str, col in date_col.items():
            if col < len(r):
                raw = r[col].replace(",", "").strip()
                if raw.isdigit() and int(raw) > 0:
                    out[d_str] = int(raw)
        return out

    # 같은 (캠페인명, 기간)이 여러 줄로 뜨면 집행비용 합산 (분할 정산 통합)
    agg: dict[tuple[str, str], dict] = {}
    for camp in campaigns:
        if "완료" not in camp.get("status", ""):
            continue
        key = (camp["campaign_name"], camp.get("period", ""))
        a = _parse_cost(camp.get("actual_cost", "0"))
        e = _parse_cost(camp.get("expected_cost", "0"))
        if key not in agg:
            agg[key] = {"campaign_name": camp["campaign_name"],
                        "period": camp.get("period", ""),
                        "actual": a, "expected": e}
        else:
            agg[key]["actual"] += a
            agg[key]["expected"] = max(agg[key]["expected"], e)

    for camp in agg.values():
        expected = camp["expected"]
        actual   = camp["actual"]
        # 집행비용이 0이거나 예상비용과 같으면 보정 불필요 (구간 공식 그대로).
        if actual <= 0 or actual == expected:
            continue

        product = mapping.get(camp["campaign_name"])
        if not product:
            continue

        try:
            p_start, p_end = _parse_period(camp["period"])
        except Exception:
            continue
        start_str = p_start.strftime("%Y-%m-%d")
        end_str   = p_end.strftime("%Y-%m-%d")

        # 이 캠페인에 속하는 소스 행: 상품 일치 + 첫 클릭일 == 기간 시작 + 마지막 클릭일 <= 기간 종료
        # → 같은 상품의 다른 기간 캠페인 행과 분리된다.
        # 셀 = (날짜, 클릭수, 채널) — 같은 날 여러 행이면 셀도 여러 개.
        cell_list: list[tuple[str, int, str]] = []
        for r in source_rows:
            if len(r) <= 1 or r[1].strip() != product:
                continue
            sc = source_cells(r)
            if not sc:
                continue
            first, last = min(sc), max(sc)
            if first != start_str or last > end_str:
                continue
            ch = r[0].strip()
            for d_str, clk in sc.items():
                cell_list.append((d_str, clk, ch))
        if not cell_list:
            continue

        last_day = max(d for d, _, _ in cell_list)
        # 마지막 날 제외 구간 비용 합 (셀별 구간 공식)
        cost_sum = sum(calc_cost(clk) for d, clk, _ in cell_list if d != last_day)
        remainder = max(0, actual - cost_sum)

        # 마지막 날 셀들에 remainder를 클릭 비율로 분배 (업데이트 범위 안일 때만)
        if last_day not in target_date_strs:
            continue
        last_cells = [(clk, ch) for d, clk, ch in cell_list if d == last_day]
        total_clk = sum(clk for clk, _ in last_cells)
        if total_clk <= 0:
            continue
        rem = remainder
        for k, (clk, ch) in enumerate(last_cells):
            cost = rem if k == len(last_cells) - 1 else round(remainder * clk / total_clk)
            if k != len(last_cells) - 1:
                rem -= cost
            key = (last_day, ch, str(clk))
            idxs = upload_index.get(key)
            if idxs:
                rows[idxs.pop(0)][7] = str(max(0, cost))

    return rows


# ── 시트 업데이트 ─────────────────────────────────────────────────────────────
def update_sheet(
    client: gspread.Client,
    new_rows: list[list[str]],
    target_dates: list[Date],
) -> int:
    """기존 데이터에서 대상 날짜 행을 제거하고 새 행을 합쳐 한 번에 다시 쓴다.

    행 단위 delete/append/sort API를 호출하지 않고 read 1 + clear 1 + write 1로
    처리해 쓰기 할당량(분당 60건) 초과를 방지한다. 정렬은 파이썬에서 수행.
    """
    sh = client.open_by_key(SPREADSHEET_ID)
    ws = sh.worksheet(TARGET_SHEET)

    target_strs = {d.strftime("%Y-%m-%d") for d in target_dates}
    all_data = ws.get_all_values()

    header = all_data[0] if all_data else []
    body   = all_data[1:] if len(all_data) > 1 else []

    # 대상 날짜가 아닌 기존 행만 유지 (빈 행 제거)
    kept = [r for r in body if r and r[0] and r[0] not in target_strs]
    deleted = len([r for r in body if r and r[0] in target_strs])

    # 합치고 날짜 오름차순 정렬 (YYYY-MM-DD 문자열은 사전순 == 날짜순)
    combined = kept + new_rows
    combined.sort(key=lambda r: r[0] if r else "")

    old_last = len(all_data)  # 기존 데이터가 차지하던 마지막 행 번호

    # 1) 기존 데이터 영역 비우기 (헤더 제외)
    if old_last > 1:
        ws.batch_clear([f"A2:H{old_last}"])

    # 2) 정렬된 전체 본문을 한 번에 쓰기
    if combined:
        ws.update(
            f"A2:H{len(combined) + 1}",
            combined,
            value_input_option="USER_ENTERED",
        )
        # 3) 서식 (한 번)
        ws.format(f"A2:H{len(combined) + 1}", {
            "textFormat": {"fontFamily": "Arial", "fontSize": 8}
        })

    print(f"[토스봇] 기존 {deleted}개 행 교체, 총 {len(combined)}개 행 기록")
    return deleted


# ── 파이프라인 (대시보드·워커 공유) ──────────────────────────────────────────
def run_pipeline(start: Date, end: Date, use_toss: bool, client=None, log=print) -> dict:
    """소스 읽기 → 비용 계산 → (옵션) 예외 로직 → 시트 업데이트.

    Args:
        start, end: 대상 날짜 범위
        use_toss:   True면 토스 대시보드 스크래핑 + 집행완료 예외 로직 적용
        client:     gspread 클라이언트 (없으면 자동 생성)
        log:        진행 로그 콜백 (기본 print)
    """
    if client is None:
        client = _client()

    target_dates = _date_range(start, end)

    log(f"📥 토스update 시트 읽는 중... ({start} ~ {end})")
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

    deleted = update_sheet(client, rows, target_dates)
    log("✅ 날짜 오름차순 정렬 완료")

    return {
        "sojaebang": [r for r in rows if r[4] != "없음"],
        "deleted": deleted,
        "dates": [d.strftime("%Y-%m-%d") for d in target_dates],
        "used_toss": use_toss,
    }


# ── main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="토스 시트 자동 업데이트 봇")
    parser.add_argument("--date",  type=str)
    parser.add_argument("--start", type=str)
    parser.add_argument("--end",   type=str)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--toss",  action="store_true", help="토스 대시보드 스크래핑 + 예외 로직 적용")
    args = parser.parse_args()

    if args.date:
        target_dates = [datetime.strptime(args.date, "%Y-%m-%d").date()]
    elif args.start and args.end:
        s = datetime.strptime(args.start, "%Y-%m-%d").date()
        e = datetime.strptime(args.end,   "%Y-%m-%d").date()
        target_dates = _date_range(s, e)
    else:
        target_dates = [(datetime.now() - timedelta(days=1)).date()]

    start, end = target_dates[0], target_dates[-1]
    date_strs = [d.strftime("%Y-%m-%d") for d in target_dates]
    print(f"[토스봇] 대상 날짜: {date_strs[0]} ~ {date_strs[-1]} ({len(target_dates)}일)")

    client = _client()

    if not args.force:
        sh = client.open_by_key(SPREADSHEET_ID)
        ws = sh.worksheet(TARGET_SHEET)
        existing = {r[0] for r in ws.get_all_values() if r}
        overlap = [d for d in date_strs if d in existing]
        if overlap:
            print(f"[토스봇] 이미 데이터 존재: {overlap}")
            print("[토스봇] --force 옵션으로 재수집 가능")
            sys.exit(0)

    result = run_pipeline(start, end, args.toss, client=client)
    print(f"\n[토스봇] 완료! 소재행 {len(result['sojaebang'])}개")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
