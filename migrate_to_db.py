"""
올스타 투표 스냅샷(data/*.json, 약 2,894개)을 SQLite 단일 파일(data/allstar_votes.db)로 합친다.

올스타 투표는 마감되어 더 이상 새 스냅샷이 추가되지 않으므로, 이 작업은 1회만 실행하면 된다.
실행 후에는 chart_builder.py의 load_all_data()가 자동으로 이 DB 파일을 우선 사용한다
(DB가 없으면 기존처럼 data/*.json을 직접 읽는 방식으로 자동 폴백하므로 안전하다).

사용법:
    python migrate_to_db.py            # data/allstar_votes.db 생성
    python migrate_to_db.py --verify   # 생성 후 기존 JSON 로딩 결과와 레코드 수 비교 검증
"""
import json
import glob
import os
import sqlite3
import sys
from datetime import datetime

POSITIONS = {
    'SP': '선발투수', 'MP': '중간투수', 'CP': '마무리투수',
    'C': '포수', '1B': '1루수', '2B': '2루수', '3B': '3루수',
    'SS': '유격수', 'OF': '외야수', 'DH': '지명타자'
}

DB_PATH = "data/allstar_votes.db"


def iter_records():
    files = sorted(glob.glob("data/*.json"))
    print(f"📂 {len(files)}개 JSON 파일 발견")

    for i, f in enumerate(files, 1):
        try:
            with open(f, encoding="utf-8") as fp:
                d = json.load(fp)
            ts = d.get("timestamp", "")
            if not ts:
                continue
            dt = datetime.fromisoformat(ts)
            dt_str = dt.isoformat()

            for pos_id, pos_data in d.get("positions", {}).items():
                for team_key in ("nanum", "dream"):
                    for p in pos_data.get(team_key, []):
                        try:
                            votes = int(str(p.get("VOTE_CN", "0")).replace(",", "") or 0)
                        except Exception:
                            votes = 0
                        yield (
                            dt_str,
                            pos_id,
                            POSITIONS.get(pos_id, pos_id),
                            team_key,
                            p.get("P_NM", ""),
                            p.get("T_NM", ""),
                            int(p.get("RANK_CN", 0) or 0),
                            votes,
                        )
        except Exception as e:
            print(f"⚠️ 파일 로드 오류 {f}: {e}")
            continue

        if i % 500 == 0:
            print(f"  ...{i}/{len(files)} 처리 중")


def migrate():
    os.makedirs("data", exist_ok=True)
    if os.path.exists(DB_PATH):
        print(f"⚠️ {DB_PATH} 가 이미 존재합니다. 덮어쓰려면 먼저 삭제 후 다시 실행하세요.")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE votes (
            datetime TEXT NOT NULL,
            pos_id   TEXT NOT NULL,
            pos_name TEXT NOT NULL,
            team     TEXT NOT NULL,
            player   TEXT NOT NULL,
            club     TEXT NOT NULL,
            rank     INTEGER NOT NULL,
            votes    INTEGER NOT NULL
        )
    """)
    cur.execute("CREATE INDEX idx_votes_datetime ON votes(datetime)")

    batch = []
    total = 0
    for rec in iter_records():
        batch.append(rec)
        if len(batch) >= 5000:
            cur.executemany(
                "INSERT INTO votes VALUES (?,?,?,?,?,?,?,?)", batch
            )
            total += len(batch)
            batch = []
    if batch:
        cur.executemany("INSERT INTO votes VALUES (?,?,?,?,?,?,?,?)", batch)
        total += len(batch)

    conn.commit()
    conn.close()

    db_size_mb = os.path.getsize(DB_PATH) / (1024 * 1024)
    print(f"\n✅ 마이그레이션 완료: {DB_PATH} ({total:,}개 레코드, {db_size_mb:.1f}MB)")
    print("   data/*.json 파일들은 그대로 두었습니다. 검증 후 직접 정리해주세요.")


def verify():
    """기존 방식(JSON 직접 파싱)과 DB 로딩 결과의 레코드 수가 일치하는지 확인."""
    if not os.path.exists(DB_PATH):
        print(f"❌ {DB_PATH} 가 없습니다. 먼저 마이그레이션을 실행하세요.")
        sys.exit(1)

    json_count = sum(1 for _ in iter_records())

    conn = sqlite3.connect(DB_PATH)
    db_count = conn.execute("SELECT COUNT(*) FROM votes").fetchone()[0]
    conn.close()

    print(f"JSON 직접 파싱 레코드 수: {json_count:,}")
    print(f"DB 레코드 수:           {db_count:,}")
    if json_count == db_count:
        print("✅ 일치합니다.")
    else:
        print("❌ 불일치! 마이그레이션을 다시 확인하세요.")
        sys.exit(1)


if __name__ == "__main__":
    if "--verify" in sys.argv:
        verify()
    else:
        migrate()
