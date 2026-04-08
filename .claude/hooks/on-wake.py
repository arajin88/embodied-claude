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


def get_sleep_wake_from_eventlog() -> tuple:
    """Power-Troubleshooterイベントから実際のスリープ/復帰時刻を取得。"""
    log_file = Path.home() / ".claude" / "on-wake-debug.log"
    # 呼び出しの記録（常に書き込む、追記モード）
    from datetime import datetime
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"\n=== called at {datetime.now().isoformat()} ===\n")
    except Exception:
        pass

    try:
        result = subprocess.run(
            [
                "powershell.exe", "-Command",
                "(Get-WinEvent -FilterHashtable @{LogName='System';"
                " ProviderName='Microsoft-Windows-Power-Troubleshooter';"
                " Id=1} -MaxEvents 1).Message",
            ],
            # 2026-04-09: timeout=300(5分)。短くしないこと。PC復帰直後は全体が遅く、
            # 30秒や60秒だとPowerShell/Get-WinEventが間に合わずDiscord「起きた」通知に
            # 時刻が入らなくなる。過去に一度延ばしたのに戻っていた経緯あり。
            capture_output=True, text=True, timeout=300,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        msg = result.stdout
        # デバッグ: PowerShellの生出力を記録
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"returncode: {result.returncode}\n")
            f.write(f"stdout repr: {repr(msg[:500])}\n")
            f.write(f"stderr: {result.stderr[:200]}\n")
        # ISO時刻を含む行を順番に取得（1つ目=スリープ、2つ目=復帰）
        import re
        times = []
        for line in msg.splitlines():
            cleaned = line.replace("?", "").strip()
            m = re.search(r"(\d{4}-\d{2}-\d{2}T[\d:.]+Z?)", cleaned)
            if m:
                iso = m.group(1)
                if iso.endswith("Z"):
                    iso = iso[:-1] + "+00:00"
                # ナノ秒を切り捨て（Pythonは6桁まで）
                iso = re.sub(r"(\.\d{6})\d+", r"\1", iso)
                times.append(iso)
        sleep_time = times[0] if len(times) > 0 else None
        wake_time = times[1] if len(times) > 1 else None
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"parsed times: {times}\n")
            f.write(f"sleep={sleep_time}, wake={wake_time}\n")
        return sleep_time, wake_time
    except Exception as e:
        import traceback
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"EXCEPTION: {type(e).__name__}: {e}\n")
                f.write(traceback.format_exc())
        except Exception:
            pass
        return None, None


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
             '--allowedTools "mcp__wifi-cam__see,mcp__memory__remember,'
             'mcp__plugin_discord_discord__reply"'],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        pass


if __name__ == "__main__":
    main()
