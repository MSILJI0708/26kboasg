import json
import glob
import os
from datetime import datetime, timedelta
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

POSITIONS = {
    'SP': '선발투수', 'MP': '중간투수', 'CP': '마무리투수',
    'C': '포수', '1B': '1루수', '2B': '2루수', '3B': '3루수',
    'SS': '유격수', 'OF': '외야수', 'DH': '지명타자'
}

TEAM_COLORS = {
    'LG': '#C30452', 'KT': '#E84C4C', 'SSG': '#CE0E2D', 'NC': '#1D5D9B',
    '두산': '#3F48CC', 'KIA': '#EA0029', '롯데': '#ED6D00', '삼성': '#74A9FF',
    '한화': '#FF6600', '키움': '#FF4D7D'
}

TEAM_MARKERS = {
    'LG':   {'symbol': 'circle',      'dash': 'solid'},
    'KT':   {'symbol': 'square',      'dash': 'solid'},
    'SSG':  {'symbol': 'diamond',     'dash': 'dash'},
    'NC':   {'symbol': 'triangle-up', 'dash': 'solid'},
    '두산': {'symbol': 'circle',      'dash': 'dash'},
    'KIA':  {'symbol': 'square',      'dash': 'dash'},
    '롯데': {'symbol': 'diamond',     'dash': 'solid'},
    '삼성': {'symbol': 'triangle-up', 'dash': 'solid'},
    '한화': {'symbol': 'circle',      'dash': 'dot'},
    '키움': {'symbol': 'square',      'dash': 'dot'},
}

# 제거할 초기 테스트 데이터 파일들 (비정기 수집, 굵은 선 원인)
# 2026-06-03에 수집 주기가 정착하기 전의 드문드문 파일들
SKIP_BEFORE = "2026-06-03T15:00:00"

def load_all_data(days=7):
    files = sorted(glob.glob("data/*.json"))
    cutoff = datetime.now().astimezone() - timedelta(days=days)
    skip_dt = datetime.fromisoformat(SKIP_BEFORE).astimezone()

    files = [f for f in files if datetime.fromisoformat(
        json.load(open(f, encoding="utf-8")).get("timestamp", "1970-01-01T00:00:00+09:00")
    ) >= cutoff] if days else files

    records = []
    for f in files:
        try:
            with open(f, encoding="utf-8") as fp:
                d = json.load(fp)
            ts = d.get("timestamp", "")
            if not ts:
                continue
            dt = datetime.fromisoformat(ts)
            # 초기 테스트 수집 기간 데이터 스킵
            if dt.astimezone() < skip_dt:
                continue
            for pos_id, pos_data in d["positions"].items():
                for team_key in ("nanum", "dream"):
                    for p in pos_data.get(team_key, []):
                        try:
                            votes = int(p.get("VOTE_CN", "0").replace(",", ""))
                        except:
                            votes = 0
                        records.append({
                            "datetime": dt,
                            "pos_id": pos_id,
                            "pos_name": POSITIONS.get(pos_id, pos_id),
                            "team": team_key,
                            "player": p.get("P_NM", ""),
                            "club": p.get("T_NM", ""),
                            "rank": int(p.get("RANK_CN", 0)),
                            "votes": votes,
                        })
        except Exception as e:
            print(f"파일 로드 오류 {f}: {e}")
            continue
    return pd.DataFrame(records)

def calc_total_votes_per_snapshot(df):
    # 드림팀 한 포지션(SP)의 전체 득표합 = 해당 스냅샷의 실제 총투표수
    # (포지션별 투표가 독립적이므로 SP dream 전체합이 총투표 대리값)
    sp_dream = df[(df["pos_id"] == "SP") & (df["team"] == "dream")]
    return sp_dream.groupby("datetime")["votes"].sum().reset_index()

def calc_new_votes(df):
    df = df.sort_values("datetime")
    df["new_votes"] = df.groupby(["pos_id", "team", "player"])["votes"].diff().fillna(0).clip(lower=0)
    return df

def calc_vote_rate(df):
    # 나눔/드림 각각의 포지션 내 득표율 (team을 모수 기준에 포함)
    total = df.groupby(["datetime", "pos_id", "team"])["votes"].transform("sum")
    df["vote_rate"] = (df["votes"] / total * 100).round(2)
    return df

def preaggregate(df):
    """
    JS 렉 방지: 포지션×팀 기준으로만 1회 집계 (중복 저장 없음).
    구단별 모드는 JS에서 이 pos_* 데이터를 club으로 가볍게 필터링해서 재사용한다.
    (포지션 1개당 보통 10구단×5명=50건, 외야는 10구단×15명=150건 수준이라 필터링 비용이 작다)
    """
    agg = {}
    cols_pos = ['datetime', 'pos_id', 'player', 'club', 'votes', 'vote_rate', 'new_votes', 'rank']

    for pos_id in df['pos_id'].unique():
        for team in ('nanum', 'dream'):
            sub = df[(df['pos_id'] == pos_id) & (df['team'] == team)]
            agg[f"pos_{pos_id}_{team}"] = sub[cols_pos].to_dict('records')

    return agg


