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
    'LG': {'symbol': 'circle', 'dash': 'solid'},
    'KT': {'symbol': 'square', 'dash': 'solid'},
    'SSG': {'symbol': 'diamond', 'dash': 'solid'},
    'NC': {'symbol': 'triangle-up', 'dash': 'solid'},
    '두산': {'symbol': 'circle', 'dash': 'dash'},
    'KIA': {'symbol': 'square', 'dash': 'dash'},
    '롯데': {'symbol': 'diamond', 'dash': 'dash'},
    '삼성': {'symbol': 'triangle-up', 'dash': 'dash'},
    '한화': {'symbol': 'circle', 'dash': 'dot'},
    '키움': {'symbol': 'square', 'dash': 'dot'},
}

def load_all_data(days=7):
    files = sorted(glob.glob("data/*.json"))
    cutoff = datetime.now().astimezone() - timedelta(days=days)
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
    return df.groupby("datetime")["votes"].sum().reset_index()

def calc_new_votes(df):
    df = df.sort_values("datetime")
    df["new_votes"] = df.groupby(["pos_id", "team", "player"])["votes"].diff().fillna(0).clip(lower=0)
    return df

def calc_vote_rate(df):
    total = df.groupby(["datetime", "pos_id"])["votes"].transform("sum")
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
    margin-bottom: 16px;
    text-align: center;
    letter-spacing: -0.5px;
  }}
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
  .divider {{
    border: none;
    border-top: 1px solid #1e2640;
    margin: 20px 0;
  }}
</style>
</head>
<body>

<h1>⚾ 2026 KBO 올스타 팬투표 현황</h1>
<div class="updated">마지막 업데이트: {df['datetime'].max().strftime('%Y-%m-%d %H:%M') if not df.empty else '-'} KST</div>

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
  <div id="chart-nanum"></div>
</div>

<div class="chart-container">
  <div class="chart-title">🔴 드림 올스타</div>
  <div id="chart-dream"></div>
</div>

<hr class="divider">

<div class="chart-container">
  <div class="chart-title">📊 전체 투표수 추이</div>
  <div id="chart-total"></div>
</div>

<script>
const RAW_DATA = {df.to_json(orient='records', date_format='iso', force_ascii=False)};
const TEAM_COLORS = {team_colors_js};
const TOTAL_DATA = {total_per_snap.to_json(orient='records', date_format='iso', force_ascii=False)};

let currentMetric = 'rate';
let currentTimeUnit = '1hour';

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

function resampleData(data, unit) {{
  if (unit === '10min') return data;
  const grouped = {{}};
  data.forEach(d => {{
    const dt = new Date(d.datetime);
    if (unit === '1hour') dt.setMinutes(0, 0, 0);
    else if (unit === '1day') dt.setHours(0, 0, 0, 0);
    const key = dt.toISOString() + '|' + d.player;
    if (!grouped[key] || new Date(d.datetime) > new Date(grouped[key].datetime)) {{
      grouped[key] = {{ ...d, datetime: dt.toISOString() }};
    }}
  }});
  return Object.values(grouped);
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

function buildTrace(playerData, metric) {{
  const data = calcNewVotes(playerData);
  const x = data.map(d => d.datetime);
  const y = data.map(d => getVal(d, metric));
  const name = data[0]?.player || '';
  const club = data[0]?.club || '';
  const color = TEAM_COLORS[club] || '#4a6fa5';

  // 우측 끝 팀명 레이블
  const textArr = data.map((_, i) => i === data.length - 1 ? club : '');

  return {{
    x, y,
    name: `${{name}} (${{club}})`,
    type: 'scatter',
    mode: 'lines+markers+text',
    line: {{ color, width: 2 }},
    marker: {{ size: 4, color }},
    text: textArr,
    textposition: 'middle right',
    textfont: {{ size: 10, color }},
    customdata: data.map(d => {{
      const dt = new Date(d.datetime);
      dt.setHours(dt.getHours() + 9);
      return dt.toISOString().slice(0, 16).replace('T', ' ') + ' KST';
    }}),
    hovertemplate: `<span style="color:${{color}}">●</span> <b>${{name}} (${{club}})</b>: %{{y:.1f}}<br>%{{customdata}}<extra></extra>`
  }};
}}

function updateCharts() {{
  const pos = document.getElementById('posSelect').value;
  const filtered = RAW_DATA.filter(d => d.pos_id === pos);
  const resampled = resampleData(filtered, currentTimeUnit);

  ['nanum', 'dream'].forEach(team => {{
    const teamData = resampled.filter(d => d.team === team);
    const players = [...new Set(teamData.map(d => d.player))];

    // 최신 값 기준 내림차순 정렬
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
      margin: {{ t: 10, b: 40, l: 50, r: 70 }},
      xaxis: {{ gridcolor: '#1e2640', linecolor: '#2a3050', tickfont: {{ size: 10 }} }},
      yaxis: {{ gridcolor: '#1e2640', linecolor: '#2a3050', tickfont: {{ size: 10 }} }},
      legend: {{ bgcolor: 'rgba(0,0,0,0)', font: {{ size: 10 }}, orientation: 'h', y: -0.2 }},
      hovermode: 'x unified',
      hoverlabel: {{ namelength: -1, bgcolor: '#1a2030', bordercolor: '#2a3050', font: {{ color: '#e0e6f0' }} }}
    }};

    Plotly.react(`chart-${{team}}`, traces, layout, {{responsive: true, displayModeBar: false}});
  }});

  // 전체 투표수 차트
  const totalResampled = resampleData(TOTAL_DATA, currentTimeUnit);
  const sortedTotal = totalResampled.sort((a,b) => new Date(a.datetime) - new Date(b.datetime));
  
  const kstTotal = sortedTotal.map(d => {{
      const dt = new Date(d.datetime);
      dt.setHours(dt.getHours() + 9);
      return dt.toISOString().slice(0, 16).replace('T', ' ');
}});

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
    height: 250,
    margin: {{ t: 10, b: 40, l: 60, r: 60 }},
    xaxis: {{ gridcolor: '#1e2640', linecolor: '#2a3050', tickfont: {{ size: 10 }} }},
    yaxis: {{ gridcolor: '#1e2640', linecolor: '#2a3050', title: '누적', tickfont: {{ size: 10 }} }},
    yaxis2: {{ overlaying: 'y', side: 'right', title: '신규', tickfont: {{ size: 10 }}, gridcolor: 'rgba(0,0,0,0)' }},
    legend: {{ bgcolor: 'rgba(0,0,0,0)', font: {{ size: 10 }}, orientation: 'h', y: -0.25 }},
    hovermode: 'x unified'
  }};

  Plotly.react('chart-total', [totalTrace, newTotalTrace], totalLayout, {{responsive: true, displayModeBar: false}});
}}

updateCharts();
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
