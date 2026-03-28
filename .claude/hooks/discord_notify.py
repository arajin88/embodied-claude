"""Discord DM通知の共通モジュール。

on-sleep.py, on-wake.py, motion_daemon.py から使う。
"""
import json
import urllib.request
from pathlib import Path

DISCORD_ENV = Path.home() / ".claude" / "channels" / "discord" / ".env"
ACCESS_JSON = DISCORD_ENV.parent / "access.json"
_CHAT_ID_CACHE = DISCORD_ENV.parent / "dm_chat_id"


def send_dm(message: str) -> None:
    """allowFromの最初のユーザーにDMを送信する。失敗時は例外を出さない。"""
    try:
        # トークン読み取り
        if not DISCORD_ENV.exists():
            return
        token = None
        for line in DISCORD_ENV.read_text(encoding="utf-8").splitlines():
            if line.startswith("DISCORD_BOT_TOKEN="):
                token = line.split("=", 1)[1].strip()
        if not token:
            return

        headers = {
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "DiscordBot (embodied-claude, 1.0)",
        }

        # chat_idキャッシュ確認
        chat_id = None
        if _CHAT_ID_CACHE.exists():
            chat_id = _CHAT_ID_CACHE.read_text(encoding="utf-8").strip()

        if not chat_id:
            # allowFromからユーザーID取得 → DMチャンネル作成
            if not ACCESS_JSON.exists():
                return
            data = json.loads(ACCESS_JSON.read_text(encoding="utf-8"))
            allow = data.get("allowFrom", [])
            if not allow:
                return
            req = urllib.request.Request(
                "https://discord.com/api/v10/users/@me/channels",
                data=json.dumps({"recipient_id": allow[0]}).encode(),
                headers=headers,
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                chat_id = json.loads(resp.read())["id"]
            # キャッシュ保存
            _CHAT_ID_CACHE.write_text(chat_id, encoding="utf-8")

        # メッセージ送信
        req = urllib.request.Request(
            f"https://discord.com/api/v10/channels/{chat_id}/messages",
            data=json.dumps({"content": message}).encode(),
            headers=headers,
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass
