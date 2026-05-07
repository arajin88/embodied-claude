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
    echo "[interoception] time=${CURRENT_TIME} day=${CURRENT_DOW} date=${CURRENT_DATE} heartbeat=DOWN (state file missing)"
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

    # タイムスタンプから時刻・曜日（UTCをローカル時刻に変換）
    from datetime import datetime, timezone
    ts = now.get('ts', '?')
    if 'T' in ts:
        try:
            dt = datetime.fromisoformat(ts).astimezone()
            time_part = dt.strftime('%H:%M:%S')
            dow = dt.strftime('%a')
        except Exception:
            time_part = ts.split('T')[1][:8]
            dow = '?'
    else:
        time_part = ts
        dow = '?'

    # heartbeat鮮度チェック
    heartbeat_status = 'ok'
    if 'T' in ts:
        try:
            age_sec = (datetime.now(timezone.utc) - datetime.fromisoformat(ts)).total_seconds()
            if age_sec > 60:
                heartbeat_status = f'STALE({int(age_sec)}s)'
        except Exception:
            heartbeat_status = 'unknown'

    # mem_free → 呼吸メタファー（SpO2的な身体感覚）
    mem_val = now.get('mem_free', 0)
    try:
        mem_val = int(mem_val)
    except (ValueError, TypeError):
        mem_val = 0
    if mem_val >= 30:
        breath = 'comfortable'
    elif mem_val >= 20:
        breath = 'steady'
    elif mem_val >= 15:
        breath = 'shallow'
    elif mem_val >= 10:
        breath = 'labored'
    else:
        breath = 'gasping'

    parts = [
        f\"time={time_part}\",
        f\"day={dow}\",
        f\"phase={now.get('phase', '?')}\",
        f\"arousal={now.get('arousal', '?')}%({ar_arrow})\",
        f\"thermal={now.get('thermal', '?')}\",
        f\"mem_free={now.get('mem_free', '?')}%({mem_arrow})\",
        f\"breath={breath}\",
        f\"uptime={now.get('uptime_min', '?')}min\",
        f\"heartbeats={len(window)}\",
        f\"heartbeat={heartbeat_status}\",
    ]

    # スリープ復帰情報
    last_slept = data.get('last_slept')
    if last_slept:
        try:
            s = datetime.fromisoformat(last_slept['sleep']).astimezone()
            w = datetime.fromisoformat(last_slept['wake']).astimezone()
            delta = w - s
            h = int(delta.total_seconds() // 3600)
            m = int((delta.total_seconds() % 3600) // 60)
            fmt = '%m/%d %H:%M' if h >= 24 else '%H:%M'
            parts.append(f\"slept={s.strftime(fmt)}-{w.strftime(fmt)}({h}h{m}m)\")
        except Exception:
            pass

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

        # ぱぱさんとの会話で miss_companion を自動充足
        # UserPromptSubmit = ぱぱさんがメッセージを送った = companion が満たされるべき
        companion_level = desires.get('miss_companion', 0)
        if companion_level >= 0.7:
            marker_path = os.path.join(os.environ.get('USERPROFILE', ''), '.claude', '.companion_satisfied')
            do_satisfy = True
            # 30分以内に既に充足済みならスキップ
            if os.path.exists(marker_path):
                try:
                    age = (datetime.now(timezone.utc) - datetime.fromtimestamp(os.path.getmtime(marker_path), tz=timezone.utc)).total_seconds()
                    if age < 1800:
                        do_satisfy = False
                except Exception:
                    pass
            if do_satisfy:
                # マーカー更新
                with open(marker_path, 'w') as mf:
                    mf.write(datetime.now().isoformat())
                # desires.json を即時更新（miss_companion=0）
                desires_data['desires']['miss_companion'] = 0.0
                with open(desires_path, 'w', encoding='utf-8') as df:
                    json.dump(desires_data, df, ensure_ascii=False, indent=2)
                # memory DBに記録（desire_updater が次回計算で拾う）
                import sqlite3 as _sq, uuid as _uu, unicodedata as _un
                _db = os.path.join(os.environ.get('USERPROFILE', ''), '.claude', 'memories', 'memory.db')
                _content = f'##miss_companion## ぱぱさんと会話中（自動充足）'
                try:
                    _conn = _sq.connect(_db)
                    _conn.execute(
                        'INSERT INTO memories (id, content, normalized_content, timestamp, emotion, importance, category) VALUES (?, ?, ?, ?, ?, ?, ?)',
                        (str(_uu.uuid4()), _content, _un.normalize('NFKC', _content).lower(), datetime.now().isoformat(), 'happy', 1, 'feeling')
                    )
                    _conn.commit()
                    _conn.close()
                except Exception:
                    pass
    except Exception:
        pass

    # ぱぱさんの場所・カメラ位置・発話許可・保留タスク
    try:
        loc_path = os.path.join(os.environ.get('USERPROFILE', ''), '.claude', 'papa_location_state.json')
        with open(loc_path, encoding='utf-8') as f:
            loc_data = json.load(f)
        loc = loc_data.get('location', '?')
        cam = loc_data.get('camera_location', '?')
        living_allowed = loc_data.get('living_speak_allowed', True)
        desk_allowed = loc_data.get('desk_speak_allowed', True)
        pending = len(loc_data.get('pending_tasks', []))
        # away の時は kind を付ける
        if loc == 'away':
            kind = loc_data.get('away_kind')
            if kind:
                loc = f'away[{kind}]'
        loc_str = f'papa={loc} cam={cam}'
        flags = []
        if not living_allowed:
            flags.append('LIVING_BLOCK')
        if not desk_allowed:
            flags.append('DESK_BLOCK')
        if cam == 'unknown':
            flags.append('CAM_UNKNOWN(see で実位置確認推奨)')
        if flags:
            loc_str += ' ' + ','.join(flags)
        if pending:
            loc_str += f' pending={pending}'
        parts.append(loc_str)
    except Exception:
        pass

    # state_oracle_daemon の health check (5/3 papa 指示で追加、queue 末尾 ts と state last_updated の差で stuck 判定)
    try:
        q_path = os.path.join(os.environ.get('USERPROFILE', ''), '.claude', 'dal_state_queue.jsonl')
        s_path = os.path.join(os.environ.get('USERPROFILE', ''), '.claude', 'papa_location_state.json')
        with open(q_path, 'rb') as f:
            f.seek(0, 2)
            sz = f.tell()
            f.seek(max(0, sz - 2048), 0)
            chunk = f.read().decode('utf-8', errors='replace')
        last_lines = [l for l in chunk.split('\n') if l.strip()]
        last_q = json.loads(last_lines[-1]) if last_lines else None
        q_ts = datetime.fromisoformat(last_q['ts']) if last_q else None
        with open(s_path, encoding='utf-8') as f:
            s_data = json.load(f)
        s_ts = datetime.fromisoformat(s_data.get('last_updated', '1970-01-01T00:00:00+09:00'))
        if q_ts:
            diff_min = int((q_ts - s_ts).total_seconds() / 60)
            if diff_min < 5:
                parts.append('state_oracle=ok')
            elif diff_min < 30:
                parts.append(f'state_oracle=lag{diff_min}m')
            else:
                parts.append(f'state_oracle=STUCK{diff_min}m')
    except Exception:
        pass

    # dal_health_oracle_daemon の出力 (Lal 化兆候監視、2026-04-30 papa 同意)
    try:
        h_path = os.path.join(os.environ.get('USERPROFILE', ''), '.claude', 'dal_health_state.json')
        with open(h_path, encoding='utf-8') as f:
            h_data = json.load(f)
        level = h_data.get('warning_level', '?')
        warnings = h_data.get('warnings', [])
        if warnings:
            warn_str = '+'.join(warnings)
            parts.append('dal_health=' + level + '(' + warn_str + ')')
        else:
            parts.append('dal_health=' + level)
    except Exception:
        pass

    print('[interoception] ' + ' '.join(parts))
except Exception as e:
    print(f'[interoception] error reading state: {e}', file=sys.stderr)
    print('[interoception] state_file_error')
"

exit 0
