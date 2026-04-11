"""Discord DM通知の共通モジュール。

on-sleep.py, on-wake.py, motion_daemon.py から使う。
"""
import json
import mimetypes
import urllib.request
import uuid
from pathlib import Path

DISCORD_ENV = Path.home() / ".claude" / "channels" / "discord" / ".env"
ACCESS_JSON = DISCORD_ENV.parent / "access.json"
_CHAT_ID_CACHE = DISCORD_ENV.parent / "dm_chat_id"


def _get_token() -> str | None:
    """Discord bot token を .env から読む。"""
    if not DISCORD_ENV.exists():
        return None
    for line in DISCORD_ENV.read_text(encoding="utf-8").splitlines():
        if line.startswith("DISCORD_BOT_TOKEN="):
            return line.split("=", 1)[1].strip()
    return None


def _get_chat_id(token: str) -> str | None:
    """DM channel ID を取得する（キャッシュあり）。"""
    if _CHAT_ID_CACHE.exists():
        return _CHAT_ID_CACHE.read_text(encoding="utf-8").strip()

    if not ACCESS_JSON.exists():
        return None
    data = json.loads(ACCESS_JSON.read_text(encoding="utf-8"))
    allow = data.get("allowFrom", [])
    if not allow:
        return None

    headers = {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
        "User-Agent": "DiscordBot (embodied-claude, 1.0)",
    }
    req = urllib.request.Request(
        "https://discord.com/api/v10/users/@me/channels",
        data=json.dumps({"recipient_id": allow[0]}).encode(),
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        chat_id = json.loads(resp.read())["id"]
    _CHAT_ID_CACHE.write_text(chat_id, encoding="utf-8")
    return chat_id


def send_dm(message: str) -> None:
    """allowFromの最初のユーザーにDMを送信する。失敗時は例外を出さない。"""
    try:
        token = _get_token()
        if not token:
            return
        chat_id = _get_chat_id(token)
        if not chat_id:
            return

        headers = {
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "DiscordBot (embodied-claude, 1.0)",
        }
        req = urllib.request.Request(
            f"https://discord.com/api/v10/channels/{chat_id}/messages",
            data=json.dumps({"content": message}).encode(),
            headers=headers,
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass


def send_dm_with_image(message: str, image_path: str | Path) -> None:
    """画像添付付きDM送信。失敗時は例外を出さない。"""
    try:
        image_path = Path(image_path)
        if not image_path.exists():
            send_dm(message)
            return

        token = _get_token()
        if not token:
            return
        chat_id = _get_chat_id(token)
        if not chat_id:
            return

        # multipart/form-data を手組み
        boundary = f"----DiscordBoundary{uuid.uuid4().hex}"
        content_type = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
        image_bytes = image_path.read_bytes()
        filename = image_path.name

        payload_json = json.dumps({"content": message})

        body = b""
        body += f"--{boundary}\r\n".encode()
        body += b'Content-Disposition: form-data; name="payload_json"\r\n'
        body += b"Content-Type: application/json\r\n\r\n"
        body += payload_json.encode() + b"\r\n"
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="files[0]"; filename="{filename}"\r\n'.encode()
        body += f"Content-Type: {content_type}\r\n\r\n".encode()
        body += image_bytes + b"\r\n"
        body += f"--{boundary}--\r\n".encode()

        headers = {
            "Authorization": f"Bot {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "DiscordBot (embodied-claude, 1.0)",
        }
        req = urllib.request.Request(
            f"https://discord.com/api/v10/channels/{chat_id}/messages",
            data=body,
            headers=headers,
        )
        urllib.request.urlopen(req, timeout=30)
    except Exception:
        pass
