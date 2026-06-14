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
    '두산': '#6B8CFF', 'KIA': '#EA0029', '롯데': '#4A9EFF', '삼성': '#74A9FF',
    '한화': '#FF6600', '키움': '#FF4D7D'
}

TEAM_MARKERS = {
    'LG':   {'symbol': 'circle',      'dash': 'solid'},
    'KT':   {'symbol': 'square',      'dash': 'solid'},
    'SSG':  {'symbol': 'diamond',     'dash': 'solid'},
    'NC':   {'symbol': 'triangle-up', 'dash': 'solid'},
    '두산': {'symbol': 'circle',      'dash': 'dash'},
    'KIA':  {'symbol': 'square',      'dash': 'dash'},
    '롯데': {'symbol': 'diamond',     'dash': 'dash'},
    '삼성': {'symbol': 'triangle-up', 'dash': 'dash'},
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

def build_chart(df):
    df = calc_new_votes(df)
    df = calc_vote_rate(df)
    total_per_snap = calc_total_votes_per_snapshot(df)
    total_per_snap = total_per_snap.sort_values("datetime")
    total_per_snap["new_total"] = total_per_snap["votes"].diff().fillna(0).clip(lower=0)

    team_colors_js = json.dumps(
        {v: TEAM_COLORS.get(v, '#4a6fa5') for v in df['club'].unique().tolist() if isinstance(v, str)},
        ensure_ascii=False
    )
    team_markers_js = json.dumps(
        {v: TEAM_MARKERS.get(v, {'symbol': 'circle', 'dash': 'solid'}) for v in df['club'].unique().tolist() if isinstance(v, str)},
        ensure_ascii=False
    )

    last_updated = df['datetime'].max().strftime('%Y-%m-%d %H:%M') if not df.empty else '-'

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>2026 KBO 올스타 투표 현황</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: 'Pretendard', 'Noto Sans KR', sans-serif;
    background: #0a0e1a;
    color: #e0e6f0;
    min-height: 100vh;
    padding: 16px;
  }}
  h1 {{
    font-size: 1.3rem;
    font-weight: 700;
    color: #fff;
    margin-bottom: 8px;
    text-align: center;
    letter-spacing: -0.5px;
  }}
  .header-links {{
    text-align: center;
    margin-bottom: 8px;
  }}
  .header-links a {{
    color: #4a9eff;
    text-decoration: none;
    font-size: 0.8rem;
    margin: 0 8px;
    opacity: 0.8;
  }}
  .header-links a:hover {{ opacity: 1; text-decoration: underline; }}
  .updated {{
    font-size: 0.75rem;
    color: #6b7a99;
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
    color: #6b7a99;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }}
  select, .toggle-group {{
    background: #151929;
    border: 1px solid #2a3050;
    color: #e0e6f0;
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 0.85rem;
    cursor: pointer;
    outline: none;
  }}
  select:focus {{ border-color: #4a6fa5; }}
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
    background: #151929;
    color: #6b7a99;
    transition: all 0.2s;
  }}
  .toggle-btn.active {{
    background: #2a4a8a;
    color: #fff;
  }}
  .chart-container {{
    background: #111520;
    border: 1px solid #1e2640;
    border-radius: 12px;
    padding: 12px;
    margin-bottom: 16px;
  }}
  .chart-title {{
    font-size: 0.9rem;
    font-weight: 600;
    color: #a0b0d0;
    margin-bottom: 8px;
    padding-left: 4px;
  }}
  .zoom-hint {{
    font-size: 0.7rem;
    color: #4a6070;
    text-align: right;
    padding-right: 4px;
    margin-bottom: 4px;
  }}
  .zoom-hint kbd {{
    background: #1e2a40;
    border: 1px solid #3a4a6a;
    border-radius: 3px;
    padding: 0px 4px;
    font-size: 0.65rem;
    font-family: monospace;
    color: #8090b0;
  }}
  .divider {{
    border: none;
    border-top: 1px solid #1e2640;
    margin: 20px 0;
  }}
</style>
</head>
<body>

<h1>⚾ 2026 KBO 올스타 팬투표 현황</h1>
<div class="header-links">
  <a href="https://kbo.kr" target="_blank" rel="noopener">🔗 KBO 공식 투표</a>
  <a href="https://github.com/your-repo" target="_blank" rel="noopener" id="github-link">📁 GitHub</a>
</div>
<div class="updated">마지막 업데이트: {last_updated} KST</div>

<div class="controls">
  <div class="control-group">
    <label>포지션</label>
    <select id="posSelect" onchange="updateCharts()">
      {''.join(f'<option value="{k}">{v}</option>' for k, v in POSITIONS.items())}
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
</div>

<div class="chart-container">
  <div class="chart-title">🔵 나눔 올스타</div>
  <div class="zoom-hint">🖱 스크롤: 전체 줌 · 드래그: 이동 · x축 위 드래그↔: 시간축 줌 · y축 위 드래그↕: 값축 줌</div>
  <div id="chart-nanum"></div>
</div>

<div class="chart-container">
  <div class="chart-title">🔴 드림 올스타</div>
  <div class="zoom-hint">🖱 스크롤: 전체 줌 · 드래그: 이동 · x축 위 드래그↔: 시간축 줌 · y축 위 드래그↕: 값축 줌</div>
  <div id="chart-dream"></div>
</div>

<hr class="divider">

<div class="chart-container">
  <div class="chart-title">📊 전체 투표수 추이</div>
  <div class="zoom-hint">🖱 스크롤: 전체 줌 · 드래그: 이동 · x축 위 드래그↔: 시간축 줌 · y축 위 드래그↕: 값축 줌</div>
  <div id="chart-total"></div>
</div>

<script>
const RAW_DATA = {df.to_json(orient='records', date_format='iso', force_ascii=False)};
const TEAM_COLORS = {team_colors_js};
const TEAM_MARKERS = {team_markers_js};
const TOTAL_DATA = {total_per_snap.to_json(orient='records', date_format='iso', force_ascii=False)};

let currentMetric = 'rate';
let currentTimeUnit = '1hour';

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

function findPrevVal(data, idx, metric, unit) {{
  const curTime = new Date(data[idx].datetime).getTime();
  const targetTime = curTime - unitToMs(unit);
  let closest = null;
  let minDiff = Infinity;
  for (let i = 0; i < idx; i++) {{
    const t = new Date(data[i].datetime).getTime();
    const diff = Math.abs(t - targetTime);
    if (diff < minDiff) {{
      minDiff = diff;
      closest = data[i];
    }}
  }}
  if (!closest) return null;
  const diffMin = Math.round(minDiff / 60000);
  return {{ val: getVal(closest, metric), diffMin }};
}}

function buildTrace(playerData, metric) {{
  const data = calcNewVotes(playerData);
  const name = data[0]?.player || '';
  const club = data[0]?.club || '';
  const color = TEAM_COLORS[club] || '#4a6fa5';
  const marker = TEAM_MARKERS[club] || {{ symbol: 'circle', dash: 'solid' }};

  const x = data.map(d => toKST(d.datetime));
  const y = data.map(d => getVal(d, metric));

  const textArr = data.map((_, i) => i === data.length - 1 ? club : '');

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
    line: {{ color, width: 2, dash: marker.dash }},
    marker: {{ size: markerSize, color, symbol: marker.symbol }},
    text: textArr,
    textposition: 'middle right',
    textfont: {{ size: 10, color }},
    hovertemplate: `<span style="color:${{color}}">●</span> <b>${{name}} (${{club}})</b>: ${{valFmt}}${{valLabel}}  %{{customdata[1]}}<extra></extra>`
  }};
}}

