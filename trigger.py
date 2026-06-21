# trigger.py
#
# static.yml(배포)이 Kboallstar.yml(수집)을 "발사하고 응답만 받는" 방식이었던 것을
# "완료될 때까지 기다리는" 방식으로 바꾼다.
#
# 기존 문제:
#   - dispatch API는 워크플로를 큐에 등록만 하고 즉시 204를 반환한다.
#   - static.yml은 이 호출이 끝나자마자 다음 단계(chart_builder.py)로 넘어갔기 때문에,
#     Kboallstar.yml의 수집(collector.py)이 끝나기 한참 전에 옛날 data/로 차트를 빌드해 배포했다.
#   - 데이터 양이 적을 때는 수집이 빨리 끝나 우연히 타이밍이 맞았지만,
#     수집 시간이 늘어나면서 어긋나기 시작한 것.
#
# 해결:
#   - dispatch 직전 시각(UTC)을 기록해 둔다.
#   - dispatch 직후, 그 시각 이후에 새로 생성된 run을 찾아 ID를 특정한다.
#     (dispatch API 응답 자체에는 run_id가 없어 list-runs로 조회해야 함)
#   - 해당 run의 상태(status)가 "completed"가 될 때까지 폴링한다.
#   - conclusion이 "success"가 아니면 이후 빌드를 막기 위해 에러로 종료한다
#     (workflow에서 continue-on-error를 쓰지 않는 한 여기서 파이프라인이 멈춘다).

import os
import sys
import time
import requests
from datetime import datetime, timezone

TOKEN    = os.environ["GITHUB_TOKEN"]
OWNER    = "MSILJI0708"
REPO     = "26kboasg"
WORKFLOW = "Kboallstar.yml"

API_BASE = f"https://api.github.com/repos/{OWNER}/{REPO}/actions/workflows/{WORKFLOW}"
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
}

# 폴링 설정
POLL_INTERVAL_SEC = 15      # 몇 초마다 상태를 확인할지
MAX_WAIT_SEC       = 20 * 60  # 최대 대기 시간 (수집 데이터가 더 커지면 이 값을 늘릴 것)
RUN_LOOKUP_RETRIES = 6       # dispatch 직후 run이 목록에 뜨기까지 약간의 지연이 있을 수 있어 재시도
RUN_LOOKUP_DELAY   = 3


def dispatch_workflow() -> datetime:
    """Kboallstar.yml을 트리거하고, dispatch 직전 시각(UTC)을 반환한다."""
    before = datetime.now(timezone.utc)
    res = requests.post(
        f"{API_BASE}/dispatches",
        headers=HEADERS,
        json={"ref": "main"},
        timeout=30,
    )
    if res.status_code != 204:
        print(f"❌ 워크플로 트리거 실패: {res.status_code} {res.text}")
        sys.exit(1)
    print(f"✅ 워크플로 트리거 성공 (dispatch 시각: {before.isoformat()})")
    return before


def find_new_run_id(after: datetime) -> int:
    """dispatch 시각 이후에 새로 생성된 run의 ID를 찾는다."""
    for attempt in range(1, RUN_LOOKUP_RETRIES + 1):
        res = requests.get(
            f"{API_BASE}/runs",
            headers=HEADERS,
            params={"event": "workflow_dispatch", "per_page": 5},
            timeout=30,
        )
        res.raise_for_status()
        runs = res.json().get("workflow_runs", [])
        for run in runs:
            created_at = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
            if created_at >= after:
                print(f"✅ 새 run 발견: id={run['id']}, created_at={run['created_at']}")
                return run["id"]
        print(f"  ⏳ 아직 새 run을 못 찾음 (시도 {attempt}/{RUN_LOOKUP_RETRIES}), {RUN_LOOKUP_DELAY}초 후 재시도")
        time.sleep(RUN_LOOKUP_DELAY)

    print("❌ dispatch 이후 새로 생성된 run을 찾지 못함")
    sys.exit(1)


def wait_for_completion(run_id: int) -> None:
    """run이 completed 상태가 될 때까지 폴링하고, 결과(conclusion)를 검사한다."""
    elapsed = 0
    while elapsed < MAX_WAIT_SEC:
        res = requests.get(
            f"https://api.github.com/repos/{OWNER}/{REPO}/actions/runs/{run_id}",
            headers=HEADERS,
            timeout=30,
        )
        res.raise_for_status()
        run = res.json()
        status = run["status"]          # queued | in_progress | completed
        conclusion = run["conclusion"]  # None | success | failure | cancelled | ...

        print(f"  [{elapsed:>4}s] status={status} conclusion={conclusion}")

        if status == "completed":
            if conclusion == "success":
                print("✅ 수집 워크플로(Kboallstar.yml) 완료: 성공")
                return
            else:
                print(f"❌ 수집 워크플로(Kboallstar.yml) 실패: conclusion={conclusion}")
                print(f"   상세 로그: {run['html_url']}")
                sys.exit(1)

        time.sleep(POLL_INTERVAL_SEC)
        elapsed += POLL_INTERVAL_SEC

    print(f"❌ 제한 시간({MAX_WAIT_SEC}초) 내에 수집 워크플로가 끝나지 않음")
    sys.exit(1)


if __name__ == "__main__":
    dispatched_at = dispatch_workflow()
    run_id = find_new_run_id(dispatched_at)
    wait_for_completion(run_id)
    print("✅ 수집 완료 확인됨 — 이후 단계(chart_builder.py)에서 최신 data/를 사용할 수 있습니다.")
