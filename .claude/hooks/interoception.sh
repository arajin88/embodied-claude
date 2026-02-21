#!/bin/bash
# interoception.sh - AIの内受容感覚（interoception）
# UserPromptSubmitフックで毎ターン実行される
# heartbeat-daemon.sh が書き出した state file を読んでコンテキストに注入する
# 自前で計測せず、読み取り→整形→出力するだけの軽量版

STATE_FILE="${USERPROFILE//\\//}/.claude/interoception_state.json"

# state file がなければフォールバック（デーモン未起動時）
if [ ! -f "$STATE_FILE" ]; then
    CURRENT_TIME=$(date '+%H:%M:%S')
    CURRENT_DOW=$(date '+%a')
    CURRENT_DATE=$(date '+%Y-%m-%d')
    echo "[interoception] time=${CURRENT_TIME} day=${CURRENT_DOW} date=${CURRENT_DATE} (heartbeat daemon not running)"
    exit 0
fi

# state file から読み取って1行に整形
PYTHON="C:/Users/araji/AppData/Local/Programs/Python/Python311/python.exe"
"$PYTHON" -c "
import json, sys
try:
    with open('${STATE_FILE}') as f:
        data = json.load(f)
    now = data.get('now', {})
    trend = data.get('trend', {})
    window = data.get('window', [])

    # トレンド矢印
    arrows = {'rising': '+', 'falling': '-', 'stable': '~'}
    ar_arrow = arrows.get(trend.get('arousal', 'stable'), '→')
    mem_arrow = arrows.get(trend.get('mem_free', 'stable'), '→')

    # タイムスタンプから時刻・曜日
    from datetime import datetime
    ts = now.get('ts', '?')
    if 'T' in ts:
        time_part = ts.split('T')[1][:8]
        try:
            dt = datetime.strptime(ts[:10], '%Y-%m-%d')
            dow = dt.strftime('%a')  # Mon, Tue, ...
        except Exception:
            dow = '?'
    else:
        time_part = ts
        dow = '?'

    parts = [
        f\"time={time_part}\",
        f\"day={dow}\",
        f\"phase={now.get('phase', '?')}\",
        f\"arousal={now.get('arousal', '?')}%({ar_arrow})\",
        f\"thermal={now.get('thermal', '?')}\",
        f\"mem_free={now.get('mem_free', '?')}%({mem_arrow})\",
        f\"uptime={now.get('uptime_min', '?')}min\",
        f\"heartbeats={len(window)}\",
    ]

    # desires.json を読んで欲求レベルを追加
    import os
    desires_path = os.path.join(os.environ.get('USERPROFILE', ''), '.claude', 'desires.json')
    try:
        with open(desires_path) as f:
            desires_data = json.load(f)
        desires = desires_data.get('desires', {})
        short = {'look_outside': 'outside', 'browse_curiosity': 'browse', 'miss_companion': 'companion', 'observe_room': 'room'}
        desire_parts = []
        for key, level in desires.items():
            label = short.get(key, key)
            flag = '(!)' if level >= 0.7 else ''
            desire_parts.append(f\"{label}={level:.2f}{flag}\")
        if desire_parts:
            parts.append('desires: ' + ' '.join(desire_parts))
    except Exception:
        pass

    print('[interoception] ' + ' '.join(parts))
except Exception as e:
    print(f'[interoception] error reading state: {e}', file=sys.stderr)
    print('[interoception] state_file_error')
"

exit 0
