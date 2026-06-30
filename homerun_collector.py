"""
2026 KBO 올스타 홈런더비 투표 수집기.

allstar.koreabaseball.com의 홈런더비 메인 페이지(Homerun/Main.aspx)가
내부적으로 호출하는 ASMX 웹서비스를 그대로 서버사이드에서 호출한다.
(collector.py가 GetKboAll을 호출하는 방식과 동일한 패턴)

예상 응답 형태 (Main.aspx의 setVoteState() 참고):
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

다만 ASMX 웹서비스는 환경에 따라 {"d": ...} 로 한 번 더 감싸거나,
"d" 값 자체가 JSON 문자열로 이중 인코딩되어 오는 경우가 흔하다.
이 스크립트는 그런 변형들을 모두 흡수하고, 그래도 알아볼 수 없는 형태면
원본 응답을 그대로 디버그용으로 저장한다 (스크립트가 죽지 않고 항상 파일을 남김).
"""
import requests
import json
import os
import traceback
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

URL = "https://allstar.koreabaseball.com/ws/HomerunDerby.asmx/GetMainPlayerList"
HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
    "Referer": "https://allstar.koreabaseball.com/Homerun/Main.aspx",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}


def unwrap(data):
    """ASMX의 {"d": ...} 래핑과 이중 JSON 인코딩을 모두 풀어서 dict로 반환 시도."""
    for _ in range(3):  # 중첩 래핑 대비 최대 3단계까지 풀어본다
        if isinstance(data, dict) and "d" in data and len(data) == 1:
            data = data["d"]
            continue
        if isinstance(data, str):
            try:
                data = json.loads(data)
                continue
            except Exception:
                break
        break
    return data


def fetch_homerun(retries=3):
    """
    반환값: (parsed_dict_or_None, debug_info)
    debug_info에는 실패 시 원인 파악용 원본 텍스트 일부가 담긴다.
    """
    debug_info = {}
    for attempt in range(retries):
        try:
            r = requests.post(URL, headers=HEADERS, data={}, timeout=15)
            debug_info["http_status"] = r.status_code
            debug_info["raw_text_sample"] = r.text[:1000]
            r.raise_for_status()
            data = r.json()
            data = unwrap(data)
            if isinstance(data, dict):
                return data, debug_info
            debug_info["error"] = f"파싱 결과가 dict가 아님 (type={type(data).__name__})"
        except Exception as e:
            debug_info["error"] = f"{type(e).__name__}: {e}"
            print(f"❌ 홈런더비 수집 시도 {attempt+1}/{retries} 실패: {e}")
    return None, debug_info


def normalize(raw):
    now = datetime.now(KST)
    result = {
        "timestamp": now.isoformat(),
        "state": None,
        "updateDtTm": "",
        "playerList": [],
    }

    if not isinstance(raw, dict):
        return result, now

    result["state"] = raw.get("state")
    result["updateDtTm"] = raw.get("updateDtTm", "") or ""

    player_list = raw.get("playerList") or []
    if not isinstance(player_list, list):
        player_list = []

    for p in player_list:
        if not isinstance(p, dict):
            continue
        try:
            votes = int(str(p.get("voteCn", "0")).replace(",", "") or 0)
        except Exception:
            votes = 0
        try:
            rank_no = int(p.get("rankNo", 0) or 0)
        except Exception:
            rank_no = 0
        result["playerList"].append({
            "pNm": p.get("pNm", ""),
            "pId": p.get("pId", ""),
            "seasonId": p.get("seasonId", ""),
            "tId": p.get("tId", ""),
            "tNm": p.get("tNm", ""),
            "rankNo": rank_no,
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
    # 무슨 일이 있어도(예상치 못한 응답 형태, 네트워크 오류 등) 항상 파일 하나는 남긴다.
    # → 다음에 data_homerun/*.json을 열어보면 무엇이 잘못됐는지 바로 확인 가능.
    now = datetime.now(KST)
    result = {
        "timestamp": now.isoformat(),
        "state": None,
        "updateDtTm": "",
        "playerList": [],
    }
    try:
        raw, debug_info = fetch_homerun()
        result, now = normalize(raw)
        if raw is None:
            result["_debug"] = debug_info
            print(f"⚠️ 홈런더비 데이터 수집 실패 - 디버그 정보 포함하여 저장: {debug_info}")
        else:
            print(f"✅ 홈런더비 수집 완료 (state={result['state']}, 선수 {len(result['playerList'])}명)")
    except Exception:
        result["_debug"] = {"fatal_error": traceback.format_exc()}
        print("❌ 홈런더비 수집기에서 처리되지 않은 예외 발생:")
        print(traceback.format_exc())

    save(result, now)
