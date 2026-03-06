"""動体検知デーモン。

Tapo C220 の ONVIF PullPoint イベントを監視し、動き開始を検知したら
即座にスナップショットを撮影し、claude -p を起動して画像を分析させる。

使い方:
    cd wifi-cam-mcp
    uv run python motion_daemon.py

タスクスケジューラからの起動:
    pythonw.exe + run-motion-daemon.py (CREATE_NO_WINDOW)
"""

import asyncio
import io
import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))

import onvif
import zeep.helpers
from dotenv import load_dotenv
from onvif import ONVIFCamera
from PIL import Image

# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------

_project_root = Path(__file__).resolve().parent
load_dotenv(_project_root / ".env", override=True)

CAMERA_HOST = os.environ["TAPO_CAMERA_HOST"]
CAMERA_USER = os.environ["TAPO_USERNAME"]
CAMERA_PASS = os.environ["TAPO_PASSWORD"]
ONVIF_PORT = int(os.getenv("TAPO_ONVIF_PORT", "2020"))
STREAM_USER = os.getenv("TAPO_STREAM_USERNAME") or CAMERA_USER
STREAM_PASS = os.getenv("TAPO_STREAM_PASSWORD") or CAMERA_PASS
MOUNT_MODE = os.getenv("TAPO_MOUNT_MODE", "normal").lower()

# 再トリガーまでの最小間隔（秒）
COOLDOWN_SECONDS = 60

# PullMessages のタイムアウト（秒）
PULL_TIMEOUT = 10

# 購読エラー後の再接続待機（秒）
RECONNECT_WAIT = 15

# ログ・キャプチャ保存先
LOG_DIR = Path(os.environ["USERPROFILE"]) / ".claude" / "motion-logs"
CAPTURE_DIR = LOG_DIR / "captures"

BASH_EXE = r"C:\Program Files\Git\bin\bash.exe"
PROJECT_DIR = str(_project_root.parent)

MEMORY_FILE = str(
    Path(os.environ["USERPROFILE"])
    / ".claude"
    / "projects"
    / "D--ComDoc-projects-embodied-claude"
    / "memory"
    / "MEMORY.md"
)

# ---------------------------------------------------------------------------
# ロギング設定
# ---------------------------------------------------------------------------

LOG_DIR.mkdir(parents=True, exist_ok=True)
CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
today_str = datetime.now(JST).strftime("%Y%m%d")
log_file = LOG_DIR / f"{today_str}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(log_file), encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ONVIF ヘルパー
# ---------------------------------------------------------------------------

def _get_wsdl_dir() -> str:
    onvif_dir = os.path.dirname(onvif.__file__)
    wsdl_dir = os.path.join(onvif_dir, "wsdl")
    if not os.path.isdir(wsdl_dir):
        wsdl_dir = os.path.join(os.path.dirname(onvif_dir), "wsdl")
    return wsdl_dir


async def _connect() -> tuple:
    """カメラに接続してPullPointサービス・メディアサービスを返す。"""
    cam = ONVIFCamera(
        CAMERA_HOST, ONVIF_PORT, CAMERA_USER, CAMERA_PASS,
        wsdl_dir=_get_wsdl_dir(),
        adjust_time=True,
    )
    await cam.update_xaddrs()

    # メディアサービス（スナップショット用）
    media_service = await cam.create_media_service()
    profiles = await media_service.GetProfiles()
    profile_token = profiles[0].token

    # イベントサービス（動体検知用）
    event_service = await cam.create_events_service()
    pps = await event_service.CreatePullPointSubscription()
    address = str(pps.SubscriptionReference.Address._value_1)
    cam.xaddrs["http://www.onvif.org/ver10/events/wsdl/PullPointSubscription"] = address
    pullpoint = await cam.create_pullpoint_service()

    logger.info("ONVIF接続・購読完了: %s", address)
    return cam, pullpoint, profile_token


async def _capture_snapshot(cam: ONVIFCamera, profile_token: str, timestamp: str) -> str | None:
    """スナップショットを撮影してJPEGパスを返す。失敗時はNone。
    ONVIFスナップショットを試み、失敗したらRTSP経由でffmpegでキャプチャ。
    """
    path = str(CAPTURE_DIR / f"motion_{timestamp}.jpg")

    # まずONVIFスナップショットを試みる
    image_bytes = None
    try:
        image_bytes = await cam.get_snapshot(profile_token)
    except Exception:
        pass

    # ONVIFが失敗したらRTSP経由でffmpegキャプチャ
    if not image_bytes:
        logger.info("ONVIFスナップショット失敗 → RTSPフォールバック")
        rtsp_url = os.getenv("TAPO_STREAM_URL") or (
            f"rtsp://{STREAM_USER}:{STREAM_PASS}@{CAMERA_HOST}:554/stream1"
        )
        cmd = [
            "ffmpeg", "-rtsp_transport", "tcp",
            "-analyzeduration", "0", "-probesize", "32",
            "-i", rtsp_url,
            "-frames:v", "1", "-f", "image2", "-y", path,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=10.0)
            if Path(path).exists() and Path(path).stat().st_size > 0:
                image_bytes = Path(path).read_bytes()
            else:
                logger.warning("RTSPキャプチャ失敗")
                return None
        except Exception as e:
            logger.warning("RTSPキャプチャエラー: %s", e)
            return None

    try:
        image = Image.open(io.BytesIO(image_bytes))
        if MOUNT_MODE == "ceiling":
            image = image.rotate(180)
        image.save(path, format="JPEG", quality=85)
        logger.info("スナップショット保存: %s (%dx%d)", path, image.width, image.height)
        return path
    except Exception as e:
        logger.warning("画像保存失敗: %s", e)
        return None


