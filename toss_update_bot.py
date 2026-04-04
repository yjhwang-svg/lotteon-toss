"""토스update 시트를 읽어 토스업로드 시트에 자동 업데이트하는 봇.

사용법:
    # 오늘 날짜 기준 어제 데이터 업로드 (기본)
    py toss_update_bot.py

    # 특정 날짜 데이터 업로드
    py toss_update_bot.py --date 2026-04-02
"""

import argparse
import sys
from datetime import datetime, timedelta

import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SA_FILE = (
    r"C:\Users\MADUP\주식회사매드업 Dropbox\광고사업부\4. 광고주"
    r"\카카오스타일\★ 지그재그\리포트\(이전)\2. 파이썬"
    r"\uploading-raw-data-to-gspread-a76f45bcfd36.json"
)
SPREADSHEET_ID = "18Gzpi_yeYQXbjqChlhm9EHT7z0Gi-65D0NCX7iC3SJ4"
SOURCE_SHEET = "토스update"
TARGET_SHEET = "토스업로드"


def get_client() -> gspread.Client:
    creds = Credentials.from_service_account_file(SA_FILE, scopes=SCOPES)
    return gspread.authorize(creds)


def find_date_column(header_row: list[str], target_date: str) -> int | None:
    """헤더 행에서 target_date(YYYY-MM-DD)에 해당하는 열 인덱스를 반환."""
    for i, cell in enumerate(header_row):
        if cell == target_date:
            return i
    return None


def build_upload_rows(
    source_data: list[list[str]], target_date: str
) -> list[list[str]]:
    """토스update 데이터에서 target_date에 해당하는 업로드 행들을 생성."""
    header = source_data[0]
    col_idx = find_date_column(header, target_date)
    if col_idx is None:
        raise ValueError(f"토스update 시트에서 '{target_date}' 열을 찾을 수 없습니다.")

    rows: list[list[str]] = []

    # 디폴트 행: 소재명=없음, 노출/클릭/비용 모두 0
    rows.append([target_date, "토스", "-", "없음", "없음", "0", "0", "0"])

    for row in source_data[1:]:
        channel = row[0].strip() if row[0] else ""
        if not channel:
            continue

        value = row[col_idx].strip() if col_idx < len(row) and row[col_idx] else ""
        if not value:
            continue

        rows.append([
            target_date,
            "토스",
            "-",
            "없음",
            channel,       # 소재명 = 채널상세
            "0",           # 노출 = 0
            value,         # 클릭 = 토스update 수치
            "100000",      # 비용 = 100000
        ])

    return rows


def upload_rows(client: gspread.Client, rows: list[list[str]]) -> int:
    """토스업로드 시트에 행들을 append하고 폰트를 Arial 8pt로 설정."""
    sh = client.open_by_key(SPREADSHEET_ID)
    ws = sh.worksheet(TARGET_SHEET)

    existing_row_count = len(ws.get_all_values())
    ws.append_rows(rows, value_input_option="USER_ENTERED")

    start_row = existing_row_count + 1
    end_row = existing_row_count + len(rows)
    fmt_range = f"A{start_row}:H{end_row}"
    ws.format(fmt_range, {
        "textFormat": {"fontFamily": "Arial", "fontSize": 8}
    })

    return len(rows)


def check_already_uploaded(client: gspread.Client, target_date: str) -> bool:
    """이미 해당 날짜 데이터가 업로드되어 있는지 확인."""
    sh = client.open_by_key(SPREADSHEET_ID)
    ws = sh.worksheet(TARGET_SHEET)
    existing = ws.get_all_values()
    return any(row[0] == target_date for row in existing[1:])


def main():
    parser = argparse.ArgumentParser(description="토스 시트 자동 업데이트 봇")
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="업데이트할 날짜 (YYYY-MM-DD). 미지정 시 어제 날짜",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="이미 데이터가 있어도 강제 업로드",
    )
    args = parser.parse_args()

    if args.date:
        target_date = args.date
    else:
        target_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    print(f"[토스봇] 대상 날짜: {target_date}")

    client = get_client()

    if not args.force and check_already_uploaded(client, target_date):
        print(f"[토스봇] {target_date} 데이터가 이미 존재합니다. --force 로 강제 업로드 가능")
        sys.exit(0)

    print("[토스봇] 토스update 시트 읽는 중...")
    sh = client.open_by_key(SPREADSHEET_ID)
    ws_source = sh.worksheet(SOURCE_SHEET)
    source_data = ws_source.get_all_values()

    print("[토스봇] 업로드 행 생성 중...")
    rows = build_upload_rows(source_data, target_date)
    print(f"[토스봇] 생성된 행 수: {len(rows)}개 (디폴트 행 1 + 소재 {len(rows)-1}개)")

    print("[토스봇] 토스업로드 시트에 append 중...")
    count = upload_rows(client, rows)
    print(f"[토스봇] 완료! {count}개 행 업로드됨")

    for r in rows:
        print(f"  {r}")


if __name__ == "__main__":
    main()
