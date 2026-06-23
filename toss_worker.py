"""토스 재수집 로컬 워커.

사무실 PC(토스 로그인된 Chrome이 있는 컴퓨터)에서 상시 실행한다.
구글시트 큐를 10초마다 확인하여 pending 작업을 스크래핑·업데이트한다.

실행:
    py toss_worker.py

필요 조건:
    - 이 PC의 Chrome에 토스 광고 플랫폼 로그인
    - browser-harness 설치
    - Service Account 키 파일 (toss_update_bot.SA_FILE 경로)
"""

import time
import traceback
from datetime import datetime

from toss_update_bot import _client, run_pipeline, SPREADSHEET_ID
from toss_queue import find_pending, update_job

POLL_INTERVAL = 10  # 초


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def process_job(client, sh, job: dict):
    row = job["row"]
    jid = job["job_id"]
    start = job["start"]
    end = job["end"]

    log(f"▶ 작업 시작 {jid} ({start} ~ {end})")
    update_job(sh, row, "running", "워커 실행 중...")

    logs = []
    def collect(m):
        logs.append(m)
        log(f"   {m}")

    try:
        # start/end는 문자열 → date 변환
        from datetime import datetime as dt
        s = dt.strptime(start, "%Y-%m-%d").date()
        e = dt.strptime(end, "%Y-%m-%d").date()
        result = run_pipeline(s, e, use_toss=True, client=client, log=collect)
        msg = f"완료: 소재행 {len(result['sojaebang'])}개, 삭제 {result['deleted']}개"
        update_job(sh, row, "done", msg)
        log(f"✔ 작업 완료 {jid} — {msg}")
    except Exception as exc:
        err = f"{exc}\n{traceback.format_exc()}"
        update_job(sh, row, "error", str(exc))
        log(f"✖ 작업 실패 {jid}: {exc}")


def main():
    log("토스 워커 시작. 큐 확인 중... (Ctrl+C로 종료)")
    client = _client()
    sh = client.open_by_key(SPREADSHEET_ID)

    while True:
        try:
            pending = find_pending(sh, mode="toss")
            for job in pending:
                process_job(client, sh, job)
        except Exception as exc:
            log(f"⚠ 폴링 오류: {exc}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