def build_chart(df):
    df = calc_new_votes(df)
    df = calc_vote_rate(df)
    total_per_snap = calc_total_votes_per_snapshot(df)
    total_per_snap = total_per_snap.sort_values("datetime")
    total_per_snap["new_total"] = total_per_snap["votes"].diff().fillna(0).clip(lower=0)

    # ── 사전 집계 (JS 렉 방지) ──
    agg_data = preaggregate(df)
    agg_data_clean = {
        k: [{kk: (str(vv) if hasattr(vv, 'isoformat') else vv) for kk, vv in row.items()} for row in v]
        for k, v in agg_data.items()
    }
    # lazy-load: 키별로 별도 <script type="application/json"> 태그 생성.
    # 브라우저가 페이지 로드 시 자동으로 파싱/실행하지 않으므로 초기 로딩 비용이 거의 0.
    # 포지션 탭을 열 때 JS에서 해당 id만 JSON.parse 한다.
    agg_data_scripts = "\n".join(
        f'<script type="application/json" id="agg-{k}">{json.dumps(v, ensure_ascii=False)}</script>'
        for k, v in agg_data_clean.items()
    )
    # 키 목록만 가벼운 JS 배열로 별도 전달 (어떤 포지션×팀 키가 존재하는지 확인용)
    agg_keys_js = json.dumps(list(agg_data_clean.keys()), ensure_ascii=False)

    # ── 신한은행 vs 공식 비교 데이터 (사전 계산된 결과 파일 임베드) ──
    shinhan_compare_path = "shinhan_compare_data.json"
    if os.path.exists(shinhan_compare_path):
        with open(shinhan_compare_path, encoding="utf-8") as f:
            shinhan_compare = json.load(f)
        shinhan_compare_js = json.dumps(shinhan_compare, ensure_ascii=False)
    else:
        shinhan_compare_js = "null"

    team_colors_js = json.dumps(
        {v: TEAM_COLORS.get(v, '#4a6fa5') for v in df['club'].unique().tolist() if isinstance(v, str)},
        ensure_ascii=False
    )
    team_markers_js = json.dumps(
        {v: TEAM_MARKERS.get(v, {'symbol': 'circle', 'dash': 'solid'}) for v in df['club'].unique().tolist() if isinstance(v, str)},
        ensure_ascii=False
    )

    # 실제 데이터 범위 계산 → 초기 x축 범위로 사용
    dt_min = df['datetime'].min()
    dt_max = df['datetime'].max()
    from datetime import timedelta
    x_range_start = (dt_min - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M')
    x_range_end   = (dt_max + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M')

    last_updated = df['datetime'].max().strftime('%Y-%m-%d %H:%M') if not df.empty else '-'

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>2026 KBO 올스타 투표 현황</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
  /* ── 다크/라이트 CSS 변수 ── */
  :root {{
    --bg:          #0a0e1a;
    --bg2:         #111520;
    --bg3:         #151929;
    --border:      #1e2640;
    --border2:     #2a3050;
    --text:        #e0e6f0;
    --text-muted:  #6b7a99;
    --text-dim:    #a0b0d0;
    --text-hint:   #4a6070;
    --active-bg:   #2a4a8a;
    --active-text: #fff;
    --grid:        #1e2640;
    --grid2:       #2a3050;
    --kbd-bg:      #1e2a40;
    --kbd-border:  #3a4a6a;
    --kbd-text:    #8090b0;
    --hover-bg:    #1a2030;
    --hover-border:#2a3050;
    --hover-text:  #e0e6f0;
    --link:        #4a9eff;
  }}
  body.light-mode {{
    --bg:          #f0f4fa;
    --bg2:         #ffffff;
    --bg3:         #e8edf5;
    --border:      #ccd6e8;
    --border2:     #b0bdd4;
    --text:        #1a2540;
    --text-muted:  #5a6a88;
    --text-dim:    #3a4a6a;
    --text-hint:   #7a8aaa;
    --active-bg:   #2a5ab8;
    --active-text: #fff;
    --grid:        #dde5f0;
    --grid2:       #c8d4e8;
    --kbd-bg:      #dde5f0;
    --kbd-border:  #b0bdd4;
    --kbd-text:    #5a6a88;
    --hover-bg:    #f5f8ff;
    --hover-border:#b0bdd4;
    --hover-text:  #1a2540;
    --link:        #1a6fd4;
  }}

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: 'Pretendard', 'Noto Sans KR', sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    padding: 16px;
    transition: background 0.2s, color 0.2s;
  }}
  h1 {{
    font-size: 1.3rem;
    font-weight: 700;
    color: var(--active-text);
    margin-bottom: 8px;
    text-align: center;
    letter-spacing: -0.5px;
  }}
  body.light-mode h1 {{ color: var(--text); }}
  .header-links {{
    text-align: center;
    margin-bottom: 8px;
  }}
  .header-links a {{
    color: var(--link);
    text-decoration: none;
    font-size: 0.8rem;
    margin: 0 8px;
    opacity: 0.8;
  }}
  .header-links a:hover {{ opacity: 1; text-decoration: underline; }}
  .updated {{
    font-size: 0.75rem;
    color: var(--text-muted);
    text-align: center;
    margin-bottom: 20px;
  }}
  .controls {{
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-bottom: 16px;
    align-items: center;
  }}
  .control-group {{
    display: flex;
    flex-direction: column;
    gap: 4px;
  }}
  .control-group label {{
    font-size: 0.7rem;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }}
  select, .toggle-group {{
    background: var(--bg3);
    border: 1px solid var(--border2);
    color: var(--text);
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 0.85rem;
    cursor: pointer;
    outline: none;
  }}
  select:focus {{ border-color: var(--active-bg); }}
  .toggle-group {{
    display: flex;
    gap: 0;
    padding: 0;
    overflow: hidden;
  }}
  .toggle-btn {{
    padding: 6px 12px;
    font-size: 0.8rem;
    cursor: pointer;
    border: none;
    background: var(--bg3);
    color: var(--text-muted);
    transition: all 0.2s;
  }}
  .toggle-btn.active {{
    background: var(--active-bg);
    color: var(--active-text);
  }}
  .chart-container {{
    background: var(--bg2);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 12px;
    margin-bottom: 16px;
  }}
  .chart-title {{
    font-size: 0.9rem;
    font-weight: 600;
    color: var(--text-dim);
    margin-bottom: 8px;
    padding-left: 4px;
  }}
  .zoom-hint {{
    font-size: 0.7rem;
    color: var(--text-hint);
    text-align: right;
    padding-right: 4px;
    margin-bottom: 4px;
  }}
  .zoom-hint kbd {{
    background: var(--kbd-bg);
    border: 1px solid var(--kbd-border);
    border-radius: 3px;
    padding: 0px 4px;
    font-size: 0.65rem;
    font-family: monospace;
    color: var(--kbd-text);
  }}
  .divider {{
    border: none;
    border-top: 1px solid var(--border);
    margin: 20px 0;
  }}

  /* ── 라이트모드 토글 버튼 (우상단 고정) ── */
  #theme-toggle {{
    position: fixed;
    top: 12px;
    right: 12px;
    z-index: 9999;
    background: var(--bg3);
    border: 1px solid var(--border2);
    color: var(--text);
    border-radius: 20px;
    padding: 5px 11px;
    font-size: 0.8rem;
    cursor: pointer;
    box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    transition: all 0.2s;
    white-space: nowrap;
  }}
  #theme-toggle:hover {{ border-color: var(--active-bg); }}

  /* ── 모바일 툴팁 토글 버튼 (우하단 고정, 모바일 only) ── */
  #hover-toggle {{
    display: none;               /* JS가 모바일 감지 시 flex로 변경 */
    position: fixed;
    bottom: 20px;
    right: 12px;
    z-index: 9999;
    background: var(--active-bg);
    color: #fff;
    border: none;
    border-radius: 24px;
    padding: 10px 16px;
    font-size: 0.85rem;
    font-weight: 600;
    cursor: pointer;
    box-shadow: 0 3px 14px rgba(0,0,0,0.45);
    letter-spacing: -0.2px;
    transition: background 0.2s, box-shadow 0.2s;
    -webkit-tap-highlight-color: transparent;
    align-items: center;
    gap: 6px;
  }}
  #hover-toggle:active {{ opacity: 0.8; }}
  #hover-toggle.visible {{ display: flex; }}
  #hover-toggle.tooltip-hidden {{
    background: var(--bg3);
    color: var(--text-muted);
    border: 1px solid var(--border2);
  }}

  /* 모바일 전용: 좌우 여백을 최소화해 차트가 화면 폭을 최대한 차지하게 함 */
  @media (max-width: 768px) {{
    body {{ padding: 8px; }}
    .chart-container {{ padding: 10px 4px; }}
    .chart-title {{ padding-left: 6px; }}
  }}

  /* 모바일/데스크탑별 zoom-hint 텍스트 분기 */
  @media (pointer: coarse) {{
    .zoom-hint .desktop-hint {{ display: none; }}
    .zoom-hint .mobile-hint  {{ display: inline; }}
  }}
  @media (pointer: fine) {{
    .zoom-hint .desktop-hint {{ display: inline; }}
    .zoom-hint .mobile-hint  {{ display: none; }}
  }}

  /* ── 모바일 전용: 선수 on/off 토글 칩 패널 ── */
  .player-toggle-panel {{
    margin: 4px 0 14px 0;
    padding: 10px 10px 8px 10px;
    background: var(--bg3);
    border: 1px solid var(--border2);
    border-radius: 10px;
  }}
  .player-toggle-hint {{
    font-size: 0.72rem;
    color: var(--text-muted);
    margin-bottom: 8px;
  }}
  .player-toggle-row {{
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 6px;
    margin-bottom: 8px;
  }}
  .player-toggle-chip {{
    display: flex;
    align-items: center;
    gap: 6px;
    width: 100%;
    box-sizing: border-box;
    padding: 7px 9px;
    border-radius: 8px;
    border: 1px solid var(--border2);
    background: var(--bg2);
    color: var(--text);
    font-size: 0.72rem;
    font-weight: 600;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
    transition: opacity .15s, background .15s;
    overflow: hidden;
  }}
  .player-toggle-chip span:not(.chip-dot) {{
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }}
  .player-toggle-chip .chip-dot {{
    width: 9px; height: 9px; border-radius: 50%;
    flex-shrink: 0;
  }}
  .player-toggle-chip.off {{
    opacity: 0.4;
    background: var(--bg3);
    text-decoration: line-through;
  }}
  .player-toggle-actions {{
    display: flex;
    gap: 8px;
    padding-top: 6px;
    border-top: 1px solid var(--border2);
  }}
  .player-toggle-action-btn {{
    flex: 1;
    padding: 7px 0;
    border-radius: 6px;
    border: 1px solid var(--border2);
    background: transparent;
    color: var(--text-muted);
    font-size: 0.75rem;
    font-weight: 600;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
  }}
  .player-toggle-action-btn:active {{
    background: var(--bg2);
  }}
</style>
</head>
<body>

<!-- 라이트/다크 모드 토글 (우상단 고정) -->
<button id="theme-toggle" onclick="toggleTheme()" title="라이트/다크 모드 전환">🌙 다크</button>

<!-- 모바일 전용: 호버 팝업 숨김/표시 버튼 (JS에서 모바일 감지 시 visible) -->
<button id="hover-toggle" onclick="toggleHoverLabel()" title="툴팁 숨기기/보이기">👁 툴팁 끄기</button>

<h1>⚾ 2026 KBO 올스타 팬투표 현황</h1>
<div class="header-links">
  <a href="https://allstar.koreabaseball.com/Allstar/Vote.aspx" target="_blank" rel="noopener">🔗 KBO 공식 투표</a>
  <a href="https://github.com/your-repo" target="_blank" rel="noopener" id="github-link">📁 GitHub</a>
</div>
<div class="updated">마지막 업데이트: {last_updated} KST</div>

<!-- ══════════════════════════════════════════════
     최상단 모드 탭: 실시간 집계 / 중간집계(신한) 비교
     ══════════════════════════════════════════════ -->
<div class="main-tabs">
  <button class="main-tab-btn active" id="main-tab-live"     onclick="setMainTab('live')">📡 실시간 집계</button>
  <button class="main-tab-btn"        id="main-tab-shinhan"  onclick="setMainTab('shinhan')">🏦 중간집계 비교</button>
</div>

<!-- ══════════════════════════════════════════════
     실시간 집계 탭 콘텐츠
     ══════════════════════════════════════════════ -->
<div id="main-panel-live">

<div class="controls">
  <div class="control-group" id="selector-group">
    <label id="selector-label">포지션</label>
    <select id="posSelect" onchange="updateCharts()">
      {''.join(f'<option value="{k}">{v}</option>' for k, v in POSITIONS.items())}
    </select>
    <select id="clubSelect" onchange="updateCharts()" style="display:none">
      {''.join(f'<option value="{c}">{c}</option>' for c in ['KIA','KT','LG','NC','SSG','두산','롯데','삼성','키움','한화'])}
    </select>
  </div>
  <div class="control-group">
    <label>표시 방식</label>
    <div class="toggle-group">
      <button class="toggle-btn active" id="btn-rate" onclick="setMetric('rate')">득표율</button>
      <button class="toggle-btn" id="btn-votes" onclick="setMetric('votes')">득표수</button>
      <button class="toggle-btn" id="btn-new" onclick="setMetric('new')">신규득표</button>
    </div>
  </div>
  <div class="control-group">
    <label>시간 단위</label>
    <div class="toggle-group">
      <button class="toggle-btn" id="btn-10min" onclick="setTimeUnit('10min')">10분</button>
      <button class="toggle-btn active" id="btn-1hour" onclick="setTimeUnit('1hour')">1시간</button>
      <button class="toggle-btn" id="btn-1day" onclick="setTimeUnit('1day')">1일</button>
    </div>
  </div>
  <div class="control-group">
    <label>보기 방식</label>
    <div class="toggle-group">
      <button class="toggle-btn active" id="btn-bypos" onclick="setViewMode('position')">포지션별</button>
      <button class="toggle-btn" id="btn-byclub" onclick="setViewMode('club')">구단별</button>
    </div>
  </div>
</div>

<div id="pos-section">
<div class="chart-container">
  <div class="chart-title" id="title-nanum">🔵 나눔 올스타</div>
  <div class="zoom-hint">
    <span class="desktop-hint">🖱 스크롤: 전체 줌 · 드래그: 이동 · x축 드래그↔: 시간축 줌 · y축 드래그↕: 값축 줌</span>
    <span class="mobile-hint">👆 1핑거: 이동 · 핀치: 시간축 줌 · 더블탭: 초기화 · 우하단 버튼: 툴팁 ON/OFF</span>
  </div>
  <div id="chart-nanum"></div>
</div>

<div class="chart-container">
  <div class="chart-title" id="title-dream">🔴 드림 올스타</div>
  <div class="zoom-hint">
    <span class="desktop-hint">🖱 스크롤: 전체 줌 · 드래그: 이동 · x축 드래그↔: 시간축 줌 · y축 드래그↕: 값축 줌</span>
    <span class="mobile-hint">👆 1핑거: 이동 · 핀치: 시간축 줌 · 더블탭: 초기화 · 우하단 버튼: 툴팁 ON/OFF</span>
  </div>
  <div id="chart-dream"></div>
</div>
</div>

