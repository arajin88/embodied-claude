"""wake_eventlog.py — Windows Power-Troubleshooter Id=1 イベントから sleep/wake 時刻を取得。

heartbeat-daemon と on-wake.py の両方から import される共通関数。
2026-05-01 papa 指摘で extract: on-wake.py 単独だと wake event 直後の race window が
30秒〜数分発生し、interoception.sh の slept 注入が古い state を読む事故を起こした。
heartbeat-daemon が 5 秒 poll で wake 検知 + 即座に event log query することで
race window を 5 秒以下に短縮する設計。

timeout=300 は重要: PC 復帰直後は全体が遅く、30秒や60秒だと PowerShell/Get-WinEvent が
間に合わない（過去に延長されたのが戻されてた経緯あり）。
"""
from __future__ import annotations

import re
import subprocess
from datetime import datetime
from pathlib import Path


def get_sleep_wake_from_eventlog(log_file_path: Path | None = None) -> tuple[str | None, str | None]:
    """Power-Troubleshooter Id=1 から (sleep_iso, wake_iso) を取得。

    log_file_path: デバッグログ書き込み先。None なら ~/.claude/on-wake-debug.log。
    呼び出し元別にデバッグログを分離したい場合は path を渡す。
    """
    if log_file_path is None:
        log_file_path = Path.home() / ".claude" / "on-wake-debug.log"

    try:
        with open(log_file_path, "a", encoding="utf-8") as f:
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
            capture_output=True, text=True, timeout=300,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        msg = result.stdout
        try:
            with open(log_file_path, "a", encoding="utf-8") as f:
                f.write(f"returncode: {result.returncode}\n")
                f.write(f"stdout repr: {repr(msg[:500])}\n")
                f.write(f"stderr: {result.stderr[:200]}\n")
        except Exception:
            pass

        # ISO 時刻を含む行を順番に取得（1つ目=スリープ、2つ目=復帰）
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
        try:
            with open(log_file_path, "a", encoding="utf-8") as f:
                f.write(f"parsed times: {times}\n")
                f.write(f"sleep={sleep_time}, wake={wake_time}\n")
        except Exception:
            pass
        return sleep_time, wake_time
    except Exception as e:
        import traceback
        try:
            with open(log_file_path, "a", encoding="utf-8") as f:
                f.write(f"EXCEPTION: {type(e).__name__}: {e}\n")
                f.write(traceback.format_exc())
        except Exception:
            pass
        return None, None