// 시간 단위별 x축 틱 간격 (밀리초)
function getXAxisConfig(unit) {{
  // Plotly date축 dtick: 밀리초 단위 숫자 사용 (1000ms * 60s * 60m * Nh)
  const H = 60 * 60 * 1000;
  if (unit === '10min') return {{ dtick: 3 * H,  tickformat: '%m-%d %H:%M', nticks: 0 }};
  if (unit === '1hour') return {{ dtick: 6 * H,  tickformat: '%m-%d %H시',  nticks: 0 }};
  if (unit === '1day')  return {{ dtick: 24 * H, tickformat: '%m-%d',       nticks: 0 }};
  return {{ dtick: 6 * H, tickformat: '%m-%d %H시', nticks: 0 }};
}}

// 공통 스크롤 줌 설정
const scrollZoomConfig = {{
  responsive: true,
  scrollZoom: true,
  displayModeBar: false
}};

function updateCharts() {{
  const pos = document.getElementById('posSelect').value;
  const filtered = RAW_DATA.filter(d => d.pos_id === pos);
  const resampled = resampleData(filtered, currentTimeUnit);

  // xAxisBase를 updateCharts 스코프 최상단에 선언 → 총투표 차트 포함 전체 공유
  const xCfg = getXAxisConfig(currentTimeUnit);
  const xAxisBase = {{
    gridcolor: '#1e2640', linecolor: '#2a3050',
    tickfont: {{ size: 10 }}, tickangle: -45,
    type: 'date',
    dtick: xCfg.dtick,
    tickformat: xCfg.tickformat,
    range: ['2026-06-03 15:00', '2026-06-25 00:00'],
    fixedrange: false
  }};

  ['nanum', 'dream'].forEach(team => {{
    const teamData = resampled.filter(d => d.team === team);
    const players = [...new Set(teamData.map(d => d.player))];

    const playerLatest = {{}};
    players.forEach(p => {{
      const pd = teamData.filter(d => d.player === p);
      const latest = pd.sort((a,b) => new Date(b.datetime) - new Date(a.datetime))[0];
      playerLatest[p] = latest ? getVal(latest, currentMetric) : 0;
    }});
    const sortedPlayers = [...players].sort((a,b) => playerLatest[b] - playerLatest[a]);

    const traces = sortedPlayers.map(p => {{
      const pd = teamData.filter(d => d.player === p);
      return buildTrace(pd, currentMetric);
    }});

    const layout = {{
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      font: {{ color: '#a0b0d0', size: 11 }},
      height: 320,
      margin: {{ t: 10, b: 60, l: 50, r: 70 }},
      xaxis: xAxisBase,
      yaxis: {{ gridcolor: '#1e2640', linecolor: '#2a3050', tickfont: {{ size: 10 }}, rangemode: 'nonnegative', fixedrange: false }},
      legend: {{ bgcolor: 'rgba(0,0,0,0)', font: {{ size: 10 }}, orientation: 'h', y: -0.25 }},
      hovermode: 'x unified',
      hoverlabel: {{ namelength: -1, bgcolor: '#1a2030', bordercolor: '#2a3050', font: {{ color: '#e0e6f0' }} }},
      dragmode: 'pan'
    }};

    Plotly.react(`chart-${{team}}`, traces, layout, scrollZoomConfig);
  }});

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
    type: 'bar',
    marker: {{ color: 'rgba(255,180,50,0.6)' }},
    hovertemplate: '%{{x}}<br>신규: %{{y:,}}<extra></extra>',
    yaxis: 'y2'
  }};

  const totalLayout = {{
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: {{ color: '#a0b0d0', size: 11 }},
    height: 260,
    margin: {{ t: 10, b: 60, l: 60, r: 60 }},
    xaxis: xAxisBase,
    yaxis: {{ gridcolor: '#1e2640', linecolor: '#2a3050', title: '누적', tickfont: {{ size: 10 }}, rangemode: 'nonnegative', fixedrange: false }},
    yaxis2: {{ overlaying: 'y', side: 'right', title: '신규', tickfont: {{ size: 10 }}, gridcolor: 'rgba(0,0,0,0)', rangemode: 'nonnegative' }},
    legend: {{ bgcolor: 'rgba(0,0,0,0)', font: {{ size: 10 }}, orientation: 'h', y: -0.3 }},
    hovermode: 'x unified',
    dragmode: 'pan'
  }};

  Plotly.react('chart-total', [totalTrace, newTotalTrace], totalLayout, scrollZoomConfig);
}}

