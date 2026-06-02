import requests
import json
import os
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
POSITIONS = {
    'SP': '선발투수', 'MP': '중간투수', 'CP': '마무리투수',
    'C': '포수', '1B': '1루수', '2B': '2루수', '3B': '3루수',
    'SS': '유격수', 'OF': '외야수', 'DH': '지명타자'
}
URL = "https://allstar.koreabaseball.com/ws/Allstar.asmx/GetKboAll"
HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
    "Referer": "https://allstar.koreabaseball.com/Default.aspx",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

def fetch_all():
    now = datetime.now(KST)
    result = {
        "timestamp": now.isoformat(),
        "positions": {}
    }

    for pos_id, pos_name in POSITIONS.items():
        try:
            r = requests.post(URL, headers=HEADERS, data={"pos": pos_id}, timeout=15)
            r.raise_for_status()
            data = r.json()

            if data.get("code") == "100":
                result["positions"][pos_id] = {
                    "name": pos_name,
                    "nanum": data["arrWE"],  # 나눔 올스타
                    "dream": data["arrEA"],  # 드림 올스타
                }
                print(f"✅ {pos_name} 수집 완료")
            else:
                print(f"⚠️  {pos_name} 응답 코드 오류: {data.get('code')}")

        except Exception as e:
            print(f"❌ {pos_name} 수집 실패: {e}")

    return result, now

def save(result, now):
    os.makedirs("data", exist_ok=True)
    filename = f"data/{now.strftime('%Y-%m-%d_%H-%M')}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n💾 저장 완료: {filename}")
    return filename

if __name__ == "__main__":
    result, now = fetch_all()
    save(result, now)