<div id="of-section" style="display:none">
  <div class="chart-container">
    <div class="zoom-hint">
    <span class="desktop-hint">🖱 스크롤: 전체 줌 · 드래그: 이동 · x축 드래그↔: 시간축 줌 · y축 드래그↕: 값축 줌</span>
    <span class="mobile-hint">👆 1핑거: 이동 · 핀치: 시간축 줌 · 더블탭: 초기화 · 우하단 버튼: 툴팁 ON/OFF</span>
  </div>
    <div id="chart-of-nanum"></div>
  </div>
  <div class="chart-container">
    <div class="zoom-hint">
    <span class="desktop-hint">🖱 스크롤: 전체 줌 · 드래그: 이동 · x축 드래그↔: 시간축 줌 · y축 드래그↕: 값축 줌</span>
    <span class="mobile-hint">👆 1핑거: 이동 · 핀치: 시간축 줌 · 더블탭: 초기화 · 우하단 버튼: 툴팁 ON/OFF</span>
  </div>
    <div id="chart-of-dream"></div>
  </div>
  <div class="chart-container" id="of2-nanum-wrap">
    <div class="zoom-hint">
    <span class="desktop-hint">🖱 스크롤: 전체 줌 · 드래그: 이동 · x축 드래그↔: 시간축 줌 · y축 드래그↕: 값축 줌</span>
  </div>
    <div id="chart-of2-nanum"></div>
  </div>
  <div class="chart-container" id="of2-dream-wrap">
    <div class="zoom-hint">
    <span class="desktop-hint">🖱 스크롤: 전체 줌 · 드래그: 이동 · x축 드래그↔: 시간축 줌 · y축 드래그↕: 값축 줌</span>
  </div>
    <div id="chart-of2-dream"></div>
  </div>
</div>

<hr class="divider">

<div class="chart-container">
  <div class="chart-title">📊 전체 투표수 추이</div>
  <div class="zoom-hint">
    <span class="desktop-hint">🖱 스크롤: 전체 줌 · 드래그: 이동 · x축 드래그↔: 시간축 줌 · y축 드래그↕: 값축 줌</span>
    <span class="mobile-hint">👆 1핑거: 이동 · 핀치: 시간축 줌 · 더블탭: 초기화 · 우하단 버튼: 툴팁 ON/OFF</span>
  </div>
  <div id="chart-total"></div>
</div>

</div> <!-- /#main-panel-live -->

<!-- ══════════════════════════════════════════════
     포지션×팀 데이터 lazy-load 저장소
     application/json 타입은 브라우저가 자동 파싱/실행하지 않으므로
     초기 페이지 로드 비용이 거의 없다. 필요한 키만 그때그때 JSON.parse.
     ══════════════════════════════════════════════ -->
{agg_data_scripts}

<!-- ══════════════════════════════════════════════
     중간집계(신한) 비교 탭 콘텐츠
     ══════════════════════════════════════════════ -->
<div id="main-panel-shinhan" style="display:none">

<div class="chart-container" id="shinhan-section">
  <div class="chart-title">🏦 신한 SOL트래블 vs 공식 비교 <span style="font-size:0.8rem;font-weight:400;color:var(--text-muted)">(1차 6/7 14시 · 2차 6/14 14시, 선수별 1차공식·1차신한·2차공식·2차신한)</span></div>

  <div style="display:flex;gap:6px;margin-bottom:8px;">
    <button id="sh-team-nanum" class="sh-team-btn" onclick="setShinhanTeam('nanum')">🔵 나눔</button>
    <button id="sh-team-dream" class="sh-team-btn" onclick="setShinhanTeam('dream')">🔴 드림</button>
  </div>
  <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px;" id="shinhan-pos-tabs"></div>

  <div id="chart-shinhan"></div>
  <div id="shinhan-note" style="font-size:0.75rem;color:var(--text-muted);margin-top:6px;"></div>
</div>

</div> <!-- /#main-panel-shinhan -->

