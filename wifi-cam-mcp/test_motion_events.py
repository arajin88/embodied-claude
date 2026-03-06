"""ONVIF動体検知イベントの動作確認スクリプト。

使い方:
    cd wifi-cam-mcp
    uv run python test_motion_events.py

動かしながらカメラの前で手を振ってみて、イベントが来るか確認する。
Ctrl+C で停止。
"""

import asyncio
import os
from datetime import timedelta
from pathlib import Path

import onvif
import zeep.helpers
from dotenv import load_dotenv
from onvif import ONVIFCamera

# .env 読み込み
_project_root = Path(__file__).resolve().parent
load_dotenv(_project_root / ".env", override=True)


async def main() -> None:
    host = os.environ["TAPO_CAMERA_HOST"]
    username = os.environ["TAPO_USERNAME"]
    password = os.environ["TAPO_PASSWORD"]
    onvif_port = int(os.getenv("TAPO_ONVIF_PORT", "2020"))

    print(f"接続先: {host}:{onvif_port}")

    # WSDL パス（camera.py と同じ回避策）
    onvif_dir = os.path.dirname(onvif.__file__)
    wsdl_dir = os.path.join(onvif_dir, "wsdl")
    if not os.path.isdir(wsdl_dir):
        wsdl_dir = os.path.join(os.path.dirname(onvif_dir), "wsdl")

    cam = ONVIFCamera(host, onvif_port, username, password, wsdl_dir=wsdl_dir, adjust_time=True)
    await cam.update_xaddrs()
    print("✓ ONVIF接続OK")

    # イベントサービス作成
    event_service = await cam.create_events_service()
    print("✓ イベントサービス作成OK")

    # サポートするイベントプロパティを確認
    try:
        props = await event_service.GetEventProperties()
        props_dict = zeep.helpers.serialize_object(props, dict)
        topic_set = props_dict.get("TopicSet", {})
        print(f"✓ イベントプロパティ取得OK: {list(topic_set.keys()) if topic_set else '不明'}")
    except Exception as e:
        print(f"⚠ イベントプロパティ取得失敗（無視して続行）: {e}")

    # PullPoint購読作成
    print("PullPoint購読を作成中...")
    pps = await event_service.CreatePullPointSubscription()
    address = pps.SubscriptionReference.Address._value_1
    print(f"✓ 購読作成OK: {address}")

    # PullPointのxaddrをセットしてからサービスを作成（managers.pyと同じ方法）
    cam.xaddrs["http://www.onvif.org/ver10/events/wsdl/PullPointSubscription"] = str(address)
    pullpoint = await cam.create_pullpoint_service()

    print("\nイベント待機開始（Ctrl+C で停止）")
    print("カメラの前で手を振ってみてください...\n")

    poll_count = 0
    motion_count = 0

    try:
        while True:
            poll_count += 1
            try:
                msg = await pullpoint.PullMessages({
                    "Timeout": timedelta(seconds=10),
                    "MessageLimit": 10,
                })
            except Exception as e:
                print(f"PullMessages エラー: {e}")
                await asyncio.sleep(2)
                continue

            notifications = msg.NotificationMessage or []
            if notifications:
                for n in notifications:
                    n_dict = zeep.helpers.serialize_object(n, dict)
                    topic = n_dict.get("Topic", {})
                    topic_val = topic.get("_value_1", str(topic)) if isinstance(topic, dict) else str(topic)

                    # IsMotion と PropertyOperation を抽出
                    is_motion = None
                    prop_op = None
                    try:
                        inner = n_dict["Message"]["_value_1"]
                        prop_op = inner.get("PropertyOperation")
                        items = inner["Data"]["SimpleItem"]
                        if not isinstance(items, list):
                            items = [items]
                        for item in items:
                            if isinstance(item, dict) and item.get("Name") == "IsMotion":
                                is_motion = item.get("Value")
                                break
                    except (KeyError, TypeError):
                        pass

                    motion_count += 1
                    # Changed のみを実際の動き変化として扱う
                    marker = "★ 動き変化！" if prop_op == "Changed" else f"({prop_op})"
                    print(f"[Poll#{poll_count}] {marker} IsMotion={is_motion!r}")
            else:
                print(f"[Poll#{poll_count}] イベントなし")

    except KeyboardInterrupt:
        print(f"\n停止。合計 {poll_count} 回ポーリング、{motion_count} 件のイベントを受信。")

    await cam.close()


if __name__ == "__main__":
    asyncio.run(main())
