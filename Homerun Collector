"""
2026 KBO 올스타 홈런더비 투표 수집기.

allstar.koreabaseball.com의 홈런더비 메인 페이지(Homerun/Main.aspx)가
내부적으로 호출하는 ASMX 웹서비스를 그대로 서버사이드에서 호출한다.
(collector.py가 GetKboAll을 호출하는 방식과 동일한 패턴)

응답 형태 (Main.aspx의 setVoteState() 참고):
{
  "state": 0 | 1 | 2,        # 0=투표 전, 1=투표 중(실시간), 2=투표 종료(최종)
  "updateDtTm": "...",       # 마지막 집계 갱신 시각 (state==1일 때만 존재)
  "playerList": [
    {
      "pNm": "선수명", "pId": 12345, "seasonId": 2026,
      "tId": "LG", "tNm": "LG", "rankNo": 1, "voteCn": "1,234,567"
    }, ...
  ]
}
"""
import requests
import json
import os
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

URL = "https://allstar.koreabaseball.com/ws/HomerunDerby.asmx/GetMainPlayerList"
HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
    "Referer": "https://allstar.koreabaseball.com/Homerun/Main.aspx",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}


def fetch_homerun(retries=3):
    for attempt in range(retries):
        try:
            r = requests.post(URL, headers=HEADERS, data={}, timeout=15)
            r.raise_for_status()
            data = r.json()
            # GetMainPlayerList는 ASMX 기본 포맷이면 {"d": {...}} 로 감싸져 올 수도 있으므로 둘 다 대응
            if isinstance(data, dict) and "d" in data and isinstance(data["d"], dict):
                data = data["d"]
            return data
        except Exception as e:
            print(f"❌ 홈런더비 수집 시도 {attempt+1}/{retries} 실패: {e}")
    return None


def normalize(raw):
    now = datetime.now(KST)
    result = {
        "timestamp": now.isoformat(),
        "state": raw.get("state") if raw else None,
        "updateDtTm": raw.get("updateDtTm", "") if raw else "",
        "playerList": [],
    }

    if not raw:
        return result, now

    for p in raw.get("playerList", []):
        try:
            votes = int(str(p.get("voteCn", "0")).replace(",", "") or 0)
        except Exception:
            votes = 0
        result["playerList"].append({
            "pNm": p.get("pNm", ""),
            "pId": p.get("pId", ""),
            "seasonId": p.get("seasonId", ""),
            "tId": p.get("tId", ""),
            "tNm": p.get("tNm", ""),
            "rankNo": int(p.get("rankNo", 0) or 0),
            "votes": votes,
        })

    return result, now


def save(result, now):
    os.makedirs("data_homerun", exist_ok=True)
    filename = f"data_homerun/{now.strftime('%Y-%m-%d_%H-%M-%S')}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n💾 홈런더비 저장 완료: {filename}")
    return filename


if __name__ == "__main__":
    raw = fetch_homerun()
    result, now = normalize(raw)
    if raw is None:
        print("⚠️ 홈런더비 데이터 수집 실패 (raw=None) - 빈 스냅샷 저장")
    else:
        print(f"✅ 홈런더비 수집 완료 (state={result['state']}, 선수 {len(result['playerList'])}명)")
    save(result, now)
