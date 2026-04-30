"""スタンバイ復帰時にstate fileに記録 + Discord DM通知。

タスクスケジューラから Power-Troubleshooter イベントID 1 で起動される。
イベントログから実際のスリープ/復帰時刻を取得する。
"""
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

STATE_FILE = Path.home() / ".claude" / "interoception_state.json"

sys.path.insert(0, str(Path(__file__).parent))
from discord_notify import send_dm
# 2026-05-01 papa 訂正で extract: get_sleep_wake_from_eventlog は wake_eventlog.py に移動
# heartbeat-daemon と共通使用、race condition 解消の一環
from wake_eventlog import get_sleep_wake_from_eventlog


def main() -> None:
    # イベントログから実際の時刻を取得
    sleep_iso, wake_iso = get_sleep_wake_from_eventlog()

    # state file読み込み
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    else:
        data = {}

    # スリープ時間を計算
    duration_msg = ""
    if sleep_iso and wake_iso:
        try:
            sleep_dt = datetime.fromisoformat(sleep_iso)
            wake_dt = datetime.fromisoformat(wake_iso)
            delta = wake_dt - sleep_dt
            hours = int(delta.total_seconds() // 3600)
            mins = int((delta.total_seconds() % 3600) // 60)
            fmt = "%m/%d %H:%M" if hours >= 24 else "%H:%M"
            s_local = sleep_dt.astimezone().strftime(fmt)
            w_local = wake_dt.astimezone().strftime(fmt)
            duration_msg = f"（{s_local}→{w_local}、{hours}時間{mins}分）"
        except Exception:
            pass

    # state fileに復帰情報を記録
    now = datetime.now(timezone.utc).isoformat()
    data["last_wake"] = now
    if sleep_iso and wake_iso:
        data["last_slept"] = {
            "sleep": sleep_iso,
            "wake": wake_iso,
        }
    # last_sleep_startはもう不要なので消す
    data.pop("last_sleep_start", None)
    STATE_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Discord DM通知
    send_dm(f"起きた！{duration_msg}")

    # 寝起きの自律行動（ベランダを見て独り言）
    try:
        BASH = r"C:\Program Files\Git\bin\bash.exe"
        PROJECT_DIR = r"D:\ComDoc\projects\embodied-claude"
        prompt = (
            "起きた。まずベランダを見て今日の天気を確認して、"
            "見たものと感想をrememberに記録して、"
            "Discordに独り言として一言つぶやいて。"
            "ぱぱさんへの呼びかけではなく独り言で。"
        )
        subprocess.Popen(
            [BASH, "-c",
             f'cd "{PROJECT_DIR}" && claude -p "{prompt}" '
             '--effort low '
             '--allowedTools "mcp__wifi-cam__see,mcp__memory__remember,'
             'mcp__plugin_discord_discord__reply"'],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        pass


if __name__ == "__main__":
    main()