updateCharts();

// ── 축 위에 투명 div 덮어씌워 드래그로 축 zoom ──────────────────────
// Plotly가 축 이벤트를 가로채므로, 축 영역 위에 별도 div를 생성해 이벤트 처리
(function() {{
  const CHART_IDS = ['chart-nanum', 'chart-dream', 'chart-total'];
  let drag = null;
  let rafId  = null;

  function msOf(v) {{ return typeof v === 'number' ? v : new Date(v).getTime(); }}

  function buildOverlays(id) {{
    const gd = document.getElementById(id);
    if (!gd || !gd._fullLayout || gd.__overlayDone) return;

    const fl   = gd._fullLayout;
    const xa   = fl.xaxis, ya = fl.yaxis;
    const rect = gd.getBoundingClientRect();
    const gdRect = gd.getBoundingClientRect();

    // Plotly 내부 plot 영역 좌표 (margin 기준)
    const margin = fl.margin;
    const plotL  = margin.l, plotR = rect.width  - margin.r;
    const plotT  = margin.t, plotB = rect.height - margin.b;

    // ── X축 오버레이: plot 아래쪽 여백(x축 틱 영역) ──
    const xDiv = document.createElement('div');
    xDiv.style.cssText = `
      position:absolute; cursor:ew-resize; z-index:999;
      left:${{plotL}}px; top:${{plotB}}px;
      width:${{plotR - plotL}}px; height:${{margin.b}}px;
    `;
    xDiv.title = '좌우 드래그: 시간축 확대/축소';

    // ── Y축 오버레이: plot 왼쪽 여백(y축 틱 영역) ──
    const yDiv = document.createElement('div');
    yDiv.style.cssText = `
      position:absolute; cursor:ns-resize; z-index:999;
      left:0; top:${{plotT}}px;
      width:${{plotL}}px; height:${{plotB - plotT}}px;
    `;
    yDiv.title = '상하 드래그: 값축 확대/축소';

    // gd는 position:relative가 필요
    gd.style.position = 'relative';
    gd.appendChild(xDiv);
    gd.appendChild(yDiv);

    function startDrag(e, mode) {{
      e.preventDefault();
      const xr = [msOf(xa.range[0]), msOf(xa.range[1])];
      const yr  = [+ya.range[0], +ya.range[1]];
      drag = {{
        gd, mode,
        sx: e.clientX, sy: e.clientY,
        x0: xr[0], x1: xr[1], xSpan: xr[1] - xr[0],
        y0: yr[0], y1: yr[1], ySpan: yr[1] - yr[0],
      }};
    }}

    xDiv.addEventListener('mousedown', e => startDrag(e, 'x'));
    yDiv.addEventListener('mousedown', e => startDrag(e, 'y'));

    gd.__overlayDone = true;
  }}

  function tryBuild() {{
    CHART_IDS.forEach(id => {{
      const gd = document.getElementById(id);
      if (gd && gd._fullLayout && !gd.__overlayDone) buildOverlays(id);
    }});
  }}

  // updateCharts 래핑: 재렌더링 시 오버레이 재생성
  const _orig = window.updateCharts;
  window.updateCharts = function() {{
    CHART_IDS.forEach(id => {{
      const gd = document.getElementById(id);
      if (gd) {{
        gd.__overlayDone = false;
        // 기존 오버레이 div 제거
        gd.querySelectorAll('div[title*="드래그"]').forEach(d => d.remove());
      }}
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
        // 오른쪽: 축소(범위 넓힘), 왼쪽: 확대(범위 좁힘)
        const factor = Math.pow(1.004, dx);
        const mid  = (drag.x0 + drag.x1) / 2;
        const half = Math.max(1800000, Math.min(drag.xSpan / 2 * factor, 25 * 86400000));
        Plotly.relayout(drag.gd, {{
          'xaxis.range[0]': new Date(mid - half).toISOString(),
          'xaxis.range[1]': new Date(mid + half).toISOString(),
        }});
      }} else {{
        // 위: 축소(범위 넓힘), 아래: 확대(범위 좁힘)
        const factor = Math.pow(1.004, -dy);
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
}})();
</script>
</body>
</html>"""

    os.makedirs("output", exist_ok=True)
    with open("output/chart.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("✅ 차트 저장 완료: output/chart.html")

if __name__ == "__main__":
    print("📊 데이터 로딩 중...")
    df = load_all_data()
    print(f"✅ {len(df)}개 레코드 로드 완료")
    df = calc_vote_rate(df)
    build_chart(df)