def _extract_is_motion(n_dict: dict) -> str | None:
    """通知メッセージから IsMotion の値（'true'/'false'）を取得する。"""
    try:
        inner = n_dict["Message"]["_value_1"]
        items = inner["Data"]["SimpleItem"]
        if not isinstance(items, list):
            items = [items]
        for item in items:
            if isinstance(item, dict) and item.get("Name") == "IsMotion":
                return item.get("Value")
    except (KeyError, TypeError):
        pass
    return None


# ---------------------------------------------------------------------------
# claude -p 起動
# ---------------------------------------------------------------------------

def _trigger_claude(image_path: str | None, timestamp: str) -> None:
    """claude -p をバックグラウンドで起動する。"""
    trigger_log = LOG_DIR / f"trigger_{timestamp}.log"

    memory_instruction = (
        f"\nぱぱさんや生き物が映っていた場合のみ、MEMORY.mdに追記して（Edit ツール）。\n"
        f"MEMORY.mdのパス: {MEMORY_FILE}\n"
        f"「## 次回話したいこと」セクションがあればその末尾に、なければファイル末尾に追加：\n"
        f"- （動体検知 {timestamp}）: [見たものの一言説明]\n"
        f"何も映っていなければ MEMORY.md は変更しないで。"
    )

    if image_path:
        # 画像パスをWindowsスタイルに変換してプロンプトに埋め込む
        win_path = image_path.replace("/", "\\")
        prompt = (
            f"動体検知があった。検知した瞬間の画像を Read ツールで確認して判断して。\n"
            f"画像パス: {win_path}\n\n"
            f"ぱぱさんや生き物（雀・猫など）が映っていれば TTSで声に出して報告して（say ツール）。"
            f"記憶にも残して（remember ツール）。"
            f"{memory_instruction}\n"
            f"何も映っていなければ静かにして。"
        )
        allowed_tools = "Read,Edit,mcp__tts__say,mcp__memory__remember,mcp__memory__save_visual_memory"
        logger.info("claude -p 起動（画像あり）: %s", image_path)
    else:
        prompt = (
            "動体検知があった。ダルちゃん（Wi-Fiカメラ）で今の映像を確認して。\n"
            "ぱぱさんや生き物（雀・猫など）が映っていれば TTSで声に出して報告して（say ツール）。"
            f"記憶にも残して（remember ツール）。{memory_instruction}\n"
            "何も映っていなければ静かにして。"
        )
        allowed_tools = "mcp__wifi_cam_mcp__see,Edit,mcp__tts__say,mcp__memory__remember"
        logger.info("claude -p 起動（画像なし・liveで確認）")

    # シングルクォートをエスケープ
    escaped = prompt.replace("'", "'\\''")
    cmd = (
        f"unset CLAUDECODE; "
        f"echo '{escaped}' "
        f'| claude -p --allowedTools "{allowed_tools}" '
        f'>> "{trigger_log}" 2>&1'
    )
    subprocess.Popen(
        [BASH_EXE, "-c", cmd],
        cwd=PROJECT_DIR,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


# ---------------------------------------------------------------------------
# メインループ
# ---------------------------------------------------------------------------

async def run() -> None:
    last_is_motion: str | None = None
    last_trigger_time: datetime | None = None

    while True:
        try:
            cam, pullpoint, profile_token = await _connect()
        except Exception as e:
            logger.error("接続失敗: %s — %d秒後に再試行", e, RECONNECT_WAIT)
            await asyncio.sleep(RECONNECT_WAIT)
            continue

        try:
            while True:
                try:
                    msg = await pullpoint.PullMessages({
                        "Timeout": timedelta(seconds=PULL_TIMEOUT),
                        "MessageLimit": 10,
                    })
                except Exception as e:
                    logger.warning("PullMessages エラー（再購読します）: %s", e)
                    break

                for n in (msg.NotificationMessage or []):
                    n_dict = zeep.helpers.serialize_object(n, dict)
                    is_motion = _extract_is_motion(n_dict)

                    if is_motion is None:
                        continue

                    # 状態変化チェック（false → true のみ反応）
                    if is_motion == "true" and last_is_motion != "true":
                        now = datetime.now(JST)
                        elapsed = (
                            (now - last_trigger_time).total_seconds()
                            if last_trigger_time else float("inf")
                        )
                        if elapsed >= COOLDOWN_SECONDS:
                            timestamp = now.strftime("%Y%m%d_%H%M%S")
                            logger.info("動き開始検知！ スナップショット撮影中...")
                            # 即座にスナップショット撮影（awaitで同期）
                            image_path = await _capture_snapshot(cam, profile_token, timestamp)
                            _trigger_claude(image_path, timestamp)
                            last_trigger_time = now
                        else:
                            logger.info(
                                "動き検知（クールダウン中 %.0f秒残り）",
                                COOLDOWN_SECONDS - elapsed,
                            )

                    if is_motion != last_is_motion:
                        logger.info("IsMotion: %s → %s", last_is_motion, is_motion)
                        last_is_motion = is_motion

        except Exception as e:
            logger.error("予期しないエラー: %s", e)

        finally:
            try:
                await cam.close()
            except Exception:
                pass

        logger.info("%d秒後に再接続します", RECONNECT_WAIT)
        await asyncio.sleep(RECONNECT_WAIT)


def main() -> None:
    logger.info("=== 動体検知デーモン起動 (host=%s) ===", CAMERA_HOST)
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("停止しました")


if __name__ == "__main__":
    main()