<style>
  .main-tabs {{
    display:flex; gap:8px; margin: 16px 0 20px 0;
  }}
  .main-tab-btn {{
    padding:10px 20px;border-radius:8px;border:1px solid var(--border2);
    background:var(--bg3);color:var(--text-muted);cursor:pointer;
    font-size:0.95rem;font-weight:700;transition:all .15s;
  }}
  .main-tab-btn.active {{ background:var(--active-bg);color:#fff;border-color:var(--active-bg); }}
  .sh-team-btn {{
    padding:6px 14px;border-radius:6px;border:1px solid var(--border2);
    background:var(--bg3);color:var(--text-muted);cursor:pointer;
    font-size:0.85rem;font-weight:600;transition:all .15s;
  }}
  .sh-team-btn.active {{ background:var(--active-bg);color:#fff;border-color:var(--active-bg); }}
  .sh-pos-btn {{
    padding:5px 10px;border-radius:6px;border:1px solid var(--border2);
    background:var(--bg3);color:var(--text-muted);cursor:pointer;font-size:0.8rem;transition:all .15s;
  }}
  .sh-pos-btn.active {{ background:#6c5ce7;color:#fff;border-color:#6c5ce7; }}
</style>

<script>
// AGG 키 목록 (실제 데이터는 agg-(키이름) id의 script 태그에 분리 저장됨)
const AGG_KEYS = {agg_keys_js};
const _aggCache = {{}};

// 포지션×팀 데이터를 그때그때 파싱해서 가져오는 lazy-load 함수.
// 1회 파싱 후 메모리 캐시에 저장 (같은 포지션 재방문 시 재파싱 없음).
function getAggData(key) {{
  if (_aggCache[key]) return _aggCache[key];
  const el = document.getElementById(`agg-${{key}}`);
  if (!el) return [];
  const parsed = JSON.parse(el.textContent);
  _aggCache[key] = parsed;
  return parsed;
}}

const SHINHAN_COMPARE = {shinhan_compare_js};
const TEAM_COLORS_BASE = {team_colors_js};

// 구단 색상 조회 함수.
// KT는 다크모드에서는 흰색, 라이트모드에서는 검은색으로 테마에 따라 달라진다
// (그 외 구단은 고정색을 그대로 사용).
function getTeamColor(club) {{
  if (club === 'KT') {{
    const isLight = document.body.classList.contains('light-mode');
    return isLight ? '#1a1a1a' : '#ffffff';
  }}
  return TEAM_COLORS_BASE[club] || '#4a6fa5';
}}

// 기존 코드 호환용: TEAM_COLORS[club] 형태로 쓰던 곳들을 위한 Proxy.
// club 키로 접근하면 getTeamColor()를 호출해 테마별 색을 즉시 반환한다.
const TEAM_COLORS = new Proxy({{}}, {{
  get(_, club) {{ return getTeamColor(club); }}
}});
const TEAM_MARKERS = {team_markers_js};
const TOTAL_DATA = {total_per_snap.to_json(orient='records', date_format='iso', force_ascii=False)};

// 모바일 감지 (스크립트 최상단 — scrollZoomConfig 등에서 참조)
const IS_MOBILE = /Mobi|Android|iPhone|iPad|iPod/i.test(navigator.userAgent)
               || (window.matchMedia && window.matchMedia('(pointer:coarse)').matches);

let currentMetric = 'rate';
let currentTimeUnit = '1hour';
// 모바일이면 첫 로드 시 툴팁 숨김 (그래프 조작 방해 방지), 데스크탑은 표시
let hoverHidden = IS_MOBILE;

// ISO 문자열 그대로 반환 (Plotly date축 전용)
function toDateStr(isoStr) {{
  // UTC → KST (+9h) 보정한 뒤 'YYYY-MM-DD HH:MM' 형태로 반환
  const dt = new Date(new Date(isoStr).getTime() + 9 * 3600 * 1000);
  return dt.toISOString().slice(0, 16).replace('T', ' ');
}}

// 호버용 KST 표시 문자열 (기존 동일)
function toKST(isoStr) {{
  return toDateStr(isoStr);
}}

function setMetric(m) {{
  currentMetric = m;
  ['rate','votes','new'].forEach(x => document.getElementById('btn-'+x).classList.remove('active'));
  document.getElementById('btn-'+m).classList.add('active');
  updateCharts();
}}

function setTimeUnit(u) {{
  currentTimeUnit = u;
  ['10min','1hour','1day'].forEach(x => document.getElementById('btn-'+x).classList.remove('active'));
  document.getElementById('btn-'+u).classList.add('active');
  updateCharts();
}}

// 선수별 데이터 리샘플 (나눔/드림 차트용)
function resampleData(data, unit) {{
  if (unit === '10min') return data;
  const grouped = {{}};
  data.forEach(d => {{
    const dt = new Date(d.datetime);
    if (unit === '1hour') dt.setMinutes(0, 0, 0);
    else if (unit === '1day') dt.setHours(0, 0, 0, 0);
    const key = dt.toISOString() + '|' + (d.player || '');
    if (!grouped[key] || new Date(d.datetime) > new Date(grouped[key].datetime)) {{
      grouped[key] = {{ ...d, datetime: dt.toISOString() }};
    }}
  }});
  return Object.values(grouped);
}}

// 총투표 데이터 리샘플 (player 없이 시간대별 마지막 votes값 사용)
function resampleTotal(data, unit) {{
  if (unit === '10min') return [...data].sort((a,b) => new Date(a.datetime) - new Date(b.datetime));
  const grouped = {{}};
  data.forEach(d => {{
    const dt = new Date(d.datetime);
    if (unit === '1hour') dt.setMinutes(0, 0, 0);
    else if (unit === '1day') dt.setHours(0, 0, 0, 0);
    const key = dt.toISOString();
    // 해당 시간대의 마지막(최신) 값으로 갱신
    if (!grouped[key] || new Date(d.datetime) > new Date(grouped[key]._raw)) {{
      grouped[key] = {{ datetime: key, votes: d.votes, _raw: d.datetime }};
    }}
  }});
  return Object.values(grouped).sort((a,b) => new Date(a.datetime) - new Date(b.datetime));
}}

function calcNewVotes(playerData) {{
  const sorted = playerData.sort((a,b) => new Date(a.datetime) - new Date(b.datetime));
  return sorted.map((d, i) => {{
    const prev = sorted[i-1];
    return {{ ...d, new_votes: prev ? Math.max(0, d.votes - prev.votes) : 0 }};
  }});
}}

function getVal(d, metric) {{
  if (metric === 'rate') return d.vote_rate || 0;
  if (metric === 'votes') return d.votes || 0;
  return d.new_votes || 0;
}}

function unitToMs(unit) {{
  if (unit === '10min') return 10 * 60 * 1000;
  if (unit === '1hour') return 60 * 60 * 1000;
  if (unit === '1day') return 24 * 60 * 60 * 1000;
  return 60 * 60 * 1000;
}}

// 이전: 매 포인트마다 idx 이전 전체를 선형탐색 → O(n²), 10분 단위(점 1700+개)에서 렉 발생
// 변경: data가 시간순 정렬되어 있음을 이용해 이진탐색으로 targetTime 근처 인덱스를 바로 찾음 → O(log n)
function findPrevVal(data, idx, metric, unit) {{
  const curTime = new Date(data[idx].datetime).getTime();
  const targetTime = curTime - unitToMs(unit);

  // data[0..idx-1] 구간에서 시간이 targetTime 이하인 마지막 위치를 이진탐색
  let lo = 0, hi = idx - 1, pos = -1;
  while (lo <= hi) {{
    const mid = (lo + hi) >> 1;
    const t = new Date(data[mid].datetime).getTime();
    if (t <= targetTime) {{ pos = mid; lo = mid + 1; }}
    else {{ hi = mid - 1; }}
  }}

  // pos(targetTime 이하 마지막)와 pos+1(targetTime 초과 첫 값) 중 더 가까운 쪽 선택
  let closest = null, minDiff = Infinity;
  if (pos >= 0) {{
    const t = new Date(data[pos].datetime).getTime();
    const diff = Math.abs(t - targetTime);
    if (diff < minDiff) {{ minDiff = diff; closest = data[pos]; }}
  }}
  if (pos + 1 < idx) {{
    const t = new Date(data[pos + 1].datetime).getTime();
    const diff = Math.abs(t - targetTime);
    if (diff < minDiff) {{ minDiff = diff; closest = data[pos + 1]; }}
  }}

  if (!closest) return null;
  const diffMin = Math.round(minDiff / 60000);
  return {{ val: getVal(closest, metric), diffMin }};
}}

function buildTrace(playerData, metric, rankDash) {{
  const data = calcNewVotes(playerData);
  const name = data[0]?.player || '';
  const club = data[0]?.club || '';
  const color = TEAM_COLORS[club] || '#4a6fa5';
  const marker = TEAM_MARKERS[club] || {{ symbol: 'circle', dash: 'solid' }};
  // dash는 "구단 구분용"이 아니라 "차트 안 득표 순위 구분용"이다.
  // rankDash가 주어지면(1등=실선, 2등=듬성점선, 3등 이상=촘촘점선) 그것을 우선 사용한다.
  const dash = rankDash || marker.dash;

  const x = data.map(d => toKST(d.datetime));
  const y = data.map(d => getVal(d, metric));

  // 모바일은 화면이 좁아 끝점 구단 라벨이 차트 우측을 압박하므로 생략 (대신 토글 칩에 표시됨)
  const textArr = IS_MOBILE ? data.map(() => '') : data.map((_, i) => i === data.length - 1 ? club : '');

  const customdata = data.map((d, i) => {{
    const kst = toKST(d.datetime);
    if (metric === 'new') {{
      return [kst, ''];
    }}
    const prev = findPrevVal(data, i, metric, currentTimeUnit);
    if (!prev) return [kst, '-'];
    const diff = getVal(d, metric) - prev.val;
    const sign = diff >= 0 ? '▲' : '▼';
    const unit = metric === 'rate' ? '%p' : '표';
    const diffStr = metric === 'rate'
      ? `${{sign}}${{Math.abs(diff).toFixed(2)}}${{unit}}`
      : `${{sign}}${{Math.abs(Math.round(diff)).toLocaleString()}}${{unit}}`;
    const note = prev.diffMin > 20 ? ` (${{prev.diffMin}}분 기준)` : '';
    return [kst, diffStr + note];
  }});

  const valFmt = metric === 'rate' ? '%{{y:.2f}}' : '%{{y:,}}';
  const valLabel = metric === 'rate' ? '%' : '표';

  // 포인트가 많으면 마커 숨김 (선만 표시) — 빽빽한 점이 굵은 선처럼 보이는 현상 방지
  // 1시간 단위 이하면 포인트가 많아 마커 불필요, 1일 단위만 마커 표시
  const showMarkers = currentTimeUnit === '1day' || data.length <= 50;
  const traceMode = showMarkers ? 'lines+markers+text' : 'lines+text';
  const markerSize = showMarkers ? 6 : 0;

  return {{
    x, y,
    customdata,
    name: `${{name}} (${{club}})`,
    type: 'scatter',
    mode: traceMode,
    line: {{ color, width: 2, dash: dash }},
    marker: {{ size: markerSize, color, symbol: marker.symbol }},
    text: textArr,
    textposition: 'middle right',
    textfont: {{ size: 10, color }},
    hovertemplate: `<span style="color:${{color}}">●</span> <b>${{name}} (${{club}})</b>: ${{valFmt}}${{valLabel}}  %{{customdata[1]}}<extra></extra>`
  }};
}}

// 화면 픽셀 기반으로 dtick 계산
// spanMs: 현재 x축 범위(ms), pxWidth: 차트 플롯 영역 픽셀 너비, minPx: 눈금 최소 간격(px)
function calcDtickByPixel(spanMs, pxWidth, minPx) {{
  if (!pxWidth || pxWidth <= 0) pxWidth = 800; // 폴백
  const msPerPx = spanMs / pxWidth;
  const minMs = msPerPx * minPx;
  const H = 3600000;
  // 정돈된 간격 후보 (작은 것부터)
  const candidates = [
    5 * 60000,      // 5분
    10 * 60000,     // 10분
    30 * 60000,     // 30분
    H,              // 1시간
    2 * H,          // 2시간
    3 * H,          // 3시간
    6 * H,          // 6시간
    12 * H,         // 12시간
    24 * H,         // 1일
    2 * 86400000,   // 2일
    3 * 86400000,   // 3일
    7 * 86400000,   // 7일
  ];
  for (const c of candidates) {{
    if (c >= minMs) return c;
  }}
  return candidates[candidates.length - 1];
}}

// 차트 플롯 영역의 픽셀 너비 반환 (마진 제외)
function getChartPlotWidth(chartId) {{
  const gd = document.getElementById(chartId);
  if (!gd) return 800;
  try {{
    const layout = gd._fullLayout;
    if (layout && layout.width && layout._size) {{
      return layout._size.w; // 실제 플롯 영역 너비 (마진 제외)
    }}
    return gd.getBoundingClientRect().width - 120; // 마진 추정
  }} catch(e) {{
    return gd.getBoundingClientRect().width - 120;
  }}
}}

// 시간 단위별 x축 틱 간격 (밀리초) — 초기 렌더 시 사용
function getXAxisConfig(unit) {{
  const H = 60 * 60 * 1000;
  // 초기 범위(spanMs)를 전체 x 범위로 계산
  const rangeStart = new Date('{x_range_start}').getTime();
  const rangeEnd   = new Date('{x_range_end}').getTime();
  const spanMs     = rangeEnd - rangeStart;
  // 첫 번째 차트 너비를 기준으로 dtick 계산 (아직 렌더 전이므로 DOM 너비 사용)
  const firstChart = document.querySelector('.chart-container') || document.body;
  const pxWidth    = Math.max(300, firstChart.getBoundingClientRect().width - 120);
  const dtick      = calcDtickByPixel(spanMs, pxWidth, 50);
  if (unit === '10min') return {{ dtick, tickformat: '%m-%d %H:%M' }};
  if (unit === '1hour') return {{ dtick, tickformat: '%m-%d %H시'  }};
  if (unit === '1day')  return {{ dtick, tickformat: '%m-%d'       }};
  return {{ dtick, tickformat: '%m-%d %H시' }};
}}

// 공통 스크롤 줌 설정 (데스크탑: scrollZoom 활성 / 모바일: Plotly 내장 터치 비활성화)
const scrollZoomConfig = {{
  responsive: true,
  // 모바일에서는 커스텀 터치 핸들러를 쓰므로 Plotly 내장 터치줌 끔
  scrollZoom: !IS_MOBILE,
  displayModeBar: false,
}};

// 신한 비교 차트(chart-shinhan) 전용 설정.
// 막대그래프는 카테고리 축이라 시간축 전용 커스텀 터치 핸들러를 적용하지 않으므로,
// 모바일에서도 Plotly 기본 핀치줌/팬이 동작하도록 scrollZoom을 항상 켠다.
const barChartZoomConfig = {{
  responsive: true,
  scrollZoom: true,
  displayModeBar: false,
}};

let currentViewMode = 'position';

function setViewMode(mode) {{
  currentViewMode = mode;
  document.getElementById('btn-bypos').classList.toggle('active', mode === 'position');
  document.getElementById('btn-byclub').classList.toggle('active', mode === 'club');
  document.getElementById('posSelect').style.display  = mode === 'position' ? '' : 'none';
  document.getElementById('clubSelect').style.display = mode === 'club'     ? '' : 'none';
  document.getElementById('selector-label').textContent = mode === 'position' ? '포지션' : '구단';
  // 포지션별 모드: 고정 제목 표시 / 구단별 모드: Plotly title로 대체하므로 고정 제목 숨김
  const showStaticTitle = mode === 'position';
  document.getElementById('title-nanum').style.display = showStaticTitle ? '' : 'none';
  document.getElementById('title-dream').style.display = showStaticTitle ? '' : 'none';
  updateCharts();
}}

// ── 모바일 전용: 범례 대신 터치하기 쉬운 "선수 토글 칩" 패널 ──
// Plotly 범례는 모바일에서 글자가 작고 줄바꿈이 많아 어떤 선수를 껐는지 알아보기 어렵다.
// 차트 바로 아래에 큼직한 칩 버튼을 만들어 누르면 해당 선수 선만 숨기고,
// 칩 자체의 색이 옅어지는 것으로 "꺼짐" 상태를 명확히 보여준다.
function attachMobilePlayerToggle(chartId, traces) {{
  if (!IS_MOBILE) return;
  const gd = document.getElementById(chartId);
  if (!gd) return;

  let panel = document.getElementById(`toggle-panel-${{chartId}}`);
  if (!panel) {{
    panel = document.createElement('div');
    panel.id = `toggle-panel-${{chartId}}`;
    panel.className = 'player-toggle-panel';
    gd.insertAdjacentElement('afterend', panel);
  }}
  panel.innerHTML = '';

  // 안내 문구 (최초 1회성 느낌으로 항상 표시 — 작고 은은하게)
  const hint = document.createElement('div');
  hint.className = 'player-toggle-hint';
  hint.textContent = '👆 칩을 탭하면 해당 선수를 숨기거나 다시 표시할 수 있어요';
  panel.appendChild(hint);

  const chipRow = document.createElement('div');
  chipRow.className = 'player-toggle-row';
  panel.appendChild(chipRow);

  traces.forEach((t, idx) => {{
    const chip = document.createElement('button');
    chip.className = 'player-toggle-chip';
    chip.type = 'button';
    const dotColor = (t.line && t.line.color) || (t.marker && t.marker.color) || '#4a6fa5';
    chip.innerHTML = `<span class="chip-dot" style="background:${{dotColor}}"></span><span>${{t.name || ''}}</span>`;
    chip.dataset.active = 'true';
    chip.onclick = () => {{
      const isActive = chip.dataset.active === 'true';
      const nextVisible = isActive ? 'legendonly' : true;
      chip.dataset.active = isActive ? 'false' : 'true';
      chip.classList.toggle('off', isActive);
      Plotly.restyle(gd, {{ visible: nextVisible }}, [idx]);
    }};
    chipRow.appendChild(chip);
  }});

  // 전체 보기 / 전체 숨기기 단축 버튼
  const actionRow = document.createElement('div');
  actionRow.className = 'player-toggle-actions';
  const showAllBtn = document.createElement('button');
  showAllBtn.className = 'player-toggle-action-btn';
  showAllBtn.textContent = '전체 표시';
  showAllBtn.onclick = () => {{
    Plotly.restyle(gd, {{ visible: true }}, traces.map((_, i) => i));
    chipRow.querySelectorAll('.player-toggle-chip').forEach(c => {{
      c.dataset.active = 'true';
      c.classList.remove('off');
    }});
  }};
  const hideAllBtn = document.createElement('button');
  hideAllBtn.className = 'player-toggle-action-btn';
  hideAllBtn.textContent = '전체 숨기기';
  hideAllBtn.onclick = () => {{
    Plotly.restyle(gd, {{ visible: 'legendonly' }}, traces.map((_, i) => i));
    chipRow.querySelectorAll('.player-toggle-chip').forEach(c => {{
      c.dataset.active = 'false';
      c.classList.add('off');
    }});
  }};
  actionRow.appendChild(showAllBtn);
  actionRow.appendChild(hideAllBtn);
  panel.appendChild(actionRow);
}}

function renderTeamChart(chartId, traces, xAxisBase, title) {{
  const c = (typeof getPlotlyColors === 'function') ? getPlotlyColors() : {{}};
  const grid  = c.grid  || '#1e2640';
  const line  = c.line  || '#2a3050';
  const font  = c.font  || '#a0b0d0';
  const hbg   = c.hover_bg     || '#1a2030';
  const hbrd  = c.hover_border || '#2a3050';
  const hfont = c.hover_font   || '#e0e6f0';
  // 모바일: 끝점 라벨이 없으므로 우측 여백 최소화 + 좌측도 좁게 → 차트가 화면을 최대한 가로로 채움
  // 범례는 숨기고(showlegend:false) 대신 차트 아래 토글 칩 패널로 대체 (스크롤 없는 3열 그리드)
  const marginCfg = IS_MOBILE
    ? {{ t: 30, b: 50, l: 38, r: 10 }}
    : {{ t: 30, b: 60, l: 50, r: 70 }};
  const layout = {{
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: {{ color: font, size: 11 }},
    height: 320,
    margin: marginCfg,
    xaxis: {{ ...xAxisBase, gridcolor: grid, linecolor: line }},
    yaxis: {{ gridcolor: grid, linecolor: line, tickfont: {{ size: 10 }}, rangemode: 'nonnegative', fixedrange: false }},
    showlegend: !IS_MOBILE,
    legend: {{ bgcolor: 'rgba(0,0,0,0)', font: {{ size: 10 }}, orientation: 'h', y: -0.25 }},
    hovermode: hoverHidden ? false : 'x unified',
    hoverlabel: {{ namelength: -1, bgcolor: hbg, bordercolor: hbrd, font: {{ color: hfont }} }},
    dragmode: IS_MOBILE ? false : 'pan',
    title: {{ text: title, font: {{ color: font, size: 13 }}, x: 0.01, xanchor: 'left' }}
  }};
  Plotly.react(chartId, traces, layout, scrollZoomConfig);
  attachMobilePlayerToggle(chartId, traces);
}}

// 득표 순위(차트 안에서) → dash 패턴 매핑.
// 1등=실선, 2등=듬성 점선, 3등 이상=촘촘 점선.
// 팀(구단)을 구분하려는 장치가 아니라, 같은 차트 안에서 보이는 선수들의 순위를 구분하기 위함이다.
function rankToDash(rankIdx) {{
  if (rankIdx === 0) return 'solid';
  if (rankIdx === 1) return 'dash';
  return 'dot';
}}

function buildChartTraces(data) {{
  const players = [...new Set(data.map(d => d.player))];
  const playerLatest = {{}};
  players.forEach(p => {{
    const pd = data.filter(d => d.player === p);
    const latest = pd.sort((a,b) => new Date(b.datetime) - new Date(a.datetime))[0];
    playerLatest[p] = latest ? getVal(latest, currentMetric) : 0;
  }});
  const sortedPlayers = [...players].sort((a,b) => playerLatest[b] - playerLatest[a]);

  // 외야수 구단별 보기(같은 구단 3명)는 색도 별도로 배정해 동일 구단 내 3명을 구분.
  // 그 외(포지션별 모드 등, 보통 서로 다른 구단)는 구단 고유색을 그대로 쓰고 dash만 순위로 구분.
  const OF_COLORS = ['#4af0c8', '#ff9f43', '#a29bfe'];
  const isOFClubMode = sortedPlayers.length > 1 &&
    data.length > 0 && data[0].pos_id === 'OF' &&
    [...new Set(data.map(d => d.club))].length === 1;

  return sortedPlayers.map((p, i) => {{
    const rankDash = rankToDash(i);
    const t = buildTrace(data.filter(d => d.player === p), currentMetric, rankDash);
    if (isOFClubMode) {{
      // 같은 구단 외야수 3명: 색까지 다르게 줘서 더 명확히 구분
      t.line   = {{ ...t.line,   color: OF_COLORS[i % 3] }};
      t.marker = {{ ...t.marker, color: OF_COLORS[i % 3] }};
      t.textfont = {{ ...t.textfont, color: OF_COLORS[i % 3] }};
    }}
    return t;
  }});
}}

function updateCharts() {{
  const xCfg = getXAxisConfig(currentTimeUnit);
  const c2 = (typeof getPlotlyColors === 'function') ? getPlotlyColors() : {{}};
  const xAxisBase = {{
    gridcolor: c2.grid || '#1e2640', linecolor: c2.line || '#2a3050',
    tickfont: {{ size: 10, color: c2.font || '#a0b0d0' }}, tickangle: -45,
    type: 'date',
    dtick: xCfg.dtick,
    tickformat: xCfg.tickformat,
    range: ['{x_range_start}', '{x_range_end}'],
    fixedrange: false
  }};

  // 구단별 모드 - 외야수 차트 표시 여부
  const ofDiv  = document.getElementById('of-section');
  const posDiv = document.getElementById('pos-section');

  if (currentViewMode === 'position') {{
    if (ofDiv)  ofDiv.style.display  = 'none';
    if (posDiv) posDiv.style.display = '';
    const pos = document.getElementById('posSelect').value;

    ['nanum', 'dream'].forEach(team => {{
      const teamData = resampleData(getAggData(`pos_${{pos}}_${{team}}`), currentTimeUnit);
      const traces = buildChartTraces(teamData);
      const marginCfgPos = IS_MOBILE
        ? {{ t: 10, b: 50, l: 38, r: 10 }}
        : {{ t: 10, b: 60, l: 50, r: 70 }};
      const layout = {{
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
        font: {{ color: c2.font || '#a0b0d0', size: 11 }},
        height: 320,
        margin: marginCfgPos,
        xaxis: {{ ...xAxisBase }},
        yaxis: {{ gridcolor: c2.grid || '#1e2640', linecolor: c2.line || '#2a3050', tickfont: {{ size: 10 }}, rangemode: 'nonnegative', fixedrange: false }},
        showlegend: !IS_MOBILE,
        legend: {{ bgcolor: 'rgba(0,0,0,0)', font: {{ size: 10 }}, orientation: 'h', y: -0.25 }},
        hovermode: hoverHidden ? false : 'x unified',
        hoverlabel: {{ namelength: -1, bgcolor: c2.hover_bg || '#1a2030', bordercolor: c2.hover_border || '#2a3050', font: {{ color: c2.hover_font || '#e0e6f0' }} }},
        dragmode: IS_MOBILE ? false : 'pan'
      }};
      Plotly.react(`chart-${{team}}`, traces, layout, scrollZoomConfig);
      attachMobilePlayerToggle(`chart-${{team}}`, traces);
    }});
  }} else {{
    // 구단별 모드
    if (ofDiv)  ofDiv.style.display  = '';
    if (posDiv) posDiv.style.display = 'none';  // 구단별: 나눔/드림 div 숨김 (chart-of-* 사용)
    const club = document.getElementById('clubSelect').value;
    const NON_OF_POS = ['SP','MP','CP','C','1B','2B','3B','SS','DH'];

    ['nanum', 'dream'].forEach(team => {{
      // AGG_DATA의 pos_* 키들을 모아 club으로 필터링 (중복 저장 없이 재사용)
      let nonOfRaw = [];
      NON_OF_POS.forEach(pos => {{
        const posAll = getAggData(`pos_${{pos}}_${{team}}`);
        nonOfRaw = nonOfRaw.concat(posAll.filter(d => d.club === club));
      }});
      const nonOfData = resampleData(nonOfRaw, currentTimeUnit);
      // 각 포지션의 1위 선수만
      const top1PerPos = {{}};
      NON_OF_POS.forEach(pos => {{
        const posData = nonOfData.filter(d => d.pos_id === pos);
        const players = [...new Set(posData.map(d => d.player))];
        const playerLatest = {{}};
        players.forEach(p => {{
          const pd = posData.filter(d => d.player === p);
          const latest = pd.sort((a,b) => new Date(b.datetime) - new Date(a.datetime))[0];
          playerLatest[p] = latest ? getVal(latest, currentMetric) : 0;
        }});
        const top = players.sort((a,b) => playerLatest[b] - playerLatest[a])[0];
        if (top) top1PerPos[pos] = posData.filter(d => d.player === top);
      }});

      // 포지션별 고유 색상 (구단 색 대신 사용)
      const POS_COLORS = {{
        'SP': '#ff6b6b', 'MP': '#ffa500', 'CP': '#ffd700',
        'C':  '#00d4aa', '1B': '#4a9eff', '2B': '#a78bfa',
        '3B': '#f472b6', 'SS': '#34d399', 'DH': '#fb923c'
      }};
      const POS_DASHES = {{
        'SP': 'solid', 'MP': 'dash', 'CP': 'dot',
        'C': 'solid', '1B': 'dash', '2B': 'dot',
        '3B': 'solid', 'SS': 'dash', 'DH': 'dot'
      }};

      const traces = Object.entries(top1PerPos).map(([pos, pd]) => {{
        const t = buildTrace(pd, currentMetric);
        t.name = `${{pos}} ${{t.name}}`;
        // 포지션마다 다른 색/선 스타일로 구분
        const posColor = POS_COLORS[pos] || '#4a6fa5';
        const posDash  = POS_DASHES[pos] || 'solid';
        t.line   = {{ ...t.line,   color: posColor, dash: posDash, width: 2 }};
        t.marker = {{ ...t.marker, color: posColor }};
        t.textfont = {{ ...t.textfont, color: posColor }};
        return t;
      }});
      const teamLabel = team === 'nanum' ? '🔵 나눔 올스타' : '🔴 드림 올스타';
      const mainChartId = `chart-of-${{team}}`;
      const ofChartId   = `chart-of2-${{team}}`;
      const mainWrap = document.getElementById(mainChartId)?.closest('.chart-container');
      const ofWrap   = document.getElementById(ofChartId)?.closest('.chart-container');

      // 후보가 없는 팀은 컨테이너 숨김
      if (traces.length === 0) {{
        if (mainWrap) mainWrap.style.display = 'none';
      }} else {{
        if (mainWrap) mainWrap.style.display = '';
        renderTeamChart(mainChartId, traces, xAxisBase, teamLabel + ` — ${{club}} (9포지션 1위)`);
      }}

      // 외야수 차트 — pos_OF_* 에서 club 필터링
      const ofRaw  = getAggData(`pos_OF_${{team}}`).filter(d => d.club === club);
      const ofData = resampleData(ofRaw, currentTimeUnit);
      const ofTraces = buildChartTraces(ofData);
      if (ofTraces.length === 0) {{
        if (ofWrap) ofWrap.style.display = 'none';
      }} else {{
        if (ofWrap) ofWrap.style.display = '';
        renderTeamChart(ofChartId, ofTraces, xAxisBase, teamLabel + ` — ${{club}} 외야수`);
      }}
    }});
  }}

  // 전체 투표수 차트
  const sortedTotal = resampleTotal(TOTAL_DATA, currentTimeUnit);
  const kstTotal = sortedTotal.map(d => toKST(d.datetime));

  const totalTrace = {{
    x: kstTotal,
    y: sortedTotal.map(d => d.votes),
    name: '누적 투표수',
    type: 'scatter',
    mode: 'lines',
    line: {{ color: '#4a9eff', width: 2 }},
    fill: 'tozeroy',
    fillcolor: 'rgba(74,158,255,0.1)',
    hovertemplate: '%{{x}}<br>누적: %{{y:,}}<extra></extra>'
  }};

  const newTotalTrace = {{
    x: kstTotal,
    y: sortedTotal.map((d,i) => i > 0 ? Math.max(0, d.votes - sortedTotal[i-1].votes) : 0),
    name: '신규 투표수',
    type: 'scatter',
    mode: 'lines',
    line: {{ color: '#ff4757', width: 2 }},
    fill: 'tozeroy',
    fillcolor: 'rgba(255,71,87,0.25)',
    hovertemplate: '%{{x}}<br>신규: %{{y:,}}<extra></extra>',
    yaxis: 'y2'
  }};

  const totalLayout = {{
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: {{ color: c2.font || '#a0b0d0', size: 11 }},
    height: 260,
    margin: {{ t: 10, b: 60, l: 60, r: 60 }},
    xaxis: {{ ...xAxisBase }},
    yaxis: {{ gridcolor: c2.grid || '#1e2640', linecolor: c2.line || '#2a3050', title: '누적', tickfont: {{ size: 10 }}, rangemode: 'nonnegative', fixedrange: false }},
    yaxis2: {{ overlaying: 'y', side: 'right', title: '신규', tickfont: {{ size: 10 }}, gridcolor: 'rgba(0,0,0,0)', rangemode: 'nonnegative' }},
    legend: {{ bgcolor: 'rgba(0,0,0,0)', font: {{ size: 10 }}, orientation: 'h', y: -0.3 }},
    hovermode: hoverHidden ? false : 'x unified',
    dragmode: IS_MOBILE ? false : 'pan'
  }};

  Plotly.react('chart-total', [totalTrace, newTotalTrace], totalLayout, scrollZoomConfig);
}}

updateCharts();

// ── 축 위에 투명 div 덮어씌워 드래그로 축 zoom ──────────────────────
(function() {{
  const CHART_IDS = ['chart-nanum', 'chart-dream', 'chart-of-nanum', 'chart-of-dream', 'chart-total'];
  let drag = null;
  let rafId = null;

  function msOf(v) {{ return typeof v === 'number' ? v : new Date(v).getTime(); }}

  function buildOverlays(id) {{
    const gd = document.getElementById(id);
    if (!gd || !gd._fullLayout || gd.__overlayDone) return;

    const fl = gd._fullLayout;
    const mg = fl.margin;  // {{ l, r, t, b }}

    // gd의 실제 렌더 크기 (Plotly가 그린 SVG 크기)
    const W = gd.offsetWidth  || gd.clientWidth;
    const H = gd.offsetHeight || gd.clientHeight;
    if (!W || !H) return;  // 아직 렌더 안됨

    const plotL = mg.l;
    const plotR = W - mg.r;
    const plotT = mg.t;
    const plotB = H - mg.b;

    gd.style.position = 'relative';

    // 기존 오버레이 제거
    gd.querySelectorAll('.__axis-overlay').forEach(d => d.remove());

    function makeDiv(left, top, width, height, cursor, title) {{
      const d = document.createElement('div');
      d.className = '__axis-overlay';
      d.style.cssText = [
        'position:absolute',
        `left:${{left}}px`, `top:${{top}}px`,
        `width:${{width}}px`, `height:${{height}}px`,
        `cursor:${{cursor}}`, 'z-index:1000',
        // 'outline: 2px solid rgba(255,100,100,0.4)',
        // 'outline: 2px solid rgba(255,100,100,0.5)',
      ].join(';');
      d.title = title;
      return d;
    }}

    // x축 오버레이 (plot 아래 여백 전체)
    const xDiv = makeDiv(plotL, plotB, plotR - plotL, mg.b, 'ew-resize', '좌우 드래그: 시간축 확대/축소');
    // y축 오버레이 (plot 왼쪽 여백 전체)
    const yDiv = makeDiv(0, plotT, mg.l, plotB - plotT, 'ns-resize', '상하 드래그: 값축 확대/축소');

    function startDrag(e, mode) {{
      e.preventDefault();
      e.stopPropagation();
      // 매번 gd._fullLayout을 새로 읽어야 이전 zoom 상태가 정확히 반영됨
      const curLayout = gd._fullLayout;
      const xr = [msOf(curLayout.xaxis.range[0]), msOf(curLayout.xaxis.range[1])];
      const yr = [+curLayout.yaxis.range[0], +curLayout.yaxis.range[1]];
      drag = {{
        gd, mode,
        sx: e.clientX, sy: e.clientY,
        x0: xr[0], x1: xr[1], xSpan: xr[1] - xr[0],
        y0: yr[0], y1: yr[1], ySpan: yr[1] - yr[0],
      }};
    }}

    xDiv.addEventListener('mousedown', e => startDrag(e, 'x'));
    yDiv.addEventListener('mousedown', e => startDrag(e, 'y'));
    // 더블클릭으로 전체 범위 초기화
    gd.addEventListener('dblclick', () => {{
      Plotly.relayout(gd, {{'xaxis.autorange': true, 'yaxis.autorange': true}});
    }});
    gd.appendChild(xDiv);
    gd.appendChild(yDiv);
    gd.__overlayDone = true;
  }}

  function tryBuild() {{
    CHART_IDS.forEach(id => buildOverlays(id));
  }}

  // updateCharts 래핑
  const _orig = window.updateCharts;
  window.updateCharts = function() {{
    CHART_IDS.forEach(id => {{
      const gd = document.getElementById(id);
      if (gd) {{ gd.__overlayDone = false; gd.querySelectorAll('.__axis-overlay').forEach(d => d.remove()); }}
    }});
    _orig();
    requestAnimationFrame(() => requestAnimationFrame(tryBuild));
  }};
  requestAnimationFrame(() => requestAnimationFrame(tryBuild));

  // mousemove: rAF throttle
  window.addEventListener('mousemove', e => {{
    if (!drag) return;
    if (rafId) return;
    const cx = e.clientX, cy = e.clientY;
    rafId = requestAnimationFrame(() => {{
      rafId = null;
      if (!drag) return;
      const dx = cx - drag.sx;
      const dy = cy - drag.sy;
      if (drag.mode === 'x') {{
        const factor = Math.pow(1.002, dx);
        const mid  = (drag.x0 + drag.x1) / 2;
        const half = Math.max(1800000, Math.min(drag.xSpan / 2 * factor, 25 * 86400000));
        const spanMs = half * 2;
        // 화면 픽셀 기반으로 dtick 계산 (최소 50px 간격)
        const pxW = getChartPlotWidth(drag.gd.id);
        const dtick = calcDtickByPixel(spanMs, pxW, 50);
        Plotly.relayout(drag.gd, {{
          'xaxis.range[0]': new Date(mid - half).toISOString(),
          'xaxis.range[1]': new Date(mid + half).toISOString(),
          'xaxis.dtick':    dtick,
        }});
      }} else {{
        const factor = Math.pow(1.002, -dy);
        const mid  = (drag.y0 + drag.y1) / 2;
        const half = Math.max(0.1, drag.ySpan / 2 * factor);
        Plotly.relayout(drag.gd, {{
          'yaxis.range[0]': Math.max(0, mid - half),
          'yaxis.range[1]': mid + half,
        }});
      }}
    }});
  }});

  window.addEventListener('mouseup', () => {{ drag = null; rafId = null; }});
  // 윈도우 리사이즈 시 오버레이 재생성
  window.addEventListener('resize', () => {{
    CHART_IDS.forEach(id => {{
      const gd = document.getElementById(id);
      if (gd) {{ gd.__overlayDone = false; gd.querySelectorAll('.__axis-overlay').forEach(d => d.remove()); }}
    }});
    requestAnimationFrame(tryBuild);
  }});
}})();

// ═══════════════════════════════════════════════════════
// ① 라이트/다크 모드 토글
// ═══════════════════════════════════════════════════════
function getPlotlyColors() {{
  const light = document.body.classList.contains('light-mode');
  return {{
    paper: light ? 'rgba(255,255,255,0)' : 'rgba(0,0,0,0)',
    plot:  light ? 'rgba(255,255,255,0)' : 'rgba(0,0,0,0)',
    font:  light ? '#3a4a6a'             : '#a0b0d0',
    grid:  light ? '#dde5f0'             : '#1e2640',
    line:  light ? '#c8d4e8'             : '#2a3050',
    hover_bg:     light ? '#f5f8ff' : '#1a2030',
    hover_border: light ? '#b0bdd4' : '#2a3050',
    hover_font:   light ? '#1a2540' : '#e0e6f0',
  }};
}}

function applyPlotlyTheme() {{
  const c = getPlotlyColors();
  const CHART_IDS = ['chart-nanum','chart-dream','chart-of-nanum','chart-of-dream','chart-total','chart-shinhan'];
  CHART_IDS.forEach(id => {{
    const gd = document.getElementById(id);
    if (!gd || !gd.data) return;
    Plotly.relayout(gd, {{
      paper_bgcolor: c.paper,
      plot_bgcolor:  c.plot,
      'font.color':  c.font,
      'xaxis.gridcolor': c.grid, 'xaxis.linecolor': c.line,
      'yaxis.gridcolor': c.grid, 'yaxis.linecolor': c.line,
      'hoverlabel.bgcolor':   c.hover_bg,
      'hoverlabel.bordercolor': c.hover_border,
      'hoverlabel.font.color': c.hover_font,
    }});
  }});
}}

function toggleTheme() {{
  const isLight = document.body.classList.toggle('light-mode');
  // 라이트 모드일 때: "🌙 다크" (클릭하면 다크로 전환)
  // 다크 모드일 때: "☀️ 라이트" (클릭하면 라이트로 전환)
  document.getElementById('theme-toggle').textContent = isLight ? '🌙 다크' : '☀️ 라이트';
  localStorage.setItem('kbo-theme', isLight ? 'light' : 'dark');
  // 차트 재렌더 (색상 변수 재적용 — KT처럼 테마별로 달라지는 구단색 포함)
  updateCharts();
  // 신한 비교 차트(별도 탭)도 KT 색 등이 바뀌도록 갱신
  if (typeof window.renderShinhanChart === 'function') {{
    window.renderShinhanChart();
  }}
}}

// 저장된 테마 복원
(function() {{
  const saved = localStorage.getItem('kbo-theme');
  if (saved === 'light') {{
    document.body.classList.add('light-mode');
    document.getElementById('theme-toggle').textContent = '🌙 다크';
  }} else {{
    // 다크 모드 기본
    document.getElementById('theme-toggle').textContent = '☀️ 라이트';
  }}
}})();

// ═══════════════════════════════════════════════════════
// ② 모바일 감지 + 호버 팝업 토글 + 터치 pan/pinch/더블탭
// ═══════════════════════════════════════════════════════
// IS_MOBILE은 스크립트 최상단에서 선언됨

// hoverHidden은 전역에서 선언됨

function toggleHoverLabel() {{
  hoverHidden = !hoverHidden;
  const btn = document.getElementById('hover-toggle');
  if (hoverHidden) {{
    btn.innerHTML = '👁 툴팁 켜기';
    btn.classList.add('tooltip-hidden');
  }} else {{
    btn.innerHTML = '👁 툴팁 끄기';
    btn.classList.remove('tooltip-hidden');
  }}
  const CHART_IDS = ['chart-nanum','chart-dream','chart-of-nanum','chart-of-dream','chart-total','chart-shinhan'];
  CHART_IDS.forEach(id => {{
    const gd = document.getElementById(id);
    if (!gd || !gd.data) return;
    Plotly.relayout(gd, {{ hovermode: hoverHidden ? false : 'x unified' }});
  }});
}}

// 모바일이면 툴팁 버튼 표시 + 버튼 텍스트 초기화
if (IS_MOBILE) {{
  const btn = document.getElementById('hover-toggle');
  btn.classList.add('visible');
  // hoverHidden은 IS_MOBILE 기반으로 전역에서 이미 true로 초기화됨
  btn.innerHTML = '👁 툴팁 켜기';
  btn.classList.add('tooltip-hidden');
}}

// ── 모바일 터치: 1핑거 pan + 2핑거 핀치줌 + 더블탭 초기화 ──
(function() {{
  if (!IS_MOBILE) return;

  const CHART_IDS = ['chart-nanum','chart-dream','chart-of-nanum','chart-of-dream','chart-total'];

  function msOf(v) {{ return typeof v === 'number' ? v : new Date(v).getTime(); }}

  function clampSpan(half) {{
    return Math.max(1800000, Math.min(half, 25 * 86400000));
  }}

  function applyXRange(gd, mid, half) {{
    const spanMs = half * 2;
    const pxW = getChartPlotWidth(gd.id);
    const dtick = calcDtickByPixel(spanMs, pxW, 50);
    Plotly.relayout(gd, {{
      'xaxis.range[0]': new Date(mid - half).toISOString(),
      'xaxis.range[1]': new Date(mid + half).toISOString(),
      'xaxis.dtick': dtick,
    }});
  }}

  function attachTouch(id) {{
    const gd = document.getElementById(id);
    if (!gd || gd.__touchDone) return;
    gd.__touchDone = true;

    // 더블탭 감지용
    let lastTap = 0;

    // 터치 상태
    let state = null; // {{ mode: 'pan'|'pinch', ... }}
    let rafId = null;
    let pendingRelayout = null;

    function getXRange() {{
      if (!gd._fullLayout) return null;
      const xr = gd._fullLayout.xaxis.range;
      return [msOf(xr[0]), msOf(xr[1])];
    }}

    gd.addEventListener('touchstart', e => {{
      // 더블탭 체크
      const now = Date.now();
      if (e.touches.length === 1 && (now - lastTap) < 300) {{
        e.preventDefault();
        Plotly.relayout(gd, {{ 'xaxis.autorange': true, 'yaxis.autorange': true }});
        lastTap = 0;
        state = null;
        return;
      }}
      lastTap = e.touches.length === 1 ? now : 0;

      const xr = getXRange();
      if (!xr) return;

      if (e.touches.length === 1) {{
        // 1핑거: pan
        e.preventDefault();
        state = {{
          mode: 'pan',
          startX: e.touches[0].clientX,
          xr0: xr,
          span: xr[1] - xr[0],
        }};
      }} else if (e.touches.length === 2) {{
        // 2핑거: 핀치줌
        e.preventDefault();
        const [a, b] = [e.touches[0], e.touches[1]];
        const dist = Math.abs(a.clientX - b.clientX);
        state = {{
          mode: 'pinch',
          dist0: Math.max(dist, 1),
          xr0: xr,
          mid: (xr[0] + xr[1]) / 2,
          half0: (xr[1] - xr[0]) / 2,
        }};
      }}
    }}, {{ passive: false }});

    gd.addEventListener('touchmove', e => {{
      if (!state) return;
      e.preventDefault();

      if (rafId) return;
      rafId = requestAnimationFrame(() => {{
        rafId = null;
        if (!state) return;

        if (state.mode === 'pan' && e.touches.length >= 1) {{
          // 1핑거 pan: 손가락 이동량 → x축 이동
          const pxW = getChartPlotWidth(id);
          const dx = e.touches[0].clientX - state.startX;
          // 픽셀당 ms 비율: span / plotWidth
          const msPerPx = state.span / Math.max(pxW, 1);
          const shift = -dx * msPerPx;  // 오른쪽으로 밀면 시간축 앞으로
          const newMid = (state.xr0[0] + state.xr0[1]) / 2 + shift;
          const half = state.span / 2;
          pendingRelayout = {{ gd, mid: newMid, half }};
        }} else if (state.mode === 'pinch' && e.touches.length >= 2) {{
          // 2핑거 핀치줌
          const [a, b] = [e.touches[0], e.touches[1]];
          const dist = Math.abs(a.clientX - b.clientX);
          // 손가락이 벌어질수록(dist↑) 화면이 확대 → 시간범위 축소
          const scale = state.dist0 / Math.max(dist, 1);
          const half = clampSpan(state.half0 * scale);
          pendingRelayout = {{ gd, mid: state.mid, half }};
        }}

        if (pendingRelayout) {{
          const {{ gd: g, mid, half }} = pendingRelayout;
          applyXRange(g, mid, half);
          pendingRelayout = null;
        }}
      }});
    }}, {{ passive: false }});

    gd.addEventListener('touchend', e => {{
      if (e.touches.length === 0) state = null;
      else if (e.touches.length === 1 && state && state.mode === 'pinch') {{
        // 핀치 → 1핑거로 전환: pan 상태로 리셋
        const xr = getXRange();
        if (xr) {{
          state = {{
            mode: 'pan',
            startX: e.touches[0].clientX,
            xr0: xr,
            span: xr[1] - xr[0],
          }};
        }}
      }}
    }}, {{ passive: true }});
  }}

  function attachAll() {{
    CHART_IDS.forEach(id => {{
      const gd = document.getElementById(id);
      if (gd) gd.__touchDone = false; // 재부착 허용
      attachTouch(id);
    }});
  }}

  // updateCharts 이후 재부착
  const _origTouch = window.updateCharts;
  window.updateCharts = function() {{
    _origTouch();
    requestAnimationFrame(attachAll);
  }};
  requestAnimationFrame(attachAll);
}})();

// ══════════════════════════════════════════════════════
// 신한은행 vs 공식 비교 차트 (1차/2차 통합 — 선수당 4막대)
// ══════════════════════════════════════════════════════
(function() {{
  const POS_LIST  = ['SP','MP','CP','C','1B','2B','3B','SS','DH','OF'];
  const POS_LABEL = {{ SP:'선발', MP:'중간', CP:'마무리', C:'포수', '1B':'1루', '2B':'2루', '3B':'3루', SS:'유격', DH:'지명', OF:'외야' }};

  if (!SHINHAN_COMPARE) {{
    const sec = document.getElementById('shinhan-section');
    if (sec) sec.style.display = 'none';
    const tabBtn = document.getElementById('main-tab-shinhan');
    if (tabBtn) tabBtn.style.display = 'none'; // 데이터 없으면 탭 자체를 숨김
    return;
  }}

  let currentTeam = 'nanum';
  let currentPos  = 'SP';

  function buildPosTabs() {{
    const wrap = document.getElementById('shinhan-pos-tabs');
    if (!wrap) return;
    wrap.innerHTML = '';
    POS_LIST.forEach(pos => {{
      const btn = document.createElement('button');
      btn.id = `sh-tab-${{pos}}`;
      btn.className = 'sh-pos-btn' + (pos === currentPos ? ' active' : '');
      btn.textContent = POS_LABEL[pos];
      btn.onclick = () => {{
        currentPos = pos;
        document.querySelectorAll('.sh-pos-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        renderShinhanChart();
      }};
      wrap.appendChild(btn);
    }});
  }}

  window.setShinhanTeam = function(team) {{
    currentTeam = team;
    document.getElementById('sh-team-nanum').classList.toggle('active', team === 'nanum');
    document.getElementById('sh-team-dream').classList.toggle('active', team === 'dream');
    renderShinhanChart();
  }};

  function renderShinhanChart() {{
    const c = (typeof getPlotlyColors === 'function') ? getPlotlyColors() : {{}};
    const rows = (SHINHAN_COMPARE[currentPos] && SHINHAN_COMPARE[currentPos][currentTeam]) || [];

    if (!rows.length) {{
      Plotly.purge('chart-shinhan');
      const note = document.getElementById('shinhan-note');
      if (note) note.textContent = '⚠️ 데이터 없음';
      return;
    }}

    const sorted = [...rows].sort((a,b) => (a.rank2||99) - (b.rank2||99) || (a.rank1||99) - (b.rank1||99));
    // x축 카테고리 라벨은 선수명만 (구단 표시는 아래 annotations 배지로 대체)
    const players = sorted.map(r => r.player);

    const mk = (key, name, color) => ({{
      x: players,
      y: sorted.map(r => r[key]),
      customdata: sorted.map(r => r.club),
      name: name,
      type: 'bar',
      marker: {{ color: color, opacity: 0.9 }},
      text: sorted.map(r => r[key] != null ? r[key].toLocaleString() : '-'),
      textposition: 'outside',
      textfont: {{ size: 9 }},
      hovertemplate: `%{{x}} (%{{customdata}})<br>${{name}}: %{{y:,}}표<extra></extra>`,
    }});

    const traces = [
      mk('off1', '1차 공식 (6/7)',  '#4a9eff'),
      mk('sh1',  '1차 신한 (6/7)',  '#ffd700'),
      mk('off2', '2차 공식 (6/14)', '#2e6fd4'),
      mk('sh2',  '2차 신한 (6/14)', '#ff9500'),
    ];

    // 구단별 배경색 배지: 선수명 x축 라벨 아래에 구단색 박스 + 구단명을 그려
    // 어느 팀 소속인지 한눈에 구분되게 한다. xref:'x'라 막대와 함께 줌/드래그된다.
    function readableTextColor(hexColor) {{
      const hex = (hexColor || '#4a6fa5').replace('#', '');
      const r = parseInt(hex.substring(0,2), 16) || 0;
      const g = parseInt(hex.substring(2,4), 16) || 0;
      const b = parseInt(hex.substring(4,6), 16) || 0;
      const luminance = (0.299*r + 0.587*g + 0.114*b) / 255;
      return luminance > 0.55 ? '#1a1a2e' : '#ffffff';
    }}

    const clubAnnotations = sorted.map((r, i) => {{
      const clubColor = TEAM_COLORS[r.club] || '#4a6fa5';
      return {{
        x: i,
        y: 0,
        xref: 'x',
        yref: 'paper',
        yanchor: 'top',
        xanchor: 'center',
        yshift: -42,
        text: r.club,
        showarrow: false,
        font: {{ size: 10, color: readableTextColor(clubColor), weight: 600 }},
        bgcolor: clubColor,
        borderpad: 4,
        borderwidth: 0,
        opacity: 0.95,
      }};
    }});

    // 다른 차트들과 동일한 줌/팬 동작 통일:
    // - 스크롤: 전체 줌 (scrollZoomConfig)
    // - 드래그: 좌우 이동 (dragmode: 'pan')
    // 막대그래프는 카테고리(문자열) x축이라 초기 range를 인덱스로 잘라
    // "상위 5명만" 보이게 하고, 드래그하면 나머지 후보가 드러나도록 한다.
    const INITIAL_VISIBLE = 5;
    const xRange = players.length > INITIAL_VISIBLE
      ? [-0.5, INITIAL_VISIBLE - 0.5]
      : undefined; // 5명 이하면 전체 표시, range 제한 없음

    const teamLabel = currentTeam === 'nanum' ? '🔵 나눔' : '🔴 드림';
    Plotly.react('chart-shinhan', traces, {{
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      font: {{ color: c.font || '#a0b0d0', size: 11 }},
      barmode: 'group',
      bargap: 0.18,
      bargroupgap: 0.08,
      height: Math.max(390, sorted.length > 8 ? 450 : 390),
      margin: {{ t: 40, b: 90, l: 50, r: 20 }},
      xaxis: {{
        gridcolor: c.grid || '#1e2640',
        tickfont: {{ size: 10 }},
        range: xRange,
        fixedrange: false,
      }},
      yaxis: {{ gridcolor: c.grid || '#1e2640', title: {{ text: '득표수', font: {{ size: 10 }} }}, rangemode: 'nonnegative', fixedrange: false }},
      legend: {{ orientation: 'h', y: -0.3, bgcolor: 'rgba(0,0,0,0)', font: {{ size: 10 }} }},
      title: {{ text: `${{teamLabel}} · ${{POS_LABEL[currentPos]}}(${{currentPos}}) — 1차 vs 2차 공식·신한 비교`,
                font: {{ size: 13, color: c.font || '#a0b0d0' }}, x: 0.01 }},
      annotations: clubAnnotations,
      dragmode: 'pan',
      hovermode: hoverHidden ? false : 'closest',
      hoverlabel: {{ bgcolor: c.hover_bg || '#1a2030', bordercolor: c.hover_border || '#2a3050', font: {{ color: c.hover_font || '#e0e6f0' }} }},
    }}, barChartZoomConfig);

    const note = document.getElementById('shinhan-note');
    if (note) {{
      const scrollHint = players.length > INITIAL_VISIBLE
        ? ` 처음엔 상위 ${{INITIAL_VISIBLE}}명만 표시되며, 좌우로 드래그하면 더 많은 후보를 볼 수 있습니다.`
        : '';
      note.textContent = `💡 1차=6/7 14시(11시·15시 데이터 선형보간 추정) · 2차=6/14 14시 · 신한 값은 PDF 합산 득표수에서 공식 득표수를 뺀 추정치입니다.${{scrollHint}}`;
    }}
  }}

  buildPosTabs();
  document.getElementById('sh-team-nanum').classList.add('active');
  // 신한 탭은 처음엔 숨겨져 있으므로 자동 렌더하지 않음.
  // setMainTab('shinhan')에서 최초 진입 시 1회 호출됨 (window.renderShinhanChart로 노출).
  window.renderShinhanChart = renderShinhanChart;
}})();

// ── 메인 탭 전환: 실시간 집계 ↔ 중간집계(신한) 비교 ──
let _shinhanRendered = false;
function setMainTab(tab) {{
  document.getElementById('main-tab-live').classList.toggle('active', tab === 'live');
  document.getElementById('main-tab-shinhan').classList.toggle('active', tab === 'shinhan');
  document.getElementById('main-panel-live').style.display    = tab === 'live'    ? '' : 'none';
  document.getElementById('main-panel-shinhan').style.display = tab === 'shinhan' ? '' : 'none';

  if (tab === 'shinhan') {{
    // 숨겨진 상태(width:0)에서 Plotly가 그려지면 레이아웃이 깨지므로
    // 탭이 보이게 된 직후(1프레임 뒤)에 최초 1회만 렌더한다.
    if (!_shinhanRendered && typeof window.renderShinhanChart === 'function') {{
      _shinhanRendered = true;
      requestAnimationFrame(() => window.renderShinhanChart());
    }} else {{
      // 이미 렌더된 적 있으면 크기만 재계산 (컨테이너가 display:none이었다가 풀렸으므로)
      requestAnimationFrame(() => {{
        const gd = document.getElementById('chart-shinhan');
        if (gd && gd.data) Plotly.Plots.resize(gd);
      }});
    }}
  }} else {{
    // 실시간 탭으로 복귀 시에도 동일하게 차트 크기 재계산
    requestAnimationFrame(() => {{
      ['chart-nanum','chart-dream','chart-of-nanum','chart-of-dream',
       'chart-of2-nanum','chart-of2-dream','chart-total'].forEach(id => {{
        const gd = document.getElementById(id);
        if (gd && gd.data) Plotly.Plots.resize(gd);
      }});
    }});
  }}
}}
</script>
</body>
</html>"""

    os.makedirs("output", exist_ok=True)
    with open("output/chart.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("✅ 차트 저장 완료: output/chart.html")

if __name__ == "__main__":
    print("📊 데이터 로딩 중...")
    df = load_all_data(days=0)  # 전체 기간 로드
    print(f"✅ {len(df)}개 레코드 로드 완료")
    df = calc_vote_rate(df)
    build_chart(df)
