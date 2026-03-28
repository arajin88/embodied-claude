"""
heartbeat-daemon.py - Windows版心拍デーモン

5秒ごとにシステム状態を ~/.claude/interoception_state.json に書き出す。
interoception.sh (UserPromptSubmitフック) がこのファイルを読んでコンテキストに注入する。

起動方法（タスクスケジューラで自動起動）:
    pythonw.exe heartbeat-daemon.py
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil

STATE_FILE = Path.home() / ".claude" / "interoception_state.json"
WINDOW_SIZE = 12  # 12 * 5秒 = 1分間


def get_phase(hour: int) -> str:
    if 5 <= hour < 10:
        return "morning"
    elif 10 <= hour < 12:
        return "late_morning"
    elif 12 <= hour < 14:
        return "midday"
    elif 14 <= hour < 17:
        return "afternoon"
    elif 17 <= hour < 20:
        return "evening"
    elif 20 <= hour < 23:
        return "night"
    else:
        return "late_night"


def get_trend(values: list) -> str:
    if len(values) < 3:
        return "stable"
    diff = values[-1] - values[-3]
    if diff > 5:
        return "rising"
    elif diff < -5:
        return "falling"
    return "stable"


def collect() -> dict:
    now = datetime.now(timezone.utc)
    hour = datetime.now().hour  # ローカル時刻でphase判定

    # CPU負荷（覚醒度）
    arousal = int(psutil.cpu_percent(interval=0.5))

    # メモリ空き率
    vm = psutil.virtual_memory()
    mem_free = int(100 - vm.percent)

    # 体温（GPU温度をnvidia-smiで取得、取れない場合は0）
    thermal = 0
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=3,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        val = result.stdout.strip()
        if val.isdigit():
            thermal = int(val)
    except Exception:
        pass

    # 稼働時間（分）
    uptime_min = int((time.time() - psutil.boot_time()) / 60)

    return {
        "ts": now.isoformat(),
        "phase": get_phase(hour),
        "arousal": arousal,
        "mem_free": mem_free,
        "thermal": thermal,
        "uptime_min": uptime_min,
    }


def main() -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    window: list = []

    # 既存のwindowを読み込む
    if STATE_FILE.exists():
        try:
            existing = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            window = existing.get("window", [])
        except Exception:
            pass

    while True:
        entry = collect()

        # リングバッファ更新
        window.append(entry)
        window = window[-WINDOW_SIZE:]

        # トレンド算出
        arousal_vals = [e["arousal"] for e in window]
        mem_vals = [e["mem_free"] for e in window]

        state = {
            "now": entry,
            "window": window,
            "trend": {
                "arousal": get_trend(arousal_vals),
                "mem_free": get_trend(mem_vals),
            },
        }

        # 他プロセス（on-sleep/on-wake）が書いたキーを保持
        _preserve_keys = ("last_sleep_start", "last_wake", "last_slept")
        if STATE_FILE.exists():
            try:
                existing = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                for k in _preserve_keys:
                    if k in existing:
                        state[k] = existing[k]
            except Exception:
                pass

        # アトミック書き込み
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(STATE_FILE)

        time.sleep(5)


if __name__ == "__main__":
    main()
