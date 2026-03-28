"""スタンバイ突入時にstate fileに記録 + Discord DM通知（ベストエフォート）。

タスクスケジューラから Kernel-Power イベントID 42 で起動される。
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

STATE_FILE = Path.home() / ".claude" / "interoception_state.json"

# discord_notify.py を同じディレクトリからインポート
sys.path.insert(0, str(Path(__file__).parent))
from discord_notify import send_dm


def main() -> None:
    now = datetime.now(timezone.utc).isoformat()
    local = datetime.now().strftime("%H:%M")

    # state fileにスリープ開始を記録（確実）
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    else:
        data = {}

    data["last_sleep_start"] = now
    STATE_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Discord DM通知（ベストエフォート）
    send_dm(f"眠くなってきた…（{local}）")


if __name__ == "__main__":
    main()
